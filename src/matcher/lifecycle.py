"""`matcher train` and `matcher promote` (matcher ADR 0004).

train: build a bundle (from the committed defaults, or from a parent version with files
replaced), run the eval set on it when one exists, log the run and register a version.
promote: move `champion` to a version, refused if its eval metrics regressed against the
current champion's (ADR 0003 gate) unless forced. A rollback is a promote of an older version.

shortcut: training on application labels (logistic regression on dimension scores) is not
here yet; it needs the backend's label export (jobradar ADR 0008). Add `--labels` then.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from matcher import bundle
from matcher.embed import Embedder
from matcher.evaluate import check, run
from matcher.registry import MLflowRegistry
from matcher.schemas import Profile

DEFAULT_TAXONOMY = Path("data/skills.yaml")
DEFAULT_CONFIG = Path("defaults/scoring.yaml")
# The eval set files a run snapshots, so a version stays tied to the exact data it was measured
# on after eval/ moves on. The profile is personal: only its checksum is logged.
EVAL_FILES = ("VERSION", "jobs.jsonl", "grades.jsonl", "skills.jsonl", "tolerances.yaml")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    """The matcher commit: MATCHER_GIT_COMMIT (set in the image), else the checkout's HEAD."""
    if commit := os.environ.get("MATCHER_GIT_COMMIT"):
        return commit
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        out = subprocess.run(  # noqa: S603  fixed arguments, no input
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
        )
        return out.stdout.strip()
    except OSError, subprocess.SubprocessError:
        return "unknown"


def snapshot_eval(eval_dir: Path, profile: Path, report: dict[str, Any], dest: Path) -> str:
    """Copy the eval set and the report into dest with a checksum manifest; returns the
    dataset checksum (over the data files, not the report)."""
    dest.mkdir()
    files = []
    for name in EVAL_FILES:
        if (eval_dir / name).is_file():
            shutil.copyfile(eval_dir / name, dest / name)
            files.append({"name": name, "sha256": _sha256(dest / name)})
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    manifest = {
        "dataset_version": report["dataset_version"],
        "dataset_sha256": digest,
        "files": files,
        "profile_sha256": _sha256(profile),
    }
    (dest / "dataset.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (dest / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return digest


@dataclass
class Trained:
    version: str
    metrics: dict[str, float]
    dataset_version: str | None


def train(
    reg: MLflowRegistry,
    parent: str | None,
    taxonomy: Path | None,
    config: Path | None,
    eval_dir: Path,
    eval_profile: Path,
    embedder: Embedder | None,
) -> Trained:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        if parent is not None:
            reg.download(parent, tmp / "parent")
            taxonomy = taxonomy or tmp / "parent/taxonomy.yaml"
            config = config or tmp / "parent/scoring.yaml"
        new = tmp / "bundle"
        bundle.build(new, taxonomy or DEFAULT_TAXONOMY, config or DEFAULT_CONFIG, parent)
        b = bundle.load(new)

        metrics: dict[str, float] = {}
        dataset_version = None
        digest = ""
        has_eval = (eval_dir / "grades.jsonl").exists() or (eval_dir / "skills.jsonl").exists()
        if has_eval and eval_profile.is_file():
            profile = Profile.model_validate(
                yaml.safe_load(eval_profile.read_text(encoding="utf-8"))
            )
            result = run(eval_dir, profile, b.taxonomy, b.config, embedder)
            metrics = dict(result["metrics"])
            dataset_version = str(result["dataset_version"])
            digest = snapshot_eval(eval_dir, eval_profile, result, tmp / "eval")

        tags = {
            "parent": parent or "",
            "source": "defaults" if parent is None else "derived",
            "git_commit": git_commit(),
        }
        emb = b.manifest.embedding_model
        if dataset_version:
            tags["eval_dataset_version"] = dataset_version
            tags["eval_dataset_sha256"] = digest
        params = {
            "parent": parent or "none",
            "matcher_version": bundle.MATCHER_VERSION,
            "embedding_model": f"{emb.model}@{emb.revision}",
            "seed": str(b.manifest.seed),
        }
        extra = {"eval": tmp / "eval"} if dataset_version else {}
        version = reg.register(new, params, metrics, tags, extra)
    return Trained(version=version, metrics=metrics, dataset_version=dataset_version)


def promote_problems(reg: MLflowRegistry, version: str, tolerances: dict[str, float]) -> list[str]:
    """Why promoting `version` over the current champion would be a regression ([] if not)."""
    champion = reg.champion()
    if champion is None or champion == version:
        return []
    cur: dict[str, Any] = {
        "dataset_version": reg.dataset_version(version),
        "metrics": reg.metrics(version),
    }
    base: dict[str, Any] = {
        "dataset_version": reg.dataset_version(champion),
        "metrics": reg.metrics(champion),
    }
    if not cur["metrics"] or not base["metrics"]:
        return [f"no eval metrics to compare version {version} with champion {champion}"]
    return check(cur, base, tolerances)


def promote(
    reg: MLflowRegistry, version: str, reason: str, force: bool, tolerances: dict[str, float]
) -> tuple[str, list[str]]:
    """Returns the gate tag ("first", "passed" or "forced") and the problems found. Nothing
    changes when there are problems and force is not set."""
    first = reg.champion() is None
    problems = promote_problems(reg, version, tolerances)
    if problems and not force:
        return "refused", problems
    gate = "first" if first else ("forced" if problems else "passed")
    reg.promote(version, reason, gate)
    return gate, problems
