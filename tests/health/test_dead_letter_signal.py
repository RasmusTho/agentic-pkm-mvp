"""Dead-letter health signal tests (KERNEL-12 / #2774).

Verifies (spec: docs/RUNTIME_CORRECTNESS_KERNEL/DEAD_LETTER_HEALTH_SIGNAL.md):
1. `HealthContract.evaluate()` snapshot includes `dead_lettered_count` and
   `oldest_undelivered_age_seconds` computed from the outbox source.
2. Thresholds (`dead_lettered_warn`, `oldest_undelivered_age_warn_s`) are
   configurable via `HealthThresholds` and reflected in `to_payload()`.
3. An injected dead-letter — written by the PRODUCTION worker dead-letter
   writer, not a test helper — flips the health snapshot on the next
   `app.health_contract.DEFAULT_CONTRACT.evaluate()` call (one worker tick).
4. A dead-letter breach is an ALERTING signal only: it never blocks writes
   (`writes_allowed` stays True; nothing is added to `WRITE_BLOCKED_STATES`).

The signal is read-only by contract (cross-task invariant #5): these tests
assert detection only; no repair/re-drive path exists or is exercised.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

import pytest

from app.health_contract import (
    DEFAULT_CONTRACT,
    WRITE_BLOCKED_STATES,
    HealthContract,
    HealthStateMachine,
    reset_state_machine,
)
from app.settings.health_settings import HealthThresholds, load_health_settings
from app.workers.outbox_worker import (
    OUTBOX_EVENT_DEAD_LETTERED,
    _dead_letter_outbox_message,
)


def _mock_index_doctor() -> dict[str, object]:
    return {
        "backend": "mock",
        "expected_identity": None,
        "stored_identity": None,
        "issues": [],
        "warnings": [],
    }


@pytest.fixture()
def isolated_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the JSONL outbox at a tmp file and force the memory backend.

    STORE_BACKEND=memory keeps the health contract on the file-based outbox
    source (no Postgres in the `not pg` suite) and makes the worker dead-letter
    writer append to the JSONL audit sink only — the same production sink the
    health contract reads.
    """
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    # Keep the unrelated DB-backed index diagnostic out of the signal under test.
    monkeypatch.setattr("app.health_contract.diagnose_index", _mock_index_doctor)
    return outbox_path


def _inject_dead_letter(reason: str = "dispatch_failed:RuntimeError") -> None:
    """Inject a dead-letter through the PRODUCTION worker writer.

    This is the exact code path the worker runs when a poison row exhausts
    `_resolve_max_dispatch_attempts()` — not a hand-rolled JSONL line.
    """
    _dead_letter_outbox_message(
        "ingest.vault.changed",
        {"note_path": "notes/example.md", "trace_id": "trace-dl-1"},
        message_id="00000000-0000-0000-0000-000000000001",
        reason=reason,
        attempts=5,
        trace_id="trace-dl-1",
        error="boom",
    )


def _fresh_contract() -> HealthContract:
    return HealthContract(
        state_machine=HealthStateMachine(),
        vault_root_fn=lambda: None,
    )


# ---------------------------------------------------------------------------
# AC1: snapshot includes the two fields, computed from the outbox source
# ---------------------------------------------------------------------------


def test_snapshot_includes_dead_letter_fields(isolated_outbox: Path) -> None:
    contract = _fresh_contract()

    snapshot = contract.evaluate()
    assert snapshot["dead_lettered_count"] == 0
    assert snapshot["oldest_undelivered_age_seconds"] == 0.0
    assert snapshot["dead_letter_status"] == "pass"

    _inject_dead_letter()

    snapshot = contract.evaluate()
    assert snapshot["dead_lettered_count"] == 1
    assert isinstance(snapshot["oldest_undelivered_age_seconds"], float)
    # The injected record is a real production record with the canonical topic.
    raw = isolated_outbox.read_text(encoding="utf-8")
    assert OUTBOX_EVENT_DEAD_LETTERED in raw


# ---------------------------------------------------------------------------
# AC2: thresholds configurable via HealthThresholds + reflected in to_payload()
# ---------------------------------------------------------------------------


def test_thresholds_configurable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Defaults carry the new fields and expose them in the payload.
    defaults = HealthThresholds.defaults()
    payload = defaults.to_payload()
    assert payload["dead_lettered_warn"] == defaults.dead_lettered_warn
    assert (
        payload["oldest_undelivered_age_warn_s"]
        == defaults.oldest_undelivered_age_warn_s
    )

    # Explicit construction overrides the defaults.
    custom = HealthThresholds(
        outbox_degrade_oldest_age_s=15.0,
        outbox_recover_oldest_age_s=5.0,
        degrade_samples=3,
        recover_samples=10,
        dead_lettered_warn=7,
        oldest_undelivered_age_warn_s=42.5,
    )
    custom_payload = custom.to_payload()
    assert custom_payload["dead_lettered_warn"] == 7
    assert custom_payload["oldest_undelivered_age_warn_s"] == 42.5

    # Vault settings frontmatter configures the new keys ...
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "SystemDir")
    vault = tmp_path / "vault"
    settings_dir = vault / "SystemDir" / "Settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "health.md").write_text(
        dedent(
            """\
            ---
            thresholds:
              outbox_degrade_oldest_age_s: 20.0
              outbox_recover_oldest_age_s: 8.0
              degrade_samples: 4
              recover_samples: 12
              dead_lettered_warn: 3
              oldest_undelivered_age_warn_s: 120.0
            ---
            """
        ),
        encoding="utf-8",
    )
    result = load_health_settings(vault_root=vault, profile_env={})
    assert result.status == "ok"
    assert result.settings.thresholds.dead_lettered_warn == 3
    assert result.settings.thresholds.oldest_undelivered_age_warn_s == 120.0

    # ... and stay OPTIONAL: an existing settings file without them still
    # loads ok with the built-in defaults (no breakage of deployed vaults).
    (settings_dir / "health.md").write_text(
        dedent(
            """\
            ---
            thresholds:
              outbox_degrade_oldest_age_s: 20.0
              outbox_recover_oldest_age_s: 8.0
              degrade_samples: 4
              recover_samples: 12
            ---
            """
        ),
        encoding="utf-8",
    )
    result = load_health_settings(vault_root=vault, profile_env={})
    assert result.status == "ok"
    assert (
        result.settings.thresholds.dead_lettered_warn
        == defaults.dead_lettered_warn
    )
    assert (
        result.settings.thresholds.oldest_undelivered_age_warn_s
        == defaults.oldest_undelivered_age_warn_s
    )


# ---------------------------------------------------------------------------
# AC3: injected dead-letter flips the snapshot through the production path
# ---------------------------------------------------------------------------


def test_injected_dead_letter_flips_snapshot(isolated_outbox: Path) -> None:
    """One production dead-letter write flips DEFAULT_CONTRACT.evaluate().

    The Verify: target requires the field/breach to appear via
    `app.health_contract.DEFAULT_CONTRACT.evaluate()` — the exact object the
    HTTP `/healthz` / `/readyz` surface evaluates — within one tick (i.e. the
    next evaluation after the worker writes the dead-letter record).
    """
    reset_state_machine()
    try:
        baseline = DEFAULT_CONTRACT.evaluate()
        assert baseline["dead_lettered_count"] == 0
        assert baseline["dead_letter_status"] == "pass"

        # Production writer: the same call the worker makes on dispatch
        # exhaustion (app/workers/outbox_worker.py).
        _inject_dead_letter()

        snapshot = DEFAULT_CONTRACT.evaluate()
        assert snapshot["dead_lettered_count"] == 1
        # Default dead_lettered_warn=1: a single dead-letter is already loud.
        assert snapshot["dead_letter_status"] == "warn"
        assert any(
            "dead-letter" in action for action in snapshot["suggested_actions"]
        ), "breach must surface a suggested action on the health surface"
    finally:
        reset_state_machine()


# ---------------------------------------------------------------------------
# AC4: dead-letter breach never blocks writes
# ---------------------------------------------------------------------------


def test_dead_letter_does_not_block_writes(isolated_outbox: Path) -> None:
    # Contract-level guarantee: no dead-letter state was added to the
    # write-blocking set (design decision in the spec).
    assert WRITE_BLOCKED_STATES == {"safe_mode", "unhealthy"}

    contract = _fresh_contract()
    _inject_dead_letter()
    snapshot = contract.evaluate()

    assert snapshot["dead_letter_status"] == "warn"
    assert snapshot["writes_allowed"] is True
    assert snapshot["write_guard_reason"] is None


# ---------------------------------------------------------------------------
# Stale-backlog leg: oldest_undelivered_age breach also flips the status
# ---------------------------------------------------------------------------


def test_oldest_undelivered_age_breach_flips_status(
    isolated_outbox: Path,
) -> None:
    """The age leg breaches independently of the count leg (no dead-letters)."""
    from app.health_contract import _dead_letter_status

    thresholds = HealthThresholds.defaults()
    now = datetime.now(timezone.utc)  # noqa: UP017 — matches app module usage

    fresh = {
        "dead_lettered_count": 0,
        "oldest_undelivered_age_seconds": 0.0,
    }
    assert _dead_letter_status(fresh, thresholds) == "pass"

    stale = {
        "dead_lettered_count": 0,
        "oldest_undelivered_age_seconds": (
            thresholds.oldest_undelivered_age_warn_s + 1.0
        ),
    }
    assert _dead_letter_status(stale, thresholds) == "warn"
    assert now.tzinfo is not None
