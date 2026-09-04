from __future__ import annotations

from pathlib import Path
from fastapi import HTTPException

from app.operations import OperationContext, OperationRequest, OperationStatus
from app.operations.read_operations import (
    ReadOperationAdapters,
    ReadOwnerResult,
    read_capability_discovery,
)


def _request(operation_id: str, **kwargs):
    return OperationRequest(
        operation_id, "request-1", OperationContext("vault-a", "generation-1"), **kwargs
    )


def test_read_operations_delegate_to_canonical_production_services() -> None:
    calls: list[str] = []

    def owner(name: str):
        def invoke(_request, _vault_root):
            calls.append(name)
            return ReadOwnerResult("succeeded")

        return invoke

    adapters = ReadOperationAdapters(
        {
            operation: owner(operation)
            for operation in (
                "artifact.list",
                "artifact.read",
                "artifact.search",
                "artifact.related",
            )
        },
        read_capability_discovery(),
        context_resolver=lambda request: Path("."),
    )
    for operation in ("artifact.list", "artifact.read", "artifact.search", "artifact.related"):
        assert adapters.invoke(_request(operation)).status is OperationStatus.SUCCEEDED
    assert calls == ["artifact.list", "artifact.read", "artifact.search", "artifact.related"]
    assert adapters.invoke(_request("operation.discovery")).status is OperationStatus.SUCCEEDED


def test_read_results_preserve_identity_context_provenance_and_freshness() -> None:
    item = {
        "stable_id": "artifact-1",
        "locator": "notes/a.md",
        "current_locator": "notes/a.md",
        "vault_context": "vault-a",
        "provenance": {"owner": "retrieval.capability"},
        "freshness": {"state": "stale"},
    }
    adapters = ReadOperationAdapters(
        {"artifact.search": lambda request, vault_root: ReadOwnerResult("succeeded", (item,))},
        read_capability_discovery(),
        context_resolver=lambda request: Path("."),
    )
    outcome = adapters.invoke(_request("artifact.search"))
    assert outcome.status is OperationStatus.SUCCEEDED
    assert outcome.items == (item,)
    assert outcome.extensions["authority_class"] == "read_only"


def test_read_failures_are_typed_and_never_ambiguous_empty_success() -> None:
    adapters = ReadOperationAdapters(
        {"artifact.search": lambda request, vault_root: ReadOwnerResult("owner_unavailable")},
        read_capability_discovery(),
        context_resolver=lambda request: Path("."),
    )
    missing = adapters.invoke(
        OperationRequest("artifact.search", "request-2", OperationContext(""))
    )
    unavailable = adapters.invoke(_request("unknown.read"))
    inaccessible = ReadOperationAdapters(
        {"artifact.read": lambda request, vault_root: ReadOwnerResult("artifact_inaccessible")},
        read_capability_discovery(),
        context_resolver=lambda request: Path("."),
    ).invoke(_request("artifact.read"))
    degraded = adapters.invoke(_request("artifact.search"))
    assert (missing.status, missing.extensions["read_state"]) == (
        OperationStatus.REJECTED,
        "missing_context",
    )
    assert (unavailable.status, unavailable.extensions["read_state"]) == (
        OperationStatus.NOT_SUPPORTED,
        "capability_unavailable",
    )
    assert (inaccessible.status, inaccessible.extensions["read_state"]) == (
        OperationStatus.REJECTED,
        "artifact_inaccessible",
    )
    assert (degraded.status, degraded.extensions["read_state"]) == (
        OperationStatus.DEGRADED_READ,
        "owner_unavailable",
    )
    assert all(
        outcome.status is not OperationStatus.SUCCEEDED
        for outcome in (missing, unavailable, inaccessible, degraded)
    )


def test_read_adapter_rejects_stale_context_and_translates_owner_http_errors() -> None:
    stale = ReadOperationAdapters(
        {"artifact.read": lambda request, vault_root: ReadOwnerResult("succeeded")},
        read_capability_discovery(),
        context_resolver=lambda request: None,
    ).invoke(_request("artifact.read"))
    missing = ReadOperationAdapters(
        {
            "artifact.read": lambda request, vault_root: (_ for _ in ()).throw(
                HTTPException(status_code=404, detail={"error": "note_not_found"})
            )
        },
        read_capability_discovery(),
        context_resolver=lambda request: Path("."),
    ).invoke(_request("artifact.read"))
    assert (stale.status, stale.extensions["read_state"]) == (
        OperationStatus.REJECTED,
        "missing_context",
    )
    assert (missing.status, missing.extensions["read_state"]) == (
        OperationStatus.NOT_FOUND,
        "note_not_found",
    )
