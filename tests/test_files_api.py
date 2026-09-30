"""Files API sync and Claude review of held contacts — fake clients, no network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.extraction.deal_profile import extract_profile
from app.models import Category
from app.pipeline import load_builtin_tables, run_matching
from app.services import claude_review
from app.services.files_api import file_id_for, load_registry, sync_builtin_lists
from tests.conftest import DEFAULT_DECK, REPORT_DATE
from tests.test_sheets import HEAD, row, workbook


class FakeFiles:
    def __init__(self):
        self.uploads, self.known = [], set()

    def upload(self, file):
        name, handle, mime = file
        fid = f"file_{len(self.uploads) + 1:03d}"
        self.uploads.append((name, len(handle.read()), mime))
        self.known.add(fid)
        return SimpleNamespace(id=fid)

    def retrieve_metadata(self, fid):
        if fid not in self.known:
            raise RuntimeError("404")
        return SimpleNamespace(id=fid)


@pytest.fixture
def lists_dir(tmp_path):
    held = row(Email="held@x.example", **{"First Name": "Hal", "Investor Type": "", "Organization": "Hal Fund"})
    held[HEAD.index("Investor Type")] = ""
    rows = [HEAD + ["Profile"], row() + ["Angel investor in Texas"], held + ["Member of the Austin angel group network"],
            row(Email="nope@x.example", **{"First Name": "Nop", "Investor Type": ""}) + ["Consultant"]]
    rows[3][HEAD.index("Investor Type")] = ""
    (tmp_path / "master.xlsx").write_bytes(workbook({"Master": rows}))
    return tmp_path


def settings_for(folder, **kw):
    return Settings(im_investor_lists_dir=folder, anthropic_api_key="sk-test", im_llm_enabled=True, **kw)


def test_sync_uploads_once_and_reuploads_changed_files(lists_dir):
    client = SimpleNamespace(files=FakeFiles())
    settings = settings_for(lists_dir)
    registry = sync_builtin_lists(settings, client)
    assert list(registry) == ["master.xlsx"] and len(client.files.uploads) == 1
    assert client.files.uploads[0][2].endswith("spreadsheetml.sheet")
    sync_builtin_lists(settings, client)                       # unchanged: no new upload
    assert len(client.files.uploads) == 1
    assert file_id_for(lists_dir / "master.xlsx", settings) == "file_001"
    (lists_dir / "master.xlsx").write_bytes((lists_dir / "master.xlsx").read_bytes() + b"")  # same bytes
    (lists_dir / "master.xlsx").write_bytes(workbook({"Master": [HEAD, row()]}))           # changed content
    assert file_id_for(lists_dir / "master.xlsx", settings) is None
    sync_builtin_lists(settings, client)
    assert len(client.files.uploads) == 2 and load_registry(settings)["master.xlsx"]["file_id"] == "file_002"


class FakeMessages:
    def __init__(self, suggestions):
        self.suggestions, self.calls = suggestions, []

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps({"suggestions": self.suggestions})
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def test_review_verifies_quotes_and_suggestions_need_acceptance(lists_dir, cfg):
    settings = settings_for(lists_dir)
    sync_builtin_lists(settings, SimpleNamespace(files=FakeFiles()))
    tables = load_builtin_tables(lists_dir / "master.xlsx")
    profile = extract_profile(DEFAULT_DECK)
    result = run_matching(profile, tables, [], cfg, report_date=REPORT_DATE)
    held = {s.contact.email for s in result.scored if s.status == "Review: category"}
    assert "held@x.example" in held

    candidates = claude_review._candidates(result, settings, tables)
    ids = {c["scored"].contact.email: i for i, c in enumerate(candidates)}
    fake = FakeMessages([
        {"id": ids["held@x.example"], "category": Category.ANGEL_GROUP.value, "column": "Profile",
         "evidence": "Austin angel group network"},
        *([{"id": ids["nope@x.example"], "category": Category.VC.value, "column": "Profile",
            "evidence": "Leading seed VC fund"}] if "nope@x.example" in ids else []),
    ])
    accepted = claude_review.review_held_contacts(result, tables, settings, client=SimpleNamespace(beta=SimpleNamespace(messages=fake)))

    call = fake.calls[0]
    assert {"type": "container_upload", "file_id": "file_001"} in call["messages"][0]["content"]
    assert call["tools"][0]["type"].startswith("code_execution")
    assert [s.email for s in accepted] == ["held@x.example"]            # fabricated quote discarded
    assert accepted[0].category == Category.ANGEL_GROUP and accepted[0].rule_check == "agrees"
    assert "held@x.example" not in {s.contact.email for s in result.ranked}   # never auto-ranked
    entry = next(e for e in result.log if e.code == "CATEGORY_REVIEW" and e.email == "held@x.example")
    assert "Suggested by Claude" in entry.detail
    assert any("Files API" in x for x in result.limitations)

    rerun = run_matching(profile, tables, [], cfg, report_date=REPORT_DATE,
                         category_overrides={"held@x.example": Category.ANGEL_GROUP.value})
    ranked = {s.contact.email: s.category for s in rerun.ranked}
    assert ranked.get("held@x.example") == Category.ANGEL_GROUP
    assert any(e.code == "CATEGORY_ACCEPTED" for e in rerun.log)


def test_review_skips_without_file_ids(lists_dir, cfg):
    settings = settings_for(lists_dir)
    tables = load_builtin_tables(lists_dir / "master.xlsx")
    result = run_matching(extract_profile(DEFAULT_DECK), tables, [], cfg, report_date=REPORT_DATE)
    assert claude_review.review_held_contacts(result, tables, settings, client=object()) == []
    assert not claude_review.is_available(settings)
