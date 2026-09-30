"""Claude cross-check logic, with a fake client (no network)."""

from __future__ import annotations

from app.extraction.deal_profile import extract_profile
from app.extraction.llm import augment_profile
from app.models import FactStatus, Money
from tests.conftest import make_deck

DECK = make_deck(
    "Acme Cardio\nInvestor presentation",
    "Headquartered in Austin, Texas. Digital therapeutics for cardiac rehab.",
    "Raising $2M Seed round on a SAFE\n$500K committed from angels\nFinal commitments due Q4 2026",
)


class FakeClient:
    model = "fake-model"

    def __init__(self, facts):
        self.facts = facts
        self.user = ""

    def extract(self, system, user):
        self.user = user
        return {"facts": self.facts}


def fact(field, value, slide, quote):
    return {"field": field, "value": value, "slide": slide, "quote": quote}


def test_confirms_fills_and_flags_conflicts():
    profile = extract_profile(DECK)
    assert profile.facts["target_close_date"].status == FactStatus.NOT_STATED
    client = FakeClient([
        fact("raise_amount", "$2M", 3, "Raising $2M Seed round on a SAFE"),                 # confirms
        fact("target_close_date", "Q4 2026", 3, "Final commitments due Q4 2026"),                     # fills
        fact("stage", "Series A", 3, "Raising $2M Seed round on a SAFE"),                   # disagrees → conflict
        fact("soft_interest", "$900K", 3, "Invented quote that is not on the slide"),       # ungrounded → dropped
    ])
    augment_profile(profile, DECK, client)
    f = profile.facts
    assert f["raise_amount"].status == FactStatus.STATED and f["raise_amount"].value == Money(2_000_000)
    assert "Confirmed by Claude" in " ".join(f["raise_amount"].notes)
    assert f["target_close_date"].status == FactStatus.STATED and f["target_close_date"].display == "Q4 2026"
    assert f["target_close_date"].sources[0].locator == "slide 3"
    assert f["stage"].status == FactStatus.CONFLICT
    assert f["soft_interest"].status == FactStatus.NOT_STATED
    assert "1 ungrounded" in profile.extraction_log[-1]
    assert "<deck>" in client.user and client.user.rstrip().endswith("</deck>")


def test_numbers_must_appear_in_quote_and_remaining_is_recalculated():
    deck = make_deck("Raising $3M Seed round", "Angels have signed $1M toward this round")
    profile = extract_profile(deck)
    profile.facts["amount_committed"].status = FactStatus.NOT_STATED   # simulate the rules missing it
    profile.facts["amount_committed"].value = None
    profile.facts["amount_remaining"].status = FactStatus.NOT_STATED
    augment_profile(profile, deck, FakeClient([
        fact("amount_committed", "$1M signed", 2, "Angels have signed $1M toward this round"),
        fact("raise_amount", "$5M", 1, "Raising $3M Seed round"),                            # number not in quote
    ]))
    assert profile.facts["amount_committed"].detail["commitment_type"] == "signed"
    assert profile.facts["raise_amount"].value == Money(3_000_000)
    assert profile.facts["amount_remaining"].value == Money(2_000_000)
    assert profile.facts["amount_remaining"].status == FactStatus.CALCULATED
