"""The skill taxonomy (matcher ADR 0002): loading, validation and the alias index."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from matcher.tokens import lower, tokens

MAX_PHRASE = 4  # aliases are 1-4 tokens
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class Skill(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    category: str
    aliases: list[str] = Field(min_length=1)
    cased: list[str] = []
    related: list[str] = []


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[str]
    skills: list[Skill]


@dataclass(frozen=True)
class Taxonomy:
    skills: dict[str, Skill]
    index: dict[tuple[str, ...], str] = field(repr=False)  # lowercase alias tokens -> skill id
    cased_index: dict[tuple[str, ...], str] = field(repr=False)  # exact-case alias tokens -> id

    def related(self, a: str, b: str) -> bool:
        return b in self.skills[a].related or a in self.skills[b].related


class TaxonomyError(ValueError):
    pass


def load(path: Path) -> Taxonomy:
    return parse(path.read_text(encoding="utf-8"))


def parse(text: str) -> Taxonomy:
    """Parse and validate. Every problem is reported at once."""
    data = _File.model_validate(yaml.safe_load(text))
    problems: list[str] = []
    skills: dict[str, Skill] = {}
    index: dict[tuple[str, ...], str] = {}
    cased_index: dict[tuple[str, ...], str] = {}

    for s in data.skills:
        if not _ID.match(s.id):
            problems.append(f"{s.id}: id must be lowercase letters, digits and _")
        if s.id in skills:
            problems.append(f"{s.id}: duplicate id")
        if s.category not in data.categories:
            problems.append(f"{s.id}: unknown category {s.category!r}")
        skills[s.id] = s
        for alias in s.aliases:
            _add(index, tuple(lower(tokens(alias))), alias, s.id, problems)
        for alias in s.cased:
            _add(cased_index, tuple(tokens(alias)), alias, s.id, problems)

    for s in data.skills:
        for r in s.related:
            if r not in skills:
                problems.append(f"{s.id}: related skill {r!r} does not exist")
            elif r == s.id:
                problems.append(f"{s.id}: related to itself")
    if problems:
        raise TaxonomyError("; ".join(problems))
    return Taxonomy(skills=skills, index=index, cased_index=cased_index)


def _add(
    idx: dict[tuple[str, ...], str], key: tuple[str, ...], alias: str, sid: str, problems: list[str]
) -> None:
    if not 1 <= len(key) <= MAX_PHRASE:
        problems.append(f"{sid}: alias {alias!r} must be 1-{MAX_PHRASE} words")
    elif key in idx and idx[key] != sid:
        problems.append(f"{sid}: alias {alias!r} already belongs to {idx[key]}")
    else:
        idx[key] = sid
