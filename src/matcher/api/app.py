"""HTTP API: health, readiness, version (jobradar ADR 0004). Matching routes come in Phase 3."""

import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated, Any

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from matcher.config import Settings
from matcher.logs import log

MATCHER_VERSION = version("jobradar-matcher")
API_VERSIONS = ["v1"]
PROBLEM_JSON = "application/problem+json"
# Accept a caller's X-Request-ID only if it is short and plain, so it is safe to log.
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")


class Problem(BaseModel):
    """RFC 9457 problem details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    errors: list[dict[str, Any]] | None = None


class Status(BaseModel):
    status: str


class VersionInfo(BaseModel):
    matcher_version: str
    api_versions: list[str]


def problem(status: int, title: str, detail: str | None = None, **extra: Any) -> JSONResponse:
    body = Problem(title=title, status=status, detail=detail, **extra)
    return JSONResponse(body.model_dump(exclude_none=True), status, media_type=PROBLEM_JSON)


_bearer = HTTPBearer(auto_error=False)


def require_token(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected: str = request.app.state.settings.token
    given = creds.credentials if creds else ""
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "missing or invalid bearer token")


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ready = True  # Phase 3: set once the embedding model and bundles are loaded
        log.info("started", matcher_version=MATCHER_VERSION)
        yield
        app.state.ready = False

    app = FastAPI(title="jobradar-matcher", version=MATCHER_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.ready = False

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        given = request.headers.get("x-request-id", "")
        request_id = given if REQUEST_ID_RE.fullmatch(given) else str(uuid.uuid7())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return problem(exc.status_code, title=str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field paths and messages only: the offending input may be personal data.
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem(422, title="validation error", errors=errors)

    @app.get("/healthz", response_model=Status, tags=["health"])
    async def healthz() -> Status:
        return Status(status="ok")

    @app.get(
        "/readyz",
        response_model=Status,
        responses={503: {"model": Problem}},
        tags=["health"],
    )
    async def readyz(request: Request) -> Status | JSONResponse:
        if not request.app.state.ready:
            return problem(503, title="not ready")
        return Status(status="ready")

    @app.get(
        "/v1/version",
        response_model=VersionInfo,
        responses={401: {"model": Problem}},
        dependencies=[Depends(require_token)],
        tags=["v1"],
    )
    async def v1_version() -> VersionInfo:
        return VersionInfo(matcher_version=MATCHER_VERSION, api_versions=API_VERSIONS)

    return app
