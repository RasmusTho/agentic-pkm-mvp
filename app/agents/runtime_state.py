from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict


RUNTIME_STATE_CONTRACT_FIELDS = frozenset(
    {
        "trace_id",
        "authority",
        "authority_basis",
        "proposal_id",
        "receipt_event_id",
    }
)


class RuntimeStateContract(TypedDict, total=False):
    """Minimal runtime-state linkage shared by agent execution surfaces."""

    trace_id: str | None
    authority: dict[str, Any] | None
    authority_basis: str | None
    proposal_id: str | None
    receipt_event_id: str | None


class RuntimeStateModel(BaseModel):
    """Pydantic form of the shared runtime-state linkage contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str | None = None
    authority: dict[str, Any] | None = None
    authority_basis: str | None = None
    proposal_id: str | None = None
    receipt_event_id: str | None = None


def runtime_state_contract_fields(state_cls: type) -> set[str]:
    """Return declared runtime-state fields for TypedDict or Pydantic state classes."""

    model_fields = getattr(state_cls, "model_fields", None)
    if model_fields is not None:
        return set(model_fields)
    return set(getattr(state_cls, "__annotations__", {}))


def conforms_to_runtime_state_contract(state_cls: type) -> bool:
    return RUNTIME_STATE_CONTRACT_FIELDS.issubset(runtime_state_contract_fields(state_cls))


__all__ = [
    "RUNTIME_STATE_CONTRACT_FIELDS",
    "RuntimeStateContract",
    "RuntimeStateModel",
    "conforms_to_runtime_state_contract",
    "runtime_state_contract_fields",
]
