"""Deterministic deal-profile extraction from deck text, with slide references on every fact.

Rules:
* Only what the deck states is reported; everything else is "not stated in deck".
* Several different values for one field → CONFLICT (no value chosen; the user resolves it).
* Remaining allocation is calculated only when raise and commitment are single, unconflicted
  values in the same currency that refer to the same round (and the same as-of date, if dated).
* Signed/committed money and soft interest are separate fields; soft interest is never subtracted.
* User overrides are stored beside the deck facts, never over them.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from app.extraction import taxonomy as tx
from app.extraction.parsing import date_mentions, money_mentions, parse_money
from app.ingestion.deck import DeckDocument
from app.models import (
    DEAL_FIELDS,
    NOT_STATED_TEXT,
    Candidate,
    DealProfile,
    Fact,
    FactStatus,
    GeoArea,
    Location,
    Money,
    Override,
    SourceRef,
)
from app.utils.text import normalize_org, truncate

# ------------------------------------------------------------------------------ lines


@dataclass
class Line:
    text: str
    page: int
    locator: str

    def ref(self, excerpt: str | None = None) -> SourceRef:
        return SourceRef(file="", locator=self.locator, excerpt=truncate(excerpt or self.text, 160))


def _lines(deck: DeckDocument) -> list[Line]:
    out = []
    for page in deck.pages:
        for segment, text in page.segments():
            for raw in text.split("\n"):
                raw = raw.strip()
                if raw:
                    out.append(Line(raw, page.number, deck.locator(page.number, segment)))
    return out


# ------------------------------------------------------------------------------ money classification

_CLASSES: list[tuple[str, re.Pattern[str]]] = [
    ("ignore", re.compile(
        r"valuation|\bcap\b|pre-money|post-money|\bTAM\b|\bSAM\b|\bSOM\b|\bmarket\b|revenue|\bARR\b|\bMRR\b|"
        r"\bgrants?\b|salar\w*|budget|\bcosts?\b|\bpric\w*|\bper\b|use of (?:funds|proceeds)|runway|\bburn\b|"
        r"savings|reimburs\w*|\bsales\b|EBITDA|margin|\bspend\b|\bfee\b", re.I)),
    ("prior", re.compile(r"\braised\b|\bto date\b|\bpreviously\b|\bprior (?:round|funding|raise)\b|\bhistoric", re.I)),
    ("soft", re.compile(r"soft[- ]?circled|soft[- ]?commit\w*|soft interest|verbal\w*|indications? of interest|"
                        r"\bIOIs?\b|\binterest\b|\bpipeline\b|\bLOIs?\b|\bpending\b|in diligence", re.I)),
    ("signed", re.compile(r"\bsigned\b|\bclosed\b|\bfunded\b|\breceived\b|\bwired\b|\bexecuted\b|in the bank|"
                          r"\bsecured\b", re.I)),
    ("committed", re.compile(r"\bcommitted\b|\bcommitments?\b", re.I)),
    ("remaining", re.compile(r"\bremaining\b|\bremains\b|\bavailable\b|\bleft\b|\bbalance\b|still open|"
                             r"open allocation|to be raised|\bunallocated\b", re.I)),
    ("raise", re.compile(r"\braising\b|\bseeking\b|\bthe ask\b|\bask\b|round size|\braise\b|target raise|"
                         r"\boffering\b|\bround\b|\bSAFE\b|convertible note", re.I)),
]
_CLASS_PRIORITY = {name: i for i, (name, _p) in enumerate(_CLASSES)}
_SEPARATORS = re.compile(r"[|;•\n]|,\s|\s[–—-]\s|\.\s")
_FUTURE = re.compile(r"\bnext round\b|\bfuture\b|\bnext raise\b|\bfollow-on\b|\bsubsequent\b|\bplanned\b|"
                     r"\bwill raise\b|\bseries [a-c] in 20\d\d\b", re.I)
_SAME_ROUND = re.compile(r"\bthis round\b|\bcurrent round\b|\bof which\b|\btoward[s]?\b|\bof the round\b|"
                         r"\bin the round\b|\bthis raise\b", re.I)
_AS_OF = re.compile(r"\bas of\b", re.I)
WINDOW = 45


def _classify(text: str, start: int, end: int, prev_end: int, next_start: int) -> str | None:
    after = text[end:min(next_start, end + WINDOW)]
    cut = _SEPARATORS.search(after)
    if cut:
        after = after[:cut.start()]
    before = text[max(prev_end, start - WINDOW):start]
    cuts = list(_SEPARATORS.finditer(before))
    if cuts:
        before = before[cuts[-1].end():]
    best: tuple[float, int, str] | None = None
    for name, pat in _CLASSES:
        for m in pat.finditer(after):
            key = (m.start(), _CLASS_PRIORITY[name], name)
            best = min(best, key) if best else key
        for m in pat.finditer(before):
            key = (len(before) - m.end() + 3, _CLASS_PRIORITY[name], name)
            best = min(best, key) if best else key
    return best[2] if best else None


@dataclass
class MoneyHit:
    kind: str
    money: Money
    line: Line
    round_label: str | None
    as_of: str | None
    same_round_hint: bool
    future: bool


def _round_label(text: str) -> str | None:
    stages = {s for _a, _b, s in tx.stage_mentions(text) if s != "Growth"}
    if re.search(r"\bbridge\b", text, re.I):
        stages.add("Bridge")
    return sorted(stages)[0] if len(stages) == 1 else (None if not stages else "/".join(sorted(stages)))


def _money_hits(lines: list[Line]) -> list[MoneyHit]:
    hits = []
    for line in lines:
        mentions = money_mentions(line.text)
        for i, m in enumerate(mentions):
            prev_end = mentions[i - 1].end if i else 0
            next_start = mentions[i + 1].start if i + 1 < len(mentions) else len(line.text)
            kind = _classify(line.text, m.start, m.end, prev_end, next_start)
            if kind is None or kind == "ignore":
                continue
            if kind == "committed" and re.search(r"\bsigned\b|\bexecuted\b|\bfunded\b|\bwired\b|\breceived\b",
                                                  line.text[prev_end:next_start], re.I):
                kind = "signed"
            as_of = None
            if _AS_OF.search(line.text):
                dates = date_mentions(line.text)
                as_of = dates[0].display if dates else None
            hits.append(MoneyHit(kind, m.money, line, _round_label(line.text), as_of,
                                 bool(_SAME_ROUND.search(line.text)), bool(_FUTURE.search(line.text))))
    return hits


# ------------------------------------------------------------------------------ field helpers


def _set_from_candidates(fact: Fact, candidates: list[Candidate], key=lambda c: c.display) -> None:
    """One distinct value → STATED; several → CONFLICT; none → NOT_STATED."""
    fact.candidates = candidates
    if not candidates:
        return
    distinct = list(dict.fromkeys(key(c) for c in candidates))
    fact.sources = [c.source for c in candidates]
    if len(distinct) == 1:
        fact.status = FactStatus.STATED
        fact.value = candidates[0].value
        fact.display = candidates[0].display
        fact.detail = dict(candidates[0].detail)
    else:
        fact.status = FactStatus.CONFLICT
        fact.value = None
        fact.display = "conflicting figures — " + " vs ".join(distinct)
        fact.notes.append("Different values appear in the deck: " + "; ".join(
            f"{c.display} ({c.source.locator})" for c in candidates) + ". Resolve before relying on this field.")


def _money_key(c: Candidate) -> str:
    m: Money = c.value
    return f"{m.currency}:{round(m.amount, -2)}"


def _money_candidates(hits: list[MoneyHit], kinds: set[str]) -> list[Candidate]:
    return [Candidate(h.money, h.money.display(), h.line.ref(),
                      {"kind": h.kind, "round": h.round_label, "as_of": h.as_of, "page": h.line.page,
                       "same_round_hint": h.same_round_hint})
            for h in hits if h.kind in kinds and not h.future]


def _dedupe_money(fact: Fact, candidates: list[Candidate]) -> None:
    fact.candidates = candidates
    if not candidates:
        return
    distinct = list(dict.fromkeys(_money_key(c) for c in candidates))
    fact.sources = [c.source for c in candidates]
    first = candidates[0]
    if len(distinct) == 1:
        fact.status, fact.value, fact.display = FactStatus.STATED, first.value, first.display
        fact.detail = dict(first.detail)
        rounds = {c.detail.get("round") for c in candidates if c.detail.get("round")}
        fact.detail["round"] = rounds.pop() if len(rounds) == 1 else None
        fact.detail["pages"] = sorted({c.detail["page"] for c in candidates})
        fact.detail["same_round_hint"] = any(c.detail.get("same_round_hint") for c in candidates)
        dates = {c.detail.get("as_of") for c in candidates if c.detail.get("as_of")}
        fact.detail["as_of"] = dates.pop() if len(dates) == 1 else None
    else:
        _set_from_candidates(fact, candidates, key=_money_key)


# ------------------------------------------------------------------------------ extraction

_LEGAL = re.compile(
    r"\b([A-Z][A-Za-z0-9&'\-]*(?:\s+[A-Z][A-Za-z0-9&'\-]*){0,4}),?\s+"
    r"(Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|PBC|GmbH|Co\.)(?![A-Za-z])"
)
_GENERIC_TITLE = re.compile(r"^(?:pitch deck|investor (?:deck|presentation)|confidential|company overview|"
                            r"presentation|welcome|agenda)\b", re.I)
_INSTRUMENTS = [
    ("Post-money SAFE", r"post[- ]money SAFEs?"),
    ("Pre-money SAFE", r"pre[- ]money SAFEs?"),
    ("SAFE", r"\bSAFEs?\b"),
    ("Convertible note", r"convertible (?:promissory )?notes?"),
    ("Priced equity (preferred stock)", r"(?:series (?:seed|a|b) )?preferred (?:stock|equity|shares)|priced (?:equity )?round|priced equity"),
    ("Common stock", r"common (?:stock|shares)"),
    ("KISS", r"\bKISS\b"),
    ("Revenue-based financing", r"revenue[- ]based financ\w+"),
    ("Reg CF crowdfunding", r"\breg(?:ulation)? CF\b|equity crowdfunding"),
]
_RAISE_CONTEXT = re.compile(r"\braising\b|\bthe ask\b|\bterms?\b|\binstrument\b|\bround\b|\boffering\b|\bseeking\b|"
                            r"\braise\b", re.I)
_PRIOR_CONTEXT = re.compile(r"\braised\b|\bpreviously\b|\bprior\b|\bhistor|\bconverted\b", re.I)
_HQ = re.compile(r"(?i:headquartered|based|located|HQ(?:'d)?|headquarters|head office)\s*(?i:in|:|-|–)?\s*"
                 r"(?P<loc>[A-Z][A-Za-z .'\-]+(?:,\s*[A-Z][A-Za-z .'\-]+){0,2})")
_ADDRESS = re.compile(r"\b(?P<loc>[A-Z][a-z]+(?: [A-Z][a-z]+)?,\s*[A-Z]{2})\s+\d{5}\b")
_TARGET_GEO = [
    re.compile(r"(?:seeking|targeting|looking for|prefer(?:ring)?|open to|welcom\w*)\s+(?:only\s+)?"
               r"(?P<geo>[A-Z][A-Za-z .\-]{1,40}?)[- ](?:based )?investors", re.I),
    re.compile(r"investors?\s+(?:based\s+)?(?:in|from)\s+(?P<geo>[A-Z][A-Za-z .,\-]{1,40})", re.I),
    re.compile(r"(?:target|preferred)\s+investor\s+(?:geography|location|base)\s*:\s*(?P<geo>.+)$", re.I),
]
_CLOSE = re.compile(r"\b(?:target(?:ed)?|expected|anticipated|planned|projected|final)?\s*clos(?:e|ing)\b"
                    r"(?! the gap)", re.I)
_EXPLICIT_SECTOR = re.compile(r"^(?:sector|industry|vertical|category|space)\s*[:\-–]\s*(?P<v>.+)$", re.I)
_EXPLICIT_STAGE = re.compile(r"(?:\bstage|\bround)\s*[:\-–]\s*(?P<v>[A-Za-z\- ]{3,20})", re.I)


def _company(deck: DeckDocument, lines: list[Line], profile: dict[str, Fact]) -> None:
    legal_scores: Counter[str] = Counter()
    legal_refs: dict[str, list[SourceRef]] = {}
    first_page, last_page = deck.pages[0].number, deck.pages[-1].number
    for line in lines:
        for m in _LEGAL.finditer(line.text):
            name = re.sub(r"^(?:Copyright|Confidential|The)\s+", "", m.group(1)).strip()
            if not name or name.split()[0].lower() in {"and", "by", "for", "with", "from"}:
                continue
            full = f"{name}, {m.group(2)}" if "," in m.group(0) else f"{name} {m.group(2)}"
            weight = 1 + (3 if re.search(r"©|copyright|confidential|all rights", line.text, re.I) else 0) \
                + (2 if line.page in (first_page, last_page) else 0)
            legal_scores[full] += weight
            legal_refs.setdefault(full, []).append(line.ref())
    title_line = next((l for l in lines if l.page == first_page and not _GENERIC_TITLE.match(l.text)
                       and 1 <= len(l.text.split()) <= 5 and not money_mentions(l.text)), None)
    title = title_line.text if title_line else None
    if legal_scores:
        def rank(name: str) -> tuple[int, int]:
            bonus = 3 if title and fuzz.token_set_ratio(normalize_org(name), normalize_org(title)) >= 85 else 0
            return legal_scores[name] + bonus, len(legal_refs[name])
        best = max(legal_scores, key=rank)
        f = profile["legal_name"]
        f.status, f.value, f.display, f.sources = FactStatus.STATED, best, best, legal_refs[best][:4]
        others = [n for n in legal_scores if n != best]
        if others:
            f.notes.append("Other legal entity names in the deck (partners/customers?): " + ", ".join(others[:5]))
    legal = profile["legal_name"].value
    f = profile["company_name"]
    if title and (not legal or fuzz.token_set_ratio(normalize_org(legal), normalize_org(title)) >= 85):
        f.status, f.value, f.display, f.sources = FactStatus.STATED, title, title, [title_line.ref()]
    elif legal:
        base = re.sub(r",?\s+(?:Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|PBC|GmbH|Co\.)$", "", legal)
        f.status, f.value, f.display = FactStatus.STATED, base, base
        f.sources = profile["legal_name"].sources[:2]
        f.notes.append("Taken from the legal entity name.")


def _sector(lines: list[Line], deck: DeckDocument, profile: dict[str, Fact]) -> None:
    sec, sub = profile["sector"], profile["subsector"]
    for line in lines:
        m = _EXPLICIT_SECTOR.match(line.text)
        if m:
            s_name, s_sub = tx.match_sector_name(m.group("v"))
            if s_name:
                sec.status, sec.value, sec.display, sec.sources = FactStatus.STATED, s_name, s_name, [line.ref()]
                tags = tx.parse_sector_focus(m.group("v"))
                subs = sorted({s for (sc, s) in tags.subsectors if sc == s_name})
                if subs:
                    sub.status, sub.value, sub.display, sub.sources = (FactStatus.STATED, subs, " / ".join(subs),
                                                                       [line.ref()])
                break
    sector_hits, sub_hits = tx.scan_sector_hits(deck.full_text)
    if sec.value is None:
        if not sector_hits or max(sector_hits.values()) < 3:
            return
        ranked = sorted(sector_hits.items(), key=lambda kv: -kv[1])
        top = ranked[0][0]
        sec.status, sec.value, sec.display = FactStatus.CLASSIFIED, top, top
        sec.notes.append("Classified from sector vocabulary in the deck (" + ", ".join(
            f"{name}: {n}" for name, n in ranked[:3]) + " weighted mentions). Confirm or override.")
        if len(ranked) > 1 and ranked[1][1] >= 0.8 * ranked[0][1]:
            sec.notes.append(f"Close second: {ranked[1][0]} — review.")
    if sub.value is None and sec.value:
        in_sector = sorted(((s, n) for (sc, s), n in sub_hits.items() if sc == sec.value), key=lambda kv: -kv[1])
        chosen = [s for s, n in in_sector if n >= 2][:2] or [s for s, _n in in_sector[:1]]
        if chosen:
            sub.status, sub.value, sub.display = FactStatus.CLASSIFIED, chosen, " / ".join(chosen)
            sub.notes.append("Classified from subsector vocabulary: " + ", ".join(
                f"{s} ({n})" for s, n in in_sector[:4]) + ". Confirm or override.")
    for fact, names in ((sec, [sec.value] if sec.value else []), (sub, sub.value or [])):
        if fact.status != FactStatus.CLASSIFIED:
            continue
        pats = [p for sc, s, p in tx._SUB_PATTERNS if s in names or sc in names]
        refs = []
        for line in lines:
            if any(p.search(line.text) for p in pats):
                refs.append(line.ref())
            if len(refs) >= 4:
                break
        fact.sources = refs


def _stage_and_instrument(lines: list[Line], raise_hits: list[MoneyHit], profile: dict[str, Fact]) -> None:
    stage = profile["stage"]
    candidates = [Candidate(h.round_label, h.round_label, h.line.ref())
                  for h in raise_hits if h.round_label and h.round_label in tx.STAGES]
    if not candidates:
        for line in lines:
            if _PRIOR_CONTEXT.search(line.text) or _FUTURE.search(line.text):
                continue
            m = _EXPLICIT_STAGE.search(line.text)
            value = tx.normalize_stage(m.group("v")) if m else None
            if value is None:
                rm = re.search(r"\b(pre[- ]?seed|seed|series [a-c])\s+(?:round|raise|financing|extension)\b",
                               line.text, re.I)
                value = tx.normalize_stage(rm.group(1)) if rm else None
            if value:
                candidates.append(Candidate(value, value, line.ref()))
    _set_from_candidates(stage, candidates)

    inst = profile["instrument"]
    found: list[Candidate] = []
    raise_lines = {id(h.line) for h in raise_hits}
    for line in lines:
        if not (id(line) in raise_lines or _RAISE_CONTEXT.search(line.text)) or _PRIOR_CONTEXT.search(line.text):
            continue
        names = [name for name, pat in _INSTRUMENTS if re.search(pat, line.text, re.I)]
        if any(n in names for n in ("Post-money SAFE", "Pre-money SAFE")) and "SAFE" in names:
            names.remove("SAFE")
        found.extend(Candidate(n, n, line.ref()) for n in names)
    specific = {c.value for c in found} & {"Post-money SAFE", "Pre-money SAFE"}
    if specific:
        found = [c for c in found if c.value != "SAFE"]
    _set_from_candidates(inst, found)


def _geography(lines: list[Line], profile: dict[str, Fact]) -> None:
    geo = profile["company_geography"]
    cands: list[Candidate] = []
    for line in lines:
        for m in _HQ.finditer(line.text):
            loc = tx.parse_location(m.group("loc"))
            if loc:
                cands.append(Candidate(loc, loc.display(), line.ref()))
    if not cands:
        for line in lines:
            for m in _ADDRESS.finditer(line.text):
                loc = tx.parse_location(m.group("loc"))
                if loc:
                    cands.append(Candidate(loc, loc.display(), line.ref(), {"basis": "company address"}))
    _set_from_candidates(geo, cands, key=lambda c: (c.value.state or "", c.value.country or ""))
    if geo.status == FactStatus.STATED and geo.candidates and geo.candidates[0].detail.get("basis"):
        geo.notes.append("Taken from the company address in the deck.")

    target = profile["target_investor_geography"]
    tcands = []
    for line in lines:
        for pat in _TARGET_GEO:
            m = pat.search(line.text)
            if m:
                areas = tx.parse_geo_focus(m.group("geo"))
                if areas:
                    label = ", ".join(a.name for a in areas)
                    tcands.append(Candidate(areas, label, line.ref()))
                    break
    _set_from_candidates(target, tcands)


def _dates(deck: DeckDocument, lines: list[Line], profile: dict[str, Fact]) -> None:
    close = profile["target_close_date"]
    cands = []
    for line in lines:
        cm = _CLOSE.search(line.text)
        if not cm:
            continue
        for d in date_mentions(line.text):
            if d.start >= cm.start() - 40:
                cands.append(Candidate(d.value, d.display, line.ref(), {"precision": d.precision}))
                break
    _set_from_candidates(close, cands)

    deck_date = profile["deck_date"]
    for page in (deck.pages[0], deck.pages[-1]):
        page_lines = [l for l in lines if l.page == page.number and not _CLOSE.search(l.text)
                      and not re.search(r"founded|since|launch|©|copyright", l.text, re.I)]
        found = next(((d, l) for l in page_lines for d in date_mentions(l.text)), None)
        if found:
            d, l = found
            deck_date.status, deck_date.value, deck_date.display = FactStatus.STATED, d.value, d.display
            deck_date.sources = [l.ref()]
            return
    if deck.metadata_date:
        deck_date.status = FactStatus.METADATA
        deck_date.value = deck.metadata_date.date()
        deck_date.display = f"{deck.metadata_date:%B} {deck.metadata_date.day}, {deck.metadata_date.year} (file metadata)"
        deck_date.sources = [SourceRef(file="", locator="file metadata")]
        deck_date.notes.append("No date on the title or closing slide; using the file's creation/modified date.")


def _remaining(profile: dict[str, Fact], hits: list[MoneyHit]) -> None:
    rem = profile["amount_remaining"]
    _dedupe_money(rem, _money_candidates(hits, {"remaining"}))
    calc, why = calculate_remaining(profile["raise_amount"], profile["amount_committed"])
    if rem.status == FactStatus.STATED:
        if calc is not None and abs(calc.amount - rem.value.amount) > 0.02 * max(rem.value.amount, 1):
            rem.notes.append(f"Stated remaining ({rem.display}) differs from raise − committed "
                             f"({calc.display()}). Review.")
        return
    if rem.status == FactStatus.CONFLICT:
        return
    if calc is not None:
        raise_f, com_f = profile["raise_amount"], profile["amount_committed"]
        rem.status, rem.value, rem.display = FactStatus.CALCULATED, calc, f"{calc.display()} (calculated)"
        rem.sources = raise_f.sources[:2] + com_f.sources[:2]
        rem.notes.append(f"Calculated: raise {raise_f.value.display()} − {com_f.detail.get('commitment_type', 'committed')} "
                         f"{com_f.value.display()}. Soft interest is not subtracted.")
    else:
        rem.notes.append(why)


def calculate_remaining(raise_f: Fact, com_f: Fact) -> tuple[Money | None, str]:
    """Raise − committed, only when both refer to the same round, currency and date."""
    if not raise_f.resolved:
        return None, "Not calculated: raise amount is not established."
    if not com_f.resolved:
        return None, "Not calculated: committed amount is not established."
    r, c = raise_f.value, com_f.value
    if r.currency != c.currency:
        return None, f"Not calculated: raise ({r.currency}) and commitments ({c.currency}) are in different currencies."
    r_round, c_round = raise_f.detail.get("round"), com_f.detail.get("round")
    if r_round and c_round and r_round != c_round:
        return None, f"Not calculated: raise refers to {r_round} but commitments to {c_round}."
    same_page = set(raise_f.detail.get("pages", [])) & set(com_f.detail.get("pages", []))
    if not (same_page or com_f.detail.get("same_round_hint") or (r_round and r_round == c_round)):
        return None, ("Not calculated: the deck does not tie the committed amount to the current round "
                      "(different slide, no round named).")
    r_date, c_date = raise_f.detail.get("as_of"), com_f.detail.get("as_of")
    if r_date and c_date and r_date != c_date:
        return None, f"Not calculated: figures are dated differently ({r_date} vs {c_date})."
    if c.amount > r.amount:
        return None, "Not calculated: committed amount exceeds the raise amount — review the figures."
    return Money(round(r.amount - c.amount, 2), r.currency), ""


def extract_profile(deck: DeckDocument) -> DealProfile:
    facts = {name: Fact(field=name, label=label) for name, label in DEAL_FIELDS.items()}
    lines = _lines(deck)
    hits = _money_hits(lines)
    raise_hits = [h for h in hits if h.kind == "raise" and not h.future]

    _company(deck, lines, facts)
    _sector(lines, deck, facts)
    _stage_and_instrument(lines, raise_hits, facts)

    _dedupe_money(facts["raise_amount"], _money_candidates(hits, {"raise"}))
    committed = facts["amount_committed"]
    _dedupe_money(committed, _money_candidates(hits, {"signed", "committed"}))
    if committed.candidates:
        kinds = {c.detail["kind"] for c in committed.candidates}
        committed.detail["commitment_type"] = "signed" if kinds == {"signed"} else (
            "signed/committed" if "signed" in kinds else "committed (signing status not stated)")
        if committed.status == FactStatus.STATED:
            committed.display = f"{committed.value.display()} {committed.detail['commitment_type']}"
    _dedupe_money(facts["soft_interest"], _money_candidates(hits, {"soft"}))
    if facts["soft_interest"].status == FactStatus.STATED:
        facts["soft_interest"].notes.append("Soft interest is not a commitment and is never subtracted.")
    _remaining(facts, hits)
    _geography(lines, facts)
    _dates(deck, lines, facts)

    for f in facts.values():
        f.sources = [SourceRef(file=deck.filename, locator=s.locator, sheet=s.sheet, excerpt=s.excerpt)
                     for s in f.sources]
        for c in f.candidates:
            c.source = SourceRef(file=deck.filename, locator=c.source.locator, excerpt=c.source.excerpt)
    future = [h for h in hits if h.kind == "raise" and h.future]
    profile = DealProfile(deck_file=deck.filename, facts=facts, warnings=list(deck.warnings))
    if future:
        profile.extraction_log.append("Ignored future-round amounts: " + "; ".join(
            f"{h.money.display()} ({h.line.locator})" for h in future))
    profile.extraction_log.append(f"Read {deck.page_count} {deck.unit}s; OCR on {len(deck.ocr_pages)}.")
    return profile


# ------------------------------------------------------------------------------ overrides

MONEY_FIELDS = {"raise_amount", "amount_committed", "soft_interest", "amount_remaining"}


def make_override(profile: DealProfile, name: str, text: str, reason: str = "") -> Override:
    """Validate user text for a field; raises ValueError with a readable message."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Enter a value.")
    if name in MONEY_FIELDS:
        raise_value = profile.effective("raise_amount")
        money = parse_money(text, raise_value.currency if isinstance(raise_value, Money) else "USD")
        if money is None:
            raise ValueError(f"'{text}' is not an amount (e.g. $2.5M).")
        return Override(name, money, money.display(), reason)
    if name == "stage":
        stage = tx.normalize_stage(text)
        if stage is None:
            raise ValueError(f"Stage must be one of: {', '.join(tx.STAGES)}.")
        return Override(name, stage, stage, reason)
    if name == "sector":
        match = next((s for s in tx.SECTOR_NAMES if s.lower() == text.lower()), None) or tx.match_sector_name(text)[0]
        if match is None:
            raise ValueError("Pick a sector from the list.")
        return Override(name, match, match, reason)
    if name == "subsector":
        names = [s.strip() for s in re.split(r"\s*[/;,]\s*", text) if s.strip()]
        known = [next((k for k in tx.SECTOR_OF_SUBSECTOR if k.lower() == n.lower()), None) for n in names]
        if not all(known):
            parsed = sorted({s for _sc, s in tx.parse_sector_focus(text).subsectors})
            if not parsed:
                raise ValueError("Subsector must come from the taxonomy (see the list).")
            known = parsed
        return Override(name, known, " / ".join(known), reason)
    if name == "company_geography":
        loc = tx.parse_location(text)
        if loc is None:
            raise ValueError("Location not recognized (e.g. 'Austin, TX' or 'London, UK').")
        return Override(name, loc, loc.display(), reason)
    if name == "target_investor_geography":
        areas = tx.parse_geo_focus(text)
        if not areas:
            raise ValueError("Geography not recognized (e.g. 'United States', 'Texas', 'North America').")
        return Override(name, areas, ", ".join(a.name for a in areas), reason)
    if name in {"target_close_date", "deck_date"}:
        dates = date_mentions(text)
        if not dates:
            raise ValueError("Date not recognized (e.g. 'December 15, 2026' or 'Q4 2026').")
        return Override(name, dates[0].value, dates[0].display, reason)
    return Override(name, text, text, reason)


# ------------------------------------------------------------------------------ matching context


@dataclass
class DealContext:
    """Effective (deck + overrides) values used for matching."""

    company_name: str | None
    legal_name: str | None
    aliases: list[str]
    sector: str | None
    subsectors: list[str]
    stage: str | None
    raise_amount: Money | None
    remaining: Money | None
    remaining_basis: str
    location: Location | None
    target_investor_geo: list[GeoArea] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_context(profile: DealProfile, user_aliases: list[str] | None = None) -> DealContext:
    eff = profile.effective
    raise_amount: Money | None = eff("raise_amount")
    remaining: Money | None = None
    basis = "unknown"
    rem_fact = profile.facts["amount_remaining"]
    if "amount_remaining" in profile.overrides:
        remaining, basis = eff("amount_remaining"), "override"
    elif rem_fact.status == FactStatus.STATED:
        remaining, basis = rem_fact.value, "stated in deck"
    elif {"raise_amount", "amount_committed"} & set(profile.overrides):
        raise_f = Fact("raise_amount", "", FactStatus.STATED, raise_amount) if raise_amount else Fact("raise_amount", "")
        raise_f.detail = dict(profile.facts["raise_amount"].detail)
        com_val = eff("amount_committed")
        com_f = Fact("amount_committed", "", FactStatus.STATED, com_val) if com_val else Fact("amount_committed", "")
        com_f.detail = dict(profile.facts["amount_committed"].detail)
        com_f.detail["same_round_hint"] = True   # the user confirmed the figures by overriding them
        calc, _why = calculate_remaining(raise_f, com_f)
        if calc:
            remaining, basis = calc, "calculated from corrected values"
    elif rem_fact.status == FactStatus.CALCULATED:
        remaining, basis = rem_fact.value, "calculated (raise − committed)"
    notes = []
    if remaining is None and raise_amount is not None:
        notes.append("Remaining allocation not established; check sizes are compared with the full raise.")
    aliases = [a for a in [eff("company_name"), eff("legal_name"), *(user_aliases or [])] if a]
    subsectors = eff("subsector") or []
    return DealContext(
        company_name=eff("company_name"), legal_name=eff("legal_name"),
        aliases=list(dict.fromkeys(a.strip() for a in aliases if a.strip())),
        sector=eff("sector"), subsectors=list(subsectors), stage=eff("stage"),
        raise_amount=raise_amount, remaining=remaining, remaining_basis=basis,
        location=eff("company_geography"), target_investor_geo=eff("target_investor_geography") or [],
        notes=notes,
    )


def profile_bullets(profile: DealProfile, ctx: DealContext, limit: int = 6) -> list[str]:
    """Compact deal-profile bullets for the PDF and UI, from the template's bullet patterns;
    each bullet cites the slide/page references of its facts."""
    from app.reports.template import fill_bullet, load_template

    section = load_template().section("deal_profile")
    markers = (section.model_extra or {})["source_markers"]
    values = {name: profile.effective_display(name) for name in DEAL_FIELDS}

    def refs(names: list[str]) -> str:
        locs = []
        for n in names:
            if n in profile.overrides:
                locs.append(markers["override"])
                continue
            locs += [s.locator.replace("slide ", markers["slide"]).replace("page ", markers["page"])
                     for s in profile.facts[n].sources[:2]]
        locs = list(dict.fromkeys(locs))[: markers["max_refs"]]
        return f" [{', '.join(locs)}]" if locs else ""

    return [fill_bullet(b.pattern, values, values["company_name"]) + refs(b.fields)
            for b in section.bullets][:limit]
