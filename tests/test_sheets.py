"""Multi-sheet investor workbooks: unsubscribe sheets, headerless sheets, skipped sheets, real-data vocab."""

from __future__ import annotations

import io

from openpyxl import Workbook

from app.extraction.deal_profile import extract_profile
from app.ingestion.mapping import ROLE_CONTACTS, ROLE_SKIP, ROLE_SUPPRESSION
from app.pipeline import load_tables, run_matching
from app.screening.categorize import categorize
from app.screening.scoring import incompatibility, parse_attributes
from app.extraction.deal_profile import build_context
from tests.conftest import DEFAULT_DECK, REPORT_DATE, investor


def workbook(sheets: dict[str, list[list[str]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEAD = list(investor().keys()) + ["Alternative Emails"]


def row(**kw) -> list[str]:
    values = investor(**kw)
    return [values[k] for k in HEAD[:-1]] + [kw.get("alt", "")]


def core_workbook() -> bytes:
    return workbook({
        "Core List": [HEAD, row(), row(Email="ann@x.example", **{"First Name": "Ann"}, alt="ann.alt@y.example"),
                      row(Email="kim@z.example", **{"First Name": "Kim"})],
        # headerless unsubscribe sheet, exactly like the real "Core unsubs" tab
        "Core unsubs": [["Core Dash", "Org", "Pat", "Lee", "pat.lee@fund.example", "", "Unsub"],
                        ["Core Dash", "Org", "X", "Y", "ANN.ALT@Y.example", "", "Unsub"]],
        "Notes": [["Some", "free"], ["text", "here"]],
    })


def test_roles_are_detected_and_headerless_first_row_is_kept():
    tables = {t.table.sheet: t for t in load_tables(data=core_workbook(), filename="core.xlsx")}
    assert tables["Core List"].role == ROLE_CONTACTS
    unsubs = tables["Core unsubs"]
    assert unsubs.role == ROLE_SUPPRESSION and len(unsubs.table.rows) == 2   # first row is data, not headers
    assert unsubs.table.columns[0] == "Column 1" and unsubs.table.warnings
    assert tables["Notes"].role == ROLE_SKIP


def test_unsubscribe_sheet_suppresses_primary_and_alternative_emails(cfg):
    tables = load_tables(data=core_workbook(), filename="core.xlsx")
    result = run_matching(extract_profile(DEFAULT_DECK), tables, [], cfg, report_date=REPORT_DATE)
    suppressed = {e.email.lower(): e.detail for e in result.log if e.code == "SUPPRESSED"}
    assert set(suppressed) == {"pat.lee@fund.example", "ann@x.example"}          # ann matched via alternative email
    assert all("unsubscribe list" in d and "Core unsubs" in d for d in suppressed.values())
    assert [s.contact.email for s in result.ranked] == ["kim@z.example"]
    assert any("was not used" in x and "Notes" in x for x in result.limitations)
    assert any("unsubscribe sheet" in x for x in result.limitations)


def test_real_vocabulary():
    from app.models import Contact

    def contact(**values):
        return Contact(email="a@b.example", email_display="a@b.example", first_name="A", last_name="B",
                       organization="O", values=values, sources=[])

    assert categorize(contact(investor_type="Family Investment Office")).category.value == "HNI & Family Offices"
    attrs = parse_attributes(contact(ten_core="Keiretsu"))
    assert attrs.ten.core and attrs.ten.core_text == "Keiretsu"
    assert parse_attributes(contact(ten_core="No")).ten.core is False


def test_description_adds_evidence_but_never_excludes():
    from app.models import Contact

    ctx = build_context(extract_profile(DEFAULT_DECK))
    c = Contact(email="a@b.example", email_display="a@b.example", first_name="A", last_name="B", organization="O",
                values={"description": "Growth-stage investor based in Europe; writes checks of $2M-$5M in fintech."},
                sources=[])
    attrs = parse_attributes(c)
    assert {"stage", "geography", "check_size", "sector"} <= attrs.from_description
    assert incompatibility(attrs, ctx) is None      # free text is evidence, not a stated exclusion rule
