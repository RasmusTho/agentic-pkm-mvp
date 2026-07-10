"""File-first, restart-safe records for pre-ticket BuilderOps inquiries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import fcntl
from contextlib import contextmanager
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from app.builderops.config import load_paths
from app.builderops.models import (
    BuilderOpsConflictError,
    BuilderOpsValidationError,
    normalize_actor,
    normalize_record,
    utc_now,
    validate_source_refs,
)
from app.builderops.vault_queue import (
    VaultQueueError,
    _require_within_vault,
    _trusted_vault_root,
)

INQUIRY_SCHEMA = "builderops.model-inquiry.v1"
QUESTION_SCHEMA = "builderops.model-inquiry-question.v1"
TURN_SCHEMA = "builderops.model-inquiry-turn.v1"
SYNTHESIS_SCHEMA = "builderops.model-inquiry-synthesis.v1"
READINESS_SCHEMA = "builderops.model-inquiry-readiness.v1"
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
READINESS_OUTCOMES = frozenset({"issue_ready", "needs_input", "not_ready"})
TERMINAL_TURN_OUTCOMES = frozenset({"accepted", "completed", "failed", "not_ready", "refused"})
_INQUIRY_LOCKS_GUARD = threading.Lock()
_INQUIRY_LOCKS: dict[str, threading.RLock] = {}


class ModelInquiryService:
    """Persist immutable inquiry artifacts in the configured shared BuilderOps vault."""

    def __init__(self, vault_root: Path) -> None:
        try:
            self._vault_root = _trusted_vault_root(Path(vault_root))
        except VaultQueueError as exc:
            raise BuilderOpsValidationError(str(exc)) from exc
        if not self._vault_root.is_dir():
            raise BuilderOpsValidationError(
                f"BUILDEROPS_VAULT_ROOT is unavailable: {self._vault_root}"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ModelInquiryService":
        try:
            paths = load_paths(dict(env) if env is not None else None)
        except ValueError as exc:
            raise BuilderOpsValidationError(str(exc)) from exc
        if paths.vault_root is None:
            raise BuilderOpsValidationError(
                "BUILDEROPS_VAULT_ROOT is required for model inquiries"
            )
        return cls(paths.vault_root)

    def start(
        self,
        *,
        question: str,
        workflow: str,
        source_refs: list[dict[str, Any]],
        created_by: Mapping[str, Any] | str | None = None,
        inquiry_id: str | None = None,
        after_persist: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        question = _nonempty(question, "question")
        workflow = _safe_id(workflow, "workflow")
        validate_source_refs(source_refs)
        actor = normalize_actor(created_by)
        inquiry_id = _safe_id(inquiry_id or _new_inquiry_id(), "inquiry_id")
        directory = self._inquiry_dir(inquiry_id, create=True)
        question_path = directory / "question.json"
        question_existing = self._read_optional(question_path)
        question_payload: dict[str, Any] = {
            "schema": QUESTION_SCHEMA,
            "artifact_id": "question",
            "inquiry_id": inquiry_id,
            "workflow": workflow,
            "content": question,
            "content_hash": _content_hash(question),
            "source_refs": source_refs,
            "created_by": actor,
            "created_at": _existing_timestamp(question_existing),
        }
        question_payload["artifact_hash"] = _artifact_hash(question_payload)
        self._write_immutable(
            question_path,
            question_payload,
            label="immutable question artifact",
        )

        receipt = self._start_receipt(
            inquiry_id,
            question_payload,
            source_refs=source_refs,
            actor=actor,
        )
        manifest_path = directory / "manifest.json"
        manifest_existing = self._read_optional(manifest_path)
        manifest = {
            "schema": INQUIRY_SCHEMA,
            "inquiry_id": inquiry_id,
            "workflow": workflow,
            "question_artifact_id": "question",
            "question_content_hash": question_payload["content_hash"],
            "question_artifact_hash": question_payload["artifact_hash"],
            "start_receipt_id": receipt["id"],
            "source_refs": source_refs,
            "created_by": actor,
            "created_at": _existing_timestamp(
                manifest_existing,
                fallback=question_payload["created_at"],
            ),
        }
        manifest["artifact_hash"] = _artifact_hash(manifest)
        self._write_immutable(
            manifest_path,
            manifest,
            label="immutable inquiry manifest",
        )
        trace = self.trace(inquiry_id)
        if after_persist is not None:
            after_persist(inquiry_id)
        return trace

    def commit_turn(
        self,
        inquiry_id: str,
        *,
        turn_id: str,
        sequence: int,
        role: str,
        content: str,
        input_artifact_refs: list[str],
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        safe_inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        lock = _inquiry_lock(self._vault_root, safe_inquiry_id)
        with lock:
            with self._inquiry_process_lock(safe_inquiry_id):
                return self._commit_turn_locked(
                    safe_inquiry_id,
                    turn_id=turn_id,
                    sequence=sequence,
                    role=role,
                    content=content,
                    input_artifact_refs=input_artifact_refs,
                    source_refs=source_refs,
                )

    def _commit_turn_locked(
        self,
        inquiry_id: str,
        *,
        turn_id: str,
        sequence: int,
        role: str,
        content: str,
        input_artifact_refs: list[str],
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        turn_id = _safe_id(turn_id, "turn_id")
        role = _safe_id(role, "role")
        content = _nonempty(content, "turn content")
        _validate_sequence(sequence)
        _validate_artifact_refs(input_artifact_refs)
        validate_source_refs(source_refs)
        directory = self._require_inquiry(inquiry_id)
        # Sequence is the atomic reservation key. Two concurrent writers for the
        # same successor slot therefore contend on one no-overwrite pathname.
        path = directory / "turns" / f"{sequence:06d}.json"
        existing = self._read_optional(path)
        for committed in self._read_turns(directory, inquiry_id, allow_orphans=True):
            if committed["turn_id"] == turn_id and committed["sequence"] != sequence:
                raise BuilderOpsConflictError(f"immutable turn id already exists: {turn_id}")
            if committed["sequence"] == sequence and committed["turn_id"] != turn_id:
                raise BuilderOpsConflictError(
                    f"turn sequence already exists for {committed['turn_id']}: {sequence}"
                )
        payload = {
            "schema": TURN_SCHEMA,
            "artifact_id": turn_id,
            "turn_id": turn_id,
            "inquiry_id": inquiry_id,
            "sequence": sequence,
            "role": role,
            "content": content,
            "content_hash": _content_hash(content),
            "input_artifact_refs": input_artifact_refs,
            "source_refs": source_refs,
            "created_at": _existing_timestamp(existing),
        }
        payload["artifact_hash"] = _artifact_hash(payload)
        reservation_path = directory / "turn-ids" / f"{turn_id}.json"
        _, reservation_created = self._write_immutable_status(
            reservation_path,
            {
                "schema": "builderops.model-inquiry-turn-reservation.v1",
                "inquiry_id": inquiry_id,
                "turn_id": turn_id,
                "sequence": sequence,
                "artifact_hash": payload["artifact_hash"],
            },
            label="immutable turn id reservation",
        )
        try:
            return self._write_immutable(path, payload, label="immutable turn artifact")
        except BuilderOpsConflictError:
            self._reconcile_failed_turn_reservation(
                directory,
                reservation_path,
                turn_id=turn_id,
                sequence=sequence,
                artifact_hash=cast(str, payload["artifact_hash"]),
                created_by_this_attempt=reservation_created,
            )
            raise

    def commit_synthesis(
        self,
        inquiry_id: str,
        *,
        content: str,
        input_artifact_refs: list[str],
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        content = _nonempty(content, "synthesis content")
        _validate_artifact_refs(input_artifact_refs)
        validate_source_refs(source_refs)
        directory = self._require_inquiry(inquiry_id)
        path = directory / "synthesis.json"
        existing = self._read_optional(path)
        payload = {
            "schema": SYNTHESIS_SCHEMA,
            "artifact_id": "synthesis",
            "inquiry_id": inquiry_id,
            "content": content,
            "content_hash": _content_hash(content),
            "input_artifact_refs": input_artifact_refs,
            "source_refs": source_refs,
            "created_at": _existing_timestamp(existing),
        }
        payload["artifact_hash"] = _artifact_hash(payload)
        return self._write_immutable(path, payload, label="immutable synthesis artifact")

    def commit_readiness(
        self,
        inquiry_id: str,
        *,
        outcome: str,
        rationale: str,
        input_artifact_refs: list[str],
        source_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        if outcome not in READINESS_OUTCOMES:
            raise BuilderOpsValidationError(f"unsupported readiness outcome: {outcome}")
        rationale = _nonempty(rationale, "readiness rationale")
        _validate_artifact_refs(input_artifact_refs)
        validate_source_refs(source_refs)
        directory = self._require_inquiry(inquiry_id)
        path = directory / "readiness.json"
        existing = self._read_optional(path)
        content_hash = _content_hash(
            json.dumps(
                {"outcome": outcome, "rationale": rationale},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        payload = {
            "schema": READINESS_SCHEMA,
            "artifact_id": "readiness",
            "inquiry_id": inquiry_id,
            "outcome": outcome,
            "rationale": rationale,
            "content_hash": content_hash,
            "input_artifact_refs": input_artifact_refs,
            "source_refs": source_refs,
            "created_at": _existing_timestamp(existing),
        }
        payload["artifact_hash"] = _artifact_hash(payload)
        return self._write_immutable(path, payload, label="immutable readiness artifact")

    def commit_terminal_turn_receipt(
        self,
        inquiry_id: str,
        *,
        turn_id: str,
        outcome: str,
        source_refs: list[dict[str, Any]],
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        turn_id = _safe_id(turn_id, "turn_id")
        if outcome not in TERMINAL_TURN_OUTCOMES:
            raise BuilderOpsValidationError(f"unsupported terminal turn outcome: {outcome}")
        validate_source_refs(source_refs)
        actor_ref = normalize_actor(actor)
        directory = self._require_inquiry(inquiry_id)
        turn = next(
            (item for item in self._read_turns(directory, inquiry_id) if item["turn_id"] == turn_id),
            None,
        )
        if turn is None:
            raise BuilderOpsValidationError(f"inquiry turn not found: {turn_id}")
        path = directory / "receipts" / f"turn-{turn_id}-terminal.json"
        existing = self._read_optional(path)
        occurred_at = _existing_timestamp(existing)
        receipt = normalize_record(
            {
                "id": f"receipt_{inquiry_id}_{turn_id}_terminal",
                "object_type": "BuilderOpsReceipt",
                "summary": f"Terminal receipt for inquiry turn {turn_id}",
                "event_type": "inquiry_turn_terminal",
                "actor": actor_ref,
                "occurred_at": occurred_at,
                "target_refs": [
                    {
                        "ref_type": "builderops_inquiry_turn",
                        "ref": f"{inquiry_id}/{turn_id}",
                        "authority_surface": "builderops",
                    }
                ],
                "action": outcome,
                "receipt_body": f"Turn {turn_id} reached terminal outcome {outcome}.",
                "idempotency_key": f"inquiry:{inquiry_id}:turn:{turn_id}:terminal",
                "source_refs": source_refs,
                "created_by": actor_ref,
                "turn_content_hash": turn["content_hash"],
                "turn_artifact_hash": turn["artifact_hash"],
                "outcome": outcome,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
        )
        receipt["artifact_hash"] = _artifact_hash(receipt)
        return self._write_immutable(path, receipt, label="immutable terminal receipt")

    def trace(self, inquiry_id: str) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        directory = self._require_inquiry(inquiry_id)
        manifest = self._read_required(directory / "manifest.json")
        question = self._read_required(directory / "question.json")
        turns = self._read_turns(directory, inquiry_id)
        synthesis = self._read_optional(directory / "synthesis.json")
        readiness = self._read_optional(directory / "readiness.json")
        for artifact in [synthesis, readiness]:
            if artifact is not None and artifact.get("inquiry_id") != inquiry_id:
                raise BuilderOpsValidationError("foreign artifact in inquiry trace")
        receipts = self._read_receipts(directory)
        self._validate_manifest(manifest, question, receipts, inquiry_id)
        self._validate_artifact_graph(turns, synthesis, readiness)
        source_refs = _dedupe_source_refs(
            manifest.get("source_refs", []),
            question.get("source_refs", []),
            *(turn.get("source_refs", []) for turn in turns),
            *((artifact or {}).get("source_refs", []) for artifact in [synthesis, readiness]),
            *(receipt.get("source_refs", []) for receipt in receipts),
        )
        return {
            "inquiry": manifest,
            "question": question,
            "turns": turns,
            "synthesis": synthesis,
            "readiness": readiness,
            "receipts": receipts,
            "source_refs": source_refs,
            "completeness": {
                "ok": True,
                "question": True,
                "turn_count": len(turns),
                "synthesis": synthesis is not None,
                "readiness": readiness is not None,
            },
        }

    def resume(self, inquiry_id: str) -> dict[str, Any]:
        trace = self.trace(inquiry_id)
        terminal_by_turn: dict[str, str] = {}
        for receipt in trace["receipts"]:
            if receipt.get("event_type") != "inquiry_turn_terminal":
                continue
            outcome = receipt.get("outcome")
            if outcome not in TERMINAL_TURN_OUTCOMES:
                continue
            for turn in trace["turns"]:
                expected_ref = f"{inquiry_id}/{turn['turn_id']}"
                expected_id = f"receipt_{inquiry_id}_{turn['turn_id']}_terminal"
                expected_key = f"inquiry:{inquiry_id}:turn:{turn['turn_id']}:terminal"
                if (
                    receipt.get("id") == expected_id
                    and receipt.get("idempotency_key") == expected_key
                    and receipt.get("action") == outcome
                    and receipt.get("turn_content_hash") == turn["content_hash"]
                    and receipt.get("turn_artifact_hash") == turn["artifact_hash"]
                    and any(
                        ref.get("ref_type") == "builderops_inquiry_turn"
                        and ref.get("ref") == expected_ref
                        for ref in receipt.get("target_refs", [])
                    )
                ):
                    terminal_by_turn[turn["turn_id"]] = receipt["id"]
        skipped = [
            turn["turn_id"] for turn in trace["turns"] if turn["turn_id"] in terminal_by_turn
        ]
        pending = [
            turn["turn_id"] for turn in trace["turns"] if turn["turn_id"] not in terminal_by_turn
        ]
        next_sequence = max((turn["sequence"] for turn in trace["turns"]), default=-1) + 1
        return {
            "inquiry_id": inquiry_id,
            "skipped_turn_ids": skipped,
            "pending_turn_ids": pending,
            "terminal_receipt_ids": [terminal_by_turn[turn_id] for turn_id in skipped],
            "next_sequence": next_sequence,
        }

    def _start_receipt(
        self,
        inquiry_id: str,
        question: dict[str, Any],
        *,
        source_refs: list[dict[str, Any]],
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        directory = self._inquiry_dir(inquiry_id, create=True)
        path = directory / "receipts" / "inquiry-started.json"
        existing = self._read_optional(path)
        occurred_at = _existing_timestamp(existing, fallback=question["created_at"])
        receipt = normalize_record(
            {
                "id": f"receipt_{inquiry_id}_started",
                "object_type": "BuilderOpsReceipt",
                "summary": f"Started model inquiry {inquiry_id}",
                "event_type": "inquiry_started",
                "actor": actor,
                "occurred_at": occurred_at,
                "target_refs": [
                    {
                        "ref_type": "builderops_inquiry_question",
                        "ref": f"{inquiry_id}/question",
                        "authority_surface": "builderops",
                    }
                ],
                "action": "persist_question",
                "receipt_body": "Persisted immutable inquiry question before successor execution.",
                "idempotency_key": f"inquiry:{inquiry_id}:start",
                "source_refs": source_refs,
                "created_by": actor,
                "question_content_hash": question["content_hash"],
                "question_artifact_hash": question["artifact_hash"],
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
        )
        receipt["artifact_hash"] = _artifact_hash(receipt)
        return self._write_immutable(path, receipt, label="immutable inquiry start receipt")

    def _inquiries_root(self, *, create: bool) -> Path:
        path = self._vault_root / "model-inquiries"
        if path.is_symlink():
            raise BuilderOpsValidationError(f"model inquiry root must not be a symlink: {path}")
        if create:
            try:
                _mkdir_durable(path)
            except OSError as exc:
                raise BuilderOpsValidationError(
                    f"unable to create model inquiry root: {path}"
                ) from exc
        resolved = path.resolve(strict=False)
        self._require_within_vault(resolved, label="model inquiry root")
        return resolved

    def _inquiry_dir(self, inquiry_id: str, *, create: bool) -> Path:
        root = self._inquiries_root(create=create)
        path = root / inquiry_id
        if path.is_symlink():
            raise BuilderOpsValidationError(f"inquiry directory must not be a symlink: {path}")
        if create:
            try:
                _mkdir_durable(path)
            except OSError as exc:
                raise BuilderOpsValidationError(
                    f"unable to create inquiry directory: {path}"
                ) from exc
            for child in ("turns", "turn-ids", "receipts"):
                child_path = path / child
                if child_path.is_symlink():
                    raise BuilderOpsValidationError(
                        f"inquiry artifact directory must not be a symlink: {child_path}"
                    )
                try:
                    _mkdir_durable(child_path)
                except OSError as exc:
                    raise BuilderOpsValidationError(
                        f"unable to create inquiry artifact directory: {child_path}"
                    ) from exc
        resolved = path.resolve(strict=False)
        self._require_within_vault(resolved, label="inquiry directory")
        return resolved

    def _require_inquiry(self, inquiry_id: str) -> Path:
        directory = self._inquiry_dir(inquiry_id, create=False)
        if not directory.is_dir() or not (directory / "manifest.json").is_file():
            raise BuilderOpsValidationError(f"model inquiry not found: {inquiry_id}")
        return directory

    @contextmanager
    def _inquiry_process_lock(self, inquiry_id: str) -> Iterator[None]:
        directory = self._require_inquiry(inquiry_id)
        path = directory / ".turn-commit.lock"
        self._validate_artifact_parent(path)
        if path.is_symlink():
            raise BuilderOpsValidationError(f"turn commit lock must not be a symlink: {path}")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        existed = path.exists()
        descriptor: int | None = None
        locked = False
        try:
            descriptor = os.open(path, flags, 0o600)
            if not existed:
                _fsync_directory(path.parent)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            yield
        except OSError as exc:
            raise BuilderOpsValidationError(f"unable to lock model inquiry: {inquiry_id}") from exc
        finally:
            if descriptor is not None:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _read_turns(
        self,
        directory: Path,
        inquiry_id: str,
        *,
        allow_orphans: bool = False,
    ) -> list[dict[str, Any]]:
        turns_dir = directory / "turns"
        reservations_dir = directory / "turn-ids"
        if turns_dir.is_symlink():
            raise BuilderOpsValidationError(f"turn directory must not be a symlink: {turns_dir}")
        if reservations_dir.is_symlink():
            raise BuilderOpsValidationError(
                f"turn reservation directory must not be a symlink: {reservations_dir}"
            )
        turn_files = [
            (path, self._read_required(path)) for path in sorted(turns_dir.glob("*.json"))
        ]
        turns = [turn for _, turn in turn_files]
        reservation_files = sorted(reservations_dir.glob("*.json"))
        seen_ids: set[str] = set()
        seen_sequences: set[int] = set()
        for path, turn in turn_files:
            if turn.get("schema") != TURN_SCHEMA or turn.get("inquiry_id") != inquiry_id:
                raise BuilderOpsValidationError("invalid or foreign turn artifact")
            turn_id = _safe_id(str(turn.get("turn_id", "")), "turn_id")
            if turn.get("artifact_id") != turn_id:
                raise BuilderOpsValidationError(f"turn artifact id mismatch: {turn_id}")
            sequence = turn.get("sequence")
            _validate_sequence(sequence)
            sequence = cast(int, sequence)
            if path.name != f"{sequence:06d}.json":
                raise BuilderOpsValidationError(f"turn sequence filename mismatch: {path.name}")
            if turn_id in seen_ids or sequence in seen_sequences:
                raise BuilderOpsValidationError("duplicate inquiry turn id or sequence")
            content = turn.get("content")
            if not isinstance(content, str) or not content.strip():
                raise BuilderOpsValidationError(f"invalid turn content: {turn_id}")
            if turn.get("content_hash") != _content_hash(content):
                raise BuilderOpsValidationError(f"turn content hash mismatch: {turn_id}")
            _safe_id(str(turn.get("role", "")), "role")
            _validate_persisted_artifact_refs(turn.get("input_artifact_refs"))
            _validate_persisted_source_refs(turn.get("source_refs"))
            _validate_artifact_hash(turn, label=f"turn {turn_id}")
            reservation = self._read_required(reservations_dir / f"{turn_id}.json")
            expected_reservation = {
                "schema": "builderops.model-inquiry-turn-reservation.v1",
                "inquiry_id": inquiry_id,
                "turn_id": turn_id,
                "sequence": sequence,
                "artifact_hash": turn["artifact_hash"],
            }
            if reservation != expected_reservation:
                raise BuilderOpsValidationError(f"turn id reservation mismatch: {turn_id}")
            seen_ids.add(turn_id)
            seen_sequences.add(sequence)
        committed_ids = {turn["turn_id"] for turn in turns}
        reserved_ids = {path.stem for path in reservation_files}
        if not allow_orphans and reserved_ids != committed_ids:
            orphaned = sorted(reserved_ids - committed_ids)
            missing = sorted(committed_ids - reserved_ids)
            raise BuilderOpsValidationError(
                f"turn reservation graph mismatch: orphaned={orphaned}, missing={missing}"
            )
        return sorted(turns, key=lambda item: (item["sequence"], item["turn_id"]))

    def _read_receipts(self, directory: Path) -> list[dict[str, Any]]:
        receipts_dir = directory / "receipts"
        if receipts_dir.is_symlink():
            raise BuilderOpsValidationError(f"receipt directory must not be a symlink: {receipts_dir}")
        receipts = [self._read_required(path) for path in sorted(receipts_dir.glob("*.json"))]
        seen_ids: set[str] = set()
        for receipt in receipts:
            try:
                normalized = normalize_record(receipt)
            except (TypeError, ValueError, KeyError) as exc:
                raise BuilderOpsValidationError("invalid BuilderOpsReceipt in inquiry") from exc
            if normalized != receipt:
                raise BuilderOpsValidationError("non-canonical BuilderOpsReceipt in inquiry")
            _validate_artifact_hash(receipt, label=f"receipt {receipt.get('id', '')}")
            receipt_id = str(receipt.get("id", ""))
            if receipt_id in seen_ids:
                raise BuilderOpsValidationError(f"duplicate inquiry receipt id: {receipt_id}")
            seen_ids.add(receipt_id)
        return receipts

    def _validate_manifest(
        self,
        manifest: dict[str, Any],
        question: dict[str, Any],
        receipts: list[dict[str, Any]],
        inquiry_id: str,
    ) -> None:
        if manifest.get("schema") != INQUIRY_SCHEMA or manifest.get("inquiry_id") != inquiry_id:
            raise BuilderOpsValidationError("invalid inquiry manifest")
        _validate_artifact_hash(manifest, label="manifest")
        if question.get("schema") != QUESTION_SCHEMA or question.get("inquiry_id") != inquiry_id:
            raise BuilderOpsValidationError("invalid inquiry question artifact")
        if question.get("artifact_id") != "question":
            raise BuilderOpsValidationError("invalid inquiry question artifact id")
        _safe_id(str(question.get("workflow", "")), "workflow")
        if manifest.get("workflow") != question.get("workflow"):
            raise BuilderOpsValidationError("manifest workflow mismatch")
        if not isinstance(question.get("content"), str) or not question["content"].strip():
            raise BuilderOpsValidationError("invalid inquiry question content")
        _validate_persisted_source_refs(question.get("source_refs"))
        _validate_persisted_source_refs(manifest.get("source_refs"))
        if question.get("content_hash") != _content_hash(str(question.get("content", ""))):
            raise BuilderOpsValidationError("question content hash mismatch")
        _validate_artifact_hash(question, label="question")
        if manifest.get("question_content_hash") != question["content_hash"]:
            raise BuilderOpsValidationError("manifest question hash mismatch")
        if manifest.get("question_artifact_hash") != question["artifact_hash"]:
            raise BuilderOpsValidationError("manifest question artifact hash mismatch")
        if manifest.get("question_artifact_id") != "question":
            raise BuilderOpsValidationError("manifest question artifact mismatch")
        start_receipt = next(
            (receipt for receipt in receipts if receipt.get("id") == manifest.get("start_receipt_id")),
            None,
        )
        if start_receipt is None:
            raise BuilderOpsValidationError("inquiry start receipt is missing")
        expected_ref = f"{inquiry_id}/question"
        if (
            start_receipt.get("event_type") != "inquiry_started"
            or start_receipt.get("id") != f"receipt_{inquiry_id}_started"
            or start_receipt.get("idempotency_key") != f"inquiry:{inquiry_id}:start"
            or start_receipt.get("action") != "persist_question"
            or start_receipt.get("question_content_hash") != question["content_hash"]
            or start_receipt.get("question_artifact_hash") != question["artifact_hash"]
            or not any(
                ref.get("ref_type") == "builderops_inquiry_question"
                and ref.get("ref") == expected_ref
                for ref in start_receipt.get("target_refs", [])
            )
        ):
            raise BuilderOpsValidationError("inquiry start receipt does not match question")

    def _validate_artifact_graph(
        self,
        turns: list[dict[str, Any]],
        synthesis: dict[str, Any] | None,
        readiness: dict[str, Any] | None,
    ) -> None:
        turn_sequences = {turn["turn_id"]: turn["sequence"] for turn in turns}
        available = {"question", *turn_sequences}
        for turn in turns:
            refs = set(turn.get("input_artifact_refs", []))
            if not refs or not refs <= available:
                raise BuilderOpsValidationError(
                    f"turn has dangling input artifact refs: {turn['turn_id']}"
                )
            for ref in refs & turn_sequences.keys():
                if turn_sequences[ref] >= turn["sequence"]:
                    raise BuilderOpsValidationError(
                        f"turn input sequence is not prior: {turn['turn_id']} -> {ref}"
                    )
        if synthesis is not None:
            self._validate_derived_artifact(
                synthesis,
                schema=SYNTHESIS_SCHEMA,
                artifact_id="synthesis",
                label="synthesis",
            )
            refs = set(synthesis.get("input_artifact_refs", []))
            if not refs or not refs <= available:
                raise BuilderOpsValidationError("synthesis has dangling input artifact refs")
            available.add("synthesis")
        if readiness is not None:
            self._validate_readiness_artifact(readiness)
            refs = set(readiness.get("input_artifact_refs", []))
            if not refs or not refs <= available:
                raise BuilderOpsValidationError("readiness has dangling input artifact refs")

    def _validate_derived_artifact(
        self,
        artifact: dict[str, Any],
        *,
        schema: str,
        artifact_id: str,
        label: str,
    ) -> None:
        if artifact.get("schema") != schema or artifact.get("artifact_id") != artifact_id:
            raise BuilderOpsValidationError(f"invalid {label} artifact")
        content = artifact.get("content")
        if not isinstance(content, str) or not content.strip():
            raise BuilderOpsValidationError(f"invalid {label} content")
        if artifact.get("content_hash") != _content_hash(content):
            raise BuilderOpsValidationError(f"{label} content hash mismatch")
        _validate_persisted_artifact_refs(artifact.get("input_artifact_refs"))
        _validate_persisted_source_refs(artifact.get("source_refs"))
        _validate_artifact_hash(artifact, label=label)

    def _validate_readiness_artifact(self, artifact: dict[str, Any]) -> None:
        if artifact.get("schema") != READINESS_SCHEMA or artifact.get("artifact_id") != "readiness":
            raise BuilderOpsValidationError("invalid readiness artifact")
        outcome = artifact.get("outcome")
        rationale = artifact.get("rationale")
        if outcome not in READINESS_OUTCOMES or not isinstance(rationale, str) or not rationale.strip():
            raise BuilderOpsValidationError("invalid readiness outcome or rationale")
        expected_hash = _content_hash(
            json.dumps(
                {"outcome": outcome, "rationale": rationale},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        if artifact.get("content_hash") != expected_hash:
            raise BuilderOpsValidationError("readiness content hash mismatch")
        _validate_persisted_artifact_refs(artifact.get("input_artifact_refs"))
        _validate_persisted_source_refs(artifact.get("source_refs"))
        _validate_artifact_hash(artifact, label="readiness")

    def _require_within_vault(self, candidate: Path, *, label: str) -> None:
        try:
            _require_within_vault(candidate, self._vault_root, label=label)
        except VaultQueueError as exc:
            raise BuilderOpsValidationError(str(exc)) from exc

    def _write_immutable(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        label: str,
    ) -> dict[str, Any]:
        result, _ = self._write_immutable_status(path, payload, label=label)
        return result

    def _write_immutable_status(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        label: str,
    ) -> tuple[dict[str, Any], bool]:
        self._validate_artifact_parent(path)
        if path.is_symlink():
            raise BuilderOpsConflictError(f"{label} path must not be a symlink: {path}")
        existing = self._read_optional(path)
        if existing is not None:
            if existing == payload:
                _fsync_directory(path.parent)
                return existing, False
            raise BuilderOpsConflictError(f"{label} conflicts with committed content: {path}")
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
            _fsync_directory(path.parent)
        except FileExistsError:
            existing = self._read_required(path)
            if existing == payload:
                _fsync_directory(path.parent)
                return existing, False
            raise BuilderOpsConflictError(f"{label} conflicts with committed content: {path}")
        except OSError as exc:
            raise BuilderOpsValidationError(f"unable to persist {label}: {path}") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return payload, True

    def _reconcile_failed_turn_reservation(
        self,
        directory: Path,
        reservation_path: Path,
        *,
        turn_id: str,
        sequence: int,
        artifact_hash: str,
        created_by_this_attempt: bool,
    ) -> None:
        expected = {
            "schema": "builderops.model-inquiry-turn-reservation.v1",
            "inquiry_id": directory.name,
            "turn_id": turn_id,
            "sequence": sequence,
            "artifact_hash": artifact_hash,
        }
        existing = self._read_optional(reservation_path)
        committed = any(
            turn.get("turn_id") == turn_id
            for turn in self._read_turn_files_without_reservations(directory)
        )
        if existing == expected and not committed:
            try:
                reservation_path.unlink()
                _fsync_directory(reservation_path.parent)
            except OSError as exc:
                qualifier = "new" if created_by_this_attempt else "recovered"
                raise BuilderOpsValidationError(
                    f"unable to remove {qualifier} orphan turn reservation: {reservation_path}"
                ) from exc

    def _read_turn_files_without_reservations(self, directory: Path) -> list[dict[str, Any]]:
        turns_dir = directory / "turns"
        if turns_dir.is_symlink():
            raise BuilderOpsValidationError(f"turn directory must not be a symlink: {turns_dir}")
        return [self._read_required(path) for path in sorted(turns_dir.glob("*.json"))]

    def _read_optional(self, path: Path) -> dict[str, Any] | None:
        self._validate_artifact_parent(path)
        if path.is_symlink():
            raise BuilderOpsValidationError(f"inquiry artifact must not be a symlink: {path}")
        if not path.exists():
            return None
        return self._read_required(path)

    def _read_required(self, path: Path) -> dict[str, Any]:
        self._validate_artifact_parent(path)
        if path.is_symlink():
            raise BuilderOpsValidationError(f"inquiry artifact must not be a symlink: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BuilderOpsValidationError(f"invalid inquiry artifact: {path}") from exc
        if not isinstance(payload, dict):
            raise BuilderOpsValidationError(f"inquiry artifact must be an object: {path}")
        return payload

    def _validate_artifact_parent(self, path: Path) -> None:
        if path.parent.is_symlink():
            raise BuilderOpsValidationError(
                f"inquiry artifact parent must not be a symlink: {path.parent}"
            )
        self._require_within_vault(path.parent.resolve(strict=False), label="inquiry artifact parent")


def _new_inquiry_id() -> str:
    return f"inq_{utc_now().replace('-', '').replace(':', '')}_{uuid4().hex[:8]}"


def _inquiry_lock(vault_root: Path, inquiry_id: str) -> threading.RLock:
    key = f"{vault_root}:{inquiry_id}"
    with _INQUIRY_LOCKS_GUARD:
        return _INQUIRY_LOCKS.setdefault(key, threading.RLock())


def _safe_id(value: str, field: str) -> str:
    value = str(value).strip()
    if not SAFE_ID_RE.fullmatch(value):
        raise BuilderOpsValidationError(f"{field} must be filename-safe")
    return value


def _nonempty(value: str, field: str) -> str:
    value = str(value).strip()
    if not value:
        raise BuilderOpsValidationError(f"{field} must be non-empty")
    return value


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "artifact_hash"}
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _content_hash(encoded)


def _validate_artifact_hash(payload: Mapping[str, Any], *, label: str) -> None:
    if payload.get("artifact_hash") != _artifact_hash(payload):
        raise BuilderOpsValidationError(f"{label} artifact hash mismatch")


def _existing_timestamp(
    existing: dict[str, Any] | None,
    *,
    fallback: str | None = None,
) -> str:
    if existing is not None and isinstance(existing.get("created_at"), str):
        return existing["created_at"]
    return fallback or utc_now()


def _validate_sequence(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BuilderOpsValidationError("turn sequence must be a non-negative integer")


def _validate_artifact_refs(refs: list[str]) -> None:
    if not isinstance(refs, list) or not refs:
        raise BuilderOpsValidationError("input_artifact_refs must be a non-empty list")
    for ref in refs:
        _safe_id(ref, "input artifact ref")


def _validate_persisted_artifact_refs(value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(ref, str) for ref in value):
        raise BuilderOpsValidationError("input_artifact_refs must be a list of strings")
    _validate_artifact_refs(value)


def _validate_persisted_source_refs(value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(ref, dict) for ref in value):
        raise BuilderOpsValidationError("source_refs must be a list of objects")
    validate_source_refs(value)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise BuilderOpsValidationError(f"unable to sync inquiry artifact directory: {path}") from exc


def _mkdir_durable(path: Path) -> None:
    existed = path.exists()
    path.mkdir(exist_ok=True)
    if not existed:
        _fsync_directory(path.parent)
        _fsync_directory(path)


def _dedupe_source_refs(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for ref in group:
            key = json.dumps(ref, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen.add(key)
                result.append(ref)
    return result


__all__ = ["ModelInquiryService"]
