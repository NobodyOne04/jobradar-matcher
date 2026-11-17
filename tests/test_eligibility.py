"""Eligibility (matcher ADR 0006): languages, relocation, remote regions, visa sponsorship."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from matcher.extract.eligibility import languages_required, posting_language, sponsorship
from matcher.schemas import Job, Profile
from matcher.score import MatchResult, score
from matcher.score.config import load as load_config
from matcher.taxonomy import load

ROOT = Path(__file__).parent.parent


def langs(line: str, preferred_section: bool = False) -> set[tuple[str, str, str]]:
    return {
        (r.language, r.level, r.requirement)
        for r in languages_required([(line, preferred_section)])
    }


# --- Extraction: cases taken from real postings (eval/jobs.jsonl) -------------------------------


@pytest.mark.parametrize(
    ("line", "want"),
    [
        ("Fluent in German required", {("de", "C1", "required")}),
        (
            "Fluent French and business English is required",
            {("fr", "C1", "required"), ("en", "B2", "required")},
        ),
        ("English proficiency: C1-level English required", {("en", "C1", "required")}),
        ("English level - B2", {("en", "B2", "required")}),
        (
            "Native-level Thai fluency with professional working proficiency in English.",
            {("th", "C2", "required"), ("en", "B2", "required")},
        ),
        # the "a plus" is about other languages, not English
        (
            "Fluent in English, with proficiency in one or more additional European"
            " languages a plus",
            {("en", "C1", "required")},
        ),
        # a choice of languages is no single requirement
        (
            "Fluency in English essential; proficiency in Bahasa Indonesia, Bahasa Melayu, Thai, "
            "Vietnamese, or other ASEAN languages",
            {("en", "C1", "required"), ("id", "C1", "preferred")},
        ),
        ("German is a plus", set()),  # no level and no requirement word: not a requirement
        ("Spanish speaking would be a plus", {("es", "B2", "preferred")}),
        # nationalities, markets and places are not language requirements
        ("You will work with German customers and our French Polynesia office", set()),
        ("Experience selling into the Japanese market", set()),
    ],
)
def test_language_requirements(line: str, want: set[tuple[str, str, str]]) -> None:
    assert langs(line) == want


def test_required_in_the_clause_beats_a_preferred_heading() -> None:
    assert langs("Fluency in English is required to coordinate with partners", True) == {
        ("en", "C1", "required")
    }
    assert langs("Fluent Dutch", True) == {("nl", "C1", "preferred")}


def test_posting_language() -> None:
    en = "We are looking for a data engineer to join our team and you will build the pipelines " * 4
    de = "Wir suchen einen Data Engineer für unser Team und du bist mit der Plattform vertraut " * 4
    assert posting_language(en) == "en"
    assert posting_language(de) == "de"
    assert posting_language("Python SQL Spark Kafka") is None  # too short to tell


@pytest.mark.parametrize(
    ("lines", "want"),
    [
        (
            ["Bright Vision is unable to sponsor new H-1B visa petitions for this position."],
            "ruled_out",
        ),
        (["Applicants must be authorized to work in the United States."], "ruled_out"),
        (["We do not offer visa sponsorship."], "ruled_out"),
        (
            ["Relocation support to one of our hubs, Cyprus or Spain, for you and your family"],
            "offered",
        ),
        (["Visa sponsorship is available for this role."], "offered"),
        # a refusal wins over an offer
        (["We provide a relocation package.", "We cannot sponsor work visas."], "ruled_out"),
        (["Great team, flexible hours."], None),
    ],
)
def test_sponsorship(lines: list[str], want: str | None) -> None:
    found = sponsorship(lines)
    assert (found.stance if found else None) == want


# --- Scoring --------------------------------------------------------------------------------------

TAX, CFG = load(ROOT / "data/skills.yaml"), load_config(ROOT / "defaults/scoring.yaml")


def profile(**changes: Any) -> Profile:
    """The fictional v2 example, as the ADR's candidate: in Thailand, remote worldwide/APAC/TH,
    relocation anywhere with sponsorship needed, English C1 and Russian native."""
    data: dict[str, Any] = yaml.safe_load(
        (ROOT / "tests/fixtures/profile_example_v2.yaml").read_text()
    )
    data["languages"] = [{"language": "en", "level": "C1"}, {"language": "ru", "level": "native"}]
    data["preferences"] = {
        "remote_only": False,
        "locations": ["Thailand"],
        "remote_regions": ["worldwide", "apac", "TH"],
        "relocation": {"willing": True, "regions": ["worldwide"], "needs_visa_sponsorship": True},
        "hard_constraints": ["locations", "languages", "work_authorization"],
        **changes,
    }
    return Profile.model_validate(data)


def run(p: Profile, **job: Any) -> MatchResult:
    job.setdefault("title", "Senior Data Engineer")
    return score(p, Job(**job), TAX, CFG)


def gates(r: MatchResult) -> dict[str, str]:
    return {g.constraint: g.result for g in r.gates}


def test_remote_open_to_your_regions_is_reachable() -> None:
    r = run(
        profile(),
        remote_policy="remote",
        location_text="Remote - APAC",
        description_text="You will build pipelines and our team is distributed",
    )
    assert gates(r)["locations"] == "pass" and gates(r)["work_authorization"] == "pass"


def test_remote_limited_elsewhere_counts_as_relocation() -> None:
    r = run(
        profile(),
        remote_policy="remote",
        countries=["US"],
        description_text="Applicants must be authorized to work in the United States.",
    )
    assert gates(r)["locations"] == "pass"  # reachable by moving
    assert gates(r)["work_authorization"] == "fail"  # but they won't sponsor
    assert r.band == "excluded"


def test_onsite_abroad_with_sponsorship_offered() -> None:
    r = run(
        profile(),
        remote_policy="onsite",
        countries=["DE"],
        description_text="Visa sponsorship is available for this role.",
    )
    loc = next(d for d in r.dimensions if d.name == "location")
    assert gates(r) == {"languages": "unknown", "locations": "pass", "work_authorization": "pass"}
    assert any("relocation, sponsorship or help offered" in e for e in loc.evidence)


def test_onsite_abroad_silent_on_sponsorship_stays_eligible() -> None:
    r = run(profile(), remote_policy="onsite", countries=["SG"], description_text="Join our team.")
    assert gates(r)["work_authorization"] == "unknown" and r.band != "excluded"


def test_no_relocation_means_onsite_abroad_is_out() -> None:
    p = profile(relocation={"willing": False})
    r = run(p, remote_policy="onsite", countries=["DE"], description_text="Join our team.")
    assert gates(r)["locations"] == "fail" and r.band == "excluded"


def test_language_you_lack_fails_and_one_you_speak_passes() -> None:
    p = profile()
    de = run(p, remote_policy="remote", description_text="Requirements:\nFluent in German required")
    assert gates(de)["languages"] == "fail" and de.band == "excluded"
    ru = run(p, remote_policy="remote", description_text="Requirements:\nNative Russian required")
    assert gates(ru)["languages"] == "pass"
    native_en = run(p, remote_policy="remote", description_text="Requirements:\nNative English")
    assert gates(native_en)["languages"] == "fail"  # native is C2; you have C1


def test_posting_in_a_language_you_dont_list_is_a_hint_not_a_gate() -> None:
    text = (
        "Wir suchen einen Data Engineer für unser Team und du bist mit der Plattform vertraut " * 4
    )
    r = run(profile(), remote_policy="remote", description_text=text)
    assert gates(r)["languages"] == "pass"  # 0.5 never fails a gate
    loc = next(d for d in r.dimensions if d.name == "location")
    assert any("posting is in German" in e for e in loc.evidence)


def test_v1_profiles_take_the_old_path() -> None:
    data = yaml.safe_load((ROOT / "tests/fixtures/profile_example.yaml").read_text())
    data["preferences"] = {
        "remote_only": True,
        "locations": ["Thailand"],
        "hard_constraints": ["remote_only", "locations"],
    }
    r = run(
        Profile.model_validate(data),
        remote_policy="onsite",
        countries=["DE"],
        description_text="Visa sponsorship is available.",
    )
    assert gates(r) == {"locations": "fail", "remote_only": "fail"}
