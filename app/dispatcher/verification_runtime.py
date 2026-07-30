"""Host composition for one API-backed, fenced BCP-05 verification cycle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import VerificationConsumer
from app.dispatcher.verification_merge import (
    MergeEffectReceipt,
    VerificationMergeExecutor,
)


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
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("contract") != "bcp05_demerzel_cycle.v1"
                or receipt.get("run_id") != run.run_id
                or receipt.get("repository") != run.repository.lower()
                or receipt.get("pr_number") != run.pr_number
                or receipt.get("head_sha") != run.current_head_sha
                or receipt.get("governing_issue")
                != run.request.get("linked_issue")
                or receipt.get("terminal_outcome")
                != "dry_run_no_merge"
                or not isinstance(receipt.get("operation_key"), str)
                or not isinstance(receipt.get("readback"), Mapping)
                or receipt.get("raw_secret_count") != 0
            ):
                raise ValueError(
                    "completed verification cycle receipt is malformed"
                )
            return dict(receipt)
        if run.status == "backoff":
            receipt = run.terminal_receipt
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("contract") != "bcp05_demerzel_cycle.v1"
                or receipt.get("run_id") != run.run_id
                or receipt.get("terminal_outcome")
                != "retry_after_readback"
            ):
                raise ValueError(
                    "deferred verification cycle receipt is malformed"
                )
            return dict(receipt)
        pending = self.ledger.pending_effect_binding(run_id)
        if (
            isinstance(pending, Mapping)
            and pending.get("effect_type") == "github.merge.dry_run"
        ):
            merge_receipt = self.merge_executor.recover(
                run, dry_run=True
            )
            return self._settle(run_id, merge_receipt)
        if self.ledger.merge_ready_receipt(run_id) is None:
            run = self.consumer.recover(run_id)
        return self._finish_ready_dry_cycle(run.run_id)

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
        return receipt

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


__all__ = ["HostFencedVerificationCycle"]
