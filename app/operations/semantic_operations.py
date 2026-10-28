"""Dormant AUTOOPS-06 adapters; HKA owns semantic validation and source effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.knowledge.semantic import KnowledgeSemanticOwner, SEMANTIC_OPERATIONS
from .contracts import (
    ConvergenceState,
    OperationContext,
    OperationConvergence,
    OperationRequest,
    OperationStatus,
    SourceEffectStatus,
)
from .execution_kernel import OwnerExecutionResult


@dataclass(frozen=True)
class SemanticOperationServerConfig:
    owner: KnowledgeSemanticOwner
    context: OperationContext


def build_semantic_operation_handlers(
    config: SemanticOperationServerConfig,
) -> dict[str, Callable[[OperationRequest], OwnerExecutionResult]]:
    return {
        operation: lambda request: _execute(request, config) for operation in SEMANTIC_OPERATIONS
    }


def _execute(
    request: OperationRequest, config: SemanticOperationServerConfig, *, recover: bool = False
) -> OwnerExecutionResult:
    def refuse(status: OperationStatus, reason: str) -> OwnerExecutionResult:
        return OwnerExecutionResult(status, warnings=(reason,))

    if (
        request.operation_version != "ygg.operation.v1"
        or request.mode != "execute"
        or request.operation_id not in SEMANTIC_OPERATIONS
    ):
        return refuse(OperationStatus.NOT_SUPPORTED, "semantics supports only v1 execute")
    if request.context != config.context or (
        config.context.active_context_ref,
        config.context.vault_generation,
    ) != (config.owner.active_context.context_id, str(config.owner.active_context.generation)):
        return refuse(OperationStatus.REJECTED, "semantic context differs from the server binding")
    if request.provenance is not None and request.provenance.actor != config.owner.actor:
        return refuse(OperationStatus.REJECTED, "semantic actor differs from the server principal")
    if (
        len(request.targets) != 1
        or set(request.targets[0]) != {"artifact_id"}
        or not isinstance(request.targets[0]["artifact_id"], str)
    ):
        return refuse(OperationStatus.INVALID, "one stable artifact or container UUID is required")
    if not isinstance(request.expected_version, str) or not request.expected_version:
        return refuse(OperationStatus.CONFLICTED, "expected raw-byte source version is required")
    result = (config.owner.reconcile if recover else config.owner.apply)(
        request_id=request.request_id,
        operation=request.operation_id,
        artifact_id=request.targets[0]["artifact_id"],
        expected_version=request.expected_version,
        arguments=request.arguments,
        admission_deadline=None if request.delegation is None else request.delegation.get("expires_at"),
    )
    source = SourceEffectStatus(result.source_effect)
    projection = (
        ConvergenceState.CONVERGED
        if result.status == "succeeded"
        else ConvergenceState.REBUILD_REQUIRED
        if source is not SourceEffectStatus.NOT_APPLIED
        else ConvergenceState.NOT_REQUIRED
    )
    return OwnerExecutionResult(
        OperationStatus(result.status),
        effect_id=request.request_id if result.receipt else None,
        effect_receipt={"receipt_id": result.receipt.get("receipt_id"), "write": result.receipt}
        if result.receipt
        else None,
        items=(
            {
                "artifact_id": request.targets[0]["artifact_id"],
                "status": result.status,
                "version": request.expected_version,
                "result_version": result.receipt.get("resulting_version")
                if result.receipt
                else None,
            },
        ),
        convergence=OperationConvergence(
            source, store=projection, index=projection, link=projection
        ),
        warnings=(result.reason,) if result.reason else (),
    )


def reconcile_semantic_operation(
    request: OperationRequest, config: SemanticOperationServerConfig,
) -> OwnerExecutionResult:
    """Read/verify-first recovery through the existing semantic receipt owner."""
    return _execute(request, config, recover=True)
