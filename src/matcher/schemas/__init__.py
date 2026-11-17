"""Inputs of matching: the candidate profile (schema v1, jobradar ADR 0006, or v2, ADR 0015)
and the normalized job (jobradar ADR 0005). Both are validated strictly: unknown fields are
errors, and a v1 profile may not carry v2 fields."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Seniority = Literal["junior", "mid", "senior", "staff", "principal", "lead", "manager", "director"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship"]
Period = Literal["year", "month", "day", "hour"]
Constraint = Literal[
    "employment_types",
    "remote_only",
    "locations",
    "timezones",
    "salary",
    "languages",
    "work_authorization",  # v2 only (jobradar ADR 0015); evaluated from matcher ADR 0006
]
CEFR = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]
Place = Field(min_length=2, max_length=40)

Short = Field(min_length=1, max_length=200)
Text = Field(min_length=1, max_length=2000)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Experience(_Strict):
    title: str = Short
    company: str = Short
    start: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    end: str | None = Field(default=None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    responsibilities: list[str] = Field(default=[], max_length=50)
    achievements: list[str] = Field(default=[], max_length=50)
    skills: list[str] = Field(default=[], max_length=200)


class ProfileSkill(_Strict):
    name: str = Short
    level: Literal["basic", "intermediate", "advanced", "expert"] | None = None
    years: float | None = Field(default=None, ge=0, le=60)


class Timezones(_Strict):
    min_utc_offset: float = Field(ge=-12, le=14)
    max_utc_offset: float = Field(ge=-12, le=14)


class Salary(_Strict):
    min: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    period: Period


class Language(_Strict):
    language: str = Field(pattern=r"^[a-z]{2}$")  # ISO 639-1
    level: CEFR


class Relocation(_Strict):
    willing: bool
    regions: list[str] = Field(default=[], max_length=50)  # worldwide, regions or ISO codes
    needs_visa_sponsorship: bool | None = None


class Preferences(_Strict):
    employment_types: list[EmploymentType] = []
    remote_only: bool | None = None
    locations: list[str] = Field(default=[], max_length=200)
    remote_regions: list[str] = Field(default=[], max_length=50)  # v2
    relocation: Relocation | None = None  # v2
    timezones: Timezones | None = None
    salary: Salary | None = None
    hard_constraints: list[Constraint] = []


V2_ONLY_CONSTRAINTS = frozenset({"languages", "work_authorization"})


class Profile(_Strict):
    """Candidate profile, schema_version 1 or 2 (v2 adds the fields marked below)."""

    schema_version: Literal[1, 2]
    headline: str | None = None
    target_roles: list[str] = Field(default=[], max_length=10)  # v2
    languages: list[Language] = Field(default=[], max_length=20)  # v2
    seniority: Seniority
    years_of_experience: float = Field(ge=0, le=60)
    experience: list[Experience] = Field(max_length=50)
    skills: list[ProfileSkill] = Field(max_length=300)
    preferences: Preferences
    extra: dict[str, object] = {}

    @model_validator(mode="after")
    def _v1_has_no_v2_fields(self) -> Profile:
        # Mirrors the backend's schemas: v1 must mean what it meant (jobradar ADR 0006, 0015).
        if self.schema_version == 1:
            prefs = self.preferences
            if (
                self.target_roles
                or self.languages
                or prefs.remote_regions
                or prefs.relocation is not None
                or V2_ONLY_CONSTRAINTS & set(prefs.hard_constraints)
            ):
                raise ValueError(
                    "schema_version 1 has no target_roles, languages, remote_regions,"
                    " relocation, or languages/work_authorization constraints"
                )
        return self


class Job(_Strict):
    """The source-independent job the backend sends (unknown stays unknown)."""

    title: str = Field(min_length=1, max_length=500)
    company_name: str = Field(default="", max_length=500)
    description_text: str = Field(default="", max_length=200_000)
    location_text: str = Field(default="", max_length=20_000)
    remote_policy: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    countries: list[str] = Field(default=[], max_length=300)
    employment_type: Literal["full_time", "part_time", "contract", "internship", "unknown"] = (
        "unknown"
    )
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    salary_period: Period | None = None
    posted_at: datetime | None = None
