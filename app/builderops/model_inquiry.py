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
from app.builderops.model_inquiry_contract import (
    MODEL_TURN_SYSTEM_PROMPT,
    canonical_hash,
    github_issue_url_matches,
    initial_context_packet,
    model_turn_request_hash,
)
from llm_contract import ADAPTER_FAILURE_CLASSES
from app.builderops.model_inquiry_report import render_markdown_report
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
PROMOTION_INTENT_SCHEMA = "builderops.model-inquiry-promotion-intent.v1"
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
# Mirrors the declared logical-secret grammar in app/ops/host_secret_contract.py.
CREDENTIAL_IDENTITY_RE = re.compile(r"[a-z][a-z0-9]{0,15}\.[a-z][a-z0-9-]{0,15}\Z")
CREDENTIAL_ATTEMPT_REQUEST_ID = "adapter_req_credential"
READINESS_OUTCOMES = frozenset({"issue_ready", "needs_input", "not_ready"})
TERMINAL_TURN_OUTCOMES = frozenset({"accepted", "completed", "failed", "not_ready", "refused"})
RUN_TERMINAL_OUTCOMES = frozenset(
    {
        "consensus",
        "degraded_consensus",
        "max_rounds_exhausted",
        "provider_refused",
        "malformed_output",
        "provider_unavailable",
        "provider_error",
        "persistence_failed",
    }
)
PROVIDER_TURN_FIELDS = frozenset(
    {
        "adapter_request_id",
        "provider_request_id",
        "adapter_id",
        "provider",
        "model",
        "context_hash",
        "request_hash",
        "input_hash",
        "output_hash",
        "phase",
        "round_index",
        "stance",
        "accepted_artifact_hash",
    }
)
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
        provider_metadata: Mapping[str, Any] | None = None,
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
                    provider_metadata=provider_metadata,
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
        provider_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        turn_id = _safe_id(turn_id, "turn_id")
        role = _safe_id(role, "role")
        content = _nonempty(content, "turn content")
        _validate_sequence(sequence)
        _validate_artifact_refs(input_artifact_refs)
        validate_source_refs(source_refs)
        normalized_provider_metadata = _validate_provider_metadata(provider_metadata)
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
        reservation_path = directory / "turn-ids" / f"{turn_id}.json"
        existing_reservation = self._read_optional(reservation_path)
        # An orphaned reservation (process loss between reserving the turn id and
        # committing the turn artifact -- see _reconcile_failed_turn_reservation)
        # already fixed this turn's identity, including its created_at. An exact
        # retry must reproduce that identity byte-for-byte so it recomputes the
        # SAME artifact_hash the reservation already holds, instead of minting a
        # fresh utc_now() that can cross a wall-clock second boundary and drift
        # the hash. A retry that is not exact (different content, sequence, role,
        # input refs, or provenance) still lands on a different artifact_hash (or
        # a different reservation "sequence" value) and fails closed at the
        # reservation write below, exactly like a rewrite of a committed turn.
        created_at = _existing_timestamp(
            existing,
            fallback=_reservation_timestamp(existing_reservation),
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
            "created_at": created_at,
        }
        payload.update(normalized_provider_metadata)
        payload["artifact_hash"] = _artifact_hash(payload)
        new_reservation: dict[str, Any] = {
            "schema": "builderops.model-inquiry-turn-reservation.v1",
            "inquiry_id": inquiry_id,
            "turn_id": turn_id,
            "sequence": sequence,
            "artifact_hash": payload["artifact_hash"],
        }
        # A reservation that crashed before this fix shipped has no created_at key.
        # Unconditionally writing one here would make every retry against it --
        # even an exact one -- fail strict dict-equality forever (new_reservation
        # can never equal a 5-key legacy record), permanently stranding a
        # genuinely pre-fix orphan instead of merely inheriting its old
        # same-second-luck retry odds. Only add created_at when there is no
        # legacy shape to stay compatible with: a brand-new reservation, or one
        # this fix already wrote.
        if existing_reservation is None or "created_at" in existing_reservation:
            new_reservation["created_at"] = created_at
        _, reservation_created = self._write_immutable_status(
            reservation_path,
            new_reservation,
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
                created_at=created_at,
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

    def commit_readiness_receipt(
        self,
        inquiry_id: str,
        *,
        source_refs: list[dict[str, Any]],
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        validate_source_refs(source_refs)
        trace = self.trace(inquiry_id)
        directory = self._require_inquiry(inquiry_id)
        readiness = trace.get("readiness")
        if not isinstance(readiness, dict):
            raise BuilderOpsValidationError("readiness receipt requires readiness evidence")
        outcome = str(readiness["outcome"])
        if outcome == "issue_ready" and readiness.get("input_artifact_refs") != ["synthesis"]:
            raise BuilderOpsValidationError("readiness receipt requires synthesis as sole input")
        if readiness.get("source_refs") != source_refs:
            raise BuilderOpsValidationError("readiness receipt source refs must match evidence")
        input_artifacts = _readiness_input_artifacts(
            question=trace["question"],
            turns=trace["turns"],
            synthesis=trace["synthesis"],
            readiness=readiness,
        )
        path = directory / "receipts" / "readiness-terminal.json"
        existing = self._read_optional(path)
        occurred_at = _existing_timestamp(existing, fallback=readiness["created_at"])
        actor_ref = normalize_actor(actor)
        receipt = normalize_record(
            {
                "id": f"receipt_{inquiry_id}_readiness_terminal",
                "object_type": "BuilderOpsReceipt",
                "summary": f"Model inquiry {inquiry_id} readiness is {outcome}",
                "event_type": "inquiry_readiness_terminal",
                "actor": actor_ref,
                "occurred_at": occurred_at,
                "target_refs": [
                    {
                        "ref_type": "builderops_inquiry",
                        "ref": inquiry_id,
                        "authority_surface": "builderops",
                    }
                ],
                "action": outcome,
                "receipt_body": f"Canonical readiness evaluation ended {outcome}.",
                "idempotency_key": f"inquiry:{inquiry_id}:readiness:terminal",
                "source_refs": source_refs,
                "created_by": actor_ref,
                "readiness_artifact_hash": readiness["artifact_hash"],
                "input_artifacts": input_artifacts,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
        )
        receipt["artifact_hash"] = _artifact_hash(receipt)
        return self._write_immutable(path, receipt, label="immutable readiness receipt")

    def commit_promotion_intent(
        self,
        inquiry_id: str,
        *,
        repository: str,
        marker: str,
        title: str,
        issue_body: str,
        source_refs: list[dict[str, Any]],
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        validate_source_refs(source_refs)
        directory = self._require_inquiry(inquiry_id)
        readiness = self._read_required(directory / "readiness.json")
        synthesis = self._read_required(directory / "synthesis.json")
        path = directory / "promotion-intent.json"
        existing = self._read_optional(path)
        actor_ref = normalize_actor(actor)
        payload = {
            "schema": PROMOTION_INTENT_SCHEMA,
            "artifact_id": "promotion-intent",
            "object_type": "PromotionIntent",
            "inquiry_id": inquiry_id,
            "target_authority_surface": "github_issue",
            "target_repository": repository,
            "promotion_marker": marker,
            "title": title,
            "issue_body": issue_body,
            "issue_body_hash": _content_hash(issue_body),
            "readiness_artifact_hash": readiness["artifact_hash"],
            "synthesis_artifact_hash": synthesis["artifact_hash"],
            "source_refs": source_refs,
            "created_by": actor_ref,
            "created_at": _existing_timestamp(existing),
        }
        payload["artifact_hash"] = _artifact_hash(payload)
        self._validate_promotion_intent(
            payload,
            inquiry_id=inquiry_id,
            readiness=readiness,
            synthesis=synthesis,
        )
        return self._write_immutable(path, payload, label="immutable promotion intent")

    def commit_promotion_receipt(
        self,
        inquiry_id: str,
        *,
        intent: Mapping[str, Any],
        issue_number: int,
        issue_url: str,
        issue_created_at: str,
        source_refs: list[dict[str, Any]],
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        if (
            isinstance(issue_number, bool)
            or not isinstance(issue_number, int)
            or issue_number < 1
        ):
            raise BuilderOpsValidationError("GitHub issue number must be positive")
        validate_source_refs(source_refs)
        directory = self._require_inquiry(inquiry_id)
        persisted_intent = self._read_required(directory / "promotion-intent.json")
        if dict(intent) != persisted_intent:
            raise BuilderOpsValidationError("promotion receipt intent does not match persisted intent")
        if source_refs != intent.get("source_refs"):
            raise BuilderOpsValidationError("promotion receipt source refs must match intent")
        if not github_issue_url_matches(
            issue_url,
            intent["target_repository"],
            issue_number,
        ):
            raise BuilderOpsValidationError("GitHub issue URL does not match target repository")
        if not isinstance(issue_created_at, str) or not issue_created_at.strip():
            raise BuilderOpsValidationError("GitHub issue created_at must be non-empty")
        path = directory / "receipts" / "promotion-github-issue.json"
        existing = self._read_optional(path)
        occurred_at = _existing_timestamp(existing, fallback=issue_created_at)
        actor_ref = normalize_actor(actor)
        issue_ref = f"{intent['target_repository']}#{issue_number}"
        receipt = normalize_record(
            {
                "id": f"receipt_{inquiry_id}_promotion_github_issue",
                "object_type": "BuilderOpsReceipt",
                "summary": f"Promoted model inquiry {inquiry_id} to GitHub Issue",
                "event_type": "inquiry_promotion_terminal",
                "actor": actor_ref,
                "occurred_at": occurred_at,
                "target_refs": [
                    {
                        "ref_type": "builderops_inquiry",
                        "ref": inquiry_id,
                        "authority_surface": "builderops",
                    },
                    {
                        "ref_type": "github_issue",
                        "ref": issue_ref,
                        "authority_surface": "github",
                    },
                ],
                "action": "promoted",
                "receipt_body": "Explicit REST promotion created or reconciled one GitHub Issue.",
                "idempotency_key": f"inquiry:{inquiry_id}:promotion:github_issue",
                "source_refs": source_refs,
                "created_by": actor_ref,
                "promotion_intent_artifact_hash": intent["artifact_hash"],
                "promotion_marker": intent["promotion_marker"],
                "github_issue_number": issue_number,
                "github_issue_url": issue_url,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
        )
        receipt["artifact_hash"] = _artifact_hash(receipt)
        return self._write_immutable(path, receipt, label="immutable promotion receipt")

    def commit_delivery_reference(
        self,
        inquiry_id: str,
        *,
        delivery_ref: Mapping[str, Any],
        source_refs: list[dict[str, Any]],
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        ref = dict(delivery_ref)
        validate_source_refs([ref], "delivery_ref")
        allowed = {"github_pull_request", "verification_receipt", "owner_doc"}
        if ref.get("ref_type") not in allowed:
            raise BuilderOpsValidationError(
                f"delivery ref_type must be one of: {', '.join(sorted(allowed))}"
            )
        validate_source_refs(source_refs)
        directory = self._require_inquiry(inquiry_id)
        ref_hash = canonical_hash(ref)[:24]
        path = directory / "receipts" / f"delivery-{ref_hash}.json"
        existing = self._read_optional(path)
        occurred_at = _existing_timestamp(existing)
        actor_ref = normalize_actor(actor)
        receipt = normalize_record(
            {
                "id": f"receipt_{inquiry_id}_delivery_{ref_hash}",
                "object_type": "BuilderOpsReceipt",
                "summary": f"Linked delivery reference for inquiry {inquiry_id}",
                "event_type": "inquiry_delivery_linked",
                "actor": actor_ref,
                "occurred_at": occurred_at,
                "target_refs": [
                    {
                        "ref_type": "builderops_inquiry",
                        "ref": inquiry_id,
                        "authority_surface": "builderops",
                    },
                    ref,
                ],
                "action": "link_delivery",
                "receipt_body": "Appended one delivery reference to the inquiry trace.",
                "idempotency_key": f"inquiry:{inquiry_id}:delivery:{ref_hash}",
                "source_refs": source_refs,
                "created_by": actor_ref,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
        )
        receipt["artifact_hash"] = _artifact_hash(receipt)
        return self._write_immutable(path, receipt, label="immutable delivery receipt")

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

    def commit_provider_attempt_receipt(
        self,
        inquiry_id: str,
        *,
        adapter_request_id: str,
        outcome: str,
        details: Mapping[str, Any],
        source_refs: list[dict[str, Any]],
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        adapter_request_id = _safe_id(adapter_request_id, "adapter_request_id")
        outcome = _safe_id(outcome, "provider attempt outcome")
        validate_source_refs(source_refs)
        sanitized = _validate_receipt_details(details)
        directory = self._require_inquiry(inquiry_id)
        path = directory / "receipts" / f"attempt-{adapter_request_id}.json"
        existing = self._read_optional(path)
        occurred_at = _existing_timestamp(existing)
        actor_ref = normalize_actor(actor)
        receipt = normalize_record(
            {
                "id": f"receipt_{inquiry_id}_{adapter_request_id}",
                "object_type": "BuilderOpsReceipt",
                "summary": f"Provider attempt {adapter_request_id} ended {outcome}",
                "event_type": "inquiry_provider_attempt_terminal",
                "actor": actor_ref,
                "occurred_at": occurred_at,
                "target_refs": [
                    {
                        "ref_type": "builderops_inquiry",
                        "ref": inquiry_id,
                        "authority_surface": "builderops",
                    }
                ],
                "action": outcome,
                "receipt_body": f"Provider attempt ended with classified outcome {outcome}.",
                "idempotency_key": f"inquiry:{inquiry_id}:attempt:{adapter_request_id}",
                "source_refs": source_refs,
                "created_by": actor_ref,
                "adapter_request_id": adapter_request_id,
                "outcome": outcome,
                "details": sanitized,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
        )
        receipt["artifact_hash"] = _artifact_hash(receipt)
        return self._write_immutable(path, receipt, label="immutable provider attempt receipt")

    def commit_run_terminal_receipt(
        self,
        inquiry_id: str,
        *,
        outcome: str,
        details: Mapping[str, Any],
        source_refs: list[dict[str, Any]],
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        if outcome not in RUN_TERMINAL_OUTCOMES:
            raise BuilderOpsValidationError(f"unsupported inquiry run outcome: {outcome}")
        validate_source_refs(source_refs)
        sanitized = _validate_receipt_details(details)
        directory = self._require_inquiry(inquiry_id)
        path = directory / "receipts" / "inquiry-run-terminal.json"
        existing = self._read_optional(path)
        occurred_at = _existing_timestamp(existing)
        actor_ref = normalize_actor(actor)
        receipt = normalize_record(
            {
                "id": f"receipt_{inquiry_id}_run_terminal",
                "object_type": "BuilderOpsReceipt",
                "summary": f"Model inquiry {inquiry_id} ended {outcome}",
                "event_type": "inquiry_run_terminal",
                "actor": actor_ref,
                "occurred_at": occurred_at,
                "target_refs": [
                    {
                        "ref_type": "builderops_inquiry",
                        "ref": inquiry_id,
                        "authority_surface": "builderops",
                    }
                ],
                "action": outcome,
                "receipt_body": f"Inquiry runner reached terminal outcome {outcome}.",
                "idempotency_key": f"inquiry:{inquiry_id}:run:terminal",
                "source_refs": source_refs,
                "created_by": actor_ref,
                "outcome": outcome,
                "details": sanitized,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            }
        )
        receipt["artifact_hash"] = _artifact_hash(receipt)
        return self._write_immutable(path, receipt, label="immutable inquiry run terminal receipt")

    def trace(self, inquiry_id: str, *, include_delivery: bool = False) -> dict[str, Any]:
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        directory = self._require_inquiry(inquiry_id)
        manifest = self._read_required(directory / "manifest.json")
        question = self._read_required(directory / "question.json")
        turns = self._read_turns(directory, inquiry_id)
        synthesis = self._read_optional(directory / "synthesis.json")
        readiness = self._read_optional(directory / "readiness.json")
        promotion_intent = self._read_optional(directory / "promotion-intent.json")
        for artifact in [synthesis, readiness]:
            if artifact is not None and artifact.get("inquiry_id") != inquiry_id:
                raise BuilderOpsValidationError("foreign artifact in inquiry trace")
        readiness_inputs = (
            _readiness_input_artifacts(
                question=question,
                turns=turns,
                synthesis=synthesis,
                readiness=readiness,
            )
            if readiness is not None
            else None
        )
        receipts = self._read_receipts(
            directory,
            readiness=readiness,
            readiness_input_artifacts=readiness_inputs,
            promotion_intent=promotion_intent,
        )
        self._validate_manifest(manifest, question, receipts, inquiry_id)
        self._validate_artifact_graph(question, turns, synthesis, readiness)
        if promotion_intent is not None:
            self._validate_promotion_intent(
                promotion_intent,
                inquiry_id=inquiry_id,
                readiness=readiness,
                synthesis=synthesis,
            )
        self._validate_run_terminal_semantics(receipts, turns, synthesis)
        source_refs = _dedupe_source_refs(
            manifest.get("source_refs", []),
            question.get("source_refs", []),
            *(turn.get("source_refs", []) for turn in turns),
            *((artifact or {}).get("source_refs", []) for artifact in [synthesis, readiness]),
            *(receipt.get("source_refs", []) for receipt in receipts),
        )
        result = {
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
        if include_delivery:
            result["delivery_refs"] = _delivery_refs(receipts)
            result["promotion_intent"] = promotion_intent
        return result

    def write_human_readable_report(self, inquiry_id: str) -> Path:
        """Write the mutable Markdown projection after a terminal inquiry run."""
        inquiry_id = _safe_id(inquiry_id, "inquiry_id")
        trace = self.trace(inquiry_id)
        directory = self._require_inquiry(inquiry_id)
        path = directory / "report.md"
        self._write_derived_text(
            path,
            render_markdown_report(trace),
            label="human-readable inquiry report",
        )
        return path

    def _validate_promotion_intent(
        self,
        intent: dict[str, Any],
        *,
        inquiry_id: str,
        readiness: dict[str, Any] | None,
        synthesis: dict[str, Any] | None,
    ) -> None:
        if (
            intent.get("schema") != PROMOTION_INTENT_SCHEMA
            or intent.get("artifact_id") != "promotion-intent"
            or intent.get("object_type") != "PromotionIntent"
            or intent.get("inquiry_id") != inquiry_id
            or intent.get("target_authority_surface") != "github_issue"
            or readiness is None
            or synthesis is None
            or intent.get("readiness_artifact_hash") != readiness.get("artifact_hash")
            or intent.get("synthesis_artifact_hash") != synthesis.get("artifact_hash")
        ):
            raise BuilderOpsValidationError("invalid inquiry promotion intent")
        if not isinstance(intent.get("title"), str) or not intent["title"].strip():
            raise BuilderOpsValidationError("invalid promotion intent title")
        if len(intent["title"].strip()) > 200 or "\n" in intent["title"] or "\r" in intent["title"]:
            raise BuilderOpsValidationError("invalid promotion intent title")
        if not isinstance(intent.get("issue_body"), str) or not intent["issue_body"].strip():
            raise BuilderOpsValidationError("invalid promotion intent issue body")
        repository = intent.get("target_repository")
        marker = intent.get("promotion_marker")
        if (
            not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not isinstance(marker, str)
            or not re.fullmatch(
                rf"<!-- builderops-inquiry-promotion:{re.escape(inquiry_id)}:[0-9a-f]{{64}} -->",
                marker,
            )
            or marker not in intent["issue_body"]
        ):
            raise BuilderOpsValidationError("invalid promotion intent marker or repository")
        if intent.get("issue_body_hash") != _content_hash(intent["issue_body"]):
            raise BuilderOpsValidationError("promotion intent issue body hash mismatch")
        _validate_persisted_source_refs(intent.get("source_refs"))
        _validate_artifact_hash(intent, label="promotion intent")

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
        with self._named_inquiry_lock(inquiry_id, ".turn-commit.lock", "turn commit"):
            yield

    @contextmanager
    def inquiry_runner_lock(self, inquiry_id: str) -> Iterator[None]:
        safe_id = _safe_id(inquiry_id, "inquiry_id")
        with self._named_inquiry_lock(safe_id, ".inquiry-runner.lock", "inquiry runner"):
            yield

    @contextmanager
    def inquiry_promotion_lock(self, inquiry_id: str) -> Iterator[None]:
        safe_id = _safe_id(inquiry_id, "inquiry_id")
        with self._named_inquiry_lock(safe_id, ".inquiry-promotion.lock", "inquiry promotion"):
            yield

    @contextmanager
    def _named_inquiry_lock(
        self,
        inquiry_id: str,
        filename: str,
        label: str,
    ) -> Iterator[None]:
        directory = self._require_inquiry(inquiry_id)
        path = directory / filename
        self._validate_artifact_parent(path)
        if path.is_symlink():
            raise BuilderOpsValidationError(f"{label} lock must not be a symlink: {path}")
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
        except OSError as exc:
            raise BuilderOpsValidationError(f"unable to acquire {label} lock: {inquiry_id}") from exc
        try:
            yield
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
            _validate_provider_metadata_from_turn(turn)
            _validate_artifact_hash(turn, label=f"turn {turn_id}")
            reservation = self._read_required(reservations_dir / f"{turn_id}.json")
            expected_reservation = {
                "schema": "builderops.model-inquiry-turn-reservation.v1",
                "inquiry_id": inquiry_id,
                "turn_id": turn_id,
                "sequence": sequence,
                "artifact_hash": turn["artifact_hash"],
            }
            # created_at joined the reservation payload to make exact-retry recovery
            # deterministic (see _commit_turn_locked). Reservations written before that
            # change have no created_at key; require it to match the committed turn's
            # own created_at when present, without breaking pre-existing durable data
            # that predates the field.
            if "created_at" in reservation:
                expected_reservation["created_at"] = turn["created_at"]
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

    def _read_receipts(
        self,
        directory: Path,
        *,
        readiness: Mapping[str, Any] | None = None,
        readiness_input_artifacts: list[dict[str, str]] | None = None,
        promotion_intent: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        receipts_dir = directory / "receipts"
        if receipts_dir.is_symlink():
            raise BuilderOpsValidationError(f"receipt directory must not be a symlink: {receipts_dir}")
        receipt_files = [
            (path, self._read_required(path)) for path in sorted(receipts_dir.glob("*.json"))
        ]
        receipts = [receipt for _, receipt in receipt_files]
        seen_ids: set[str] = set()
        run_terminal_count = 0
        for path, receipt in receipt_files:
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
            if receipt.get("event_type") == "inquiry_run_terminal":
                run_terminal_count += 1
                _validate_run_terminal_receipt(directory.name, path, receipt)
            elif receipt.get("event_type") == "inquiry_provider_attempt_terminal":
                _validate_provider_attempt_receipt(directory.name, path, receipt)
            elif receipt.get("event_type") == "inquiry_readiness_terminal":
                _validate_readiness_terminal_receipt(
                    directory.name,
                    path,
                    receipt,
                    readiness,
                    readiness_input_artifacts,
                )
            elif receipt.get("event_type") == "inquiry_promotion_terminal":
                _validate_promotion_terminal_receipt(
                    directory.name,
                    path,
                    receipt,
                    promotion_intent,
                )
            elif receipt.get("event_type") == "inquiry_delivery_linked":
                _validate_delivery_receipt(directory.name, path, receipt)
        if run_terminal_count > 1:
            raise BuilderOpsValidationError("multiple inquiry run terminal receipts")
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
        question: dict[str, Any],
        turns: list[dict[str, Any]],
        synthesis: dict[str, Any] | None,
        readiness: dict[str, Any] | None,
    ) -> None:
        turn_sequences = {turn["turn_id"]: turn["sequence"] for turn in turns}
        available = {"question", *turn_sequences}
        artifacts: dict[str, dict[str, Any]] = {"question": question}
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
            if "adapter_request_id" in turn:
                input_basis = [
                    {
                        "artifact_id": ref,
                        "artifact_hash": artifacts[ref]["artifact_hash"],
                    }
                    for ref in turn["input_artifact_refs"]
                ]
                if turn["input_hash"] != _content_hash(
                    json.dumps(
                        input_basis,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ):
                    raise BuilderOpsValidationError(
                        f"provider turn input hash mismatch: {turn['turn_id']}"
                    )
                expected_context = canonical_hash(
                    initial_context_packet(
                        inquiry_id=str(question["inquiry_id"]),
                        workflow=str(question["workflow"]),
                        question_artifact_id=str(question["artifact_id"]),
                        question_artifact_hash=str(question["artifact_hash"]),
                        source_refs=list(question["source_refs"]),
                    )
                )
                if turn["context_hash"] != expected_context:
                    raise BuilderOpsValidationError(
                        f"provider turn context hash mismatch: {turn['turn_id']}"
                    )
                expected_requests = {
                    model_turn_request_hash(
                        inquiry_id=str(turn["inquiry_id"]),
                        role=str(turn["role"]),
                        phase=str(turn["phase"]),
                        round_index=int(turn["round_index"]),
                        context_hash=str(turn["context_hash"]),
                        input_hash=str(turn["input_hash"]),
                        input_artifact_refs=list(turn["input_artifact_refs"]),
                        adapter_id=str(turn["adapter_id"]),
                        provider=str(turn["provider"]),
                        model=str(turn["model"]),
                    ),
                    model_turn_request_hash(
                        inquiry_id=str(turn["inquiry_id"]),
                        role=str(turn["role"]),
                        phase=str(turn["phase"]),
                        round_index=int(turn["round_index"]),
                        context_hash=str(turn["context_hash"]),
                        input_hash=str(turn["input_hash"]),
                        input_artifact_refs=list(turn["input_artifact_refs"]),
                        adapter_id=str(turn["adapter_id"]),
                        provider=str(turn["provider"]),
                        model=str(turn["model"]),
                        system_prompt=MODEL_TURN_SYSTEM_PROMPT,
                    ),
                }
                if turn["request_hash"] not in expected_requests:
                    raise BuilderOpsValidationError(
                        f"provider turn request hash mismatch: {turn['turn_id']}"
                    )
                if turn["adapter_request_id"] != f"adapter_req_{turn['request_hash'][:32]}":
                    raise BuilderOpsValidationError(
                        f"provider turn adapter request id mismatch: {turn['turn_id']}"
                    )
                if turn["stance"] == "accept":
                    reviewed_hashes = {
                        artifacts[ref]["artifact_hash"]
                        for ref in turn["input_artifact_refs"]
                        if ref != "question"
                    }
                    if turn["accepted_artifact_hash"] not in reviewed_hashes:
                        raise BuilderOpsValidationError(
                            f"provider turn accepts non-prior artifact: {turn['turn_id']}"
                        )
            artifacts[turn["turn_id"]] = turn
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

    def _validate_run_terminal_semantics(
        self,
        receipts: list[dict[str, Any]],
        turns: list[dict[str, Any]],
        synthesis: dict[str, Any] | None,
    ) -> None:
        terminal = next(
            (
                receipt
                for receipt in receipts
                if receipt.get("event_type") == "inquiry_run_terminal"
            ),
            None,
        )
        if terminal is None:
            return
        outcome = terminal["outcome"]
        details = terminal["details"]
        if outcome in {"consensus", "degraded_consensus"}:
            accepted_hash = details.get("accepted_artifact_hash")
            round_index = details.get("round_index")
            if not isinstance(round_index, int) or isinstance(round_index, bool) or round_index < 0:
                raise BuilderOpsValidationError("consensus terminal has invalid round_index")
            accepted_turn = next(
                (turn for turn in turns if turn.get("artifact_hash") == accepted_hash),
                None,
            )
            accept_turns = [
                turn
                for turn in turns
                if turn.get("phase") == "review"
                and turn.get("round_index") == round_index
                and turn.get("stance") == "accept"
                and turn.get("accepted_artifact_hash") == accepted_hash
            ]
            attempt_receipts = [
                receipt
                for receipt in receipts
                if receipt.get("event_type") == "inquiry_provider_attempt_terminal"
            ]
            effective_targets = {
                (turn.get("adapter_id"), turn.get("provider"), turn.get("model"))
                for turn in accept_turns
            }
            degraded = bool(attempt_receipts) or len(effective_targets) != 2
            expected_detail_fields = {"accepted_artifact_hash", "round_index"}
            if outcome == "degraded_consensus":
                expected_detail_fields.add("degradation_reason")
            if (
                accepted_turn is None
                or round_index > 19
                or len(accept_turns) != 2
                or {turn.get("role") for turn in accept_turns} != {"fable", "gpt_codex"}
                or synthesis is None
                or synthesis.get("input_artifact_refs") != [accepted_turn["turn_id"]]
                or synthesis.get("content") != accepted_turn["content"]
                or set(details) != expected_detail_fields
                or (outcome == "consensus" and degraded)
                or (outcome == "degraded_consensus" and not degraded)
                or (
                    outcome == "degraded_consensus"
                    and details.get("degradation_reason") != "operational adapter fallback used"
                )
            ):
                raise BuilderOpsValidationError("consensus terminal is not linked to accepted graph")
            return
        if outcome == "max_rounds_exhausted":
            max_rounds = details.get("max_rounds")
            if (
                isinstance(max_rounds, bool)
                or not isinstance(max_rounds, int)
                or max_rounds < 1
                or max_rounds > 20
            ):
                raise BuilderOpsValidationError("max-round terminal has invalid bound")
            review_pairs = {
                (turn.get("round_index"), turn.get("role"))
                for turn in turns
                if turn.get("phase") == "review"
            }
            expected_pairs = {
                (round_index, role)
                for round_index in range(max_rounds)
                for role in ("fable", "gpt_codex")
            }
            draft_roles = {
                turn.get("role") for turn in turns if turn.get("phase") == "draft"
            }
            review_turns = [turn for turn in turns if turn.get("phase") == "review"]
            draft_turns = [turn for turn in turns if turn.get("phase") == "draft"]
            accepted_groups: dict[tuple[int, str], set[str]] = {}
            for turn in review_turns:
                if turn.get("stance") != "accept":
                    continue
                key = (
                    int(turn["round_index"]),
                    str(turn["accepted_artifact_hash"]),
                )
                accepted_groups.setdefault(key, set()).add(str(turn["role"]))
            proven_consensus = any(
                roles == {"fable", "gpt_codex"} for roles in accepted_groups.values()
            )
            if (
                review_pairs != expected_pairs
                or draft_roles != {"fable", "gpt_codex"}
                or len(review_turns) != 2 * max_rounds
                or len(draft_turns) != 2
                or proven_consensus
            ):
                raise BuilderOpsValidationError("max-round terminal has incomplete review graph")
            return
        attempts = [
            receipt
            for receipt in receipts
            if receipt.get("event_type") == "inquiry_provider_attempt_terminal"
            and receipt.get("outcome") == outcome
            and receipt.get("details") == details
        ]
        if len(attempts) != 1:
            raise BuilderOpsValidationError("failure terminal is not linked to one provider attempt")

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

    def _write_derived_text(self, path: Path, content: str, *, label: str) -> None:
        self._validate_artifact_parent(path)
        if path.is_symlink():
            raise BuilderOpsValidationError(f"{label} path must not be a symlink: {path}")
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        except OSError as exc:
            raise BuilderOpsValidationError(f"unable to persist {label}: {path}") from exc
        finally:
            temporary.unlink(missing_ok=True)

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
        created_at: str,
        artifact_hash: str,
        created_by_this_attempt: bool,
    ) -> None:
        existing = self._read_optional(reservation_path)
        expected: dict[str, Any] = {
            "schema": "builderops.model-inquiry-turn-reservation.v1",
            "inquiry_id": directory.name,
            "turn_id": turn_id,
            "sequence": sequence,
            "artifact_hash": artifact_hash,
        }
        # Mirrors the write-side and _read_turns backward-compat rule: only
        # require created_at when the on-disk reservation actually carries it, so
        # a legacy (pre-fix) orphan this attempt just matched or wrote is still
        # recognized and cleaned up.
        if existing is not None and "created_at" in existing:
            expected["created_at"] = created_at
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


def _reservation_timestamp(reservation: Mapping[str, Any] | None) -> str | None:
    """Recover the created_at an orphaned turn-id reservation already fixed.

    Returns None for a reservation written before created_at joined the
    reservation payload (or when no reservation exists yet), which falls
    _existing_timestamp back to a fresh utc_now() -- the pre-fix behavior --
    for that narrow pre-existing-data case only.
    """
    if reservation is not None and isinstance(reservation.get("created_at"), str):
        return reservation["created_at"]
    return None


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


def _validate_provider_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    payload = dict(value)
    if set(payload) != PROVIDER_TURN_FIELDS:
        raise BuilderOpsValidationError("provider turn metadata fields do not match contract")
    for field in (
        "adapter_request_id",
        "adapter_id",
        "provider",
        "model",
        "phase",
        "stance",
    ):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise BuilderOpsValidationError(f"provider turn {field} must be non-empty")
    _safe_id(payload["adapter_request_id"], "adapter_request_id")
    if payload["phase"] not in {"draft", "review"}:
        raise BuilderOpsValidationError("provider turn phase must be draft or review")
    if payload["stance"] not in {"draft", "accept", "revise"}:
        raise BuilderOpsValidationError("refusal cannot be committed as a provider turn")
    provider_request_id = payload["provider_request_id"]
    if provider_request_id is not None and (
        not isinstance(provider_request_id, str) or not provider_request_id.strip()
    ):
        raise BuilderOpsValidationError("provider_request_id must be null or non-empty")
    if provider_request_id is not None:
        lowered = provider_request_id.lower()
        if (
            len(provider_request_id) > 256
            or any(
                char
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
                for char in provider_request_id
            )
            or any(
                token in lowered
                for token in ("secret", "credential", "bearer", "api_key", "token")
            )
        ):
            raise BuilderOpsValidationError("provider_request_id failed safe identifier validation")
    for field in ("context_hash", "request_hash", "input_hash", "output_hash"):
        _validate_sha256(payload[field], field)
    accepted = payload["accepted_artifact_hash"]
    if accepted is not None:
        _validate_sha256(accepted, "accepted_artifact_hash")
    if payload["stance"] == "accept" and accepted is None:
        raise BuilderOpsValidationError("accept provider turn requires accepted artifact hash")
    if payload["stance"] != "accept" and accepted is not None:
        raise BuilderOpsValidationError("only accept provider turn may set accepted artifact hash")
    round_index = payload["round_index"]
    if isinstance(round_index, bool) or not isinstance(round_index, int) or round_index < 0:
        raise BuilderOpsValidationError("provider turn round_index must be non-negative")
    return payload


def _validate_provider_metadata_from_turn(turn: Mapping[str, Any]) -> None:
    present = PROVIDER_TURN_FIELDS & set(turn)
    if not present:
        return
    if present != PROVIDER_TURN_FIELDS:
        raise BuilderOpsValidationError("persisted provider turn metadata is incomplete")
    _validate_provider_metadata({field: turn[field] for field in PROVIDER_TURN_FIELDS})
    if turn["output_hash"] != turn.get("content_hash"):
        raise BuilderOpsValidationError("provider turn output hash does not match stored response")


def _validate_sha256(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise BuilderOpsValidationError(f"{field} must be lowercase sha256")


def _validate_receipt_details(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    forbidden = ("secret", "token", "api_key", "authorization", "stderr", "argv", "environment")

    def visit(item: Any, path: str) -> None:
        if item is None or isinstance(item, (str, int, float, bool)):
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or any(token in key.lower() for token in forbidden):
                    raise BuilderOpsValidationError(f"unsafe receipt detail key: {path}.{key}")
                visit(child, f"{path}.{key}")
            return
        raise BuilderOpsValidationError(f"receipt detail is not JSON-safe: {path}")

    visit(payload, "details")
    return payload


def _validate_run_terminal_receipt(
    inquiry_id: str,
    path: Path,
    receipt: Mapping[str, Any],
) -> None:
    outcome = receipt.get("outcome")
    expected_target = [
        {
            "ref_type": "builderops_inquiry",
            "ref": inquiry_id,
            "authority_surface": "builderops",
        }
    ]
    if (
        path.name != "inquiry-run-terminal.json"
        or receipt.get("id") != f"receipt_{inquiry_id}_run_terminal"
        or receipt.get("idempotency_key") != f"inquiry:{inquiry_id}:run:terminal"
        or outcome not in RUN_TERMINAL_OUTCOMES
        or receipt.get("action") != outcome
        or receipt.get("target_refs") != expected_target
        or not isinstance(receipt.get("details"), dict)
    ):
        raise BuilderOpsValidationError("invalid inquiry run terminal receipt")
    _validate_receipt_details(cast(Mapping[str, Any], receipt["details"]))


def _validate_readiness_terminal_receipt(
    inquiry_id: str,
    path: Path,
    receipt: Mapping[str, Any],
    readiness: Mapping[str, Any] | None,
    input_artifacts: list[dict[str, str]] | None,
) -> None:
    if readiness is None or input_artifacts is None:
        raise BuilderOpsValidationError("readiness receipt has no loaded readiness evidence")
    outcome = readiness.get("outcome")
    expected_target = [
        {
            "ref_type": "builderops_inquiry",
            "ref": inquiry_id,
            "authority_surface": "builderops",
        }
    ]
    if (
        path.name != "readiness-terminal.json"
        or receipt.get("id") != f"receipt_{inquiry_id}_readiness_terminal"
        or receipt.get("idempotency_key") != f"inquiry:{inquiry_id}:readiness:terminal"
        or receipt.get("action") != outcome
        or receipt.get("target_refs") != expected_target
        or receipt.get("readiness_artifact_hash") != readiness.get("artifact_hash")
        or receipt.get("input_artifacts") != input_artifacts
        or receipt.get("source_refs") != readiness.get("source_refs")
        or outcome not in READINESS_OUTCOMES
    ):
        raise BuilderOpsValidationError("invalid inquiry readiness terminal receipt")


def _validate_promotion_terminal_receipt(
    inquiry_id: str,
    path: Path,
    receipt: Mapping[str, Any],
    intent: Mapping[str, Any] | None,
) -> None:
    if intent is None:
        raise BuilderOpsValidationError("promotion receipt has no loaded promotion intent")
    targets = receipt.get("target_refs")
    issue_number = receipt.get("github_issue_number")
    if (
        path.name != "promotion-github-issue.json"
        or receipt.get("id") != f"receipt_{inquiry_id}_promotion_github_issue"
        or receipt.get("idempotency_key") != f"inquiry:{inquiry_id}:promotion:github_issue"
        or receipt.get("action") != "promoted"
        or receipt.get("promotion_intent_artifact_hash") != intent.get("artifact_hash")
        or receipt.get("promotion_marker") != intent.get("promotion_marker")
        or receipt.get("source_refs") != intent.get("source_refs")
        or isinstance(issue_number, bool)
        or not isinstance(issue_number, int)
        or issue_number < 1
        or not isinstance(targets, list)
        or len(targets) != 2
        or not isinstance(targets[0], dict)
        or not isinstance(targets[1], dict)
        or targets[0]
        != {
            "ref_type": "builderops_inquiry",
            "ref": inquiry_id,
            "authority_surface": "builderops",
        }
        or targets[1].get("ref_type") != "github_issue"
        or targets[1].get("ref") != f"{intent.get('target_repository')}#{issue_number}"
        or not isinstance(receipt.get("github_issue_url"), str)
        or not github_issue_url_matches(
            receipt["github_issue_url"],
            intent.get("target_repository"),
            issue_number,
        )
    ):
        raise BuilderOpsValidationError("invalid inquiry promotion terminal receipt")


def _validate_delivery_receipt(
    inquiry_id: str,
    path: Path,
    receipt: Mapping[str, Any],
) -> None:
    targets = receipt.get("target_refs")
    if not isinstance(targets, list) or len(targets) != 2:
        raise BuilderOpsValidationError("invalid inquiry delivery receipt")
    delivery_ref = targets[1]
    if not isinstance(delivery_ref, dict):
        raise BuilderOpsValidationError("invalid inquiry delivery receipt")
    ref_hash = canonical_hash(delivery_ref)[:24]
    if (
        path.name != f"delivery-{ref_hash}.json"
        or receipt.get("id") != f"receipt_{inquiry_id}_delivery_{ref_hash}"
        or receipt.get("idempotency_key") != f"inquiry:{inquiry_id}:delivery:{ref_hash}"
        or receipt.get("action") != "link_delivery"
        or targets[0]
        != {
            "ref_type": "builderops_inquiry",
            "ref": inquiry_id,
            "authority_surface": "builderops",
        }
        or delivery_ref.get("ref_type")
        not in {"github_pull_request", "verification_receipt", "owner_doc"}
    ):
        raise BuilderOpsValidationError("invalid inquiry delivery receipt")


def _readiness_input_artifacts(
    *,
    question: Mapping[str, Any],
    turns: list[dict[str, Any]],
    synthesis: Mapping[str, Any] | None,
    readiness: Mapping[str, Any],
) -> list[dict[str, str]]:
    artifacts: dict[str, Mapping[str, Any]] = {"question": question}
    if synthesis is not None:
        artifacts["synthesis"] = synthesis
    artifacts.update({str(turn["turn_id"]): turn for turn in turns})
    result: list[dict[str, str]] = []
    for ref in readiness.get("input_artifact_refs", []):
        artifact = artifacts.get(str(ref))
        if artifact is None or not isinstance(artifact.get("artifact_hash"), str):
            raise BuilderOpsValidationError("readiness receipt has missing input artifact")
        result.append(
            {"artifact_id": str(ref), "artifact_hash": str(artifact["artifact_hash"])}
        )
    if not result:
        raise BuilderOpsValidationError("readiness receipt requires input artifacts")
    return result


def _delivery_refs(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for receipt in receipts:
        if receipt.get("event_type") not in {
            "inquiry_promotion_terminal",
            "inquiry_delivery_linked",
        }:
            continue
        for ref in receipt.get("target_refs", [])[1:]:
            if isinstance(ref, dict):
                refs.append(dict(ref))
    return sorted(refs, key=lambda item: (str(item.get("ref_type")), str(item.get("ref"))))


def _validate_provider_attempt_receipt(
    inquiry_id: str,
    path: Path,
    receipt: Mapping[str, Any],
) -> None:
    request_id = _safe_id(str(receipt.get("adapter_request_id", "")), "adapter_request_id")
    outcome = receipt.get("outcome")
    allowed = RUN_TERMINAL_OUTCOMES - {
        "consensus",
        "degraded_consensus",
        "max_rounds_exhausted",
    }
    expected_target = [
        {
            "ref_type": "builderops_inquiry",
            "ref": inquiry_id,
            "authority_surface": "builderops",
        }
    ]
    details = receipt.get("details")
    if (
        path.name != f"attempt-{request_id}.json"
        or receipt.get("id") != f"receipt_{inquiry_id}_{request_id}"
        or receipt.get("idempotency_key") != f"inquiry:{inquiry_id}:attempt:{request_id}"
        or outcome not in allowed
        or receipt.get("action") != outcome
        or receipt.get("target_refs") != expected_target
        or not isinstance(details, dict)
        or details.get("adapter_request_id") != request_id
    ):
        raise BuilderOpsValidationError("invalid provider attempt terminal receipt")
    _validate_receipt_details(cast(Mapping[str, Any], details))
    if request_id == "adapter_req_configuration":
        if (
            outcome != "provider_unavailable"
            or details
            != {
                "adapter_request_id": "adapter_req_configuration",
                "classification": "explicit role adapter unavailable",
            }
        ):
            raise BuilderOpsValidationError("invalid configuration attempt receipt")
        return
    if request_id == CREDENTIAL_ATTEMPT_REQUEST_ID:
        # A declared credential that is absent or unusable fails closed before a
        # request packet exists, so this reserved attempt carries the classified
        # diagnostic and the logical identifier instead of turn hashes.
        if (
            outcome != "provider_error"
            or set(details) != {"adapter_request_id", "classification", "diagnostic"}
            or details.get("classification") != "declared credential unavailable"
        ):
            raise BuilderOpsValidationError("invalid credential attempt receipt")
        _validate_adapter_failure_diagnostic(details["diagnostic"])
        diagnostic = cast(Mapping[str, Any], details["diagnostic"])
        if diagnostic.get("adapter_failure_class") != "credential_unavailable" or not diagnostic.get(
            "credential_identity_ref"
        ):
            raise BuilderOpsValidationError("invalid credential attempt receipt")
        return
    expected_classifications = {
        "provider_refused": "provider returned explicit refusal",
        "malformed_output": "provider output failed strict response validation",
        "provider_unavailable": "explicit role adapter unavailable",
        "provider_error": "provider adapter execution failed",
        "persistence_failed": "provider result was not durably committed",
    }
    expected_fields = {
        "adapter_request_id",
        "request_hash",
        "context_hash",
        "input_hash",
        "output_hash",
        "classification",
    }
    candidate_fields = {*expected_fields, "candidate_adapter_id"}
    allowed_fields = {frozenset(expected_fields), frozenset(candidate_fields)}
    if outcome == "provider_error":
        allowed_fields.add(frozenset({*expected_fields, "diagnostic"}))
        allowed_fields.add(frozenset({*candidate_fields, "diagnostic"}))
    if (
        frozenset(details) not in allowed_fields
        or details.get("classification") != expected_classifications.get(str(outcome))
    ):
        raise BuilderOpsValidationError("provider attempt details do not match outcome contract")
    if "diagnostic" in details:
        _validate_adapter_failure_diagnostic(details["diagnostic"])
    candidate_adapter_id = details.get("candidate_adapter_id")
    if candidate_adapter_id is not None:
        _safe_id(str(candidate_adapter_id), "candidate_adapter_id")
        candidate_diagnostic = details.get("diagnostic")
        if (
            isinstance(candidate_diagnostic, Mapping)
            and candidate_diagnostic.get("adapter_id") != candidate_adapter_id
        ):
            raise BuilderOpsValidationError("candidate adapter identity does not match diagnostic")
    for field in ("request_hash", "context_hash", "input_hash"):
        _validate_sha256(details.get(field), f"attempt {field}")
    output_hash = details.get("output_hash")
    if output_hash is not None:
        _validate_sha256(output_hash, "attempt output_hash")
    if request_id != f"adapter_req_{str(details['request_hash'])[:32]}":
        raise BuilderOpsValidationError("provider attempt request ID does not match request hash")


def _validate_adapter_failure_diagnostic(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise BuilderOpsValidationError("adapter failure diagnostic must be an object")
    expected_fields = {"adapter_id", "adapter_failure_class"}
    optional_exit_code = "adapter_exit_code"
    optional_credential = "credential_identity_ref"
    if not expected_fields <= set(value) or not set(value) <= {
        *expected_fields,
        optional_exit_code,
        optional_credential,
    }:
        raise BuilderOpsValidationError("invalid adapter failure diagnostic fields")
    _safe_id(str(value.get("adapter_id", "")), "adapter failure adapter_id")
    failure_class = value.get("adapter_failure_class")
    if not isinstance(failure_class, str) or failure_class not in ADAPTER_FAILURE_CLASSES:
        raise BuilderOpsValidationError("invalid adapter failure class")
    if optional_credential in value:
        credential = value[optional_credential]
        # Declared logical identifier grammar only: no value, environment name,
        # provider secret, or host path can satisfy it.
        if not isinstance(credential, str) or not CREDENTIAL_IDENTITY_RE.fullmatch(credential):
            raise BuilderOpsValidationError("invalid credential identity reference")
    if (failure_class == "credential_unavailable") != (optional_credential in value):
        raise BuilderOpsValidationError(
            "credential_unavailable and credential_identity_ref must appear together"
        )
    if failure_class == "credential_unavailable" and set(value) != {
        "adapter_id",
        "adapter_failure_class",
        "credential_identity_ref",
    }:
        raise BuilderOpsValidationError(
            "credential_unavailable diagnostic must use the exact typed field set"
        )
    if optional_exit_code in value:
        exit_code = value[optional_exit_code]
        if (
            not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or not 1 <= exit_code <= 255
        ):
            raise BuilderOpsValidationError("invalid adapter exit code")


def validate_adapter_failure_diagnostic(value: Any) -> None:
    """Validate the persisted closed diagnostic contract at another boundary."""
    _validate_adapter_failure_diagnostic(value)


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
