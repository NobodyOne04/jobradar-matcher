"""What a posting says about who can take it (matcher ADR 0006): required languages and their
level, the language the posting is written in, and visa sponsorship or right-to-work statements.

Deterministic regexes and stopword counts, no model. Precision comes first: a wrongly found
requirement can hide a job, so a language counts only next to a level word ("fluent German"),
a CEFR level ("German C1"), or a requirement word ("German is required"), never alone
("German customers").
"""

import re
from typing import Literal

from pydantic import BaseModel

CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2", "native"]
Level = Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]

LANGUAGES: dict[str, str] = {  # name (lower case) -> ISO 639-1
    "english": "en",
    "german": "de",
    "deutsch": "de",
    "french": "fr",
    "dutch": "nl",
    "flemish": "nl",
    "spanish": "es",
    "castilian": "es",
    "italian": "it",
    "portuguese": "pt",
    "polish": "pl",
    "russian": "ru",
    "ukrainian": "uk",
    "czech": "cs",
    "slovak": "sk",
    "hungarian": "hu",
    "romanian": "ro",
    "bulgarian": "bg",
    "greek": "el",
    "turkish": "tr",
    "swedish": "sv",
    "danish": "da",
    "norwegian": "no",
    "finnish": "fi",
    "icelandic": "is",
    "estonian": "et",
    "latvian": "lv",
    "lithuanian": "lt",
    "hebrew": "he",
    "arabic": "ar",
    "hindi": "hi",
    "japanese": "ja",
    "korean": "ko",
    "mandarin": "zh",
    "chinese": "zh",
    "cantonese": "zh",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "bahasa": "id",
    "malay": "ms",
    "melayu": "ms",
    "tagalog": "tl",
    "filipino": "tl",
}
_LANG = r"(" + "|".join(sorted(LANGUAGES, key=len, reverse=True)) + r")"

# Level words, strongest first: "native" C2 per the ADR, "fluent" C1, "business" B2...
_LEVEL_WORDS: list[tuple[Level, str]] = [
    ("C2", r"native(?:[\s-]level)?|mother[\s-]tongue|bilingual"),
    (
        "C1",
        r"fluent|fluency in|full professional(?: working)? proficiency|excellent|"
        r"proficient|proficiency in|advanced",
    ),
    (
        "B2",
        r"business[\s-](?:level|fluent|fluency)|(?:professional )?working proficiency(?: in)?|"
        r"strong|"
        r"very good|good command of|solid",
    ),
    ("B1", r"conversational|intermediate|working knowledge of|good"),
    ("A2", r"basic|elementary"),
]
_LEVEL_WORD = r"(" + "|".join(p for _, p in _LEVEL_WORDS) + r")"
_CEFR = r"\b([ABC][12])\b"
_REQUIRED_WORD = r"(?:is |are )?(?:required|a must|mandatory|essential|necessary)"

_PATTERNS = [
    # "fluent German", "native-level English", "fluency in Dutch and English"
    re.compile(
        _LEVEL_WORD
        + r" (?:in |level )?(?:both )?"
        + _LANG
        + r"(?: ?(?:and|&|/|,) ?"
        + _LANG
        + r")?",
        re.IGNORECASE,
    ),
    # "German (C1)", "English: B2", "English proficiency: C1", "German C1 level"
    re.compile(
        _LANG + r"(?: language)?(?: (?:skills|proficiency|level))?(?: ?[:(\-–])? ?" + _CEFR,
        re.IGNORECASE,
    ),
    # "German is required", "English required", "Japanese language skills are a must"
    re.compile(_LANG + r"(?: language)?(?: skills)? " + _REQUIRED_WORD, re.IGNORECASE),
    # "German speaking", "German-speaking"
    re.compile(_LANG + r"[ -]speaking\b", re.IGNORECASE),
    # "C1-level English", "B2 English"
    re.compile(_CEFR + r"[ -]?(?:level )?" + _LANG, re.IGNORECASE),
]
_REQUIRED_IN_CLAUSE = re.compile(
    r"\brequired\b|\bmust\b|\bmandatory\b|\bessential\b|\bnecessary\b", re.IGNORECASE
)
_OR = re.compile(r"\bor\b", re.IGNORECASE)
_ANY_LANG = re.compile(r"\b" + _LANG + r"\b", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|;")
_PREFERRED_INLINE = re.compile(
    r"nice[\s-]to[\s-]have|\bbonus\b|\ba plus\b|\bpreferred\b|\bideally\b|\bdesirable\b|"
    r"\badvantage\b|\bwould be (great|nice|helpful)\b|\bnot required\b",
    re.IGNORECASE,
)


class LanguageRequirement(BaseModel):
    language: str  # ISO 639-1
    level: Level
    requirement: Literal["required", "preferred"]
    evidence: str


def _level_of(word: str) -> Level:
    w = word.casefold()
    for level, pattern in _LEVEL_WORDS:
        if re.fullmatch(pattern, w, re.IGNORECASE):
            return level
    return "B2"


def _cefr(code: str) -> Level:
    up = code.upper()
    for level in CEFR_ORDER:
        if level == up:
            return level  # type: ignore[return-value]  # CEFR_ORDER holds exactly the Level values
    return "B2"


MAX_LINE = 2000  # longer "lines" are pasted blobs, not requirement lines


def _norm(line: str) -> str:
    """Single spaces and a length cap before any pattern runs: the patterns use single literal
    spaces, never adjacent optional whitespace, so matching stays linear on hostile input."""
    return " ".join(line.split())[:MAX_LINE]


def _matches(sentence: str) -> list[tuple[int, str, Level]]:
    """(position, ISO code, level) of every language mention with a level or requirement."""
    out: list[tuple[int, str, Level]] = []
    for i, pattern in enumerate(_PATTERNS):
        for m in pattern.finditer(sentence):
            level: Level
            if i == 0:
                level, names = _level_of(m.group(1)), [g for g in m.groups()[1:] if g]
            elif i == 1:
                level, names = _cefr(m.group(2)), [m.group(1)]
            elif i == 4:
                level, names = _cefr(m.group(1)), [m.group(2)]
            else:
                level, names = "B2", [m.group(1)]
            out += [(m.start(), LANGUAGES[n.casefold()], level) for n in names]
    return out


def _clause_at(sentence: str, pos: int) -> str:
    start = sentence.rfind(",", 0, pos) + 1
    end = sentence.find(",", pos)
    return sentence[start : end if end >= 0 else len(sentence)]


def languages_required(lines: list[tuple[str, bool]]) -> list[LanguageRequirement]:
    """Language requirements on (line, in a preferred section) pairs; the strongest level and
    the strictest requirement win per language.

    Judged per sentence and clause: "Fluent in English, other European languages a plus" needs
    English. "Required" in the clause beats a "nice to have" heading. Two or more languages
    joined by "or" ("Thai, Vietnamese, or other ASEAN languages") are a choice, so none of them
    is required."""
    best: dict[str, LanguageRequirement] = {}
    for raw, preferred_section in lines:
        line = _norm(raw)
        for sentence in _SENTENCE.split(line):
            found = _matches(sentence)
            if not found:
                continue
            named = {LANGUAGES[m.group(1).casefold()] for m in _ANY_LANG.finditer(sentence)}
            choice = len(named) >= 2 and bool(_OR.search(sentence))
            for pos, code, level in found:
                clause = _clause_at(sentence, pos)
                req: Literal["required", "preferred"]
                if choice:
                    req = "preferred"
                elif _REQUIRED_IN_CLAUSE.search(clause) or (
                    # "Fluent French and business English is required": the sentence says it
                    _REQUIRED_IN_CLAUSE.search(sentence) and not _PREFERRED_INLINE.search(clause)
                ):
                    req = "required"
                elif preferred_section or _PREFERRED_INLINE.search(clause):
                    req = "preferred"
                else:
                    req = "required"
                cur = best.get(code)
                stricter = cur is None or (cur.requirement == "preferred" and req == "required")
                higher = (
                    cur is not None
                    and cur.requirement == req
                    and CEFR_ORDER.index(level) > CEFR_ORDER.index(cur.level)
                )
                if stricter or higher:
                    best[code] = LanguageRequirement(
                        language=code, level=level, requirement=req, evidence=_short(line)
                    )
    return [best[c] for c in sorted(best)]


# --- The posting's own language ---------------------------------------------------------------

_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the and of to in for with you our we are will is on as be your this that".split()
    ),
    "de": frozenset(
        "und der die das mit für wir sie ist eine ein zu auf den von im bei dich du".split()
    ),
    "fr": frozenset(
        "et le la les des de du pour avec vous nous une un est en sur dans au tu".split()
    ),
    "nl": frozenset("en de het een van voor met je wij jij zijn op te bij ons in naar".split()),
    "es": frozenset("y el la los las de del para con tu nuestro una un es en por que se".split()),
    "pt": frozenset("e o a os as de do da para com você nosso uma um é em por que se".split()),
    "it": frozenset("e il la le gli di del per con tu nostro una un è in che si sono".split()),
    "pl": frozenset("i w na z do się jest dla że nie oraz jak od przez naszego".split()),
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def posting_language(text: str) -> str | None:
    """The language most of the first 400 words are stopwords of, if it is clear: at least 15
    hits and twice the runner-up. Mixed or short texts give None."""
    words = [w.casefold() for w in _WORD.findall(text)[:400]]
    counts = sorted(
        ((sum(w in stop for w in words), code) for code, stop in _STOPWORDS.items()), reverse=True
    )
    (top, code), (second, _) = counts[0], counts[1]
    return code if top >= 15 and top >= 2 * second else None


# --- Visa sponsorship and the right to work ----------------------------------------------------

_SPONSOR_RULED_OUT = re.compile(
    r"\b(?:no|not|cannot|can't|can ?not|unable to|do not|don't|does not|doesn't|will not|won't|"
    r"are not able to|is not able to) (?:currently )?(?:able to )?"
    r"(?:(?:provide|offer|support|sponsor|consider) )?(?:any )?"
    r"(?:(?:visa|work permit|employment) )?sponsor(?:ship)?\b|"
    r"\bwithout (?:the need for )?(?:current or future )?(?:visa |employer )?sponsorship\b|"
    r"\bsponsorship (?:is |will )?(?:not|n't) (?:be )?(?:available|provided|offered|possible)\b|"
    r"\bmust (?:already )?(?:have|hold|possess) (?:the |a )?(?:full |valid |existing )?"
    r"(?:legal )?(?:right|authori[sz]ation|permission|permit) to work\b|"
    r"\bmust be (?:legally )?(?:authori[sz]ed|eligible|entitled) to work\b",
    re.IGNORECASE,
)
_SPONSOR_OFFERED = re.compile(
    r"\bvisa sponsorship (?:is )?(?:available|provided|offered|possible)\b|"
    r"\b(?:we|will|can|happy to) (?:offer|provide|support|sponsor)(?: full)?"
    r" (?:visa )?(?:sponsorship|your visa|visas|work permits?)\b|"
    r"\b(?:sponsor|sponsoring) (?:your |a |work )?(?:visa|work permit)s?\b|"
    r"\brelocation (?:package|support|assistance|bonus|allowance)\b|"
    r"\b(?:help|support|assist)(?: you)? with (?:your )?(?:relocation|visa)\b|"
    r"\brelocation (?:is |will be )?(?:provided|offered|covered|available|supported)\b",
    re.IGNORECASE,
)

Sponsorship = Literal["offered", "ruled_out"]


class SponsorshipStatement(BaseModel):
    stance: Sponsorship
    evidence: str


def sponsorship(lines: list[str]) -> SponsorshipStatement | None:
    """What the posting says about sponsoring a move; a refusal wins over an offer ("we do not
    sponsor visas, but help with relocation" cannot hire you if you need a visa)."""
    offered: str | None = None
    for line in map(_norm, lines):
        if _SPONSOR_RULED_OUT.search(line):
            return SponsorshipStatement(stance="ruled_out", evidence=_short(line))
        if offered is None and _SPONSOR_OFFERED.search(line):
            offered = line
    return SponsorshipStatement(stance="offered", evidence=_short(offered)) if offered else None


def _short(line: str, limit: int = 160) -> str:
    line = " ".join(line.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"
