"""Operation-kernel adapters for owner-native governed archival providers."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import OperationRequest, OperationStatus
from .execution_kernel import OwnerExecutionResult

ArchiveProvider = Callable[[OperationRequest], Mapping[str, Any]]


@dataclass(frozen=True)
class ArchivalOperationAdapters:
    """Dispatch archive/restore by owner artifact class without owning policy."""

    providers: Mapping[str, ArchiveProvider]
    unsupported_classes: frozenset[str] = frozenset({"hka"})

    def handlers(self) -> dict[str, Callable[[OperationRequest], OwnerExecutionResult]]:
        return {"archive": self.execute, "restore": self.execute}

    def execute(self, request: OperationRequest) -> OwnerExecutionResult:
        if len(request.targets) != 1:
            return OwnerExecutionResult.failed("archival operation requires exactly one target")
        artifact_class = str(request.targets[0].get("artifact_class", ""))
        if artifact_class in self.unsupported_classes:
            return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("archival provider unavailable for artifact class",))
        provider = self.providers.get(artifact_class)
        if provider is None:
            return OwnerExecutionResult(OperationStatus.NOT_SUPPORTED, warnings=("archival provider unavailable for artifact class",))
        try:
            outcome = dict(provider(request))
        except Exception:
            return OwnerExecutionResult.ambiguous()
        state = str(outcome.get("state", ""))
        if state in {"partial", "stale", "refused"}:
            return OwnerExecutionResult(OperationStatus.RECOVERY_REQUIRED, items=(outcome,), warnings=("owner recovery guidance required",))
        # The provider owns all identity, generation, liveness, policy and
        # receipt fields. Preserve its mapping verbatim as the sole item.
        return OwnerExecutionResult.succeeded(items=(outcome,))


__all__ = ["ArchivalOperationAdapters", "ArchiveProvider"]
