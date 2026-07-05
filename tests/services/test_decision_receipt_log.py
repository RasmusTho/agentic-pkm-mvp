"""Slice 1 (#2970) — durable WriteGuard-gated decision-receipt log + dual-write.

Invariant (feat #2969): the vault receipt log is the canonical judgment record;
Postgres is a rebuildable projection. Every decision write appends the
WriteGuard-gated durable receipt FIRST (commit point), then the DB projection.
No decision is ever recorded DB-only, and no decision write silently proceeds
when the guard blocks.

These tests exercise the durable (Postgres) branch of
``app.services.decisions.insert_decision`` without a real database by forcing the
non-memory backend and recording the DB seam — so they run in the ``not pg`` CI
gate while still proving the receipt-before-ack ordering and the guard behavior
on the real code path.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import app.receipts.decision_receipt_log as receipt_log
import app.services.decisions as decisions_module
from app.receipts.decision_receipt_log import (
    RECEIPT_WRITE_ACTION,
    SCHEMA_VERSION,
    append_decision_receipt,
    decisions_receipts_dir,
    iter_decision_receipts,
)
from app.write_guard import WritesBlockedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_shards(vault_root: Path) -> list[dict[str, Any]]:
    receipts_dir = decisions_receipts_dir(vault_root)
    records: list[dict[str, Any]] = []
    if not receipts_dir.exists():
        return records
    for shard in sorted(receipts_dir.glob("decisions-*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


class _RecordingCursor:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._log.append("db_insert")

    def fetchone(self) -> None:
        return None


class _RecordingConn:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def __enter__(self) -> "_RecordingConn":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self._log)


@pytest.fixture
def durable_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the durable (non-memory) branch of ``insert_decision``."""
    monkeypatch.setattr(decisions_module, "_use_memory_backend", lambda: False)
    # vault_uuid resolution touches the DB; keep it deterministic/offline here.
    monkeypatch.setattr(receipt_log, "resolve_vault_uuid", lambda object_id: None)


@pytest.fixture
def allow_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )


# ---------------------------------------------------------------------------
# AC1 — receipt appended before the DB write
# ---------------------------------------------------------------------------


def test_write_appends_receipt_then_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    durable_backend: None,
    allow_writes: None,
) -> None:
    """Every decision write appends a schema-valid receipt to the JSONL log
    BEFORE the DB write, and the DB write still happens (dual-write)."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    order: list[str] = []

    # Record the DB seam, and prove the receipt file already exists by the time
    # the DB insert runs (receipt-before-ack ordering, not merely both-present).
    def _recording_conn_rw(*args: object, **kwargs: object) -> _RecordingConn:
        receipts_dir = decisions_receipts_dir(vault)
        assert receipts_dir.exists(), "receipt must be durable before the DB write"
        assert any(receipts_dir.glob("decisions-*.jsonl"))
        order.append("db")
        return _RecordingConn(order)

    real_append = receipt_log.append_decision_receipt

    def _recording_append(**kwargs: object) -> dict[str, Any]:
        order.append("receipt")
        return real_append(**kwargs)

    monkeypatch.setattr(decisions_module, "append_decision_receipt", _recording_append)
    monkeypatch.setattr(decisions_module, "conn_rw", _recording_conn_rw)

    decisions_module.insert_decision(
        "obj-ac1", "review", {"allow": True, "score": 0.9, "agent": "reviewer"}, "trace-ac1"
    )

    # Ordering: receipt append happened-before the DB insert.
    assert order == ["receipt", "db", "db_insert"]

    records = _read_shards(vault)
    assert len(records) == 1
    rec = records[0]
    assert rec["schema_version"] == SCHEMA_VERSION
    assert rec["object_id"] == "obj-ac1"
    assert rec["vault_uuid"] is None
    assert rec["key"] == "review"
    # trace_id folded into the value envelope, exactly as the DB projection stores it.
    assert rec["value"]["trace_id"] == "trace-ac1"
    assert rec["value"]["allow"] is True
    assert rec["created_at"]


# ---------------------------------------------------------------------------
# AC2 — a blocked WriteGuard defers/raises loudly; no DB-only decision recorded
# ---------------------------------------------------------------------------


def test_blocked_guard_no_silent_db_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    durable_backend: None,
) -> None:
    """A blocked WriteGuard raises before any receipt or DB write — the
    governance action never silently proceeds DB-only (C-8)."""
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    def _blocked(action: str) -> None:
        raise WritesBlockedError("safe_mode", "runtime degraded", action)

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", _blocked
    )

    db_calls: list[str] = []
    monkeypatch.setattr(
        decisions_module,
        "conn_rw",
        lambda *a, **k: db_calls.append("db") or _RecordingConn([]),
    )

    with pytest.raises(WritesBlockedError):
        decisions_module.insert_decision(
            "obj-ac2", "review", {"allow": True}, "trace-ac2"
        )

    # No DB write attempted, and no receipt shard written.
    assert db_calls == []
    assert _read_shards(vault) == []


def test_blocked_guard_asserts_the_receipt_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam asserts the named ``decision.receipt`` action (auditable, not a
    silent absence of a guard)."""
    vault = tmp_path / "vault"
    seen: list[str] = []
    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: seen.append(action),
    )
    append_decision_receipt(
        object_id="obj",
        key="review",
        value={"allow": True},
        trace_id="t",
        vault_root=vault,
        vault_uuid=None,
    )
    assert seen == [RECEIPT_WRITE_ACTION]


# ---------------------------------------------------------------------------
# AC3 — the classifier path routes through the guarded writer (no except: pass)
# ---------------------------------------------------------------------------


def test_classification_path_is_guarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, durable_backend: None
) -> None:
    """The classifier's ``classification`` decision routes through the guarded
    receipt-log writer: a blocked guard fails the classify transition loudly
    (never a swallowed put_decision)."""
    from app.objects import DomainObject, ObjectStore

    store = ObjectStore()
    store.save_object(
        DomainObject(
            uuid="obj-ac3",
            kind="note",
            payload={"text": "some content to classify"},
            source_ref=None,
            created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        ),
        emit_outbox=False,
    )
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))

    # Force the classifier to reach persistence (heuristic fallback is fine).
    import app.agents.classifier.agent as classifier_agent

    def _blocked(action: str) -> None:
        raise WritesBlockedError("safe_mode", "runtime degraded", action)

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", _blocked
    )

    with pytest.raises(WritesBlockedError):
        classifier_agent.classify_object("obj-ac3", trace_id="trace-ac3")


def test_classify_shim_has_no_silent_swallow() -> None:
    """The legacy ``app/agents/classify.py`` shim no longer imports the
    deprecated ``put_decision`` nor carries an ``except Exception: pass`` around
    a decision write (the third silent-swallow site is removed)."""
    src = Path(__file__).resolve().parents[2] / "app" / "agents" / "classify.py"
    text = src.read_text(encoding="utf-8")
    assert "from app.stores.decisions import put_decision" not in text
    assert "put_decision(" not in text
    # No bare swallow around persistence remains.
    assert "except Exception:\n        pass" not in text


# ---------------------------------------------------------------------------
# Writer mechanics — dated shards, append-only, round-trip
# ---------------------------------------------------------------------------


def test_receipts_are_dated_shards_and_append_only(
    tmp_path: Path, allow_writes: None
) -> None:
    from datetime import datetime, timezone

    vault = tmp_path / "vault"
    jan = datetime(2026, 1, 15, tzinfo=timezone.utc)
    feb = datetime(2026, 2, 15, tzinfo=timezone.utc)

    append_decision_receipt(
        object_id="o1", key="review", value={"allow": True}, trace_id="t1",
        created_at=jan, vault_root=vault, vault_uuid="uuid-1",
    )
    append_decision_receipt(
        object_id="o1", key="review", value={"allow": False}, trace_id="t2",
        created_at=jan, vault_root=vault, vault_uuid="uuid-1",
    )
    append_decision_receipt(
        object_id="o2", key="evaluate", value={"promote": True}, trace_id="t3",
        created_at=feb, vault_root=vault, vault_uuid="uuid-2",
    )

    receipts_dir = decisions_receipts_dir(vault)
    shards = sorted(p.name for p in receipts_dir.glob("*.jsonl"))
    assert shards == ["decisions-202601.jsonl", "decisions-202602.jsonl"]

    all_records = iter_decision_receipts(vault)
    assert [r["trace_id"] if "trace_id" in r else r["value"]["trace_id"] for r in all_records] == [
        "t1",
        "t2",
        "t3",
    ]
    assert all_records[0]["vault_uuid"] == "uuid-1"
    assert all_records[2]["vault_uuid"] == "uuid-2"
