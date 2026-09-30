from __future__ import annotations

import os
import subprocess
import sys

# Tests never call external services, whatever the local .env contains.
os.environ["IM_NOTIFY_ENABLED"] = "false"
os.environ["IM_LLM_ENABLED"] = "false"
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_config  # noqa: E402
from app.extraction.deal_profile import extract_profile  # noqa: E402
from app.ingestion.deck import DeckDocument, DeckPage  # noqa: E402
from app.ingestion.mapping import INTRO_FIELDS, INVESTOR_FIELDS, auto_map  # noqa: E402
from app.ingestion.tables import ImportedTable  # noqa: E402
from app.pipeline import TableInput, extract, load_deck, load_tables, run_matching  # noqa: E402

SAMPLES = ROOT / "sample_data"
REPORT_DATE = date(2026, 9, 30)


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def samples() -> Path:
    if not (SAMPLES / "cardiolyte_health_deck.pptx").is_file():
        subprocess.run([sys.executable, str(SAMPLES / "make_samples.py")], check=True)
    return SAMPLES


@pytest.fixture(scope="session")
def sample_deck(samples, cfg):
    return load_deck(samples / "cardiolyte_health_deck.pptx", cfg)


@pytest.fixture(scope="session")
def sample_result(samples, cfg, sample_deck):
    profile = extract(sample_deck)
    investors = load_tables(samples / "TEN_Capital_Investor_List_SAMPLE.xlsx")
    intros = load_tables(samples / "TEN_Intro_Tracker_2026.xlsx", kind="intro")
    csv_intros = load_tables(samples / "cardiolyte_health_intros_Q3.csv", kind="intro")
    for t in csv_intros:
        t.company_specific = True
    return run_matching(profile, investors, intros + csv_intros, cfg, report_date=REPORT_DATE)


def make_deck(*pages: str, filename: str = "deck.pptx") -> DeckDocument:
    return DeckDocument(filename=filename, source_format="pptx", unit="slide",
                        pages=[DeckPage(number=i + 1, text=t) for i, t in enumerate(pages)])


DEFAULT_DECK = make_deck(
    "Acme Cardio\nRemote cardiac rehab digital therapeutic",
    "Headquartered in Austin, Texas\nDigital therapeutics for cardiovascular care; cardiology partners",
    "Raising $2M Seed round on a SAFE\n$500K committed from angels",
)


def table(rows: list[dict], filename: str = "list.csv", sheet: str | None = None) -> ImportedTable:
    columns = list(dict.fromkeys(k for r in rows for k in r))
    return ImportedTable(filename=filename, sheet=sheet, columns=columns,
                         rows=[{c: str(r.get(c, "")) for c in columns} for r in rows],
                         row_numbers=list(range(2, len(rows) + 2)), sha256="0" * 64)


def investor_input(rows: list[dict], filename: str = "investors.csv") -> TableInput:
    t = table(rows, filename)
    return TableInput(t, auto_map(t, INVESTOR_FIELDS))


def intro_input(rows: list[dict], filename: str = "intros.csv", company_specific: bool = False) -> TableInput:
    t = table(rows, filename)
    return TableInput(t, auto_map(t, INTRO_FIELDS), company_specific)


def investor(**kw) -> dict:
    base = {"First Name": "Pat", "Last Name": "Lee", "Email": "pat.lee@fund.example", "Organization": "Fund A",
            "Investor Type": "Angel", "Location": "Austin, TX", "Sector Focus": "Digital Therapeutics",
            "Stage Focus": "Seed", "Check Size": "$25K-$100K", "Geographic Focus": "Texas"}
    base.update(kw)
    return base


def run(cfg, rows, intros=None, deck=DEFAULT_DECK, **kw):
    profile = extract_profile(deck)
    return run_matching(profile, [investor_input(rows)], intros or [], cfg, report_date=REPORT_DATE, **kw)
