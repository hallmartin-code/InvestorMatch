"""Headless runner.

    python -m app.cli --deck sample_data/cardiolyte_health_deck.pptx \
        --investors sample_data/TEN_Capital_Investor_List_SAMPLE.xlsx \
        --intros sample_data/TEN_Intro_Tracker_2026.xlsx sample_data/cardiolyte_health_intros_Q3.csv \
        --out output

Optional: --alias NAME (repeatable), --company-specific FILE (intro lists without a company column),
--overrides overrides.json ({"field": {"value": "...", "reason": "..."}}), --decisions decisions.json
({"email": "Treat as introduced" | "Treat as not introduced"}), --google, --date YYYY-MM-DD,
--no-claude (skip Claude deck analysis when ANTHROPIC_API_KEY is set), --no-email (do not email results
when RESEND_API_KEY is set).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.config import get_settings, load_config
from app.errors import ExportUnavailableError, InvestorMatchError
from app.extraction.deal_profile import make_override
from app.pipeline import (
    builtin_suppression_tables,
    deliver_results,
    extract,
    load_builtin_tables,
    load_deck,
    load_tables,
    output_names,
    render_outputs,
    run_matching,
)
from app.reports.frames import summary_counts
from app.screening.introductions import file_mentions_alias

__all__ = ["main", "output_names"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TEN Capital Investor Match (headless)")
    parser.add_argument("--deck", required=True, type=Path)
    parser.add_argument("--investors", type=Path, help="TEN Capital Investor List (default: configured project file)")
    parser.add_argument("--intros", nargs="*", type=Path, default=[])
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--company-specific", nargs="*", type=Path, default=[])
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--google", action="store_true", help="also export to Google Sheets if configured")
    parser.add_argument("--no-claude", action="store_true", help="skip Claude deck analysis even if a key is set")
    parser.add_argument("--no-email", action="store_true", help="do not email the results even if Resend is configured")
    args = parser.parse_args(argv)

    settings = get_settings()
    cfg = load_config(settings.im_config_path)
    try:
        investors_path = args.investors or settings.default_investor_list()
        if investors_path is None:
            parser.error("No investor list: pass --investors or set IM_INVESTOR_LIST_PATH.")
        deck = load_deck(args.deck, cfg)
        client = None
        if settings.llm_available and not args.no_claude:
            from app.extraction.llm import ClaudeClient

            client = ClaudeClient(settings)
        profile = extract(deck, llm_client=client)
        if args.overrides:
            for name, spec in json.loads(args.overrides.read_text(encoding="utf-8")).items():
                profile.overrides[name] = make_override(profile, name, spec["value"], spec.get("reason", ""))
        aliases = args.alias + [a for a in (profile.effective("company_name"), profile.effective("legal_name")) if a]
        builtin = settings.builtin_investor_lists()
        if investors_path in builtin:
            investors = load_builtin_tables(investors_path)
        else:
            investors = load_tables(investors_path)
        # Unsubscribe sheets of every built-in list always apply.
        investors += builtin_suppression_tables(exclude={investors_path}, settings=settings)
        intros = []
        specific = {p.name for p in args.company_specific}
        for path in args.intros:
            for t in load_tables(path, kind="intro"):
                t.company_specific = not t.mapping.get("company") and (
                    path.name in specific or file_mentions_alias(path.name, aliases))
                intros.append(t)
        decisions = json.loads(args.decisions.read_text(encoding="utf-8")) if args.decisions else {}
        result = run_matching(profile, investors, intros, cfg, user_aliases=args.alias,
                              intro_decisions=decisions, report_date=args.date)
        if not args.no_claude:
            from app.services import claude_review

            if claude_review.is_available(settings):
                claude_review.review_held_contacts(result, investors, settings)
        pdf_name, xlsx_name = output_names(result.context.company_name, result.report_date)
        args.out.mkdir(parents=True, exist_ok=True)
        files = render_outputs(result)
        for name, data in files.items():
            (args.out / name).write_bytes(data)
        summary = {"company": result.context.company_name, "report_date": result.report_date.isoformat(),
                   "counts": summary_counts(result), "stats": result.stats, "limitations": result.limitations,
                   "outputs": [pdf_name, xlsx_name]}
        if args.google:
            from app.reports.google_sheets import export_to_google_sheets

            try:
                summary["google_sheet"] = export_to_google_sheets(result, settings, xlsx_name[:-5])
            except ExportUnavailableError as exc:
                summary["google_sheet"] = f"not exported: {exc}"
        if not args.no_email:
            summary["email"] = deliver_results(result, files, settings).status_text
        (args.out / f"{xlsx_name[:-5]}_summary.json").write_text(json.dumps(summary, indent=2, default=str),
                                                                  encoding="utf-8")
    except InvestorMatchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
