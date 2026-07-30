"""Fenced privileged merge effect for the API-backed verifier.

This is an effect adapter, not a second verifier. It consumes a claimed
``VerificationRun`` only after the consumer has committed an exact review-only
merge-ready receipt. The adapter commits a task-bound outbox intent,
re-resolves protected-base policy and host credential binding, invokes only a
GitHub-enforced conditional merge/merge-queue operation, and treats readback
or crash recovery as terminal authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ControlPlaneNotFoundError,
)
from app.builderops.control_plane.routing import RepoRef
from app.dispatcher.verification_dispatch import VerificationRun
from app.dispatcher.verified_merge import (
    FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
    fixed_verified_merge_commit_title,
)


class MergeAuthorityError(RuntimeError):
    """The protected repository did not authorize the privileged effect."""


@dataclass(frozen=True)
class ProtectedDeliveryManifest:
    repository: str
    base_sha: str
    blob_sha: str
    content_sha256: str
    credential_id: str
    credential_generation: int
    allowed_effects: tuple[str, ...]

    @classmethod
    def from_document(
        cls,
        document: Mapping[str, Any],
        *,
        repository: str,
        base_sha: str,
        blob_sha: str,
    ) -> "ProtectedDeliveryManifest":
        canonical = RepoRef.parse(repository).canonical
        manifest_repo = RepoRef.parse(document.get("repository")).canonical
        effects = document.get("allowed_effects")
        credential = document.get("github_credential")
        if (
            manifest_repo != canonical
            or not isinstance(effects, list)
            or any(not isinstance(value, str) for value in effects)
            or not isinstance(credential, Mapping)
            or not isinstance(credential.get("credential_id"), str)
            or not isinstance(credential.get("rotation_generation"), int)
            or isinstance(credential.get("rotation_generation"), bool)
            or int(credential["rotation_generation"]) < 1
        ):
            raise MergeAuthorityError(
                "protected delivery manifest is malformed or cross-repository"
            )
        digest = hashlib.sha256(
            json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        return cls(
            repository=canonical,
            base_sha=base_sha,
            blob_sha=blob_sha,
            content_sha256=digest,
            credential_id=str(credential["credential_id"]),
            credential_generation=int(credential["rotation_generation"]),
            allowed_effects=tuple(effects),
        )


class ProtectedRepositoryAuthority(Protocol):
    def protected_base_sha(self, repository: str) -> str: ...

    def delivery_manifest(
        self, repository: str, base_sha: str
    ) -> ProtectedDeliveryManifest: ...

    def current_pr_head(self, repository: str, pr_number: int) -> str: ...

    def required_gates(
        self, repository: str, pr_number: int, head_sha: str
    ) -> Mapping[str, bool]: ...

    def verified_merge_prepared(
        self,
        repository: str,
        pr_number: int,
        *,
        run_id: str,
        head_sha: str,
        expected_repair_budget: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def conditional_merge(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        expected_base_sha: str,
        expected_manifest_blob_sha: str,
        commit_title: str,
        commit_message: str,
        credential: object,
    ) -> Mapping[str, object]: ...

    def merge_readback(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object]: ...


class HostCredentialResolver(Protocol):
    def resolve(
        self,
        *,
        repository: str,
        credential_id: str,
        rotation_generation: int,
    ) -> object: ...


class EffectIntentLedger(Protocol):
    def closure_ready(self, run_id: str) -> bool: ...

    def merge_ready_receipt(
        self, run_id: str
    ) -> Mapping[str, object] | None: ...

    def repair_budget_projection(
        self, run_id: str
    ) -> Mapping[str, object]: ...

    def begin_effect(
        self,
        run_id: str,
        *,
        effect_type: str,
        payload: Mapping[str, object],
        holder: str,
        lease_id: str,
        idempotency_key: str,
    ) -> str: ...

    def effect_claim(
        self, operation_key: str
    ) -> Mapping[str, object]: ...

    def pending_effect_binding(
        self, run_id: str
    ) -> Mapping[str, object] | None: ...

    def recover_effect(
        self,
        operation_key: str,
        *,
        run_id: str,
        effect_type: str,
    ) -> Mapping[str, object]: ...

    def finish_effect(
        self,
        operation_key: str,
        *,
        observed_applied: bool,
        evidence: Mapping[str, object],
    ) -> None: ...


class OutboxExecutorAuthority(Protocol):
    def claim(self, operation_key: str) -> Mapping[str, object]: ...

    def recover(self, operation_key: str) -> Mapping[str, object]: ...

    def status(self, operation_key: str) -> Mapping[str, object]: ...

    def mark_unknown(
        self, claim: Mapping[str, object], *, detail: str
    ) -> None: ...

    def reconcile(
        self,
        claim: Mapping[str, object],
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class BuilderOpsOutboxExecutor:
    """Host-privileged outbox API client; it never opens the database."""

    _CLAIM_FIELDS = (
        "repository",
        "operation_key",
        "worker_id",
        "fencing_token",
        "intent_lsn",
        "claim_lsn",
        "receipt_sequence",
        "expires_at",
    )

    def __init__(
        self,
        client: BuilderOpsControlPlaneClient,
        *,
        repository: str,
        worker_id: str,
        source_ref: str = "github-issue:3603",
    ) -> None:
        self.client = client
        self.worker_id = worker_id
        self.envelope = {
            "repository": RepoRef.parse(repository).canonical,
            "scope": "verification-executor",
            "stack": "builderops-control-plane",
            "source_refs": [source_ref],
            "schema_version": 1,
        }

    def claim(self, operation_key: str) -> Mapping[str, object]:
        return self.client.claim_outbox(
            envelope=self.envelope,
            operation_key=operation_key,
            worker_id=self.worker_id,
        )

    def recover(self, operation_key: str) -> Mapping[str, object]:
        return self.client.recover_outbox(
            envelope=self.envelope,
            operation_key=operation_key,
        )

    def status(self, operation_key: str) -> Mapping[str, object]:
        try:
            return self.client.get_outbox_status(
                repository=str(self.envelope["repository"]),
                operation_key=operation_key,
            )
        except ControlPlaneNotFoundError:
            return {"status": "missing", "operation_key": operation_key}

    def _claim_identity(
        self, claim: Mapping[str, object]
    ) -> dict[str, object]:
        try:
            return {field: claim[field] for field in self._CLAIM_FIELDS}
        except KeyError as exc:
            raise MergeAuthorityError("outbox claim identity is incomplete") from exc

    def mark_unknown(
        self, claim: Mapping[str, object], *, detail: str
    ) -> None:
        self.client.mark_outbox_unknown(
            envelope=self.envelope,
            claim=self._claim_identity(claim),
            detail=detail,
        )

    def reconcile(
        self,
        claim: Mapping[str, object],
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence: Mapping[str, object],
    ) -> Mapping[str, object]:
        return self.client.reconcile_outbox(
            envelope=self.envelope,
            claim=self._claim_identity(claim),
            observed_applied=observed_applied,
            terminal_unknown=terminal_unknown,
            evidence=evidence,
        )


@dataclass(frozen=True)
class MergeEffectReceipt:
    outcome: str
    operation_key: str
    repository: str
    pr_number: int
    head_sha: str
    base_sha: str
    manifest_blob_sha: str
    manifest_sha256: str
    credential_id: str
    credential_generation: int
    readback: Mapping[str, object]


class VerificationMergeExecutor:
    def __init__(
        self,
        ledger: EffectIntentLedger,
        outbox: OutboxExecutorAuthority,
        repository: ProtectedRepositoryAuthority,
        credentials: HostCredentialResolver,
    ) -> None:
        self.ledger = ledger
        self.outbox = outbox
        self.repository = repository
        self.credentials = credentials

    @staticmethod
    def _required_gates_pass(gates: Mapping[str, bool]) -> bool:
        required = {
            "ci",
            "review",
            "protection",
            "scope",
            "current_head",
        }
        return required.issubset(gates) and all(gates[name] for name in required)

    @staticmethod
    def _same_manifest(
        left: ProtectedDeliveryManifest,
        right: ProtectedDeliveryManifest,
    ) -> bool:
        return (
            left.repository == right.repository
            and left.base_sha == right.base_sha
            and left.blob_sha == right.blob_sha
            and left.content_sha256 == right.content_sha256
            and left.credential_id == right.credential_id
            and left.credential_generation == right.credential_generation
        )

    @staticmethod
    def _same_prepared_gate(
        left: Mapping[str, object],
        right: Mapping[str, object],
    ) -> bool:
        return hashlib.sha256(
            json.dumps(
                dict(left),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).digest() == hashlib.sha256(
            json.dumps(
                dict(right),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).digest()

    @staticmethod
    def _validate_claim(
        claim: Mapping[str, object],
        *,
        operation_key: str,
        effect_type: str,
        run_id: str,
    ) -> None:
        expires_at = claim.get("expires_at")
        fencing_token = claim.get("fencing_token")
        try:
            expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise MergeAuthorityError("outbox claim expiry is malformed") from exc
        if (
            claim.get("operation_key") != operation_key
            or claim.get("effect_type") != effect_type
            or claim.get("task_id") != run_id
            or claim.get("effect_eligible") is not True
            or not isinstance(fencing_token, int)
            or isinstance(fencing_token, bool)
            or fencing_token < 1
            or expires.tzinfo is None
            or expires <= datetime.now(timezone.utc)
        ):
            raise MergeAuthorityError(
                "outbox claim is not an eligible current fenced merge intent"
            )

    def _terminal_no_effect(
        self,
        operation_key: str,
        *,
        evidence: Mapping[str, object],
    ) -> None:
        self.ledger.finish_effect(
            operation_key,
            observed_applied=True,
            evidence={"outcome": "terminal_no_effect", **dict(evidence)},
        )

    def _readback_and_reconcile(
        self,
        claim: Mapping[str, object],
        *,
        run: VerificationRun,
        detail: str,
    ) -> tuple[Mapping[str, object], bool]:
        readback = self.repository.merge_readback(
            run.repository.lower(), run.pr_number
        )
        applied = self._merged_exactly(readback, run)
        self.ledger.finish_effect(
            str(claim["operation_key"]),
            observed_applied=applied,
            evidence={"detail": detail, **dict(readback)},
        )
        return readback, applied

    def execute(
        self,
        run: VerificationRun,
        *,
        holder: str,
        lease_id: str,
        requested_credential_id: str | None = None,
        dry_run: bool = False,
    ) -> MergeEffectReceipt:
        canonical = RepoRef.parse(run.repository).canonical
        if canonical != run.repository.lower():
            raise MergeAuthorityError("verification RepoRef is not canonical")
        if run.status not in {"claimed", "running"}:
            raise MergeAuthorityError("merge requires a claimed verification run")
        if not self.ledger.closure_ready(run.run_id):
            raise MergeAuthorityError(
                "merge requires the verifier's fresh independent review gate"
            )
        marker = self.ledger.merge_ready_receipt(run.run_id)
        if (
            not isinstance(marker, Mapping)
            or marker.get("repository") != canonical
            or marker.get("pr_number") != run.pr_number
            or marker.get("head_sha") != run.current_head_sha
        ):
            raise MergeAuthorityError(
                "merge requires a current host-fenced merge-ready receipt"
            )

        base_sha = self.repository.protected_base_sha(canonical)
        manifest = self.repository.delivery_manifest(canonical, base_sha)
        effect_type = "github.merge.dry_run" if dry_run else "github.merge"
        if effect_type not in manifest.allowed_effects:
            raise MergeAuthorityError("protected manifest does not authorize merge")
        if (
            requested_credential_id is not None
            and requested_credential_id != manifest.credential_id
        ):
            raise MergeAuthorityError(
                "client credential selection conflicts with protected manifest"
            )
        if self.repository.current_pr_head(canonical, run.pr_number) != run.current_head_sha:
            raise MergeAuthorityError("pull request head changed before final validation")
        gates = self.repository.required_gates(
            canonical, run.pr_number, run.current_head_sha
        )
        if not self._required_gates_pass(gates):
            raise MergeAuthorityError("required CI/review/protection/scope gate is missing")
        prepared_gate: Mapping[str, object] | None = None
        commit_title = fixed_verified_merge_commit_title(run.pr_number)
        commit_message = FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
        repair_budget = self.ledger.repair_budget_projection(run.run_id)
        if not dry_run:
            prepared_gate = self.repository.verified_merge_prepared(
                canonical,
                run.pr_number,
                run_id=run.run_id,
                head_sha=run.current_head_sha,
                expected_repair_budget=repair_budget,
            )
            if (
                prepared_gate.get("governing_issue")
                != run.request.get("linked_issue")
                or prepared_gate.get("closing_issues")
                != list(run.closing_authority)
                or prepared_gate.get("closing_reference_count") != 0
                or prepared_gate.get("fixed_commit_title") != commit_title
                or prepared_gate.get("fixed_commit_message") != commit_message
            ):
                raise MergeAuthorityError(
                    "verified-merge prepared authority does not match the run"
                )

        try:
            operation_key = self.ledger.begin_effect(
                run.run_id,
                effect_type=effect_type,
                payload={
                    "repository": canonical,
                    "governing_issue": run.request["linked_issue"],
                    "pr_number": run.pr_number,
                    "head_sha": run.current_head_sha,
                    "base_sha": base_sha,
                    "manifest_blob_sha": manifest.blob_sha,
                    "manifest_sha256": manifest.content_sha256,
                    "credential_id": manifest.credential_id,
                    "rotation_generation": manifest.credential_generation,
                    "fixed_commit_title": commit_title,
                    "fixed_commit_message": commit_message,
                    "verified_merge_prepared": (
                        dict(prepared_gate)
                        if prepared_gate is not None
                        else None
                    ),
                },
                holder=holder,
                lease_id=lease_id,
                idempotency_key=(
                    f"{run.run_id}:github.merge:{run.current_head_sha}:"
                    f"{base_sha}:{manifest.blob_sha}"
                ),
            )
        except ValueError as exc:
            raise MergeAuthorityError(
                "outbox claim is not an eligible current fenced merge intent"
            ) from exc

        # This is deliberately after the durable intent: base, manifest, head,
        # and gates can race while the local commit becomes durable.
        effect_base = self.repository.protected_base_sha(canonical)
        effect_manifest = self.repository.delivery_manifest(canonical, effect_base)
        effect_head = self.repository.current_pr_head(canonical, run.pr_number)
        effect_gates = self.repository.required_gates(
            canonical, run.pr_number, effect_head
        )
        effect_prepared_gate = (
            self.repository.verified_merge_prepared(
                canonical,
                run.pr_number,
                run_id=run.run_id,
                head_sha=run.current_head_sha,
                expected_repair_budget=repair_budget,
            )
            if prepared_gate is not None
            else None
        )
        if (
            effect_base != base_sha
            or effect_head != run.current_head_sha
            or not self._same_manifest(manifest, effect_manifest)
            or not self._required_gates_pass(effect_gates)
            or (
                prepared_gate is not None
                and (
                    effect_prepared_gate is None
                    or not self._same_prepared_gate(
                        prepared_gate, effect_prepared_gate
                    )
                )
            )
        ):
            self._terminal_no_effect(
                operation_key,
                evidence={
                    "base_sha": effect_base,
                    "head_sha": effect_head,
                    "manifest_blob_sha": effect_manifest.blob_sha,
                    "required_gates": dict(effect_gates),
                    "verified_merge_prepared": (
                        dict(effect_prepared_gate)
                        if effect_prepared_gate is not None
                        else None
                    ),
                },
            )
            raise MergeAuthorityError(
                "protected base/manifest/head/gates changed after final validation"
            )

        claim = self.ledger.effect_claim(operation_key)
        self._validate_claim(
            claim,
            operation_key=operation_key,
            effect_type=effect_type,
            run_id=run.run_id,
        )
        credential = self.credentials.resolve(
            repository=canonical,
            credential_id=manifest.credential_id,
            rotation_generation=manifest.credential_generation,
        )
        if dry_run:
            readback: Mapping[str, object] = {
                "merged": False,
                "head_sha": run.current_head_sha,
                "outcome": "dry_run_no_merge",
                "credential_binding_resolved": credential is not None,
            }
            self.ledger.finish_effect(
                operation_key,
                observed_applied=True,
                evidence=readback,
            )
            return self._receipt(
                "dry_run_no_merge",
                operation_key,
                run,
                manifest,
                readback,
            )
        try:
            self.repository.conditional_merge(
                canonical,
                run.pr_number,
                expected_head_sha=run.current_head_sha,
                expected_base_sha=base_sha,
                expected_manifest_blob_sha=manifest.blob_sha,
                commit_title=commit_title,
                commit_message=commit_message,
                credential=credential,
            )
        except Exception:
            # Every transport failure is outcome-unknown until exact GitHub
            # readback proves whether the conditional effect applied.
            readback, applied = self._readback_and_reconcile(
                claim,
                run=run,
                detail="GitHub merge outcome is unknown; readback required",
            )
            return self._receipt(
                "merged" if applied else "retry_after_readback",
                operation_key,
                run,
                manifest,
                readback,
            )
        readback, applied = self._readback_and_reconcile(
            claim,
            run=run,
            detail="GitHub merge returned; authoritative readback required",
        )
        if not applied:
            raise MergeAuthorityError(
                "merge return was not confirmed by exact-head GitHub readback"
            )
        return self._receipt(
            "merged", operation_key, run, manifest, readback
        )

    def recover(
        self,
        run: VerificationRun,
        *,
        dry_run: bool = False,
    ) -> MergeEffectReceipt:
        """Reconcile one task-bound merge intent without replaying the effect."""
        canonical = RepoRef.parse(run.repository).canonical
        marker = self.ledger.merge_ready_receipt(run.run_id)
        pending = self.ledger.pending_effect_binding(run.run_id)
        effect_type = "github.merge.dry_run" if dry_run else "github.merge"
        if (
            not isinstance(marker, Mapping)
            or marker.get("repository") != canonical
            or marker.get("pr_number") != run.pr_number
            or marker.get("head_sha") != run.current_head_sha
            or not isinstance(pending, Mapping)
            or pending.get("effect_type") != effect_type
            or pending.get("task_id") != run.run_id
            or pending.get("head_sha") != run.current_head_sha
            or not isinstance(pending.get("operation_key"), str)
            or not isinstance(pending.get("payload"), Mapping)
        ):
            raise MergeAuthorityError(
                "merge recovery requires exact durable task-bound authority"
            )
        operation_key = str(pending["operation_key"])
        payload = pending["payload"]
        assert isinstance(payload, Mapping)
        base_sha = payload.get("base_sha")
        if not isinstance(base_sha, str):
            raise MergeAuthorityError("merge recovery base identity is malformed")
        manifest = self.repository.delivery_manifest(canonical, base_sha)
        if (
            payload.get("repository") != canonical
            or payload.get("pr_number") != run.pr_number
            or payload.get("head_sha") != run.current_head_sha
            or payload.get("manifest_blob_sha") != manifest.blob_sha
            or payload.get("manifest_sha256") != manifest.content_sha256
            or payload.get("credential_id") != manifest.credential_id
            or payload.get("rotation_generation")
            != manifest.credential_generation
            or payload.get("fixed_commit_title")
            != fixed_verified_merge_commit_title(run.pr_number)
            or payload.get("fixed_commit_message")
            != FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
        ):
            raise MergeAuthorityError(
                "merge recovery manifest binding is inconsistent"
            )
        reconciliation_evidence = pending.get(
            "reconciliation_evidence"
        )
        reconciliation_sequence = pending.get(
            "reconciliation_receipt_sequence"
        )
        durable_reconciliation = (
            isinstance(reconciliation_evidence, Mapping)
            and isinstance(reconciliation_sequence, int)
            and not isinstance(reconciliation_sequence, bool)
        )
        if (
            not dry_run
            and durable_reconciliation
            and isinstance(reconciliation_evidence, Mapping)
            and reconciliation_evidence.get("merged") is True
            and not self._merged_exactly(reconciliation_evidence, run)
        ):
            raise MergeAuthorityError(
                "durable merge reconciliation lacks exact governed commit text"
            )
        if (
            pending.get("outbox_status") == "succeeded"
            and durable_reconciliation
        ):
            assert isinstance(reconciliation_evidence, Mapping)
            if dry_run:
                outcome = "dry_run_no_merge"
            elif self._merged_exactly(reconciliation_evidence, run):
                outcome = "merged"
            elif (
                reconciliation_evidence.get("outcome")
                == "terminal_no_effect_after_recovery"
            ):
                outcome = "terminal_no_effect"
            else:
                outcome = "retry_after_readback"
            return self._receipt(
                outcome,
                operation_key,
                run,
                manifest,
                reconciliation_evidence,
            )
        if (
            pending.get("outbox_status") == "pending"
            and durable_reconciliation
        ):
            assert isinstance(reconciliation_evidence, Mapping)
            return self._receipt(
                "retry_after_readback",
                operation_key,
                run,
                manifest,
                reconciliation_evidence,
            )
        try:
            self.ledger.recover_effect(
                operation_key,
                run_id=run.run_id,
                effect_type=effect_type,
            )
        except ValueError as exc:
            raise MergeAuthorityError(
                "merge recovery could not acquire current fenced authority"
            ) from exc
        if dry_run:
            readback: Mapping[str, object] = {
                "merged": False,
                "head_sha": run.current_head_sha,
                "outcome": "recovered_dry_run_no_merge",
            }
            self.ledger.finish_effect(
                operation_key,
                observed_applied=True,
                evidence=readback,
            )
            return self._receipt(
                "dry_run_no_merge",
                operation_key,
                run,
                manifest,
                readback,
            )

        readback = self.repository.merge_readback(
            canonical, run.pr_number
        )
        if self._merged_exactly(readback, run):
            self.ledger.finish_effect(
                operation_key,
                observed_applied=True,
                evidence=dict(readback),
            )
            return self._receipt(
                "merged",
                operation_key,
                run,
                manifest,
                readback,
            )
        if readback.get("merged") is True:
            raise MergeAuthorityError(
                "merged GitHub readback lacks exact governed commit text"
            )

        current_base = self.repository.protected_base_sha(canonical)
        current_manifest = self.repository.delivery_manifest(
            canonical, current_base
        )
        current_head = self.repository.current_pr_head(
            canonical, run.pr_number
        )
        current_gates = self.repository.required_gates(
            canonical, run.pr_number, current_head
        )
        drifted = (
            current_base != base_sha
            or current_head != run.current_head_sha
            or not self._same_manifest(manifest, current_manifest)
            or not self._required_gates_pass(current_gates)
        )
        self.ledger.finish_effect(
            operation_key,
            observed_applied=drifted,
            evidence={
                "outcome": (
                    "terminal_no_effect_after_recovery"
                    if drifted
                    else "retry_after_readback"
                ),
                **dict(readback),
            },
        )
        return self._receipt(
            "terminal_no_effect" if drifted else "retry_after_readback",
            operation_key,
            run,
            manifest,
            readback,
        )

    @staticmethod
    def _merged_exactly(
        readback: Mapping[str, object], run: VerificationRun
    ) -> bool:
        return bool(
            readback.get("merged") is True
            and readback.get("head_sha") == run.current_head_sha
            and isinstance(readback.get("merge_commit_sha"), str)
            and readback.get("merge_commit_sha")
            and readback.get("merge_commit_title")
            == fixed_verified_merge_commit_title(run.pr_number)
            and readback.get("merge_commit_message")
            == FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
        )

    @staticmethod
    def _receipt(
        outcome: str,
        operation_key: str,
        run: VerificationRun,
        manifest: ProtectedDeliveryManifest,
        readback: Mapping[str, object],
    ) -> MergeEffectReceipt:
        return MergeEffectReceipt(
            outcome=outcome,
            operation_key=operation_key,
            repository=run.repository.lower(),
            pr_number=run.pr_number,
            head_sha=run.current_head_sha,
            base_sha=manifest.base_sha,
            manifest_blob_sha=manifest.blob_sha,
            manifest_sha256=manifest.content_sha256,
            credential_id=manifest.credential_id,
            credential_generation=manifest.credential_generation,
            readback=dict(readback),
        )


__all__ = [
    "BuilderOpsOutboxExecutor",
    "HostCredentialResolver",
    "MergeAuthorityError",
    "MergeEffectReceipt",
    "ProtectedDeliveryManifest",
    "ProtectedRepositoryAuthority",
    "OutboxExecutorAuthority",
    "VerificationMergeExecutor",
]
