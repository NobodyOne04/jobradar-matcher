import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from matcher.schemas import Job, Profile
from matcher.score import MatchResult, score
from matcher.score.config import ScoringConfig
from matcher.score.config import load as load_config
from matcher.taxonomy import Taxonomy, load

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load(ROOT / "data/skills.yaml")


@pytest.fixture(scope="module")
def cfg() -> ScoringConfig:
    return load_config(ROOT / "defaults/scoring.yaml")


def profile(**prefs: Any) -> Profile:
    """The fictional example profile, with preferences replaced by `prefs` when given."""
    data = yaml.safe_load((ROOT / "tests/fixtures/profile_example.yaml").read_text())
    if prefs:
        data["preferences"] = prefs
    return Profile.model_validate(data)


def run(tax: Taxonomy, cfg: ScoringConfig, p: Profile, **job: Any) -> MatchResult:
    job.setdefault("title", "Senior Data Engineer")
    return score(p, Job(**job), tax, cfg)


def dim(r: MatchResult, name: str) -> float | None:
    return next(d.score for d in r.dimensions if d.name == name)


def test_skills_matched_transferable_missing(tax: Taxonomy, cfg: ScoringConfig) -> None:
    r = run(
        tax,
        cfg,
        profile(),
        description_text="Requirements:\nPython, Dagster and Flink.\nNice to have: Rust",
    )
    s = r.skills
    assert {x.id for x in s.matched} == {"python", "flink"}
    assert [(x.id, x.via) for x in s.transferable] == [("dagster", "Apache Airflow")]
    assert {x.id for x in s.missing} == {"rust"}
    # required: python 1 + flink 1 + dagster 0.5 of 3; preferred rust 0 of 0.5 -> 2.5 / 3.5
    assert dim(r, "skills") == round(2.5 / 3.5, 2)


def test_unknown_is_not_a_mismatch(tax: Taxonomy, cfg: ScoringConfig) -> None:
    p = profile(
        remote_only=True,
        salary={"min": 90000, "currency": "EUR", "period": "year"},
        hard_constraints=["remote_only", "salary"],
    )
    r = run(tax, cfg, p, description_text="We use Python.")  # no remote, salary, level info
    assert r.hard_constraints == "unknown"
    assert r.band != "excluded"
    assert {g.result for g in r.gates} == {"unknown"}
    assert r.completeness < 1 and r.confidence != "high"


def test_failed_gate_excludes_whatever_the_score(tax: Taxonomy, cfg: ScoringConfig) -> None:
    p = profile(remote_only=True, hard_constraints=["remote_only"])
    r = run(
        tax, cfg, p, description_text="Python, SQL, Airflow, dbt", location_text="Berlin (hybrid)"
    )
    assert r.hard_constraints == "fail"
    assert r.band == "excluded"
    assert r.explanations[0].startswith("Hard constraint remote_only failed")


@pytest.mark.parametrize(
    ("job", "want_score", "want_gate"),
    [
        (
            {
                "salary_min": 95000,
                "salary_max": 110000,
                "salary_currency": "EUR",
                "salary_period": "year",
            },
            1.0,
            "pass",
        ),
        (
            {"salary_max": 85000, "salary_currency": "EUR", "salary_period": "year"},
            0.5,
            "pass",
        ),  # near miss
        ({"salary_max": 60000, "salary_currency": "EUR", "salary_period": "year"}, 0.0, "fail"),
        (
            {"salary_max": 120000, "salary_currency": "USD", "salary_period": "year"},
            1.0,
            "pass",
        ),  # 110k EUR
        (
            {"salary_max": 8000, "salary_currency": "EUR", "salary_period": "month"},
            1.0,
            "pass",
        ),  # 96k/year
        ({"description_text": "Salary: €70-80k per year"}, 0.0, "fail"),  # from the text
        ({}, None, "unknown"),
    ],
)
def test_compensation(
    tax: Taxonomy, cfg: ScoringConfig, job: dict[str, Any], want_score: float | None, want_gate: str
) -> None:
    p = profile(
        salary={"min": 90000, "currency": "EUR", "period": "year"}, hard_constraints=["salary"]
    )
    r = run(tax, cfg, p, **job)
    assert dim(r, "compensation") == want_score
    assert r.gates[0].result == want_gate


@pytest.mark.parametrize(
    ("job", "want"),
    [
        ({"location_text": "Remote: Germany, Spain"}, "pass"),
        ({"location_text": "Remote: worldwide"}, "pass"),
        ({"description_text": "Fully remote within Europe."}, "pass"),
        ({"countries": ["US"], "location_text": "Remote - US"}, "fail"),
        ({"location_text": "Remote, United States"}, "fail"),
        ({"location_text": "Remote"}, "unknown"),
        ({"location_text": "Work with us remotely"}, "unknown"),  # "us" is not the US
    ],
)
def test_locations(tax: Taxonomy, cfg: ScoringConfig, job: dict[str, Any], want: str) -> None:
    p = profile(locations=["Germany"], hard_constraints=["locations"])
    assert run(tax, cfg, p, **job).gates[0].result == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Overlap with CET required", "pass"),
        ("Working hours UTC-8 to UTC-5", "fail"),
        ("", "unknown"),
    ],
)
def test_timezones(tax: Taxonomy, cfg: ScoringConfig, text: str, want: str) -> None:
    p = profile(
        timezones={"min_utc_offset": -1, "max_utc_offset": 3}, hard_constraints=["timezones"]
    )
    assert run(tax, cfg, p, description_text=text).gates[0].result == want


def test_seniority(tax: Taxonomy, cfg: ScoringConfig) -> None:
    p = profile()  # senior, 8 years
    assert dim(run(tax, cfg, p, title="Senior Data Engineer"), "seniority") == 1.0
    assert dim(run(tax, cfg, p, title="Principal Data Engineer"), "seniority") == 0.1
    assert (
        dim(
            run(tax, cfg, p, title="Data Engineer", description_text="10+ years of experience"),
            "seniority",
        )
        == 0.4
    )
    assert dim(run(tax, cfg, p, title="Data Engineer"), "seniority") is None


def test_employment_type(tax: Taxonomy, cfg: ScoringConfig) -> None:
    p = profile(employment_types=["full_time"], hard_constraints=["employment_types"])
    assert run(tax, cfg, p, employment_type="full_time").gates[0].result == "pass"
    assert run(tax, cfg, p, employment_type="internship").gates[0].result == "fail"
    assert run(tax, cfg, p).gates[0].result == "unknown"


def test_score_is_a_banded_multiple_of_five(tax: Taxonomy, cfg: ScoringConfig) -> None:
    for title in ("Senior Data Engineer", "Junior Analyst", "Staff Engineer"):
        r = run(tax, cfg, profile(), title=title, description_text="Python, SQL, Kafka, Java, Rust")
        assert r.score % 5 == 0 and 0 <= r.score <= 100
        assert r.band == ("strong" if r.score >= 75 else "good" if r.score >= 55 else "weak")


def test_no_known_skills_is_a_mismatch(tax: Taxonomy, cfg: ScoringConfig) -> None:
    # ADR 0005: a posting naming no taxonomy skill scores 0 on skills, not unknown.
    r = run(tax, cfg, profile(), title="Account Executive", description_text="Close deals.")
    assert dim(r, "skills") == 0 and r.score == 0 and r.band == "weak"
    assert r.confidence == "low" and "No known skills found in the posting" in r.explanations


def test_few_known_skills_are_weak_evidence(tax: Taxonomy, cfg: ScoringConfig) -> None:
    one = run(tax, cfg, profile(), title="Sales", description_text="Requirements: SQL.")
    assert dim(one, "skills") == round(1 / cfg.skills.min_evidence, 2)
    assert any("only 1 known skills" in e for e in one.explanations)
    many = run(tax, cfg, profile(), description_text="Requirements: Python, SQL, Kafka.")
    assert dim(many, "skills") == 1.0


def test_real_posting_end_to_end(tax: Taxonomy, cfg: ScoringConfig) -> None:
    j = json.loads((ROOT / "tests/fixtures/job_senior_data_engineer.json").read_text())
    job = Job(
        title=j["title"],
        description_text=j["description_text"],
        remote_policy="remote",
        location_text="Remote: Germany, Portugal, Spain (UTC-1 to UTC+1)",
        employment_type="full_time",
    )
    a = score(profile(), job, tax, cfg)
    assert (a.band, a.hard_constraints) == ("good", "unknown")  # no salary in the posting
    assert "Data modeling" in a.explanations[2]
    assert all(score(profile(), job, tax, cfg) == a for _ in range(3))  # deterministic


def test_inputs_are_strict() -> None:
    data = yaml.safe_load((ROOT / "tests/fixtures/profile_example.yaml").read_text())
    with pytest.raises(ValidationError):
        Profile.model_validate({**data, "ssn": "123"})
    with pytest.raises(ValidationError):
        Profile.model_validate({**data, "schema_version": 3})
    with pytest.raises(ValidationError):
        Job.model_validate({"title": "x", "remote_policy": "sometimes"})


def test_config_rejects_unknown_dimensions(cfg: ScoringConfig) -> None:
    raw = cfg.model_dump()
    raw["weights"]["vibes"] = 0.1
    with pytest.raises(ValidationError, match="unknown dimensions"):
        ScoringConfig.model_validate(raw)
