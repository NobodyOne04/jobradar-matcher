"""Scoring a job against a profile (matcher ADR 0002): dimensions, hard constraints, the
banded score, confidence and completeness, and explanations.

Unknown is never a mismatch (SPEC 6.3): a dimension without data is left out of the score
and lowers completeness; a hard constraint without data is "unknown", never "fail".
Pure and deterministic: the same profile, job, taxonomy and config give the same result.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from matcher.embed import Embedder
from matcher.extract import Extraction, extract, match_skills
from matcher.schemas import Job, Profile
from matcher.score import geo
from matcher.score.config import ScoringConfig
from matcher.taxonomy import Taxonomy

GateResult = Literal["pass", "fail", "unknown"]


class Dimension(BaseModel):
    name: str
    score: float | None  # 0..1, None = unknown
    weight: float
    evidence: list[str]


class SkillRef(BaseModel):
    id: str
    name: str
    requirement: Literal["required", "preferred"]
    via: str | None = None  # transferable: the related skill the candidate has


class Skills(BaseModel):
    matched: list[SkillRef]
    transferable: list[SkillRef]
    missing: list[SkillRef]
    unrecognized: list[str]


class Gate(BaseModel):
    constraint: str
    result: GateResult
    reason: str


class MatchResult(BaseModel):
    score: int  # 0-100, a multiple of 5
    band: Literal["strong", "good", "weak", "excluded"]
    confidence: Literal["high", "medium", "low"]
    completeness: float  # share of the total weight whose dimensions had data
    hard_constraints: GateResult
    gates: list[Gate]
    dimensions: list[Dimension]
    skills: Skills
    explanations: list[str]


@dataclass
class _Dim:
    score: float | None
    evidence: list[str] = field(default_factory=list)


# --- Candidate skills -----------------------------------------------------------------------


def candidate_skills(profile: Profile, tax: Taxonomy) -> set[str]:
    """Taxonomy ids of everything the profile shows: its skills, the skills of each job, and
    what the experience bullets and headline mention. Same alias matching as for postings."""
    texts = [s.name for s in profile.skills] + [n for e in profile.experience for n in e.skills]
    # What the candidate did counts too: "Built ELT pipelines into BigQuery" shows ETL.
    texts += [line for e in profile.experience for line in (*e.responsibilities, *e.achievements)]
    if profile.headline:
        texts.append(profile.headline)
    return {sid for text in texts for sid in match_skills(text, tax)}


# --- Dimensions -----------------------------------------------------------------------------


def _skills(
    ex: Extraction, have: set[str], tax: Taxonomy, cfg: ScoringConfig
) -> tuple[_Dim, Skills]:
    matched, transferable, missing = [], [], []
    got = total = 0.0
    for s in ex.skills:
        weight = 1.0 if s.requirement == "required" else cfg.skills.preferred_weight
        total += weight
        ref = SkillRef(id=s.id, name=s.name, requirement=s.requirement)
        if s.id in have:
            matched.append(ref)
            got += weight
            continue
        via = sorted(h for h in have if tax.related(s.id, h))
        if via:
            transferable.append(ref.model_copy(update={"via": tax.skills[via[0]].name}))
            got += weight * cfg.skills.transfer_credit
        else:
            missing.append(ref)
    skills = Skills(
        matched=matched, transferable=transferable, missing=missing, unrecognized=ex.unrecognized
    )
    # ADR 0005: the taxonomy is the candidate's field, so a posting naming none of its skills
    # is a mismatch (0), not missing data; a few known skills are weak evidence, so the score
    # is shrunk as if the posting named min_evidence skills.
    if total == 0:
        return _Dim(0.0, ["no known skills found in the posting"]), skills
    req = [s for s in ex.skills if s.requirement == "required"]
    req_matched = sum(1 for s in matched if s.requirement == "required")
    evidence = [f"{req_matched} of {len(req)} required skills matched"] if req else []
    if total < cfg.skills.min_evidence:
        evidence.append(f"only {len(ex.skills)} known skills in the posting")
    return _Dim(got / max(total, cfg.skills.min_evidence), evidence), skills


def _responsibilities(
    ex: Extraction, profile: Profile, cfg: ScoringConfig, embedder: Embedder | None
) -> _Dim:
    """How close the job's duties are to what the candidate has done: for each duty, the most
    similar experience bullet; their mean cosine, mapped from [low, high] to [0, 1]."""
    if embedder is None:
        return _Dim(None, ["embedding model not loaded"])
    bullets = [b for e in profile.experience for b in (*e.responsibilities, *e.achievements)]
    if not bullets:
        return _Dim(None, ["no experience bullets in your profile"])
    if not ex.duties:
        return _Dim(None, ["no responsibilities in the posting"])
    sims = embedder.embed(ex.duties) @ embedder.embed(bullets).T
    best = sims.max(axis=1)
    mean = round(float(best.mean()), 3)  # rounded before mapping: stable across platforms
    c = cfg.responsibilities
    value = min(max((mean - c.low) / (c.high - c.low), 0.0), 1.0)
    order = sorted(range(len(ex.duties)), key=lambda i: (-float(best[i]), i))[: c.top_pairs]
    evidence = [f"similarity {mean:.2f} on average over {len(ex.duties)} duties"] + [
        f"{float(best[i]):.2f}: {_cut(ex.duties[i])} ~ {_cut(bullets[int(sims[i].argmax())])}"
        for i in order
    ]
    return _Dim(value, evidence)


def _cut(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _seniority(ex: Extraction, profile: Profile, cfg: ScoringConfig) -> _Dim:
    parts, evidence = [], []
    ranks = cfg.seniority.ranks
    if ex.title_level:
        gap = ranks[profile.seniority] - ranks[ex.title_level]
        gap = max(min(gap, 3), -3)
        parts.append(cfg.seniority.level_gap_scores[gap])
        evidence.append(f"title says {ex.title_level}, you are {profile.seniority}")
    if ex.years_required:
        short = max(0, int(ex.years_required - profile.years_of_experience))
        scores = cfg.seniority.years_short_scores
        parts.append(scores[min(short, len(scores) - 1)])
        evidence.append(
            f"asks {ex.years_required}+ years, you have {profile.years_of_experience:g}"
        )
    if not parts:
        return _Dim(None, ["no level or years in the posting"])
    return _Dim(sum(parts) / len(parts), evidence)


def _per_year_eur(amount: float, currency: str, period: str, cfg: ScoringConfig) -> float | None:
    rate = cfg.compensation.eur_per_unit.get(currency)
    factor = cfg.compensation.per_year.get(period)
    return None if rate is None or factor is None else amount * rate * factor


def _compensation(job: Job, ex: Extraction, profile: Profile, cfg: ScoringConfig) -> _Dim:
    want = profile.preferences.salary
    if want is None:
        return _Dim(None, ["no salary preference in your profile"])
    if job.salary_currency and job.salary_period and (job.salary_max or job.salary_min):
        top = job.salary_max or job.salary_min
        cur, per = job.salary_currency, job.salary_period
    elif ex.salary and ex.salary.period:
        top, cur, per = ex.salary.max or ex.salary.min, ex.salary.currency, ex.salary.period
    else:
        return _Dim(None, ["no salary in the posting"])
    offered = _per_year_eur(top or 0, cur, per, cfg)
    floor = _per_year_eur(want.min, want.currency, want.period, cfg)
    if offered is None or floor is None:
        return _Dim(None, [f"no fixed rate for {cur} or {want.currency}"])
    shown = f"up to {cur} {top:,.0f}/{per}"
    if offered >= floor:
        return _Dim(1.0, [f"{shown} meets your minimum"])
    if offered >= floor * cfg.compensation.near_miss:
        return _Dim(0.5, [f"{shown} is just below your minimum"])
    return _Dim(0.0, [f"{shown} is below your minimum"])


_REMOTE = re.compile(r"\bremote\b|\bwork from home\b|\bfully distributed\b", re.IGNORECASE)
_HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
_ONSITE = re.compile(r"\bon[\s-]?site\b|\bin[\s-]office\b|\bin the office\b", re.IGNORECASE)


def _remote_policy(job: Job) -> str:
    """The job's remote policy: the structured field, else what the title or location says."""
    if job.remote_policy != "unknown":
        return job.remote_policy
    where = f"{job.title}\n{job.location_text}"
    if _HYBRID.search(where):
        return "hybrid"
    if _REMOTE.search(where):
        return "remote"
    if _ONSITE.search(where):
        return "onsite"
    return "unknown"


def _location(job: Job, ex: Extraction, profile: Profile) -> tuple[_Dim, dict[str, _Dim]]:
    """Remote, country and timezone fit; each also feeds its hard constraint."""
    prefs = profile.preferences
    subs: dict[str, _Dim] = {}

    if prefs.remote_only:
        policy = _remote_policy(job)
        subs["remote_only"] = (
            _Dim(1.0, ["remote"])
            if policy == "remote"
            else _Dim(None, ["remote policy not stated"])
            if policy == "unknown"
            else _Dim(0.0, [f"{policy}, not remote"])
        )

    if prefs.locations:
        yours = frozenset().union(*(geo.covers(p) for p in prefs.locations))
        allowed = (
            frozenset(c for c in job.countries if c in geo.COUNTRIES)
            | geo.mentioned(job.location_text)
            | frozenset().union(*(geo.region_countries(r) for r in ex.regions))
        )
        if not yours or not allowed:
            subs["locations"] = _Dim(None, ["no known location to compare"])
        elif yours & allowed:
            subs["locations"] = _Dim(1.0, ["open to your locations"])
        else:
            subs["locations"] = _Dim(0.0, [f"limited to {_names(allowed)}"])

    if prefs.timezones:
        lo, hi = prefs.timezones.min_utc_offset, prefs.timezones.max_utc_offset
        if not ex.utc_offsets:
            subs["timezones"] = _Dim(None, ["no time zone in the posting"])
        elif any(lo <= o <= hi for o in ex.utc_offsets):
            subs["timezones"] = _Dim(1.0, ["time zone overlaps yours"])
        else:
            offsets = ", ".join(f"UTC{o:+g}" for o in ex.utc_offsets)
            subs["timezones"] = _Dim(0.0, [f"time zones {offsets} are outside your range"])

    known = [d for d in subs.values() if d.score is not None]
    evidence = [e for d in subs.values() for e in d.evidence]
    if not known:
        return _Dim(None, evidence or ["no location preference in your profile"]), subs
    return _Dim(sum(d.score or 0 for d in known) / len(known), evidence), subs


def _names(codes: frozenset[str], limit: int = 4) -> str:
    names = sorted(geo.COUNTRIES[c][0] for c in codes)
    return ", ".join(names[:limit]) + (
        f" and {len(names) - limit} more" if len(names) > limit else ""
    )


def _employment(job: Job, profile: Profile) -> _Dim:
    wanted = profile.preferences.employment_types
    if not wanted:
        return _Dim(None, ["no employment type preference in your profile"])
    if job.employment_type == "unknown":
        return _Dim(None, ["employment type not stated"])
    if job.employment_type in wanted:
        return _Dim(1.0, [job.employment_type.replace("_", " ")])
    return _Dim(0.0, [f"{job.employment_type.replace('_', ' ')}, not one you accept"])


# --- Gates and aggregation ------------------------------------------------------------------


def _gate(constraint: str, dim: _Dim | None) -> Gate:
    if dim is None or dim.score is None:
        reason = dim.evidence[0] if dim and dim.evidence else "no data"
        return Gate(constraint=constraint, result="unknown", reason=reason)
    # A near miss (score 0.5, e.g. salary 90-100% of your minimum) still passes the gate.
    result: GateResult = "fail" if dim.score == 0 else "pass"
    return Gate(
        constraint=constraint, result=result, reason=dim.evidence[0] if dim.evidence else ""
    )


def score(
    profile: Profile, job: Job, tax: Taxonomy, cfg: ScoringConfig, embedder: Embedder | None = None
) -> MatchResult:
    """Without an embedder the responsibilities dimension is unknown (lower completeness)."""
    ex = extract(job.title, job.description_text, tax)
    skills_dim, skills = _skills(ex, candidate_skills(profile, tax), tax, cfg)
    location_dim, location_subs = _location(job, ex, profile)
    dims: dict[str, _Dim] = {
        "skills": skills_dim,
        "responsibilities": _responsibilities(ex, profile, cfg, embedder),
        "seniority": _seniority(ex, profile, cfg),
        "compensation": _compensation(job, ex, profile, cfg),
        "location": location_dim,
        "employment_type": _employment(job, profile),
    }

    gate_inputs: dict[str, _Dim | None] = {
        **location_subs,
        "salary": dims["compensation"],
        "employment_types": dims["employment_type"],
    }
    gates = [_gate(c, gate_inputs.get(c)) for c in sorted(profile.preferences.hard_constraints)]
    overall: GateResult = (
        "fail"
        if any(g.result == "fail" for g in gates)
        else "unknown"
        if any(g.result == "unknown" for g in gates)
        else "pass"
    )

    weights = {name: cfg.weights[name] for name in dims if name in cfg.weights}
    known = {n: w for n, w in weights.items() if dims[n].score is not None}
    total_w, known_w = sum(weights.values()), sum(known.values())
    raw = sum(w * (dims[n].score or 0) for n, w in known.items()) / known_w if known_w else 0.0
    value = int(5 * round(raw * 100 / 5))
    completeness = round(known_w / total_w, 2) if total_w else 0.0

    band: Literal["strong", "good", "weak", "excluded"] = (
        "excluded"
        if overall == "fail"
        else "strong"
        if value >= cfg.bands.strong
        else "good"
        if value >= cfg.bands.good
        else "weak"
    )
    recognized = len(ex.skills)
    high, medium = cfg.confidence.high, cfg.confidence.medium
    confidence: Literal["high", "medium", "low"] = (
        "high"
        if completeness >= high["min_completeness"]
        and recognized >= high["min_recognized_skills"]
        and overall != "unknown"
        else "medium"
        if completeness >= medium["min_completeness"]
        else "low"
    )

    return MatchResult(
        score=value,
        band=band,
        confidence=confidence,
        completeness=completeness,
        hard_constraints=overall,
        gates=gates,
        dimensions=[
            Dimension(
                name=n,
                score=None if d.score is None else round(d.score, 2),
                weight=weights.get(n, 0.0),
                evidence=d.evidence,
            )
            for n, d in dims.items()
        ],
        skills=skills,
        explanations=_explain(gates, skills, dims),
    )


def _explain(gates: list[Gate], skills: Skills, dims: dict[str, _Dim]) -> list[str]:
    if all(d.score is None for d in dims.values()):
        return ["Not enough information in the posting to score it"]
    out = [
        f"Hard constraint {g.constraint} failed: {g.reason}" for g in gates if g.result == "fail"
    ]
    out += [
        f"Hard constraint {g.constraint} unknown: {g.reason}"
        for g in gates
        if g.result == "unknown"
    ]
    if dims["skills"].evidence:
        out.append("; ".join(dims["skills"].evidence).capitalize())
    missing_req = [s.name for s in skills.missing if s.requirement == "required"]
    if missing_req:
        out.append("Missing required: " + ", ".join(missing_req))
    if skills.transferable:
        out.append(
            "Transferable: "
            + ", ".join(f"{s.name} (you have {s.via})" for s in skills.transferable)
        )
    if dims["responsibilities"].score is not None:
        out.append("Responsibilities: " + dims["responsibilities"].evidence[0])
    for name in ("seniority", "compensation", "location", "employment_type"):
        if dims[name].score is not None and dims[name].evidence:
            out.append(f"{name.replace('_', ' ').capitalize()}: {'; '.join(dims[name].evidence)}")
    return out
