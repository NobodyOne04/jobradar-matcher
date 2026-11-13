"""HTTP API (jobradar ADR 0004): health, readiness, version, model versions, and /v1/match."""

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
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException

from matcher.bundle import BundleError
from matcher.config import Settings
from matcher.embed import Embedder
from matcher.embed import manifest as embedding_manifest
from matcher.logs import log
from matcher.models import ModelStore, Unavailable, UnknownVersion
from matcher.schemas import Job, Profile
from matcher.score import MatchResult, score

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


MAX_BATCH = 50


class MatchJob(Job):
    """A normalized job with the backend's id for it."""

    job_id: str = Field(min_length=1, max_length=100)
    content_hash: str | None = Field(default=None, max_length=128)


class MatchRequest(BaseModel):
    model_version: str = Field(
        pattern=r"^[0-9]{1,9}$", description="the MLflow model version to use"
    )
    profile: Profile
    jobs: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=MAX_BATCH,
        description="MatchJob objects; each is validated on its own, see JobError",
    )


class MatchItem(MatchResult):
    job_id: str


class JobError(BaseModel):
    """One job that could not be scored; the others in the batch still are."""

    job_id: str | None
    error: str
    errors: list[dict[str, Any]]


class MatchResponse(BaseModel):
    model_version: str
    matcher_version: str
    results: list[MatchItem | JobError]


class ModelListing(BaseModel):
    models: list[dict[str, Any]]


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


def create_app(settings: Settings, store: ModelStore | None = None) -> FastAPI:
    """store defaults to MLflow at settings.mlflow_uri (or the cache alone without one)."""
    if store is None:
        from matcher.registry import MLflowRegistry

        source = MLflowRegistry(settings.mlflow_uri) if settings.mlflow_uri else None
        store = ModelStore(source, settings.cache_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.embedding_dir is not None:
            # Ready only with the model: without it, responsibilities would silently be unknown.
            app.state.embedder = Embedder(settings.embedding_dir, embedding_manifest())
        app.state.ready = True
        log.info(
            "started",
            matcher_version=MATCHER_VERSION,
            embedding_model=settings.embedding_dir is not None,
            mlflow=settings.mlflow_uri is not None,
        )
        yield
        app.state.ready = False

    app = FastAPI(title="jobradar-matcher", version=MATCHER_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.ready = False
    app.state.embedder = None
    app.state.store = store

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

    @app.get(
        "/v1/models",
        response_model=ModelListing,
        responses={401: {"model": Problem}},
        dependencies=[Depends(require_token)],
        tags=["v1"],
    )
    def v1_models(request: Request) -> ModelListing:
        return ModelListing(models=request.app.state.store.listing())

    @app.post(
        "/v1/match",
        response_model=MatchResponse,
        responses={401: {"model": Problem}, 422: {"model": Problem}, 503: {"model": Problem}},
        dependencies=[Depends(require_token)],
        tags=["v1"],
    )
    def v1_match(body: MatchRequest, request: Request) -> MatchResponse | JSONResponse:
        # A plain def: FastAPI runs it in a thread, so CPU-bound scoring never blocks the loop.
        start = time.perf_counter()
        try:
            model = request.app.state.store.get(body.model_version)
        except UnknownVersion:
            return problem(422, title="unknown model version", detail=body.model_version)
        except BundleError as e:
            return problem(422, title="model version unusable here", detail=str(e))
        except Unavailable:
            return problem(503, title="model registry unavailable", detail="retry later")
        results: list[MatchItem | JobError] = []
        for raw in body.jobs:
            try:
                job = MatchJob.model_validate(raw)
            except ValidationError as e:
                job_id = raw.get("job_id") if isinstance(raw.get("job_id"), str) else None
                errors = [
                    {"loc": list(x["loc"]), "msg": x["msg"], "type": x["type"]} for x in e.errors()
                ]
                results.append(JobError(job_id=job_id, error="invalid job", errors=errors))
                continue
            r = score(body.profile, job, model.taxonomy, model.config, request.app.state.embedder)
            results.append(MatchItem(job_id=job.job_id, **r.model_dump()))
        log.info(
            "matched",
            model_version=body.model_version,
            jobs=len(body.jobs),
            errors=sum(isinstance(r, JobError) for r in results),
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return MatchResponse(
            model_version=body.model_version, matcher_version=MATCHER_VERSION, results=results
        )

    return app
