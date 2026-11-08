"""Review-screen helpers: held-contact breakdown, projected ranks, data-quality notes and action warnings.

Pure functions over a RunResult so the UI and the tests share one definition.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.models import Contact, FactStatus, LogStatus, RunResult, ScoredContact

# Scoring components and the investor-list columns that feed them (description is a fallback for the first four).
SCORE_FIELDS: list[tuple[str, str, tuple[str, ...]]] = [
    ("sector", "Sector / subsector", ("sector_focus", "thesis")),
    ("stage", "Stage", ("stage_focus",)),
    ("check_size", "Check size", ("check_size", "check_min", "check_max")),
    ("geography", "Geography", ("geo_focus",)),
    ("ten_relationship", "TEN relationship", ("ten_core", "ten_events", "ten_similar_intros")),
]


def unmapped_score_fields(mapping: dict[str, str | None], weights: dict[str, float]) -> list[dict[str, Any]]:
    """Score components with no mapped column on this sheet: [{label, weight, partial}] where ``partial``
    explains a fallback (description text, location, intro lists) that can still earn some points."""
    has = lambda key: bool(mapping.get(key))  # noqa: E731
    out = []
    for key, label, fields in SCORE_FIELDS:
        if any(has(f) for f in fields):
            continue
        partial = ""
        if key != "ten_relationship" and has("description"):
            partial = "read from the Description column where it mentions it"
        elif key == "geography" and (has("location") or has("country")):
            partial = "inferred from investor location only (lower points)"
        elif key == "ten_relationship":
            partial = "only intros to similar clients from uploaded introduction trackers can count"
        out.append({"key": key, "label": label, "weight": weights.get(key, 0.0), "partial": partial})
    return out


# ------------------------------------------------------------------------------ contacts

_INITIAL = re.compile(r"^[A-Za-z]\.?$")


def incomplete_name(c: Contact) -> bool:
    """A missing or single-letter first/last name (e.g. last name 'w') — needs checking before outreach."""
    return not c.first_name or not c.last_name or bool(_INITIAL.match(c.first_name) or _INITIAL.match(c.last_name))


def contact_note(c: Contact) -> str:
    if c.generic_inbox:
        return "general inbox"
    if incomplete_name(c):
        return "incomplete name"
    return ""


def projected_rank(score: float, ranked: list[ScoredContact], category=None) -> int:
    """Rank the contact would take (within ``category``, or overall) if it were ranked with this score."""
    pool = [s for s in ranked if category is None or s.category == category]
    return 1 + sum(1 for s in pool if s.fit_score > score)


# ------------------------------------------------------------------------------ held contacts

def _reason_group(code: str, reason: str) -> str:
    if code == "POSSIBLE_PRIOR_INTRO":
        return "Possible prior introduction"
    text = reason.split(" '")[0].split(":")[0].split(" — ")[0].strip()
    return text or reason


def held_reasons(result: RunResult) -> dict[str, tuple[str, str]]:
    """email → (reason group, full reason) for every contact held for review."""
    out = {}
    for e in result.log:
        if e.status == LogStatus.REVIEW and e.email not in out:
            out[e.email] = (_reason_group(e.code, e.reason), e.reason)
    return out


def held_breakdown(result: RunResult) -> list[tuple[str, int]]:
    counts = Counter(group for group, _ in held_reasons(result).values())
    return counts.most_common()


def held_contacts(result: RunResult) -> list[ScoredContact]:
    """Held contacts by projected Fit Score (highest first)."""
    held = [s for s in result.scored if s.status.startswith("Review")]
    return sorted(held, key=lambda s: (-s.fit_score, -s.evidence_completeness, s.contact.email))


def held_rows(result: RunResult, limit: int | None = None) -> list[dict[str, Any]]:
    reasons = held_reasons(result)
    suggestions = {s.email: s for s in result.category_suggestions}
    threshold = result.config["thresholds"]["min_fit_score"]
    rows = []
    for s in held_contacts(result)[:limit]:
        c = s.contact
        sug = suggestions.get(c.email)
        category = sug.category if sug else s.category
        rank = projected_rank(s.fit_score, result.ranked, category)
        rows.append({
            "Projected fit": s.fit_score,
            "Would rank": (f"#{rank} in {category.value}" if category else f"#{rank} overall")
            if s.fit_score >= threshold else "below threshold",
            "Name": c.full_name, "Organization": c.organization,
            "Held because": reasons.get(c.email, ("", s.status))[1],
            "Investor type": c.get("investor_type"),
            "Claude suggests": sug.category.value if sug else "",
            "Email": c.email_display,
            "Why a fit": s.why,
        })
    return rows


# ------------------------------------------------------------------------------ warnings

def ten_relationship_unscored(result: RunResult) -> bool:
    return bool(result.scored) and all(s.component("ten_relationship").rating == 0 for s in result.scored)


def action_warnings(result: RunResult) -> tuple[list[str], list[str]]:
    """(warnings that need an action now — at most 3, most important first; every other note)."""
    deal = result.deal
    actions: list[str] = []
    if deal.conflicts:
        actions.append("Conflicting deck figures for " + ", ".join(f.label.lower() for f in deal.conflicts)
                       + " are not used — resolve them on the Profile step.")
    if any(x.startswith("Claude review of held contacts not completed") for x in result.limitations):
        actions.append("Claude's review of held contacts did not finish — held contacts were not checked.")
    if ten_relationship_unscored(result):
        actions.append("No TEN relationship data was found, so that 10% of the Fit Score is 0 for everyone — "
                       "map the core list / events columns on the Mapping step if the list has them.")
    if deal.facts["sector"].status == FactStatus.CLASSIFIED and "sector" not in deal.overrides:
        actions.append(f"Sector was classified from deck wording ({deal.effective_display('sector')}) — "
                       "confirm it on the Profile step.")
    if not any(f["Role"] == "Investor Introductions" for f in result.input_files):
        actions.append("No introduction tracker was uploaded — investors already introduced to this company "
                       "cannot be excluded.")
    shown = actions[:3]
    covered = ("Conflicting", "Claude review of held", "Sector/subsector classified", "No Investor Introductions")
    rest = actions[3:] + [x for x in result.limitations if not x.startswith(covered)]
    return shown, rest


# ------------------------------------------------------------------------------ deal profile

def likely_candidate(candidates: list, deck_text: str = "", filename: str = "") -> int:
    """Index of the most likely value among conflicting deck candidates: how often each value occurs in the
    deck (and the file name, for company names), then how often it was extracted; ties keep deck order."""
    text = deck_text.lower()
    fname = re.sub(r"[_\-.]+", " ", filename.lower())
    extracted = Counter(c.display for c in candidates)

    def score(i: int) -> tuple:
        d = candidates[i].display.lower().strip()
        return (text.count(d) if d else 0) + (3 if d and d in fname else 0), extracted[candidates[i].display], -i

    return max(range(len(candidates)), key=score) if candidates else 0
