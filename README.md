# TEN Capital Investor Match

Reads a startup pitch deck and the TEN Capital Investor List, screens out contacts who should not be
approached, and produces a ranked investor contact list for the company's current raise:

* **One-page PDF** (US Letter) — deal profile, qualified counts by category, top three contacts per
  category, material gaps, and the already-introduced count. Footer: *Confidential – for recipients only.*
* **Excel workbook** — Ranked Investors, Already Introduced, Deal Profile, Exclusions and Review, Scoring Evidence.
* **Google Sheet** — the same five sheets, when a service account is configured.
* **Results email** — after every generation (each matching run and each re-run after review decisions), a
  summary following the template's sections is emailed via Resend to `Info@tencapital.group` with the PDF and
  workbook attached. Each generated state is emailed once; a failed email never fails the analysis.

The app never invents names, emails, phone numbers, LinkedIn URLs, preferences or TEN relationships. It never
contacts investors or founders; the only email it sends is the internal results email.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app/app.py                     # http://localhost:8501
```

Headless run on the bundled **synthetic** sample (writes to `output/`):

```bash
python sample_data/make_samples.py           # regenerate sample inputs (already included)
python -m app.cli --deck sample_data/cardiolyte_health_deck.pptx \
    --investors sample_data/TEN_Capital_Investor_List_SAMPLE.xlsx \
    --intros sample_data/TEN_Intro_Tracker_2026.xlsx sample_data/cardiolyte_health_intros_Q3.csv \
    --out output
pytest                                       # 76 tests
```

Example outputs from that run are in [`sample_output/`](sample_output/). Python 3.11+.

## Workflow (UI)

1. **Inputs** — pitch deck (PDF, PPTX, PPT), TEN Capital Investor List (Excel/CSV; if none is uploaded the
   project file from `IM_INVESTOR_LIST_PATH` or `data/TEN*Investor*List*.xlsx` is used), one or more
   Investor Introductions lists, and optional company aliases.
2. **Column mapping** — headers are auto-mapped (exact synonym → phrase → fuzzy) and every mapping can be changed.
   Intro lists without a company column can be marked "for this company only"; otherwise their matches are held
   for review.
3. **Deal profile** — every extracted fact with its status and slide/page reference. Correct any field; overrides
   are stored beside the deck facts (both appear in the Deal Profile sheet), never over them.
4. **Results & review** — ranked contacts, possible prior introductions with a decision column
   (*Treat as not introduced* / *Treat as introduced*), the exclusion log and screening limitations.
5. **Export** — PDF, Excel, and Google Sheets.

## Deal-profile extraction

Every slide is read: text frames, grouped shapes, tables, chart data, speaker notes, footnotes and appendices.
PDF tables drawn as positioned text are rebuilt row by row. Image-only slides and large pictures are OCR'd with
RapidOCR (no system binary). Legacy `.ppt` is converted with LibreOffice when installed; otherwise the app says
how to install it or re-save as PPTX/PDF.

Rules (deterministic, in `app/extraction/deal_profile.py`):

* Money amounts are classified by the nearest keyword: raise, signed, committed, soft interest, remaining,
  prior (e.g. "raised to date") or ignored (valuation cap, TAM, revenue, use of funds…). Future-round figures
  ("Next round: Series A of $8M") are ignored and logged.
* Fields not found are **"not stated in deck"**. Different values for one field are **conflicting figures** — no
  value is chosen until the user resolves it.
* **Signed** commitments, **committed** amounts whose signing status is not stated, and **soft interest** are
  kept apart. Soft interest is never subtracted.
* Remaining allocation is **calculated** only when raise and commitment are single unconflicted values in the
  same currency, tied to the same round (same slide, "this round"/"of which" wording, or the same round name),
  and not dated differently. The result is labelled "(calculated)".
* Sector/subsector come from an explicit "Sector:" line when present; otherwise they are classified from the
  deck's vocabulary and labelled *Classified from deck language*.

**Claude deck analysis** runs whenever `ANTHROPIC_API_KEY` is set (ticked by default per run; `--no-claude` in the
CLI). Claude (`claude-opus-5-5`, structured JSON output, server-side refusal fallback) reads the whole deck and
returns every deal-profile fact with a slide number and verbatim quote. Facts whose quote does not match that
slide, or whose numbers are not in the quote, are discarded. Its reading is cross-checked against the rules:
fields the rules missed are filled, keyword-classified sector/subsector is replaced by Claude's grounded
classification, matching values are marked "Confirmed by Claude", and disagreements become **conflicts** for the
user to resolve. The deck is passed as data in `<deck>` tags with an instruction to ignore instructions inside
it. Screening, scoring and the template-driven PDF/Excel stay deterministic Python.

## Built-in investor lists

Trusted lists live in `data/investor_lists/` (or `IM_INVESTOR_LISTS_DIR`). The Inputs step offers them in a picker,
newest first, with the newest selected by default; pick one or more, and upload other lists alongside if needed.
Parsed files are cached per file version, so later runs skip re-reading them. **Unsubscribe sheets from every built-in list
always apply**, even when that list isn't selected. Within a file, a contact sheet whose emails are already on a
larger sheet (a segment such as "A-Priority" of "Master") is skipped automatically.

## Files API: Claude review of held contacts

The built-in lists are also uploaded to the Anthropic **Files API** so Claude can read them. Files uploaded to
the Files API cannot be downloaded back, so matching still runs on the app's local copy. The file IDs give Claude
the same list inside its code-execution sandbox:

```bash
python -m app.services.files_api      # upload new/changed built-in lists; IDs go to data/investor_lists/files_api.json
```

After each matching run, contacts held for review only because their investor type is missing or ambiguous,
and that would reach the Fit Score threshold if categorized (up to 200), are sent to Claude by file, sheet, row
and email. Claude opens the list via `container_upload`, reads each row and suggests one of the four categories
with a verbatim quote. Each quote is verified against the app's copy of that row, and any suggestion whose quote
isn't found is discarded. Suggestions appear in *Results → Claude category suggestions* and in the review log,
with the evidence column and a rule check. **They are never ranked until a reviewer accepts them**; accepted ones
re-run matching and are logged as `CATEGORY_ACCEPTED`. Toggle on the Inputs step; `IM_CLAUDE_REVIEW_ENABLED=false`
turns it off; the CLI skips it with `--no-claude`.

## Multi-sheet investor workbooks

Every sheet of the investor workbook is read and given a role, shown and changeable in the Column mapping step:

* **Investor contacts** — mapped as usual; duplicates across sheets are merged by email.
* **Unsubscribe / suppression list** — detected from the sheet name (unsub, opt-out, do not contact, DNC, bounced…)
  or a column that marks every row "Unsub". Every email on it (found by header or by content) excludes the matching
  contact, including matches on a contact's *Alternative emails*; the exclusion cites the sheet and row.
* **Skip** — sheets without identifiable email and name columns are skipped with a note instead of blocking the run.

Sheets whose first row is data (an email address where a header would be) are read without a header row.
A free-text *Description / profile* column is used as fallback evidence for sector, stage, geography and check size
when the dedicated columns are empty; such points are labelled "(from description)" and never exclude a contact.

## Screening

| Step | Rule |
|---|---|
| Email | Only syntactically valid addresses (syntax ≠ deliverability). Generic inboxes (`info@`, `invest@`…) are kept but flagged. |
| Duplicates | Merged by case-insensitive email; list fields are unioned, conflicts noted, missing fields filled. Suppression on any duplicate suppresses the merged contact. Same name + organization under different emails is flagged. |
| Suppression | Unsubscribed / opted-out / bounced / do-not-contact values in the mapped status column. |
| Prior introductions | Email (case-insensitive) or normalized name + organization on a row for this company (aliases: deck name, legal name, user aliases) → **excluded, "do not re-intro"**. Name-only, similar-name, organization-level rows, near-miss company names (e.g. "Cardiolyte Hlth") and files with no company column → **held for review**, never silently treated as new. No intro files → an explicit limitation. |
| Investor type | Private equity, buyout, investment banks and growth-equity types excluded. Unstated, unrecognized, mixed or ambiguous types go to review — they are never forced into a category. |
| Incompatibility | Explicit stage focus that excludes the deal stage, growth/late-stage-only focus, a geographic focus that excludes the company location, or an investor located outside the deck's stated target investor geography → excluded. Unknown is never incompatible. |

Categories, in order: **Angels**, **Angel Groups & Syndicates**, **HNI & Family Offices**, **VCs (Seed & Early-Stage)**
(includes corporate VCs).

## Fit Score rubric (1–10)

Each component is rated 0–10; Fit Score = Σ rating × weight, rounded half-up to one decimal (floor 1.0).

| Component | Weight | Ratings |
|---|---|---|
| Sector / subsector | 45% | investor names one of the deal's subsectors (explicit niche) **10** · names the deal's sector broadly **7** · names a different subsector in the same sector **5** · generalist / sector-agnostic **3** · outside the sector **0** |
| Stage | 15% | deal stage named (including inside a range like "Seed to Series A") **10** · covered only by "early stage" **7** · stage-agnostic **5** |
| Check size | 15% | minimum ≤ remaining allocation and maximum ≥ 2% of it **10** · can participate but checks are smaller **6** · minimum exceeds remaining **0** · states it does not co-invest: capped at **4**. Investors need not fund the whole balance. |
| Geography | 15% | stated focus includes the company's city/state/US sub-region **10** · country **8** · continental region **6** · global **5** · no stated focus: *inferred* from investor location — same state **4**, same country **2** (labelled "inferred") |
| TEN relationship | 10% | documented core-list status **5** + introductions to similar clients (master-list column, or intro-list rows for other companies in the deal's sector) **3** + TEN event participation **2**. Presence in the master list alone is not evidence. |

* **Unknown attributes earn 0 and are flagged** in the Scoring Evidence sheet; they are never treated as incompatibility.
* **Evidence completeness** = share of the five investor-side attributes that are documented; reported separately.
* Contacts with Fit Score **≥ 5.0** are kept. Within each category: score ↓, evidence completeness ↓, organization,
  name. Each organization is capped at **3** contacts across the complete list (its strongest are kept).
* **TEN Relationship (Y/N)**: `Y` only with documented evidence; `N` when every relationship field is explicitly
  negative; otherwise `needs research`. Other missing contact fields also show `needs research`.
* "Why a fit" lists only documented evidence; inferences are labelled "(inferred)".

All numbers live in [`config/scoring.toml`](config/scoring.toml); its fingerprint is recorded in each workbook.

## Outputs

**Ranked Investors** columns (exact): Category | Fit Score | First Name | Last Name | Organization | Email | Phone |
Investor Type | Location | Why a fit | TEN Relationship (Y/N) | LinkedIn.

Every row in every sheet keeps its source file, sheet and row (or deck slide/page). All sheets have filters, frozen
headers and readable widths. Text is written as literal strings with Excel's quote-prefix flag when it starts with
`= + - @`, so imported values cannot run as formulas, and values like `+1 512…` are unchanged. Google Sheets uses
`valueInputOption=RAW`.

The PDF is checked after rendering: exactly one page, every text span inside the page, and every shortlisted name
present. If a check fails, it is rebuilt with shorter text (one-line rationales, fewer limitation bullets). Body text
never drops below 9 pt. Thin categories are never padded.

## Document structure template

The one-page PDF's structure lives in
[`app/reports/templates/investor_contact_shortlist.template.json`](app/reports/templates/investor_contact_shortlist.template.json):
page and palette, header fields, the deal-profile fields analyzed and their statuses, section order and titles,
bullet patterns, count rows, table columns and widths, character/line limits, placeholders, the category list,
the footer, the one-page reduction ladder, layout checks, and the companion workbook's sheets and columns. It
contains no company, investor or deal data. The PDF renderer, the deal-profile bullets and the workbook column
lists all read it. The blank references are generated from it:

* [`docs/INVESTOR_CONTACT_SHORTLIST_TEMPLATE.md`](docs/INVESTOR_CONTACT_SHORTLIST_TEMPLATE.md) — field-by-field specification
* [`docs/investor_contact_shortlist_TEMPLATE.pdf`](docs/investor_contact_shortlist_TEMPLATE.pdf) — the page with placeholders only

To change the layout, edit the JSON, run `python -m app.reports.template`, then `pytest`. The tests check that the
template validates, holds no run data, and matches the rendered report, and that the docs are up to date.

## Icons

`app/static/` is the public directory (Streamlit `enableStaticServing`, served at `/app/static/`).
`favicon.png` is the TEN Capital icon, used as the browser-tab favicon through
`st.set_page_config(page_icon=FAVICON_PATH)` (`app/config.py`) and as the header mark. Generated from it:
`favicon.ico` (16/32/48), `favicon-16x16.png`, `favicon-32x32.png`, `favicon-48x48.png`, `icon-192.png`
(web manifest) and `apple-touch-icon.png` (180 px on white), all listed in `site.webmanifest`.

## Configuration

Copy `.env.example` to `.env`. Secrets are read only from the environment.

| Variable | Purpose |
|---|---|
| `IM_INVESTOR_LIST_PATH` | Default TEN Capital Investor List (else `data/TEN*Investor*List*.xlsx`) |
| `ANTHROPIC_API_KEY`, `IM_LLM_ENABLED`, `IM_LLM_MODEL` | Claude deck analysis (on when a key is set; default model `claude-opus-5-5`) |
| `TEN_APP_PASSWORD` | Optional access password for the web app (unset = no password) |
| `RESEND_API_KEY`, `IM_NOTIFY_TO`, `IM_NOTIFY_FROM` | Automated results email after every generation (default to `Info@tencapital.group`, from `reports@tencapital.group`; the sender domain must be verified in Resend). `IM_NOTIFY_ENABLED=false` or CLI `--no-email` turns it off. |
| `IM_GOOGLE_SERVICE_ACCOUNT_FILE` (or `GOOGLE_APPLICATION_CREDENTIALS`) | Service-account JSON key for Google Sheets export |
| `IM_GOOGLE_DRIVE_FOLDER_ID`, `IM_GOOGLE_SHARE_WITH` | Optional target folder; addresses to share with (no notification email) |

**Enabling Google Sheets:** create a Google Cloud service account, enable the Sheets and Drive APIs, download its
JSON key to a location outside this project, and set `IM_GOOGLE_SERVICE_ACCOUNT_FILE`. Without it, the PDF and Excel
exports are complete and the app shows these steps.

**Legacy .ppt:** install LibreOffice (`soffice` on PATH or in the default install folder), or save the deck as PPTX/PDF.

## Architecture

```text
app/
  app.py                 Streamlit UI              cli.py       headless runner
  pipeline.py            orchestration             config.py    env settings + scoring.toml
  models.py              dataclasses (facts, contacts, scores, log, SourceRef)
  ingestion/             deck.py (PDF/PPTX/PPT + OCR), ocr.py, tables.py (CSV/Excel), mapping.py
  extraction/            deal_profile.py (rules, conflicts, remaining, overrides), parsing.py (money/dates/checks),
                         taxonomy.py (sectors, stages, geography), llm.py (optional Claude)
  screening/             contacts.py (validation, dedupe, suppression), introductions.py, categorize.py,
                         scoring.py (attributes, incompatibility, rubric), ranking.py (sort, org cap)
  reports/               frames.py (sheet content), excel_report.py, google_sheets.py, pdf_report.py, theme.py
config/scoring.toml      weights, ratings, thresholds, screening vocabularies, OCR budget
sample_data/             synthetic deck (PPTX + PDF), investor list, intro lists, generator
tests/                   extraction, screening, scoring, reports, UI smoke test
```

Deploy: `Dockerfile` + `railway.json` — see [DEPLOY.md](DEPLOY.md). Live at
<https://investor-match-production.up.railway.app> (password-protected).

## Known limitations

* Extraction is rule-based; unusual phrasing ("we're closing out a 2.5 mil seed") can be missed and then shows as
  "not stated in deck" for the user to fill in. Sector classification is keyword-based and labelled as such.
* OCR quality depends on image resolution; OCR text is used like slide text and cited as "(OCR)".
* Location parsing covers US states/major cities and common countries; others become "unknown", not incompatible.
* Check sizes in a different currency from the raise are not converted (rated unknown and flagged).
* Email deliverability is not verified.
