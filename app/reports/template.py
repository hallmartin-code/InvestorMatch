"""Document structure template: the single source of truth for the Investor Contact Shortlist.

``templates/investor_contact_shortlist.template.json`` defines the page, header, sections, fields,
labels, patterns, column widths, limits, placeholders, footer, reduction ladder and the companion
workbook's sheets and columns. It holds no company, investor or deal data. The PDF renderer, the
deal-profile bullets, the workbook column lists, the blank preview PDF and the Markdown
specification are all driven by it.

Regenerate the reference documents after editing the JSON:

    python -m app.reports.template
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import ROOT
from app.models import CATEGORY_ORDER, DEAL_FIELDS, NOT_STATED_TEXT

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TEMPLATE = TEMPLATE_DIR / "investor_contact_shortlist.template.json"
DOCS_DIR = ROOT / "docs"
MARKDOWN_PATH = DOCS_DIR / "INVESTOR_CONTACT_SHORTLIST_TEMPLATE.md"
PREVIEW_PATH = DOCS_DIR / "investor_contact_shortlist_TEMPLATE.pdf"
REQUIRED_SECTIONS = ("deal_profile", "qualified_contacts", "top_contacts", "gaps_and_limitations")
_FIELD = re.compile(r"\{([a-z_]+)\}")
_OPTIONAL = re.compile(r"\[\[(.*?)\]\]")


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class FieldSpec(_Model):
    key: str
    label: str = ""
    source: str = ""
    format: str = ""
    placeholder: str = ""
    empty_text: str | None = None
    width_pt: float | str | None = None
    max_chars: int | None = None
    max_lines: int | None = None


class Bullet(_Model):
    key: str
    pattern: str

    @property
    def fields(self) -> list[str]:
        return _FIELD.findall(self.pattern)


class Section(_Model):
    id: str
    title: str
    row: int
    column: str
    type: str
    description: str = ""
    bullets: list[Bullet] = Field(default_factory=list)
    rows: list[FieldSpec] = Field(default_factory=list)
    columns: list[FieldSpec] = Field(default_factory=list)


class Rung(_Model):
    why_lines: int
    limitations: int
    profile_bullets: int


class Sheet(_Model):
    name: str
    columns: list[str]


class ReportTemplate(_Model):
    template_id: str
    version: str
    document_title: str
    purpose: str
    rules: list[str]
    page: dict[str, Any]
    header: dict[str, Any]
    deal_fields: list[FieldSpec]
    fact_statuses: list[dict[str, str]]
    sections: list[Section]
    categories: list[dict[str, str]]
    footer: dict[str, Any]
    reduction_ladder: list[Rung]
    layout_checks: list[str]
    companion_workbook: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> ReportTemplate:
        ids = [s.id for s in self.sections]
        missing = [s for s in REQUIRED_SECTIONS if s not in ids]
        if missing:
            raise ValueError(f"template is missing sections: {missing}")
        if [f.key for f in self.deal_fields] != list(DEAL_FIELDS):
            raise ValueError("deal_fields must list every deal-profile field, in order")
        if [c["label"] for c in self.categories] != [c.value for c in CATEGORY_ORDER]:
            raise ValueError("categories must match the app's category order and labels")
        for bullet in self.section("deal_profile").bullets:
            unknown = [f for f in bullet.fields if f not in DEAL_FIELDS]
            if unknown:
                raise ValueError(f"bullet {bullet.key} uses unknown fields {unknown}")
        ladder = self.reduction_ladder
        for a, b in zip(ladder, ladder[1:], strict=False):
            if b.why_lines > a.why_lines or b.limitations > a.limitations or b.profile_bullets > a.profile_bullets:
                raise ValueError("each reduction-ladder rung must show no more text than the one before")
        if self.page["min_body_size_pt"] < 9:
            raise ValueError("body text may not be smaller than 9 pt")
        return self

    def section(self, section_id: str) -> Section:
        return next(s for s in self.sections if s.id == section_id)

    @property
    def sheets(self) -> list[Sheet]:
        return [Sheet.model_validate(s) for s in self.companion_workbook["sheets"]]

    def sheet_columns(self, name: str) -> list[str]:
        return next(s.columns for s in self.sheets if s.name == name)

    def deal_placeholder(self, key: str) -> str:
        return next(f.placeholder for f in self.deal_fields if f.key == key)


@lru_cache(maxsize=4)
def load_template(path: Path = DEFAULT_TEMPLATE) -> ReportTemplate:
    return ReportTemplate.model_validate_json(Path(path).read_text(encoding="utf-8"))


def fill_bullet(pattern: str, values: dict[str, str], company: str | None = None) -> str:
    """Fill ``{field}`` slots; drop ``[[...]]`` segments whose field is not stated or repeats the company."""
    def optional(match: re.Match) -> str:
        inner = match.group(1)
        for key in _FIELD.findall(inner):
            value = values.get(key, "")
            if not value or value == NOT_STATED_TEXT or (company and value == company):
                return ""
        return inner

    text = _OPTIONAL.sub(optional, pattern)
    return _FIELD.sub(lambda m: values.get(m.group(1), NOT_STATED_TEXT), text)


# ------------------------------------------------------------------------------ Markdown specification


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    def cell(v: Any) -> str:
        return "" if v is None else str(v).replace("|", "\\|").replace("\n", " ")
    return (["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
            + ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows])


def render_markdown(t: ReportTemplate | None = None) -> str:
    t = t or load_template()
    p = t.page
    m = p["margins_pt"]
    out = [f"# {t.document_title} — Document Structure Template", "",
           f"<!-- Generated from app/reports/templates/{DEFAULT_TEMPLATE.name} by `python -m app.reports.template`. "
           "Edit the JSON, not this file. -->", "",
           f"Template `{t.template_id}` v{t.version}. {t.purpose}", "",
           "This template contains structure only: sections, fields, formats, limits and placeholders. It holds no "
           "company, investor or deal data; every value is filled from a run.", "", "## Rules", ""]
    out += [f"- {r}" for r in t.rules]
    out += ["", "## Page", ""] + _table(["Property", "Value"], [
        ["Size", f"{p['size']} {p['orientation']} ({p['width_pt']} × {p['height_pt']} pt)"],
        ["Margins", f"left {m['left']} · right {m['right']} · top {m['top']} · bottom {m['bottom']} pt"],
        ["Pages", f"exactly {p['max_pages']}"],
        ["Font", f"{p['font_family']}, body {p['body_size_pt']} pt (minimum {p['min_body_size_pt']} pt)"],
        ["Palette", ", ".join(f"{k} `{v}`" for k, v in p["palette"].items())],
    ])
    h = t.header
    rows_by = {}
    for s in t.sections:
        rows_by.setdefault(s.row, []).append(s)
    out += ["", "## Layout", "", "```text", h["eyebrow"],
            h["title_pattern"].format(company_name=h["company_placeholder"], document_title=t.document_title),
            h["meta_separator"].join(f"{f['label']}: {f['placeholder']}" for f in h["meta_fields"])]
    for row in sorted(rows_by):
        out.append(f"Row {row}: " + " | ".join(f"{s.title} ({s.column})" for s in rows_by[row]))
    out += [t.footer["confidential_text"],
            t.footer["standard_line_pattern"].format(document_title=t.document_title, page="[PAGE#]",
                                                     report_date="[DATE]") + "   [TEN Capital Logo]", "```"]
    out += ["", "## Header", "", f"**Eyebrow:** `{h['eyebrow']}`  ", f"**Title:** `{h['title_pattern']}` "
            f"({h['title_size_pt']} pt; empty company → “{h['company_empty_text']}”)  ",
            f"**Logo:** {h['logo']['file']}, {h['logo']['width_in']} in, {h['logo']['position']}", ""]
    out += _table(["Field", "Label", "Source", "Format", "Placeholder", "If empty"],
                  [[f"`{f['key']}`", f["label"], f"`{f['source']}`", f["format"], f["placeholder"],
                    f.get("empty_text", "")] for f in h["meta_fields"]])
    out += ["", "## Deal-profile fields analyzed", "",
            "Extracted from every slide/page (text, tables, charts, notes, footnotes, appendices, OCR of image-only "
            "content), each with slide/page references and one of the statuses below.", ""]
    out += _table(["Field", "Label", "Placeholder"], [[f"`{f.key}`", f.label, f.placeholder] for f in t.deal_fields])
    out += ["", "**Fact statuses**", ""] + _table(["Status", "Meaning"],
                                                    [[s["status"], s["meaning"]] for s in t.fact_statuses])
    for n, s in enumerate(t.sections, start=1):
        out += ["", f"## {n}. {s.title}", "", f"*Row {s.row}, {s.column} · type `{s.type}`.* {s.description}", ""]
        extra = s.model_extra or {}
        if s.bullets:
            out += _table(["Bullet", "Pattern", "Fields"], [[f"`{b.key}`", f"`{b.pattern}`",
                                                            ", ".join(b.fields)] for b in s.bullets])
            out += ["", f"Source markers: `{extra['source_markers']['format']}` (max "
                        f"{extra['source_markers']['max_refs']}; overrides cite “{extra['source_markers']['override']}”). "
                        f"{extra.get('optional_segment_rule', '')}"]
        if s.rows:
            out += _table(["Row", "Label", "Source", "Placeholder"],
                          [[f"`{r.key}`", r.label, r.source, r.placeholder] for r in s.rows])
        if s.columns:
            out += [f"Grouped by category; group header `{extra['group_header_pattern']}`; up to "
                    f"{extra['max_rows_per_group']} rows per group; empty group → “{extra['empty_group_text']}”.", ""]
            out += _table(["Column", "Label", "Source", "Width", "Limit", "Placeholder", "If empty"],
                          [[f"`{c.key}`", c.label, c.source, c.width_pt,
                            f"{c.max_chars} chars" if c.max_chars else (f"{c.max_lines} lines" if c.max_lines else ""),
                            c.placeholder, c.empty_text or ""] for c in s.columns])
        if s.id == "gaps_and_limitations":
            out += [f"Up to {extra['max_items']} items (`{extra['item_placeholder']}`); overflow: "
                    f"`{extra['overflow_pattern']}`", "", f"Closing note: `{extra['closing_note']['pattern']}`"]
    out += ["", "## Investor categories", ""] + _table(["Order", "Label", "Definition"], [
        [i, c["label"], c["definition"]] for i, c in enumerate(t.categories, start=1)])
    f = t.footer
    out += ["", "## Footer", "", f"- `{f['confidential_text']}` ({f['confidential_size_pt']} pt, centered)",
            f"- `{f['standard_line_pattern']}` + logo ({f['standard_line_size_pt']} pt, centered; logo "
            f"{f['logo']['width_in']} × {f['logo']['height_in']} in)"]
    out += ["", "## One-page reduction ladder", "",
            "Built, checked, and rebuilt with the next rung until every layout check passes.", ""]
    out += _table(["Rung", "“Why a fit” lines", "Limitation bullets", "Profile bullets"],
                  [[i, r.why_lines, r.limitations, r.profile_bullets] for i, r in enumerate(t.reduction_ladder, 1)])
    out += ["", "**Layout checks:** " + "; ".join(t.layout_checks) + "."]
    wb = t.companion_workbook
    out += ["", "## Companion workbook", "", f"File: `{wb['file_pattern']}`. {wb['sheet_rules']}", ""]
    out += _table(["Sheet", "Columns"], [[s.name, " · ".join(s.columns)] for s in t.sheets])
    return "\n".join(out) + "\n"


def write_docs() -> list[Path]:
    from app.reports.template_preview import render_template_preview

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    MARKDOWN_PATH.write_text(render_markdown(), encoding="utf-8")
    PREVIEW_PATH.write_bytes(render_template_preview())
    return [MARKDOWN_PATH, PREVIEW_PATH]


if __name__ == "__main__":
    for written in write_docs():
        print("wrote", written)
