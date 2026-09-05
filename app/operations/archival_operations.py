"""Dormant direct-composition handlers for governed archival operations.

This module intentionally does not install routes, discovery, GUI, MCP, or a
runtime singleton. Issue #5352 owns that later authenticated integration.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.archival.contracts import ArtifactClass, LivenessState, TransitionStage
from app.heimdal.local_archive import (
    OPERATION_RESTORE_SERVICE,
    ArchiveDegradedError,
    OperationTargetRefused,
    run_single_record_archive_operation,
    run_single_record_restore_operation,
    resolve_operation_restore_target,
)

from .contracts import OperationRequest, OperationStatus
from .execution_kernel import ArchivalOperationReceipt, OwnerExecutionResult

ARCHIVE_OPERATION_ID = "artifact.archive"
RESTORE_OPERATION_ID = "artifact.restore"


@dataclass(frozen=True)
class ArchivalOperationServerConfig:
    """Server-origin configuration; never populated from an operation request."""

    config_root: Path
    channel: str
    vault_root: Path
    restore_service: str = OPERATION_RESTORE_SERVICE


def build_archival_operation_handlers(
    server_config: ArchivalOperationServerConfig,
) -> dict[str, Callable[[OperationRequest], OwnerExecutionResult]]:
    """Return dormant handlers for explicit direct kernel composition only."""
    return {
        ARCHIVE_OPERATION_ID: lambda request: _execute(request, server_config),
        RESTORE_OPERATION_ID: lambda request: _execute(request, server_config),
    }


def _execute(request: OperationRequest, config: ArchivalOperationServerConfig) -> OwnerExecutionResult:
    target = _source_target(request)
    if isinstance(target, OwnerExecutionResult):
        return target
    if type(request.expected_version) is not int or request.expected_version < 0:
        return OwnerExecutionResult(OperationStatus.CONFLICTED, warnings=("expected generation is required",))
    try:
        proof = resolve_operation_restore_target(target, service_reader=config.restore_service)
    except OperationTargetRefused as exc:
        return OwnerExecutionResult(OperationStatus.REJECTED, warnings=(str(exc),))
    except Exception:
        return OwnerExecutionResult.ambiguous()
    if request.expected_version != proof.generation:
        return OwnerExecutionResult(OperationStatus.CONFLICTED, warnings=("expected generation is stale",))
    try:
        if request.operation_id == ARCHIVE_OPERATION_ID:
            result = run_single_record_archive_operation(proof, config_root=config.config_root, channel=config.channel, vault_root=config.vault_root, request_id=request.request_id)
        else:
            result = run_single_record_restore_operation(proof, service_reader=config.restore_service, request_id=request.request_id)
    except OperationTargetRefused as exc:
        return OwnerExecutionResult(OperationStatus.REJECTED, warnings=(str(exc),))
    except ArchiveDegradedError:
        return OwnerExecutionResult.ambiguous()
    except Exception:
        return OwnerExecutionResult.ambiguous()
    return _map_owner_result(request, proof, result.transition)


def _source_target(request: OperationRequest) -> str | OwnerExecutionResult:
    if len(request.targets) != 1:
        return OwnerExecutionResult.failed("archival operation requires exactly one target")
    target = request.targets[0]
    try:
        artifact_class = ArtifactClass(str(target["artifact_class"]))
    except (KeyError, TypeError, ValueError):
        return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("archival artifact class is unavailable",))
    if artifact_class is ArtifactClass.HUMAN:
        return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("owner_decision_required:#5325",))
    if artifact_class in {ArtifactClass.DERIVED, ArtifactClass.RECEIPT}:
        return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("archival mutation is not owned for artifact class",))
    raw_ref = target.get("artifact_id")
    if not isinstance(raw_ref, str) or not raw_ref or "raw_ref" in target:
        return OwnerExecutionResult.failed("source target requires artifact_id as the sole opaque raw_ref")
    return raw_ref


def _map_owner_result(request: OperationRequest, proof: Any, transition: Any) -> OwnerExecutionResult:
    receipt = getattr(transition, "receipt", None)
    stage = getattr(transition, "stage", None)
    liveness = getattr(getattr(transition, "liveness", None), "state", None)
    if stage is TransitionStage.CONFLICT or liveness is LivenessState.CONFLICT:
        return OwnerExecutionResult(OperationStatus.CONFLICTED, warnings=("owner transition conflicted",))
    if stage is TransitionStage.REFUSED or liveness is LivenessState.REFUSED:
        return OwnerExecutionResult(OperationStatus.REJECTED, warnings=("owner transition refused",))
    expected_stage = TransitionStage.RETIRED if request.operation_id == ARCHIVE_OPERATION_ID else TransitionStage.RESTORED
    if stage is not expected_stage or receipt is None:
        return OwnerExecutionResult.ambiguous()
    try:
        if (
            receipt.generation.value != proof.generation
            or receipt.artifact.owner_native_id.token != proof.artifact_id
            or receipt.policy_profile.value != "raw_evidence"
            or receipt.stage is not stage
            or receipt.liveness.state is not liveness
            or not any(reference.opaque_id.token == proof.representation_id for reference in receipt.representation_refs)
        ):
            return OwnerExecutionResult(OperationStatus.CONFLICTED, warnings=("owner receipt binding mismatch",))
        projection = ArchivalOperationReceipt(
            artifact_ref=receipt.artifact.owner_native_id.token,
            receipt_ref=receipt.receipt_ref.token,
            generation=receipt.generation.value,
            artifact_class=ArtifactClass.SOURCE,
            policy=receipt.policy_profile,
            stage=receipt.stage,
            liveness=receipt.liveness.state,
        )
    except (AttributeError, TypeError, ValueError):
        return OwnerExecutionResult.ambiguous()
    return OwnerExecutionResult(OperationStatus.SUCCEEDED, archival_receipt=projection)


__all__ = ["ARCHIVE_OPERATION_ID", "RESTORE_OPERATION_ID", "ArchivalOperationServerConfig", "build_archival_operation_handlers"]
