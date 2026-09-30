"""Evidence-based Fit Score (1–10).

Fit = 0.45·Sector + 0.15·Stage + 0.15·Check size + 0.15·Geography + 0.10·TEN relationship,
each component rated 0–10 (ratings in config/scoring.toml), rounded half-up to one decimal,
with a floor of 1.0. Unknown attributes earn 0 and are flagged; they are never treated as
incompatibility. Evidence completeness (share of the five investor-side attributes that are
documented) is reported separately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.extraction import taxonomy as tx
from app.extraction.deal_profile import DealContext
from app.extraction.parsing import CheckRange, parse_check
from app.models import Category, ComponentScore, Contact, GeoArea, Location, Money, ScoredContact
from app.screening.introductions import IntroRecord
from app.utils.text import fold, is_truthy, truncate

# ------------------------------------------------------------------------------ investor attributes


@dataclass
class TenEvidence:
    core: bool | None = None
    core_text: str = ""
    events: bool | None = None
    events_text: str = ""
    similar: bool | None = None
    similar_text: str = ""

    @property
    def known(self) -> bool:
        return any(v is not None for v in (self.core, self.events, self.similar))

    @property
    def positive(self) -> bool:
        return bool(self.core or self.events or self.similar)


@dataclass
class InvestorAttributes:
    sector: tx.SectorTags
    stage: tx.StageFocus
    check: CheckRange | None
    geo_focus: list[GeoArea]
    location: Location | None
    participation: str | None            # "co-invests" | "solo" | None
    ten: TenEvidence = field(default_factory=TenEvidence)
    from_description: set[str] = field(default_factory=set)   # attributes read from the free-text description


_CHECK_CONTEXT = re.compile(r"\bchecks?\b|\bticket|\binvests?\s+(?:between\s+)?(?:up to\s+)?[$€£]|"
                            r"\binvestments? (?:of|between|from)\b|\bper (?:deal|company|investment)\b|"
                            r"\bcheck sizes?\b|\bwrites?\b", re.I)


def _from_description(text: str) -> tuple[tx.SectorTags, tx.StageFocus, list[GeoArea], CheckRange | None]:
    """Evidence from a free-text investor description. Generic words ("technology") are not a generalist
    signal here, and money only counts as a check size next to check wording."""
    tags = tx.parse_sector_focus(text)
    tags.generalist, tags.unrecognized = False, []
    check = None
    if _CHECK_CONTEXT.search(text):
        check = parse_check(text)
    return tags, tx.parse_stage_focus(text), tx.parse_geo_focus(text), check


def _yes_no_count(value: str) -> bool | None:
    text = fold(value).strip()
    if not text:
        return None
    number = re.fullmatch(r"\d+", text)
    if number:
        return int(text) > 0
    truth = is_truthy(text)
    return truth if truth is not None else True     # free text (event names, company names) = documented


def parse_attributes(contact: Contact, similar_intros: list[IntroRecord] | None = None) -> InvestorAttributes:
    get = contact.get
    check = None
    if get("check_min") or get("check_max"):
        lo = parse_check(get("check_min")) if get("check_min") else None
        hi = parse_check(get("check_max")) if get("check_max") else None
        check = CheckRange(lo.minimum if lo else None, hi.maximum if hi else None,
                           (lo or hi).currency, f"{get('check_min')}–{get('check_max')}")
    elif get("check_size"):
        check = parse_check(get("check_size"))
    location = tx.parse_location(", ".join(p for p in (get("location"), get("country")) if p))

    part_text = fold(get("participation"))
    header = fold(contact.values.get("_participation_header", ""))
    participation = None
    if part_text:
        if re.search(r"lead only|only lead|\bsole\b|\bsolo\b|does not co-?invest|no co-?invest", part_text):
            participation = "solo"
        elif re.search(r"co-?invest|follow|syndicat|either|both|lead or follow|lead/follow|alongside", part_text):
            participation = "co-invests"
        elif is_truthy(part_text) is not None and re.search(r"co-?invest|syndicat|follow", header):
            participation = "co-invests" if is_truthy(part_text) else "solo"

    ten = TenEvidence()
    core_text = fold(get("ten_core"))
    if core_text:
        if re.search(r"non-?core|tier ?[23]", core_text) or is_truthy(core_text) is False:
            ten.core = False
        else:
            # Yes/Core/Tier 1, or a named core-list tag (e.g. "Keiretsu", "3X in 3") in the core-list column.
            ten.core = True
            if not is_truthy(core_text):
                ten.core_text = get("ten_core")
    if get("ten_events"):
        ten.events, ten.events_text = _yes_no_count(get("ten_events")), get("ten_events")
    if get("ten_similar_intros"):
        ten.similar, ten.similar_text = _yes_no_count(get("ten_similar_intros")), get("ten_similar_intros")
    if similar_intros:
        ten.similar = True
        names = ", ".join(dict.fromkeys(i.company for i in similar_intros))
        ten.similar_text = "; ".join(filter(None, [ten.similar_text, f"introduced to {names}"]))

    attrs = InvestorAttributes(
        sector=tx.parse_sector_focus(get("sector_focus"), get("thesis")),
        stage=tx.parse_stage_focus(get("stage_focus")),
        check=check, geo_focus=tx.parse_geo_focus(get("geo_focus")), location=location,
        participation=participation, ten=ten,
    )
    if get("description"):   # fallback only where the dedicated column says nothing
        d_sector, d_stage, d_geo, d_check = _from_description(get("description"))
        if not attrs.sector.known and d_sector.known:
            attrs.sector = d_sector
            attrs.from_description.add("sector")
        if not attrs.stage.known and d_stage.known:
            attrs.stage = d_stage
            attrs.from_description.add("stage")
        if not attrs.geo_focus and d_geo:
            attrs.geo_focus = d_geo
            attrs.from_description.add("geography")
        if attrs.check is None and d_check is not None:
            attrs.check = d_check
            attrs.from_description.add("check_size")
    return attrs


# ------------------------------------------------------------------------------ incompatibility


def incompatibility(attrs: InvestorAttributes, ctx: DealContext) -> tuple[str, str] | None:
    """Explicit stage or geographic incompatibility (unknown is never incompatible). Attributes read from a
    free-text description can add evidence but never exclude a contact."""
    st = attrs.stage
    stated_stage = "stage" not in attrs.from_description
    if stated_stage and st.named and not st.early_broad and not st.agnostic and st.named <= tx.LATE_ONLY:
        return "GROWTH_ONLY", f"Growth / late-stage only (stage focus: {', '.join(sorted(st.named))})"
    if stated_stage and ctx.stage and st.known and ctx.stage not in st.all_stages:
        focus = ", ".join(s for s in tx.STAGES if s in st.all_stages)
        return "STAGE_INCOMPATIBLE", f"Stated stage focus ({focus}) excludes {ctx.stage}"
    if ctx.location and attrs.geo_focus and "geography" not in attrs.from_description:
        results = [tx.area_contains(a, ctx.location) for a in attrs.geo_focus]
        if results and all(r is False for r in results):
            names = ", ".join(a.name for a in attrs.geo_focus)
            return "GEO_INCOMPATIBLE", f"Stated geographic focus ({names}) excludes {ctx.location.display()}"
    if ctx.target_investor_geo and attrs.location:
        results = [tx.area_contains(a, attrs.location) for a in ctx.target_investor_geo]
        if results and all(r is False for r in results):
            names = ", ".join(a.name for a in ctx.target_investor_geo)
            return ("OUTSIDE_TARGET_GEO",
                    f"Investor location ({attrs.location.display()}) is outside the deck's target investor geography ({names})")
    return None


# ------------------------------------------------------------------------------ components


def _sector(attrs: InvestorAttributes, ctx: DealContext, r: dict[str, float], w: float) -> ComponentScore:
    tags = attrs.sector
    known = tags.known
    if not ctx.sector:
        return ComponentScore("sector", "Sector/subsector", 0, w, known, "Deal sector not established",
                              flags=["deal sector unknown"])
    if not known:
        extra = f" (unrecognized terms: {', '.join(tags.unrecognized[:4])})" if tags.unrecognized else ""
        return ComponentScore("sector", "Sector/subsector", 0, w, False, "Sector focus not documented" + extra,
                              flags=["sector focus unknown"])
    niche = sorted({s for sc, s in tags.subsectors if s in ctx.subsectors})
    if niche:
        return ComponentScore("sector", "Sector/subsector", r["niche_match"], w, True,
                              f"Explicit {' & '.join(niche)} focus")
    if ctx.sector in tags.sectors:
        return ComponentScore("sector", "Sector/subsector", r["broad_sector"], w, True, f"Broad {ctx.sector} focus")
    adjacent = sorted({s for sc, s in tags.subsectors if sc == ctx.sector})
    if adjacent:
        return ComponentScore("sector", "Sector/subsector", r["adjacent_niche"], w, True,
                              f"Adjacent niche in sector ({', '.join(adjacent[:3])})")
    if tags.generalist:
        return ComponentScore("sector", "Sector/subsector", r["generalist"], w, True, "Generalist / sector-agnostic")
    stated = sorted({s for _sc, s in tags.subsectors} | tags.sectors)
    return ComponentScore("sector", "Sector/subsector", r["outside"], w, True,
                          f"Stated focus outside {ctx.sector} ({', '.join(stated[:3])})")


def _stage(attrs: InvestorAttributes, ctx: DealContext, r: dict[str, float], w: float) -> ComponentScore:
    st = attrs.stage
    if not ctx.stage:
        return ComponentScore("stage", "Stage", 0, w, st.known, "Deal stage not established",
                              flags=["deal stage unknown"])
    if not st.known:
        return ComponentScore("stage", "Stage", 0, w, False, "Stage focus not documented",
                              flags=["stage focus unknown"])
    if ctx.stage in st.named:
        return ComponentScore("stage", "Stage", r["named_stage"], w, True, f"Invests at {ctx.stage}")
    if st.early_broad and ctx.stage in tx.EARLY_STAGES:
        return ComponentScore("stage", "Stage", r["early_stage_broad"], w, True, "Early-stage focus (broad)")
    if st.agnostic:
        return ComponentScore("stage", "Stage", r["stage_agnostic"], w, True, "Stage-agnostic")
    return ComponentScore("stage", "Stage", 0, w, True, f"Stage focus does not include {ctx.stage}")


def _check(attrs: InvestorAttributes, ctx: DealContext, r: dict[str, float], w: float) -> ComponentScore:
    check = attrs.check
    target: Money | None = ctx.remaining or ctx.raise_amount
    basis = "remaining" if ctx.remaining else "raise"
    if check is None or (check.minimum is None and check.maximum is None):
        return ComponentScore("check_size", "Check size", 0, w, False, "Check size not documented",
                              flags=["check size unknown"])
    if target is None:
        return ComponentScore("check_size", "Check size", 0, w, True,
                              f"{check.display()} checks; deal raise/remaining not established",
                              flags=["deal allocation unknown"])
    if check.currency != target.currency:
        return ComponentScore("check_size", "Check size", 0, w, True,
                              f"Check size in {check.currency}; deal in {target.currency} (not converted)",
                              flags=["currency differs"])
    target_text = f"{target.display()} {basis}"
    if check.minimum and check.minimum > target.amount:
        return ComponentScore("check_size", "Check size", r["min_exceeds_remaining"], w, True,
                              f"Minimum check {Money(check.minimum, check.currency).display()} exceeds {target_text}")
    floor = target.amount * r["participation_floor_pct"] / 100
    if check.maximum is not None and check.maximum < floor:
        rating, text = r["small_participation"], f"{check.display()} checks are small vs {target_text}"
    else:
        rating, text = r["meaningful_participation"], f"{check.display()} checks fit {target_text}"
    if attrs.participation == "solo":
        rating = min(rating, r["solo_only_penalty"])
        text += "; states it does not co-invest"
    elif attrs.participation == "co-invests":
        text += "; co-invests"
    return ComponentScore("check_size", "Check size", rating, w, True, text)


_GEO_RANK = {"local": 3, "country": 2, "region": 1, "global": 0}


def _geography(attrs: InvestorAttributes, ctx: DealContext, r: dict[str, float], w: float) -> ComponentScore:
    known = bool(attrs.geo_focus)
    if ctx.location is None:
        return ComponentScore("geography", "Geography", 0, w, known, "Company geography not established",
                              flags=["deal geography unknown"])
    if attrs.geo_focus:
        containing = [a for a in attrs.geo_focus if tx.area_contains(a, ctx.location)]
        if containing:
            best = max(containing, key=lambda a: _GEO_RANK[tx.GEO_SPECIFICITY[a.kind]])
            level = tx.GEO_SPECIFICITY[best.kind]
            return ComponentScore("geography", "Geography", r[level], w, True, f"{best.name} focus")
        return ComponentScore("geography", "Geography", 0, w, True,
                              "Geographic focus cannot be compared with the company location",
                              flags=["geography undetermined"])
    loc = attrs.location
    if loc and ctx.location.state and loc.state == ctx.location.state:
        return ComponentScore("geography", "Geography", r["inferred_same_state"], w, False,
                              f"Based in {loc.state} (inferred from location; no stated focus)", inferred=True,
                              flags=["geographic focus unknown"])
    if loc and ctx.location.country and loc.country == ctx.location.country:
        return ComponentScore("geography", "Geography", r["inferred_same_country"], w, False,
                              f"Based in {loc.country} (inferred from location; no stated focus)", inferred=True,
                              flags=["geographic focus unknown"])
    return ComponentScore("geography", "Geography", 0, w, False, "Geographic focus not documented",
                          flags=["geographic focus unknown"])


def _ten(attrs: InvestorAttributes, p: dict[str, float], w: float) -> tuple[ComponentScore, str]:
    ten = attrs.ten
    points, parts = 0.0, []
    if ten.core:
        points += p["core_list"]
        parts.append(f"TEN core list ({truncate(ten.core_text, 40)})" if ten.core_text else "TEN core list")
    if ten.similar:
        points += p["similar_client_intros"]
        parts.append(f"intros to similar clients ({truncate(ten.similar_text, 60)})")
    if ten.events:
        points += p["event_participation"]
        parts.append(f"TEN events ({truncate(ten.events_text, 40)})")
    rating = min(points, 10.0)
    if ten.positive:
        flag = "Y"
    elif ten.core is False and ten.events is False and ten.similar is False:
        flag = "N"
    else:
        flag = "needs research"
    evidence = "; ".join(parts) if parts else ("No documented TEN relationship" if ten.known
                                               else "TEN relationship not documented")
    flags = [] if ten.known else ["TEN relationship unknown"]
    return ComponentScore("ten_relationship", "TEN relationship", rating, w, ten.known, evidence, flags=flags), flag


def round_score(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def why_line(components: list[ComponentScore], limit: int = 170) -> str:
    parts = []
    for c in components:
        if c.rating <= 0:
            continue
        text = c.evidence
        if c.key == "ten_relationship":
            text = text.split(" (")[0] if len(text) > 50 else text
        parts.append(text.replace(" (inferred from location; no stated focus)", " (inferred)"))
    return truncate("; ".join(parts), limit) or "Insufficient documented evidence"


def score_contact(contact: Contact, attrs: InvestorAttributes, ctx: DealContext, category: Category | None,
                  cfg: dict[str, Any]) -> ScoredContact:
    weights = cfg["weights"]
    ten_component, ten_flag = _ten(attrs, cfg["ten_relationship_points"], weights["ten_relationship"])
    components = [
        _sector(attrs, ctx, cfg["sector_ratings"], weights["sector"]),
        _stage(attrs, ctx, cfg["stage_ratings"], weights["stage"]),
        _check(attrs, ctx, cfg["check_ratings"], weights["check_size"]),
        _geography(attrs, ctx, cfg["geography_ratings"], weights["geography"]),
        ten_component,
    ]
    for c in components:
        if c.key in attrs.from_description and c.known:
            c.evidence += " (from description)"
            c.flags.append("read from free-text description")
    raw = sum(c.weighted for c in components)
    fit = max(1.0, min(10.0, round_score(raw)))
    completeness = sum(1 for c in components if c.known) / len(components)
    return ScoredContact(contact=contact, category=category, components=components, fit_score=fit,
                         evidence_completeness=completeness, why=why_line(components), ten_relationship=ten_flag)
