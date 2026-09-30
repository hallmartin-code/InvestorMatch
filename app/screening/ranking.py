"""Threshold, ordering and the per-organization cap."""

from __future__ import annotations

from app.models import CATEGORY_ORDER, ScoredContact
from app.utils.text import fold, normalize_org


def sort_key(s: ScoredContact) -> tuple:
    """Category order, then score ↓, evidence completeness ↓, organization, last name, first name."""
    return (CATEGORY_ORDER.index(s.category), -s.fit_score, -s.evidence_completeness,
            normalize_org(s.contact.organization), fold(s.contact.last_name), fold(s.contact.first_name),
            s.contact.email)


def org_key(s: ScoredContact) -> str:
    """Contacts without an organization are capped individually (by email)."""
    return normalize_org(s.contact.organization) or f"email:{s.contact.email}"


def rank(qualified: list[ScoredContact], org_cap: int) -> tuple[list[ScoredContact], list[ScoredContact]]:
    """Returns (ranked, capped). The cap keeps each organization's strongest contacts across the
    complete list (score, then evidence completeness, then name)."""
    by_strength = sorted(qualified, key=lambda s: (-s.fit_score, -s.evidence_completeness,
                                                   CATEGORY_ORDER.index(s.category), fold(s.contact.last_name),
                                                   fold(s.contact.first_name), s.contact.email))
    counts: dict[str, int] = {}
    kept, capped = [], []
    for s in by_strength:
        key = org_key(s)
        if counts.get(key, 0) >= org_cap:
            s.status = "Organization cap"
            capped.append(s)
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(s)
    kept.sort(key=sort_key)
    position: dict = {}
    for s in kept:
        position[s.category] = position.get(s.category, 0) + 1
        s.rank = position[s.category]
        s.status = "Ranked"
    return kept, capped
