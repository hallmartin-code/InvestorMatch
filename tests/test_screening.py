from __future__ import annotations

from app.models import Category, LogStatus
from app.pipeline import DECISION_INTRODUCED, DECISION_NEW
from tests.conftest import intro_input, investor, run


def codes(result, email):
    return {e.code for e in result.log if e.email.lower() == email.lower()}


def ranked_emails(result):
    return [s.contact.email for s in result.ranked]


# ---- suppression and duplicates

def test_suppression_applies_across_duplicates(cfg):
    rows = [investor(Email="Sam@Fund.example", **{"Email Status": "Subscribed"}),
            investor(Email="sam@fund.example", **{"Email Status": "Unsubscribed"})]
    r = run(cfg, rows)
    assert ranked_emails(r) == []
    assert "SUPPRESSED" in codes(r, "sam@fund.example")
    assert "DUPLICATE_MERGED" in codes(r, "sam@fund.example")


def test_duplicates_merge_by_email_and_fill_missing_fields(cfg):
    rows = [investor(Email="Ana@X.example", Phone=""), investor(Email="ana@x.example", Phone="+1 512 555 0100")]
    r = run(cfg, rows)
    assert len(r.ranked) == 1
    contact = r.ranked[0].contact
    assert contact.merged_count == 2 and contact.get("phone") == "+1 512 555 0100"
    assert len(contact.sources) == 2


def test_invalid_missing_and_generic_emails(cfg):
    rows = [investor(Email="bad@@x.example"), investor(Email="", **{"First Name": "No"}),
            investor(Email="info@angels.example", **{"First Name": "", "Last Name": ""})]
    r = run(cfg, rows)
    assert "INVALID_EMAIL" in codes(r, "bad@@x.example")
    assert any(e.code == "NO_EMAIL" for e in r.log)
    assert ranked_emails(r) == ["info@angels.example"]
    assert "GENERIC_INBOX" in codes(r, "info@angels.example")


# ---- prior introductions

def test_prior_intro_by_email_is_case_insensitive(cfg):
    intro = intro_input([{"Company": "Acme Cardio", "Investor Email": "PAT.LEE@FUND.EXAMPLE", "Intro Date": "2026-08-01"}])
    r = run(cfg, [investor()], [intro])
    assert ranked_emails(r) == []
    assert "ALREADY_INTRODUCED" in codes(r, "pat.lee@fund.example")
    assert r.already_introduced[0]["Status"] == "DO NOT RE-INTRO"
    assert r.already_introduced[0]["Introduction Date"] == "2026-08-01"


def test_prior_intro_by_normalized_name_and_org(cfg):
    intro = intro_input([{"Investor Name": "Lee, Pat", "Firm": "Fund A, LLC"}], "acme_cardio_intros.csv", True)
    r = run(cfg, [investor()], [intro])
    assert "ALREADY_INTRODUCED" in codes(r, "pat.lee@fund.example")


def test_ambiguous_matches_are_held_for_review(cfg):
    intros = intro_input([{"Company": "Acme Cardio", "Investor Name": "Pat Lee", "Firm": "Other Fund"},
                          {"Company": "Acme Cardio", "Firm": "Fund B"},
                          {"Company": "Acme Kardio", "Investor Email": "kim@c.example"}])
    rows = [investor(), investor(Email="jo@b.example", **{"First Name": "Jo", "Organization": "Fund B"}),
            investor(Email="kim@c.example", **{"First Name": "Kim", "Organization": "Fund C"})]
    r = run(cfg, rows, [intros])
    for email in ("pat.lee@fund.example", "jo@b.example", "kim@c.example"):
        assert "POSSIBLE_PRIOR_INTRO" in codes(r, email)
    assert ranked_emails(r) == []


def test_intro_file_without_company_column_is_ambiguous_unless_marked(cfg):
    rows = [{"Investor Email": "pat.lee@fund.example"}]
    r = run(cfg, [investor()], [intro_input(rows, "q3_intros.csv", company_specific=False)])
    assert "POSSIBLE_PRIOR_INTRO" in codes(r, "pat.lee@fund.example")
    assert any("name no company" in x for x in r.limitations)
    r = run(cfg, [investor()], [intro_input(rows, "q3_intros.csv", company_specific=True)])
    assert "ALREADY_INTRODUCED" in codes(r, "pat.lee@fund.example")


def test_review_decisions(cfg):
    intro = [intro_input([{"Company": "Acme Cardio", "Investor Name": "Pat Lee", "Firm": "Other"}])]
    r = run(cfg, [investor()], intro, intro_decisions={"pat.lee@fund.example": DECISION_NEW})
    assert ranked_emails(r) == ["pat.lee@fund.example"]
    r = run(cfg, [investor()], intro, intro_decisions={"pat.lee@fund.example": DECISION_INTRODUCED})
    assert "ALREADY_INTRODUCED" in codes(r, "pat.lee@fund.example")


def test_other_company_intro_is_not_exclusion(cfg):
    intro = intro_input([{"Company": "Ledger Co", "Investor Email": "pat.lee@fund.example"}])
    r = run(cfg, [investor()], [intro])
    assert ranked_emails(r) == ["pat.lee@fund.example"]


def test_missing_intro_files_is_a_limitation(cfg):
    r = run(cfg, [investor()])
    assert any("prior-introduction screening is incomplete" in x for x in r.limitations)


# ---- types, stage, geography

def test_excluded_and_ambiguous_types(cfg):
    rows = [investor(Email="pe@x.example", **{"Investor Type": "Private Equity"}),
            investor(Email="ib@x.example", **{"Investor Type": "Investment Bank"}),
            investor(Email="growth@x.example", **{"Investor Type": "Venture Capital", "Stage Focus": "Growth, Late stage"}),
            investor(Email="amb@x.example", **{"Investor Type": "Angel / VC"}),
            investor(Email="none@x.example", **{"Investor Type": ""})]
    r = run(cfg, rows)
    assert "EXCLUDED_PE" in codes(r, "pe@x.example")
    assert "EXCLUDED_BANK" in codes(r, "ib@x.example")
    assert "GROWTH_ONLY" in codes(r, "growth@x.example")
    assert "CATEGORY_REVIEW" in codes(r, "amb@x.example")
    assert "CATEGORY_REVIEW" in codes(r, "none@x.example")
    assert ranked_emails(r) == []


def test_explicit_incompatibility_excludes_but_unknown_does_not(cfg):
    rows = [investor(Email="a@x.example", **{"Stage Focus": "Series B"}),
            investor(Email="b@x.example", **{"Geographic Focus": "Europe"}),
            investor(Email="c@x.example", **{"Stage Focus": "", "Geographic Focus": ""})]
    r = run(cfg, rows)
    assert "STAGE_INCOMPATIBLE" in codes(r, "a@x.example")
    assert "GEO_INCOMPATIBLE" in codes(r, "b@x.example")
    unknown = next(s for s in r.scored if s.contact.email == "c@x.example")
    assert unknown.component("stage").rating == 0 and not unknown.component("stage").known
    assert "stage focus unknown" in unknown.component("stage").flags


def test_categories(cfg):
    rows = [investor(Email="1@x.example", Organization="Org 1", **{"Investor Type": "Angel Group"}),
            investor(Email="2@x.example", Organization="Org 2", **{"Investor Type": "Family Office"}),
            investor(Email="3@x.example", Organization="Org 3", **{"Investor Type": "Corporate VC"}),
            investor(Email="4@x.example", Organization="Org 4", **{"Investor Type": "Individual angel"})]
    r = run(cfg, rows)
    cats = {s.contact.email: s.category for s in r.ranked}
    assert cats == {"1@x.example": Category.ANGEL_GROUP, "2@x.example": Category.FAMILY_OFFICE,
                    "3@x.example": Category.VC, "4@x.example": Category.ANGEL}
    assert [s.category for s in r.ranked] == [Category.ANGEL, Category.ANGEL_GROUP, Category.FAMILY_OFFICE, Category.VC]


# ---- ordering and organization cap

def test_ordering_and_org_cap(cfg):
    rows = [investor(Email=f"p{i}@big.example", Organization="Big Fund", **{
        "First Name": f"P{i}", "Sector Focus": "Digital Therapeutics" if i < 2 else "Healthcare"}) for i in range(5)]
    rows.append(investor(Email="solo@x.example", Organization="Small", **{"Sector Focus": "Healthcare",
                                                                          "Geographic Focus": ""}))
    r = run(cfg, rows)
    big = [s for s in r.ranked if s.contact.organization == "Big Fund"]
    assert len(big) == 3
    assert sum(1 for e in r.log if e.code == "ORG_CAP") == 2
    scores = [s.fit_score for s in r.ranked]
    assert scores == sorted(scores, reverse=True)
    assert [s.rank for s in r.ranked] == list(range(1, len(r.ranked) + 1))


def test_below_threshold_is_logged(cfg):
    r = run(cfg, [investor(**{"Sector Focus": "Fintech", "Stage Focus": "", "Check Size": "",
                              "Geographic Focus": ""})])
    assert ranked_emails(r) == []
    assert "BELOW_THRESHOLD" in codes(r, "pat.lee@fund.example")


def test_sample_run_counts(sample_result):
    r = sample_result
    assert r.stats["suppressed"] >= 2
    assert {e.code for e in r.log} >= {"ALREADY_INTRODUCED", "POSSIBLE_PRIOR_INTRO", "ORG_CAP", "EXCLUDED_PE",
                                        "EXCLUDED_BANK", "GROWTH_ONLY", "STAGE_INCOMPATIBLE", "GEO_INCOMPATIBLE",
                                        "INVALID_EMAIL", "DUPLICATE_MERGED", "GENERIC_INBOX", "CATEGORY_REVIEW"}
    assert all(s.fit_score >= 5.0 for s in r.ranked)
    assert sum(1 for s in r.ranked if s.contact.organization == "Pulse Ventures") == 3
    assert not {s.contact.email for s in r.ranked} & {row["Email"].lower() for row in r.already_introduced}
    assert all(e.status != LogStatus.REVIEW or e.email not in {s.contact.email for s in r.ranked} for e in r.log)
