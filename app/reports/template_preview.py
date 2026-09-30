"""Blank template preview: the one-page layout filled with placeholders only (no data)."""

from __future__ import annotations

from app.models import DEAL_FIELDS
from app.reports.pdf_report import TEMPLATE, ContactRow, ShortlistData, render_data
from app.reports.template import fill_bullet


def placeholder_data() -> ShortlistData:
    t = TEMPLATE
    h = t.header
    meta = {f["key"]: f["placeholder"] for f in h["meta_fields"]}
    sections = {s.id: s for s in t.sections}
    values = {key: t.deal_placeholder(key) for key in DEAL_FIELDS}
    bullets = [fill_bullet(b.pattern, values) + " [s#]" for b in sections["deal_profile"].bullets]
    counts = sections["qualified_contacts"]
    rows = {r.key: r for r in counts.rows}
    count_rows = [(c["label"], rows["category_counts"].placeholder) for c in t.categories]
    count_rows += [(rows["qualified_total"].label.format(min_fit_score="[min]"), rows["qualified_total"].placeholder),
                   (rows["already_introduced"].label, rows["already_introduced"].placeholder),
                   (rows["held_for_review"].label, rows["held_for_review"].placeholder)]
    top = sections["top_contacts"]
    extra = top.model_extra or {}
    col = {c.key: c.placeholder for c in top.columns}
    groups = [(extra["group_header_pattern"].format(category=c["label"], count="[N]"),
               [ContactRow(col["rank"], col["name"], col["organization"], col["score"], col["why"])
                for _ in range(extra["max_rows_per_group"])]) for c in t.categories]
    gaps = sections["gaps_and_limitations"].model_extra or {}
    closing = gaps["closing_note"]["placeholders"]
    return ShortlistData(
        company=h["company_placeholder"], raise_line=meta["raise_line"], report_date=meta["report_date"],
        deck_date=meta["deck_date"], bullets=bullets, count_rows=count_rows, groups=groups,
        limitations=[gaps["item_placeholder"]] * gaps["max_items"],
        already_introduced=closing["already_introduced"], workbook_file=closing["workbook_file"],
        fit_rationale=False)


def render_template_preview() -> bytes:
    return render_data(placeholder_data())
