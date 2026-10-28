"""Dormant AUTOOPS-05 move/rename composition over the HKA placement port."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable

from app.knowledge.placement import KnowledgePlacementOwner, PlacementIntent, PlacementResult
from .contracts import (
    ConvergenceState,
    OperationContext,
    OperationConvergence,
    OperationRequest,
    OperationStatus,
    SourceEffectStatus,
)
from .execution_kernel import OwnerExecutionResult

MOVE_OPERATION_ID = "artifact.move"
RENAME_OPERATION_ID = "artifact.rename"


@dataclass(frozen=True)
class PlacementOperationServerConfig:
    owner: KnowledgePlacementOwner
    context: OperationContext
    artifact_id: str
    source: str


def build_placement_operation_handlers(
    config: PlacementOperationServerConfig,
) -> dict[str, Callable[[OperationRequest], OwnerExecutionResult]]:
    return {
        operation: lambda request: _execute(request, config)
        for operation in (MOVE_OPERATION_ID, RENAME_OPERATION_ID)
    }


def reconcile_placement_operation(
    request: OperationRequest, config: PlacementOperationServerConfig
) -> OwnerExecutionResult:
    """Explicit owner recovery, separate from the kernel's historical replay.

    No transport installs this seam. Its caller must retain the kernel's current
    delegation/policy admission; HKA also rechecks the bound WSP/GOV effect seam.
    """
    return _execute(request, config, recover=True)


def _execute(
    request: OperationRequest, config: PlacementOperationServerConfig, *, recover: bool = False
) -> OwnerExecutionResult:
    def refuse(status: OperationStatus, reason: str) -> OwnerExecutionResult:
        return OwnerExecutionResult(status, warnings=(reason,))

    if (
        request.operation_version != "ygg.operation.v1"
        or request.mode != "execute"
        or request.operation_id not in {MOVE_OPERATION_ID, RENAME_OPERATION_ID}
    ):
        return refuse(
            OperationStatus.NOT_SUPPORTED, "placement supports only move/rename v1 execute"
        )
    if request.context != config.context or (
        config.context.active_context_ref,
        config.context.vault_generation,
    ) != (config.owner.context_ref, config.owner.vault_generation):
        return refuse(
            OperationStatus.REJECTED, "placement context differs from the immutable server binding"
        )
    if request.targets != ({"artifact_id": config.artifact_id},) or not config.artifact_id:
        return refuse(
            OperationStatus.REJECTED, "placement requires exactly the server-bound artifact"
        )
    if request.provenance is not None and request.provenance.actor != config.owner.actor:
        return refuse(OperationStatus.REJECTED, "placement actor differs from the server principal")
    if not isinstance(request.expected_version, str) or not request.expected_version:
        return refuse(OperationStatus.CONFLICTED, "expected source generation is required")
    key = "destination" if request.operation_id == MOVE_OPERATION_ID else "name"
    if set(request.arguments) != {key, "destination_generation"} or not all(
        isinstance(value, str) and value for value in request.arguments.values()
    ):
        return refuse(
            OperationStatus.INVALID,
            "placement requires a destination and its expected absent generation",
        )
    destination = str(request.arguments[key])
    if request.operation_id == RENAME_OPERATION_ID:
        if PurePosixPath(destination).name != destination or "\\" in destination:
            return refuse(OperationStatus.INVALID, "rename accepts one portable filename")
        destination = str(PurePosixPath(config.source).with_name(destination))
    intent = PlacementIntent(
        request.request_id,
        request.operation_id,
        config.artifact_id,
        config.source,
        destination,
        request.expected_version,
        str(request.arguments["destination_generation"]),
        config.context.active_context_ref,
        config.context.vault_generation or "",
    )
    return _map(config.owner.place_artifact(intent, recover=recover), request)


def _map(result: PlacementResult, request: OperationRequest) -> OwnerExecutionResult:
    record = result.record or {}
    receipt = record.get("receipt")
    source = (
        SourceEffectStatus.COMMITTED if result.source_committed else SourceEffectStatus.NOT_APPLIED
    )
    if result.status == "recovery_required" and not record:
        source = SourceEffectStatus.UNKNOWN
    projection = (
        ConvergenceState.REBUILD_REQUIRED
        if result.source_committed
        else ConvergenceState.NOT_REQUIRED
    )
    return OwnerExecutionResult(
        OperationStatus(result.status),
        effect_id=request.request_id if record else None,
        effect_receipt={"receipt_id": receipt["receipt_id"], "placement": receipt}
        if receipt
        else {
            "placement": {
                "recovery_ref": request.request_id,
                "phase": record.get("phase"),
                "source_locator": record.get("intent", {}).get("source"),
                "destination_locator": record.get("intent", {}).get("destination"),
            }
        }
        if record
        else None,
        convergence=OperationConvergence(
            source,
            store=projection,
            index=projection,
            link=projection,
            extensions={
                "owner": "knowledge.placement",
                "phase": record.get("phase"),
                "locator_repair": "source-backed replay"
                if result.source_committed
                else "not_required",
            },
        ),
        warnings=(result.reason,) if result.reason else (),
    )
