"""Explicit actual TEST proof; a required missing/blocked outcome fails pytest."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

if os.environ.get("COMPANION_UI_LIVE_DEEP_REVIEW") != "1":
    pytest.skip("Set COMPANION_UI_LIVE_DEEP_REVIEW=1 for actual TEST acceptance.", allow_module_level=True)

from tests.companion_ui.live_deep_review import acceptance_passed, execute_manifest

pytestmark = pytest.mark.browser_runtime


def test_deep_review_live_acceptance() -> None:
    path = os.environ.get("COMPANION_UI_DEEP_REVIEW_MANIFEST")
    report = execute_manifest(Path(path) if path else None)
    failures = [(row["id"], row["status"], row["reason"]) for row in report["scenarios"] if row["status"] != "passed"]
    assert acceptance_passed(report), f"actual_required_TEST_proof_failed: {failures!r}; private report.json retained"
