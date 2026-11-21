"""Run history: saved runs, re-runs updating the same row, email marks, pruning and failure isolation."""

from __future__ import annotations

import copy

from pydantic import SecretStr

from app.config import Settings
from app.pipeline import output_names, render_outputs
from app.services import history


def _settings(tmp_path, keep=500):
    return Settings(database_url=SecretStr(f"sqlite:///{(tmp_path / 'h.db').as_posix()}"), im_history_max_runs=keep)


def test_postgres_urls_use_psycopg():
    assert history.normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert history.normalize_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert history.normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_off_without_database_url():
    s = Settings(database_url=None)
    assert not history.available(s)
    assert history.list_runs(settings=s) == []
    assert history.save_run(None, {}, settings=s) is None


def test_save_rerun_email_download_delete(sample_result, tmp_path):
    s = _settings(tmp_path)
    files = render_outputs(sample_result)
    pdf_name, xlsx_name = output_names(sample_result.context.company_name, sample_result.report_date)
    run_id = history.save_run(sample_result, files, settings=s)
    assert run_id
    assert history.save_run(sample_result, files, run_id, settings=s) == run_id      # re-run: same row
    runs = history.list_runs(settings=s)
    assert len(runs) == 1 and runs[0]["company"] == sample_result.context.company_name
    assert runs[0]["ranked"] == len(sample_result.ranked) and runs[0]["emailed_at"] is None
    history.mark_emailed(run_id, ["Info@tencapital.group"], settings=s)
    assert history.list_runs(settings=s)[0]["emailed_to"] == "Info@tencapital.group"
    assert history.get_files(run_id, settings=s) == {pdf_name: files[pdf_name], xlsx_name: files[xlsx_name]}
    assert history.delete_run(run_id, settings=s)
    assert history.list_runs(settings=s) == []


def test_oldest_runs_are_pruned(sample_result, tmp_path):
    s = _settings(tmp_path, keep=2)
    files = {"a.pdf": b"%PDF"}
    ids = [history.save_run(copy.deepcopy(sample_result), files, settings=s) for _ in range(3)]
    assert [r["id"] for r in history.list_runs(settings=s)] == ids[:0:-1]


def test_unreachable_database_never_breaks_a_run(sample_result):
    s = Settings(database_url=SecretStr("postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=1"))
    assert history.save_run(sample_result, {}, settings=s) is None
    assert history.list_runs(settings=s) is None
