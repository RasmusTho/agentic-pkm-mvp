"""Host composition for one API-backed, fenced BCP-05 verification cycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import VerificationConsumer
from app.dispatcher.verification_dispatch import (
    VerificationSubscriptionBusy,
)
from app.dispatcher.verification_merge import (
    MergeEffectReceipt,
    VerificationMergeExecutor,
    verification_authority_digest,
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
        set(receipt) != _CYCLE_RECEIPT_KEYS
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
    validated_dry_run_readback(
        readback,
        head_sha=receipt.get("head_sha"),
        terminal_outcome=receipt.get("terminal_outcome"),
    )
    return dict(receipt)


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

    def run_dry_cycle(
        self, request: Mapping[str, object]
    ) -> Mapping[str, object]:
        run = self.consumer.consume(request)
        return self._finish_ready_dry_cycle(run.run_id)

    def recover_dry_cycle(self, run_id: str) -> Mapping[str, object]:
        run = self.ledger.get(run_id)
        if run is None:
            raise ValueError("verification cycle run is unavailable")
        if run.status == "completed":
            receipt = run.terminal_receipt
            return self._validated_receipt(
                run, receipt, allowed_outcomes={"dry_run_no_merge"}
            )
        if run.status == "backoff":
            receipt = run.terminal_receipt
            return self._validated_receipt(
                run, receipt, allowed_outcomes={"retry_after_readback"}
            )
        if self._lease_is_live(run):
            raise VerificationSubscriptionBusy(
                f"verification cycle {run_id} still has a live task owner"
            )
        pending = self.ledger.pending_effect_binding(run_id)
        merge_ready = self.ledger.merge_ready_receipt(run_id)
        if merge_ready is not None:
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
            return self._settle(run_id, merge_receipt)
        if merge_ready is None:
            run = self.consumer.recover(run_id)
        return self._finish_ready_dry_cycle(run.run_id)

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
        if (
            run is None
            or run.lease_id is None
            or self.ledger.merge_ready_receipt(run_id) is None
        ):
            raise ValueError(
                "verification cycle did not reach durable merge readiness"
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
    "validated_cycle_receipt_shape",
    "validated_dry_run_readback",
]
