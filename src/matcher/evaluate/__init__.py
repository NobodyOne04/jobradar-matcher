"""The evaluation set and its metrics (matcher ADR 0003).

eval/ holds: VERSION, jobs.jsonl ({"job_id", "job"}), grades.jsonl ({"job_id", "grade": 0-3}),
skills.jsonl ({"job_id", "skills": {skill_id: "required"|"preferred"}}), tolerances.yaml,
baseline.json. Your real profile is not committed; the eval profile is passed in.
"""

import math
import statistics
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from matcher.embed import Embedder
from matcher.extract import extract
from matcher.schemas import Job, Profile
from matcher.score import score
from matcher.score.config import ScoringConfig
from matcher.taxonomy import Taxonomy

Requirement = Literal["required", "preferred"]


class EvalJob(BaseModel):
    job_id: str
    job: Job


class Grade(BaseModel):
    job_id: str
    grade: int = Field(ge=0, le=3)  # 0 no fit, 1 weak, 2 good, 3 strong


class SkillLabels(BaseModel):
    job_id: str
    skills: dict[str, Requirement]


def read_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(model.model_validate_json(line))
            except ValueError as e:
                raise ValueError(f"{path}:{n}: {e}") from e
    return rows


def write_jsonl(path: Path, rows: list[BaseModel]) -> None:
    """Replace the file whole, through a temporary file, so an interrupted write loses nothing."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, row: BaseModel) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(row.model_dump_json() + "\n")


# --- Metrics --------------------------------------------------------------------------------


def ndcg_at(grades_in_rank_order: list[int], k: int) -> float:
    """Normalized discounted cumulative gain of the top k, with gain 2^grade - 1."""

    def dcg(gs: Iterable[int]) -> float:
        return sum(float(2**g - 1) / math.log2(i + 2) for i, g in enumerate(gs))

    ideal = dcg(sorted(grades_in_rank_order, reverse=True)[:k])
    return dcg(grades_in_rank_order[:k]) / ideal if ideal else 0.0


def _ratio(a: int, b: int) -> float:
    return round(a / b, 4) if b else 0.0


def skill_metrics(
    jobs: dict[str, Job], labels: list[SkillLabels], tax: Taxonomy
) -> dict[str, float]:
    """Micro precision and recall of extracted skills against the hand labels, per category
    too, and how often required/preferred agrees on correctly found skills."""
    tp = fp = fn = agree = 0
    per_cat: dict[str, list[int]] = {}  # category -> [tp, fp, fn]
    for lab in labels:
        job = jobs[lab.job_id]
        got = {s.id: s.requirement for s in extract(job.title, job.description_text, tax).skills}
        for sid in got.keys() | lab.skills.keys():
            counts = per_cat.setdefault(
                tax.skills[sid].category if sid in tax.skills else "?", [0, 0, 0]
            )
            if sid in got and sid in lab.skills:
                tp += 1
                counts[0] += 1
                agree += got[sid] == lab.skills[sid]
            elif sid in got:
                fp += 1
                counts[1] += 1
            else:
                fn += 1
                counts[2] += 1
    out = {
        "skill_precision": _ratio(tp, tp + fp),
        "skill_recall": _ratio(tp, tp + fn),
        "required_accuracy": _ratio(agree, tp),
        "skill_labelled_jobs": float(len(labels)),
    }
    for cat, (ctp, cfp, cfn) in sorted(per_cat.items()):
        out[f"skill_recall.{cat}"] = _ratio(ctp, ctp + cfn)
        out[f"skill_precision.{cat}"] = _ratio(ctp, ctp + cfp)
    return out


def ranking_metrics(
    profile: Profile,
    jobs: dict[str, Job],
    grades: list[Grade],
    tax: Taxonomy,
    cfg: ScoringConfig,
    embedder: Embedder | None,
) -> dict[str, float]:
    """Score every graded job and compare the ranking with your grades."""
    rows, latencies = [], []
    for g in grades:
        start = time.perf_counter()
        r = score(profile, jobs[g.job_id], tax, cfg, embedder)
        latencies.append((time.perf_counter() - start) * 1000)
        rows.append((r.band == "excluded", -r.score, g.job_id, g.grade, r))
    rows.sort(key=lambda row: row[:3])  # excluded last, then by score, then by id (stable)
    ranked = [row[3] for row in rows]
    results = [row[4] for row in rows]
    good = [row for row in rows if row[3] >= 2]
    return {
        "ndcg_at_10": round(ndcg_at(ranked, 10), 4),
        "precision_at_10": _ratio(sum(g >= 2 for g in ranked[:10]), min(10, len(ranked))),
        "false_fails": float(sum(1 for row in good if row[4].hard_constraints == "fail")),
        "low_confidence_share": _ratio(sum(r.confidence == "low" for r in results), len(results)),
        "latency_p50_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "latency_p95_ms": round(_p95(latencies), 2),
        "graded_jobs": float(len(grades)),
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)]


def run(
    eval_dir: Path, profile: Profile, tax: Taxonomy, cfg: ScoringConfig, embedder: Embedder | None
) -> dict[str, Any]:
    jobs = {j.job_id: j.job for j in read_jsonl(eval_dir / "jobs.jsonl", EvalJob)}
    grades = [g for g in read_jsonl(eval_dir / "grades.jsonl", Grade) if g.job_id in jobs]
    labels = [s for s in read_jsonl(eval_dir / "skills.jsonl", SkillLabels) if s.job_id in jobs]
    if not grades and not labels:
        raise ValueError(f"nothing to evaluate in {eval_dir}: grade some jobs first")
    metrics: dict[str, float] = {}
    if labels:
        metrics |= skill_metrics(jobs, labels, tax)
    if grades:
        metrics |= ranking_metrics(profile, jobs, grades, tax, cfg, embedder)
    return {"dataset_version": (eval_dir / "VERSION").read_text().strip(), "metrics": metrics}


# --- Gate -----------------------------------------------------------------------------------

LOWER_IS_BETTER = {"low_confidence_share", "latency_p50_ms", "latency_p95_ms", "false_fails"}


def check(
    current: dict[str, Any], baseline: dict[str, Any], tolerances: dict[str, float]
) -> list[str]:
    """Problems that fail the gate: any false fail, a different dataset version, or a metric
    worse than baseline beyond its tolerance. Metrics without a tolerance are informational."""
    problems = []
    cur: dict[str, float] = current["metrics"]
    base: dict[str, float] = baseline["metrics"]
    if cur.get("false_fails", 0) > 0:
        problems.append(
            f"false_fails = {cur['false_fails']:g}: a job you graded good or strong was excluded"
        )
    if current["dataset_version"] != baseline["dataset_version"]:
        problems.append(
            f"dataset version {current['dataset_version']} != baseline "
            f"{baseline['dataset_version']}: metrics are only comparable within one version; "
            "commit a new baseline"
        )
        return problems
    for name, tol in sorted(tolerances.items()):
        if name not in cur or name not in base:
            continue
        worse = cur[name] - base[name] if name in LOWER_IS_BETTER else base[name] - cur[name]
        if worse > tol + 1e-9:
            problems.append(f"{name}: {cur[name]:g} vs baseline {base[name]:g} (tolerance {tol:g})")
    return problems


def ungraded(jobs: list[EvalJob], done: set[str]) -> Iterator[EvalJob]:
    return (j for j in jobs if j.job_id not in done)
