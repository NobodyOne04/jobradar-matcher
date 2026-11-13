"""train / promote / rollback / download against a real MLflow 3.18 server (Docker)."""

import json
import shutil
import socket
import subprocess
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from matcher import lifecycle
from matcher.models import ModelStore
from matcher.registry import MLflowRegistry

ROOT = Path(__file__).parent.parent
IMAGE = "ghcr.io/mlflow/mlflow:v3.18.0"


def _docker_ok() -> bool:
    return (
        shutil.which("docker") is not None
        and subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
    )


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="needs Docker for an MLflow server")


@pytest.fixture(scope="module")
def registry() -> Iterator[MLflowRegistry]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    name = f"matcher-test-mlflow-{port}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-p",
            f"127.0.0.1:{port}:5000",
            IMAGE,
            "mlflow",
            "server",
            "--host",
            "0.0.0.0",
            "--port",
            "5000",
            "--backend-store-uri",
            "sqlite:////tmp/mlflow.db",
            "--serve-artifacts",
            "--artifacts-destination",
            "/tmp/artifacts",
            "--allowed-hosts",
            f"127.0.0.1:{port}",
        ],
        check=True,
        capture_output=True,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except OSError:
                time.sleep(1)
        yield MLflowRegistry(f"http://127.0.0.1:{port}")
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True, check=False)


def test_train_promote_rollback(registry: MLflowRegistry, tmp_path: Path) -> None:
    no_eval = tmp_path / "eval"  # no eval set yet: versions carry no metrics
    v1 = lifecycle.train(registry, None, None, None, no_eval, no_eval / "profile.yaml", None)
    assert (v1.version, v1.metrics) == ("1", {})
    assert lifecycle.promote(registry, "1", "first model", False, {}) == ("first", [])
    assert registry.champion() == "1"

    # A derived version with a changed config.
    cfg = yaml.safe_load((ROOT / "defaults/scoring.yaml").read_text())
    cfg["bands"]["strong"] = 80
    (tmp_path / "scoring.yaml").write_text(yaml.safe_dump(cfg))
    v2 = lifecycle.train(
        registry, "1", None, tmp_path / "scoring.yaml", no_eval, no_eval / "profile.yaml", None
    )
    assert v2.version == "2"

    # Without metrics the gate cannot compare: refused unless forced.
    gate, problems = lifecycle.promote(registry, "2", "stricter bands", False, {"ndcg_at_10": 0.02})
    assert gate == "refused" and "no eval metrics" in problems[0]
    assert registry.champion() == "1"
    assert lifecycle.promote(registry, "2", "stricter bands", True, {})[0] == "forced"
    assert registry.champion() == "2"

    # Rollback is a promote of the older version.
    lifecycle.promote(registry, "1", "v2 too strict", True, {})
    assert registry.champion() == "1"
    tags = registry.client.get_model_version("jobradar-matcher", "1").tags
    assert tags["promoted_reason"] == "v2 too strict"
    listing = {v["version"]: v for v in registry.versions()}
    assert listing["1"]["champion"] and listing["2"]["parent"] == "1"

    # The server side: download, verify and load each version; v2 has the changed config.
    store = ModelStore(registry, tmp_path / "cache")
    assert store.get("1").config.bands.strong == 75
    assert store.get("2").config.bands.strong == 80
    assert store.get("2").manifest.parent == "1"


def test_versions_with_eval_metrics_pass_the_gate(registry: MLflowRegistry, tmp_path: Path) -> None:
    from matcher.evaluate import Grade, append_jsonl

    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    j = json.loads((ROOT / "tests/fixtures/job_senior_data_engineer.json").read_text())
    (eval_dir / "jobs.jsonl").write_text(
        json.dumps(
            {"job_id": "a", "job": {"title": j["title"], "description_text": j["description_text"]}}
        )
        + "\n"
    )
    (eval_dir / "VERSION").write_text("1\n")
    append_jsonl(eval_dir / "grades.jsonl", Grade(job_id="a", grade=2))
    profile = ROOT / "tests/fixtures/profile_example.yaml"

    a = lifecycle.train(registry, None, None, None, eval_dir, profile, None)
    b = lifecycle.train(registry, None, None, None, eval_dir, profile, None)
    quality = {k: v for k, v in a.metrics.items() if not k.startswith("latency")}
    assert quality and quality == {
        k: v for k, v in b.metrics.items() if not k.startswith("latency")
    }
    assert a.dataset_version == "1"
    lifecycle.promote(registry, a.version, "measured", True, {})
    tolerances = yaml.safe_load((ROOT / "eval/tolerances.yaml").read_text())
    # Equal metrics: the gate passes without --force.
    assert lifecycle.promote(registry, b.version, "same quality", False, tolerances) == (
        "passed",
        [],
    )

    # The version is tied to its data: the eval set and report are run artifacts with
    # checksums, the profile only as a checksum, and the tags name dataset and commit.
    mv = registry.client.get_model_version("jobradar-matcher", a.version)
    assert mv.tags["eval_dataset_version"] == "1" and mv.tags["git_commit"]
    got = Path(
        registry._mlflow.artifacts.download_artifacts(
            run_id=mv.run_id, artifact_path="eval", dst_path=str(tmp_path / "dl")
        )
    )
    manifest = json.loads((got / "dataset.json").read_text())
    assert manifest["dataset_sha256"] == mv.tags["eval_dataset_sha256"]
    assert {f["name"] for f in manifest["files"]} == {"VERSION", "jobs.jsonl", "grades.jsonl"}
    assert (got / "jobs.jsonl").read_bytes() == (eval_dir / "jobs.jsonl").read_bytes()
    assert json.loads((got / "report.json").read_text())["metrics"] == a.metrics
    assert not (got / "profile.yaml").exists()
