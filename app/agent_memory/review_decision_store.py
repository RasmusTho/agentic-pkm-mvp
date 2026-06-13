from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent_memory.review_queue import ReviewDecision, ReviewEntry
from app.vault.manager import VaultContext

REVIEW_DECISION_RECEIPT_KIND = "agent_memory.review_decision"
REVIEW_DECISION_STORE_VERSION = 1


@dataclass(frozen=True)
class ReviewDecisionRecord:
    vault_id: str
    channel: str
    candidate_id: str
    outcome: ReviewDecision
    decided_by: str
    decided_at: datetime
    source_refs: tuple[str, ...]
    receipt_kind: str = REVIEW_DECISION_RECEIPT_KIND
    terminal: bool = False
    decision_notes: str | None = None
    revision_of: str | None = None
    generated_by: str | None = None
    derived_from: str | None = None


class ReviewDecisionStoreError(ValueError):
    """Raised when a review-decision receipt cannot be recorded truthfully."""


class ReviewDecisionStore:
    """Durable vault-scoped review decision receipt store.

    Pending candidates are intentionally outside this store. Only explicit
    review decisions are recorded, and promote remains non-terminal until the
    later materialization slice marks it terminal after a governed vault write.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()

    def record_decision(
        self,
        entry: ReviewEntry,
        *,
        vault_context: VaultContext,
        channel: str,
    ) -> ReviewDecisionRecord:
        if entry.decision is None or entry.decided_by is None or entry.decided_at is None:
            raise ReviewDecisionStoreError("only decided review entries can be recorded")
        vault_id = _vault_id(vault_context)
        channel = _safe_str(channel)
        if not channel:
            raise ReviewDecisionStoreError("channel is required")

        record = ReviewDecisionRecord(
            vault_id=vault_id,
            channel=channel,
            candidate_id=entry.candidate_id,
            outcome=entry.decision,
            decided_by=entry.decided_by,
            decided_at=entry.decided_at.astimezone(timezone.utc),
            source_refs=tuple(entry.source_refs),
            terminal=entry.decision in {ReviewDecision.REJECT, ReviewDecision.REVISE},
            decision_notes=entry.decision_notes,
            revision_of=entry.revision_of,
            generated_by=entry.generated_by,
            derived_from=entry.derived_from,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_memory_review_decisions (
                    vault_id, channel, candidate_id, outcome, decided_by, decided_at,
                    terminal, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vault_id, channel, candidate_id) DO UPDATE SET
                    outcome = excluded.outcome,
                    decided_by = excluded.decided_by,
                    decided_at = excluded.decided_at,
                    terminal = excluded.terminal,
                    payload = excluded.payload
                """,
                (
                    record.vault_id,
                    record.channel,
                    record.candidate_id,
                    record.outcome.value,
                    record.decided_by,
                    _iso(record.decided_at),
                    1 if record.terminal else 0,
                    json.dumps(_record_payload(record), sort_keys=True, separators=(",", ":")),
                ),
            )
            conn.commit()
        return record

    def get_decision(
        self,
        candidate_id: str,
        *,
        vault_context: VaultContext,
        channel: str,
    ) -> ReviewDecisionRecord | None:
        vault_id = _vault_id(vault_context)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload
                FROM agent_memory_review_decisions
                WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                """,
                (vault_id, _safe_str(channel), _safe_str(candidate_id)),
            ).fetchone()
        if row is None:
            return None
        return _record_from_payload(json.loads(row["payload"]))

    def list_decisions(
        self,
        *,
        vault_context: VaultContext,
        channel: str,
    ) -> tuple[ReviewDecisionRecord, ...]:
        vault_id = _vault_id(vault_context)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload
                FROM agent_memory_review_decisions
                WHERE vault_id = ? AND channel = ?
                ORDER BY decided_at, candidate_id
                """,
                (vault_id, _safe_str(channel)),
            ).fetchall()
        return tuple(_record_from_payload(json.loads(row["payload"])) for row in rows)

    def mark_terminal(
        self,
        candidate_id: str,
        *,
        vault_context: VaultContext,
        channel: str,
    ) -> ReviewDecisionRecord:
        record = self.get_decision(
            candidate_id,
            vault_context=vault_context,
            channel=channel,
        )
        if record is None:
            raise ReviewDecisionStoreError("cannot mark missing decision terminal")
        terminal_record = ReviewDecisionRecord(
            vault_id=record.vault_id,
            channel=record.channel,
            candidate_id=record.candidate_id,
            outcome=record.outcome,
            decided_by=record.decided_by,
            decided_at=record.decided_at,
            source_refs=record.source_refs,
            receipt_kind=record.receipt_kind,
            terminal=True,
            decision_notes=record.decision_notes,
            revision_of=record.revision_of,
            generated_by=record.generated_by,
            derived_from=record.derived_from,
        )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_memory_review_decisions
                SET terminal = 1, payload = ?
                WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                """,
                (
                    json.dumps(
                        _record_payload(terminal_record),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    record.vault_id,
                    record.channel,
                    record.candidate_id,
                ),
            )
            conn.commit()
        return terminal_record

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_memory_review_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vault_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                decided_by TEXT NOT NULL,
                decided_at TEXT NOT NULL,
                terminal INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                UNIQUE(vault_id, channel, candidate_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_memory_review_decisions_scope
            ON agent_memory_review_decisions(vault_id, channel, decided_at, candidate_id)
            """
        )
        conn.commit()
        return conn


def _default_db_path() -> Path:
    configured = os.getenv("AGENT_MEMORY_REVIEW_DECISION_DB")
    if configured:
        return Path(configured).expanduser()
    return (
        Path(os.getenv("RUNTIME_TRACE_DIR", "runtime/agent_memory")).expanduser()
        / "review_decisions.sqlite3"
    )


def _safe_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _vault_id(context: VaultContext) -> str:
    vault_id = _safe_str(context.active_vault_id)
    if vault_id:
        return vault_id
    vault_path = _safe_str(context.active_vault_path)
    if vault_path:
        return f"path:{Path(vault_path).expanduser().resolve()}"
    raise ReviewDecisionStoreError("vault_context must include active_vault_id or active_vault_path")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def _record_payload(record: ReviewDecisionRecord) -> dict[str, Any]:
    return {
        "store_version": REVIEW_DECISION_STORE_VERSION,
        "receipt_kind": record.receipt_kind,
        "vault_id": record.vault_id,
        "channel": record.channel,
        "candidate_id": record.candidate_id,
        "outcome": record.outcome.value,
        "decided_by": record.decided_by,
        "decided_at": _iso(record.decided_at),
        "terminal": record.terminal,
        "source_refs": list(record.source_refs),
        "decision_notes": record.decision_notes,
        "revision_of": record.revision_of,
        "generated_by": record.generated_by,
        "derived_from": record.derived_from,
    }


def _record_from_payload(payload: dict[str, Any]) -> ReviewDecisionRecord:
    return ReviewDecisionRecord(
        vault_id=str(payload["vault_id"]),
        channel=str(payload["channel"]),
        candidate_id=str(payload["candidate_id"]),
        outcome=ReviewDecision(str(payload["outcome"])),
        decided_by=str(payload["decided_by"]),
        decided_at=_parse_iso(str(payload["decided_at"])),
        source_refs=tuple(str(ref) for ref in payload.get("source_refs", [])),
        receipt_kind=str(payload.get("receipt_kind") or REVIEW_DECISION_RECEIPT_KIND),
        terminal=bool(payload.get("terminal", False)),
        decision_notes=payload.get("decision_notes"),
        revision_of=payload.get("revision_of"),
        generated_by=payload.get("generated_by"),
        derived_from=payload.get("derived_from"),
    )


__all__ = [
    "REVIEW_DECISION_RECEIPT_KIND",
    "ReviewDecisionRecord",
    "ReviewDecisionStore",
    "ReviewDecisionStoreError",
]
