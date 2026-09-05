"""Host composition for one API-backed, fenced BCP-05 verification cycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.builderops.execution_routing_receipts import (
    CanaryReceiptEvidenceError,
    ReceiptStore,
    load_canary_receipt_for_verification_request,
    record_acceptance_observation,
    validate_canary_receipt_request_binding,
)
from app.dispatcher.verification_consumer import VerificationConsumer
from app.dispatcher.verification_dispatch import (
    VerificationSubscriptionBusy,
)
from app.dispatcher.verification_merge import (
    MergeEffectReceipt,
    VerificationMergeExecutor,
    verification_authority_digest,
)
from app.dispatcher.linux_containment import (
    validated_linux_containment_receipt,
)
from app.dispatcher.verified_merge import (
    FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
    fixed_verified_merge_commit_title,
)


_CYCLE_RECEIPT_KEYS = frozenset(
    {
        "contract",
        "governing_issue",
        "repository",
        "pr_number",
        "head_sha",
        "run_id",
        "terminal_outcome",
        "operation_key",
        "readback",
        "merge_authority",
        "raw_secret_count",
    }
)
_OPTIONAL_CYCLE_RECEIPT_KEYS = frozenset({"containment"})
_DRY_READBACK_KEYS = frozenset(
    {
        "merged",
        "head_sha",
        "outcome",
        "credential_binding_resolved",
    }
)
_DRY_READBACK_OUTCOMES = frozenset(
    {"dry_run_no_merge", "recovered_dry_run_no_merge"}
)
_EFFECT_PAYLOAD_KEYS = frozenset(
    {
        "repository",
        "governing_issue",
        "pr_number",
        "head_sha",
        "base_sha",
        "manifest_blob_sha",
        "manifest_sha256",
        "credential_id",
        "rotation_generation",
        "fixed_commit_title",
        "fixed_commit_message",
        "verified_merge_prepared",
        "review_authority_sha256",
    }
)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validated_dry_run_readback(
    readback: Mapping[str, object],
    *,
    head_sha: object,
    terminal_outcome: object,
) -> dict[str, object]:
    """Validate the complete safe stdout/durable dry-run readback schema."""

    if (
        not {"merged", "head_sha"}.issubset(readback)
        or not set(readback).issubset(_DRY_READBACK_KEYS)
        or not isinstance(readback.get("merged"), bool)
        or readback.get("head_sha") != head_sha
        or (
            "outcome" in readback
            and readback.get("outcome") not in _DRY_READBACK_OUTCOMES
        )
        or (
            "credential_binding_resolved" in readback
            and readback.get("credential_binding_resolved") is not True
        )
        or readback.get("merged") is not False
    ):
        raise ValueError("verification cycle readback is malformed")
    return dict(readback)


def validated_cycle_receipt_shape(
    receipt: Mapping[str, object],
) -> dict[str, object]:
    """Validate every public BCP-05 receipt leaf before stdout or replay."""

    from app.builderops.control_plane.routing import RepoRef

    authority = receipt.get("merge_authority")
    readback = receipt.get("readback")
    raw_repository = receipt.get("repository")
    try:
        repository = RepoRef.parse(
            raw_repository if isinstance(raw_repository, str) else None
        ).canonical
    except Exception as exc:
        raise ValueError("verification cycle receipt is malformed") from exc
    safe_id = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    hex40 = re.compile(r"[0-9a-f]{40}")
    hex64 = re.compile(r"[0-9a-f]{64}")
    if (
        not _CYCLE_RECEIPT_KEYS.issubset(receipt)
        or not set(receipt).issubset(
            _CYCLE_RECEIPT_KEYS | _OPTIONAL_CYCLE_RECEIPT_KEYS
        )
        or receipt.get("contract") != "bcp05_demerzel_cycle.v1"
        or not _positive_int(receipt.get("governing_issue"))
        or receipt.get("repository") != repository
        or not _positive_int(receipt.get("pr_number"))
        or not isinstance(receipt.get("head_sha"), str)
        or hex40.fullmatch(str(receipt.get("head_sha"))) is None
        or not isinstance(receipt.get("run_id"), str)
        or safe_id.fullmatch(str(receipt.get("run_id"))) is None
        or receipt.get("terminal_outcome")
        not in {"dry_run_no_merge", "retry_after_readback"}
        or not isinstance(receipt.get("operation_key"), str)
        or safe_id.fullmatch(str(receipt.get("operation_key"))) is None
        or not isinstance(readback, Mapping)
        or not isinstance(authority, Mapping)
        or set(authority)
        != {
            "base_sha",
            "manifest_blob_sha",
            "manifest_sha256",
            "credential_id",
            "credential_generation",
        }
        or not isinstance(authority.get("base_sha"), str)
        or hex40.fullmatch(str(authority.get("base_sha"))) is None
        or not isinstance(authority.get("manifest_blob_sha"), str)
        or safe_id.fullmatch(str(authority.get("manifest_blob_sha"))) is None
        or not isinstance(authority.get("manifest_sha256"), str)
        or hex64.fullmatch(str(authority.get("manifest_sha256"))) is None
        or not isinstance(authority.get("credential_id"), str)
        or safe_id.fullmatch(str(authority.get("credential_id"))) is None
        or not isinstance(authority.get("credential_generation"), int)
        or isinstance(authority.get("credential_generation"), bool)
        or int(authority.get("credential_generation", 0)) <= 0
        or not isinstance(receipt.get("raw_secret_count"), int)
        or isinstance(receipt.get("raw_secret_count"), bool)
        or receipt.get("raw_secret_count") != 0
    ):
        raise ValueError("verification cycle receipt is malformed")
    if "containment" in receipt:
        validated_containment_receipt_shape(receipt["containment"])
    validated_dry_run_readback(
        readback,
        head_sha=receipt.get("head_sha"),
        terminal_outcome=receipt.get("terminal_outcome"),
    )
    return dict(receipt)


def validated_containment_receipt_shape(value: object) -> dict[str, object]:
    """Validate the Linux receipt before API replay or public output."""

    return validated_linux_containment_receipt(value)


class HostFencedVerificationCycle:
    """Compose the retained reviewer with the host-only no-merge executor.

    BCP-05 uses this safe dry-run path for installed-main acceptance. A real
    merge still requires an injected conditional transport and the complete
    verification-and-closure phase ceremony; this class never invents that
    authority.
    """

    def __init__(
        self,
        ledger: BuilderOpsVerificationLedger,
        consumer: VerificationConsumer,
        merge_executor: VerificationMergeExecutor,
        *,
        holder: str,
        containment_receipt_required: bool = False,
        canary_receipt_store: ReceiptStore | None = None,
        canary_receipt_store_factory: Callable[[], ReceiptStore] | None = None,
    ) -> None:
        if consumer.ledger is not ledger or not consumer.host_fenced_merge:
            raise ValueError(
                "host cycle requires the API ledger in host-fenced mode"
            )
        if merge_executor.ledger is not ledger:
            raise ValueError(
                "host cycle merge executor must share the API ledger"
            )
        if (
            ledger.effect_outbox is None
            or merge_executor.outbox is not ledger.effect_outbox
        ):
            raise ValueError(
                "host cycle requires one shared BuilderOps outbox authority"
            )
        self.ledger = ledger
        self.consumer = consumer
        self.merge_executor = merge_executor
        self.holder = holder
        self.containment_receipt_required = containment_receipt_required
        self.canary_receipt_store = canary_receipt_store
        self.canary_receipt_store_factory = canary_receipt_store_factory

    def run_dry_cycle(
        self,
        request: Mapping[str, object],
        *,
        canary_receipt: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        canary_receipt = self._resolve_canary_receipt(request, canary_receipt)
        run = self.consumer.consume(request)
        receipt = self._finish_ready_dry_cycle(run.run_id)
        if (
            canary_receipt is not None
            and receipt.get("terminal_outcome") == "dry_run_no_merge"
        ):
            completed_run = self.ledger.get(run.run_id)
            if completed_run is None:
                raise CanaryReceiptEvidenceError(
                    "verification run disappeared before canary acceptance"
                )
            self._observe_canary(completed_run, canary_receipt)
        return receipt

    def recover_dry_cycle(
        self,
        run_id: str,
        *,
        canary_receipt: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        run = self.ledger.get(run_id)
        if run is None:
            raise ValueError("verification cycle run is unavailable")
        canary_receipt = self._resolve_canary_receipt(
            run.request, canary_receipt
        )
        if run.status == "completed":
            receipt = run.terminal_receipt
            validated = self._validated_receipt(
                run, receipt, allowed_outcomes={"dry_run_no_merge"}
            )
            self._observe_canary(run, canary_receipt)
            return validated
        if run.status == "backoff":
            retry_receipt = run.terminal_receipt
            return self._validated_receipt(
                run, retry_receipt, allowed_outcomes={"retry_after_readback"}
            )
        if self._lease_is_live(run):
            raise VerificationSubscriptionBusy(
                f"verification cycle {run_id} still has a live task owner"
            )
        pending = self.ledger.pending_effect_binding(run_id)
        merge_ready = self.ledger.merge_ready_receipt(run_id)
        if merge_ready is not None:
            if (
                self.containment_receipt_required
                and "containment" not in merge_ready
            ):
                raise ValueError(
                    "verification Linux containment evidence is unavailable"
                )
            # A durable merge-ready marker means model work must not be
            # relaunched. Rebind every remaining effect and settlement to a
            # fresh task fence before touching the outbox.
            prior_lease_id = run.lease_id
            run = self.ledger.claim(run_id, self.holder)
            if (
                prior_lease_id is not None
                and run.lease_id == prior_lease_id
            ):
                raise VerificationSubscriptionBusy(
                    f"verification cycle {run_id} did not acquire a fresh "
                    "task fence"
                )
        if (
            isinstance(pending, Mapping)
            and pending.get("effect_type") == "github.merge.dry_run"
        ):
            merge_receipt = self.merge_executor.recover(
                run, dry_run=True
            )
            settled_receipt = self._settle(run_id, merge_receipt)
            if (
                canary_receipt is not None
                and settled_receipt.get("terminal_outcome") == "dry_run_no_merge"
            ):
                completed_run = self.ledger.get(run_id)
                if completed_run is None:
                    raise CanaryReceiptEvidenceError(
                        "verification run disappeared before canary acceptance"
                    )
                self._observe_canary(completed_run, canary_receipt)
            return settled_receipt
        if merge_ready is None:
            run = self.consumer.recover(run_id)
        final_receipt = self._finish_ready_dry_cycle(run.run_id)
        if (
            canary_receipt is not None
            and final_receipt.get("terminal_outcome") == "dry_run_no_merge"
        ):
            completed_run = self.ledger.get(run.run_id)
            if completed_run is None:
                raise CanaryReceiptEvidenceError(
                    "verification run disappeared before canary acceptance"
                )
            self._observe_canary(completed_run, canary_receipt)
        return final_receipt

    def _resolve_canary_receipt(
        self,
        request: Mapping[str, object],
        canary_receipt: Mapping[str, object] | None,
    ) -> Mapping[str, object] | None:
        """Use an explicit receipt or rebuild it from durable request lineage."""

        if canary_receipt is not None:
            validate_canary_receipt_request_binding(canary_receipt, request)
            return canary_receipt
        if request.get("canary_identity") is None:
            return None
        if self.canary_receipt_store is None:
            if self.canary_receipt_store_factory is None:
                raise CanaryReceiptEvidenceError(
                    "canary acceptance requires the BuilderOps receipt store"
                )
            self.canary_receipt_store = self.canary_receipt_store_factory()
        resolved = load_canary_receipt_for_verification_request(
            self.canary_receipt_store, request
        )
        validate_canary_receipt_request_binding(resolved, request)
        return resolved

    def _observe_canary(
        self,
        run: Any,
        canary_receipt: Mapping[str, object] | None,
    ) -> None:
        """Consume the verifier result without changing verifier authority."""

        if canary_receipt is None:
            return
        if self.canary_receipt_store is None:
            if self.canary_receipt_store_factory is None:
                raise CanaryReceiptEvidenceError(
                    "canary acceptance requires the BuilderOps receipt store"
                )
            self.canary_receipt_store = self.canary_receipt_store_factory()
        linked_issue = run.request.get("linked_issue")
        if (
            not isinstance(linked_issue, int)
            or isinstance(linked_issue, bool)
            or linked_issue <= 0
        ):
            raise CanaryReceiptEvidenceError(
                "verification run lacks a governing issue for canary acceptance"
            )
        verification_receipt: Mapping[str, object] | None = None
        merge_ready = self.ledger.merge_ready_receipt(run.run_id)
        if isinstance(merge_ready, Mapping):
            candidate = merge_ready.get("coordinator_receipt")
            if isinstance(candidate, Mapping):
                # The coordinator receipt carries the verifier verdict, while
                # the durable merge-ready wrapper carries the exact runtime
                # identity.  Bind both before the evidence-only consumer sees
                # the result; a bare verdict is never accepted as delivery.
                verification_receipt = dict(candidate)
                runtime_identity = {
                    "repository": run.repository,
                    "pr_number": run.pr_number,
                    "head_sha": run.current_head_sha,
                    "run_id": run.run_id,
                }
                for key, value in runtime_identity.items():
                    if key not in verification_receipt:
                        verification_receipt[key] = value
        if verification_receipt is None:
            verification_receipt = run.terminal_receipt
        reason = None
        if verification_receipt is None:
            reason = "verification_not_reached"
        record_acceptance_observation(
            self.canary_receipt_store,
            canary_receipt,
            verification_receipt,
            repository=run.repository,
            pr_number=run.pr_number,
            head_sha=run.current_head_sha,
            governing_issue=linked_issue,
            run_id=run.run_id,
            verification_request=run.request,
            not_accepted_reason=reason,
        )

    @staticmethod
    def _lease_is_live(run: object) -> bool:
        expires_at = getattr(run, "lease_expires_at", None)
        if expires_at is None:
            return False
        if not isinstance(expires_at, str):
            raise ValueError(
                "verification cycle task lease expiry is malformed"
            )
        try:
            expires = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                "verification cycle task lease expiry is malformed"
            ) from exc
        if expires.tzinfo is None:
            raise ValueError(
                "verification cycle task lease expiry is malformed"
            )
        return expires.astimezone(timezone.utc) > datetime.now(timezone.utc)

    def _finish_ready_dry_cycle(
        self, run_id: str
    ) -> Mapping[str, object]:
        run = self.ledger.get(run_id)
        merge_ready = self.ledger.merge_ready_receipt(run_id)
        if (
            run is None
            or run.lease_id is None
            or merge_ready is None
        ):
            raise ValueError(
                "verification cycle did not reach durable merge readiness"
            )
        if (
            self.containment_receipt_required
            and "containment" not in merge_ready
        ):
            raise ValueError(
                "verification Linux containment evidence is unavailable"
            )
        merge_receipt = self.merge_executor.execute(
            run,
            holder=self.holder,
            lease_id=run.lease_id,
            dry_run=True,
        )
        return self._settle(run_id, merge_receipt)

    def _settle(
        self,
        run_id: str,
        merge_receipt: MergeEffectReceipt,
    ) -> Mapping[str, object]:
        receipt = self._receipt(run_id, merge_receipt)
        if merge_receipt.outcome == "dry_run_no_merge":
            return self._complete(run_id, receipt)
        if merge_receipt.outcome != "retry_after_readback":
            raise ValueError(
                "dry verification cycle returned an invalid outcome"
            )
        run = self.ledger.get(run_id)
        if run is None or run.lease_id is None:
            raise ValueError(
                "verification cycle lost its task lease before deferral"
            )
        self.ledger.backoff(
            run_id,
            receipt,
            (
                datetime.now(timezone.utc) + timedelta(minutes=1)
            ).isoformat(),
            holder=self.holder,
            lease_id=run.lease_id,
        )
        return receipt

    def _receipt(
        self,
        run_id: str,
        merge_receipt: MergeEffectReceipt,
    ) -> Mapping[str, object]:
        run = self.ledger.get(run_id)
        if run is None:
            raise ValueError(
                "verification cycle disappeared before receipt construction"
            )
        receipt: dict[str, Any] = {
            "contract": "bcp05_demerzel_cycle.v1",
            "governing_issue": run.request.get("linked_issue"),
            "repository": run.repository.lower(),
            "pr_number": run.pr_number,
            "head_sha": run.current_head_sha,
            "run_id": run.run_id,
            "terminal_outcome": merge_receipt.outcome,
            "operation_key": merge_receipt.operation_key,
            "readback": dict(merge_receipt.readback),
            "merge_authority": {
                key: value
                for key, value in asdict(merge_receipt).items()
                if key
                in {
                    "base_sha",
                    "manifest_blob_sha",
                    "manifest_sha256",
                    "credential_id",
                    "credential_generation",
                }
            },
            "raw_secret_count": 0,
        }
        merge_ready = self.ledger.merge_ready_receipt(run_id)
        if not isinstance(merge_ready, Mapping):
            raise ValueError("verification merge readiness is unavailable")
        if (
            self.containment_receipt_required
            and "containment" not in merge_ready
        ):
            raise ValueError(
                "verification Linux containment evidence is unavailable"
            )
        if "containment" in merge_ready:
            receipt["containment"] = validated_containment_receipt_shape(
                merge_ready["containment"]
            )
        return self._validated_receipt(
            run,
            receipt,
            allowed_outcomes={"dry_run_no_merge", "retry_after_readback"},
        )

    def _validated_receipt(
        self,
        run: Any,
        receipt: object,
        *,
        allowed_outcomes: set[str],
    ) -> dict[str, object]:
        pending = self.ledger.pending_effect_binding(run.run_id)
        if not isinstance(receipt, Mapping) or not isinstance(pending, Mapping):
            raise ValueError("verification cycle receipt is malformed")
        payload = pending.get("payload")
        outbox_intent = pending.get("outbox_intent")
        readback = receipt.get("readback")
        authority = receipt.get("merge_authority")
        evidence = pending.get("reconciliation_evidence")
        if not all(
            isinstance(value, Mapping)
            for value in (payload, outbox_intent, readback, authority, evidence)
        ):
            raise ValueError("verification cycle receipt is malformed")
        assert isinstance(payload, Mapping)
        assert isinstance(outbox_intent, Mapping)
        assert isinstance(readback, Mapping)
        assert isinstance(authority, Mapping)
        assert isinstance(evidence, Mapping)
        expected_authority = {
            "base_sha": payload.get("base_sha"),
            "manifest_blob_sha": payload.get("manifest_blob_sha"),
            "manifest_sha256": payload.get("manifest_sha256"),
            "credential_id": payload.get("credential_id"),
            "credential_generation": payload.get("rotation_generation"),
        }
        sequence = pending.get("reconciliation_receipt_sequence")
        terminal_outcome = receipt.get("terminal_outcome")
        expected_statuses = (
            {"succeeded"}
            if terminal_outcome == "dry_run_no_merge"
            else {"pending", "succeeded"}
        )
        marker = self.ledger.merge_ready_receipt(run.run_id)
        if (
            not isinstance(marker, Mapping)
            or receipt.get("contract") != "bcp05_demerzel_cycle.v1"
            or receipt.get("run_id") != run.run_id
            or receipt.get("repository") != run.repository.lower()
            or receipt.get("pr_number") != run.pr_number
            or receipt.get("head_sha") != run.current_head_sha
            or receipt.get("governing_issue")
            != run.request.get("linked_issue")
            or receipt.get("terminal_outcome") not in allowed_outcomes
            or pending.get("effect_type") != "github.merge.dry_run"
            or pending.get("task_id") != run.run_id
            or pending.get("head_sha") != run.current_head_sha
            or outbox_intent.get("repository") != run.repository.lower()
            or outbox_intent.get("operation_key")
            != pending.get("operation_key")
            or outbox_intent.get("task_id") != run.run_id
            or outbox_intent.get("effect_type") != "github.merge.dry_run"
            or outbox_intent.get("payload") != payload
            or receipt.get("operation_key") != pending.get("operation_key")
            or set(payload) != _EFFECT_PAYLOAD_KEYS
            or payload.get("repository") != run.repository.lower()
            or payload.get("governing_issue")
            != run.request.get("linked_issue")
            or payload.get("pr_number") != run.pr_number
            or payload.get("head_sha") != run.current_head_sha
            or payload.get("verified_merge_prepared") is not None
            or payload.get("fixed_commit_title")
            != fixed_verified_merge_commit_title(run.pr_number)
            or payload.get("fixed_commit_message")
            != FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
            or payload.get("review_authority_sha256")
            != verification_authority_digest(marker)
            or pending.get("outbox_status") not in expected_statuses
            or not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or dict(readback) != dict(evidence)
            or dict(authority) != expected_authority
            or receipt.get("raw_secret_count") != 0
        ):
            raise ValueError("verification cycle receipt is malformed")
        if (
            self.containment_receipt_required
            and "containment" not in marker
        ) or (("containment" in marker) != ("containment" in receipt)):
            raise ValueError("verification cycle receipt is malformed")
        if marker.get("containment") != receipt.get("containment"):
            raise ValueError("verification cycle receipt is malformed")
        return validated_cycle_receipt_shape(receipt)

    def _complete(
        self,
        run_id: str,
        receipt: Mapping[str, object],
    ) -> Mapping[str, object]:
        run = self.ledger.get(run_id)
        if run is None or run.lease_id is None:
            raise ValueError(
                "verification cycle lost its task lease before completion"
            )
        self.ledger.terminal(
            run_id,
            "completed",
            receipt,
            holder=self.holder,
            lease_id=run.lease_id,
        )
        return dict(receipt)


__all__ = [
    "HostFencedVerificationCycle",
    "validated_containment_receipt_shape",
    "validated_cycle_receipt_shape",
    "validated_dry_run_readback",
]
