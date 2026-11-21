"""Run history: every completed matching run is saved with its PDF and workbook so past shortlists can be
reopened and downloaded later.

Storage is any SQLAlchemy database named by ``DATABASE_URL``: Railway's Postgres in production (Railway sets
the variable when the Postgres service is referenced), or e.g. ``sqlite:///history.db`` locally. Without
``DATABASE_URL`` the feature is off and the app behaves exactly as before.

One analysis (a deck upload) is one row: re-running after accepting suggestions or resolving introductions
updates that row instead of adding new ones, and "Finalize & email" records when it was emailed.
History problems never break a run: every function logs and returns None / [] on database errors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from app.config import APP_VERSION, Settings, get_settings
from app.utils.logging import get_logger

LOGGER = get_logger(__name__)


def normalize_url(url: str) -> str:
    """Railway and Heroku style 'postgres://' / 'postgresql://' URLs → the psycopg 3 driver."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def available(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.database_url and settings.database_url.get_secret_value().strip())


@lru_cache(maxsize=4)
def _store(url: str):
    from sqlalchemy import (
        Column,
        DateTime,
        Integer,
        LargeBinary,
        MetaData,
        String,
        Table,
        Text,
        create_engine,
    )

    engine = create_engine(normalize_url(url), pool_pre_ping=True, future=True)
    meta = MetaData()
    runs = Table(
        "im_runs", meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("company", String(300), nullable=False, default=""),
        Column("deck_file", String(500), nullable=False, default=""),
        Column("report_date", String(10), nullable=False, default=""),
        Column("investor_lists", Text, nullable=False, default=""),
        Column("ranked", Integer, nullable=False, default=0),
        Column("held", Integer, nullable=False, default=0),
        Column("introduced", Integer, nullable=False, default=0),
        Column("generation", String(32), nullable=False, default=""),
        Column("emailed_at", DateTime(timezone=True), nullable=True),
        Column("emailed_to", Text, nullable=True),
        Column("app_version", String(40), nullable=False, default=""),
        Column("pdf_name", String(300), nullable=False, default=""),
        Column("pdf", LargeBinary, nullable=True),
        Column("xlsx_name", String(300), nullable=False, default=""),
        Column("xlsx", LargeBinary, nullable=True),
    )
    meta.create_all(engine, checkfirst=True)
    return engine, runs


class _Unreachable:
    """Stands in for the store when the database cannot be reached (already logged)."""


def _get(settings: Settings | None):
    """(engine, table), None when history is off, or _Unreachable when the database fails."""
    settings = settings or get_settings()
    if not available(settings):
        return None
    try:
        return _store(settings.database_url.get_secret_value())
    except Exception:  # noqa: BLE001 - e.g. Postgres down or wrong URL; lru_cache does not keep failures
        LOGGER.exception("Run history database unreachable")
        return _Unreachable


def _summary(result) -> dict[str, Any]:
    from app.reports.frames import summary_counts
    from app.services.notifications import generation_key

    counts = summary_counts(result)
    lists = sorted({f["File"] for f in result.input_files if f["Role"].startswith("TEN Capital Investor List")
                    and "Investor contacts" in f["Role"]})
    return {"company": (result.context.company_name or "")[:300], "deck_file": (result.deal.deck_file or "")[:500],
            "report_date": result.report_date.isoformat(), "investor_lists": "; ".join(lists),
            "ranked": counts["qualified_total"], "held": counts["review"],
            "introduced": counts["already_introduced"], "generation": generation_key(result),
            "app_version": APP_VERSION}


def save_run(result, files: dict[str, bytes], run_id: int | None = None,
             settings: Settings | None = None) -> int | None:
    """Insert this run (or update ``run_id``, the same analysis re-run). Returns the row id."""
    from sqlalchemy import insert, update

    from app.pipeline import output_names

    store = _get(settings)
    if store in (None, _Unreachable):
        return None
    engine, runs = store
    pdf_name, xlsx_name = output_names(result.context.company_name, result.report_date)
    now = datetime.now(UTC)
    values = {**_summary(result), "updated_at": now, "pdf_name": pdf_name, "pdf": files.get(pdf_name),
              "xlsx_name": xlsx_name, "xlsx": files.get(xlsx_name)}
    try:
        with engine.begin() as conn:
            if run_id is not None:
                changed = conn.execute(update(runs).where(runs.c.id == run_id).values(**values)).rowcount
                if changed:
                    _prune(conn, runs, settings)
                    return run_id
            new_id = conn.execute(insert(runs).values(created_at=now, **values)).inserted_primary_key[0]
            _prune(conn, runs, settings)
            return int(new_id)
    except Exception:  # noqa: BLE001 - history must never break a run
        LOGGER.exception("Could not save the run to history")
        return None


def _prune(conn, runs, settings: Settings | None) -> None:
    """Keep the newest IM_HISTORY_MAX_RUNS runs (0 = keep everything)."""
    from sqlalchemy import delete, select

    keep = (settings or get_settings()).im_history_max_runs
    if keep and keep > 0:
        newest = select(runs.c.id).order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(keep)
        conn.execute(delete(runs).where(runs.c.id.not_in(newest.scalar_subquery())))


def mark_emailed(run_id: int | None, recipients: list[str], settings: Settings | None = None) -> None:
    from sqlalchemy import update

    store = _get(settings)
    if store in (None, _Unreachable) or run_id is None:
        return
    engine, runs = store
    try:
        with engine.begin() as conn:
            conn.execute(update(runs).where(runs.c.id == run_id)
                         .values(emailed_at=datetime.now(UTC), emailed_to=", ".join(recipients)))
    except Exception:  # noqa: BLE001
        LOGGER.exception("Could not record the email in history")


def list_runs(limit: int = 100, settings: Settings | None = None) -> list[dict[str, Any]] | None:
    """Newest first, without the files. None when the database cannot be reached."""
    from sqlalchemy import select

    store = _get(settings)
    if store is None:
        return []
    if store is _Unreachable:
        return None
    engine, runs = store
    cols = [c for c in runs.c if c.name not in ("pdf", "xlsx")]
    try:
        with engine.connect() as conn:
            rows = conn.execute(select(*cols).order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(limit))
            return [dict(r._mapping) for r in rows]
    except Exception:  # noqa: BLE001
        LOGGER.exception("Could not read run history")
        return None


def get_files(run_id: int, settings: Settings | None = None) -> dict[str, bytes]:
    """{file name: bytes} for the run's PDF and workbook (empty when unavailable)."""
    from sqlalchemy import select

    store = _get(settings)
    if store in (None, _Unreachable):
        return {}
    engine, runs = store
    try:
        with engine.connect() as conn:
            row = conn.execute(select(runs.c.pdf_name, runs.c.pdf, runs.c.xlsx_name, runs.c.xlsx)
                               .where(runs.c.id == run_id)).first()
    except Exception:  # noqa: BLE001
        LOGGER.exception("Could not read files for run %s", run_id)
        return {}
    if row is None:
        return {}
    return {name: bytes(data) for name, data in ((row.pdf_name, row.pdf), (row.xlsx_name, row.xlsx)) if data}


def delete_run(run_id: int, settings: Settings | None = None) -> bool:
    from sqlalchemy import delete

    store = _get(settings)
    if store in (None, _Unreachable):
        return False
    engine, runs = store
    try:
        with engine.begin() as conn:
            return bool(conn.execute(delete(runs).where(runs.c.id == run_id)).rowcount)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Could not delete run %s", run_id)
        return False
