from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.agent_memory.candidate import validated_memory_scope_id
from app.agent_memory.review_queue import ReviewDecision, ReviewEntry
from app.vault.manager import VaultContext

REVIEW_DECISION_RECEIPT_KIND = "agent_memory.review_decision"
REVIEW_DECISION_STORE_VERSION = 3
_UNSET = object()


@dataclass(frozen=True)
class ReviewDecisionRecord:
    vault_id: str
    channel: str
    candidate_id: str
    outcome: ReviewDecision
    decided_by: str
    decided_at: datetime
    source_refs: tuple[str, ...]
    scope_id: str | None = None
    receipt_kind: str = REVIEW_DECISION_RECEIPT_KIND
    terminal: bool = False
    decision_notes: str | None = None
    revision_of: str | None = None
    generated_by: str | None = None
    derived_from: str | None = None
    candidate_digest: str | None = None
    materializing: bool = False


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
        if (
            entry.scope_id is not None
            and validated_memory_scope_id(entry.scope_id) is None
        ):
            raise ReviewDecisionStoreError("candidate scope is invalid")

        record = ReviewDecisionRecord(
            vault_id=vault_id,
            channel=channel,
            candidate_id=entry.candidate_id,
            outcome=entry.decision,
            decided_by=entry.decided_by,
            decided_at=entry.decided_at.astimezone(timezone.utc),
            source_refs=tuple(entry.source_refs),
            scope_id=entry.scope_id,
            terminal=entry.decision in {ReviewDecision.REJECT, ReviewDecision.REVISE},
            decision_notes=entry.decision_notes,
            revision_of=entry.revision_of,
            generated_by=entry.generated_by,
            derived_from=entry.derived_from,
            candidate_digest=review_candidate_digest(entry),
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing_row = conn.execute(
                """
                SELECT payload
                FROM agent_memory_review_decisions
                WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                """,
                (record.vault_id, record.channel, record.candidate_id),
            ).fetchone()
            if existing_row is not None:
                existing = _record_from_payload(json.loads(existing_row["payload"]))
                if existing.terminal:
                    raise ReviewDecisionStoreError(
                        "terminal review decisions cannot be replaced"
                    )
                if existing.scope_id != record.scope_id:
                    raise ReviewDecisionStoreError(
                        "candidate scope cannot change across review decisions"
                    )
                if (
                    existing.candidate_digest is not None
                    and existing.candidate_digest != record.candidate_digest
                ):
                    raise ReviewDecisionStoreError(
                        "candidate content cannot change across review decisions"
                    )
                if existing.materializing:
                    if record.outcome is ReviewDecision.PROMOTE:
                        return existing
                    raise ReviewDecisionStoreError(
                        "review decision cannot change while materialization is in progress"
                    )
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
        expected_scope_id: str | None | object = _UNSET,
        expected_outcome: ReviewDecision | None = None,
    ) -> ReviewDecisionRecord:
        vault_id = _vault_id(vault_context)
        safe_channel = _safe_str(channel)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT payload
                FROM agent_memory_review_decisions
                WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                """,
                (vault_id, safe_channel, _safe_str(candidate_id)),
            ).fetchone()
            if row is None:
                raise ReviewDecisionStoreError("cannot mark missing decision terminal")
            record = _record_from_payload(json.loads(row["payload"]))
            if record.terminal:
                raise ReviewDecisionStoreError("decision is already terminal")
            if expected_scope_id is not _UNSET and record.scope_id != expected_scope_id:
                raise ReviewDecisionStoreError(
                    "persisted candidate scope changed before terminal transition"
                )
            if expected_outcome is not None and record.outcome is not expected_outcome:
                raise ReviewDecisionStoreError(
                    "persisted decision outcome changed before terminal transition"
                )
            terminal_record = replace(record, terminal=True)
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

    @contextmanager
    def promotion_materialization_transaction(
        self,
        candidate_id: str,
        *,
        vault_context: VaultContext,
        channel: str,
        expected_scope_id: str,
        expected_candidate_digest: str,
    ) -> Iterator[ReviewDecisionRecord]:
        """Serialize one promoted decision through artifact write and terminalization."""

        vault_id = _vault_id(vault_context)
        safe_channel = _safe_str(channel)
        safe_candidate_id = _safe_str(candidate_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT payload
                FROM agent_memory_review_decisions
                WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                """,
                (vault_id, safe_channel, safe_candidate_id),
            ).fetchone()
            if row is None:
                raise ReviewDecisionStoreError(
                    "semantic memory materialization requires a persisted decision"
                )
            record = _record_from_payload(json.loads(row["payload"]))
            if record.outcome is not ReviewDecision.PROMOTE:
                raise ReviewDecisionStoreError(
                    "semantic memory materialization requires a persisted promote decision"
                )
            if record.terminal:
                raise ReviewDecisionStoreError(
                    "semantic memory decision is already terminal"
                )
            if record.scope_id != expected_scope_id:
                raise ReviewDecisionStoreError(
                    "candidate.scope_id does not match the persisted review decision"
                )
            if record.candidate_digest != expected_candidate_digest:
                raise ReviewDecisionStoreError(
                    "candidate content does not match the persisted review decision"
                )
            if not record.materializing:
                materializing_record = replace(record, materializing=True)
                conn.execute(
                    """
                    UPDATE agent_memory_review_decisions
                    SET payload = ?
                    WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                      AND outcome = ? AND terminal = 0
                    """,
                    (
                        json.dumps(
                            _record_payload(materializing_record),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        record.vault_id,
                        record.channel,
                        record.candidate_id,
                        ReviewDecision.PROMOTE.value,
                    ),
                )
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                resumed_row = conn.execute(
                    """
                    SELECT payload
                    FROM agent_memory_review_decisions
                    WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                    """,
                    (record.vault_id, record.channel, record.candidate_id),
                ).fetchone()
                if resumed_row is None:
                    raise ReviewDecisionStoreError(
                        "materializing review decision disappeared"
                    )
                record = _record_from_payload(json.loads(resumed_row["payload"]))
                if record.terminal or record.outcome is not ReviewDecision.PROMOTE:
                    raise ReviewDecisionStoreError(
                        "promote decision changed before materialization resumed"
                    )
                if (
                    record.scope_id != expected_scope_id
                    or record.candidate_digest != expected_candidate_digest
                    or not record.materializing
                ):
                    raise ReviewDecisionStoreError(
                        "materialization authority changed before resume"
                    )

            try:
                yield record
            except Exception:
                conn.rollback()
                raise

            terminal_record = replace(record, terminal=True, materializing=False)
            updated = conn.execute(
                """
                UPDATE agent_memory_review_decisions
                SET terminal = 1, payload = ?
                WHERE vault_id = ? AND channel = ? AND candidate_id = ?
                  AND outcome = ? AND terminal = 0
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
                    ReviewDecision.PROMOTE.value,
                ),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise ReviewDecisionStoreError(
                    "promote decision changed before terminal transition"
                )
            conn.commit()

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
        "scope_id": record.scope_id,
        "decision_notes": record.decision_notes,
        "revision_of": record.revision_of,
        "generated_by": record.generated_by,
        "derived_from": record.derived_from,
        "candidate_digest": record.candidate_digest,
        "materializing": record.materializing,
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
        scope_id=payload.get("scope_id"),
        receipt_kind=str(payload.get("receipt_kind") or REVIEW_DECISION_RECEIPT_KIND),
        terminal=bool(payload.get("terminal", False)),
        decision_notes=payload.get("decision_notes"),
        revision_of=payload.get("revision_of"),
        generated_by=payload.get("generated_by"),
        derived_from=payload.get("derived_from"),
        candidate_digest=payload.get("candidate_digest"),
        materializing=bool(payload.get("materializing", False)),
    )


def review_candidate_digest(entry: ReviewEntry) -> str:
    payload = entry.candidate.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "REVIEW_DECISION_RECEIPT_KIND",
    "ReviewDecisionRecord",
    "ReviewDecisionStore",
    "ReviewDecisionStoreError",
    "review_candidate_digest",
]
