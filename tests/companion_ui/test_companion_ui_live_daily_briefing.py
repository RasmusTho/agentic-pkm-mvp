"""Explicit opt-in: missing/blocked/failing actual TEST proof is a test failure."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

if os.environ.get("COMPANION_UI_LIVE_DAILY_BRIEFING") != "1":
    pytest.skip("Set COMPANION_UI_LIVE_DAILY_BRIEFING=1 for actual native acceptance.", allow_module_level=True)

from tests.companion_ui.live_daily_briefing import acceptance_passed, execute_manifest

pytestmark = pytest.mark.browser_runtime


def test_daily_briefing_live_acceptance() -> None:
    path = os.environ.get("COMPANION_UI_DAILY_BRIEFING_MANIFEST")
    report = execute_manifest(Path(path) if path else None)
    assert acceptance_passed(report), "actual_required_TEST_proof_failed: " + "; ".join(
        f"{x['id']} {x['status']}: {x['reason']}" for x in report["scenarios"] if x["status"] != "passed"
    )
