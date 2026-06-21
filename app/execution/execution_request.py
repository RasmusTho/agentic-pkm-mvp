"""Transitional adapter for `docs/contracts/EXECUTION_REQUEST.md`.

This module introduces the EXE side-effect request seam in a frozen, additive
shape. It does not decide policy and it does not perform side effects: it wraps
an already-authorized real-tool call so that GOV/OEF can see what was requested,
which DecisionToken (if any) authorized it, and how the result links back to a
trace/receipt.

The `DecisionToken` type is reused from `app.governance.governed_write` rather
than redefined, so EXE and GOV share one authorization vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from app.governance.governed_write import DecisionToken

CONTRACT_VERSION = "execution_request.v0"

ExecutionStatus = Literal["requested", "succeeded", "failed"]


@dataclass(frozen=True)
class ExecutionRequest:
    """Authorized request to perform one side effect via EXE.

    Mirrors the Inputs section of `docs/contracts/EXECUTION_REQUEST.md`. EXE knows
    how to execute; GOV decides whether execution is admissible. The DecisionToken
    reference is OPTIONAL while the orchestrator does not yet thread one through
    (see the contract's Transitional Implementation Notes).
    """

    side_effect: str
    actor: str
    resource: str
    adapter: str
    active_context_set: str | None = None
    decision_token: DecisionToken | None = None
    dry_run: bool = False
    preview: bool = False
    trace_id: str | None = None
    args: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class ExecutionResult:
    """Result of an EXE side-effect request.

    Mirrors the Outputs section of `docs/contracts/EXECUTION_REQUEST.md`. The
    result carries trace/receipt linkage so GOV/OEF can see what ran without
    inspecting EXE internals. `rollback_available` records rollback posture even
    when rollback is not implemented for this side-effect class.
    """

    request: ExecutionRequest
    status: ExecutionStatus
    preview_result: Mapping[str, Any] | None = None
    dry_run_result: Mapping[str, Any] | None = None
    effect_result: Mapping[str, Any] | None = None
    rollback_available: bool = False
    rollback_result: Mapping[str, Any] | None = None
    receipt_ref: str | None = None
    trace_id: str | None = None
    contract_version: str = CONTRACT_VERSION

    @property
    def decision_token(self) -> DecisionToken | None:
        """Authorization reference that governed this execution, if any."""
        return self.request.decision_token


__all__ = [
    "CONTRACT_VERSION",
    "DecisionToken",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
]
