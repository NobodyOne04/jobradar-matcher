"""Deterministic extraction from a job posting (matcher ADR 0002): skills, required vs preferred,
years of experience, seniority in the title, salary in the text, regions and UTC offsets.

Pure functions over (title, text, taxonomy): same input, same output, nothing read from outside.
"""

import re
from typing import Literal

from pydantic import BaseModel

from matcher.taxonomy import MAX_PHRASE, Taxonomy
from matcher.tokens import lower, tokens

Requirement = Literal["required", "preferred"]
Level = Literal["junior", "mid", "senior", "staff", "principal", "lead", "manager", "director"]


class FoundSkill(BaseModel):
    id: str
    name: str
    category: str
    requirement: Requirement
    evidence: str  # the line it was found on, shortened


class SalaryText(BaseModel):
    min: float
    max: float | None
    currency: str
    period: Literal["year", "month", "day", "hour"] | None


class Extraction(BaseModel):
    skills: list[FoundSkill]
    years_required: int | None
    title_level: Level | None
    salary: SalaryText | None
    regions: list[str]
    utc_offsets: list[float]
    unrecognized: list[str]
    duties: list[str]  # what the job involves: lines to compare with the candidate's experience


# --- Sections ---------------------------------------------------------------------------

Section = Literal["required", "preferred", "responsibilities", "ignore"]

# Checked in this order: "preferred qualifications" is preferred, not required.
_HEADINGS: list[tuple[Section, re.Pattern[str]]] = [
    (
        "preferred",
        re.compile(
            r"nice[\s-]to[\s-]have|bonus|preferred|a plus|pluses|good to have|would be great|"
            r"desirable|extra credit|ideally"
        ),
    ),
    (
        "ignore",
        re.compile(
            r"benefit|perks|about us|about the company|about \w+$|who we are|why join|why work|"
            r"what we offer|we offer|compensation|salary|equal opportunit|diversity|our values|"
            r"culture|how to apply|hiring process|interview process|application process|privacy"
        ),
    ),
    (
        "responsibilities",
        re.compile(
            r"responsibilit|what you.?ll do|what you will do|what you do|your role|the role|"
            r"day[\s-]to[\s-]day|"
            r"you will|your impact|your mission|the job|what you.?ll be doing|in this role"
        ),
    ),
    (
        "required",
        re.compile(
            r"requirement|qualification|must[\s-]have|what you.?ll (need|bring)|what you bring|"
            r"you have|you bring|who you are|about you|your profile|skills|experience|"
            r"looking for|tech stack|our stack|stack|what we need|you should have"
        ),
    ),
]
_INLINE_PREFERRED = re.compile(
    r"nice[\s-]to[\s-]have|\bbonus\b|\ba plus\b|\bis a plus\b|\bpreferred\b|\bideally\b|"
    r"\bdesirable\b|\bnot required\b|\bplus if\b|\b(an?|significant|big|strong) advantage\b|"
    r"\bwould be (great|nice|helpful)\b|\bgood to have\b"
)


def _heading(line: str) -> Section | None:
    """The section a line starts, if it looks like a heading: short, no digits, no sentence end,
    and styled as one (a trailing colon, ALL CAPS, Title Case, or at most 4 words). "5+ years
    of experience with Python" is a requirement, not a heading."""
    raw = line.strip()
    stripped = raw.split(":", 1)[0].strip() if ":" in raw else raw
    words = stripped.split()
    if not stripped or len(stripped) > 70 or len(words) > 8 or any(c.isdigit() for c in stripped):
        return None
    if stripped.endswith((".", "!", "?", ";", ",")):
        return None
    styled = (
        ":" in raw
        or stripped.isupper()
        or len(words) <= 4
        or all(w[0].isupper() for w in words if w[0].isalpha())
    )
    if not styled:
        return None
    low = stripped.casefold()
    for section, pattern in _HEADINGS:
        if pattern.search(low):
            return section
    return None


# --- Skills ---------------------------------------------------------------------------------


# A phrase never spans these: in "AWS (S3, EMR)", "AWS S3" is not one phrase.
_CLAUSE = re.compile(r"[,;:()\[\]{}|•·!?]|\s[-–—]\s|\.\s")


def match_skills(line: str, tax: Taxonomy) -> list[str]:
    """Skill ids on one line, longest alias first, each token used once."""
    found: list[str] = []
    for clause in _CLAUSE.split(line):
        orig = tokens(clause)
        low = lower(orig)
        i = 0
        while i < len(orig):
            for n in range(min(MAX_PHRASE, len(orig) - i), 0, -1):
                skill = tax.index.get(tuple(low[i : i + n])) or tax.cased_index.get(
                    tuple(orig[i : i + n])
                )
                if skill:
                    found.append(skill)
                    i += n
                    break
            else:
                i += 1
    return found


def _skills(lines: list[str], tax: Taxonomy) -> list[FoundSkill]:
    section: Section = "required"  # no recognizable sections: skills count as required
    best: dict[str, FoundSkill] = {}
    for line in lines:
        heading = _heading(line)
        if heading:
            section = heading
            if ":" not in line:
                continue  # "Tech stack: Python, Kafka" also lists skills; a bare heading does not
        if section == "ignore":
            continue
        requirement: Requirement = (
            "preferred"
            if section == "preferred" or _INLINE_PREFERRED.search(line.casefold())
            else "required"
        )
        for sid in match_skills(line, tax):
            prev = best.get(sid)
            if prev is None or (prev.requirement == "preferred" and requirement == "required"):
                s = tax.skills[sid]
                best[sid] = FoundSkill(
                    id=sid,
                    name=s.name,
                    category=s.category,
                    requirement=requirement,
                    evidence=_short(line),
                )
    return sorted(best.values(), key=lambda f: f.id)


def _short(line: str, limit: int = 160) -> str:
    line = " ".join(line.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


# --- Years, title level ---------------------------------------------------------------------

_YEARS = re.compile(
    r"(?<![\d.])(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)


def _years(lines: list[str]) -> int | None:
    """The most demanding minimum stated, e.g. "5+ years of Python" and "3 years of AWS" -> 5."""
    found = [
        int(m.group(1))
        for line in lines
        if re.search(r"experience|years of|yrs of", line, re.IGNORECASE)
        for m in _YEARS.finditer(line)
    ]
    found = [y for y in found if 0 < y <= 25]
    return max(found) if found else None


_LEVELS: list[tuple[Level, re.Pattern[str]]] = [  # lowest to highest rank
    ("junior", re.compile(r"\b(junior|jr|graduate|entry[\s-]level|intern|internship|trainee)\b")),
    ("mid", re.compile(r"\b(mid|mid[\s-]level|intermediate)\b")),
    ("senior", re.compile(r"\b(senior|sr)\b")),
    ("lead", re.compile(r"\b(lead|tech lead)\b")),
    ("staff", re.compile(r"\bstaff\b")),
    ("principal", re.compile(r"\bprincipal\b")),
    ("manager", re.compile(r"\b(manager|head of|head)\b")),
    ("director", re.compile(r"\b(director|vp|vice president)\b")),
]


def _title_level(title: str) -> Level | None:
    """The highest level named in the title: "Senior Staff Engineer" -> staff."""
    low = title.casefold()
    found: Level | None = None
    for level, pattern in _LEVELS:
        if pattern.search(low):
            found = level
    return found


# --- Salary ---------------------------------------------------------------------------------

_CUR_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP"}
_NUM = r"(\d{1,3}(?:[,.\s]\d{3})+|\d+(?:[.,]\d+)?)\s*([kK])?"
_SALARY = re.compile(
    rf"(?P<sym>[$€£])?\s?(?P<lo>{_NUM})\s*(?:-|–|—|to)\s*(?P<sym2>[$€£])?\s?(?P<hi>{_NUM})"
    r"\s*(?P<code>USD|EUR|GBP|CHF|CAD|AUD|PLN|SEK|NOK|DKK)?",
)
_PERIODS = [
    ("hour", re.compile(r"per hour|/\s?h(ou)?r\b|hourly|an hour", re.IGNORECASE)),
    ("day", re.compile(r"per day|/\s?day|daily rate|a day", re.IGNORECASE)),
    ("month", re.compile(r"per month|/\s?mo(nth)?\b|monthly|a month", re.IGNORECASE)),
    (
        "year",
        re.compile(
            r"per year|per annum|/\s?y(ea)?r\b|annual|yearly|a year|\bp\.?a\.?\b", re.IGNORECASE
        ),
    ),
]


def _amount(num: str, k: str | None) -> float:
    digits = num.replace(" ", "")
    if re.fullmatch(r"\d{1,3}([,.]\d{3})+", digits):  # 120,000 or 120.000: thousands separators
        value = float(re.sub(r"[,.]", "", digits))
    else:
        value = float(digits.replace(",", "."))
    return value * 1000 if k else value


def _salary(lines: list[str]) -> SalaryText | None:
    for line in lines:
        for m in _SALARY.finditer(line):
            sym = m.group("sym") or m.group("sym2")
            currency = _CUR_SYMBOL.get(sym or "") or m.group("code")
            if not currency:
                continue  # "3-5 years" and other ranges without money
            lo_num, lo_k = re.match(_NUM, m.group("lo")).groups()  # type: ignore[union-attr]
            hi_num, hi_k = re.match(_NUM, m.group("hi")).groups()  # type: ignore[union-attr]
            hi = _amount(hi_num, hi_k)
            lo = _amount(lo_num, lo_k or hi_k)  # "80-100k": the k belongs to both
            if lo > hi:
                continue
            tail = line[m.end() : m.end() + 40]
            period = next((p for p, rx in _PERIODS if rx.search(tail)), None)
            if period is None and lo >= 10000:
                period = "year"  # five-figure amounts without a period are annual salaries
            return SalaryText(min=lo, max=hi, currency=currency, period=period)
    return None


# --- Regions and time zones -----------------------------------------------------------------

_REGIONS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Worldwide",
        re.compile(
            # Hiring phrases only: "20,000 customers worldwide" says nothing about who can apply.
            r"\b(anywhere in the world|work from anywhere|globally remote|"
            r"remote[\s,:(–-]{1,4}(worldwide|global(ly)?|anywhere)|"
            r"(worldwide|global) remote)\b",
            re.I,
        ),
    ),
    ("Europe", re.compile(r"(?i:\beurope(an)?\b)|\bEU\b|\bEEA\b")),
    ("EMEA", re.compile(r"\bEMEA\b")),
    ("Americas", re.compile(r"\bamericas\b", re.I)),
    ("North America", re.compile(r"\bnorth america\b", re.I)),
    ("LATAM", re.compile(r"\b(LATAM|latin america)\b", re.I)),
    ("APAC", re.compile(r"\bAPAC\b|\basia[\s-]pacific\b", re.I)),
    ("United States", re.compile(r"\b(US|USA|U\.S\.A?\.?)(?!\w)|(?i:\bunited states\b)")),
    ("United Kingdom", re.compile(r"\b(UK|U\.K\.)(?!\w)|(?i:\bunited kingdom\b)")),
    ("Canada", re.compile(r"\bcanada\b", re.I)),
]
_OFFSET = re.compile(r"\b(?:UTC|GMT)\s?([+\-−±])\s?(\d{1,2})(?::?([0-5]\d))?")
_ZONES = {
    "CET": 1.0,
    "CEST": 2.0,
    "EET": 2.0,
    "EEST": 3.0,
    "WET": 0.0,
    "BST": 1.0,
    "EST": -5.0,
    "EDT": -4.0,
    "CST": -6.0,
    "MST": -7.0,
    "PST": -8.0,
    "PDT": -7.0,
}
_ZONE = re.compile(r"\b(" + "|".join(_ZONES) + r")\b")


def _regions(text: str) -> list[str]:
    return sorted(name for name, rx in _REGIONS if rx.search(text))


def _offsets(text: str) -> list[float]:
    found: set[float] = set()
    for sign, hours, minutes in _OFFSET.findall(text):
        value = int(hours) + int(minutes or 0) / 60
        if value <= 14:
            found.update({value, -value} if sign == "±" else {-value if sign in "-−" else value})
    found.update(_ZONES[z] for z in _ZONE.findall(text))
    return sorted(found)


# --- Unrecognized terms ---------------------------------------------------------------------

_TECHY = re.compile(
    r"^(?:[A-Z][a-z]+[A-Z]\w*|[A-Za-z]+\d[\w.]*|[a-z]+\.(?:js|io|ai|py|dev)|[A-Z]{2,6})$"
)
_COMMON_CAPS = {
    "AI",
    "API",
    "APIS",
    "B2B",
    "B2C",
    "CEO",
    "CTO",
    "CFO",
    "COO",
    "EU",
    "UK",
    "US",
    "USA",
    "HR",
    "PTO",
    "IT",
    "OKR",
    "OKRS",
    "KPI",
    "KPIS",
    "SAAS",
    "IPO",
    "ESG",
    "PR",
    "PM",
    "QA",
    "UI",
    "UX",
    "FAQ",
    "ID",
    "OR",
    "AND",
    "THE",
    "WE",
    "YOU",
    "OUR",
    "EMEA",
    "APAC",
    "LATAM",
    "CET",
    "UTC",
    "GMT",
    "EST",
    "PST",
    "CST",
    "USD",
    "EUR",
    "GBP",
    "CV",
    "PHD",
    "MSC",
    "BSC",
    "MS",
    "BS",
    "TBD",
    "ASAP",
    "NYC",
    "SF",
}


def _unrecognized(lines: list[str], tax: Taxonomy) -> list[str]:
    """Technical-looking words the taxonomy does not know: input for growing it."""
    known = {a for key in tax.index for a in key} | {
        a.casefold() for key in tax.cased_index for a in key
    }
    out: set[str] = set()
    for line in lines:
        toks = tokens(line)
        caps = [len(t) > 1 and t.isupper() for t in toks]
        for i, tok in enumerate(toks):
            # "GOOD WORK SHOULD BE REWARDED": capitals next to capitals are emphasis, not acronyms.
            if caps[i] and ((i > 0 and caps[i - 1]) or (i + 1 < len(toks) and caps[i + 1])):
                continue
            if (
                _TECHY.match(tok)
                and tok.upper() not in _COMMON_CAPS
                and tok.casefold() not in known
            ):
                out.add(tok)
    return sorted(out)[:30]


# --- Entry point ----------------------------------------------------------------------------


def extract(title: str, text: str, tax: Taxonomy) -> Extraction:
    lines = [line for line in text.splitlines() if line.strip()]
    kept = _kept_lines(lines)
    return Extraction(
        skills=_skills(lines, tax),
        years_required=_years(kept),
        title_level=_title_level(title),
        salary=_salary(lines),
        regions=_regions(title + "\n" + text),
        utc_offsets=_offsets(title + "\n" + text),
        unrecognized=_unrecognized(kept, tax),
        duties=_duties(lines),
    )


def _duties(lines: list[str], limit: int = 40) -> list[str]:
    """The lines under responsibility headings ("What you'll do"). A posting without such a
    heading gives its sentence-like lines outside ignored and preferred sections instead."""
    by_section: dict[Section | None, list[str]] = {}
    section: Section | None = None
    for line in lines:
        heading = _heading(line)
        if heading:
            section = heading
            continue
        if len(line.split()) >= 5:  # a sentence, not a list of tool names
            by_section.setdefault(section, []).append(" ".join(line.split()))
    found = by_section.get("responsibilities") or [
        *by_section.get(None, []),
        *by_section.get("required", []),
    ]
    return found[:limit]


def _kept_lines(lines: list[str]) -> list[str]:
    """Lines outside ignored sections (about us, benefits...).

    "Founded 10 years ago" in an About us section is not a requirement."""
    out, section = [], None
    for line in lines:
        heading = _heading(line)
        if heading:
            section = heading
        elif section != "ignore":
            out.append(line)
    return out
