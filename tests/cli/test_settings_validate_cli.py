from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.not_pg


def test_settings_validate_cli_ok() -> None:
    cmd = [sys.executable, "-m", "app.cli", "settings", "validate"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert r.returncode == 0
    assert "OK" in (r.stdout + r.stderr)


def test_settings_validate_cli_json_ok() -> None:
    cmd = [sys.executable, "-m", "app.cli", "settings", "validate", "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert r.returncode == 0
    assert '"ok": true' in r.stdout
