"""Shared HTTP wire schemas; projections never grant operation authority."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.operations.contracts import OperationOutcome


class OperationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    artifact_class: str | None = None


class OperationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    active_context_ref: str = Field(min_length=1)
    vault_generation: str = Field(min_length=1)
    target_binding_id: str | None = None
    targets: list[OperationTarget] = Field(default_factory=list, max_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_version: str | int | None = None

    @field_validator("arguments")
    @classmethod
    def reject_authority(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"path", "vault_root", "root", "key", "reader", "service_reader", "policy", "policy_decision",
                     "decision_token", "receipt", "receipt_store", "delegation", "active_context", "target_binding_id"}

        def check(item: Any) -> None:
            if isinstance(item, dict):
                if forbidden.intersection(item):
                    raise ValueError("operation arguments cannot supply host authority")
                for child in item.values():
                    check(child)
            elif isinstance(item, list):
                for child in item:
                    check(child)

        check(value)
        return value


class BatchOperationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    artifact_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_version: str = Field(min_length=1, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)

    _arguments_guard = field_validator("arguments")(OperationCommand.reject_authority.__func__)


class BatchPreviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")
    operation_id: str = Field(min_length=1, max_length=128)
    active_context_ref: str = Field(min_length=1)
    vault_generation: str = Field(min_length=1)
    target_binding_id: str = Field(min_length=1)
    items: list[BatchOperationItem] = Field(min_length=1, max_length=100)
    limit: int = Field(default=100, ge=1, le=100, strict=True)
    partial_success_policy: str = "independent"


class BatchConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class OperationReceiptReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")


class BatchReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class DiscoveryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")


def operation_transport_schemas() -> dict[str, dict[str, Any]]:
    """Project existing route validators, without an independent schema registry."""
    preconditions = deepcopy(OperationCommand.model_json_schema())
    del preconditions["properties"]["expected_version"]
    return {
        "outcome": TypeAdapter(OperationOutcome).json_schema(),
        "command": OperationCommand.model_json_schema(),
        "preconditions": preconditions,
        "receipt": OperationReceiptReference.model_json_schema(),
        "discovery": DiscoveryCommand.model_json_schema(),
        "batch_preview": BatchPreviewCommand.model_json_schema(),
        "batch_reference": BatchReference.model_json_schema(),
    }
