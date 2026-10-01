"""Streamlit UI: Inputs → Column mapping → Deal profile → Results & review → Export.

Run:  streamlit run app/app.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Streamlit puts this file's folder first on sys.path, which would shadow the `app` package.
_ROOT = Path(__file__).resolve().parent.parent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _ROOT / "app"]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import ui_theme as ui  # noqa: E402
from app.config import FAVICON_PATH, get_settings, load_config  # noqa: E402
from app.errors import ExportUnavailableError, InvestorMatchError  # noqa: E402
from app.extraction import taxonomy as tx  # noqa: E402
from app.extraction.deal_profile import build_context, make_override, profile_bullets  # noqa: E402
from app.ingestion.mapping import (  # noqa: E402
    INTRO_FIELDS,
    INVESTOR_FIELDS,
    ROLE_CONTACTS,
    ROLE_LABELS,
    ROLE_SKIP,
    ROLE_SUPPRESSION,
    INTRO_ROLE_LABELS,
    email_column_by_content,
    validate_mapping,
)
from app.screening.contacts import suppression_emails  # noqa: E402
from app.services import claude_review  # noqa: E402
from app.services.files_api import connected_investor_lists  # noqa: E402
from app.models import DEAL_FIELDS, FactStatus, LogStatus, refs_label  # noqa: E402
from app.pipeline import (  # noqa: E402
    DECISION_INTRODUCED,
    DECISION_NEW,
    DECISION_REVIEW,
    deliver_results,
    extract,
    builtin_suppression_tables,
    load_builtin_tables,
    load_deck,
    load_tables,
    output_names,
    render_outputs,
    run_matching,
)
from app.reports.frames import RANKED_COLUMNS, exclusion_rows, EXCLUSION_COLUMNS, ranked_rows, summary_counts  # noqa: E402
from app.screening.introductions import file_mentions_alias  # noqa: E402

st.set_page_config(page_title="TEN Capital Network — Investor Match",
                   page_icon=str(FAVICON_PATH) if FAVICON_PATH.is_file() else "📇", layout="wide",
                   initial_sidebar_state="collapsed")
ui.apply_theme()

STEPS = ["Inputs", "Column mapping", "Deal profile", "Results & review", "Export"]
UNMAPPED = "(unmapped)"
settings = get_settings()
cfg = load_config(settings.im_config_path)
state = st.session_state
for key, default in (("step", 0), ("deck", None), ("profile", None), ("investors", []), ("intros", []),
                     ("aliases", []), ("decisions", {}), ("result", None), ("outputs", None),
                     ("category_overrides", {})):
    state.setdefault(key, default)


if "_goto" in state:  # programmatic navigation, applied before the step widget is created
    state.step = state.pop("_goto")


def go(step: int) -> None:
    state.step = step


def navigate(step: int) -> None:
    state._goto = step
    st.rerun()


RUBRIC_MD = f"""
**Fit Score (1–10)** = Σ component rating (0–10) × weight, rounded half-up to one decimal (floor 1.0).

| Component | Weight | Ratings |
|---|---|---|
| Sector / subsector | {cfg['weights']['sector']:.0%} | explicit niche (deal subsector named) 10 · broad sector 7 · adjacent niche 5 · generalist 3 · outside 0 |
| Stage | {cfg['weights']['stage']:.0%} | deal stage named 10 · "early stage" 7 · stage-agnostic 5 |
| Check size | {cfg['weights']['check_size']:.0%} | min ≤ remaining and max ≥ {cfg['check_ratings']['participation_floor_pct']}% of remaining 10 · smaller checks 6 · min > remaining 0 · does not co-invest ≤ 4 |
| Geography | {cfg['weights']['geography']:.0%} | local focus 10 · country 8 · region 6 · global 5 · *inferred* same state 4 / country 2 (no stated focus) |
| TEN relationship | {cfg['weights']['ten_relationship']:.0%} | core list 5 + intros to similar clients 3 + event participation 2 |

Unknown attributes earn 0 and are flagged — never treated as incompatibility. Explicit stage or geographic
incompatibility excludes the contact. **Evidence completeness** (share of the five investor attributes that are
documented) is reported separately and breaks ties. Contacts scoring ≥ {cfg['thresholds']['min_fit_score']} are
kept; each organization is capped at {cfg['thresholds']['org_cap']} contacts.
"""


def _list_label(path: Path) -> str:
    from datetime import date

    return f"{path.name}  ·  updated {date.fromtimestamp(path.stat().st_mtime):%b %d, %Y}"


def _tmp_path(name: str, data: bytes) -> Path:
    folder = Path(tempfile.mkdtemp(prefix="im-"))
    path = folder / Path(name).name
    path.write_bytes(data)
    return path


# ------------------------------------------------------------------------------ header

def password_gate() -> bool:
    """Ask for TEN_APP_PASSWORD (when configured) before showing anything else."""
    import hmac

    expected = settings.ten_app_password.get_secret_value() if settings.ten_app_password else ""
    if not expected or state.get("authenticated"):
        return True
    ui.brand()
    with ui.hero("Restricted access", "TEN Capital", "Investor Match",
                 "Enter the access password provided by TEN Capital.", narrow=True):
        entered = st.text_input("Access password", type="password", key="access_password")
        with st.container(key="tc-cta"):
            submitted = st.button("Enter", type="primary", width="stretch")
        if submitted:
            if hmac.compare_digest(entered.encode(), expected.encode()):
                state.authenticated = True
                state.pop("access_password", None)
                st.rerun()
            st.error("Incorrect password.")
    ui.footer()
    return False


if not password_gate():
    st.stop()

ui.brand()
_enabled = {0} | ({1, 2} if state.profile is not None else set()) | ({3, 4} if state.result is not None else set())
_clicked = ui.step_nav(STEPS, state.step, {i for i in _enabled if i < state.step}, _enabled)
if _clicked is not None and _clicked != state.step:
    navigate(_clicked)
with st.sidebar:
    ui.brand(None)
    with st.expander("Fit Score rubric", expanded=True):
        st.markdown(RUBRIC_MD)


def disclosure_html() -> str:
    """What happens to uploads and results — shown under the input card, as in the design."""
    parts = ["Uploaded files are processed on the server in a private temporary folder and are not stored."]
    if settings.llm_available:
        parts.append(f"The deck text is analyzed by Claude ({ui.code(settings.im_llm_model)}); every fact must "
                     "quote its slide.")
    if settings.notify_available:
        parts.append("A copy of every generated shortlist (PDF + workbook) is emailed to "
                     + ", ".join(ui.code(r) for r in settings.notify_recipients()) + ".")
    parts.append("Nothing is ever sent to investors or founders.")
    return " ".join(parts)


# ------------------------------------------------------------------------------ 1. inputs

def step_inputs() -> None:
    hero = ui.hero("Investor Match", "Pitch Deck", "Investor Shortlist",
                   "Upload a pitch deck, choose TEN Capital's connected investor lists, and get a ranked investor shortlist, a "
                   "one-page PDF and a full workbook — analyzed by Claude and scored with TEN Capital's rubric.",
                   narrow=True)
    with hero:
        deck_file = st.file_uploader("Pitch deck", type=["pdf", "pptx", "ppt"], key="deck_upload",
                                     help="PDF, PPTX or legacy PPT. Image-only slides are read with OCR.")
        connected = connected_investor_lists(settings)
        chosen: list = []
        if connected:
            chosen = st.multiselect(
                "TEN Capital investor lists (connected through the Files API)", connected,
                default=connected[:1], format_func=_list_label,
                help="Only lists registered with the Anthropic Files API are used, newest first. Pick one or "
                     "more; duplicates are merged by email. Unsubscribe sheets from every connected list always "
                     "apply. Investor-list spreadsheets cannot be uploaded here.")
        else:
            st.error("No investor list is connected through the Files API. Put the list in data/investor_lists/, "
                     "run `python -m app.services.files_api`, and redeploy.")
        intro_files = st.file_uploader("Investor Introductions lists (optional)", type=["xlsx", "xls", "csv"],
                                       accept_multiple_files=True,
                                       help="One or more trackers of introductions already made; used to exclude "
                                            "investors already introduced. Not investor lists.")
        aliases = st.text_input("Company name / aliases (optional)",
                                placeholder="Other names the company has used, comma-separated",
                                help="Used to recognize prior introductions recorded under another name.")
        use_llm = False
        if settings.llm_available:
            use_llm = st.toggle(f"Analyze the deck with Claude ({settings.im_llm_model})", value=True,
                                help="Sends the deck text to the Anthropic API. Claude's reading is cross-checked "
                                     "against the rule-based extraction; every fact must quote its slide.")
        else:
            st.caption("Claude analysis is off (no ANTHROPIC_API_KEY); rule-based extraction is used.")
        if claude_review.is_available(settings):
            state.use_claude_review = st.toggle(
                "Let Claude suggest categories for held contacts (Files API)", value=state.get("use_claude_review", True),
                help="Claude opens the built-in list via its Files API copy and suggests a category, with a verified "
                     "quote, for held contacts that could reach the shortlist. You accept suggestions before they "
                     "are ranked.")
        ready = deck_file is not None and bool(chosen)
        with st.container(key="tc-cta"):
            clicked = st.button("Analyze deck and investor lists →", type="primary", disabled=not ready,
                                width="stretch")
        ui.disclosure(disclosure_html(), hero)
        if clicked:
            try:
                with st.spinner("Reading the deck (OCR on image-only slides can take a minute)…"):
                    deck = load_deck(_tmp_path(deck_file.name, deck_file.getvalue()), cfg, deck_file.name)
                    client = None
                    if use_llm:
                        from app.extraction.llm import ClaudeClient

                        client = ClaudeClient(settings)
                    state.profile = extract(deck, llm_client=client)
                    state.deck = deck
                with st.spinner("Loading investor lists…"):
                    investors = []
                    for path in chosen:
                        investors += load_builtin_tables(path)
                    investors += builtin_suppression_tables(exclude=set(chosen), settings=settings)
                state.investors = investors
                state.aliases = [a.strip() for a in aliases.split(",") if a.strip()]
                deck_names = [n for n in (state.profile.effective("company_name"),
                                          state.profile.effective("legal_name")) if n]
                state.intros = []
                for f in intro_files or []:
                    for t in load_tables(data=f.getvalue(), filename=f.name, kind="intro"):
                        t.company_specific = not t.mapping.get("company") and file_mentions_alias(
                            f.name, state.aliases + deck_names)
                        state.intros.append(t)
                state.result, state.outputs, state.decisions = None, None, {}
                navigate(1)
            except InvestorMatchError as exc:
                st.error(str(exc))


# ------------------------------------------------------------------------------ 2. mapping

def _widget_key(t, kind: str, index: int, name: str) -> str:
    """Widget keys tied to the sheet's identity (file fingerprint + sheet), never just its position, so a
    choice made for one sheet can never be applied to a different sheet that later takes that position."""
    table = t.table
    return f"{kind}-{name}-{table.sha256[:12]}-{table.filename}-{table.sheet or ''}-{index}"


def _mapping_editor(t, specs, kind: str, index: int) -> None:
    table = t.table
    role_note = f" · {(ROLE_LABELS if kind == 'investor' else INTRO_ROLE_LABELS)[t.role]}"
    with st.expander(f"{table.label} — {len(table.rows)} rows{role_note}",
                     expanded=index == 0 or (kind == "investor" and t.role == ROLE_SUPPRESSION
                                             and len(table.rows) < 2000)):
        for warning in table.warnings:
            st.caption(f"ℹ {warning}")
        options = [UNMAPPED] + table.columns
        if kind == "intro":
            roles = list(INTRO_ROLE_LABELS)
            t.role = st.selectbox("Use this sheet as", roles, index=roles.index(t.role),
                                  format_func=INTRO_ROLE_LABELS.get, key=_widget_key(t, kind, index, "role"),
                                  help="Skipped sheets (dashboards, FAQs, empty tabs) are not used.")
            if t.role == ROLE_SKIP:
                if t.role_reason:
                    st.caption(f"Detected automatically: {t.role_reason}.")
                return
        if kind == "investor":
            roles = list(ROLE_LABELS)
            t.role = st.selectbox("Use this sheet as", roles, index=roles.index(t.role),
                                  format_func=ROLE_LABELS.get, key=_widget_key(t, kind, index, "role"),
                                  help="Unsubscribe lists remove every listed email from the results. "
                                       "Skipped sheets are not used.")
            if t.role_reason and t.role != ROLE_CONTACTS:
                st.caption(f"Detected automatically: {t.role_reason}.")
            if t.role == ROLE_SKIP:
                return
            if t.role == ROLE_SUPPRESSION:
                current = t.mapping.get("email") or email_column_by_content(table) or UNMAPPED
                choice = st.selectbox("Email column", options, index=options.index(current),
                                      key=_widget_key(t, kind, index, "suppression-email"))
                t.mapping["email"] = None if choice == UNMAPPED else choice
                count = len(suppression_emails(table, t.mapping))
                (st.caption if count else st.warning)(
                    f"{count} valid email address(es) on this list will be excluded from the results."
                    if count else "No valid email addresses found in that column.")
                return
        cols = st.columns(3)
        for i, spec in enumerate(specs):
            current = t.mapping.get(spec.key) or UNMAPPED
            choice = cols[i % 3].selectbox(spec.label, options, index=options.index(current),
                                           key=_widget_key(t, kind, index, f"map-{spec.key}"),
                                           help=("e.g. " + " · ".join(table.sample(current)))
                                           if current != UNMAPPED else None)
            t.mapping[spec.key] = None if choice == UNMAPPED else choice
        if kind == "intro" and not t.mapping.get("company"):
            t.company_specific = st.checkbox(
                "This file lists introductions for this company only (no company column)",
                value=t.company_specific, key=_widget_key(t, kind, index, "specific"),
                help="If unticked, matches from this file are held for review instead of excluded.")
        for problem in validate_mapping(t.mapping, kind, table):
            st.warning(problem)


def step_mapping() -> None:
    if state.profile is None:
        st.info("Start with step 1.")
        return
    ui.hero("Step 2 of 5", "Source columns", "verified fields",
            "Headers were mapped automatically. Correct anything that is wrong; unmapped optional fields are "
            "treated as unknown, never as incompatible.", key="mapping")
    st.markdown("**TEN Capital Investor List**")
    for i, t in enumerate(state.investors):
        _mapping_editor(t, INVESTOR_FIELDS, "investor", i)
    st.markdown("**Investor Introductions lists**")
    if not state.intros:
        st.warning("No introduction lists uploaded — prior-introduction screening will be incomplete.")
    for i, t in enumerate(state.intros):
        _mapping_editor(t, INTRO_FIELDS, "intro", i)
    st.button("Review deal profile →", type="primary", on_click=go, args=(2,))


# ------------------------------------------------------------------------------ 3. deal profile

def step_profile() -> None:
    profile = state.profile
    if profile is None:
        st.info("Start with step 1.")
        return
    deck = state.deck
    ui.hero("Step 3 of 5", "Deal profile", "review & correct",
            f"Every fact extracted from {deck.filename}, with its slide reference. Corrections are recorded as "
            "overrides beside the deck facts, never over them.", key="profile")
    for w in profile.warnings:
        st.warning(w)
    rows = []
    for name, label in DEAL_FIELDS.items():
        f = profile.facts[name]
        o = profile.overrides.get(name)
        rows.append({"Field": label, "Deck value": f.display, "Status": f.status.value,
                     "Source": refs_label(f.sources, 3), "Override": o.display if o else "",
                     "Notes": " ".join(f.notes)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if profile.conflicts:
        st.error("Conflicting figures: " + "; ".join(f.label for f in profile.conflicts)
                 + ". Resolve with an override below, or leave unresolved (the field is then not used).")

    st.markdown("**Correct a field** — overrides are recorded separately from the deck facts.")
    labels = {label: name for name, label in DEAL_FIELDS.items()}
    c1, c2, c3 = st.columns([2, 3, 3])
    field = labels[c1.selectbox("Field", list(labels))]
    fact = profile.facts[field]
    if field == "sector":
        value = c2.selectbox("Value", tx.SECTOR_NAMES)
    elif field == "subsector":
        sector = profile.effective("sector")
        options = tx.SUBSECTORS_BY_SECTOR.get(sector, list(tx.SECTOR_OF_SUBSECTOR))
        value = " / ".join(c2.multiselect("Value", options))
    elif field == "stage":
        value = c2.selectbox("Value", tx.STAGES)
    elif fact.candidates and fact.status == FactStatus.CONFLICT:
        value = c2.selectbox("Value (deck candidates)", list(dict.fromkeys(c.display for c in fact.candidates)))
    else:
        value = c2.text_input("Value", placeholder="e.g. $2.5M · Austin, TX · December 15, 2026")
    reason = c3.text_input("Reason", placeholder="e.g. confirmed with founder on 9/30")
    b1, b2 = st.columns([1, 5])
    if b1.button("Apply override"):
        try:
            profile.overrides[field] = make_override(profile, field, value, reason)
            state.result = None
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if profile.overrides:
        remove = b2.selectbox("Remove override", ["—"] + [DEAL_FIELDS[n] for n in profile.overrides])
        if remove != "—" and b2.button("Remove"):
            profile.overrides.pop(labels[remove])
            state.result = None
            st.rerun()

    ctx = build_context(profile, state.aliases)
    st.markdown("**Summary used in the PDF**")
    st.markdown("\n".join(f"- {b}" for b in profile_bullets(profile, ctx)))
    st.caption(f"Remaining allocation for check-size fit: "
               f"{ctx.remaining.display() + ' (' + ctx.remaining_basis + ')' if ctx.remaining else 'not established'}"
               f" · Aliases for intro matching: {', '.join(ctx.aliases) or 'none'}")
    if st.button("Run matching →", type="primary"):
        _run()


def _run() -> None:
    # Sheets that cannot be used (investor lists or introductions) are skipped by the pipeline and noted in
    # the screening limitations; they never block a run.
    try:
        with st.spinner("Screening and scoring…"):
            state.result = run_matching(state.profile, state.investors, state.intros, cfg,
                                        user_aliases=state.aliases, intro_decisions=state.decisions,
                                        category_overrides=state.category_overrides)
        if claude_review.is_available(settings) and state.get("use_claude_review", True):
            with st.spinner("Claude is reviewing held contacts in the investor list (Files API)…"):
                claude_review.review_held_contacts(state.result, state.investors, settings)
        with st.spinner("Generating the PDF and workbook…"):
            state.outputs = render_outputs(state.result)
        if settings.notify_available:
            with st.spinner(f"Emailing results to {', '.join(settings.notify_recipients())}…"):
                deliver_results(state.result, state.outputs, settings)
        navigate(3)
    except InvestorMatchError as exc:
        st.error(str(exc))


# ------------------------------------------------------------------------------ 4. results

def _email_status(result) -> None:
    if not result.notifications:
        return
    last = result.notifications[-1]
    (st.success if last.sent else st.warning)("✉ " + last.status_text + ".")


def step_results() -> None:
    result = state.result
    if result is None:
        st.info("Run matching from the Deal profile step.")
        return
    counts = summary_counts(result)
    ui.hero("Step 4 of 5", result.context.company_name or "Results", "ranked investors",
            f"{counts['qualified_total']} qualified contacts across four categories; "
            f"{counts['already_introduced']} already introduced and {counts['review']} held for review.",
            key="results")
    _email_status(result)
    short = {"Angels": "Angels", "Angel Groups & Syndicates": "Angel groups", "HNI & Family Offices": "HNI & FOs",
             "VCs (Seed & Early-Stage)": "Seed / early VCs"}
    tiles = [(short.get(k, k), n, k) for k, n in counts["qualified"].items()]
    tiles += [("Already introduced", counts["already_introduced"], "Excluded — do not re-intro"),
              ("Held for review", counts["review"], "Ambiguous type or possible prior introduction")]
    for col, (label, n, full) in zip(st.columns(6), tiles, strict=True):
        col.metric(label, n, help=full)
    st.subheader("Ranked investors")
    df = pd.DataFrame(ranked_rows(result), columns=RANKED_COLUMNS)
    category = st.multiselect("Category", list(counts["qualified"]), default=list(counts["qualified"]))
    st.dataframe(df[df["Category"].isin(category)], hide_index=True, width="stretch",
                 column_config={"Fit Score": st.column_config.NumberColumn(format="%.1f")})

    if result.category_suggestions:
        st.subheader("Claude category suggestions — accept to rank")
        st.caption("Claude read these contacts' rows in the investor list (Files API) and quoted the evidence; each "
                   "quote was verified against the list. Held contacts are only ranked after you accept.")
        table = pd.DataFrame([{"Accept": False, "Email": s.email, "Name": s.name, "Organization": s.organization,
                               "Suggested category": s.category.value, "Evidence": f"{s.column}: “{s.evidence}”",
                               "Rule check": s.rule_check, "Fit if categorized": s.fit_if_categorized}
                              for s in result.category_suggestions])
        edited = st.data_editor(table, hide_index=True, width="stretch",
                                disabled=[c for c in table.columns if c != "Accept"],
                                column_config={"Fit if categorized": st.column_config.NumberColumn(format="%.1f")})
        chosen = edited[edited["Accept"]]
        if st.button(f"Accept {len(chosen)} suggestion(s) and re-run", disabled=chosen.empty):
            state.category_overrides.update(dict(zip(chosen["Email"], chosen["Suggested category"], strict=True)))
            _run()
    review = [e for e in result.log if e.code == "POSSIBLE_PRIOR_INTRO"]
    if review or state.decisions:
        st.subheader("Possible prior introductions — decide before outreach")
        editor = pd.DataFrame([{"Email": e.email, "Name": f"{e.first_name} {e.last_name}".strip(),
                                "Organization": e.organization, "Evidence": e.detail,
                                "Decision": state.decisions.get(e.email, DECISION_REVIEW)} for e in review])
        if not editor.empty:
            edited = st.data_editor(editor, hide_index=True, width="stretch", disabled=[
                "Email", "Name", "Organization", "Evidence"], column_config={"Decision": st.column_config.SelectboxColumn(
                    options=[DECISION_REVIEW, DECISION_NEW, DECISION_INTRODUCED])})
            if st.button("Apply decisions and re-run"):
                state.decisions.update({r.Email: r.Decision for r in edited.itertuples() if r.Decision != DECISION_REVIEW})
                _run()
    st.subheader("Exclusions, review items and flags")
    log = pd.DataFrame(exclusion_rows(result), columns=EXCLUSION_COLUMNS)
    status = st.multiselect("Status", [s.value for s in LogStatus], default=[LogStatus.REVIEW.value, LogStatus.EXCLUDED.value])
    st.dataframe(log[log["Status"].isin(status)], hide_index=True, width="stretch")
    st.subheader("Screening limitations")
    st.markdown("\n".join(f"- {x}" for x in result.limitations))
    st.button("Export →", type="primary", on_click=go, args=(4,))


# ------------------------------------------------------------------------------ 5. export

def step_export() -> None:
    result = state.result
    if result is None:
        st.info("Run matching first.")
        return
    pdf_name, xlsx_name = output_names(result.context.company_name, result.report_date)
    if state.outputs is None:
        with st.spinner("Rendering PDF and workbook…"):
            state.outputs = render_outputs(result)
    pdf, xlsx = state.outputs[pdf_name], state.outputs[xlsx_name]
    ui.hero("Step 5 of 5", "Results", "PDF · Excel · Email",
            "Download the one-page summary and the full workbook. Contact details are kept in the workbook only.",
            key="export")
    _email_status(result)
    if settings.notify_available and not any(n.sent for n in result.notifications):
        if st.button(f"Email results to {', '.join(settings.notify_recipients())}"):
            deliver_results(result, state.outputs, settings)
            st.rerun()
    c1, c2 = st.columns(2)
    c1.download_button("Download one-page PDF", pdf, pdf_name, "application/pdf", type="primary")
    c2.download_button("Download Excel workbook", xlsx, xlsx_name,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    st.subheader("Google Sheets")
    if settings.google_credentials_file is None:
        from app.reports.google_sheets import ENABLE_INSTRUCTIONS

        st.info(ENABLE_INSTRUCTIONS)
    elif st.button("Export to Google Sheets"):
        from app.reports.google_sheets import export_to_google_sheets

        try:
            url = export_to_google_sheets(result, settings, xlsx_name[:-5])
            st.success(f"Created: {url}")
        except ExportUnavailableError as exc:
            st.error(str(exc))
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        st.image(doc[0].get_pixmap(dpi=90).tobytes("png"), caption="PDF preview")


[step_inputs, step_mapping, step_profile, step_results, step_export][state.step]()
ui.footer()
