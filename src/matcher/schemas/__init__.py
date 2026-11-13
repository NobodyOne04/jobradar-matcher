"""Inputs of matching: the candidate profile (schema v1, jobradar ADR 0006) and the normalized
job (jobradar ADR 0005). Both are validated strictly: unknown fields are errors."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Seniority = Literal["junior", "mid", "senior", "staff", "principal", "lead", "manager", "director"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship"]
Period = Literal["year", "month", "day", "hour"]
Constraint = Literal["employment_types", "remote_only", "locations", "timezones", "salary"]

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


class Preferences(_Strict):
    employment_types: list[EmploymentType] = []
    remote_only: bool | None = None
    locations: list[str] = Field(default=[], max_length=200)
    timezones: Timezones | None = None
    salary: Salary | None = None
    hard_constraints: list[Constraint] = []


class Profile(_Strict):
    """Candidate profile, schema_version 1."""

    schema_version: Literal[1]
    headline: str | None = None
    seniority: Seniority
    years_of_experience: float = Field(ge=0, le=60)
    experience: list[Experience] = Field(max_length=50)
    skills: list[ProfileSkill] = Field(max_length=300)
    preferences: Preferences
    extra: dict[str, object] = {}


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
