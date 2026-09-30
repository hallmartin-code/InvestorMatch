"""Core data structures shared by extraction, screening and reporting.

Plain dataclasses: every value that reaches a report carries the source references it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class SourceRef:
    """Where a value came from: a deck slide/page or a spreadsheet file, sheet and row."""

    file: str
    locator: str                 # "slide 4", "page 7 (OCR)", "row 14"
    sheet: str | None = None
    excerpt: str = ""

    @property
    def label(self) -> str:
        parts = [self.file]
        if self.sheet:
            parts.append(self.sheet)
        parts.append(self.locator)
        return " › ".join(parts)


def refs_label(refs: list[SourceRef], limit: int = 4) -> str:
    labels = list(dict.fromkeys(r.label for r in refs))
    more = f" (+{len(labels) - limit} more)" if len(labels) > limit else ""
    return "; ".join(labels[:limit]) + more


# ------------------------------------------------------------------------------ deal profile


class FactStatus(StrEnum):
    STATED = "Stated in deck"
    CLASSIFIED = "Classified from deck language"
    CALCULATED = "Calculated"
    METADATA = "File metadata"
    CONFLICT = "Conflicting figures"
    NOT_STATED = "Not stated in deck"


NOT_STATED_TEXT = "not stated in deck"


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str = "USD"

    def display(self) -> str:
        symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$", "AUD": "A$"}.get(self.currency)
        a = self.amount
        if a >= 1_000_000_000:
            text = f"{a / 1e9:.2f}".rstrip("0").rstrip(".") + "B"
        elif a >= 1_000_000:
            text = f"{a / 1e6:.2f}".rstrip("0").rstrip(".") + "M"
        elif a >= 1_000:
            text = f"{a / 1e3:.1f}".rstrip("0").rstrip(".") + "K"
        else:
            text = f"{a:,.0f}"
        return f"{symbol}{text}" if symbol else f"{text} {self.currency}"


@dataclass
class Candidate:
    """One value found in the deck for a field, with its source."""

    value: Any
    display: str
    source: SourceRef
    detail: dict[str, Any] = field(default_factory=dict)   # e.g. round label, commitment type, as-of date


@dataclass
class Fact:
    field: str
    label: str
    status: FactStatus = FactStatus.NOT_STATED
    value: Any = None
    display: str = NOT_STATED_TEXT
    sources: list[SourceRef] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.value is not None and self.status not in (FactStatus.CONFLICT, FactStatus.NOT_STATED)


@dataclass
class Override:
    """A user correction. Stored separately from deck facts; never overwrites them."""

    field: str
    value: Any
    display: str
    reason: str = ""
    entered_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


DEAL_FIELDS: dict[str, str] = {
    "company_name": "Company",
    "legal_name": "Legal name",
    "sector": "Sector",
    "subsector": "Subsector",
    "stage": "Stage",
    "raise_amount": "Raise amount",
    "instrument": "Instrument",
    "amount_committed": "Amount committed (signed / committed)",
    "soft_interest": "Soft interest (not committed)",
    "amount_remaining": "Amount remaining",
    "company_geography": "Company geography",
    "target_investor_geography": "Target investor geography",
    "target_close_date": "Target close date",
    "deck_date": "Deck date",
}


@dataclass
class DealProfile:
    deck_file: str
    facts: dict[str, Fact]
    overrides: dict[str, Override] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extraction_log: list[str] = field(default_factory=list)

    def fact(self, name: str) -> Fact:
        return self.facts[name]

    def effective(self, name: str) -> Any:
        if name in self.overrides:
            return self.overrides[name].value
        f = self.facts.get(name)
        return f.value if f is not None and f.resolved else None

    def effective_display(self, name: str) -> str:
        if name in self.overrides:
            return self.overrides[name].display
        f = self.facts[name]
        if f.status == FactStatus.CONFLICT:
            return "conflicting figures — " + " vs ".join(dict.fromkeys(c.display for c in f.candidates))
        return f.display

    @property
    def conflicts(self) -> list[Fact]:
        return [f for n, f in self.facts.items() if f.status == FactStatus.CONFLICT and n not in self.overrides]

    @property
    def missing(self) -> list[Fact]:
        return [f for n, f in self.facts.items() if f.status == FactStatus.NOT_STATED and n not in self.overrides]


# ------------------------------------------------------------------------------ geography


@dataclass(frozen=True)
class Location:
    raw: str
    city: str | None = None
    state: str | None = None       # US state / Canadian province abbreviation
    country: str | None = None     # ISO-like code, e.g. US, CA, GB

    def display(self) -> str:
        parts = [p for p in (self.city, self.state, self.country) if p]
        return ", ".join(parts) or self.raw


@dataclass(frozen=True)
class GeoArea:
    kind: str                      # city | state | subregion | country | region | global
    name: str
    states: frozenset[str] = frozenset()
    countries: frozenset[str] = frozenset()
    city: str | None = None


# ------------------------------------------------------------------------------ contacts


@dataclass
class ContactRecord:
    """One row of the TEN Capital Investor List after column mapping (values as text)."""

    values: dict[str, str]
    source: SourceRef

    def get(self, key: str) -> str:
        return (self.values.get(key) or "").strip()


@dataclass
class Contact:
    """A consolidated investor contact (one per normalized email)."""

    email: str                     # normalized (lower-case)
    email_display: str
    first_name: str
    last_name: str
    organization: str
    values: dict[str, str]         # consolidated mapped values
    sources: list[SourceRef]
    merged_count: int = 1
    consolidation_notes: list[str] = field(default_factory=list)
    suppressed_reason: str | None = None
    generic_inbox: bool = False

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    def get(self, key: str) -> str:
        return (self.values.get(key) or "").strip()


class Category(StrEnum):
    ANGEL = "Angels"
    ANGEL_GROUP = "Angel Groups & Syndicates"
    FAMILY_OFFICE = "HNI & Family Offices"
    VC = "VCs (Seed & Early-Stage)"


CATEGORY_ORDER = [Category.ANGEL, Category.ANGEL_GROUP, Category.FAMILY_OFFICE, Category.VC]


@dataclass
class ComponentScore:
    key: str
    label: str
    rating: float                  # 0–10
    weight: float
    known: bool                    # investor-side evidence exists
    evidence: str
    inferred: bool = False
    flags: list[str] = field(default_factory=list)

    @property
    def weighted(self) -> float:
        return self.rating * self.weight


@dataclass
class ScoredContact:
    contact: Contact
    category: Category | None
    components: list[ComponentScore]
    fit_score: float
    evidence_completeness: float   # 0–1
    why: str
    ten_relationship: str          # Y | N | needs research
    status: str = "Ranked"
    rank: int | None = None

    def component(self, key: str) -> ComponentScore:
        return next(c for c in self.components if c.key == key)


class LogStatus(StrEnum):
    EXCLUDED = "EXCLUDED"
    REVIEW = "REVIEW"
    FLAG = "FLAG"
    MERGED = "MERGED"
    INFO = "INFO"


@dataclass
class LogEntry:
    status: LogStatus
    code: str
    reason: str
    first_name: str = ""
    last_name: str = ""
    organization: str = ""
    email: str = ""
    investor_type: str = ""
    sources: list[SourceRef] = field(default_factory=list)
    detail: str = ""


@dataclass
class IntroRecord:
    """One row of an Investor Introductions list."""

    company: str
    first_name: str
    last_name: str
    full_name: str
    email: str
    organization: str
    intro_date: str
    status: str
    sector: str
    source: SourceRef
    company_specific_file: bool = False


@dataclass
class IntroMatch:
    contact_email: str | None      # None when the intro row matches no master contact
    intro: IntroRecord
    basis: str                     # "email", "name + organization", ...
    definite: bool
    company_relation: str          # "this company" | "possible alias" | "company not stated"


@dataclass
class RunResult:
    deal: DealProfile
    context: Any                   # DealContext
    ranked: list[ScoredContact]
    scored: list[ScoredContact]
    log: list[LogEntry]
    already_introduced: list[dict[str, str]]
    limitations: list[str]
    input_files: list[dict[str, str]]
    config: dict[str, Any]
    report_date: date
    stats: dict[str, Any] = field(default_factory=dict)
    notifications: list[Any] = field(default_factory=list)   # NotificationOutcome per email attempt
    category_suggestions: list[Any] = field(default_factory=list)   # verified Claude suggestions (claude_review)

    def counts_by_category(self) -> dict[Category, int]:
        counts = {c: 0 for c in CATEGORY_ORDER}
        for s in self.ranked:
            counts[s.category] += 1
        return counts
