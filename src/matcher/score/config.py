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
    min_evidence: float = Field(default=3, ge=1)  # ADR 0005; older bundles lack it


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


class EligibilityCfg(_C):
    """Location-dimension values for profile v2's eligibility rules (ADR 0006). Older bundles
    lack the section: these defaults apply."""

    remote_reachable: float = Field(default=1.0, ge=0, le=1)  # remote, open to your regions
    relocation_sponsored: float = Field(default=0.8, ge=0, le=1)  # move; help or visa offered
    relocation: float = Field(default=0.6, ge=0, le=1)  # move; sponsorship not mentioned
    posting_language_unspoken: float = Field(default=0.5, gt=0, le=1)  # never fails a gate
    # Points off a job you can only take by moving, so remote jobs open to you rank first at
    # equal fit (ADR 0006 amendment, 2026-11-17). Location is only 10% of the weight.
    relocation_penalty: int = Field(default=10, ge=0, le=50)


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
    eligibility: EligibilityCfg = EligibilityCfg()
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
