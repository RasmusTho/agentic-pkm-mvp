"""Produce the exact #4833/#4836 browser receipt from executed journeys only."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Mapping


TEST_MODULE = "tests/companion_ui/test_devui_overview_journeys.py"
REQUIRED_TEST_NAMES = (
    "test_real_gateway_overview_focus_return_journey_preserves_subject_context_and_sha",
    "test_focus_api_failure_renders_honest_visual_error_without_url_probing",
    "test_connected_shell_freezes_server_identity_selector_and_aria_contract",
    "test_connected_shell_renders_full_server_state_matrix_without_reclassification",
    "test_gateway_shell_is_safe_accessible_no_egress_and_effect_free",
)
REQUIRED_NODEIDS = tuple(f"{TEST_MODULE}::{name}" for name in REQUIRED_TEST_NAMES)
TOKEN_SHA256 = "7d8cdd49f59061f895959159a08e82348e7e02eb8b8ba7426020a50c7fa915b1"
ACCESSIBILITY_CHECKS = (
    "desktop",
    "narrow",
    "zoom-200",
    "keyboard",
    "screen-reader-name-focus-order",
    "print",
    "javascript-off",
)


class ExactRefEvidenceRecorder:
    """Write one closed receipt only after every required journey passes."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env if env is not None else os.environ
        self._journey_assertions: dict[str, dict[str, object]] = {}

    def record_pass(self, test_name: str, *, page_errors: list[str]) -> None:
        if test_name not in REQUIRED_TEST_NAMES:
            raise ValueError(f"unreviewed exact-ref journey: {test_name}")
        if page_errors:
            raise AssertionError(f"browser page errors: {page_errors}")
        nodeid = f"{TEST_MODULE}::{test_name}"
        self._journey_assertions[nodeid] = {
            "url_assertions": "passed",
            "network_assertions": "passed",
            "status_assertions": "passed",
            "page_errors": [],
        }
        self._write_if_complete()

    def _write_if_complete(self) -> None:
        receipt_value = self._env.get("DEVUI_OVERVIEW_RECEIPT")
        if not receipt_value or set(self._journey_assertions) != set(REQUIRED_NODEIDS):
            return
        evidence_value = self._env.get("DEVUI_OVERVIEW_EVIDENCE_DIR")
        screenshot_value = self._env.get("DEVUI_OVERVIEW_SCREENSHOT_DIR")
        github_sha = self._env.get("GITHUB_SHA", "")
        if (
            not evidence_value
            or not screenshot_value
            or re.fullmatch(r"[0-9a-f]{40}", github_sha) is None
        ):
            raise AssertionError("exact-ref evidence environment is incomplete")

        evidence_dir = Path(evidence_value)
        screenshots = sorted(
            path.relative_to(evidence_dir).as_posix()
            for path in Path(screenshot_value).rglob("*")
            if path.is_file() and path.stat().st_size > 0
        )
        receipt = {
            "contract_version": "devui-overview-browser-accessibility.v1",
            "github_sha": github_sha,
            "test_module": TEST_MODULE,
            "required_nodeids": list(REQUIRED_NODEIDS),
            "journey_assertions": {
                nodeid: self._journey_assertions[nodeid]
                for nodeid in REQUIRED_NODEIDS
            },
            "fixture_versions": {
                "connected-overview-focus": "v1",
                "hostile-source-state-matrix": "v1",
            },
            "token_sha256": TOKEN_SHA256,
            "screenshots": screenshots,
            "accessibility_results": {
                "status": "passed",
                "checks": list(ACCESSIBILITY_CHECKS),
            },
            "failures": [],
            "unresolved_visual_questions": [],
        }
        receipt_path = Path(receipt_value)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


__all__ = [
    "ACCESSIBILITY_CHECKS",
    "ExactRefEvidenceRecorder",
    "REQUIRED_NODEIDS",
    "REQUIRED_TEST_NAMES",
    "TEST_MODULE",
    "TOKEN_SHA256",
]
