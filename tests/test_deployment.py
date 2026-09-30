"""Deployment hygiene: the start command must expand $PORT (Railway runs it without a shell otherwise)."""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from tests.conftest import ROOT


def test_railway_start_command_runs_in_a_shell():
    cfg = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    command = cfg["deploy"]["startCommand"]
    assert cfg["build"]["builder"] == "DOCKERFILE"
    assert command.startswith("sh -c '") and "${PORT:-8501}" in command
    assert "$PORT " not in command.replace("${PORT:-8501}", "")      # never a bare, unexpanded $PORT


def test_dockerfile_cmd_expands_port():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cmd = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))
    assert '"sh", "-c"' in cmd and "${PORT:-8501}" in cmd


def test_no_procfile():
    # A Procfile's `$PORT` start command is copied into Railway service settings and breaks Dockerfile deploys.
    assert not (ROOT / "Procfile").exists()


def test_start_command_expands_port_in_sh():
    sh = subprocess.run(["sh", "-c", "command -v sh"], capture_output=True, text=True)
    if sh.returncode != 0:
        pytest.skip("no POSIX sh available")
    command = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))["deploy"]["startCommand"]
    inner = re.fullmatch(r"sh -c '(.*)'", command).group(1)
    for port, expected in (("4321", "4321"), ("", "8501")):
        out = subprocess.run(["sh", "-c", f"PORT={port}; echo {inner}"], capture_output=True, text=True).stdout
        assert f"--server.port {expected} " in out
