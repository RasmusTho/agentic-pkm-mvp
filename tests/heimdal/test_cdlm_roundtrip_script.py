"""CDLM-10 (#4389): proof-script structure and evidence contract.

The live run against the test channel is the capability receipt (posted on the
parent issue); this test pins the script's *contract*: it exists, is
re-runnable, covers stages 1–6 with named evidence outputs, declares the two
receipt schemas, and its honesty machinery (limited-status reporting, private
in-process data stripped from durable receipts) is real.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cdlm_roundtrip_proof.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("cdlm_roundtrip_proof", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered before exec so the script's dataclasses resolve their
    # string annotations (PEP 563) against a real sys.modules entry.
    sys.modules["cdlm_roundtrip_proof"] = module
    spec.loader.exec_module(module)
    return module


def test_script_stages_and_evidence_contract() -> None:
    assert SCRIPT.is_file()
    module = _load_module()

    # The two durable receipt schemas the ACs name.
    assert (
        module.RUN_REPORT_SCHEMA
        == "cross_device_capture_live_meeting.round_trip_run_report.v1"
    )
    assert (
        module.CHAOS_EVIDENCE_SCHEMA
        == "cross_device_capture_live_meeting.chaos_stage_evidence.v1"
    )

    # Stages 1–6 from the task spec, in order, each with named evidence keys.
    stages = module.STAGES
    assert [s["stage"] for s in stages] == [1, 2, 3, 4, 5, 6]
    assert [s["id"] for s in stages] == [
        "multi_modality_round_trip",
        "kill_restart_chaos",
        "duplicate_injection",
        "live_meeting_reconnect",
        "gapped_close_late_reconcile",
        "legacy_lane_statement",
    ]
    for stage in stages:
        assert stage["evidence"], stage["id"]
        # And a real stage function backs each registry entry.
        fn_prefix = f"stage_{stage['stage']}_"
        assert any(
            name.startswith(fn_prefix) for name in vars(module) if callable(getattr(module, name, None))
        ), stage["id"]

    # The four capability checklines are explicit.
    assert module.CHECKLINES == [
        "zero_lost_originals",
        "zero_duplicates",
        "gap_legibility",
        "user_note_verbatim_survival",
    ]

    # Re-runnable and network-free in plan mode: the CLI contract holds.
    plan = subprocess.run(
        [sys.executable, str(SCRIPT), "--plan"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert plan.returncode == 0, plan.stderr
    payload = json.loads(plan.stdout)
    assert payload["schemas"] == [module.RUN_REPORT_SCHEMA, module.CHAOS_EVIDENCE_SCHEMA]
    assert payload["stages"] == module.STAGES
    assert payload["checklines"] == module.CHECKLINES

    # Honesty machinery: private in-process values (raw media bytes) never
    # reach a durable receipt, and the markdown renderer names the simulator
    # limit + bifrost#21 as the remaining human step.
    stripped = module._strip_private(
        {"a": 1, "_media": b"secret-bytes", "nested": [{"_media": b"x", "keep": True}]}
    )
    assert stripped == {"a": 1, "nested": [{"keep": True}]}

    markdown = module.render_markdown(
        {
            "channel": "test",
            "hub_sha": "h" * 8,
            "client_sha": "c" * 8,
            "run_id": "cdlm10-test",
            "ran_at": "2026-07-30T00:00:00Z",
            "duplicate_injection_count": 4,
            "checklines": [
                {"checkline": name, "checked": True, "evidence": {}} for name in module.CHECKLINES
            ],
            "stages": [
                {"stage": s["stage"], "id": s["id"], "status": "pass", "limits": []}
                for s in module.STAGES
            ],
        }
    )
    assert "bifrost#21" in markdown
    assert "device walkthrough" in markdown
    for name in module.CHECKLINES:
        assert f"`{name}`" in markdown
