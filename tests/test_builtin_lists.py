"""Trusted built-in investor lists: discovery, subset sheets, and always-on unsubscribe sheets."""

from __future__ import annotations

import os
import time

from app.config import Settings
from app.extraction.deal_profile import extract_profile
from app.ingestion.mapping import ROLE_CONTACTS, ROLE_SKIP, ROLE_SUPPRESSION
from app.pipeline import builtin_suppression_tables, load_builtin_tables, load_tables, run_matching
from tests.conftest import DEFAULT_DECK, REPORT_DATE, ROOT
from tests.test_sheets import HEAD, row, workbook


def _write(folder, name, sheets, age_s=0):
    path = folder / name
    path.write_bytes(workbook(sheets))
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def _connect(settings):
    """Register every list in the folder with a fake Files API client."""
    from types import SimpleNamespace

    from app.services.files_api import sync_builtin_lists
    from tests.test_files_api import FakeFiles

    sync_builtin_lists(settings, SimpleNamespace(files=FakeFiles()))


def test_only_files_api_connected_lists_are_used(tmp_path):
    from app.services.files_api import connected_investor_lists

    connected = _write(tmp_path, "connected.xlsx", {"Master": [HEAD, row()],
                                                     "Unsubscribed": [["Email"], ["a@x.example"]]})
    settings = Settings(im_investor_lists_dir=tmp_path)
    _connect(settings)
    not_synced = _write(tmp_path, "dropped_in_later.xlsx", {"Master": [HEAD, row()],
                                                             "Unsubscribed": [["Email"], ["b@x.example"]]})
    assert connected_investor_lists(settings) == [connected]          # new file is not connected until synced
    assert not_synced in settings.builtin_investor_lists()
    sheets = {t.table.filename for t in builtin_suppression_tables(settings=settings)}
    assert sheets == {"connected.xlsx"}
    connected.write_bytes(workbook({"Master": [HEAD, row(Email="changed@x.example")]}))
    assert connected_investor_lists(settings) == []                   # a changed file must be re-synced


def test_builtin_lists_newest_first_and_default(tmp_path):
    old = _write(tmp_path, "old.xlsx", {"Master": [HEAD, row()]}, age_s=3600)
    new = _write(tmp_path, "new.xlsx", {"Master": [HEAD, row()]})
    (tmp_path / "~$new.xlsx").write_bytes(b"lock file")
    settings = Settings(im_investor_lists_dir=tmp_path, im_investor_list_path=None)
    assert settings.builtin_investor_lists() == [new, old]
    assert settings.default_investor_list() == new


def test_segment_sheets_that_repeat_the_master_are_skipped(tmp_path):
    master = [HEAD] + [row(Email=f"p{i}@x.example", **{"First Name": f"P{i}"}) for i in range(10)]
    segment = [HEAD] + master[1:4]
    path = _write(tmp_path, "segmented.xlsx", {"Master": master, "A-Priority": segment})
    roles = {t.table.sheet: (t.role, t.role_reason) for t in load_tables(path)}
    assert roles["Master"][0] == ROLE_CONTACTS
    assert roles["A-Priority"][0] == ROLE_SKIP and "Master" in roles["A-Priority"][1]


def test_unsubscribe_sheets_of_unselected_builtin_lists_still_apply(tmp_path, cfg):
    selected = _write(tmp_path, "selected.xlsx", {"Master": [HEAD, row(), row(Email="kim@z.example",
                                                                               **{"First Name": "Kim"})]})
    _write(tmp_path, "other.xlsx", {"Master": [HEAD, row(Email="zed@q.example")],
                                    "Unsubscribed": [["Email"], ["pat.lee@fund.example"]]}, age_s=60)
    settings = Settings(im_investor_lists_dir=tmp_path)
    _connect(settings)
    investors = load_builtin_tables(selected) + builtin_suppression_tables(exclude={selected}, settings=settings)
    assert [t.role for t in investors] == [ROLE_CONTACTS, ROLE_SUPPRESSION]
    result = run_matching(extract_profile(DEFAULT_DECK), investors, [], cfg, report_date=REPORT_DATE)
    assert [s.contact.email for s in result.ranked] == ["kim@z.example"]
    assert any(e.code == "SUPPRESSED" and "other.xlsx" in e.detail for e in result.log)


def test_every_suppression_style_column_is_honoured(tmp_path, cfg):
    head = HEAD + ["Unsubscribed", "Latest Status", "Engagement Status", "Do Not Contact", "Bounced"]
    rows = [
        row(Email="a@x.example") + ["", "UNSUB", "", "", ""],
        row(Email="b@x.example") + ["", "", "Unsubscribed — do not contact", "", ""],
        row(Email="c@x.example") + ["", "", "", "Y", ""],
        row(Email="d@x.example") + ["", "", "", "", "Yes"],
        row(Email="ok@x.example") + ["N", "ILF", "Prior intro made", "", "N"],
    ]
    path = _write(tmp_path, "master.xlsx", {"Master": [head] + rows})
    result = run_matching(extract_profile(DEFAULT_DECK), load_tables(path), [], cfg, report_date=REPORT_DATE)
    suppressed = {e.email for e in result.log if e.code == "SUPPRESSED"}
    assert suppressed == {"a@x.example", "b@x.example", "c@x.example", "d@x.example"}
    assert "ok@x.example" not in suppressed


def test_builtin_lists_ship_with_the_app_but_not_to_git():
    for name in (".railwayignore", ".dockerignore"):
        lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
        assert "data/*" in lines and "!data/investor_lists/" in lines
    assert "data/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
