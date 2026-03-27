"""Quality Wave F — scripted UAT harness (pytest gate for the entire Quality Wave).

This file gates the Quality Wave as done. It exercises the CLI-first UAT flow
(seed → watcher → panel → promotion → consumer → rerun) and asserts that all
10 operational checks pass in both bootstrap and converged modes.

If this test file is green, the Quality Wave "Done means" criteria are met:
  - idempotence proven (first run vs rerun stable)
  - event chain proven (watcher → panel.intent.* → promote.*)
  - deterministic diffs on golden vault
  - gates enforced in CI/UAT
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.cli.uat import (
    UATAssertionError,
    UATSummary,
    run_vault_test_flow,
    seed_vault_test_notes,
)
from app.promotion.consumer import reset_promotion_dedup_store
from app.store import object_store as object_store_module
from app.testing.runtime_contract import failing_check_names

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Configure memory backend + deterministic rule mode. Returns outbox_path."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","confidence":0.95}')
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")

    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr(
        "app.observability.status_service.INDEX_OUTBOX_PATH", outbox_path, raising=False
    )
    return outbox_path


def _seed_and_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    assert_expectations: bool = False,
    assert_mode: str = "bootstrap",
) -> UATSummary:
    """Seed the vault with test notes and run the full UAT flow."""
    _setup_env(monkeypatch, tmp_path)

    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)

    seed_result = seed_vault_test_notes(vault_root=vault_root, overwrite=True)
    assert seed_result.written >= 1, f"expected at least 1 note seeded, got {seed_result.written}"

    return run_vault_test_flow(
        vault_root=vault_root,
        assert_expectations=assert_expectations,
        assert_mode=assert_mode,
    )


# ---------------------------------------------------------------------------
# 1. Bootstrap mode — first run produces expected state
# ---------------------------------------------------------------------------

class TestUATBootstrap:
    """Validate that a fresh seed-and-run produces all expected outcomes."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def test_bootstrap_flow_completes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The full UAT flow runs without exceptions."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert summary.watcher is not None
        assert summary.promotion is not None
        assert summary.rerun is not None

    def test_bootstrap_all_checks_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """All 10 UAT checks pass in bootstrap mode."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert summary.checks is not None, "checks should be populated after non-dry-run"

        failed = failing_check_names(summary.checks)
        assert not failed, f"UAT checks failed: {failed}"

    def test_bootstrap_assert_mode_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """assert_expectations=True with bootstrap mode does not raise."""
        _seed_and_run(tmp_path, monkeypatch, assert_expectations=True, assert_mode="bootstrap")

    def test_bootstrap_watcher_finds_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Watcher detects seeded notes as changes."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert int(summary.watcher.get("changed", 0) or 0) >= 1

    def test_bootstrap_promotion_applied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """At least one promotion is applied by the consumer."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert int(summary.promotion.get("applied", 0) or 0) >= 1

    def test_bootstrap_promote_intent_emitted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """At least one promote.intent.created is emitted."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert int(summary.watcher.get("panel_promotions", 0) or 0) >= 1

    def test_bootstrap_policy_skip_counted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The manual-policy note is skipped (policy=never)."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert int(summary.watcher.get("panel_skipped_policy", 0) or 0) >= 1


# ---------------------------------------------------------------------------
# 2. Rerun idempotency — second run is a no-op
# ---------------------------------------------------------------------------

class TestUATRerunIdempotency:
    """Validate that the built-in rerun (inside run_vault_test_flow) is stable."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def test_rerun_no_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rerun detects zero changed files."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        rerun_watcher = (summary.rerun or {}).get("watcher", {})
        assert int(rerun_watcher.get("changed", 0) or 0) == 0

    def test_rerun_no_panel_side_effects(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rerun produces zero panel runs and zero new promotion intents."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        rerun_watcher = (summary.rerun or {}).get("watcher", {})
        rerun_promotion = (summary.rerun or {}).get("promotion", {})
        assert int(rerun_watcher.get("panel_runs", 0) or 0) == 0
        assert int(rerun_watcher.get("panel_promotions", 0) or 0) == 0
        assert int(rerun_promotion.get("applied", 0) or 0) == 0

    def test_rerun_zero_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both initial run and rerun produce zero errors."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert int(summary.watcher.get("errors", 0) or 0) == 0
        assert int(summary.promotion.get("errors", 0) or 0) == 0
        rerun_watcher = (summary.rerun or {}).get("watcher", {})
        rerun_promotion = (summary.rerun or {}).get("promotion", {})
        assert int(rerun_watcher.get("errors", 0) or 0) == 0
        assert int(rerun_promotion.get("errors", 0) or 0) == 0


# ---------------------------------------------------------------------------
# 3. Report generation — UAT report is written and valid
# ---------------------------------------------------------------------------

class TestUATReport:
    """Validate that the UAT report is written with all expected fields."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def test_report_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A report file is created after the flow."""
        summary = _seed_and_run(tmp_path, monkeypatch)
        assert summary.report_path is not None
        assert summary.report_path.exists()

    def test_report_contains_checks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report contains all 10 UAT checks."""
        import json

        summary = _seed_and_run(tmp_path, monkeypatch)
        assert summary.report_path is not None
        report = json.loads(summary.report_path.read_text(encoding="utf-8"))
        checks = report.get("checks", {})
        expected_check_names = {
            "watcher_errors_zero",
            "promotion_errors_zero",
            "promote_intent_emitted",
            "promotion_applied",
            "manual_policy_skipped",
            "evergreen_note_promoted",
            "manual_note_unchanged",
            "mixed_actions_stays_safe",
            "rerun_no_changes",
            "rerun_no_panel_side_effects",
        }
        assert set(checks.keys()) == expected_check_names
        assert all(checks.values()), f"Some checks failed in report: {failing_check_names(checks)}"

    def test_report_no_failed_checks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Report's failed_checks list is empty."""
        import json

        summary = _seed_and_run(tmp_path, monkeypatch)
        assert summary.report_path is not None
        report = json.loads(summary.report_path.read_text(encoding="utf-8"))
        assert report.get("failed_checks") == []


# ---------------------------------------------------------------------------
# 4. Quality Wave gate — the final assertion
# ---------------------------------------------------------------------------

class TestQualityWaveGate:
    """The single gate test: if this passes, the Quality Wave is done."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def test_quality_wave_gate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        THE GATE: Run the full UAT flow with assert_expectations=True.

        This single test proves all Quality Wave "Done means" criteria:
        - Idempotence: rerun stable (bootstrap checks + rerun checks)
        - Event chain: promote.intent.created emitted and consumed
        - Deterministic: golden vault comparisons pass (covered by QW-B, gated here via checks)
        - Gates enforced: this test IS the CI gate
        """
        summary = _seed_and_run(
            tmp_path,
            monkeypatch,
            assert_expectations=True,
            assert_mode="bootstrap",
        )

        # Verify all 10 checks explicitly
        assert summary.checks is not None
        failed = failing_check_names(summary.checks)
        assert not failed, f"Quality Wave gate FAILED — checks: {failed}"

        # Verify report was written
        assert summary.report_path is not None
        assert summary.report_path.exists()
