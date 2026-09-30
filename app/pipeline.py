"""Orchestration: deck → deal profile → screened, scored, ranked contacts → RunResult.

Every step is a pure function of its inputs (deck, tables + mappings, overrides, decisions, config),
so the UI and CLI produce identical results for identical inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.extraction.deal_profile import build_context, extract_profile
from app.ingestion.deck import DeckDocument, read_deck
from app.ingestion.mapping import INTRO_FIELDS, INVESTOR_FIELDS, auto_map, require_valid
from app.ingestion.tables import ImportedTable, read_table_file
from app.models import (
    DealProfile,
    FactStatus,
    LogEntry,
    LogStatus,
    RunResult,
    ScoredContact,
    refs_label,
)
from app.screening import introductions as intro_mod
from app.screening.categorize import categorize
from app.screening.contacts import build_records, consolidate, contact_log
from app.screening.ranking import rank
from app.screening.scoring import incompatibility, parse_attributes, score_contact
from app.utils.logging import get_logger

LOGGER = get_logger(__name__)

DECISION_REVIEW = "Review"
DECISION_NEW = "Treat as not introduced"
DECISION_INTRODUCED = "Treat as introduced"


@dataclass
class TableInput:
    table: ImportedTable
    mapping: dict[str, str | None]
    company_specific: bool = False     # intro lists without a company column


def load_tables(path: Path | None = None, *, data: bytes | None = None, filename: str | None = None,
                kind: str = "investor") -> list[TableInput]:
    specs = INVESTOR_FIELDS if kind == "investor" else INTRO_FIELDS
    tables = read_table_file(path, data=data, filename=filename)
    return [TableInput(t, auto_map(t, specs)) for t in tables]


def load_deck(path: Path, cfg: dict[str, Any], display_name: str | None = None) -> DeckDocument:
    return read_deck(Path(path), display_name, cfg.get("ocr", {}))


def extract(deck: DeckDocument, *, llm_client: Any = None) -> DealProfile:
    profile = extract_profile(deck)
    if llm_client is not None:
        from app.extraction.llm import augment_profile

        augment_profile(profile, deck, llm_client)
    return profile


def _already_row(contact, match, in_master: bool) -> dict[str, str]:
    intro = match.intro
    c = contact
    return {
        "Status": "DO NOT RE-INTRO",
        "First Name": c.first_name if c else intro.first_name,
        "Last Name": c.last_name if c else intro.last_name,
        "Organization": c.organization if c else intro.organization,
        "Email": c.email_display if c else intro.email,
        "Introduction Date": intro.intro_date or "not recorded",
        "Introduction Source": intro.source.label,
        "Company in Source": intro.company or "(file for this company)",
        "Match Basis": match.basis,
        "In TEN Master List": "Y" if in_master else "N",
        "Master List Source": refs_label(c.sources) if c else "",
        "Intro Status / Outcome": intro.status,
    }


def run_matching(profile: DealProfile, investor_tables: list[TableInput], intro_tables: list[TableInput],
                 cfg: dict[str, Any], *, user_aliases: list[str] | None = None,
                 intro_decisions: dict[str, str] | None = None, report_date: date | None = None) -> RunResult:
    intro_decisions = intro_decisions or {}
    ctx = build_context(profile, user_aliases)
    for t in investor_tables:
        require_valid(t.mapping, "investor", t.table)
    for t in intro_tables:
        require_valid(t.mapping, "intro", t.table)

    records = [r for t in investor_tables for r in build_records(t.table, t.mapping, cfg)]
    contacts, log = consolidate(records, cfg)
    limitations: list[str] = []

    active = []
    for c in contacts:
        if c.suppressed_reason:
            log.append(contact_log(LogStatus.EXCLUDED, "SUPPRESSED", "Unsubscribed / suppressed", c,
                                   c.suppressed_reason))
        else:
            active.append(c)

    # ---- prior introductions
    intros = [rec for t in intro_tables
              for rec in intro_mod.build_intro_records(t.table, t.mapping, t.company_specific)]
    screen = intro_mod.screen_introductions(active, intros, ctx.aliases, cfg, ctx.sector)
    for email, decision in intro_decisions.items():
        if email in screen.review and decision == DECISION_INTRODUCED:
            screen.introduced[email] = [m for m in screen.review.pop(email)]
            for m in screen.introduced[email]:
                m.basis += " (confirmed by reviewer)"
        elif email in screen.review and decision == DECISION_NEW:
            screen.review.pop(email)
            log.append(LogEntry(LogStatus.INFO, "INTRO_REVIEW_CLEARED",
                                "Reviewer confirmed: not previously introduced", email=email))
    by_email = {c.email: c for c in active}
    already: list[dict[str, str]] = []
    for email, matches in screen.introduced.items():
        c = by_email[email]
        log.append(contact_log(LogStatus.EXCLUDED, "ALREADY_INTRODUCED", "Already introduced to this company — do not re-intro",
                               c, "; ".join(f"{m.basis}: {m.intro.source.label}" +
                                            (f" on {m.intro.intro_date}" if m.intro.intro_date else "")
                                            for m in matches)))
        already.append(_already_row(c, matches[0], True))
    seen_unmatched: set[str] = set()
    for m in screen.unmatched:
        key = m.intro.email or f"{m.intro.full_name.lower()}|{m.intro.organization.lower()}"
        if key in seen_unmatched or not key.strip("|"):
            continue
        seen_unmatched.add(key)
        already.append(_already_row(None, m, False))
    for email, matches in screen.review.items():
        c = by_email[email]
        log.append(contact_log(LogStatus.REVIEW, "POSSIBLE_PRIOR_INTRO",
                               "Possible prior introduction — confirm before outreach", c,
                               "; ".join(f"{m.basis} [{m.company_relation}: {m.intro.company or 'no company column'}]"
                                         f" — {m.intro.source.label}" for m in matches)))

    # ---- categorize, screen, score
    min_score = cfg["thresholds"]["min_fit_score"]
    scored: list[ScoredContact] = []
    qualified: list[ScoredContact] = []
    for c in active:
        if c.email in screen.introduced:
            continue
        cat = categorize(c)
        if cat.excluded_code:
            log.append(contact_log(LogStatus.EXCLUDED, cat.excluded_code, cat.excluded_reason, c))
            continue
        attrs = parse_attributes(c, screen.similar_clients.get(c.email))
        clash = incompatibility(attrs, ctx)
        if clash:
            log.append(contact_log(LogStatus.EXCLUDED, clash[0], clash[1], c))
            continue
        s = score_contact(c, attrs, ctx, cat.category, cfg)
        scored.append(s)
        if ctx.target_investor_geo and attrs.location is None:
            log.append(contact_log(LogStatus.FLAG, "LOCATION_UNKNOWN",
                                   "Location unknown; deck states a target investor geography", c))
        if cat.review_reason:
            s.status = "Review: category"
            log.append(contact_log(LogStatus.REVIEW, "CATEGORY_REVIEW", cat.review_reason, c,
                                   f"Fit Score {s.fit_score:.1f} if categorized"))
            continue
        if c.email in screen.review:
            s.status = "Review: possible prior intro"
            continue
        if s.fit_score < min_score:
            s.status = "Below threshold"
            log.append(contact_log(LogStatus.EXCLUDED, "BELOW_THRESHOLD",
                                   f"Fit Score {s.fit_score:.1f} < {min_score:.1f}", c,
                                   f"evidence completeness {s.evidence_completeness:.0%}; "
                                   + "; ".join(f for comp in s.components for f in comp.flags)))
            continue
        qualified.append(s)

    ranked, capped = rank(qualified, cfg["thresholds"]["org_cap"])
    for s in capped:
        log.append(contact_log(LogStatus.EXCLUDED, "ORG_CAP",
                               f"Organization already has {cfg['thresholds']['org_cap']} higher-ranked contacts",
                               s.contact, f"Fit Score {s.fit_score:.1f}"))
    for s in ranked:
        if s.contact.generic_inbox:
            log.append(contact_log(LogStatus.FLAG, "GENERIC_INBOX",
                                   "Generic inbox — find a named contact if possible", s.contact))

    # ---- limitations
    limitations.extend(_limitations(profile, ctx, intro_tables, screen, ranked, contacts, log))
    stats = {
        "investor_rows": len(records), "unique_contacts": len(contacts),
        "suppressed": sum(1 for e in log if e.code == "SUPPRESSED"),
        "already_introduced": len(already),
        "already_introduced_in_master": len(screen.introduced),
        "review": sum(1 for e in log if e.status == LogStatus.REVIEW),
        "excluded": sum(1 for e in log if e.status == LogStatus.EXCLUDED),
        "scored": len(scored), "ranked": len(ranked), "org_capped": len(capped),
        "intro_rows": len(intros), "intro_relations": screen.relation_counts,
    }
    files = []
    for role, group in (("TEN Capital Investor List", investor_tables), ("Investor Introductions", intro_tables)):
        for t in group:
            files.append({"Role": role, "File": t.table.filename, "Sheet": t.table.sheet or "",
                          "Rows": str(len(t.table.rows)), "SHA-256": t.table.sha256[:16],
                          "Company-specific": "Y" if t.company_specific else ""})
    LOGGER.info("Run: %d contacts, %d ranked, %d excluded", len(contacts), len(ranked), stats["excluded"])
    return RunResult(deal=profile, context=ctx, ranked=ranked, scored=scored, log=log, already_introduced=already,
                     limitations=limitations, input_files=files, config=cfg, report_date=report_date or date.today(),
                     stats=stats)


def output_names(company: str | None, report_date: date) -> tuple[str, str]:
    from app.utils.text import slugify

    stem = f"{slugify(company or 'company')}_investor_match_{report_date:%Y-%m-%d}"
    return f"{stem}.pdf", f"{stem}.xlsx"


def render_outputs(result: RunResult) -> dict[str, bytes]:
    """{filename: bytes} for the one-page PDF and the Excel workbook."""
    from app.reports.excel_report import render_xlsx
    from app.reports.pdf_report import render_pdf

    pdf_name, xlsx_name = output_names(result.context.company_name, result.report_date)
    return {pdf_name: render_pdf(result, xlsx_name), xlsx_name: render_xlsx(result)}


def deliver_results(result: RunResult, files: dict[str, bytes], settings=None):
    """Email the results for this generation (once per generated state). Never raises."""
    from app.config import get_settings
    from app.services.notifications import generation_key, send_results_email

    key = generation_key(result)
    previous = next((n for n in result.notifications if n.sent and n.generation == key), None)
    return previous or send_results_email(result, files, settings=settings or get_settings())


def _limitations(profile, ctx, intro_tables, screen, ranked, contacts, log) -> list[str]:
    out: list[str] = []
    for f in profile.conflicts:
        out.append(f"Conflicting {f.label.lower()} in deck ({' vs '.join(dict.fromkeys(c.display for c in f.candidates))}); "
                   "not used until resolved.")
    missing = [profile.facts[n].label.lower() for n in ("sector", "stage", "raise_amount", "company_geography")
               if profile.effective(n) is None]
    if missing:
        out.append("Not established from the deck: " + ", ".join(missing) + " — related score components earn 0.")
    if ctx.remaining is None:
        out.append(ctx.notes[0] if ctx.notes else "Remaining allocation not established.")
    elif profile.facts["amount_remaining"].status == FactStatus.CALCULATED and "amount_remaining" not in profile.overrides:
        out.append(f"Remaining allocation {ctx.remaining.display()} is calculated (raise − committed), not stated.")
    if profile.facts["sector"].status == FactStatus.CLASSIFIED and "sector" not in profile.overrides:
        out.append("Sector/subsector classified from deck language; confirm before sending.")
    if not intro_tables:
        out.append("No Investor Introductions lists supplied — prior-introduction screening is incomplete.")
    unstated = screen.relation_counts.get(intro_mod.UNSTATED, 0)
    if unstated:
        out.append(f"{unstated} introduction row(s) name no company; matches were held for review.")
    review = sum(1 for e in log if e.status == LogStatus.REVIEW)
    if review:
        out.append(f"{review} contact(s) held for review (ambiguous type or possible prior intro).")
    low = sum(1 for s in ranked if s.evidence_completeness < 0.6)
    if low:
        out.append(f"{low} ranked contact(s) have evidence completeness below 60%.")
    out.append("Email syntax was checked; deliverability was not verified.")
    for w in profile.warnings:
        if "OCR" in w:
            out.append(w)
    return out
