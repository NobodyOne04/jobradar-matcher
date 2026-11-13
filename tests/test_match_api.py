import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from matcher.api.app import create_app
from matcher.config import Settings
from matcher.models import ModelStore
from tests.test_bundle import FakeSource, make

ROOT = Path(__file__).parent.parent
TOKEN = "test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, FakeSource]]:
    make(tmp_path / "registry", "1")
    src = FakeSource(tmp_path / "registry")
    app = create_app(Settings(token=TOKEN), ModelStore(src, tmp_path / "cache"))
    with TestClient(app) as c:
        yield c, src


def body(**over: Any) -> dict[str, Any]:
    real = json.loads((ROOT / "tests/fixtures/job_senior_data_engineer.json").read_text())
    b = {
        "model_version": "1",
        "profile": yaml.safe_load((ROOT / "tests/fixtures/profile_example.yaml").read_text()),
        "jobs": [
            {
                "job_id": "a",
                "title": real["title"],
                "description_text": real["description_text"],
                "remote_policy": "remote",
                "location_text": "Remote: Germany",
            },
            {"job_id": "b", "title": "Dentist", "description_text": "Treat patients."},
            {"job_id": "bad", "title": "", "remote_policy": "sometimes"},
        ],
    }
    b.update(over)
    return b


def test_match(client: tuple[TestClient, FakeSource]) -> None:
    c, _ = client
    r = c.post("/v1/match", json=body(), headers=AUTH)
    assert r.status_code == 200
    out = r.json()
    assert (out["model_version"], len(out["results"])) == ("1", 3)
    a, b, bad = out["results"]
    assert a["job_id"] == "a" and a["band"] in {"strong", "good", "weak"} and a["score"] % 5 == 0
    assert b["job_id"] == "b"
    # One invalid job is an item-level error; the rest of the batch is still scored.
    assert bad["job_id"] == "bad" and bad["error"] == "invalid job"
    assert {tuple(e["loc"]) for e in bad["errors"]} == {("title",), ("remote_policy",)}
    # Same request, same answer (the model version is cached; scoring is deterministic).
    assert c.post("/v1/match", json=body(), headers=AUTH).json() == out


def test_match_errors(client: tuple[TestClient, FakeSource]) -> None:
    c, src = client
    assert c.post("/v1/match", json=body()).status_code == 401
    r = c.post("/v1/match", json=body(model_version="9"), headers=AUTH)
    assert (r.status_code, r.json()["title"]) == (422, "unknown model version")
    assert c.post("/v1/match", json=body(model_version="x"), headers=AUTH).status_code == 422
    assert c.post("/v1/match", json=body(jobs=[]), headers=AUTH).status_code == 422
    assert (
        c.post(
            "/v1/match",
            json=body(jobs=[{"job_id": str(i), "title": "x"} for i in range(51)]),
            headers=AUTH,
        ).status_code
        == 422
    )
    bad_profile = body()
    bad_profile["profile"]["schema_version"] = 2
    assert c.post("/v1/match", json=bad_profile, headers=AUTH).status_code == 422
    src.down = True
    r = c.post("/v1/match", json=body(model_version="2"), headers=AUTH)
    assert (r.status_code, r.headers["content-type"]) == (503, "application/problem+json")


def test_models_listing(client: tuple[TestClient, FakeSource]) -> None:
    c, _ = client
    assert c.get("/v1/models", headers=AUTH).json() == {"models": []}
    c.post("/v1/match", json=body(), headers=AUTH)
    models = c.get("/v1/models", headers=AUTH).json()["models"]
    assert [(m["version"], m["loaded"]) for m in models] == [("1", True)]
    assert "embedding_model" in models[0]["manifest"]


def test_metrics(client: tuple[TestClient, FakeSource]) -> None:
    c, _ = client
    c.post("/v1/match", json=body(), headers=AUTH)
    c.get("/no/such/path/12345")
    assert c.get("/metrics").status_code == 401  # same token as /v1
    text = c.get("/metrics", headers=AUTH).text
    assert 'matcher_requests_total{code="200",route="/v1/match"}' in text
    assert 'matcher_requests_total{code="404",route="unmatched"}' in text
    assert 'matcher_match_duration_seconds_count{model_version="1"}' in text
    assert "12345" not in text  # raw paths never become labels


def test_profile_content_never_logged(
    client: tuple[TestClient, FakeSource], capsys: pytest.CaptureFixture[str]
) -> None:
    c, _ = client
    c.post("/v1/match", json=body(), headers=AUTH)
    c.post("/v1/match", json=body(jobs=[{"job_id": "x", "title": ""}]), headers=AUTH)
    out = capsys.readouterr()
    logs = out.out + out.err
    assert '"matched"' in logs or "matched" in logs  # logging did happen
    for secret in (
        "Example Logistics",
        "Designed and ran the batch platform",
        "90000",
        "Senior data engineer building",
    ):
        assert secret not in logs, f"profile content in logs: {secret}"
