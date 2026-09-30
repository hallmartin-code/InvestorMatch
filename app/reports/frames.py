"""Workbook content shared by the Excel and Google Sheets exports (one source of truth for counts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import APP_VERSION
from app.reports.template import load_template
from app.models import (
    DEAL_FIELDS,
    CATEGORY_ORDER,
    LogStatus,
    RunResult,
    ScoredContact,
    refs_label,
)

NEEDS_RESEARCH = "needs research"

_T = load_template()
RANKED_COLUMNS = _T.sheet_columns("Ranked Investors")
ALREADY_COLUMNS = _T.sheet_columns("Already Introduced")
PROFILE_COLUMNS = _T.sheet_columns("Deal Profile")
EXCLUSION_COLUMNS = _T.sheet_columns("Exclusions and Review")
EVIDENCE_COLUMNS = _T.sheet_columns("Scoring Evidence")
SHEET_NAMES = [sheet.name for sheet in _T.sheets]
_STATUS_ORDER = {LogStatus.REVIEW: 0, LogStatus.EXCLUDED: 1, LogStatus.FLAG: 2, LogStatus.MERGED: 3, LogStatus.INFO: 4}


@dataclass
class Sheet:
    name: str
    columns: list[str]
    rows: list[list[Any]]
    extra_blocks: list[tuple[str, list[str], list[list[Any]]]] = field(default_factory=list)  # (title, cols, rows)
    wrap: set[str] = field(default_factory=set)
    percent: set[str] = field(default_factory=set)
    decimal: set[str] = field(default_factory=set)


def _or_research(value: str) -> str:
    return value.strip() if value and value.strip() else NEEDS_RESEARCH


def ranked_rows(result: RunResult) -> list[list[Any]]:
    rows = []
    for s in result.ranked:
        c = s.contact
        rows.append([
            s.category.value, s.fit_score, _or_research(c.first_name), _or_research(c.last_name),
            _or_research(c.organization), c.email_display, _or_research(c.get("phone")),
            _or_research(c.get("investor_type")),
            _or_research(", ".join(p for p in (c.get("location"), c.get("country")) if p)),
            s.why, s.ten_relationship, _or_research(c.get("linkedin")),
        ])
    return rows


def _weighted(s: ScoredContact) -> str:
    terms = " + ".join(f"{c.weight:.2f}×{c.rating:g}" for c in s.components)
    return f"{terms} = {sum(c.weighted for c in s.components):.2f} → {s.fit_score:.1f}"


def evidence_rows(result: RunResult) -> list[list[Any]]:
    order = {"Ranked": 0, "Organization cap": 1, "Below threshold": 2}
    scored = sorted(result.scored, key=lambda s: (order.get(s.status, 3),
                                                  CATEGORY_ORDER.index(s.category) if s.category else 9,
                                                  -s.fit_score, s.contact.email))
    rows = []
    for s in scored:
        c = s.contact
        comp = {x.key: x for x in s.components}
        flags = [f for x in s.components for f in x.flags] + [f"{x.label}: inferred" for x in s.components if x.inferred]
        if c.generic_inbox:
            flags.append("generic inbox")
        if c.merged_count > 1:
            flags.append(f"merged from {c.merged_count} records")
        rows.append([
            s.status, s.category.value if s.category else "Needs review", s.rank or "", s.fit_score,
            s.evidence_completeness, c.first_name, c.last_name, c.organization, c.email_display,
            comp["sector"].rating, comp["sector"].evidence, comp["stage"].rating, comp["stage"].evidence,
            comp["check_size"].rating, comp["check_size"].evidence, comp["geography"].rating,
            comp["geography"].evidence, comp["ten_relationship"].rating, comp["ten_relationship"].evidence,
            _weighted(s), "; ".join(flags), refs_label(c.sources),
        ])
    return rows


def exclusion_rows(result: RunResult) -> list[list[Any]]:
    entries = sorted(result.log, key=lambda e: (_STATUS_ORDER[e.status], e.code, e.email))
    return [[e.status.value, e.code, e.reason, e.first_name, e.last_name, e.organization, e.email, e.investor_type,
             refs_label(e.sources), e.detail] for e in entries]


def profile_rows(result: RunResult) -> list[list[Any]]:
    deal = result.deal
    rows = []
    for name, label in DEAL_FIELDS.items():
        f = deal.facts[name]
        o = deal.overrides.get(name)
        excerpt = " | ".join(dict.fromkeys(s.excerpt for s in f.sources if s.excerpt))[:500]
        rows.append([label, f.display, f.status.value, refs_label(f.sources, limit=6), excerpt,
                     o.display if o else "", o.reason if o else "", deal.effective_display(name),
                     " ".join(f.notes)])
    return rows


def build_sheets(result: RunResult) -> list[Sheet]:
    ctx = result.context
    cfg = result.config
    run_info = [
        ["Report date", result.report_date.isoformat()],
        ["Deck file", result.deal.deck_file],
        ["Remaining allocation used for check-size fit",
         f"{ctx.remaining.display()} ({ctx.remaining_basis})" if ctx.remaining else
         (f"not established — compared with full raise {ctx.raise_amount.display()}" if ctx.raise_amount
          else "not established")],
        ["Company aliases used for prior-introduction matching", "; ".join(ctx.aliases) or "none"],
        ["Scoring weights", ", ".join(f"{k} {v:.0%}" for k, v in cfg["weights"].items())],
        ["Minimum Fit Score / organization cap", f"{cfg['thresholds']['min_fit_score']} / {cfg['thresholds']['org_cap']}"],
        ["Scoring config fingerprint", cfg.get("_fingerprint", "")],
        ["App version", APP_VERSION],
        ["Extraction log", " · ".join(result.deal.extraction_log)],
    ]
    files_cols = ["Role", "File", "Sheet", "Rows", "SHA-256", "Company-specific"]
    files_rows = [[f[c] for c in files_cols] for f in result.input_files]
    return [
        Sheet("Ranked Investors", RANKED_COLUMNS, ranked_rows(result), wrap={"Why a fit"}, decimal={"Fit Score"}),
        Sheet("Already Introduced", ALREADY_COLUMNS, [[r[c] for c in ALREADY_COLUMNS] for r in result.already_introduced]),
        Sheet("Deal Profile", PROFILE_COLUMNS, profile_rows(result),
              extra_blocks=[("Run information", ["Item", "Value"], run_info),
                            ("Input files", files_cols, files_rows),
                            ("Screening limitations", ["Limitation"], [[x] for x in result.limitations])],
              wrap={"Evidence Excerpt", "Notes", "Deck Value", "Effective Value"}),
        Sheet("Exclusions and Review", EXCLUSION_COLUMNS, exclusion_rows(result), wrap={"Detail", "Reason"}),
        Sheet("Scoring Evidence", EVIDENCE_COLUMNS, evidence_rows(result),
              wrap={"Sector Evidence", "Check Size Evidence", "TEN Relationship Evidence", "Weighted Calculation"},
              percent={"Evidence Completeness"}, decimal={"Fit Score"}),
    ]


def summary_counts(result: RunResult) -> dict[str, Any]:
    """The numbers the PDF prints — tests assert they equal the workbook's row counts."""
    by_cat = result.counts_by_category()
    return {
        "qualified": {c.value: by_cat[c] for c in CATEGORY_ORDER},
        "qualified_total": len(result.ranked),
        "already_introduced": len(result.already_introduced),
        "review": sum(1 for e in result.log if e.status == LogStatus.REVIEW),
        "excluded": sum(1 for e in result.log if e.status == LogStatus.EXCLUDED),
    }
