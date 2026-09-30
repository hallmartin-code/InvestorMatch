"""Headless UI smoke test: the Streamlit app renders each step without errors."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from tests.conftest import ROOT


def test_app_renders_all_steps(sample_result, sample_deck):
    at = AppTest.from_file(str(ROOT / "app" / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    at.session_state["profile"] = sample_result.deal
    at.session_state["deck"] = sample_deck
    at.session_state["result"] = sample_result
    for step in range(5):
        at.session_state["step"] = step
        at.run()
        assert not at.exception, f"step {step}: {at.exception}"
