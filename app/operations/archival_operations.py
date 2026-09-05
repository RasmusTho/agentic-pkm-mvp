"""Operation-kernel adapters for governed archival owners.

No generic provider registry is admitted here. The only mutable effects this
adapter composes are existing Heimdal raw-evidence calls, fed with a concrete
server-resolved invocation rather than a client-selected path or authority.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.archival.contracts import ArtifactClass, PolicyProfile

from .contracts import OperationRequest, OperationStatus
from .execution_kernel import OwnerExecutionResult


@dataclass(frozen=True)
class SourceArchiveInvocation:
    record: Any
    archive_root: Path
    archive_ref: str
    volume_ready: Callable[[], Any]


@dataclass(frozen=True)
class SourceRestoreInvocation:
    raw_ref: str
    reader: str
    artifact_id: str
    generation: str
    liveness: str
    policy: PolicyProfile = PolicyProfile.RAW_EVIDENCE
    key: bytes | None = None


class SourceInvocationResolver(Protocol):
    """Server composition resolves opaque identity to concrete owner inputs."""

    def __call__(self, request: OperationRequest) -> SourceArchiveInvocation | SourceRestoreInvocation: ...


@dataclass(frozen=True)
class ArchivalOperationAdapters:
    """Compose archive/restore to the existing class-native owner calls."""

    resolve_source_invocation: SourceInvocationResolver

    @classmethod
    def production(cls, resolve_source_invocation: SourceInvocationResolver) -> "ArchivalOperationAdapters":
        return cls(resolve_source_invocation)

    def handlers(self) -> dict[str, Callable[[OperationRequest], OwnerExecutionResult]]:
        return {"archive": self.execute, "restore": self.execute}

    def execute(self, request: OperationRequest) -> OwnerExecutionResult:
        if len(request.targets) != 1:
            return OwnerExecutionResult.failed("archival operation requires exactly one target")
        artifact_class = _artifact_class(request.targets[0])
        if artifact_class is None:
            return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("archival artifact class is unavailable",))
        if artifact_class is ArtifactClass.HUMAN:
            return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("owner_decision_required:#5325",))
        if artifact_class in {ArtifactClass.DERIVED, ArtifactClass.RECEIPT}:
            return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("archival mutation is not owned for artifact class",))
        try:
            invocation = self.resolve_source_invocation(request)
            if request.operation_id == "archive" and isinstance(invocation, SourceArchiveInvocation):
                return _archive_source(invocation)
            if request.operation_id == "restore" and isinstance(invocation, SourceRestoreInvocation):
                return _restore_source(invocation)
        except Exception:
            return OwnerExecutionResult.ambiguous()
        return OwnerExecutionResult.failed("server-resolved archival invocation does not match operation")


def _artifact_class(target: Mapping[str, Any]) -> ArtifactClass | None:
    try:
        return ArtifactClass(str(target["artifact_class"]))
    except (KeyError, TypeError, ValueError):
        return None


def _archive_source(invocation: SourceArchiveInvocation) -> OwnerExecutionResult:
    from app.heimdal.local_archive import relocate_raw_record

    result = relocate_raw_record(invocation.record, archive_root=invocation.archive_root, archive_ref=invocation.archive_ref, volume_ready=invocation.volume_ready)
    receipt = result.receipt
    return _complete(receipt.record_id, str(receipt.raw_generation), "retired", PolicyProfile.RAW_EVIDENCE, receipt.receipt_id)


def _restore_source(invocation: SourceRestoreInvocation) -> OwnerExecutionResult:
    from app.heimdal.local_archive import run_restore_drill

    receipt = run_restore_drill(invocation.raw_ref, reader=invocation.reader, key=invocation.key)
    return _complete(invocation.artifact_id, invocation.generation, invocation.liveness, invocation.policy, receipt.read_receipt_id)


def _complete(artifact_id: str, generation: str, liveness: str, policy: PolicyProfile, receipt_ref: str) -> OwnerExecutionResult:
    bindings = {"artifact_id": artifact_id, "generation": generation, "liveness": liveness, "policy": policy.value, "receipt_ref": receipt_ref}
    return OwnerExecutionResult(OperationStatus.SUCCEEDED, items=(bindings,), receipt_bindings=bindings)


__all__ = ["ArchivalOperationAdapters", "SourceArchiveInvocation", "SourceInvocationResolver", "SourceRestoreInvocation"]
