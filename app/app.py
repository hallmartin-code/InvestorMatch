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
from app.services.files_api import list_catalog  # noqa: E402
from app.models import DEAL_FIELDS, FactStatus, LogStatus  # noqa: E402
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
from app.reports.frames import (  # noqa: E402
    EXCLUSION_COLUMNS,
    NEEDS_RESEARCH,
    RANKED_COLUMNS,
    exclusion_rows,
    ranked_rows,
    summary_counts,
)
from app.screening.review import (  # noqa: E402
    action_warnings,
    contact_note,
    held_breakdown,
    held_contacts,
    held_rows,
    likely_candidate,
    projected_rank,
    unmapped_score_fields,
)
from app.screening.scoring import compact_why  # noqa: E402
from app.services.notifications import generation_key  # noqa: E402
from app.utils.text import truncate  # noqa: E402
from app.screening.introductions import file_mentions_alias  # noqa: E402

st.set_page_config(page_title="TEN Capital Network — Investor Match",
                   page_icon=str(FAVICON_PATH) if FAVICON_PATH.is_file() else "📇", layout="wide",
                   initial_sidebar_state="collapsed")
ui.apply_theme()

STEPS = ["Inputs", "Mapping", "Profile", "Review", "Export"]
UNMAPPED = "(unmapped)"
STALE_LIST_DAYS = 30
settings = get_settings()
cfg = load_config(settings.im_config_path)
state = st.session_state
for key, default in (("step", 0), ("deck", None), ("profile", None), ("investors", []), ("intros", []),
                     ("aliases", []), ("decisions", {}), ("result", None), ("outputs", None),
                     ("category_overrides", {})):
    state.setdefault(key, default)


if "_goto" in state:  # programmatic navigation, applied before the step widget is created
    state.step = state.pop("_goto")
if "_toast" in state:  # confirmations queued before a rerun (a toast shown right before st.rerun is lost)
    _msg, _icon = state.pop("_toast")
    st.toast(_msg, icon=_icon)


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


def _md(text: str) -> str:
    """Literal dollar signs in Markdown (otherwise "$2.5M … $1.1M" renders as a math formula)."""
    return text.replace("$", "\\$")


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

ui.brand(None)


def _locked_steps() -> dict[int, str]:
    """Steps that cannot be opened yet, with the reason shown as tooltip and toast."""
    if state.profile is None:
        reason = "Upload a pitch deck and click Analyze to unlock this step."
        return {1: reason, 2: reason, 3: reason, 4: reason}
    if state.result is None:
        reason = "Run matching on the Profile step to unlock this step."
        return {3: reason, 4: reason}
    return {}


_locked = _locked_steps()
_done = {i for i in range(len(STEPS)) if i < state.step and i not in _locked}
_clicked = ui.step_nav(STEPS, state.step, _done, _locked)
if _clicked is not None and _clicked != state.step:
    if _clicked in _locked:
        st.toast(_locked[_clicked], icon="🔒")
    else:
        navigate(_clicked)


@st.dialog("How scoring works", width="large")
def scoring_dialog() -> None:
    st.markdown(RUBRIC_MD)


def scoring_link(key: str) -> None:
    if st.button("ⓘ How scoring works", key=f"scoring-{key}", type="tertiary"):
        scoring_dialog()


def disclosure_html() -> str:
    """What happens to uploads and results — shown under the input card."""
    email = (f" Results are emailed to <b>{', '.join(settings.notify_recipients())}</b> only when you click "
             "<b>Finalize &amp; email</b> on the last step." if settings.notify_available else "")
    return ("🔒 <b>Private.</b> Uploaded files are processed in a temporary folder on the server and are not "
            "stored. Nothing is ever sent to investors or founders." + email)


# ------------------------------------------------------------------------------ 1. inputs

def _deck_summary(upload) -> str:
    """'name · 12 slides' for an uploaded deck (cheap: counts pages/slides only)."""
    import io

    name = upload.name
    try:
        if name.lower().endswith(".pdf"):
            import pymupdf

            with pymupdf.open(stream=upload.getvalue(), filetype="pdf") as doc:
                return f"<b>{name}</b> · {doc.page_count} pages"
        if name.lower().endswith(".pptx"):
            from pptx import Presentation

            return f"<b>{name}</b> · {len(Presentation(io.BytesIO(upload.getvalue())).slides)} slides"
    except Exception:  # noqa: BLE001 - a summary must never block the upload
        pass
    return f"<b>{name}</b> · legacy PowerPoint — converted when analyzed"


def _investor_list_picker() -> list:
    """Checkbox list: recommended/current lists first with investor counts, older versions under 'Archived'."""
    from html import escape

    catalog = list_catalog(settings)
    if not catalog:
        st.error("No TEN Capital investor list is available yet. An administrator needs to add one "
                 "(see DEPLOY.md → Investor lists).")
        return []
    has_recommended = any(x["status"] == "recommended" for x in catalog)
    chosen = []

    from datetime import datetime

    def row(item, default: bool) -> None:
        badge = "  :green-badge[Recommended]" if item["status"] == "recommended" else ""
        if st.checkbox(f"**{item['label']}**{badge}", value=default, key=f"list::{item['path'].name}"):
            chosen.append(item["path"])
        when = item["updated"]
        parts = [f"{when:%b} {when.day}, {when.year}"]
        if item.get("contacts") is not None:
            parts.append(f"{item['contacts']:,} contacts")
        age = (datetime.now() - when).days
        stale = (f' <span class="tc-stale">⚠ {age} days old — check for a newer version</span>'
                 if age > STALE_LIST_DAYS and item["status"] != "archived" else "")
        note = f"<br>{escape(item['note'])}" if item.get("note") else ""
        st.html(f'<div class="tc-list-meta">{" · ".join(parts)}{stale}{note}</div>')

    st.markdown("**Investor lists to search**")
    st.caption("Lists are maintained by TEN Capital and can't be uploaded here.")
    active = [x for x in catalog if x["status"] != "archived"]
    archived = [x for x in catalog if x["status"] == "archived"]
    for i, item in enumerate(active):
        row(item, item["status"] == "recommended" or (not has_recommended and i == 0))
    if archived:
        with st.expander(f"Archived versions ({len(archived)}) — older copies of the master list"):
            for item in archived:
                row(item, False)
    return chosen


def step_inputs() -> None:
    hero = ui.hero("Step 1 of 5", "Pitch Deck", "Investor Shortlist",
                   "Upload a pitch deck and choose a TEN Capital investor list to get a ranked investor shortlist, "
                   "a one-page PDF and a full workbook.", narrow=True)
    with hero:
        ui.install_drag_highlight()
        st.markdown("**Pitch deck** :orange-badge[Required]")
        deck_file = st.file_uploader("Pitch deck", type=["pdf", "pptx", "ppt"], key="deck_upload",
                                     label_visibility="collapsed")
        if deck_file is not None:
            st.html(f'<div class="tc-file-meta">✓ {_deck_summary(deck_file)}</div>')
        else:
            st.caption("Image-only slides are read too.")
        chosen = _investor_list_picker()

        with st.expander("Advanced options"):
            intro_files = st.file_uploader("Introduction trackers (optional)",
                                           type=["xlsx", "xls", "csv"], accept_multiple_files=True,
                                           key="intro_upload")
            st.caption("Spreadsheets of introductions already made for this company. Investors on them are "
                       "excluded so nobody is introduced twice.")
            aliases = st.text_input("Other company names (optional)",
                                    placeholder="Former or alternative names, comma-separated")
            st.caption("Helps recognize past introductions recorded under another name.")
            use_llm = False
            if settings.llm_available:
                use_llm = st.toggle("Use AI to analyze the deck", value=state.get("use_llm", True), key="use_llm")
                st.caption("On: AI reads every slide and double-checks each fact against the deck. "
                           "Off = keyword matching only — faster, but less accurate."
                           if use_llm else
                           "Off: keyword matching only — faster, but may miss or misread deck facts.")
            if claude_review.is_available(settings):
                state.use_claude_review = st.toggle("Suggest categories for unclassified contacts",
                                                    value=state.get("use_claude_review", True))
                st.caption("On: AI suggests a category (with evidence) for promising investors whose type is "
                           "missing; you approve each one. Adds about a minute. Off = they stay unranked."
                           if state.use_claude_review else
                           "Off: investors with a missing type stay in the review list without suggestions.")

        ready = deck_file is not None and bool(chosen)
        with st.container(key="tc-cta"):
            clicked = st.button("Analyze deck and investor lists →", type="primary", disabled=not ready,
                                width="stretch")
        if deck_file is None:
            ui.html_note('<div class="tc-cta-note todo">Upload a pitch deck to continue.</div>')
        elif not chosen:
            ui.html_note('<div class="tc-cta-note todo">Choose at least one investor list to continue.</div>')
        else:
            minutes = "about 1–2 minutes" if use_llm else "under a minute"
            ui.html_note(f'<div class="tc-cta-note">⏱ Analysis takes {minutes}. You review everything '
                         "before anything is emailed.</div>")
        ui.disclosure(disclosure_html(), hero)
        if clicked:
            try:
                progress = st.status("Analyzing — this takes " + ("about 1–2 minutes…" if use_llm else
                                                                 "under a minute…"), expanded=True)
                with progress:
                    st.write("Reading the deck (image-only slides are read with OCR)…")
                    deck = load_deck(_tmp_path(deck_file.name, deck_file.getvalue()), cfg, deck_file.name)
                    st.write(f"✓ Read {deck.page_count} {deck.unit}s.")
                    client = None
                    if use_llm:
                        from app.extraction.llm import ClaudeClient

                        client = ClaudeClient(settings)
                        st.write("AI is extracting and double-checking the deal facts…")
                    state.profile = extract(deck, llm_client=client)
                    state.deck = deck
                    st.write("✓ Deal profile extracted. Loading investor lists…")
                    investors = []
                    for path in chosen:
                        investors += load_builtin_tables(path)
                    investors += builtin_suppression_tables(exclude=set(chosen), settings=settings)
                    progress.update(label="Done — opening the column mapping", state="complete")
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


def _sample_text(table, column: str) -> str:
    values = [truncate(v, 28) for v in table.sample(column, 2)]
    return "e.g. " + " · ".join(values) if values else "column is empty"


def _score_field_warning(t) -> None:
    """Amber note listing scoring components this sheet cannot feed (they earn 0 for every contact)."""
    missing = unmapped_score_fields(t.mapping, cfg["weights"])
    if not missing:
        return
    lines = []
    for m in missing:
        line = f"**{m['label']}** — {m['weight']:.0%} of the Fit Score will be 0 for everyone"
        lines.append(line + (f" (except: {m['partial']})" if m["partial"] else ""))
    st.warning("**Unmapped scoring columns.** If the list has these, map them below:\n\n"
               + "\n".join(f"- {x}" for x in lines), icon="⚠️")


def _mapping_editor(t, specs, kind: str, index: int, expanded: bool = False) -> None:
    table = t.table
    role_note = f" · {(ROLE_LABELS if kind == 'investor' else INTRO_ROLE_LABELS)[t.role]}"
    with st.expander(f"{table.label} — {len(table.rows):,} rows{role_note}", expanded=expanded):
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
                    f"{count:,} valid email address(es) on this list will be excluded from the results."
                    if count else "No valid email addresses found in that column.")
                return
        cols = st.columns(3)
        for i, spec in enumerate(specs):
            current = t.mapping.get(spec.key) or UNMAPPED
            col = cols[i % 3]
            choice = col.selectbox(spec.label, options, index=options.index(current),
                                   key=_widget_key(t, kind, index, f"map-{spec.key}"))
            t.mapping[spec.key] = None if choice == UNMAPPED else choice
            col.caption(_sample_text(table, choice) if choice != UNMAPPED else "not used")
        if kind == "investor":
            _score_field_warning(t)
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
            "Headers were mapped automatically. Check the investor contacts sheet; unmapped optional fields are "
            "treated as unknown, never as incompatible.", key="mapping")
    indexed = list(enumerate(state.investors))
    contacts = sorted([(i, t) for i, t in indexed if t.role == ROLE_CONTACTS], key=lambda x: -len(x[1].table.rows))
    main = [contacts[0]] if contacts else []
    others = [(i, t) for i, t in indexed if not main or i != main[0][0]]
    st.markdown("**Investor contacts sheet**")
    for i, t in main:
        _mapping_editor(t, INVESTOR_FIELDS, "investor", i, expanded=True)
    suppression = [t for _, t in indexed if t.role == ROLE_SUPPRESSION]
    if suppression:
        names = ", ".join(sorted({f"{t.table.filename} › {t.table.sheet}" if t.table.sheet else t.table.filename
                                  for t in suppression}))
        st.info(f"Suppression lists are always applied from all connected files: {names}.", icon="🛡️")
    if others:
        skipped = sum(1 for _, t in others if t.role == ROLE_SKIP)
        parts = [f"{skipped} skipped"] if skipped else []
        parts += [f"{len(suppression)} unsubscribe"] if suppression else []
        extra = len(others) - skipped - len(suppression)
        parts += [f"{extra} more contact sheet(s)"] if extra else []
        if st.toggle(f"Other sheets ({len(others)}: {', '.join(parts)})", key="show_other_sheets"):
            for i, t in others:
                _mapping_editor(t, INVESTOR_FIELDS, "investor", i)
    st.markdown("**Investor introduction trackers**")
    if not state.intros:
        st.caption("None uploaded (Advanced options on step 1) — prior-introduction screening will be incomplete.")
    for i, t in enumerate(state.intros):
        _mapping_editor(t, INTRO_FIELDS, "intro", i, expanded=i == 0)
    st.button("Review deal profile →", type="primary", on_click=go, args=(2,))


# ------------------------------------------------------------------------------ 3. deal profile

STATUS_BADGE = {FactStatus.STATED: "🟢 Stated", FactStatus.CLASSIFIED: "🔵 Classified",
                FactStatus.CALCULATED: "🟣 Calculated", FactStatus.CONFLICT: "🟠 Conflicting",
                FactStatus.NOT_STATED: "⚪ Not stated"}


def _apply_override(profile, field: str, value: str, reason: str) -> bool:
    try:
        profile.overrides[field] = make_override(profile, field, value, reason)
    except ValueError as exc:
        st.error(f"{DEAL_FIELDS[field]}: {exc}")
        return False
    state.result, state.outputs = None, None
    state._toast = (f"Saved: {DEAL_FIELDS[field]} → {profile.overrides[field].display}", "✅")
    return True


def _resolve_conflicts(profile) -> None:
    deck = state.deck
    text = deck.full_text if deck is not None else ""
    for fact in profile.conflicts:
        options = list(dict.fromkeys(c.display for c in fact.candidates))
        cands = [next(c for c in fact.candidates if c.display == o) for o in options]
        best = likely_candidate(cands, text, deck.filename if deck is not None else "")
        with st.container(border=True):
            st.markdown(f"**{fact.label}** — the deck gives different values. Most likely is pre-selected.")
            labels = [f"{c.display}  ·  {c.source.locator}" for c in cands]
            pick = st.radio(fact.label, range(len(cands)), index=best, format_func=labels.__getitem__,
                            key=f"conflict-{fact.field}", label_visibility="collapsed")
            if st.button("Use this value", key=f"conflict-use-{fact.field}", type="primary"):
                if _apply_override(profile, fact.field, cands[pick].display,
                                   "Chosen from conflicting deck values"):
                    st.rerun()


def step_profile() -> None:
    profile = state.profile
    if profile is None:
        st.info("Start with step 1.")
        return
    deck = state.deck
    ui.hero("Step 3 of 5", "Deal profile", "review & correct",
            f"Every fact extracted from {deck.filename}, with its slide reference. Type a correction in the "
            "Correction column — corrections are kept beside the deck facts, never over them.", key="profile")
    for w in profile.warnings:
        st.warning(w)
    if profile.conflicts:
        st.markdown("**Resolve conflicting figures** — unresolved fields are not used for matching.")
        _resolve_conflicts(profile)

    names = list(DEAL_FIELDS)
    rows = []
    for name in names:
        f = profile.facts[name]
        o = profile.overrides.get(name)
        rows.append({"Field": DEAL_FIELDS[name], "Status": STATUS_BADGE.get(f.status, f.status.value),
                     "Deck value": f.display, "Correction": o.display if o else "",
                     "Source": ", ".join(dict.fromkeys(x.locator for x in f.sources)) or "—",
                     "Notes": " ".join(f.notes)})
    version = state.get("profile_editor_version", 0)
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", height=35 * (len(rows) + 1) + 3,
        disabled=["Field", "Status", "Deck value", "Source", "Notes"], key=f"profile-editor-{version}",
        column_config={
            "Field": st.column_config.TextColumn(width="medium", pinned=True),
            "Status": st.column_config.TextColumn(width="medium"),
            "Deck value": st.column_config.TextColumn(width="medium"),
            "Correction": st.column_config.TextColumn(
                width="medium", help="Type a value and press Enter. Clear it to remove the correction. "
                                     "Sector/stage must match the taxonomy (or use the picker below)."),
            "Source": st.column_config.TextColumn(width="medium"),
            "Notes": st.column_config.TextColumn(width="large"),
        })
    changed = False
    for name, new in zip(names, edited["Correction"].fillna(""), strict=True):
        old = profile.overrides[name].display if name in profile.overrides else ""
        new = str(new).strip()
        if new == old:
            continue
        if not new:
            profile.overrides.pop(name, None)
            state.result, state.outputs = None, None
            state._toast = (f"Removed correction for {DEAL_FIELDS[name]}", "↩️")
            changed = True
        elif _apply_override(profile, name, new, "Edited in the profile table"):
            changed = True
    if changed:
        state.profile_editor_version = version + 1
        st.rerun()

    with st.expander("Pick sector, subsector or stage from the list"):
        c1, c2, c3 = st.columns([2, 3, 1], vertical_alignment="bottom")
        field = {"Sector": "sector", "Subsector": "subsector", "Stage": "stage"}[
            c1.selectbox("Field", ["Sector", "Subsector", "Stage"])]
        if field == "sector":
            value = c2.selectbox("Value", tx.SECTOR_NAMES)
        elif field == "subsector":
            sector = profile.effective("sector")
            value = " / ".join(c2.multiselect("Value", tx.SUBSECTORS_BY_SECTOR.get(sector, list(tx.SECTOR_OF_SUBSECTOR))))
        else:
            value = c2.selectbox("Value", tx.STAGES)
        if c3.button("Save", width="stretch") and _apply_override(profile, field, value, "Picked from taxonomy"):
            state.profile_editor_version = version + 1
            st.rerun()

    ctx = build_context(profile, state.aliases)
    st.markdown("**Summary used in the PDF**")
    st.markdown(_md("\n".join(f"- {b}" for b in profile_bullets(profile, ctx, with_refs=False))))
    st.caption(_md(f"Remaining allocation for check-size fit: "
               f"{ctx.remaining.display() + ' (' + ctx.remaining_basis + ')' if ctx.remaining else 'not established'}"
               f" · Aliases for intro matching: {', '.join(ctx.aliases) or 'none'}"))
    if st.button("Run matching →", type="primary"):
        _run()


def _run(goto: int | None = 3) -> None:
    """Screen, score, let Claude review held contacts and render the files. Never emails: results are only
    emailed from the Export step ("Finalize & email"), once per generated state."""
    try:
        with st.spinner("Screening and scoring…"):
            state.result = run_matching(state.profile, state.investors, state.intros, cfg,
                                        user_aliases=state.aliases, intro_decisions=state.decisions,
                                        category_overrides=state.category_overrides)
        if claude_review.is_available(settings) and state.get("use_claude_review", True):
            with st.spinner("Claude is reviewing held contacts in the investor list…"):
                claude_review.review_held_contacts(state.result, state.investors, settings)
        with st.spinner("Generating the PDF and workbook…"):
            state.outputs = render_outputs(state.result)
        if goto is not None:
            navigate(goto)
        st.rerun()
    except InvestorMatchError as exc:
        st.error(str(exc))


# ------------------------------------------------------------------------------ 4. results

SHORT_CATEGORY = {"Angels": "Angels", "Angel Groups & Syndicates": "Groups",
                  "HNI & Family Offices": "Family offices", "VCs (Seed & Early-Stage)": "VCs"}


def _suggestions(result) -> None:
    sugs = result.category_suggestions
    if not sugs:
        return
    verified = [s for s in sugs if s.rule_check != "differs"]
    st.subheader(f"Claude found {len(sugs)} likely match{'es' if len(sugs) != 1 else ''} held for review")
    st.caption("These contacts were held only because their investor type was missing or unclear. Claude read each "
               "row in the investor list and quoted the evidence; every quote was checked against the list. "
               "“Verified” = the quote agrees with (or is not contradicted by) the app's own type rules.")
    table = pd.DataFrame([{
        "Accept": s.rule_check != "differs",
        "Projected fit": s.fit_if_categorized,
        "Would rank": f"#{projected_rank(s.fit_if_categorized, result.ranked, s.category)} in "
                      f"{SHORT_CATEGORY.get(s.category.value, s.category.value)}",
        "Name": s.name, "Organization": s.organization, "Suggested category": s.category.value,
        "Evidence": f"{s.column}: “{s.evidence}”",
        "Check": "✓ verified" if s.rule_check != "differs" else "⚠ differs from type rules",
        "Email": s.email,
    } for s in sorted(sugs, key=lambda s: -s.fit_if_categorized)])
    edited = st.data_editor(table, hide_index=True, width="stretch", key="suggestions-editor",
                            disabled=[c for c in table.columns if c != "Accept"],
                            column_config={"Projected fit": st.column_config.NumberColumn(format="%.1f"),
                                           "Accept": st.column_config.CheckboxColumn(width="small")})
    chosen = edited[edited["Accept"]]
    c1, c2, _ = st.columns([2, 2, 3])
    if c1.button(f"Accept all {len(verified)} verified and re-run", type="primary", disabled=not verified):
        state.category_overrides.update({s.email: s.category.value for s in verified})
        _run(goto=None)
    if c2.button(f"Accept selected ({len(chosen)}) and re-run", disabled=chosen.empty):
        state.category_overrides.update(dict(zip(chosen["Email"], chosen["Suggested category"], strict=True)))
        _run(goto=None)


def _grey_research(value):
    return "color: #7d8796; font-style: italic;" if value == NEEDS_RESEARCH else ""


def _ranked_table(result, rows: list, key: str):
    columns = ["Category", "Fit Score", "Why a fit", "Name", "Note", "Organization", "Email", "Phone",
               "Investor Type", "Location"]
    df = pd.DataFrame(rows)[columns] if rows else pd.DataFrame(columns=columns)
    if key != "all":
        df = df.drop(columns=["Category"])
    styled = df.style.map(_grey_research).format({"Fit Score": "{:.1f}"})
    event = st.dataframe(styled, hide_index=True, width="stretch", key=f"ranked-{key}", on_select="rerun",
                         selection_mode="single-row", height=min(38 * (len(df) + 1) + 4, 560),
                         column_config={"Why a fit": st.column_config.TextColumn(width="large"),
                                        "Note": st.column_config.TextColumn(width="small")})
    picked = event.selection.rows if event and event.selection else []
    return rows[picked[0]] if picked else None


def _contact_detail(row) -> None:
    s = row["_scored"]
    c = s.contact
    with st.container(border=True):
        st.markdown(f"**{c.full_name or c.organization or c.email_display}** · {c.organization or '—'} · "
                    f"Fit {s.fit_score:.1f} · {s.category.value}")
        st.caption(s.why)
        linkedin = c.get("linkedin")
        a, b = st.columns(2)
        a.markdown(f"**LinkedIn:** [{truncate(linkedin, 60)}]({linkedin if linkedin.startswith('http') else 'https://' + linkedin})"
                   if linkedin else "**LinkedIn:** :gray[needs research]")
        b.markdown(f"**TEN relationship:** {s.ten_relationship}")
        st.dataframe(pd.DataFrame([{"Component": x.label, "Weight": f"{x.weight:.0%}", "Rating": x.rating,
                                    "Evidence": x.evidence} for x in s.components]),
                     hide_index=True, width="stretch")


def _held_section(result, counts) -> None:
    held = counts["review"]
    total = result.stats.get("unique_contacts") or 0
    share = f" ({held / total:.0%} of {total:,} contacts)" if total else ""
    st.subheader(f"Held for review: {held:,}{share}")
    st.caption("Held contacts are not ranked until their category (or a possible prior introduction) is "
               "resolved. Projected fit = the score they would get once categorized.")
    breakdown = held_breakdown(result)
    if breakdown:
        cols = st.columns(min(len(breakdown), 4))
        for col, (reason, n) in zip(cols, breakdown[:4], strict=False):
            col.metric(reason, f"{n:,}")
        if len(breakdown) > 4:
            st.caption(" · ".join(f"{r}: {n:,}" for r, n in breakdown[4:]))
    top = held_rows(result, limit=20)
    if top:
        threshold = result.config["thresholds"]["min_fit_score"]
        clearing = sum(1 for s in held_contacts(result) if s.fit_score >= threshold)
        st.markdown(f"**Top 20 held by projected score** — {clearing:,} held contact(s) would clear the "
                    f"{threshold:.1f} threshold.")
        st.dataframe(pd.DataFrame(top), hide_index=True, width="stretch",
                     column_config={"Projected fit": st.column_config.NumberColumn(format="%.1f", width="small"),
                                    "Why a fit": st.column_config.TextColumn(width="large")})
        full = pd.DataFrame(held_rows(result))
        st.download_button(f"Download held list ({len(full):,} rows, CSV)", full.to_csv(index=False).encode("utf-8-sig"),
                           f"{output_names(result.context.company_name, result.report_date)[1][:-5]}_held.csv",
                           "text/csv", key="held-download")


def step_results() -> None:
    result = state.result
    if result is None:
        st.info("Run matching from the Deal profile step.")
        return
    counts = summary_counts(result)
    ui.hero("Step 4 of 5", result.context.company_name or "Results", "ranked investors",
            f"{counts['qualified_total']:,} qualified contacts across four categories; "
            f"{counts['already_introduced']:,} already introduced and {counts['review']:,} held for review.",
            key="results")
    actions, notes = action_warnings(result)
    for a in actions:
        st.warning(_md(a), icon="⚠️")
    if notes:
        with st.expander(f"Other notes ({len(notes)})"):
            st.markdown(_md("\n".join(f"- {x}" for x in notes)))
    scoring_link("results")

    tiles = [(SHORT_CATEGORY.get(k, k), n, k) for k, n in counts["qualified"].items()]
    tiles += [("Introduced", counts["already_introduced"], "Already introduced to this company — excluded"),
              ("On hold", counts["review"], "Held for review: ambiguous type or possible prior introduction")]
    for col, (label, n, full) in zip(st.columns(6), tiles, strict=True):
        col.metric(label, f"{n:,}", help=full)

    _suggestions(result)

    st.subheader("Ranked investors")
    st.caption("Sorted by Fit Score. Select a row for LinkedIn, TEN relationship and the scoring evidence.")
    rows = []
    for s, values in zip(result.ranked, ranked_rows(result), strict=True):
        r = dict(zip(RANKED_COLUMNS, values, strict=True))
        name = " ".join(p for p in (s.contact.first_name, s.contact.last_name) if p)
        r.update({"Name": name or NEEDS_RESEARCH, "Note": contact_note(s.contact), "_scored": s,
                  "Why a fit": " · ".join(compact_why(s.components))})
        rows.append(r)
    by_score = sorted(rows, key=lambda r: (-r["Fit Score"], r["Note"] != "", r["Email"]))
    labels = [f"All ({len(rows):,})"] + [f"{SHORT_CATEGORY.get(k, k)} ({n:,})" for k, n in counts["qualified"].items()]
    picked = None
    for tab, (i, label) in zip(st.tabs(labels), enumerate(labels), strict=True):
        with tab:
            subset = by_score if i == 0 else [r for r in by_score if r["Category"] == list(counts["qualified"])[i - 1]]
            if not subset:
                st.caption("No qualified contacts in this category.")
                continue
            picked = _ranked_table(result, subset, "all" if i == 0 else f"cat{i}") or picked
    if picked is not None:
        _contact_detail(picked)

    _held_section(result, counts)

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
                _run(goto=None)
    with st.expander("Full screening log (exclusions, review items, flags)"):
        log = pd.DataFrame(exclusion_rows(result), columns=EXCLUSION_COLUMNS)
        status = st.multiselect("Status", [s.value for s in LogStatus],
                                default=[LogStatus.REVIEW.value, LogStatus.EXCLUDED.value])
        st.dataframe(log[log["Status"].isin(status)], hide_index=True, width="stretch")
    st.button("Export →", type="primary", on_click=go, args=(4,))


# ------------------------------------------------------------------------------ 5. export

def _size(n: int) -> str:
    return f"{n / 1024:,.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:,.1f} MB"


def _finalize(result) -> None:
    """The only place results are emailed. Sends once per generated state (deliver_results deduplicates)."""
    if not settings.notify_available:
        st.caption("Email delivery is not configured on this server — download the files below.")
        return
    to = ", ".join(settings.notify_recipients())
    key = generation_key(result)
    sent_now = next((n for n in result.notifications + state.get("sent_emails", [])
                     if n.sent and n.generation == key), None)     # also survives an unchanged re-run
    sent_before = [n for n in state.get("sent_emails", []) if n.generation != key]
    with st.container(border=True):
        if sent_now:
            st.success(f"✉ Finalized — results emailed to {to} ({sent_now.at[:16].replace('T', ' ')} UTC). "
                       "Re-running or changing the results will not send another email unless you finalize again.")
            return
        st.markdown(f"**Finalize & email** — when the shortlist looks right, send the PDF and workbook to **{to}**.")
        if sent_before:
            st.caption("An earlier version of these results was already emailed. Finalizing sends the updated version.")
        failed = [n for n in result.notifications if n.generation == key and not n.sent]
        if failed:
            st.warning("✉ " + failed[-1].status_text + ".")
        if st.button(f"Finalize & email to {to}", type="primary", key="finalize"):
            with st.spinner(f"Emailing results to {to}…"):
                outcome = deliver_results(result, state.outputs, settings)
            if outcome.sent:
                state.setdefault("sent_emails", []).append(outcome)
            st.rerun()


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
    counts = summary_counts(result)
    ui.hero("Step 5 of 5", "Results", "PDF · Excel · Email",
            "Download the one-page summary and the full workbook, then finalize to email them. "
            "Contact details are kept in the workbook only.", key="export")
    _finalize(result)
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Download one-page PDF", pdf, pdf_name, "application/pdf", type="primary", width="stretch")
    c1.caption(f"PDF · 1 page · {_size(len(pdf))}")
    c2.download_button("⬇ Download Excel workbook", xlsx, xlsx_name,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="secondary",
                       width="stretch")
    c2.caption(f"Workbook · {counts['qualified_total']:,} ranked + {counts['review']:,} held · {_size(len(xlsx))}")
    st.subheader("Google Sheets")
    if not settings.google_sheets_configured:
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


if state.get("_scrolled_step") != state.step:      # opened a new step: start at the top of the page
    state._scrolled_step = state.step
    state._scroll_nonce = state.get("_scroll_nonce", 0) + 1
    ui.scroll_to_top(f"step-{state.step}-{state._scroll_nonce}")
[step_inputs, step_mapping, step_profile, step_results, step_export][state.step]()
ui.footer(f"AI: Claude ({settings.im_llm_model})" if settings.llm_available else None)
