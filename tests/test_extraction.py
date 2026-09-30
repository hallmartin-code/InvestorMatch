from __future__ import annotations

import pytest

from app.extraction.deal_profile import build_context, extract_profile, make_override
from app.extraction.parsing import parse_check
from app.models import FactStatus, Money, NOT_STATED_TEXT
from app.pipeline import load_deck
from tests.conftest import make_deck


def test_sample_deck_facts_with_slide_references(sample_deck):
    p = extract_profile(sample_deck)
    f = p.facts
    assert f["company_name"].value == "Cardiolyte Health"
    assert f["legal_name"].value == "Cardiolyte Health, Inc."
    assert f["stage"].value == "Seed"
    assert f["instrument"].value == "Post-money SAFE"
    assert f["raise_amount"].value == Money(2_500_000, "USD")
    assert f["raise_amount"].sources[0].locator == "slide 9"
    assert f["amount_committed"].value == Money(1_100_000, "USD")
    assert f["amount_committed"].detail["commitment_type"] == "signed"
    assert f["soft_interest"].value == Money(400_000, "USD")
    assert f["company_geography"].value.state == "TX"
    assert f["deck_date"].display == "October 2026"
    assert "Cardiovascular" in f["subsector"].value


def test_remaining_is_calculated_and_soft_interest_not_subtracted(sample_deck):
    rem = extract_profile(sample_deck).facts["amount_remaining"]
    assert rem.status == FactStatus.CALCULATED
    assert rem.value == Money(1_400_000, "USD")          # 2.5M − 1.1M signed; the 400K soft is not subtracted
    assert "(calculated)" in rem.display


def test_conflicting_close_dates_are_flagged_not_chosen(sample_deck):
    close = extract_profile(sample_deck).facts["target_close_date"]
    assert close.status == FactStatus.CONFLICT
    assert close.value is None
    assert {c.source.locator for c in close.candidates} == {"slide 9", "slide 11 (table)"}


def test_future_round_and_prior_raise_are_ignored(sample_deck):
    p = extract_profile(sample_deck)
    assert p.facts["raise_amount"].status == FactStatus.STATED         # $8M Series A and $750K pre-seed ignored
    assert any("future-round" in line for line in p.extraction_log)


def test_image_only_slide_is_ocrd(sample_deck):
    from app.ingestion import ocr

    if not ocr.available():
        pytest.skip("rapidocr not installed")
    assert 5 in sample_deck.ocr_pages
    assert "412 patients" in sample_deck.pages[4].ocr_text


def test_pdf_and_pptx_agree(samples, cfg, sample_deck):
    pdf = extract_profile(load_deck(samples / "cardiolyte_health_deck.pdf", cfg))
    pptx = extract_profile(sample_deck)
    for name in ("raise_amount", "amount_committed", "amount_remaining", "stage", "company_geography"):
        assert pdf.facts[name].display == pptx.facts[name].display
    assert pdf.facts["target_close_date"].status == FactStatus.CONFLICT


def test_missing_fields_are_marked_not_stated():
    p = extract_profile(make_deck("Widget Co\nWe make widgets"))
    for name in ("raise_amount", "stage", "instrument", "target_close_date", "amount_remaining"):
        assert p.facts[name].status == FactStatus.NOT_STATED
        assert p.facts[name].display == NOT_STATED_TEXT


def test_conflicting_raise_amounts():
    p = extract_profile(make_deck("Raising $2M Seed", "The ask: raising $3M Seed round"))
    assert p.facts["raise_amount"].status == FactStatus.CONFLICT
    assert p.facts["amount_remaining"].status == FactStatus.NOT_STATED


@pytest.mark.parametrize("pages, reason", [
    (("Raising $2M Seed round", "Series A investors: €500K committed"), "currenc"),
    (("Raising $2M Seed round", "$500K committed to our pre-seed round"), "refers to"),
    (("Raising $2M Seed round", "Angels: $500K committed"), "does not tie"),
])
def test_remaining_not_calculated_without_same_round_currency(pages, reason):
    p = extract_profile(make_deck(*pages))
    rem = p.facts["amount_remaining"]
    assert rem.status == FactStatus.NOT_STATED
    assert any(reason in n for n in rem.notes)


def test_soft_interest_is_separate_from_commitments():
    p = extract_profile(make_deck("Raising $2M Seed: $600K soft-circled, $400K committed"))
    assert p.facts["soft_interest"].value.amount == 600_000
    assert p.facts["amount_committed"].value.amount == 400_000
    assert p.facts["amount_committed"].detail["commitment_type"] == "committed (signing status not stated)"
    assert p.facts["amount_remaining"].value.amount == 1_600_000


def test_overrides_are_stored_separately(sample_deck):
    p = extract_profile(sample_deck)
    p.overrides["target_close_date"] = make_override(p, "target_close_date", "December 15, 2026", "founder confirmed")
    assert p.facts["target_close_date"].status == FactStatus.CONFLICT      # deck fact unchanged
    assert p.effective_display("target_close_date") == "December 15, 2026"
    p.overrides["amount_committed"] = make_override(p, "amount_committed", "$1.5M", "update")
    ctx = build_context(p)
    assert ctx.remaining == Money(1_000_000, "USD")
    assert ctx.remaining_basis == "calculated from corrected values"
    with pytest.raises(ValueError):
        make_override(p, "stage", "Series Z")


def test_check_size_parsing():
    assert (parse_check("$25K–$100K").minimum, parse_check("$25K–$100K").maximum) == (25_000, 100_000)
    assert parse_check("up to $250K").minimum is None
    assert parse_check("$1M+").maximum is None
    assert parse_check("€100K–€500K").currency == "EUR"


def test_legacy_ppt_without_libreoffice_gives_instruction(tmp_path, cfg, monkeypatch):
    from app.errors import UnsupportedFormatError
    from app.ingestion import deck as deck_mod

    monkeypatch.setattr(deck_mod, "find_soffice", lambda: None)
    path = tmp_path / "old.ppt"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)
    with pytest.raises(UnsupportedFormatError, match="LibreOffice"):
        load_deck(path, cfg)
