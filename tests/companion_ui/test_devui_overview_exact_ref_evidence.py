from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.companion_ui._devui_overview_exact_ref_evidence import (
    ACCESSIBILITY_CHECKS,
    ExactRefEvidenceRecorder,
    REQUIRED_NODEIDS,
    REQUIRED_TEST_NAMES,
    TEST_MODULE,
    TOKEN_SHA256,
)


def test_exact_ref_receipt_is_emitted_only_after_every_required_journey(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "devui-overview"
    screenshot_dir = evidence_dir / "screenshots"
    screenshot_dir.mkdir(parents=True)
    (screenshot_dir / "overview.png").write_bytes(b"screenshot")
    receipt_path = evidence_dir / "receipts" / "devui-overview-browser-accessibility.v1.json"
    head_sha = "a" * 40
    recorder = ExactRefEvidenceRecorder(
        {
            "DEVUI_OVERVIEW_EVIDENCE_DIR": str(evidence_dir),
            "DEVUI_OVERVIEW_SCREENSHOT_DIR": str(screenshot_dir),
            "DEVUI_OVERVIEW_RECEIPT": str(receipt_path),
            "GITHUB_SHA": head_sha,
        }
    )

    for test_name in REQUIRED_TEST_NAMES[:-1]:
        recorder.record_pass(test_name, page_errors=[])
    assert not receipt_path.exists()

    recorder.record_pass(REQUIRED_TEST_NAMES[-1], page_errors=[])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert receipt == {
        "contract_version": "devui-overview-browser-accessibility.v1",
        "github_sha": head_sha,
        "test_module": TEST_MODULE,
        "required_nodeids": list(REQUIRED_NODEIDS),
        "journey_assertions": {
            nodeid: {
                "url_assertions": "passed",
                "network_assertions": "passed",
                "status_assertions": "passed",
                "page_errors": [],
            }
            for nodeid in REQUIRED_NODEIDS
        },
        "fixture_versions": {
            "connected-overview-focus": "v1",
            "hostile-source-state-matrix": "v1",
        },
        "token_sha256": TOKEN_SHA256,
        "screenshots": ["screenshots/overview.png"],
        "accessibility_results": {
            "status": "passed",
            "checks": list(ACCESSIBILITY_CHECKS),
        },
        "failures": [],
        "unresolved_visual_questions": [],
    }


def test_exact_ref_receipt_refuses_unknown_journey_or_page_error() -> None:
    recorder = ExactRefEvidenceRecorder({})

    with pytest.raises(ValueError, match="unreviewed exact-ref journey"):
        recorder.record_pass("test_unreviewed", page_errors=[])
    with pytest.raises(AssertionError, match="browser page errors"):
        recorder.record_pass(REQUIRED_TEST_NAMES[0], page_errors=["boom"])


def test_exact_ref_receipt_requires_canonical_github_sha(tmp_path: Path) -> None:
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    (screenshot_dir / "overview.png").write_bytes(b"screenshot")
    recorder = ExactRefEvidenceRecorder(
        {
            "DEVUI_OVERVIEW_EVIDENCE_DIR": str(tmp_path),
            "DEVUI_OVERVIEW_SCREENSHOT_DIR": str(screenshot_dir),
            "DEVUI_OVERVIEW_RECEIPT": str(tmp_path / "receipt.json"),
            "GITHUB_SHA": "g" * 40,
        }
    )

    for test_name in REQUIRED_TEST_NAMES[:-1]:
        recorder.record_pass(test_name, page_errors=[])
    with pytest.raises(AssertionError, match="evidence environment is incomplete"):
        recorder.record_pass(REQUIRED_TEST_NAMES[-1], page_errors=[])
