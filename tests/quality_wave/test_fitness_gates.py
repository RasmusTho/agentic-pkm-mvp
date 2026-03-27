from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.uat import run_vault_test_flow, seed_vault_test_notes
from app.events.types import PROMOTE_DONE, PROMOTE_INTENT_CREATED
from app.fitness.report import SUMMARY_LABELS, evaluate_gates, load_thresholds, parse_summary_lines
from app.observability import status_service
from app.observability.status_service import get_system_status
from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store
from app.store import object_store as object_store_module

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _reset() -> None:
    object_store_module._MEMORY_STORE.clear()
    reset_promotion_dedup_store()


def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","confidence":0.95}')
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "config")
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "capture")
    monkeypatch.setenv("VAULT_DESK_DIR_REL", "workbench")
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr(status_service, "INDEX_OUTBOX_PATH", outbox_path, raising=False)
    return outbox_path


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _events_of_type(records: list[dict], event_type: str) -> list[dict]:
    return [record for record in records if record.get("event") == event_type]


def _event_records(records: list[dict]) -> list[dict]:
    return [record for record in records if record.get("event")]


def _run_seeded_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    outbox_path = _setup_env(monkeypatch, tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    seed = seed_vault_test_notes(vault_root=vault, target_subdir="Test")
    summary = run_vault_test_flow(vault_root=vault, target_subdir="Test", assert_expectations=False)
    records = _read_outbox(outbox_path)
    status = get_system_status()
    return seed.destination, summary, outbox_path, records, status


class TestEventCountersDeterministic:
    def test_counters_after_flow_match_expected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, _, status = _run_seeded_flow(tmp_path, monkeypatch)

        assert status.events is not None
        assert status.events.promote_created_total >= 1
        assert status.events.promotion_executed_total >= 1
        assert status.events.panel_runs_total == 3
        assert status.events.watcher_runs_total == 2

    def test_counters_match_outbox_event_counts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, records, status = _run_seeded_flow(tmp_path, monkeypatch)

        assert status.events is not None
        assert status.events.promote_created_total == len(_events_of_type(records, PROMOTE_INTENT_CREATED))
        assert status.events.promotion_executed_total == len(_events_of_type(records, PROMOTE_DONE))
        assert status.events.panel_runs_total == len(_events_of_type(records, "panel.intent.executed"))
        watcher_events = len([r for r in records if r.get("event") in {"watcher.run", "watcher.run.completed"}])
        assert status.events.watcher_runs_total == watcher_events

    def test_rerun_counters_show_no_new_intents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, summary, _, records, status = _run_seeded_flow(tmp_path, monkeypatch)

        assert status.events is not None
        assert (summary.rerun or {}).get("watcher", {}).get("panel_promotions") == 0
        assert len(_events_of_type(records, PROMOTE_INTENT_CREATED)) == 1
        assert status.events.promote_created_total == 1


class TestNoDuplicateIntents:
    def test_no_duplicate_event_ids_in_outbox(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, records, _ = _run_seeded_flow(tmp_path, monkeypatch)

        event_records = _event_records(records)
        event_ids = [record["event_id"] for record in event_records]
        assert len(event_ids) == len(set(event_ids))

    def test_no_duplicate_promote_intent_for_same_note(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, records, _ = _run_seeded_flow(tmp_path, monkeypatch)

        promote_intents = _events_of_type(records, PROMOTE_INTENT_CREATED)
        note_ids = [intent.get("payload", {}).get("note", {}).get("uuid") for intent in promote_intents]
        assert len(note_ids) == len(set(note_ids))


class TestIdempotencyCounters:
    def test_second_consume_adds_zero_promotions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, outbox_path, _, _ = _run_seeded_flow(tmp_path, monkeypatch)

        second = consume_promotion_intents(outbox_path=outbox_path)
        assert second["applied"] == 0
        assert second["errors"] == 0

    def test_outbox_promote_count_stable_after_rerun(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, summary, _, records, _ = _run_seeded_flow(tmp_path, monkeypatch)

        assert summary.checks is not None
        assert summary.checks["rerun_no_changes"] is True
        assert summary.checks["rerun_no_panel_side_effects"] is True
        assert len(_events_of_type(records, PROMOTE_INTENT_CREATED)) == 1


class TestFitnessGateEvaluation:
    def test_uat_report_matches_summary_payload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _setup_env(monkeypatch, tmp_path)
        vault = tmp_path / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        seed = seed_vault_test_notes(vault_root=vault, target_subdir="Test")
        summary = run_vault_test_flow(vault_root=vault, target_subdir="Test", assert_expectations=False)

        assert summary.report_path is not None
        report_path = summary.report_path
        assert report_path.exists()

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["watcher"] == summary.watcher
        assert report["promotion"] == summary.promotion
        assert report["rerun"] == (summary.rerun or {})
        assert report["checks"] == (summary.checks or {})
        assert report["failed_checks"] == []
        assert report["checks"]["rerun_no_changes"] is True
        assert report["checks"]["rerun_no_panel_side_effects"] is True
        assert seed.destination.exists()

    def test_parse_summary_lines_roundtrip(self) -> None:
        lines = [
            "CI SUMMARY LATENCY QAS003=1.000000s QAS010=0.000100s",
            "CI SUMMARY EVAL P10=0.188 NDCG10=0.924 BASE_P10=0.188 BASE_NDCG10=0.855",
            "CI SUMMARY EVAL DELTA DP10=+0.006 DnDCG10=+0.011 RELATION_TARGET=60%",
            "CI SUMMARY RELATION COVERAGE=100.00%",
            "CI SUMMARY RELATIONS coverage=100.00% validity=100.00% target=95%",
            "CI SUMMARY DIARIZATION chunk_p95=78.00 speaker_avg=2.00 flag=on",
            "CI SUMMARY REASONING claims_avg=1.50 inferences_avg=0.75 conflicts=0.00 flag=on",
        ]

        parsed = parse_summary_lines(lines, required=SUMMARY_LABELS[:-1])

        assert parsed["LATENCY"]["QAS003"] == 1.0
        assert parsed["LATENCY"]["QAS010"] == 0.0001
        assert parsed["EVAL DELTA"]["DP10"] == 0.006
        assert parsed["RELATION COVERAGE"]["COVERAGE"] == 100.0
        assert parsed["RELATIONS"]["validity"] == 100.0
        assert parsed["REASONING"]["flag"] == "on"

    def test_evaluate_gates_passes_with_good_inputs(self) -> None:
        thresholds = load_thresholds("ops/quality/baselines.yaml")
        summary = parse_summary_lines(
            [
                "CI SUMMARY LATENCY QAS003=1.000000s QAS010=0.000100s",
                "CI SUMMARY EVAL P10=0.188 NDCG10=0.924 BASE_P10=0.188 BASE_NDCG10=0.855",
                "CI SUMMARY EVAL DELTA DP10=+0.006 DnDCG10=+0.011 RELATION_TARGET=60%",
                "CI SUMMARY RELATION COVERAGE=100.00%",
                "CI SUMMARY RELATIONS coverage=100.00% validity=100.00% target=95%",
                "CI SUMMARY DIARIZATION chunk_p95=78.00 speaker_avg=2.00 flag=on",
                "CI SUMMARY REASONING claims_avg=1.50 inferences_avg=0.75 conflicts=0.00 flag=on",
            ],
            required=SUMMARY_LABELS[:-1],
        )

        ok, reasons = evaluate_gates(
            summary,
            thresholds,
            provider="ce_local",
            diarization_off={"chunk_p95": 117.0},
            strict=True,
            reasoning_enabled=True,
        )

        assert ok is True
        assert reasons == []

    def test_evaluate_gates_fails_on_bad_input(self) -> None:
        thresholds = load_thresholds("ops/quality/baselines.yaml")
        summary = parse_summary_lines(
            [
                "CI SUMMARY LATENCY QAS003=10.000000s QAS010=1.000000s",
                "CI SUMMARY EVAL P10=0.100 NDCG10=0.100 BASE_P10=0.188 BASE_NDCG10=0.855",
                "CI SUMMARY EVAL DELTA DP10=-0.020 DnDCG10=-0.020 RELATION_TARGET=60%",
                "CI SUMMARY RELATION COVERAGE=50.00%",
                "CI SUMMARY RELATIONS coverage=50.00% validity=50.00% target=95%",
                "CI SUMMARY DIARIZATION chunk_p95=200.00 speaker_avg=2.00 flag=on",
                "CI SUMMARY REASONING claims_avg=0.10 inferences_avg=0.10 conflicts=3.00 flag=on",
            ],
            required=SUMMARY_LABELS[:-1],
        )

        ok, reasons = evaluate_gates(
            summary,
            thresholds,
            provider="ce_local",
            diarization_off={"chunk_p95": 117.0},
            strict=True,
            reasoning_enabled=True,
        )

        assert ok is False
        assert set(reasons) >= {"LAT", "EVAL_DELTA", "REL_COV", "REL_VAL", "DIA_P95", "REASONING"}
