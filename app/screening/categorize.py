"""Investor type → category. Ambiguous or unstated types are flagged for review, never forced."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import Category, Contact

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EXCLUDED_PE", re.compile(r"private equity|\bPE\b|buy-?outs?", re.I)),
    ("EXCLUDED_BANK", re.compile(r"investment bank\w*|broker[- ]dealer|\bIB\b|placement agent", re.I)),
    ("EXCLUDED_GROWTH", re.compile(r"growth equity|late[- ]stage (?:fund|investor|vc)|growth fund|crossover", re.I)),
    (Category.ANGEL_GROUP, re.compile(r"angel (?:group|network|club|collective|fund|association|syndicate)|"
                                      r"\bsyndicates?\b|investor network|angel groups?", re.I)),
    (Category.ANGEL, re.compile(r"\bangel\b|\bangel investor\b|individual investor|\bindividual\b", re.I)),
    (Category.FAMILY_OFFICE, re.compile(r"family (?:investment )?offices?|family investment|\bHNI\b|\bHNWI?s?\b|"
                                        r"high[- ]net[- ]worth|\bSFO\b|\bMFO\b|private wealth", re.I)),
    (Category.VC, re.compile(r"venture capital|\bVCs?\b|venture fund|seed fund|micro[- ]?vc|corporate venture\w*|"
                             r"\bCVC\b|venture arm|early[- ]stage fund|pre-?seed fund|\bventures?\b", re.I)),
]
EXCLUSION_REASONS = {
    "EXCLUDED_PE": "Private equity / buyout investor",
    "EXCLUDED_BANK": "Investment bank / broker-dealer",
    "EXCLUDED_GROWTH": "Growth-equity / late-stage-only investor type",
}


@dataclass
class CategoryResult:
    category: Category | None = None
    excluded_code: str | None = None
    excluded_reason: str | None = None
    review_reason: str | None = None


def categorize(contact: Contact) -> CategoryResult:
    if contact.values.get("_type_conflict"):
        return CategoryResult(review_reason=f"Duplicate records disagree on investor type: {contact.values['_type_conflict']}")
    text = contact.get("investor_type")
    if not text:
        return CategoryResult(review_reason="Investor type not stated — categorize manually")
    hits = [key for key, pat in _PATTERNS if pat.search(text)]
    if Category.ANGEL_GROUP in hits and Category.ANGEL in hits:
        hits.remove(Category.ANGEL)
    excluded = [h for h in hits if isinstance(h, str) and h.startswith("EXCLUDED")]
    categories = [h for h in hits if isinstance(h, Category)]
    if excluded and not categories:
        code = excluded[0]
        return CategoryResult(excluded_code=code, excluded_reason=f"{EXCLUSION_REASONS[code]} ('{text}')")
    if excluded and categories:
        return CategoryResult(review_reason=f"Mixed investor type '{text}' (early-stage and excluded types)")
    if len(categories) == 1:
        return CategoryResult(category=categories[0])
    if len(categories) > 1:
        return CategoryResult(review_reason=f"Ambiguous investor type '{text}' fits several categories")
    return CategoryResult(review_reason=f"Unrecognized investor type '{text}'")
