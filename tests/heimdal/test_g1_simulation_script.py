"""#3408 (ADR-0060 G1): day-like simulation runner contract.

The live run against the isolated test-host instance is the receipt (posted on
the Issue); this test pins the runner's contract: the trace is deterministic,
the uplink/gap arithmetic is right, the verdict judges only the simulated path,
G1 stays unmet, the wearable-only questions are always listed, and durable
outputs carry no per-segment identifiers.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "heimdal_g1_simulation.py"
HOST_SCRIPT = REPO_ROOT / "scripts" / "heimdal_g1_sim_host.sh"


def _load_module():
    spec = importlib.util.spec_from_file_location("heimdal_g1_simulation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["heimdal_g1_simulation"] = module
    spec.loader.exec_module(module)
    return module


sim = _load_module()


def _record(index: int, **overrides: Any) -> Dict[str, Any]:
    record = {
        "index": index,
        "activity": "ambient",
        "bytes": 1000,
        "buffered_by_outage": False,
        "uplink_wait_sim_s": 0.0,
        "ready_sim_s": (index + 1) * 60.0,
        "capture_id": f"cid-{index}",
        "receipt_id": f"rcp-{index}",
        "attempts": 1,
        "status": 200,
        "outcome": "admitted",
        "content_sha256_echo_ok": True,
        "queue_wait_s": 0.0,
        "request_s": 0.4,
        "connect_s": 0.01,
        "upload_s": 0.05,
        "server_s": 0.3,
        "e2e_wall_s": 0.4,
        "e2e_equiv_s": 0.4,
        "unavailable_s": 0.0,
    }
    record.update(overrides)
    return record


def _run(records: List[Dict[str, Any]], **overrides: Any) -> Dict[str, Any]:
    run = {
        "schema": sim.RUN_SCHEMA,
        "run_id": "g1sim-test",
        "role": "main",
        "host_label": "ygg-test",
        "image_ref": "sha",
        "trace_sha256": "ab" * 32,
        "trace_generator": {"seed": 3408},
        "segment_seconds": 60,
        "segments_in_run": len(records),
        "pace": 8.0,
        "outages": [],
        "drop_index": [],
        "duplicate_every": 0,
        "restart": {},
        "wall_s": 10.0,
        "records": records,
        "probes_s": [0.01, 0.02],
        "host_samples": [],
        "reconciliation": {
            "queried": sum(1 for r in records if r.get("capture_id")),
            "admitted": sum(1 for r in records if r.get("outcome") == "admitted"),
            "not_admitted_indexes": [],
            "query_errors": 0,
        },
    }
    run.update(overrides)
    return run


def test_day_schedule_is_deterministic_and_day_sized() -> None:
    first = sim.day_schedule(8, 60, 3408)
    assert first == sim.day_schedule(8, 60, 3408)
    assert len(first) == 480
    assert set(first) <= set(sim.ACTIVITY_CLASSES)
    assert first != sim.day_schedule(8, 60, 3409)


def test_segment_filters_are_synthetic_sources_only() -> None:
    for activity in sim.ACTIVITY_CLASSES:
        graph = sim.segment_filter(activity, 60, 7)
        assert graph.startswith(("anoisesrc=", "anullsrc=")), graph
        assert graph == sim.segment_filter(activity, 60, 7)
    with pytest.raises(ValueError):
        sim.segment_filter("speech_recording", 60, 7)


def test_trace_digest_is_order_sensitive() -> None:
    a = {"index": 0, "activity": "quiet", "sha256": "1" * 64}
    b = {"index": 1, "activity": "silence", "sha256": "2" * 64}
    assert sim.trace_digest([a, b]) != sim.trace_digest([b, a])


def test_outage_windows_are_half_open_in_sim_minutes() -> None:
    outage = sim.Outage.parse("60:15")
    assert (outage.start_s, outage.end_s) == (3600.0, 4500.0)
    assert sim.outage_at([outage], 3599.9) is None
    assert sim.outage_at([outage], 3600.0) is outage
    assert sim.outage_at([outage], 4500.0) is None


def test_gap_runs_and_percentile() -> None:
    assert sim.gap_runs([7, 3, 4, 5, 9]) == [(3, 5), (7, 7), (9, 9)]
    assert sim.percentile([1, 2, 3, 4], 50) == 2.5
    assert sim.percentile([], 50) is None


def test_clean_run_passes_simulated_path_but_g1_stays_unmet() -> None:
    records = [_record(i) for i in range(10)]
    records[4] = {"index": 4, "activity": "quiet", "bytes": 1000, "buffered_by_outage": False,
                  "uplink_wait_sim_s": 0.0, "ready_sim_s": 300.0, "outcome": "dropped_by_design"}
    records[2]["duplicate"] = {"status": 200, "idempotent_replay": True, "same_receipt": True}
    run = _run(records, drop_index=[4])
    receipt = sim.build_receipt(run, None, {"operator_steps": 4})

    assert receipt["schema"] == "heimdal.g1-simulation.v1"
    assert receipt["g1_status"] == "unmet"
    assert receipt["verdict"]["simulated_path"] == "pass"
    gaps = receipt["measurements"]["gaps"]
    assert gaps["missing_runs"] == [{"first": 4, "last": 4, "seconds": 60}]
    assert gaps["missing_equals_dropped"] is True
    questions = {q["question"] for q in receipt["wearable_questions_unproven"]}
    assert questions == {
        "battery_life",
        "ble_link_dropout_and_reconnect",
        "phone_presence_and_background_audio",
        "wearability_and_real_wearing_sessions",
    }


def test_lost_original_or_silent_gap_fails_the_simulated_path() -> None:
    records = [_record(i) for i in range(5)]
    records[3].update(outcome="failed", status=None)
    run = _run(records)
    run["reconciliation"]["not_admitted_indexes"] = [3]
    verdict = sim.build_receipt(run, None, {})["verdict"]
    assert verdict["simulated_path"] == "fail"
    assert verdict["checks"]["zero_lost_originals"] is False
    # Index 3 is missing but was not a by-design drop: the gap is unexplained.
    assert verdict["checks"]["gaps_legible"] is False


def test_backlog_episode_and_keep_up_checks() -> None:
    # Outage covers sim 120..300 s: segments 2 (ready 180) and 3 (ready 240) wait for it.
    records = [_record(i) for i in range(6)]
    records[2].update(buffered_by_outage=True, uplink_wait_sim_s=120.0, e2e_equiv_s=121.5)
    records[3].update(buffered_by_outage=True, uplink_wait_sim_s=60.0, e2e_equiv_s=61.0)
    run = _run(records, outages=[{"start_s": 120.0, "duration_s": 180.0}])
    summary = sim.summarize(run)
    assert summary["gaps"]["backlog_episodes"] == [
        {"outage_sim_s": 180.0, "segments_buffered": 2, "drain_wall_s": 1.5, "max_e2e_equiv_s": 121.5}
    ]
    assert sim.interpret(summary, 60)["checks"]["backlog_recovers"] is True

    # A segment that waited behind a draining backlog is recovery traffic, not steady state.
    behind = _run([_record(0), _record(1, queue_wait_s=24.0, e2e_wall_s=24.5)])
    latency = sim.summarize(behind)["latency_s"]
    assert latency["steady_e2e"]["n"] == 1 and latency["recovery_tail_e2e"]["max"] == 24.5

    slow = [_record(i, e2e_wall_s=75.0) for i in range(4)]
    assert sim.interpret(sim.summarize(_run(slow)), 60)["checks"]["keeps_up_with_real_time"] is False


def test_durable_outputs_carry_no_segment_identifiers() -> None:
    run = _run([_record(i) for i in range(3)])
    redacted = sim.strip_private(run)
    text = json.dumps(sim.build_receipt(redacted, None, {})) + json.dumps(redacted)
    assert "cid-" not in text and "rcp-" not in text
    assert sim.summarize(redacted)["counts"] == sim.summarize(run)["counts"]
    assert sim.summarize(redacted)["counts"]["admitted"] == 3
    markdown = sim.render_markdown(sim.build_receipt(redacted, None, {}))
    assert "G1 status: unmet" in markdown
    assert "battery" in markdown


def test_host_script_is_fail_fast_and_never_pulls() -> None:
    body = HOST_SCRIPT.read_text()
    assert "set -euo pipefail" in body
    assert "docker pull" not in body
    assert "127.0.0.1:${PG_PORT}:5432" in body
    assert "rm -rf -- \"${SIM_ROOT:?}/${run_id:?}\"" in body
