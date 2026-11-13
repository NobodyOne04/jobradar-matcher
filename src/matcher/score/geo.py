"""Which countries a location phrase covers, so "Germany" in a profile matches a job open to
"Europe" or "Worldwide". A name not in these tables covers nothing known: it never causes a
mismatch, only an unknown.

shortcut: covers Europe, North America, LATAM and APAC countries common in remote hiring;
extend COUNTRIES when real postings or profiles name others.
"""

import re

# ISO 3166-1 alpha-2 -> (name, regions). Regions: Europe, EU, EMEA, North America, Americas,
# LATAM, APAC, SEA (Southeast Asia).
COUNTRIES: dict[str, tuple[str, frozenset[str]]] = {
    code: (name, frozenset(regions.split()))
    for code, name, regions in [
        ("AT", "Austria", "Europe EU EMEA"),
        ("BE", "Belgium", "Europe EU EMEA"),
        ("BG", "Bulgaria", "Europe EU EMEA"),
        ("HR", "Croatia", "Europe EU EMEA"),
        ("CY", "Cyprus", "Europe EU EMEA"),
        ("CZ", "Czechia", "Europe EU EMEA"),
        ("DK", "Denmark", "Europe EU EMEA"),
        ("EE", "Estonia", "Europe EU EMEA"),
        ("FI", "Finland", "Europe EU EMEA"),
        ("FR", "France", "Europe EU EMEA"),
        ("DE", "Germany", "Europe EU EMEA"),
        ("GR", "Greece", "Europe EU EMEA"),
        ("HU", "Hungary", "Europe EU EMEA"),
        ("IE", "Ireland", "Europe EU EMEA"),
        ("IT", "Italy", "Europe EU EMEA"),
        ("LV", "Latvia", "Europe EU EMEA"),
        ("LT", "Lithuania", "Europe EU EMEA"),
        ("LU", "Luxembourg", "Europe EU EMEA"),
        ("MT", "Malta", "Europe EU EMEA"),
        ("NL", "Netherlands", "Europe EU EMEA"),
        ("PL", "Poland", "Europe EU EMEA"),
        ("PT", "Portugal", "Europe EU EMEA"),
        ("RO", "Romania", "Europe EU EMEA"),
        ("SK", "Slovakia", "Europe EU EMEA"),
        ("SI", "Slovenia", "Europe EU EMEA"),
        ("ES", "Spain", "Europe EU EMEA"),
        ("SE", "Sweden", "Europe EU EMEA"),
        ("GB", "United Kingdom", "Europe EMEA"),
        ("CH", "Switzerland", "Europe EMEA"),
        ("NO", "Norway", "Europe EMEA"),
        ("IS", "Iceland", "Europe EMEA"),
        ("RS", "Serbia", "Europe EMEA"),
        ("UA", "Ukraine", "Europe EMEA"),
        ("TR", "Turkey", "Europe EMEA"),
        ("AE", "United Arab Emirates", "EMEA"),
        ("IL", "Israel", "EMEA"),
        ("ZA", "South Africa", "EMEA"),
        ("EG", "Egypt", "EMEA"),
        ("US", "United States", "North America Americas"),
        ("CA", "Canada", "North America Americas"),
        ("MX", "Mexico", "North America Americas LATAM"),
        ("BR", "Brazil", "Americas LATAM"),
        ("AR", "Argentina", "Americas LATAM"),
        ("CO", "Colombia", "Americas LATAM"),
        ("CL", "Chile", "Americas LATAM"),
        ("PE", "Peru", "Americas LATAM"),
        ("UY", "Uruguay", "Americas LATAM"),
        ("IN", "India", "APAC"),
        ("SG", "Singapore", "APAC SEA"),
        ("AU", "Australia", "APAC"),
        ("NZ", "New Zealand", "APAC"),
        ("JP", "Japan", "APAC"),
        ("PH", "Philippines", "APAC SEA"),
        ("VN", "Vietnam", "APAC SEA"),
        ("ID", "Indonesia", "APAC SEA"),
        ("MY", "Malaysia", "APAC SEA"),
        ("TH", "Thailand", "APAC SEA"),
        ("KH", "Cambodia", "APAC SEA"),
        ("SA", "Saudi Arabia", "EMEA"),
        ("CR", "Costa Rica", "Americas LATAM"),
        ("MM", "Myanmar", "APAC SEA"),
        ("CN", "China", "APAC"),
        ("PK", "Pakistan", "APAC"),
        ("BD", "Bangladesh", "APAC"),
        ("LK", "Sri Lanka", "APAC"),
        ("KR", "South Korea", "APAC"),
        ("TW", "Taiwan", "APAC"),
        ("HK", "Hong Kong", "APAC"),
    ]
}
ALL = frozenset(COUNTRIES)
_BY_NAME = {name.casefold(): code for code, (name, _) in COUNTRIES.items()}
_ALIASES = {
    "us": "US",
    "usa": "US",
    "uk": "GB",
    "u.k.": "GB",
    "great britain": "GB",
    "england": "GB",
    "czech republic": "CZ",
    "holland": "NL",
    "the netherlands": "NL",
    "uae": "AE",
    # Cities and states that postings give as their only location (from the jobs in the
    # database, 2026-11); a city means the job is there, not open to its country's region.
    "new york": "US",
    "new york city": "US",
    "nyc": "US",
    "san francisco": "US",
    "california": "US",
    "washington": "US",
    "boston": "US",
    "massachusetts": "US",
    "mountain view": "US",
    "palo alto": "US",
    "oakland": "US",
    "seattle": "US",
    "bellevue": "US",
    "denver": "US",
    "colorado": "US",
    "austin": "US",
    "dallas": "US",
    "texas": "US",
    "chicago": "US",
    "illinois": "US",
    "atlanta": "US",
    "los angeles": "US",
    "virginia": "US",
    "toronto": "CA",
    "london": "GB",
    "dublin": "IE",
    "paris": "FR",
    "berlin": "DE",
    "amsterdam": "NL",
    "stockholm": "SE",
    "bengaluru": "IN",
    "bangalore": "IN",
    "gurugram": "IN",
    "tokyo": "JP",
    "seoul": "KR",
    "sydney": "AU",
    # the remaining US states (Georgia is left out: also a country)
    "alabama": "US",
    "alaska": "US",
    "arizona": "US",
    "arkansas": "US",
    "connecticut": "US",
    "delaware": "US",
    "florida": "US",
    "hawaii": "US",
    "idaho": "US",
    "indiana": "US",
    "iowa": "US",
    "kansas": "US",
    "kentucky": "US",
    "louisiana": "US",
    "maine": "US",
    "maryland": "US",
    "michigan": "US",
    "minnesota": "US",
    "mississippi": "US",
    "missouri": "US",
    "montana": "US",
    "nebraska": "US",
    "nevada": "US",
    "new hampshire": "US",
    "new jersey": "US",
    "new mexico": "US",
    "north carolina": "US",
    "north dakota": "US",
    "ohio": "US",
    "oklahoma": "US",
    "oregon": "US",
    "pennsylvania": "US",
    "rhode island": "US",
    "south carolina": "US",
    "south dakota": "US",
    "tennessee": "US",
    "utah": "US",
    "vermont": "US",
    "west virginia": "US",
    "wisconsin": "US",
    "wyoming": "US",
    "philadelphia": "US",
    "raleigh": "US",
    "charlotte": "US",
    "miami": "US",
    "portland": "US",
    "usca": "US",
    "são paulo": "BR",
    "sao paulo": "BR",
    "ksa": "SA",
}
_REGION_NAMES = {
    "europe": "Europe",
    "european union": "EU",
    "eu": "EU",
    "eea": "EU",
    "emea": "EMEA",
    "north america": "North America",
    "americas": "Americas",
    "latam": "LATAM",
    "latin america": "LATAM",
    "amer": "Americas",
    "apac": "APAC",
    "asia pacific": "APAC",
    "asia-pacific": "APAC",
    "asia": "APAC",
    "southeast asia": "SEA",
    "south east asia": "SEA",
}
_WORLDWIDE = {"worldwide", "anywhere", "global", "globally"}


def region_countries(region: str) -> frozenset[str]:
    if region.casefold() in _WORLDWIDE:
        return ALL
    key = _REGION_NAMES.get(region.casefold(), region)
    return frozenset(c for c, (_, regions) in COUNTRIES.items() if key in regions)


def covers(phrase: str) -> frozenset[str]:
    """ISO codes a single location name covers: a country, a region, or worldwide."""
    p = phrase.strip().casefold()
    if p in _WORLDWIDE:
        return ALL
    if p in _REGION_NAMES:
        return region_countries(p)
    code = _BY_NAME.get(p) or _ALIASES.get(p) or (p.upper() if p.upper() in COUNTRIES else None)
    return frozenset({code}) if code else frozenset()


_NAMES = re.compile(
    r"\b("
    + "|".join(
        re.escape(n)
        for n in sorted([*_BY_NAME, *_ALIASES, *_REGION_NAMES, *_WORLDWIDE], key=len, reverse=True)
    )
    + r")\b",
    re.IGNORECASE,
)


def mentioned(text: str) -> frozenset[str]:
    """ISO codes covered by every country, region or "worldwide" named in free text."""
    out: set[str] = set()
    for m in _NAMES.finditer(text):
        word = m.group(1)
        if word.lower() in ("us", "eu", "uk") and not word.isupper():
            continue  # "us" the pronoun, not the United States
        out |= covers(word)
    return frozenset(out)
