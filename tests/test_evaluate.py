import json
from pathlib import Path

import pytest
import yaml

from matcher.evaluate import (
    EvalJob,
    Grade,
    SkillLabels,
    append_jsonl,
    check,
    ndcg_at,
    read_jsonl,
    run,
)
from matcher.evaluate.interactive import grade_session, skills_session
from matcher.schemas import Job, Profile
from matcher.score.config import load as load_config
from matcher.taxonomy import Taxonomy, load

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load(ROOT / "data/skills.yaml")


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    real = json.loads((ROOT / "tests/fixtures/job_senior_data_engineer.json").read_text())
    jobs = [
        EvalJob(
            job_id="real",
            job=Job(
                title=real["title"],
                description_text=real["description_text"],
                remote_policy="remote",
                location_text="Remote: Germany",
            ),
        ),
        EvalJob(
            job_id="onsite",
            job=Job(
                title="Senior Data Engineer",
                location_text="Berlin office",
                description_text="Requirements:\nPython, SQL, Airflow, dbt",
                remote_policy="onsite",
            ),
        ),
        EvalJob(job_id="dentist", job=Job(title="Dentist", description_text="Treat patients.")),
    ]
    for j in jobs:
        append_jsonl(tmp_path / "jobs.jsonl", j)
    (tmp_path / "VERSION").write_text("1\n")
    return tmp_path


def profile(**prefs: object) -> Profile:
    data = yaml.safe_load((ROOT / "tests/fixtures/profile_example.yaml").read_text())
    data["preferences"].update(prefs)
    return Profile.model_validate(data)


def test_ndcg() -> None:
    assert ndcg_at([3, 2, 0], 10) == 1.0
    assert ndcg_at([0, 3], 10) == pytest.approx(7 / 1.584962500721156 / 7)  # 3 ranked second
    assert ndcg_at([0, 0], 10) == 0.0


def test_run_end_to_end(eval_dir: Path, tax: Taxonomy) -> None:
    for job_id, grade in (("real", 2), ("onsite", 3), ("dentist", 0)):
        append_jsonl(eval_dir / "grades.jsonl", Grade(job_id=job_id, grade=grade))
    append_jsonl(
        eval_dir / "skills.jsonl",
        SkillLabels(
            job_id="onsite",
            skills={
                "python": "required",
                "sql": "required",
                "airflow": "required",
                "kafka": "required",
            },
        ),
    )
    # remote_only as a hard constraint excludes "onsite", which you graded 3: a false fail.
    p = profile(remote_only=True, hard_constraints=["remote_only"])
    result = run(eval_dir, p, tax, load_config(ROOT / "defaults/scoring.yaml"), None)
    m = result["metrics"]
    assert isinstance(m, dict)
    assert result["dataset_version"] == "1"
    assert m["false_fails"] == 1.0
    assert m["graded_jobs"] == 3.0
    # Extracted python, sql, airflow, dbt vs labelled python, sql, airflow, kafka.
    assert (m["skill_precision"], m["skill_recall"], m["required_accuracy"]) == (0.75, 0.75, 1.0)
    assert 0 <= m["ndcg_at_10"] <= 1 and m["latency_p95_ms"] >= m["latency_p50_ms"]


def test_run_needs_data(eval_dir: Path, tax: Taxonomy) -> None:
    with pytest.raises(ValueError, match="grade some jobs first"):
        run(eval_dir, profile(), tax, load_config(ROOT / "defaults/scoring.yaml"), None)


def metrics(version: str = "1", **m: float) -> dict[str, object]:
    return {"dataset_version": version, "metrics": m}


def test_check() -> None:
    base = metrics(ndcg_at_10=0.80, latency_p95_ms=20, false_fails=0)
    tol = {"ndcg_at_10": 0.02, "latency_p95_ms": 50}
    assert check(metrics(ndcg_at_10=0.79, latency_p95_ms=60, false_fails=0), base, tol) == []
    assert len(check(metrics(ndcg_at_10=0.70, false_fails=0), base, tol)) == 1  # ranking worse
    assert len(check(metrics(ndcg_at_10=0.80, latency_p95_ms=90), base, tol)) == 1  # slower
    assert "false_fails" in check(metrics(ndcg_at_10=0.90, false_fails=1), base, tol)[0]
    assert "dataset version" in check(metrics("2", ndcg_at_10=0.9), base, tol)[0]


def scripted(answers: list[str]) -> tuple[list[str], object, object]:
    shown: list[str] = []
    it = iter(answers)
    return shown, (lambda _prompt: next(it)), shown.append


def test_grade_session_saves_each_answer_and_resumes(eval_dir: Path) -> None:
    shown, ask, show = scripted(["m", "x", "2", "q"])
    assert grade_session(eval_dir, ask, show) == 1  # type: ignore[arg-type]
    assert any("please answer" in s for s in shown)
    assert [g.grade for g in read_jsonl(eval_dir / "grades.jsonl", Grade)] == [2]

    shown, ask, show = scripted(["s", "0"])
    assert grade_session(eval_dir, ask, show) == 1  # type: ignore[arg-type]
    grades = read_jsonl(eval_dir / "grades.jsonl", Grade)
    assert [(g.job_id, g.grade) for g in grades] == [("real", 2), ("dentist", 0)]  # onsite skipped
    assert "=== 2/3 ===" in shown[0]  # resumed after the graded one


def test_skills_session_records_corrections(eval_dir: Path, tax: Taxonomy) -> None:
    # real: accept as shown; onsite: drop dbt, add kafka as preferred, make sql preferred.
    shown, ask, show = scripted(["", "-dbt +kafka? ~sql +nope", "", "q"])
    assert skills_session(eval_dir, tax, ask, show) == 2  # type: ignore[arg-type]
    labels = {s.job_id: s.skills for s in read_jsonl(eval_dir / "skills.jsonl", SkillLabels)}
    assert labels["onsite"] == {
        "python": "required",
        "sql": "preferred",
        "airflow": "required",
        "kafka": "preferred",
    }
    assert any("unknown command or skill id: +nope" in s for s in shown)


def test_bad_lines_name_the_file_and_line(tmp_path: Path) -> None:
    (tmp_path / "grades.jsonl").write_text(
        '{"job_id": "a", "grade": 2}\n{"job_id": "b", "grade": 9}\n'
    )
    with pytest.raises(ValueError, match=r"grades.jsonl:2"):
        read_jsonl(tmp_path / "grades.jsonl", Grade)
