"""Prior-introduction screening.

Company relevance of each intro row:
* company column equals an alias (normalized)      → this company
* company similar to an alias (fuzzy)              → possible alias  → REVIEW
* no company column, file marked company-specific  → this company
* no company column, file not marked               → company not stated → REVIEW
* otherwise                                        → other company (used only as similar-client evidence)

Contact match:
* email (case-insensitive)                         → definite
* same normalized name and organization            → definite
* same name, organization differs or missing       → ambiguous → REVIEW
* similar name, same organization                  → ambiguous → REVIEW
* organization-only intro row                      → ambiguous for each contact at that organization

Definite match on a "this company" row → excluded as already introduced. Anything ambiguous →
held for review (never silently treated as a new contact).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from app.extraction import taxonomy as tx
from app.ingestion.mapping import apply_mapping
from app.ingestion.tables import ImportedTable
from app.models import Contact, IntroMatch, IntroRecord, SourceRef
from app.utils.text import normalize_email, normalize_org, normalize_person, split_name

_GENERIC_WORDS = {"health", "smart", "digital", "global", "green", "first", "united", "american", "advanced",
                  "micro", "micro", "clear", "bright", "north", "south", "blue", "open", "next", "true", "prime"}

THIS = "this company"
ALIAS = "possible alias"
UNSTATED = "company not stated"
OTHER = "other company"


def file_mentions_alias(filename: str, aliases: list[str]) -> bool:
    stem = normalize_org(re.sub(r"[_\-.]+", " ", Path(filename).stem))
    return any(a and normalize_org(a) and re.search(rf"\b{re.escape(normalize_org(a))}\b", stem) for a in aliases)


def build_intro_records(table: ImportedTable, mapping: dict[str, str | None],
                        company_specific: bool) -> list[IntroRecord]:
    out = []
    for values, row in apply_mapping(table, mapping):
        first, last = values.get("first_name", ""), values.get("last_name", "")
        full = values.get("full_name", "") or " ".join(p for p in (first, last) if p)
        if full and not (first or last):
            first, last = split_name(full)
        out.append(IntroRecord(
            company=values.get("company", ""), first_name=first, last_name=last, full_name=full,
            email=normalize_email(values.get("email", "")), organization=values.get("organization", ""),
            intro_date=values.get("intro_date", ""), status=values.get("status", ""), sector=values.get("sector", ""),
            source=SourceRef(table.filename, f"row {row}", table.sheet),
            company_specific_file=company_specific and not mapping.get("company"),
        ))
    return out


def company_relation(intro: IntroRecord, aliases: list[str], cfg: dict[str, Any]) -> str:
    if not intro.company:
        return THIS if intro.company_specific_file else UNSTATED
    name = normalize_org(intro.company)
    norm_aliases = [normalize_org(a) for a in aliases if normalize_org(a)]
    if name in norm_aliases:
        return THIS
    threshold = cfg["screening"]["intro_company_ambiguous"]
    best = max((max(fuzz.ratio(name, a), fuzz.token_sort_ratio(name, a)) for a in norm_aliases), default=0)
    if best >= threshold:
        return ALIAS
    # Same distinctive first word ("Cardiolyte Labs" vs "Cardiolyte Health"): possibly renamed.
    first = name.split()[0] if name else ""
    if len(first) >= 5 and first not in _GENERIC_WORDS and any(a.split()[0] == first for a in norm_aliases):
        return ALIAS
    return OTHER


@dataclass
class IntroScreen:
    introduced: dict[str, list[IntroMatch]] = field(default_factory=dict)   # email → definite matches
    review: dict[str, list[IntroMatch]] = field(default_factory=dict)       # email → ambiguous matches
    unmatched: list[IntroMatch] = field(default_factory=list)              # this-company rows not in master list
    similar_clients: dict[str, list[IntroRecord]] = field(default_factory=dict)  # email → other-company intros
    relation_counts: dict[str, int] = field(default_factory=dict)


def _match_contact(intro: IntroRecord, contacts_by_email: dict[str, Contact],
                   by_name: dict[str, list[Contact]], by_org: dict[str, list[Contact]],
                   cfg: dict[str, Any]) -> list[tuple[Contact, str, bool]]:
    if intro.email and intro.email in contacts_by_email:
        return [(contacts_by_email[intro.email], "email", True)]
    name = normalize_person(intro.full_name)
    org = normalize_org(intro.organization)
    results: list[tuple[Contact, str, bool]] = []
    if name:
        for c in by_name.get(name, []):
            c_org = normalize_org(c.organization)
            if org and c_org and (org == c_org or fuzz.ratio(org, c_org) >= 92):
                results.append((c, "name + organization", True))
            else:
                why = "name only (organization differs)" if org and c_org else "name only (organization missing)"
                results.append((c, why, False))
        if not results and org:
            threshold = cfg["screening"]["name_fuzzy_ambiguous"]
            for c in by_org.get(org, []):
                if fuzz.token_sort_ratio(name, normalize_person(c.full_name)) >= threshold:
                    results.append((c, "similar name + organization", False))
    elif org:
        for c in by_org.get(org, []):
            results.append((c, "organization-level introduction", False))
    return results


def _same_sector(text: str, sector: str) -> bool:
    tags = tx.parse_sector_focus(text)
    return sector in tags.sectors or any(sc == sector for sc, _s in tags.subsectors)


def screen_introductions(contacts: list[Contact], intros: list[IntroRecord], aliases: list[str],
                         cfg: dict[str, Any], sector: str | None = None) -> IntroScreen:
    screen = IntroScreen()
    by_email = {c.email: c for c in contacts}
    by_name: dict[str, list[Contact]] = {}
    by_org: dict[str, list[Contact]] = {}
    for c in contacts:
        if normalize_person(c.full_name):
            by_name.setdefault(normalize_person(c.full_name), []).append(c)
        if normalize_org(c.organization):
            by_org.setdefault(normalize_org(c.organization), []).append(c)
    for intro in intros:
        relation = company_relation(intro, aliases, cfg)
        screen.relation_counts[relation] = screen.relation_counts.get(relation, 0) + 1
        matches = _match_contact(intro, by_email, by_name, by_org, cfg)
        if relation == OTHER:
            if sector and intro.sector and _same_sector(intro.sector, sector):
                for contact, _basis, definite in matches:
                    if definite:
                        screen.similar_clients.setdefault(contact.email, []).append(intro)
            continue
        if not matches and relation == THIS:
            screen.unmatched.append(IntroMatch(None, intro, "not in TEN master list", True, relation))
        for contact, basis, definite in matches:
            match = IntroMatch(contact.email, intro, basis, definite, relation)
            if definite and relation == THIS:
                screen.introduced.setdefault(contact.email, []).append(match)
            else:
                screen.review.setdefault(contact.email, []).append(match)
    for email in screen.introduced:
        screen.review.pop(email, None)
    return screen
