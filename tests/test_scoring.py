from __future__ import annotations

from app.extraction.deal_profile import build_context, extract_profile
from app.models import Contact
from app.screening.scoring import parse_attributes, round_score, score_contact
from tests.conftest import DEFAULT_DECK


def contact(**values) -> Contact:
    return Contact(email="x@y.example", email_display="x@y.example", first_name="X", last_name="Y",
                   organization="Org", values=values, sources=[])


def score(cfg, **values):
    ctx = build_context(extract_profile(DEFAULT_DECK))
    c = contact(**values)
    return score_contact(c, parse_attributes(c), ctx, None, cfg)


FULL = dict(sector_focus="Digital Therapeutics", stage_focus="Seed", check_size="$25K-$100K", geo_focus="Texas",
            ten_core="Yes", ten_events="TEN Summit", ten_similar_intros="2")


def test_weights_and_perfect_score(cfg):
    s = score(cfg, **FULL)
    assert [c.rating for c in s.components] == [10, 10, 10, 10, 10]
    assert s.fit_score == 10.0 and s.evidence_completeness == 1.0
    assert s.ten_relationship == "Y"


def test_niche_beats_broad_beats_generalist(cfg):
    niche = score(cfg, **{**FULL, "sector_focus": "Cardiovascular"}).component("sector").rating
    broad = score(cfg, **{**FULL, "sector_focus": "Healthcare"}).component("sector").rating
    adjacent = score(cfg, **{**FULL, "sector_focus": "Diagnostics"}).component("sector").rating
    generalist = score(cfg, **{**FULL, "sector_focus": "Generalist"}).component("sector").rating
    outside = score(cfg, **{**FULL, "sector_focus": "Fintech"}).component("sector").rating
    assert niche > broad > adjacent > generalist > outside == 0


def test_unknowns_earn_zero_and_are_flagged(cfg):
    s = score(cfg, sector_focus="Digital Therapeutics")
    assert s.evidence_completeness == 0.2
    for key in ("stage", "check_size", "geography", "ten_relationship"):
        comp = s.component(key)
        assert comp.rating == 0 and not comp.known and comp.flags
    assert s.ten_relationship == "needs research"
    assert s.fit_score == 4.5


def test_check_size_uses_remaining_and_participation(cfg):
    remaining = 1_500_000  # $2M raise − $500K committed
    assert score(cfg, **{**FULL, "check_size": "$2M-$3M"}).component("check_size").rating == 0
    assert score(cfg, **{**FULL, "check_size": "$10K"}).component("check_size").rating == 6
    solo = score(cfg, **{**FULL, "participation": "Lead only"}).component("check_size")
    assert solo.rating == 4 and "does not co-invest" in solo.evidence
    fits = score(cfg, **FULL).component("check_size")
    assert "remaining" in fits.evidence and remaining == 1_500_000


def test_geography_inference_is_labeled(cfg):
    comp = score(cfg, **{**FULL, "geo_focus": "", "location": "Dallas, TX"}).component("geography")
    assert comp.rating == 4 and comp.inferred and not comp.known


def test_ten_relationship_flags(cfg):
    assert score(cfg, **{**FULL, "ten_core": "No", "ten_events": "0", "ten_similar_intros": "0"}).ten_relationship == "N"
    assert score(cfg, **{**FULL, "ten_core": "", "ten_events": "", "ten_similar_intros": ""}).ten_relationship == "needs research"


def test_rounding_half_up():
    assert round_score(7.25) == 7.3 and round_score(7.249) == 7.2
