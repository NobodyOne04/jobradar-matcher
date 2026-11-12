from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from matcher.api.app import MATCHER_VERSION, create_app
from matcher.cli import openapi_yaml
from matcher.config import Settings

TOKEN = "test-token-0123456789"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(token=TOKEN))) as c:  # `with` runs the lifespan
        yield c


def test_health_and_ready_need_no_token(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_not_ready_before_startup() -> None:
    client = TestClient(create_app(Settings(token=TOKEN)))  # no `with`: lifespan not run
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"


def test_version_with_token(client: TestClient) -> None:
    r = client.get("/v1/version", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json() == {"matcher_version": MATCHER_VERSION, "api_versions": ["v1"]}


@pytest.mark.parametrize("auth", [None, "Bearer wrong-token-0123456789", f"Basic {TOKEN}"])
def test_version_rejects_bad_token(client: TestClient, auth: str | None) -> None:
    headers = {"Authorization": auth} if auth else {}
    r = client.get("/v1/version", headers=headers)
    assert r.status_code == 401
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["status"] == 401


def test_unknown_route_is_problem_json(client: TestClient) -> None:
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"


def test_request_id_is_echoed_or_generated(client: TestClient) -> None:
    assert (
        client.get("/healthz", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"]
        == "abc-123"
    )
    # Unsafe or missing IDs are replaced, so nothing odd reaches the logs.
    generated = client.get("/healthz", headers={"X-Request-ID": "bad\tid"}).headers["X-Request-ID"]
    assert generated != "bad\tid"
    assert len(generated) == 36


def test_committed_openapi_matches_code() -> None:
    committed = (Path(__file__).parent.parent / "openapi.yaml").read_text()
    assert committed == openapi_yaml(), (
        "contract changed: run `uv run matcher openapi > openapi.yaml`"
    )
