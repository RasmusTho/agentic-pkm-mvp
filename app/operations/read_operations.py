"""Owner-native read adapters for ``ygg.operation.v1``.

The adapters deliberately translate only the operation envelope.  Discovery,
retrieval, artifact reads, and relation lookup remain owned by their existing
production seams; this module neither indexes nor reads a vault directly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import (
    CapabilityAvailability,
    CapabilityDiscovery,
    CapabilitySupport,
    OperationOutcome,
    OperationRequest,
    OperationStatus,
)


@dataclass(frozen=True)
class ReadOwnerResult:
    """The small normalized result returned by a named production read owner."""

    state: str
    items: tuple[Mapping[str, Any], ...] = ()
    warning: str | None = None


ReadOwner = Callable[[OperationRequest], ReadOwnerResult]
ContextResolver = Callable[[OperationRequest], bool]


def read_operation_handlers() -> dict[str, ReadOwner]:
    """Register only the production read owners admitted by AUTOOPS-03."""
    return {
        "artifact.list": _list_from_companion,
        "artifact.read": _read_from_artifacts,
        "artifact.search": _search_from_retrieval,
        "artifact.related": _related_from_companion,
    }


def read_capability_discovery() -> CapabilityDiscovery:
    return CapabilityDiscovery(
        tuple(
            CapabilityAvailability(operation_id, CapabilitySupport.SUPPORTED)
            for operation_id in (*read_operation_handlers(), "operation.discovery")
        )
    )


@dataclass(frozen=True)
class ReadOperationAdapters:
    """Surface-independent envelope adapter around explicit production owners."""

    owners: Mapping[str, ReadOwner]
    discovery: CapabilityDiscovery
    context_resolver: ContextResolver | None = None

    @classmethod
    def production(cls) -> "ReadOperationAdapters":
        return cls(read_operation_handlers(), read_capability_discovery())

    def invoke(self, request: OperationRequest) -> OperationOutcome:
        if request.operation_id == "operation.discovery":
            return _outcome(
                request,
                OperationStatus.SUCCEEDED,
                "succeeded",
                items=tuple(
                    _capability_item(capability) for capability in self.discovery.capabilities
                ),
            )
        context_resolver = self.context_resolver or _selected_vault_context_matches
        if not request.context.active_context_ref or not context_resolver(request):
            return _outcome(request, OperationStatus.REJECTED, "missing_context")
        owner = self.owners.get(request.operation_id)
        if owner is None:
            return _outcome(request, OperationStatus.NOT_SUPPORTED, "capability_unavailable")
        try:
            result = owner(request)
        except PermissionError:
            return _outcome(request, OperationStatus.REJECTED, "artifact_inaccessible")
        except _http_exception_type() as exc:
            return _http_exception_outcome(request, exc)
        except (ConnectionError, RuntimeError):
            return _outcome(request, OperationStatus.DEGRADED_READ, "owner_unavailable")
        return _normalize(request, result)


def _normalize(request: OperationRequest, result: ReadOwnerResult) -> OperationOutcome:
    statuses = {
        "succeeded": OperationStatus.SUCCEEDED,
        "missing_context": OperationStatus.REJECTED,
        "capability_unavailable": OperationStatus.NOT_SUPPORTED,
        "artifact_inaccessible": OperationStatus.REJECTED,
        "not_found": OperationStatus.NOT_FOUND,
        "owner_unavailable": OperationStatus.DEGRADED_READ,
    }
    return _outcome(
        request,
        statuses.get(result.state, OperationStatus.DEGRADED_READ),
        result.state,
        result.items,
        result.warning,
    )


def _outcome(
    request: OperationRequest,
    status: OperationStatus,
    state: str,
    items: tuple[Mapping[str, Any], ...] = (),
    warning: str | None = None,
) -> OperationOutcome:
    warnings = () if warning is None else (warning,)
    return OperationOutcome(
        request.request_id,
        status,
        request.operation_id,
        request.context,
        items=items,
        warnings=warnings,
        extensions={"read_state": state, "authority_class": "read_only"},
    )


def _capability_item(capability: CapabilityAvailability) -> dict[str, Any]:
    return {
        "stable_id": capability.operation_id,
        "operation_version": capability.operation_version,
        "support": capability.support.value,
        "reason": capability.reason,
        "authority_class": "read_only",
    }


def _selection_result(value: Any) -> ReadOwnerResult | None:
    if getattr(value, "state", None) == "vault_selection_required":
        return ReadOwnerResult(
            "missing_context", warning=str(getattr(value, "reason", "vault selection is required"))
        )
    return None


def _selected_vault_context_matches(request: OperationRequest) -> bool:
    """Bind ambient legacy read owners to the selected vault's stable ID.

    Those owners currently expose no immutable vault-generation token.  A
    generation-bearing operation therefore fails closed until an owner-native
    generation seam exists, rather than mislabelling a global-vault read.
    """
    from app.vault.manager import get_vault_manager

    manager = get_vault_manager()
    context = manager.context
    if context.status == "none":
        context = manager.load_last_active()
    return (
        request.context.vault_generation is None
        and context.status in {"selected", "uninitialized"}
        and bool(context.active_vault_id)
        and request.context.active_context_ref == context.active_vault_id
    )


def _http_exception_type() -> type[Exception]:
    from fastapi import HTTPException

    return HTTPException


def _http_exception_outcome(request: OperationRequest, exc: Exception) -> OperationOutcome:
    status_code = int(getattr(exc, "status_code", 503))
    detail = getattr(exc, "detail", {})
    error = detail.get("error") if isinstance(detail, Mapping) else None
    if status_code == 404:
        return _outcome(request, OperationStatus.NOT_FOUND, str(error or "not_found"))
    if status_code == 400:
        return _outcome(request, OperationStatus.INVALID, str(error or "invalid"))
    if status_code == 403:
        return _outcome(request, OperationStatus.REJECTED, "artifact_inaccessible")
    if status_code == 409:
        return _outcome(request, OperationStatus.CONFLICTED, str(error or "conflicted"))
    return _outcome(request, OperationStatus.DEGRADED_READ, str(error or "owner_unavailable"))


def _list_from_companion(request: OperationRequest) -> ReadOwnerResult:
    from app.api.routes.companion import read_companion_vault_browser

    response: Any = read_companion_vault_browser(
        q="",
        limit=int(request.arguments.get("limit", 250)),
        cursor=None,
        kind=[],
        zone=[],
        review_state=[],
        trust=[],
    )
    selection = _selection_result(response)
    if selection:
        return selection
    items = tuple(
        {
            "stable_id": note.uuid,
            "locator": note.note_path,
            "current_locator": note.note_path,
            "title": note.title,
            "vault_context": request.context.active_context_ref,
            "provenance": "companion.vault_browser",
            "freshness": {"state": "source_read"},
        }
        for note in response.notes
        if note.uuid
    )
    if len(items) != len(response.notes):
        return ReadOwnerResult(
            "owner_unavailable", items, "one or more listed artifacts lack stable identity"
        )
    return ReadOwnerResult("succeeded", items)


def _read_from_artifacts(request: OperationRequest) -> ReadOwnerResult:
    from app.api.routes.artifacts import read_artifact_note

    target = request.targets[0] if request.targets else request.arguments
    locator = str(target.get("locator") or target.get("note_path") or "")
    stable_id = str(target.get("artifact_id") or target.get("stable_id") or "")
    if not locator:
        return ReadOwnerResult("not_found", warning="artifact locator is required")
    if not stable_id:
        return ReadOwnerResult("not_found", warning="stable artifact identity is required")
    response = read_artifact_note(note_path=locator, artifact_id=stable_id or None)
    if hasattr(response, "status_code"):
        return ReadOwnerResult("missing_context", warning="vault selection is required")
    return ReadOwnerResult(
        "succeeded",
        (
            {
                "stable_id": response.artifact_id or stable_id,
                "locator": locator,
                "current_locator": locator,
                "title": response.title,
                "body": response.body,
                "version": response.content_hash,
                "vault_context": request.context.active_context_ref,
                "provenance": "artifacts.note",
                "freshness": "source_read",
            },
        ),
    )


def _search_from_retrieval(request: OperationRequest) -> ReadOwnerResult:
    from app.retrieval.capability import RetrievalRequest, retrieve

    query = str(request.arguments.get("query") or "")
    if not query:
        return ReadOwnerResult("not_found", warning="search query is required")
    response = retrieve(
        RetrievalRequest(
            query=query,
            k=int(request.arguments.get("limit", 10)),
            scope=request.context.active_context_ref,
        )
    )
    freshness = dict(response.metadata.get("temporal_validity") or {})
    items = tuple(
        {
            "stable_id": hit.doc_id,
            "locator": hit.source_ref,
            "current_locator": hit.source_ref,
            "title": str(hit.payload.get("title") or ""),
            "provenance": {
                "owner": "retrieval.capability",
                "source_ref": hit.source_ref,
                "metadata": dict(response.metadata.get("provenance") or {}),
            },
            "freshness": freshness
            or {"state": "unknown", "reason": "retrieval projection may lag"},
            "vault_context": request.context.active_context_ref,
        }
        for hit in response.hits
        if hit.doc_id
    )
    return ReadOwnerResult("succeeded", items)


def _related_from_companion(request: OperationRequest) -> ReadOwnerResult:
    from app.api.routes.companion import read_companion_vault_related

    target = request.targets[0] if request.targets else request.arguments
    response: Any = read_companion_vault_related(
        note_path=target.get("locator") or target.get("note_path"),
        artifact_uuid=target.get("artifact_id"),
        limit=int(request.arguments.get("limit", 10)),
    )
    selection = _selection_result(response)
    if selection:
        return selection
    items = tuple(
        {
            "stable_id": item.artifact_uuid or item.note_path,
            "locator": item.note_path,
            "current_locator": item.note_path,
            "title": item.title,
            "provenance": {
                "owner": "companion.vault_related",
                "signals": [signal.model_dump() for signal in item.ranking_signals],
            },
            "freshness": {"state": "source_read"},
            "vault_context": request.context.active_context_ref,
        }
        for item in response.results
    )
    return ReadOwnerResult("succeeded", items)
