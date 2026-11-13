"""The scoring config (defaults/scoring.yaml): weights, thresholds, fixed FX rates."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DIMENSIONS = (
    "skills",
    "responsibilities",
    "seniority",
    "compensation",
    "location",
    "employment_type",
)


class _C(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillsCfg(_C):
    preferred_weight: float = Field(ge=0, le=1)
    transfer_credit: float = Field(ge=0, le=1)


class ResponsibilitiesCfg(_C):
    low: float = Field(ge=-1, le=1)
    high: float = Field(ge=-1, le=1)
    top_pairs: int = Field(ge=0, le=10)


class SeniorityCfg(_C):
    ranks: dict[str, int]
    level_gap_scores: dict[int, float]
    years_short_scores: list[float] = Field(min_length=1)


class CompensationCfg(_C):
    near_miss: float = Field(gt=0, lt=1)
    eur_per_unit: dict[str, float]
    per_year: dict[str, float]


class BandsCfg(_C):
    strong: int = Field(ge=0, le=100)
    good: int = Field(ge=0, le=100)


class ConfidenceCfg(_C):
    high: dict[str, float]
    medium: dict[str, float]


class ScoringConfig(_C):
    weights: dict[str, float]
    skills: SkillsCfg
    responsibilities: ResponsibilitiesCfg
    seniority: SeniorityCfg
    compensation: CompensationCfg
    bands: BandsCfg
    confidence: ConfidenceCfg

    @model_validator(mode="after")
    def _check(self) -> ScoringConfig:
        unknown = set(self.weights) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown dimensions in weights: {sorted(unknown)}")
        if any(w <= 0 for w in self.weights.values()):
            raise ValueError("weights must be positive")
        if self.responsibilities.low >= self.responsibilities.high:
            raise ValueError("responsibilities: low must be below high")
        if self.bands.good > self.bands.strong:
            raise ValueError("bands: good must not exceed strong")
        return self


def load(path: Path) -> ScoringConfig:
    return ScoringConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
