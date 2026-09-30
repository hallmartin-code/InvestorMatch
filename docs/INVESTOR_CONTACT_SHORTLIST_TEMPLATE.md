# Investor Contact Shortlist — Document Structure Template

<!-- Generated from app/reports/templates/investor_contact_shortlist.template.json by `python -m app.reports.template`. Edit the JSON, not this file. -->

Template `investor_contact_shortlist` v1.0.0. One-page summary of a company's current raise and the qualified investor contacts for it: the deal profile extracted from the pitch deck, qualified contact counts by category, the top contacts per category with a fit rationale, material gaps and screening limitations, and the number of investors already introduced. Detailed contact information stays in the companion workbook.

This template contains structure only: sections, fields, formats, limits and placeholders. It holds no company, investor or deal data; every value is filled from a run.

## Rules

- The template holds structure only; every value is filled from a run.
- Deal-profile values come only from the deck or from recorded user overrides; missing values read 'not stated in deck'.
- Conflicting deck values are shown as conflicts, never resolved silently.
- Only qualified contacts are shown; thin categories are never padded.
- No emails, phone numbers or LinkedIn URLs on the page; they stay in the workbook.
- Text is shortened (reduction ladder), never shrunk below the minimum body size.

## Page

| Property | Value |
|---|---|
| Size | US Letter portrait (612 × 792 pt) |
| Margins | left 40 · right 40 · top 34 · bottom 54 pt |
| Pages | exactly 1 |
| Font | Open Sans, body 9.0 pt (minimum 9.0 pt) |
| Palette | heading `#1F3864`, ink `#1F2328`, secondary_ink `#4A5360`, muted `#6B7380`, rule `#D9DDE3`, zebra `#F5F7FA`, tint `#EEF3FA`, group_header_text `#FFFFFF` |

## Layout

```text
TEN CAPITAL NETWORK · INVESTOR MATCH
[Company name] — Investor Contact Shortlist
Raise: [Raise amount] · [Stage] · [Instrument]   Report date: [Report date]   Deck date: [Deck date]
Row 1: Deal profile (left) | Qualified contacts (right)
Row 2: Top contacts by category (full ranked list in the Excel export) (full)
Row 3: Material gaps and screening limitations (full)
Confidential – for recipients only.
Investor Contact Shortlist     [PAGE#]     Compiled on [DATE] by TEN Capital Network   [TEN Capital Logo]
```

## Header

**Eyebrow:** `TEN CAPITAL NETWORK · INVESTOR MATCH`  
**Title:** `{company_name} — {document_title}` (17 pt; empty company → “Company not stated in deck”)  
**Logo:** TEN_Capital_logo_footer.png, 0.9 in, top right

| Field | Label | Source | Format | Placeholder | If empty |
|---|---|---|---|---|---|
| `raise_line` | Raise | `deal.raise_amount · deal.stage · deal.instrument` | joined:' · '; stage and instrument omitted when not stated | [Raise amount] · [Stage] · [Instrument] | not stated in deck |
| `report_date` | Report date | `run.report_date` | date:Month D, YYYY | [Report date] |  |
| `deck_date` | Deck date | `deal.deck_date` | date as stated; '(file metadata)' suffix when taken from file properties | [Deck date] | not stated in deck |

## Deal-profile fields analyzed

Extracted from every slide/page (text, tables, charts, notes, footnotes, appendices, OCR of image-only content), each with slide/page references and one of the statuses below.

| Field | Label | Placeholder |
|---|---|---|
| `company_name` | Company | [Company name] |
| `legal_name` | Legal name | [Legal entity name] |
| `sector` | Sector | [Sector] |
| `subsector` | Subsector | [Subsector(s)] |
| `stage` | Stage | [Stage] |
| `raise_amount` | Raise amount | [Raise amount] |
| `instrument` | Instrument | [Instrument] |
| `amount_committed` | Amount committed (signed / committed) | [Committed amount + signing status] |
| `soft_interest` | Soft interest (not committed) | [Soft interest] |
| `amount_remaining` | Amount remaining | [Remaining (stated or calculated)] |
| `company_geography` | Company geography | [Company location] |
| `target_investor_geography` | Target investor geography | [Target investor geography] |
| `target_close_date` | Target close date | [Target close date] |
| `deck_date` | Deck date | [Deck date] |

**Fact statuses**

| Status | Meaning |
|---|---|
| Stated in deck | One value found in the deck; cited to its slide/page. |
| Classified from deck language | Sector/subsector inferred from deck vocabulary; confirm before sending. |
| Calculated | Remaining = raise − signed/committed, only for the same round, currency and date; shown with '(calculated)'. |
| File metadata | Deck date taken from file properties because no date is on the title or closing slide. |
| Conflicting figures | Different values in the deck; shown as 'conflicting figures — A vs B' and not used until resolved. |
| Not stated in deck | Not found; never guessed. |

## 1. Deal profile

*Row 1, left · type `bullets`.* 5–6 compact bullets built from the effective deal profile (deck facts, or user overrides where recorded). Each bullet ends with the slide/page references of its facts.

| Bullet | Pattern | Fields |
|---|---|---|
| `identity` | `{company_name}[[ ({legal_name})]] — {sector}; {subsector}` | company_name, legal_name, sector, subsector |
| `terms` | `Stage: {stage}; instrument: {instrument}` | stage, instrument |
| `raise` | `Raise: {raise_amount}; committed: {amount_committed}` | raise_amount, amount_committed |
| `allocation` | `Remaining: {amount_remaining}; soft interest: {soft_interest}` | amount_remaining, soft_interest |
| `geography` | `Company: {company_geography}; target investors: {target_investor_geography}` | company_geography, target_investor_geography |
| `timing` | `Target close: {target_close_date}` | target_close_date |

Source markers: `[s{n}, p{n}]` (max 3; overrides cite “user override”). A [[...]] segment is dropped when its field is not stated or repeats the company name.

## 2. Qualified contacts

*Row 1, right · type `count_table`.* Counts must equal the row counts in the companion workbook.

| Row | Label | Source | Placeholder |
|---|---|---|---|
| `category_counts` | {category} | count of Ranked Investors rows per category | [N] |
| `qualified_total` | Total qualified (score ≥ {min_fit_score}) | count of Ranked Investors rows | [N] |
| `already_introduced` | Already introduced — do not re-intro | count of Already Introduced rows | [N] |
| `held_for_review` | Held for review | count of REVIEW rows in Exclusions and Review | [N] |

## 3. Top contacts by category (full ranked list in the Excel export)

*Row 2, full · type `grouped_table`.* Up to the top contacts per category from the ranked list, in category order, then Fit Score, evidence completeness, organization and name.

Grouped by category; group header `{category} — {count} qualified`; up to 3 rows per group; empty group → “No qualified contacts in this category.”.

| Column | Label | Source | Width | Limit | Placeholder | If empty |
|---|---|---|---|---|---|---|
| `rank` | # | rank within category | 14.0 |  | # |  |
| `name` | Name | contact first + last name | 92.0 |  | [Contact name] | (generic inbox — no named contact) |
| `organization` | Organization | contact organization | 112.0 | 40 chars | [Organization] | — |
| `score` | Score | Fit Score (1–10) | 34.0 |  | [0.0] |  |
| `why` | Why a fit | documented evidence per score component; inferences labelled '(inferred)' | remaining | 2 lines | [Evidence-based fit rationale] |  |

## 4. Material gaps and screening limitations

*Row 3, full · type `bullets`.* Run limitations in priority order: deck conflicts, fields not established, calculated values, classification notes, prior-introduction screening completeness, review items, low-evidence contacts, email-deliverability disclaimer, OCR gaps.

Up to 6 items (`[Material gap or screening limitation]`); overflow: `{n} more limitation(s) listed on the Deal Profile sheet.`

Closing note: `{already_introduced} investor(s) already introduced to this company are excluded (see Already Introduced, marked “do not re-intro”). Full exports: {workbook_file} — {sheet_list}. Contact details are kept in the spreadsheet only.`

## Investor categories

| Order | Label | Definition |
|---|---|---|
| 1 | Angels | Individual investors. |
| 2 | Angel Groups & Syndicates | Angel groups, networks and syndicates. |
| 3 | HNI & Family Offices | High-net-worth individuals and single/multi-family offices. |
| 4 | VCs (Seed & Early-Stage) | Seed and early-stage venture funds, including corporate VCs. |

## Footer

- `Confidential – for recipients only.` (8 pt, centered)
- `{document_title}     {page}     Compiled on {report_date} by TEN Capital Network` + logo (7 pt, centered; logo 0.67 × 0.25 in)

## One-page reduction ladder

Built, checked, and rebuilt with the next rung until every layout check passes.

| Rung | “Why a fit” lines | Limitation bullets | Profile bullets |
|---|---|---|---|
| 1 | 2 | 6 | 6 |
| 2 | 1 | 6 | 6 |
| 3 | 1 | 5 | 6 |
| 4 | 1 | 4 | 6 |
| 5 | 1 | 4 | 5 |
| 6 | 1 | 3 | 5 |
| 7 | 1 | 2 | 5 |

**Layout checks:** exactly one page; every text span inside the page bounds; every shortlisted contact name present in full; confidential footer present; body text ≥ min_body_size_pt.

## Companion workbook

File: `{company_slug}_investor_match_{report_date:YYYY-MM-DD}.xlsx`. Filters and frozen header row on every sheet; readable widths; text stored as literal strings (formula-safe); missing optional contact fields read 'needs research'.

| Sheet | Columns |
|---|---|
| Ranked Investors | Category · Fit Score · First Name · Last Name · Organization · Email · Phone · Investor Type · Location · Why a fit · TEN Relationship (Y/N) · LinkedIn |
| Already Introduced | Status · First Name · Last Name · Organization · Email · Introduction Date · Introduction Source · Company in Source · Match Basis · In TEN Master List · Master List Source · Intro Status / Outcome |
| Deal Profile | Field · Deck Value · Status · Slide/Page References · Evidence Excerpt · Override Value · Override Reason · Effective Value · Notes |
| Exclusions and Review | Status · Reason Code · Reason · First Name · Last Name · Organization · Email · Investor Type · Source References · Detail |
| Scoring Evidence | Status · Category · Rank · Fit Score · Evidence Completeness · First Name · Last Name · Organization · Email · Sector (0-10) · Sector Evidence · Stage (0-10) · Stage Evidence · Check Size (0-10) · Check Size Evidence · Geography (0-10) · Geography Evidence · TEN Relationship (0-10) · TEN Relationship Evidence · Weighted Calculation · Unknown / Flags · Source References |
