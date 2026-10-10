"""Explicitly opted-in real-channel Playwright journey, one result per step."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

if os.environ.get("COMPANION_UI_LIVE_CORE_FLOW") != "1":
    pytest.skip(
        "Set COMPANION_UI_LIVE_CORE_FLOW=1 for the live dev/test journey.", allow_module_level=True
    )

from tests.companion_ui.live_core_flow import execute_manifest

pytestmark = pytest.mark.browser_runtime


@pytest.fixture(scope="module")
def flow_report() -> dict[str, Any]:
    path = os.environ.get("COMPANION_UI_CORE_FLOW_MANIFEST")
    if not path:
        raise ValueError("explicit_live_invocation_requires_private_manifest")
    return execute_manifest(Path(path))


def _assert_step(report: dict[str, Any], number: int) -> None:
    step = report["steps"][number - 1]
    assert step["status"] == "passed", f"{step['id']} {step['status']}: {step['reason']}"


def test_01_channel_gateway_and_health(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 1)


def test_02_open_known_note(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 2)


def test_03_capture_acknowledged_once(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 3)


def test_04_capture_survives_new_browser_context(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 4)


def test_05_fresh_capture_is_indexed_and_retrievable(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 5)


def test_06_ask_uses_this_runs_source(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 6)


def test_07_capture_unavailable_preserves_draft(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 7)


def test_08_ask_failure_is_visible_and_retryable(flow_report: dict[str, Any]) -> None:
    _assert_step(flow_report, 8)
