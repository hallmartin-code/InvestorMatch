"""Column mapping: source headers → canonical fields, auto-detected and user-correctable."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.errors import MappingError
from app.ingestion.tables import ImportedTable


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    synonyms: tuple[str, ...]


INVESTOR_FIELDS: list[FieldSpec] = [
    FieldSpec("first_name", "First name", ("first name", "first", "given name", "firstname", "fname")),
    FieldSpec("last_name", "Last name", ("last name", "last", "surname", "family name", "lastname", "lname")),
    FieldSpec("full_name", "Full name", ("full name", "name", "contact name", "investor name", "contact",
                                          "person")),
    FieldSpec("email", "Email", ("email", "e mail", "email address", "e mail address", "work email",
                                  "primary email", "mail")),
    FieldSpec("alt_emails", "Alternative emails", ("alternative emails", "alternative email", "alternate emails",
                                                    "alternate email", "other emails", "secondary email",
                                                    "additional emails", "alt emails", "alt email")),
    FieldSpec("phone", "Phone", ("phone", "phone number", "mobile", "cell", "telephone", "tel", "mobile phone",
                                  "work phone")),
    FieldSpec("organization", "Organization", ("organization", "organisation", "organization person name",
                                                "organisation person name", "firm", "company", "fund",
                                                "org", "firm name", "company name", "account", "affiliation")),
    FieldSpec("title", "Title", ("title", "job title", "role", "position")),
    FieldSpec("investor_type", "Investor type", ("investor type", "type", "investor category", "category",
                                                  "contact type", "segment", "investor class")),
    FieldSpec("location", "Location", ("location", "city state", "city", "hq", "headquarters", "address",
                                        "based in", "region", "metro")),
    FieldSpec("country", "Country", ("country",)),
    FieldSpec("sector_focus", "Sector focus", ("sector focus", "sectors", "sector", "sector industries",
                                                "industry focus", "industries", "all sector tags", "sector tags",
                                                "primary sector", "sector interests", "focus areas", "focus",
                                                "verticals", "industry")),
    FieldSpec("thesis", "Thesis / subsector focus", ("thesis", "subsector", "sub sector", "niche",
                                                      "investment thesis", "subsector focus", "keywords")),
    FieldSpec("stage_focus", "Stage focus", ("stage focus", "stage", "stages", "stage preference",
                                              "investment stage", "preferred stage")),
    FieldSpec("check_size", "Check size", ("check size", "typical check", "ticket size", "investment size",
                                            "cheque size", "check", "check range", "investment range",
                                            "check intro size")),
    FieldSpec("check_min", "Check min", ("check min", "min check", "minimum check", "min investment")),
    FieldSpec("check_max", "Check max", ("check max", "max check", "maximum check", "max investment")),
    FieldSpec("geo_focus", "Geographic focus", ("geographic focus", "geo focus", "geography",
                                                 "geographic preference", "investment geography", "regions")),
    FieldSpec("participation", "Co-invest / lead", ("co invest", "coinvest", "lead follow", "lead or follow",
                                                     "participation", "leads", "syndicates")),
    FieldSpec("linkedin", "LinkedIn", ("linkedin", "linkedin url", "linkedin profile", "li url")),
    FieldSpec("suppression", "Unsubscribed / suppressed", ("unsubscribed", "unsubscribe", "suppressed",
                                                            "email status", "subscription status", "opt out",
                                                            "do not contact", "dnc", "status")),
    FieldSpec("ten_core", "TEN core list", ("core list", "ten core", "core", "core investor", "tier",
                                             "ten core list")),
    FieldSpec("ten_events", "TEN event participation", ("events attended", "event participation", "events",
                                                         "ten events", "event attendance")),
    FieldSpec("ten_similar_intros", "Intros to similar clients", ("similar intros", "similar client intros",
                                                                   "intros to similar clients",
                                                                   "prior intros", "intro history")),
    FieldSpec("description", "Description / profile", ("description", "description thesis", "profile", "bio",
                                                         "about", "overview", "investment focus",
                                                         "investor description")),
    FieldSpec("notes", "Notes", ("notes", "comments", "remarks")),
]

INTRO_FIELDS: list[FieldSpec] = [
    FieldSpec("company", "Company introduced", ("company", "startup", "client", "company name", "portfolio company",
                                                "deal", "introduced company", "client company")),
    FieldSpec("first_name", "Investor first name", ("first name", "investor first name", "first")),
    FieldSpec("last_name", "Investor last name", ("last name", "investor last name", "surname", "last")),
    FieldSpec("full_name", "Investor name", ("investor name", "investor", "name", "contact", "contact name")),
    FieldSpec("email", "Investor email", ("investor email", "email", "e mail", "email address")),
    FieldSpec("organization", "Investor organization", ("investor firm", "firm", "organization", "organisation",
                                                         "fund", "investor organization", "investor company")),
    FieldSpec("intro_date", "Introduction date", ("intro date", "introduction date", "date introduced", "date",
                                                  "introduced on", "intro sent")),
    FieldSpec("status", "Status / outcome", ("status", "outcome", "result", "stage")),
    FieldSpec("sector", "Company sector", ("sector", "industry", "company sector", "vertical")),
]

REQUIRED = {
    "investor": [("email",), ("full_name", "first_name")],
    "intro": [("email", "full_name", "first_name", "last_name", "organization")],
}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def auto_map(table: ImportedTable, specs: list[FieldSpec]) -> dict[str, str | None]:
    """Exact synonym → whole-word containment → fuzzy (≥ 88). Each column is used at most once."""
    headers = {col: _norm(col) for col in table.columns}
    mapping: dict[str, str | None] = {s.key: None for s in specs}
    used: set[str] = set()

    def take(spec: FieldSpec, col: str) -> None:
        mapping[spec.key] = col
        used.add(col)

    for spec in specs:                                  # pass 1: exact, in synonym priority order
        col = next((c for syn in spec.synonyms for c, norm in headers.items() if c not in used and norm == syn), None)
        if col:
            take(spec, col)
    for spec in specs:                                  # pass 2: containment of a multi-word synonym
        if mapping[spec.key]:
            continue
        for col, norm in headers.items():
            if col in used:
                continue
            if any(len(s.split()) > 1 and re.search(rf"\b{re.escape(s)}\b", norm) for s in spec.synonyms):
                take(spec, col)
                break
    for spec in specs:                                  # pass 3: fuzzy
        if mapping[spec.key]:
            continue
        best, best_score = None, 0.0
        for col, norm in headers.items():
            if col in used:
                continue
            score = max(fuzz.ratio(norm, s) for s in spec.synonyms)
            if score > best_score:
                best, best_score = col, score
        if best and best_score >= 88:
            take(spec, best)
    if "email" in mapping and not mapping["email"]:      # pass 4: find the email column by its contents
        column = email_column_by_content(table, exclude=used)
        if column:
            mapping["email"] = column
    return mapping


def email_column_by_content(table: ImportedTable, exclude: set[str] = frozenset()) -> str | None:
    """The column whose sampled non-empty cells are mostly valid email addresses (≥ 60%)."""
    from app.utils.text import is_valid_email, normalize_email

    best, best_share = None, 0.0
    for col in table.columns:
        if col in exclude:
            continue
        values = [r[col] for r in table.rows[:300] if r.get(col)]
        if len(values) < 1:
            continue
        share = sum(is_valid_email(normalize_email(v)) for v in values) / len(values)
        if share > best_share:
            best, best_share = col, share
    return best if best_share >= 0.6 else None


# ------------------------------------------------------------------------------ sheet roles

ROLE_CONTACTS = "contacts"
ROLE_SUPPRESSION = "suppression"
ROLE_SKIP = "skip"
ROLE_LABELS = {ROLE_CONTACTS: "Investor contacts", ROLE_SUPPRESSION: "Unsubscribe / suppression list",
               ROLE_SKIP: "Skip this sheet"}
_SUPPRESSION_SHEET = re.compile(r"unsub|suppress|opt.?out|do.?not.?(contact|email)|\bdnc\b|bounce|blacklist|"
                                r"block.?list|removed", re.I)
_SUPPRESSION_VALUE = re.compile(r"^(unsub\w*|unsubscribed|opted.?out|suppressed|do not contact|dnc|bounced?)$", re.I)


def detect_role(table: ImportedTable, mapping: dict[str, str | None]) -> tuple[str, str]:
    """(role, reason) for an investor-list sheet. Never guesses a contact list it cannot map."""
    if _SUPPRESSION_SHEET.search(table.sheet or table.filename):
        return ROLE_SUPPRESSION, "sheet name indicates an unsubscribe / suppression list"
    for col in table.columns:
        values = [r[col] for r in table.rows if r.get(col)]
        if values and len(values) >= 0.8 * len(table.rows) and                 sum(bool(_SUPPRESSION_VALUE.match(v.strip())) for v in values) >= 0.9 * len(values):
            return ROLE_SUPPRESSION, f"every row is marked '{values[0]}' in column '{col}'"
    problems = validate_mapping(mapping, "investor", table)
    if problems:
        return ROLE_SKIP, "no email and name columns could be identified — map them to use this sheet"
    return ROLE_CONTACTS, ""


def validate_mapping(mapping: dict[str, str | None], kind: str, table: ImportedTable) -> list[str]:
    """Problems that block using the table (empty list = OK)."""
    problems = []
    for group in REQUIRED[kind]:
        if not any(mapping.get(key) for key in group):
            names = " or ".join(group)
            problems.append(f"{table.label}: map a column to {names}.")
    for key, col in mapping.items():
        if col and col not in table.columns:
            problems.append(f"{table.label}: column '{col}' (for {key}) does not exist.")
    return problems


def require_valid(mapping: dict[str, str | None], kind: str, table: ImportedTable) -> None:
    problems = validate_mapping(mapping, kind, table)
    if problems:
        raise MappingError(" ".join(problems))


def apply_mapping(table: ImportedTable, mapping: dict[str, str | None]) -> list[tuple[dict[str, str], int]]:
    """Rows as {canonical key: text} with their source row numbers."""
    out = []
    for row, number in zip(table.rows, table.row_numbers, strict=True):
        out.append(({key: row.get(col, "") if col else "" for key, col in mapping.items()}, number))
    return out
