"""Review-screen helpers, email timing and PDF wording from the second usability round."""

from __future__ import annotations

import copy

from streamlit.testing.v1 import AppTest

from app.models import Candidate, Contact, SourceRef
from app.reports.pdf_report import data_from_result
from app.screening import review
from app.utils.text import clean_cell, repair_mojibake
from tests.conftest import ROOT


def _contact(first="Ann", last="Lee", generic=False):
    return Contact(email="a@x.com", email_display="a@x.com", first_name=first, last_name=last, organization="X",
                   values={}, sources=[], generic_inbox=generic)


def test_mojibake_repaired_and_clean_text_untouched():
    assert clean_cell("Paris, ÃŽle-de-France") == "Paris, Île-de-France"
    assert repair_mojibake("MÃ¼nchen") == "München"
    for ok in ("Café", "São Paulo", "naïve – ok", "Zürich"):
        assert repair_mojibake(ok) == ok


def test_contact_notes():
    assert review.contact_note(_contact(generic=True)) == "general inbox"
    assert review.contact_note(_contact(last="w")) == "incomplete name"
    assert review.contact_note(_contact(first="")) == "incomplete name"
    assert review.contact_note(_contact()) == ""


def test_unmapped_score_fields_flags_ten_relationship():
    weights = {"sector": .45, "stage": .15, "check_size": .15, "geography": .15, "ten_relationship": .10}
    mapping = {"sector_focus": "Sector", "stage_focus": "Stage", "check_size": "Check", "geo_focus": "Geo"}
    missing = review.unmapped_score_fields(mapping, weights)
    assert [m["key"] for m in missing] == ["ten_relationship"]
    assert missing[0]["weight"] == .10
    assert not review.unmapped_score_fields({**mapping, "ten_core": "Core"}, weights)


def test_likely_candidate_prefers_value_repeated_in_deck():
    src = SourceRef(file="d.pptx", locator="slide 1")
    cands = [Candidate("Hearts made simple", "Hearts made simple", src), Candidate("CardioLyte", "CardioLyte", src)]
    text = "CardioLyte Health ... CardioLyte raises ... Hearts made simple"
    assert review.likely_candidate(cands, text, "cardiolyte_deck.pptx") == 1


def test_held_breakdown_and_projected_rank(sample_result):
    held = review.held_breakdown(sample_result)
    assert sum(n for _, n in held) == sum(1 for e in sample_result.log if e.status.value == "REVIEW")
    rows = review.held_rows(sample_result, limit=20)
    assert len(rows) <= 20
    assert all(rows[i]["Projected fit"] >= rows[i + 1]["Projected fit"] for i in range(len(rows) - 1))
    assert review.projected_rank(11.0, sample_result.ranked) == 1


def test_pdf_has_no_internal_citations_and_location_label(sample_result):
    data = data_from_result(sample_result, "book.xlsx")
    assert not any("[" in b for b in data.bullets)
    assert not any(b.startswith("Company:") for b in data.bullets)
    for _, rows in data.groups:
        assert all("…" not in r.why for r in rows)
        named = [not r.generic for r in rows]
        assert named == sorted(named, reverse=True)      # named contacts before general inboxes


def test_matching_never_emails_until_finalized(sample_result, sample_deck, monkeypatch):
    """Reaching the Review and Export steps sends nothing; only 'Finalize & email' calls deliver_results."""
    from app import pipeline

    calls = []
    monkeypatch.setattr(pipeline, "deliver_results", lambda *a, **k: calls.append(a))
    at = AppTest.from_file(str(ROOT / "app" / "app.py"), default_timeout=120)
    at.run()
    at.session_state["profile"] = sample_result.deal
    at.session_state["deck"] = sample_deck
    at.session_state["result"] = copy.deepcopy(sample_result)
    for step in (3, 4):
        at.session_state["step"] = step
        at.run()
        assert not at.exception
    assert calls == []


def test_scoring_fields_unmapped_counted_per_field():
    mapping = {"sector_focus": "S", "stage_focus": "St", "check_min": "Min", "geo_focus": "G"}
    assert review.unmapped_scoring_columns(mapping) == ["thesis", "ten_core", "ten_events", "ten_similar_intros"]
    assert "check_size" in review.unmapped_scoring_columns({})


def test_placeholder_organization_is_flagged():
    c = _contact()
    c.organization = "#Angels"
    assert review.contact_note(c) == "check organization"
    c.organization = "Alliance of Angels"
    assert review.contact_note(c) == ""


def test_small_text_meets_wcag_aa_on_every_panel():
    from app import ui_theme as ui

    def luminance(colour):
        channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in channels)
        return .2126 * r + .7152 * g + .0722 * b

    for ink in (ui.INK_300, ui.INK_500, ui.INK_600):
        for panel in (ui.NAVY_950, ui.NAVY_900, ui.NAVY_800, ui.NAVY_700):
            assert (luminance(ink) + .05) / (luminance(panel) + .05) >= 4.5, (ink, panel)


def test_suggestions_offer_accept_all_and_hide_selected_until_ticked(sample_result, sample_deck):
    from app.models import Category
    from app.services.claude_review import Suggestion

    result = copy.deepcopy(sample_result)
    result.category_suggestions = [
        Suggestion("a@x.com", "Ann Lee", "X", Category.VC, "Notes", "invests at seed", 6.5, "agrees"),
        Suggestion("b@x.com", "Bo Ray", "Y", Category.ANGEL, "Notes", "family office", 5.5, "differs"),
    ]
    at = AppTest.from_file(str(ROOT / "app" / "app.py"), default_timeout=120)
    at.run()
    at.session_state["profile"] = result.deal
    at.session_state["deck"] = sample_deck
    at.session_state["result"] = result
    at.session_state["step"] = 3
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Accept all 1 verified and re-run" in labels
    assert not any("selected" in x for x in labels)
