"""Profile schema versions 1 and 2 (jobradar ADR 0006, ADR 0015)."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from matcher.schemas import Job, Profile
from matcher.score import score
from matcher.score.config import load as load_config
from matcher.taxonomy import load

ROOT = Path(__file__).parent.parent


def v2() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (ROOT / "tests/fixtures/profile_example_v2.yaml").read_text()
    )
    return data


def v1() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (ROOT / "tests/fixtures/profile_example.yaml").read_text()
    )
    return data


def test_both_versions_parse() -> None:
    p1, p2 = Profile.model_validate(v1()), Profile.model_validate(v2())
    assert p1.schema_version == 1 and p1.target_roles == [] and p1.preferences.relocation is None
    assert p2.schema_version == 2 and p2.target_roles[0] == "Data Engineer"
    assert {(lang.language, lang.level) for lang in p2.languages} == {
        ("de", "native"),
        ("en", "C1"),
    }
    reloc = p2.preferences.relocation
    assert reloc is not None and reloc.willing and reloc.regions == ["CH", "AT", "NL"]


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(target_roles=["Data Engineer"]),
        lambda d: d.update(languages=[{"language": "en", "level": "C1"}]),
        lambda d: d["preferences"].update(remote_regions=["apac"]),
        lambda d: d["preferences"].update(relocation={"willing": True}),
        lambda d: d["preferences"].update(hard_constraints=["languages"]),
    ],
)
def test_v1_may_not_carry_v2_fields(edit: Any) -> None:
    data = v1()
    edit(data)
    with pytest.raises(ValidationError, match="schema_version 1 has no"):
        Profile.model_validate(data)


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(schema_version=3),
        lambda d: d["languages"][0].update(language="German"),
        lambda d: d["languages"][0].update(level="fluent"),
        lambda d: d["preferences"]["relocation"].pop("willing"),
        lambda d: d.update(target_roles=[f"role {i}" for i in range(11)]),
    ],
)
def test_invalid_v2(edit: Any) -> None:
    data = v2()
    edit(data)
    with pytest.raises(ValidationError):
        Profile.model_validate(data)


def test_v2_profile_scores_and_new_gates_are_unknown_until_adr_0006() -> None:
    tax, cfg = load(ROOT / "data/skills.yaml"), load_config(ROOT / "defaults/scoring.yaml")
    r = score(Profile.model_validate(v2()), Job(title="Senior Data Engineer"), tax, cfg)
    gates = {g.constraint: g.result for g in r.gates}
    assert gates["languages"] == "unknown"  # evaluated from matcher ADR 0006 on
    assert r.band != "excluded"
