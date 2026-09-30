"""One-page PDF summary (US Letter portrait), laid out by the document structure template.

Structure (titles, labels, patterns, widths, limits, footer, reduction ladder) comes from
``templates/investor_contact_shortlist.template.json``; this module fills it with run data
(``data_from_result``) or placeholders (``template_preview``). One page with no clipped text is an
invariant: the page is built, checked with PyMuPDF (page count, every text span inside the page,
every shortlisted name present), and rebuilt on the next ladder rung until it fits. Body text never
drops below the template's minimum; text is cut, not shrunk.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

import pymupdf
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.extraction.deal_profile import profile_bullets
from app.models import CATEGORY_ORDER, NOT_STATED_TEXT, RunResult
from app.reports import theme as th
from app.reports.frames import summary_counts
from app.reports.template import ReportTemplate, Rung, load_template
from app.utils.text import truncate

TEMPLATE: ReportTemplate = load_template()
PAGE_W, PAGE_H = TEMPLATE.page["width_pt"], TEMPLATE.page["height_pt"]
_M = TEMPLATE.page["margins_pt"]
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = _M["left"], _M["top"], _M["bottom"]
CONTENT_W = PAGE_W - _M["left"] - _M["right"]
TITLE = TEMPLATE.document_title
CONFIDENTIAL = TEMPLATE.footer["confidential_text"]
BODY_PT = float(TEMPLATE.page["body_size_pt"])
LADDER: list[Rung] = TEMPLATE.reduction_ladder
_SEC = {s.id: s for s in TEMPLATE.sections}
_TOP = _SEC["top_contacts"]
_TOP_X = _TOP.model_extra or {}
WIDTHS = [c.width_pt for c in _TOP.columns if c.width_pt != "remaining"]
WHY_W = CONTENT_W - sum(WIDTHS)
CELL_PAD = 6
_PAL = {k: HexColor(v) for k, v in TEMPLATE.page["palette"].items()}


class PdfLayoutError(RuntimeError):
    pass


@dataclass
class ContactRow:
    rank: str
    name: str
    organization: str
    score: str
    why: str


@dataclass
class ShortlistData:
    """Everything the page shows, as display text. Real runs and the blank preview both produce one."""

    company: str
    raise_line: str
    report_date: str
    deck_date: str
    bullets: list[str]                         # all bullets; the ladder decides how many are shown
    count_rows: list[tuple[str, str]]          # one per category, then total, already introduced, review
    groups: list[tuple[str, list[ContactRow]]]  # (group header, rows)
    limitations: list[str]
    already_introduced: str
    workbook_file: str
    required_names: list[str] = field(default_factory=list)
    fit_rationale: bool = True                 # False for placeholders (kept as-is, not width-fitted)


def _styles() -> dict[str, ParagraphStyle]:
    f = th.font
    return {
        "eyebrow": ParagraphStyle("eyebrow", fontName=f("OpenSans-SemiBold"), fontSize=BODY_PT, leading=11,
                                  textColor=_PAL["muted"]),
        "title": ParagraphStyle("title", fontName=f("OpenSans-Bold"), fontSize=TEMPLATE.header["title_size_pt"],
                                leading=TEMPLATE.header["title_size_pt"] + 3, textColor=_PAL["heading"]),
        "meta": ParagraphStyle("meta", fontName=f("OpenSans"), fontSize=BODY_PT, leading=11.5,
                               textColor=_PAL["secondary_ink"]),
        "h2": ParagraphStyle("h2", fontName=f("OpenSans-Bold"), fontSize=10.5, leading=13, textColor=_PAL["heading"],
                             spaceBefore=2, spaceAfter=3),
        "body": ParagraphStyle("body", fontName=f("OpenSans"), fontSize=BODY_PT, leading=11.3, textColor=_PAL["ink"]),
        "bullet": ParagraphStyle("bullet", fontName=f("OpenSans"), fontSize=BODY_PT, leading=11.3,
                                 textColor=_PAL["ink"], leftIndent=9, bulletIndent=0, spaceAfter=1.2),
        "cell": ParagraphStyle("cell", fontName=f("OpenSans"), fontSize=BODY_PT, leading=11, textColor=_PAL["ink"]),
        "cell_b": ParagraphStyle("cell_b", fontName=f("OpenSans-SemiBold"), fontSize=BODY_PT, leading=11,
                                 textColor=_PAL["ink"]),
        "cell_c": ParagraphStyle("cell_c", fontName=f("OpenSans-SemiBold"), fontSize=BODY_PT, leading=11,
                                 textColor=_PAL["ink"], alignment=TA_CENTER),
        "cat": ParagraphStyle("cat", fontName=f("OpenSans-Bold"), fontSize=BODY_PT, leading=11,
                              textColor=_PAL["group_header_text"]),
        "muted": ParagraphStyle("muted", fontName=f("OpenSans-Italic"), fontSize=BODY_PT, leading=11,
                                textColor=_PAL["secondary_ink"]),
    }


def _e(text: object) -> str:
    return escape(str(text))


def fit_width(text: str, width: float, font_name: str, size: float = BODY_PT) -> str:
    """Cut text (with an ellipsis) so it renders within ``width`` points on one line."""
    measure = lambda t: pdfmetrics.stringWidth(t, font_name, size)  # noqa: E731
    if measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(truncate(text, mid)) <= width:
            lo = mid
        else:
            hi = mid - 1
    return truncate(text, max(lo, 1))


def _fmt_date(d) -> str:
    return f"{d:%B} {d.day}, {d.year}"


# ------------------------------------------------------------------------------ data


def data_from_result(result: RunResult, workbook_file: str) -> ShortlistData:
    d = result.deal.effective_display
    parts = [d("raise_amount")] + [d(k) for k in ("stage", "instrument") if d(k) != NOT_STATED_TEXT]
    counts = summary_counts(result)
    rows_spec = {r.key: r for r in _SEC["qualified_contacts"].rows}
    count_rows = [(cat, str(n)) for cat, n in counts["qualified"].items()]
    count_rows += [
        (rows_spec["qualified_total"].label.format(min_fit_score=result.config["thresholds"]["min_fit_score"]),
         str(counts["qualified_total"])),
        (rows_spec["already_introduced"].label, str(counts["already_introduced"])),
        (rows_spec["held_for_review"].label, str(counts["review"])),
    ]
    per_group = _TOP_X["max_rows_per_group"]
    name_col, org_col = (next(c for c in _TOP.columns if c.key == k) for k in ("name", "organization"))
    groups, names = [], []
    for cat in CATEGORY_ORDER:
        members = [x for x in result.ranked if x.category == cat]
        header = _TOP_X["group_header_pattern"].format(category=cat.value, count=len(members))
        rows = []
        for x in members[:per_group]:
            c = x.contact
            if c.full_name:
                names.append(c.full_name)
            rows.append(ContactRow(str(x.rank), c.full_name or name_col.empty_text,
                                   truncate(c.organization, org_col.max_chars) or org_col.empty_text,
                                   f"{x.fit_score:.1f}", x.why))
        groups.append((header, rows))
    return ShortlistData(
        company=result.context.company_name or TEMPLATE.header["company_empty_text"],
        raise_line=" · ".join(parts), report_date=_fmt_date(result.report_date), deck_date=d("deck_date"),
        bullets=profile_bullets(result.deal, result.context, limit=len(_SEC["deal_profile"].bullets)),
        count_rows=count_rows, groups=groups, limitations=list(result.limitations),
        already_introduced=str(counts["already_introduced"]), workbook_file=workbook_file, required_names=names)


# ------------------------------------------------------------------------------ sections


def _header(data: ShortlistData, s: dict) -> list:
    h = TEMPLATE.header
    labels = {f["key"]: f["label"] for f in h["meta_fields"]}
    values = {"raise_line": data.raise_line, "report_date": data.report_date, "deck_date": data.deck_date}
    gap = "&nbsp;" * 3
    meta = gap.join(f"<b>{_e(labels[k])}:</b> {_e(values[k])}" for k in labels)
    left = [Paragraph(_e(h["eyebrow"]), s["eyebrow"]),
            Paragraph(_e(h["title_pattern"].format(company_name=data.company, document_title=TITLE)), s["title"]),
            Paragraph(meta, s["meta"])]
    logo = th.logo_path()
    w = h["logo"]["width_in"] * 72
    right = Image(str(logo), width=w, height=w * 232 / 631) if logo else Paragraph("", s["body"])
    table = Table([[left, right]], colWidths=[CONTENT_W - 80, 80])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.8, _PAL["heading"])]))
    return [table, Spacer(1, 7)]


def _profile_and_counts(data: ShortlistData, s: dict, rung: Rung) -> list:
    profile, counts = _SEC["deal_profile"], _SEC["qualified_contacts"]
    left = [Paragraph(_e(profile.title), s["h2"])] + [
        Paragraph(_e(b), s["bullet"], bulletText="•") for b in data.bullets[: rung.profile_bullets]]
    rows = [[Paragraph(_e(label), s["cell"]), Paragraph(_e(n), s["cell_c"])] for label, n in data.count_rows]
    total_row = len(CATEGORY_ORDER)
    rows[total_row][0] = Paragraph(f"<b>{_e(data.count_rows[total_row][0])}</b>", s["cell"])
    right_w = (counts.model_extra or {}).get("width_pt", 190)
    grid = Table(rows, colWidths=[right_w - 34, 34])
    grid.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _PAL["zebra"]), ("BACKGROUND", (0, total_row), (-1, total_row), _PAL["tint"]),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, th.WHITE), ("LINEABOVE", (0, total_row), (-1, total_row), 0.8, _PAL["heading"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    right = [Paragraph(_e(counts.title), s["h2"]), grid]
    outer = Table([[left, right]], colWidths=[CONTENT_W - right_w - 14, right_w + 14])
    outer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (0, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return [outer, Spacer(1, 6)]


def _top_contacts(data: ShortlistData, s: dict, rung: Rung) -> list:
    # Two lines never fit exactly 2× one line (word wrap), so allow 1.85× for the two-line rung.
    why_width = (WHY_W - CELL_PAD) * (1.0 if rung.why_lines == 1 else 1.85)
    head = [Paragraph(f"<b>{_e(c.label)}</b>", s["cell"]) for c in _TOP.columns]
    table_rows = [head]
    styles = [("BACKGROUND", (0, 0), (-1, 0), _PAL["tint"]), ("LINEBELOW", (0, 0), (-1, 0), 0.6, _PAL["heading"])]
    for header, rows in data.groups:
        table_rows.append([Paragraph(_e(header), s["cat"])] + [""] * (len(_TOP.columns) - 1))
        r = len(table_rows) - 1
        styles += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), _PAL["heading"])]
        if not rows:
            table_rows.append([Paragraph(_e(_TOP_X["empty_group_text"]), s["muted"])] + [""] * (len(_TOP.columns) - 1))
            styles.append(("SPAN", (0, len(table_rows) - 1), (-1, len(table_rows) - 1)))
            continue
        for row in rows:
            why = fit_width(row.why, why_width, s["cell"].fontName) if data.fit_rationale else row.why
            table_rows.append([Paragraph(_e(row.rank), s["cell"]), Paragraph(_e(row.name), s["cell_b"]),
                               Paragraph(_e(row.organization), s["cell"]), Paragraph(_e(row.score), s["cell_c"]),
                               Paragraph(_e(why), s["cell"])])
    table = Table(table_rows, colWidths=WIDTHS + [WHY_W])
    table.setStyle(TableStyle(styles + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 1), (-1, -1), 0.3, _PAL["rule"]),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [Paragraph(_e(_TOP.title), s["h2"]), table, Spacer(1, 6)]


def _gaps(data: ShortlistData, s: dict, rung: Rung) -> list:
    sec = _SEC["gaps_and_limitations"]
    extra = sec.model_extra or {}
    limit = min(rung.limitations, extra["max_items"])
    items = data.limitations[:limit]
    if len(data.limitations) > limit:
        items = items[:-1] + [extra["overflow_pattern"].format(n=len(data.limitations) - limit + 1)]
    sheets = ", ".join(sh.name for sh in TEMPLATE.sheets)
    note = _e(extra["closing_note"]["pattern"].format(
        already_introduced=data.already_introduced, workbook_file=data.workbook_file, sheet_list=sheets))
    lead = _e(f"{data.already_introduced} investor(s) already introduced")
    note = note.replace(lead, f"<b>{lead}</b>", 1).replace(_e(data.workbook_file), f"<b>{_e(data.workbook_file)}</b>", 1)
    block = [Paragraph(_e(sec.title), s["h2"])] + [Paragraph(_e(t), s["bullet"], bulletText="•") for t in items]
    block += [Spacer(1, 4), Paragraph(note, s["body"])]
    return [KeepTogether(block)]


def _footer(canvas, doc, date_text: str) -> None:
    f = TEMPLATE.footer
    canvas.saveState()
    canvas.setFont(th.font("OpenSans-SemiBold"), f["confidential_size_pt"])
    canvas.setFillColor(_PAL["secondary_ink"])
    canvas.drawCentredString(PAGE_W / 2, 30, CONFIDENTIAL)
    size = f["standard_line_size_pt"]
    canvas.setFont(th.font("OpenSans"), size)
    text = f["standard_line_pattern"].format(document_title=TITLE, page=doc.page, report_date=date_text)
    width = canvas.stringWidth(text, th.font("OpenSans"), size)
    logo = th.logo_path()
    logo_w, logo_h = (f["logo"]["width_in"] * 72, f["logo"]["height_in"] * 72) if logo else (0, 0)
    x = (PAGE_W - width - (logo_w + 6 if logo else 0)) / 2
    canvas.drawString(x, 16, text)
    if logo:
        canvas.drawImage(str(logo), x + width + 6, 11, width=logo_w, height=logo_h, mask="auto")
    canvas.restoreState()


def build(data: ShortlistData, rung: Rung) -> bytes:
    s = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(PAGE_W, PAGE_H), leftMargin=MARGIN_X, rightMargin=_M["right"],
                            topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM, title=f"{data.company} — {TITLE}",
                            author="TEN Capital Network", subject=CONFIDENTIAL)
    story = _header(data, s) + _profile_and_counts(data, s, rung) + _top_contacts(data, s, rung) + _gaps(data, s, rung)
    doc.build(story, onFirstPage=lambda c, d: _footer(c, d, data.report_date),
              onLaterPages=lambda c, d: _footer(c, d, data.report_date))
    return buffer.getvalue()


def check_layout(pdf: bytes, required: list[str]) -> list[str]:
    """Problems with the rendered page: page count, text outside the page, missing required strings."""
    problems = []
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        if doc.page_count != TEMPLATE.page["max_pages"]:
            problems.append(f"{doc.page_count} pages")
            return problems
        page = doc[0]
        bounds = page.rect
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    x0, y0, x1, y1 = span["bbox"]
                    if span["text"].strip() and (x0 < bounds.x0 - 0.5 or y0 < bounds.y0 - 0.5
                                                 or x1 > bounds.x1 + 0.5 or y1 > bounds.y1 + 0.5):
                        problems.append(f"text outside page: {span['text'][:30]!r}")
        flat = " ".join(page.get_text("text").split())
        for item in required:
            if " ".join(item.split()) not in flat:
                problems.append(f"missing text: {item!r}")
    return problems


def render_data(data: ShortlistData) -> bytes:
    required = [CONFIDENTIAL, TITLE] + data.required_names
    last: list[str] = []
    for rung in LADDER:
        pdf = build(data, rung)
        last = check_layout(pdf, required)
        if not last:
            return pdf
    raise PdfLayoutError("The summary could not fit on one page: " + "; ".join(last))


def required_strings(result: RunResult) -> list[str]:
    return [CONFIDENTIAL, TITLE] + data_from_result(result, "").required_names


def render_pdf(result: RunResult, xlsx_name: str = "investor_match.xlsx") -> bytes:
    return render_data(data_from_result(result, xlsx_name))
