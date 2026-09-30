"""Sector/subsector, stage and geography vocabularies shared by deal extraction and investor scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import GeoArea, Location
from app.utils.text import fold

# ------------------------------------------------------------------------------ sectors

# sector → (broad terms, {subsector: patterns}). Patterns are regexes matched case-insensitively
# on word boundaries. Subsector matches imply the sector.
SECTORS: dict[str, tuple[list[str], dict[str, list[str]]]] = {
    "Healthcare & Life Sciences": (
        [r"health ?care", r"life sciences?", r"medical", r"health"],
        {
            "Digital Therapeutics": [r"digital therapeutics?", r"DTx", r"prescription digital", r"software as a medical device", r"SaMD"],
            "Digital Health": [r"digital health", r"health ?tech", r"tele ?health", r"telemedicine", r"remote patient monitoring",
                               r"RPM", r"virtual care", r"m-?health"],
            "Medical Devices": [r"medical devices?", r"med ?tech", r"medical wearables?", r"implantables?"],
            "Diagnostics": [r"diagnostics?", r"in vitro diagnostics?", r"IVD", r"point[- ]of[- ]care testing"],
            "Biotech & Therapeutics": [r"biotech(?:nology)?", r"(?<!digital )therapeutics", r"drug discovery", r"biopharma",
                                       r"pharmaceuticals?", r"gene therap(?:y|ies)", r"biologics"],
            "Healthcare IT": [r"health(?:care)? IT", r"EHR", r"revenue cycle", r"clinical workflow", r"health data"],
            "Cardiovascular": [r"cardiac", r"cardiology", r"cardiovascular", r"heart (?:failure|disease|health)",
                               r"cardiometabolic", r"hypertension"],
            "Behavioral Health": [r"mental health", r"behavioral health", r"behavioural health", r"psychiatr\w*"],
            "Women's Health": [r"fem ?tech", r"women'?s health", r"maternal health", r"fertility"],
            "Aging & Senior Care": [r"aging", r"senior care", r"elder ?care", r"longevity"],
        },
    ),
    "Fintech": (
        [r"fin ?tech", r"financial services", r"financial technology"],
        {
            "Payments": [r"payments?", r"payment processing"],
            "Lending & Credit": [r"lending", r"credit", r"loans?"],
            "Insurtech": [r"insur ?tech", r"insurance"],
            "Wealth & Investing": [r"wealth ?tech", r"wealth management", r"investing platform", r"robo-?advis\w+"],
            "Banking Infrastructure": [r"neo ?banks?", r"banking[- ]as[- ]a[- ]service", r"BaaS", r"core banking"],
            "Crypto & Web3": [r"crypto\w*", r"blockchain", r"web ?3", r"defi"],
            "Regtech & Compliance": [r"reg ?tech", r"compliance automation", r"KYC", r"AML"],
        },
    ),
    "Enterprise Software": (
        [r"enterprise software", r"B2B software", r"SaaS", r"software"],
        {
            "Cybersecurity": [r"cyber ?security", r"infosec", r"security software", r"identity management"],
            "Developer Tools": [r"developer tools", r"dev ?tools", r"dev ?ops"],
            "HR & Future of Work": [r"HR ?tech", r"future of work", r"workforce management", r"recruiting software"],
            "Marketing & Sales Tech": [r"mar ?tech", r"sales ?tech", r"sales enablement", r"ad ?tech", r"CRM"],
            "Data & Analytics": [r"data infrastructure", r"analytics", r"business intelligence", r"data platform"],
            "Vertical SaaS": [r"vertical SaaS"],
        },
    ),
    "Artificial Intelligence": (
        [r"artificial intelligence", r"AI", r"machine learning", r"ML"],
        {
            "Generative AI": [r"generative AI", r"gen ?AI", r"LLMs?", r"large language models?"],
            "Computer Vision": [r"computer vision"],
            "AI Infrastructure": [r"ML ?ops", r"AI infrastructure", r"ML infrastructure"],
        },
    ),
    "Climate & Energy": (
        [r"climate ?tech", r"climate", r"clean ?tech", r"energy", r"sustainability"],
        {
            "Clean Energy": [r"renewables?", r"solar", r"wind energy", r"clean energy", r"geothermal"],
            "Energy Storage": [r"energy storage", r"batter(?:y|ies)"],
            "Carbon Management": [r"carbon capture", r"carbon removal", r"decarboni[sz]ation", r"carbon accounting"],
            "Mobility & EV": [r"electric vehicles?", r"EVs?", r"e-?mobility", r"charging infrastructure"],
            "Water": [r"water tech", r"water treatment"],
        },
    ),
    "Agtech & Food": (
        [r"agri(?:culture)?", r"food", r"ag ?tech"],
        {
            "Precision Agriculture": [r"precision agriculture", r"farm management"],
            "Alternative Protein": [r"alt(?:ernative)? proteins?", r"plant[- ]based", r"cultivated meat"],
            "Food Tech": [r"food ?tech", r"food safety"],
        },
    ),
    "Consumer": (
        [r"consumer", r"B2C"],
        {
            "CPG": [r"CPG", r"consumer packaged goods", r"beverages?"],
            "E-commerce & DTC": [r"e-?commerce", r"DTC", r"direct[- ]to[- ]consumer", r"marketplaces?"],
            "Consumer Apps": [r"consumer apps?", r"social apps?"],
            "Beauty & Wellness": [r"beauty", r"wellness", r"personal care"],
        },
    ),
    "Education": (
        [r"ed ?tech", r"education"],
        {
            "K-12": [r"K-?12"],
            "Higher Education": [r"higher ed(?:ucation)?"],
            "Workforce Upskilling": [r"upskilling", r"workforce development", r"reskilling"],
        },
    ),
    "Real Estate & Proptech": (
        [r"real estate", r"prop ?tech"],
        {"Construction Tech": [r"construction ?tech", r"contech"], "Property Management": [r"property management"]},
    ),
    "Industrial & Deep Tech": (
        [r"industrial", r"deep ?tech", r"hardware", r"manufacturing"],
        {
            "Robotics": [r"robotics?", r"automation hardware"],
            "Advanced Manufacturing": [r"advanced manufacturing", r"3D printing", r"additive manufacturing"],
            "Semiconductors": [r"semiconductors?", r"chips?"],
            "Quantum": [r"quantum"],
            "Space": [r"space ?tech", r"aerospace", r"satellites?"],
            "Supply Chain & Logistics": [r"supply chain", r"logistics", r"freight"],
            "Advanced Materials": [r"advanced materials", r"materials science"],
        },
    ),
    "Media & Gaming": (
        [r"media", r"entertainment"],
        {"Gaming": [r"gaming", r"video games?", r"esports"], "Creator Economy": [r"creator economy", r"creators?"]},
    ),
    "Govtech & Defense": (
        [r"gov ?tech", r"public sector", r"defen[cs]e"],
        {"Defense Tech": [r"defen[cs]e tech", r"dual[- ]use", r"national security"],
         "Public Safety": [r"public safety"]},
    ),
}

GENERALIST = [r"generalist", r"sector[- ]agnostic", r"industry[- ]agnostic", r"all sectors", r"any sector",
              r"diversified", r"technology", r"tech", r"multi[- ]sector", r"opportunistic"]

# Case-sensitive acronyms (so "ai" inside words or "ml" in "html" never match).
_CASE_SENSITIVE = {"AI", "ML", "DTx", "RPM", "IVD", "EHR", "BaaS", "KYC", "AML", "CPG", "DTC", "EVs?", "SaMD", "CRM",
                   "LLMs?", "B2C"}


def _compile(pattern: str) -> re.Pattern[str]:
    flags = 0 if pattern in _CASE_SENSITIVE else re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", flags)


_SUB_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (sector, sub, _compile(p)) for sector, (_b, subs) in SECTORS.items() for sub, pats in subs.items() for p in pats
]
_BROAD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (sector, _compile(p)) for sector, (broad, _s) in SECTORS.items() for p in broad
]
_GENERALIST = [_compile(p) for p in GENERALIST]

SECTOR_NAMES = list(SECTORS)
SUBSECTORS_BY_SECTOR = {sector: list(subs) for sector, (_b, subs) in SECTORS.items()}
SECTOR_OF_SUBSECTOR = {sub: sector for sector, subs in SUBSECTORS_BY_SECTOR.items() for sub in subs}


@dataclass
class SectorTags:
    """Parsed investor sector focus."""

    subsectors: set[tuple[str, str]] = field(default_factory=set)   # (sector, subsector)
    sectors: set[str] = field(default_factory=set)                  # broad sector terms
    generalist: bool = False
    unrecognized: list[str] = field(default_factory=list)

    @property
    def known(self) -> bool:
        return bool(self.subsectors or self.sectors or self.generalist)


def parse_sector_focus(*texts: str) -> SectorTags:
    """Classify each listed focus item; unrecognized items are kept for the evidence log."""
    tags = SectorTags()
    for text in texts:
        for item in re.split(r"\s*[,;|\n•/]\s*|\s+and\s+|\s*&\s*(?=[A-Z])", text or ""):
            item = item.strip(" .")
            if not item:
                continue
            subs = {(sector, sub) for sector, sub, pat in _SUB_PATTERNS if pat.search(item)}
            if subs:
                tags.subsectors |= subs
                continue
            broad = {sector for sector, pat in _BROAD_PATTERNS if pat.search(item)}
            if broad:
                tags.sectors |= broad
                continue
            if any(p.search(item) for p in _GENERALIST):
                tags.generalist = True
                continue
            tags.unrecognized.append(item)
    return tags


def scan_sector_hits(text: str) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """Occurrence counts of sector and subsector vocabulary in free text (deck classification)."""
    sector_hits: dict[str, int] = {}
    sub_hits: dict[tuple[str, str], int] = {}
    for sector, sub, pat in _SUB_PATTERNS:
        n = len(pat.findall(text))
        if n:
            sub_hits[(sector, sub)] = sub_hits.get((sector, sub), 0) + n
            sector_hits[sector] = sector_hits.get(sector, 0) + 2 * n
    for sector, pat in _BROAD_PATTERNS:
        n = len(pat.findall(text))
        if n:
            sector_hits[sector] = sector_hits.get(sector, 0) + n
    return sector_hits, sub_hits


def match_sector_name(text: str) -> tuple[str | None, str | None]:
    """Explicit 'Sector: …' value → (sector, subsector)."""
    tags = parse_sector_focus(text)
    if tags.subsectors:
        sector, sub = sorted(tags.subsectors)[0]
        return sector, sub
    if tags.sectors:
        return sorted(tags.sectors)[0], None
    return None, None


# ------------------------------------------------------------------------------ stages

STAGES = ["Pre-seed", "Seed", "Series A", "Series B", "Series C", "Growth"]
STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}
EARLY_STAGES = {"Pre-seed", "Seed", "Series A"}
LATE_ONLY = {"Series C", "Growth"}

_STAGE_TOKENS: list[tuple[str, re.Pattern[str]]] = [
    ("Pre-seed", re.compile(r"\bpre[- ]?seed\b", re.I)),
    ("Seed", re.compile(r"(?<!pre-)(?<!pre )(?<!pre)\bseed\b", re.I)),
    ("Series A", re.compile(r"\bseries[- ]a\b", re.I)),
    ("Series B", re.compile(r"\bseries[- ]b\b", re.I)),
    ("Series C", re.compile(r"\bseries[- ][c-f]\b", re.I)),
    ("Growth", re.compile(r"\b(?:growth(?:[- ]stage)?|late[- ]stage|expansion|pre[- ]ipo|mezzanine)\b", re.I)),
]
_EARLY_BROAD = re.compile(r"\bearly[- ]?stage\b|\bearly\b|\bventure[- ]stage\b", re.I)
_AGNOSTIC = re.compile(r"\ball stages\b|\bstage[- ]agnostic\b|\bany stage\b|\bmulti[- ]stage\b", re.I)
_RANGE_JOIN = re.compile(r"^\s*(?:-|–|—|to|through|thru|until)\s*$", re.I)
_PLUS = re.compile(r"^\s*(?:\+|and (?:later|above|beyond)|onward)", re.I)


@dataclass
class StageFocus:
    named: set[str] = field(default_factory=set)
    early_broad: bool = False
    agnostic: bool = False

    @property
    def known(self) -> bool:
        return bool(self.named or self.early_broad or self.agnostic)

    @property
    def all_stages(self) -> set[str]:
        out = set(self.named)
        if self.early_broad:
            out |= EARLY_STAGES
        if self.agnostic:
            out |= set(STAGES)
        return out


def stage_mentions(text: str) -> list[tuple[int, int, str]]:
    found = []
    for stage, pat in _STAGE_TOKENS:
        for m in pat.finditer(text or ""):
            found.append((m.start(), m.end(), stage))
    found.sort()
    return found


def parse_stage_focus(text: str) -> StageFocus:
    focus = StageFocus()
    text = text or ""
    if _AGNOSTIC.search(text):
        focus.agnostic = True
    mentions = stage_mentions(text)
    for i, (_s, end, stage) in enumerate(mentions):
        focus.named.add(stage)
        if i + 1 < len(mentions) and _RANGE_JOIN.match(text[end:mentions[i + 1][0]]):
            lo, hi = STAGE_INDEX[stage], STAGE_INDEX[mentions[i + 1][2]]
            focus.named |= set(STAGES[min(lo, hi): max(lo, hi) + 1])
        if _PLUS.match(text[end:end + 16]):
            focus.named |= set(STAGES[STAGE_INDEX[stage]:])
    stripped = text
    for start, end, _stage in reversed(mentions):
        stripped = stripped[:start] + " " + stripped[end:]
    if _EARLY_BROAD.search(stripped):
        focus.early_broad = True
    return focus


def normalize_stage(text: str) -> str | None:
    mentions = stage_mentions(text)
    return mentions[0][2] if mentions else None


# ------------------------------------------------------------------------------ geography

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
US_ABBR = set(US_STATES.values())
CA_PROVINCES = {"ontario": "ON", "quebec": "QC", "british columbia": "BC", "alberta": "AB", "manitoba": "MB",
                "saskatchewan": "SK", "nova scotia": "NS"}

COUNTRIES = {
    "united states": "US", "usa": "US", "u.s.a.": "US", "u.s.": "US", "us": "US", "america": "US",
    "canada": "CA", "mexico": "MX", "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "england": "GB",
    "germany": "DE", "france": "FR", "netherlands": "NL", "ireland": "IE", "spain": "ES", "italy": "IT",
    "sweden": "SE", "switzerland": "CH", "denmark": "DK", "norway": "NO", "finland": "FI", "israel": "IL",
    "india": "IN", "singapore": "SG", "japan": "JP", "china": "CN", "australia": "AU", "new zealand": "NZ",
    "brazil": "BR", "chile": "CL", "colombia": "CO", "argentina": "AR", "united arab emirates": "AE",
    "uae": "AE", "saudi arabia": "SA", "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "south korea": "KR",
}
COUNTRY_NAMES = {"US": "United States", "CA": "Canada", "GB": "United Kingdom"}

REGIONS = {
    "north america": {"US", "CA", "MX"},
    "europe": {"GB", "DE", "FR", "NL", "IE", "ES", "IT", "SE", "CH", "DK", "NO", "FI"},
    "latin america": {"MX", "BR", "CL", "CO", "AR"}, "latam": {"MX", "BR", "CL", "CO", "AR"},
    "asia pacific": {"IN", "SG", "JP", "CN", "AU", "NZ", "KR"}, "apac": {"IN", "SG", "JP", "CN", "AU", "NZ", "KR"},
    "asia": {"IN", "SG", "JP", "CN", "KR"},
    "middle east": {"IL", "AE", "SA"}, "mena": {"IL", "AE", "SA"}, "africa": {"ZA", "NG", "KE"},
    "emea": {"GB", "DE", "FR", "NL", "IE", "ES", "IT", "SE", "CH", "DK", "NO", "FI", "IL", "AE", "SA", "ZA", "NG", "KE"},
}
US_SUBREGIONS = {
    "southwest": {"TX", "AZ", "NM", "OK", "NV"},
    "southeast": {"FL", "GA", "NC", "SC", "TN", "AL", "MS", "LA", "AR", "KY", "VA"},
    "midwest": {"IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND", "OH", "SD", "WI"},
    "northeast": {"NY", "MA", "CT", "RI", "VT", "NH", "ME", "NJ", "PA"},
    "new england": {"MA", "CT", "RI", "VT", "NH", "ME"},
    "mid atlantic": {"NY", "NJ", "PA", "DE", "MD", "DC", "VA"},
    "west coast": {"CA", "OR", "WA"}, "pacific northwest": {"OR", "WA"},
    "mountain west": {"CO", "UT", "ID", "MT", "WY", "NV", "AZ", "NM"},
    "rocky mountain": {"CO", "UT", "ID", "MT", "WY"},
    "gulf coast": {"TX", "LA", "MS", "AL", "FL"},
    "bay area": {"CA"}, "silicon valley": {"CA"}, "sun belt": {"TX", "FL", "GA", "AZ", "NC", "SC", "TN", "NV"},
    "texas triangle": {"TX"},
}
CITIES = {
    "austin": "TX", "houston": "TX", "dallas": "TX", "san antonio": "TX", "fort worth": "TX",
    "boston": "MA", "cambridge": "MA", "new york": "NY", "nyc": "NY", "brooklyn": "NY", "san francisco": "CA",
    "los angeles": "CA", "san diego": "CA", "palo alto": "CA", "menlo park": "CA", "san jose": "CA",
    "seattle": "WA", "portland": "OR", "denver": "CO", "boulder": "CO", "chicago": "IL", "atlanta": "GA",
    "miami": "FL", "tampa": "FL", "orlando": "FL", "nashville": "TN", "raleigh": "NC", "durham": "NC",
    "charlotte": "NC", "minneapolis": "MN", "detroit": "MI", "pittsburgh": "PA", "philadelphia": "PA",
    "salt lake city": "UT", "phoenix": "AZ", "scottsdale": "AZ", "las vegas": "NV", "columbus": "OH",
    "cleveland": "OH", "st. louis": "MO", "kansas city": "MO", "baltimore": "MD", "washington dc": "DC",
    "new orleans": "LA", "oklahoma city": "OK", "albuquerque": "NM", "madison": "WI", "indianapolis": "IN",
}
INTL_CITIES = {"london": "GB", "toronto": "CA", "vancouver": "CA", "montreal": "CA", "berlin": "DE",
               "paris": "FR", "amsterdam": "NL", "tel aviv": "IL", "singapore": "SG", "sydney": "AU",
               "dublin": "IE", "zurich": "CH", "bangalore": "IN", "mumbai": "IN", "dubai": "AE"}
_GLOBAL = re.compile(r"\b(global|worldwide|international|any geography|anywhere|no geographic)\b", re.I)


def _word_in(needle: str, hay: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", hay) is not None


def parse_location(text: str | None) -> Location | None:
    """'Austin, TX' / 'Boston, Massachusetts, USA' / 'London' → Location."""
    raw = (text or "").strip()
    if not raw:
        return None
    low = fold(raw)
    city = state = country = None
    abbr = re.search(r",\s*([A-Z]{2})\b", raw) or re.fullmatch(r"\s*([A-Z]{2})\s*", raw)
    if abbr and abbr.group(1) in US_ABBR:
        state, country = abbr.group(1), "US"
    if state is None:
        for name, code in sorted(US_STATES.items(), key=lambda kv: -len(kv[0])):
            if _word_in(name, low) and not (name == "washington" and "washington dc" in low):
                state, country = code, "US"
                break
    if state is None:
        for name, code in CA_PROVINCES.items():
            if _word_in(name, low):
                state, country = code, "CA"
    for name, st in sorted(CITIES.items(), key=lambda kv: -len(kv[0])):
        if _word_in(name, low):
            if state is None or state == st:
                city, state, country = name.title(), st, "US"
                break
    if city is None:
        for name, code in INTL_CITIES.items():
            if _word_in(name, low):
                city, country = name.title(), country or code
                break
    if country is None:
        for name, code in sorted(COUNTRIES.items(), key=lambda kv: -len(kv[0])):
            if name in {"us", "uk"}:
                if re.search(rf"\b{name.upper()}\b", raw):
                    country = code
                    break
            elif _word_in(name, low):
                country = code
                break
    if city is None and state is None and country is None:
        return None
    return Location(raw=raw, city=city, state=state, country=country)


def parse_geo_focus(text: str | None) -> list[GeoArea]:
    areas: list[GeoArea] = []
    raw = text or ""
    low = fold(raw)
    if _GLOBAL.search(low):
        areas.append(GeoArea(kind="global", name="Global"))
    for name, states in US_SUBREGIONS.items():
        if _word_in(name, low.replace("-", " ")):
            areas.append(GeoArea(kind="subregion", name=name.title(), states=frozenset(states),
                                 countries=frozenset({"US"})))
    for name, countries in REGIONS.items():
        if _word_in(name, low.replace("-", " ")):
            areas.append(GeoArea(kind="region", name=name.title(), countries=frozenset(countries)))
    for name, st in CITIES.items():
        if _word_in(name, low):
            areas.append(GeoArea(kind="city", name=name.title(), city=name.title(), states=frozenset({st}),
                                 countries=frozenset({"US"})))
    for name, code in US_STATES.items():
        if _word_in(name, low) and not (name == "washington" and "washington dc" in low):
            if not any(a.kind == "city" and code in a.states and a.name.lower() == name for a in areas):
                areas.append(GeoArea(kind="state", name=name.title(), states=frozenset({code}),
                                     countries=frozenset({"US"})))
    for m in re.finditer(r"\b([A-Z]{2})\b", raw):
        if m.group(1) in US_ABBR and m.group(1) not in {"US", "IN", "ME", "OR", "OK", "HI"}:
            areas.append(GeoArea(kind="state", name=m.group(1), states=frozenset({m.group(1)}),
                                 countries=frozenset({"US"})))
    for name, code in COUNTRIES.items():
        if name in {"us", "uk"}:
            hit = re.search(rf"\b{name.upper()}\b", raw) is not None
        elif name == "america":
            hit = _word_in(name, low) and "north america" not in low and "latin america" not in low
        else:
            hit = _word_in(name, low)
        if hit:
            areas.append(GeoArea(kind="country", name=COUNTRY_NAMES.get(code, name.title()),
                                 countries=frozenset({code})))
    unique: dict[tuple, GeoArea] = {}
    for a in areas:
        unique.setdefault((a.kind, a.states, a.countries, a.city), a)
    return list(unique.values())


def area_contains(area: GeoArea, loc: Location) -> bool | None:
    """True/False when decidable; None when the location lacks the needed detail."""
    if area.kind == "global":
        return True
    if area.kind in {"region", "country"}:
        return None if loc.country is None else loc.country in area.countries
    if area.kind in {"subregion", "state"}:
        if loc.country and loc.country not in area.countries:
            return False
        return None if loc.state is None else loc.state in area.states
    if area.kind == "city":
        if loc.state and loc.state not in area.states:
            return False
        if loc.city is None:
            return None
        return fold(loc.city) == fold(area.city or "")
    return None


GEO_SPECIFICITY = {"city": "local", "state": "local", "subregion": "local", "country": "country",
                   "region": "region", "global": "global"}
