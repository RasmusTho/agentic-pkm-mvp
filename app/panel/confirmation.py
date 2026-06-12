"""Panel confirmation service — runtime-mediated confirm/reject for Panel proposals.

The Companion UI must not write vault files directly. This module owns policy
evaluation, WriteGuard, idempotency, execution delegation, receipts, and the
typed response contract.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agents.panel_agent.runtime import execute_panel_intent  # noqa: F401 — patchable by tests
from app.agents.panel.writeback import (
    annotate_action_ids,
    remove_actions_from_markdown,
    stable_action_id,
    write_receipts,
)
from app.events.panel import PanelIntentEvent
from app.events.schema import make_outbox_event
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import append_jsonl_outbox_event, coerce_outbox_event, write_outbox_event
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

logger = logging.getLogger(__name__)

SAME_TURN_TTL_SECONDS = 5.0
PANEL_STAGING_SCHEMA_VERSION = 1
DEFAULT_PANEL_STAGING_STATE_DIR = Path("runtime/panel")
DEFAULT_PANEL_STAGING_DB_NAME = "panel_confirmation.sqlite3"
DEFAULT_PANEL_STAGING_RETENTION_SECONDS = 7 * 24 * 60 * 60


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_panel_staging_db_path(env: dict[str, str] | None = None) -> Path:
    src = env if env is not None else os.environ
    state_dir = Path(
        src.get("PANEL_STAGING_STATE_DIR")
        or src.get("PANEL_CONFIRMATION_STATE_DIR")
        or str(DEFAULT_PANEL_STAGING_STATE_DIR)
    ).expanduser()
    return Path(
        src.get("PANEL_STAGING_DB_PATH")
        or src.get("PANEL_CONFIRMATION_DB_PATH")
        or str(state_dir / DEFAULT_PANEL_STAGING_DB_NAME)
    ).expanduser()


def _resolve_panel_staging_retention_seconds(env: dict[str, str] | None = None) -> float:
    src = env if env is not None else os.environ
    raw = src.get("PANEL_STAGING_RETENTION_SECONDS") or src.get(
        "PANEL_CONFIRMATION_RETENTION_SECONDS"
    )
    if raw is None:
        return float(DEFAULT_PANEL_STAGING_RETENTION_SECONDS)
    try:
        parsed = float(raw)
    except ValueError:
        return float(DEFAULT_PANEL_STAGING_RETENTION_SECONDS)
    return max(parsed, SAME_TURN_TTL_SECONDS)


PANEL_STAGING_DDL = [
    """
    CREATE TABLE IF NOT EXISTS panel_confirmation_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS panel_staged_proposals (
        proposal_id TEXT PRIMARY KEY,
        artifact_id TEXT NOT NULL,
        intent_event_json TEXT NOT NULL,
        proposed_at REAL NOT NULL,
        trace_id TEXT NOT NULL,
        proposal_origin TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_panel_staged_proposals_artifact
    ON panel_staged_proposals(artifact_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS panel_confirm_idempotency (
        key TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]


class SameTurnExecutionError(RuntimeError):
    pass


class UnknownProposalError(LookupError):
    pass


@dataclass
class StagedProposal:
    artifact_id: str
    intent_event: PanelIntentEvent
    proposed_at: float = field(default_factory=time.time)
    trace_id: str = ""
    # Proposal-scoped provenance — which surface staged this Panel proposal
    # (e.g. "canvas_coauthoring"). Distinct from the vault-note/frontmatter
    # ``origin`` field; Panel attribution must never overwrite artifact origin.
    proposal_origin: str | None = None


class CorrectionFields(BaseModel):
    enabled: bool = False
    corrected_action_id: str | None = None
    corrected_parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _require_correction_payload(self) -> "CorrectionFields":
        if self.enabled and self.corrected_action_id is None and self.corrected_parameters is None:
            raise ValueError(
                "correction.enabled=true requires corrected_action_id or corrected_parameters"
            )
        return self


class ConfirmRequest(BaseModel):
    proposal_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    action: str
    idempotency_key: str = Field(min_length=1)
    correction: CorrectionFields | None = None

    @model_validator(mode="after")
    def _validate_action(self) -> "ConfirmRequest":
        if self.action not in ("confirm", "reject"):
            raise ValueError(f"action must be 'confirm' or 'reject', got '{self.action}'")
        return self


class Receipt(BaseModel):
    action_taken: str
    outcome: str
    timestamp: str
    message: str | None = None
    inverse_action: str | None = None


class BlockReason(BaseModel):
    gate: str
    message: str
    code: str | None = None


def _receipt_visibility_for(status: str) -> str:
    """Map a confirm outcome to its receipt-visibility posture.

    This is the receipt step of the inspect -> queue -> confirm -> receipt
    operational loop. The posture is a projection of where the durable receipt
    lives; it is not the durable authority store. Durable receipts are written
    to the vault AI-status callout by the runtime.
    """
    if status in ("executed", "logged"):
        return "durable_vault_visible"
    if status == "blocked":
        return "blocked_no_durable_receipt"
    if status == "rejected":
        return "none_rejected"
    return "none"


class ConfirmResponse(BaseModel):
    proposal_id: str
    artifact_id: str
    status: str
    outcome: str
    receipt: Receipt | None = None
    block_reason: BlockReason | None = None
    error: str | None = None
    idempotency_key: str
    events_emitted: list[str] = Field(default_factory=list)
    # Receipt-visibility posture for the operational loop. Derived from status
    # when not explicitly provided; the UI surfaces this as visibility, not as
    # durable approval/execution authority.
    receipt_visibility: str = ""

    @model_validator(mode="after")
    def _derive_receipt_visibility(self) -> "ConfirmResponse":
        if not self.receipt_visibility:
            self.receipt_visibility = _receipt_visibility_for(self.status)
        return self


class ProposalStore:
    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        retention_seconds: float | None = None,
    ) -> None:
        self._proposals: dict[str, StagedProposal] = {}
        self._db_path = Path(db_path).expanduser() if db_path is not None else None
        self._retention_seconds = (
            float(retention_seconds)
            if retention_seconds is not None
            else _resolve_panel_staging_retention_seconds()
        )
        self._degraded_reason: str | None = None
        if self._db_path is not None:
            self._initialize()

    @classmethod
    def durable_default(cls) -> "ProposalStore":
        return cls(
            _resolve_panel_staging_db_path(),
            retention_seconds=_resolve_panel_staging_retention_seconds(),
        )

    @property
    def mode(self) -> str:
        if self._db_path is None:
            return "memory"
        if self.degraded:
            return "memory-degraded"
        return "sqlite"

    @property
    def degraded(self) -> bool:
        return self._degraded_reason is not None

    @property
    def degraded_reason(self) -> str | None:
        return self._degraded_reason

    @property
    def db_path(self) -> Path | None:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            raise RuntimeError("proposal store is memory-only")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        try:
            with self._connect() as conn:
                for stmt in PANEL_STAGING_DDL:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT OR REPLACE INTO panel_confirmation_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(PANEL_STAGING_SCHEMA_VERSION)),
                )
                self._purge_expired(conn, now=time.time())
                rows = conn.execute(
                    """
                    SELECT proposal_id, artifact_id, intent_event_json, proposed_at,
                           trace_id, proposal_origin
                    FROM panel_staged_proposals
                    ORDER BY proposed_at ASC
                    """
                ).fetchall()
                conn.commit()
            self._proposals = {}
            for row in rows:
                self._proposals[str(row["proposal_id"])] = StagedProposal(
                    artifact_id=str(row["artifact_id"]),
                    intent_event=PanelIntentEvent.model_validate_json(
                        str(row["intent_event_json"])
                    ),
                    proposed_at=float(row["proposed_at"]),
                    trace_id=str(row["trace_id"] or ""),
                    proposal_origin=row["proposal_origin"],
                )
            self._degraded_reason = None
        except Exception as exc:
            self._degraded_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("panel proposal store degraded to memory-only: %s", exc)

    def _purge_expired(self, conn: sqlite3.Connection, *, now: float) -> None:
        cutoff = now - self._retention_seconds
        conn.execute(
            "DELETE FROM panel_staged_proposals WHERE proposed_at < ?",
            (cutoff,),
        )

    def stage(self, proposal_id: str, proposal: StagedProposal) -> None:
        self._proposals[proposal_id] = proposal
        if self._db_path is None or self.degraded:
            return
        try:
            now_iso = _utc_now_iso()
            with self._connect() as conn:
                self._purge_expired(conn, now=time.time())
                conn.execute(
                    """
                    INSERT INTO panel_staged_proposals (
                        proposal_id, artifact_id, intent_event_json, proposed_at,
                        trace_id, proposal_origin, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(proposal_id) DO UPDATE SET
                        artifact_id=excluded.artifact_id,
                        intent_event_json=excluded.intent_event_json,
                        proposed_at=excluded.proposed_at,
                        trace_id=excluded.trace_id,
                        proposal_origin=excluded.proposal_origin,
                        updated_at=excluded.updated_at
                    """,
                    (
                        proposal_id,
                        proposal.artifact_id,
                        proposal.intent_event.model_dump_json(),
                        float(proposal.proposed_at),
                        proposal.trace_id,
                        proposal.proposal_origin,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
        except Exception as exc:
            self._degraded_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("panel proposal store degraded to memory-only: %s", exc)

    def get(self, proposal_id: str) -> StagedProposal | None:
        return self._proposals.get(proposal_id)

    def count_for_artifact(self, artifact_id: str) -> int:
        return sum(
            1 for proposal in self._proposals.values() if proposal.artifact_id == artifact_id
        )

    def clear(self) -> None:
        self._proposals.clear()
        if self._db_path is None or self.degraded:
            return
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM panel_staged_proposals")
                conn.commit()
        except Exception as exc:
            self._degraded_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("panel proposal store clear degraded to memory-only: %s", exc)


class ConfirmIdempotencyStore:
    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        retention_seconds: float | None = None,
    ) -> None:
        self._cache: dict[str, ConfirmResponse] = {}
        self._db_path = Path(db_path).expanduser() if db_path is not None else None
        self._retention_seconds = (
            float(retention_seconds)
            if retention_seconds is not None
            else _resolve_panel_staging_retention_seconds()
        )
        self._degraded_reason: str | None = None
        if self._db_path is not None:
            self._initialize()

    @classmethod
    def durable_default(cls) -> "ConfirmIdempotencyStore":
        return cls(
            _resolve_panel_staging_db_path(),
            retention_seconds=_resolve_panel_staging_retention_seconds(),
        )

    @property
    def mode(self) -> str:
        if self._db_path is None:
            return "memory"
        if self.degraded:
            return "memory-degraded"
        return "sqlite"

    @property
    def degraded(self) -> bool:
        return self._degraded_reason is not None

    @property
    def degraded_reason(self) -> str | None:
        return self._degraded_reason

    @property
    def db_path(self) -> Path | None:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        if self._db_path is None:
            raise RuntimeError("idempotency store is memory-only")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        try:
            with self._connect() as conn:
                for stmt in PANEL_STAGING_DDL:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT OR REPLACE INTO panel_confirmation_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(PANEL_STAGING_SCHEMA_VERSION)),
                )
                self._purge_expired(conn, now=time.time())
                rows = conn.execute(
                    "SELECT key, response_json FROM panel_confirm_idempotency ORDER BY created_at ASC"
                ).fetchall()
                conn.commit()
            self._cache = {
                str(row["key"]): ConfirmResponse.model_validate_json(
                    str(row["response_json"])
                )
                for row in rows
            }
            self._degraded_reason = None
        except Exception as exc:
            self._degraded_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("panel idempotency store degraded to memory-only: %s", exc)

    def _purge_expired(self, conn: sqlite3.Connection, *, now: float) -> None:
        cutoff = now - self._retention_seconds
        conn.execute(
            "DELETE FROM panel_confirm_idempotency WHERE created_at < ?",
            (cutoff,),
        )

    def get(self, key: str) -> ConfirmResponse | None:
        return self._cache.get(key)

    def set(self, key: str, response: ConfirmResponse) -> None:
        self._cache[key] = response
        if self._db_path is None or self.degraded:
            return
        try:
            now = time.time()
            now_iso = _utc_now_iso()
            with self._connect() as conn:
                self._purge_expired(conn, now=now)
                conn.execute(
                    """
                    INSERT INTO panel_confirm_idempotency (
                        key, response_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        response_json=excluded.response_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        key,
                        response.model_dump_json(),
                        now,
                        now_iso,
                    ),
                )
                conn.commit()
        except Exception as exc:
            self._degraded_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("panel idempotency store degraded to memory-only: %s", exc)

    def clear(self) -> None:
        self._cache.clear()
        if self._db_path is None or self.degraded:
            return
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM panel_confirm_idempotency")
                conn.commit()
        except Exception as exc:
            self._degraded_reason = f"{type(exc).__name__}: {exc}"
            logger.warning("panel idempotency store clear degraded to memory-only: %s", exc)


def panel_staging_store_posture() -> dict[str, Any]:
    degraded_reasons = [
        reason
        for reason in (
            _proposal_store.degraded_reason,
            _idempotency_store.degraded_reason,
        )
        if reason
    ]
    paths = {
        str(path)
        for path in (_proposal_store.db_path, _idempotency_store.db_path)
        if path is not None
    }
    return {
        "proposal_store_mode": _proposal_store.mode,
        "idempotency_store_mode": _idempotency_store.mode,
        "degraded": bool(degraded_reasons),
        "degraded_reason": "; ".join(degraded_reasons) if degraded_reasons else None,
        "db_path": sorted(paths)[0] if paths else None,
        "pending_proposal_count": len(_proposal_store._proposals),
        "idempotency_key_count": len(_idempotency_store._cache),
    }


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _emit_projection_event(
    event_name: str,
    payload: dict[str, Any],
    trace_id: str,
    outbox_path: Path | None = None,
) -> None:
    evt = make_outbox_event(
        event=event_name,
        source="panel_agent.confirmation",
        payload=payload,
        trace_id=trace_id,
    )
    # Write to JSONL audit log
    resolved = outbox_path or _resolve_outbox_path()
    try:
        append_jsonl_outbox_event(resolved, evt, default_source="panel_agent.confirmation")
    except Exception:
        logger.debug("projection event jsonl write skipped event=%s", event_name)
    # Mirror to DB outbox when backend is pg (same pattern as panel_agent/runtime.py)
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend == "pg" or db_url:
        outbox_evt = coerce_outbox_event(evt, default_source="panel_agent.confirmation")
        if outbox_evt is not None:
            try:
                write_outbox_event(outbox_evt, idempotency_key=outbox_evt.event_id)
            except Exception as exc:
                logger.debug("projection event db outbox write skipped event=%s err=%s", event_name, exc)


def _resolve_note_file(note_path: str | None) -> Path | None:
    if not note_path:
        return None
    vault_root_env = os.getenv("VAULT_ROOT") or os.getenv("WATCHER_VAULT_PATH")
    candidate = Path(note_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if vault_root_env:
        candidate = Path(vault_root_env).expanduser() / note_path
        if candidate.exists():
            return candidate
    return None


def _write_rejected_projection(proposal: StagedProposal) -> None:
    """Remove the proposed checkbox from the vault on rejection (no execution receipt)."""
    note_path = proposal.intent_event.payload.note.path
    note_file = _resolve_note_file(note_path)
    if note_file is None:
        return
    try:
        current = note_file.read_text(encoding="utf-8")
    except OSError:
        return

    action_ids = {
        stable_action_id(a.label)
        for a in proposal.intent_event.payload.actions
    }
    annotated = annotate_action_ids(current)
    updated = remove_actions_from_markdown(annotated, action_ids)

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    receipt_lines = [
        f"❌ {a.label} — dismissed — {now_iso}"
        for a in proposal.intent_event.payload.actions
    ]
    if receipt_lines:
        updated = write_receipts(updated, receipt_lines)

    try:
        note_file.write_text(updated, encoding="utf-8")
    except OSError:
        logger.debug("rejected projection vault write failed note_path=%s", note_path)


def _apply_correction(
    intent_event: "PanelIntentEvent",
    correction: CorrectionFields,
) -> "PanelIntentEvent":
    """Return a deep copy of intent_event with the correction applied.

    If correction.corrected_action_id is set, that action becomes the selected
    action for confirmation. If corrected_parameters is also set, parameters are
    merged into the selected action only. The original proposal is never mutated.
    """
    corrected = intent_event.model_copy(deep=True)
    for action in corrected.payload.actions:
        target = correction.corrected_action_id is None or action.id == correction.corrected_action_id
        if correction.corrected_action_id is not None:
            action.checked = target
        if target and correction.corrected_parameters is not None and action.mapping is not None:
            action.mapping.params = {**action.mapping.params, **correction.corrected_parameters}
    return corrected


def _write_blocked_projection(
    proposal: StagedProposal,
    gate: str,
    reason: str,
) -> None:
    """Write blocked receipt to AI status callout; preserve the proposed checkbox."""
    note_path = proposal.intent_event.payload.note.path
    note_file = _resolve_note_file(note_path)
    if note_file is None:
        return
    try:
        current = note_file.read_text(encoding="utf-8")
    except OSError:
        return

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    receipt_lines = [
        f"🚫 {a.label} — blocked — gate: {gate} — {now_iso}"
        for a in proposal.intent_event.payload.actions
    ]
    if reason:
        receipt_lines.append(f"Reason: {reason}")

    updated = write_receipts(current, receipt_lines)
    try:
        note_file.write_text(updated, encoding="utf-8")
    except OSError:
        logger.debug("blocked projection vault write failed note_path=%s", note_path)


class PanelConfirmationService:
    def __init__(
        self,
        proposal_store: ProposalStore,
        idempotency_store: ConfirmIdempotencyStore,
        write_guard: WriteGuard | None = None,
        same_turn_ttl: float = SAME_TURN_TTL_SECONDS,
    ) -> None:
        self._proposals = proposal_store
        self._idempotency = idempotency_store
        self._guard = write_guard or DEFAULT_WRITE_GUARD
        self._ttl = same_turn_ttl

    def confirm(self, request: ConfirmRequest) -> ConfirmResponse:
        cached = self._idempotency.get(request.idempotency_key)
        if cached is not None:
            return cached

        proposal = self._proposals.get(request.proposal_id)
        if proposal is None:
            raise UnknownProposalError(request.proposal_id)

        if proposal.artifact_id != request.artifact_id:
            raise ValueError("proposal does not belong to artifact_id")

        if (time.time() - proposal.proposed_at) < self._ttl:
            raise SameTurnExecutionError(
                "same-turn execution is not allowed — proposal was staged in the current interaction window"
            )

        try:
            self._guard.assert_writes_allowed("panel.confirm")
        except WritesBlockedError as exc:
            if request.action == "reject":
                # Rejection is a user decision, not an execution; vault write is safe even when
                # execution is blocked, but we still honour WriteGuard to keep the single-writer
                # rule uniform. Skip vault write; record rejected outcome without receipt.
                resp = ConfirmResponse(
                    proposal_id=request.proposal_id,
                    artifact_id=request.artifact_id,
                    status="rejected",
                    outcome="rejected",
                    idempotency_key=request.idempotency_key,
                    events_emitted=[],
                )
                self._idempotency.set(request.idempotency_key, resp)
                return resp
            _write_blocked_projection(
                proposal,
                gate="writeguard",
                reason=str(exc),
            )
            _emit_projection_event(
                "panel.action.blocked",
                {
                    "note_uuid": proposal.intent_event.payload.note.uuid,
                    "note_path": proposal.intent_event.payload.note.path,
                    "gate": "writeguard",
                    "reason": str(exc),
                    "proposal_id": request.proposal_id,
                },
                trace_id=proposal.trace_id or request.idempotency_key,
            )
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="blocked",
                outcome="blocked",
                block_reason=BlockReason(gate="writeguard", message=str(exc)),
                idempotency_key=request.idempotency_key,
                events_emitted=["panel.action.blocked"],
            )
            self._idempotency.set(request.idempotency_key, resp)
            return resp

        if request.action == "reject":
            _write_rejected_projection(proposal)
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="rejected",
                outcome="rejected",
                idempotency_key=request.idempotency_key,
                events_emitted=[],
            )
            self._idempotency.set(request.idempotency_key, resp)
            return resp

        import app.panel.confirmation as _self_mod

        if request.correction and request.correction.enabled:
            corrected_event = _apply_correction(proposal.intent_event, request.correction)
            result = _self_mod.execute_panel_intent(corrected_event)
        else:
            result = _self_mod.execute_panel_intent(proposal.intent_event)
        events: list[str] = []
        for e in result.emitted_events:
            if isinstance(e, dict):
                events.append(e.get("event", ""))
            else:
                events.append(getattr(e, "event", str(e)))

        # Classify outcome: if all checked actions were logged (not triggered), surface as logged.
        checked_actions = [a for a in result.actions if a.checked]
        all_logged = bool(checked_actions) and all(a.status == "logged" for a in checked_actions)
        any_triggered = any(a.status == "triggered" for a in checked_actions)

        now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

        is_corrected = bool(request.correction and request.correction.enabled)
        correction_note = "corrected" if is_corrected else None

        if all_logged and not any_triggered:
            # Logged outcome: emit panel.action.logged if not already present
            if "panel.action.logged" not in events:
                _emit_projection_event(
                    "panel.action.logged",
                    {
                        "note_uuid": proposal.intent_event.payload.note.uuid,
                        "note_path": proposal.intent_event.payload.note.path,
                        "proposal_id": request.proposal_id,
                    },
                    trace_id=proposal.trace_id or request.idempotency_key,
                )
                events.append("panel.action.logged")
            receipt = Receipt(
                action_taken="confirm",
                outcome="logged",
                timestamp=now_iso,
                message=correction_note,
            )
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="logged",
                outcome="logged",
                receipt=receipt,
                idempotency_key=request.idempotency_key,
                events_emitted=events,
            )
        else:
            # Executed outcome: extract inverse_action from result if declared.
            inverse_action: str | None = None
            for action_result in result.actions:
                inv = (action_result.details or {}).get("inverse_action_id")
                if inv:
                    inverse_action = str(inv)
                    break

            receipt = Receipt(
                action_taken="confirm",
                outcome="success",
                timestamp=now_iso,
                inverse_action=inverse_action,
                message=correction_note,
            )
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="executed",
                outcome="success",
                receipt=receipt,
                idempotency_key=request.idempotency_key,
                events_emitted=events,
            )

        self._idempotency.set(request.idempotency_key, resp)
        return resp


_proposal_store = ProposalStore.durable_default()
_idempotency_store = ConfirmIdempotencyStore.durable_default()
_service = PanelConfirmationService(_proposal_store, _idempotency_store)

__all__ = [
    "BlockReason",
    "ConfirmIdempotencyStore",
    "ConfirmRequest",
    "ConfirmResponse",
    "PanelConfirmationService",
    "panel_staging_store_posture",
    "ProposalStore",
    "Receipt",
    "SameTurnExecutionError",
    "StagedProposal",
    "UnknownProposalError",
    "_idempotency_store",
    "_proposal_store",
    "_service",
]
