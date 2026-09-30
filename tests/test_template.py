from __future__ import annotations

import json
import re

import pymupdf
import pytest

from app.models import DEAL_FIELDS
from app.reports.frames import RANKED_COLUMNS, SHEET_NAMES
from app.reports.pdf_report import render_pdf
from app.reports.template import (
    DEFAULT_TEMPLATE,
    MARKDOWN_PATH,
    ReportTemplate,
    fill_bullet,
    load_template,
    render_markdown,
)
from app.reports.template_preview import render_template_preview


def test_template_validates_and_matches_app():
    t = load_template()
    assert t.document_title == "Investor Contact Shortlist"
    assert [f.key for f in t.deal_fields] == list(DEAL_FIELDS)
    assert [s.name for s in t.sheets] == SHEET_NAMES
    assert t.sheet_columns("Ranked Investors") == RANKED_COLUMNS == [
        "Category", "Fit Score", "First Name", "Last Name", "Organization", "Email", "Phone", "Investor Type",
        "Location", "Why a fit", "TEN Relationship (Y/N)", "LinkedIn"]


def test_template_holds_no_run_data(samples):
    text = DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text)               # no email addresses
    assert not re.search(r"[$€£]\s?\d", text)                          # no money amounts
    assert not re.search(r"\b20\d\d\b", text)                          # no dates/years
    sample_terms = {"Cardiolyte", "Austin", "Pulse", "Hill Country", "Meridian", "SAFE", "Seed round"}
    assert not [term for term in sample_terms if re.search(rf"\b{re.escape(term)}\b", text)]


def test_invalid_templates_are_rejected():
    raw = json.loads(DEFAULT_TEMPLATE.read_text(encoding="utf-8"))
    broken = dict(raw, sections=[s for s in raw["sections"] if s["id"] != "top_contacts"])
    with pytest.raises(ValueError, match="missing sections"):
        ReportTemplate.model_validate(broken)
    small = dict(raw, page=dict(raw["page"], min_body_size_pt=8))
    with pytest.raises(ValueError, match="9 pt"):
        ReportTemplate.model_validate(small)


def test_fill_bullet_drops_empty_optional_segments():
    pattern = "{company_name}[[ ({legal_name})]] — {sector}"
    assert fill_bullet(pattern, {"company_name": "A", "legal_name": "A Inc.", "sector": "S"}, "A") == "A (A Inc.) — S"
    assert fill_bullet(pattern, {"company_name": "A", "legal_name": "not stated in deck", "sector": "S"}, "A") == "A — S"
    assert fill_bullet(pattern, {"company_name": "A", "legal_name": "A", "sector": "S"}, "A") == "A — S"


def test_blank_preview_is_one_page_of_placeholders_only():
    pdf = render_template_preview()
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        assert doc.page_count == 1
        text = doc[0].get_text()
    t = load_template()
    for section in t.sections:
        assert " ".join(section.title.split()) in " ".join(text.split())
    assert "[Company name]" in text and "[Contact name]" in text
    assert not re.search(r"[$€£]\s?\d|@\w", text)


def test_report_follows_template(sample_result):
    text = " ".join(pymupdf.open(stream=render_pdf(sample_result), filetype="pdf")[0].get_text().split())
    t = load_template()
    for section in t.sections:
        assert " ".join(section.title.split()) in text
    for label in (f["label"] for f in t.header["meta_fields"]):
        assert f"{label}:" in text
    assert t.header["eyebrow"] in text and t.footer["confidential_text"] in text


def test_markdown_spec_is_in_sync():
    assert MARKDOWN_PATH.read_text(encoding="utf-8") == render_markdown(), \
        "run `python -m app.reports.template` after editing the template"
