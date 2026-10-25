"""Dormant read-only handlers for ``ygg.operation.v1`` discovery (AUTOOPS-03).

The adapter only translates the operation envelope.  Vault context is resolved
exclusively through ``ActiveContextSelectionService.resolve_request_context``
and filesystem roots exclusively through ``context_bound_read_window``; listing,
reading, relation ranking, and retrieval remain owned by their existing
production seams.  This module installs no route, GUI, MCP tool, or singleton.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.governance.binding_authority import BindingAuthorizationError
from app.instance.active_context_service import (
    ACTION_SELECTION_INSPECT,
    PERMISSION_SELECTION_READ,
    WRITE_CLASS_READ,
    ActiveContextSelectionService,
    DerivedContext,
)
from app.instance.context_bound_read import (
    ContextBoundReadError,
    ContextBoundReadRoot,
    context_bound_read_window,
)
from app.instance.vault_registry import VaultRegistryStore
from app.vault.active_context_v1 import ActiveContextSetV1

from .contracts import (
    CapabilityAvailability,
    CapabilityDiscovery,
    CapabilitySupport,
    OperationItemOutcome,
    OperationOutcome,
    OperationRequest,
    OperationStatus,
)

LIST_OPERATION_ID = "artifact.list"
READ_OPERATION_ID = "artifact.read"
SEARCH_OPERATION_ID = "artifact.search"
RELATED_OPERATION_ID = "artifact.related"
DISCOVERY_OPERATION_ID = "operation.discovery"

#: Named production read owner for each operation (recorded on every outcome).
READ_OWNERS: Mapping[str, str] = {
    LIST_OPERATION_ID: "companion.vault_browser",
    READ_OPERATION_ID: "artifacts.note",
    SEARCH_OPERATION_ID: "retrieval.capability",
    RELATED_OPERATION_ID: "companion.vault_related",
}

#: Typed read states.  Each maps to exactly one envelope status, so a failure is
#: never reported as an empty success.
_STATUS_BY_STATE: Mapping[str, OperationStatus] = {
    "succeeded": OperationStatus.SUCCEEDED,
    "partial": OperationStatus.DEGRADED_READ,
    "missing_context": OperationStatus.INVALID,
    "invalid_arguments": OperationStatus.INVALID,
    "context_unavailable": OperationStatus.REJECTED,
    "context_denied": OperationStatus.REJECTED,
    "stale_context": OperationStatus.CONFLICTED,
    "identity_conflict": OperationStatus.CONFLICTED,
    "index_unavailable": OperationStatus.DEGRADED_READ,
    "artifact_inaccessible": OperationStatus.REJECTED,
    "artifact_not_found": OperationStatus.NOT_FOUND,
    "capability_unavailable": OperationStatus.NOT_SUPPORTED,
    "owner_unavailable": OperationStatus.DEGRADED_READ,
}


@dataclass(frozen=True)
class RequestContextCarrier:
    """Transport-supplied selection bearer plus the server-derived identity.

    The carrier is not vault authority: it is handed unchanged to the
    owner-native ``resolve_request_context`` seam, which alone decides the
    immutable selected-vault generation.
    """

    service: ActiveContextSelectionService
    derived: DerivedContext
    session_bearer: str | None
    override_bearer: str | None = None

    def resolve(self) -> ActiveContextSetV1:
        return self.service.resolve_request_context(
            derived=self.derived,
            session_bearer=self.session_bearer,
            override_bearer=self.override_bearer,
            action=ACTION_SELECTION_INSPECT,
            write_class=WRITE_CLASS_READ,
            required_permission=PERMISSION_SELECTION_READ,
        ).snapshot


@dataclass(frozen=True)
class ReadResult:
    """Normalized result of one production read owner."""

    state: str
    items: tuple[OperationItemOutcome, ...] = ()
    freshness: Mapping[str, Any] = field(default_factory=dict)
    warning: str | None = None


ReadOwner = Callable[
    [OperationRequest, ActiveContextSetV1, tuple[ContextBoundReadRoot, ...], VaultRegistryStore],
    ReadResult,
]


def read_capability_discovery() -> CapabilityDiscovery:
    return CapabilityDiscovery(
        tuple(
            CapabilityAvailability(
                operation_id, CapabilitySupport.SUPPORTED, extensions={"authority_class": "read_only"}
            )
            for operation_id in (*READ_OWNERS, DISCOVERY_OPERATION_ID)
        )
    )


def build_read_operation_handlers() -> dict[str, ReadOwner]:
    """The production read owners admitted by AUTOOPS-03."""
    return {
        LIST_OPERATION_ID: _list_owner,
        READ_OPERATION_ID: _read_owner,
        SEARCH_OPERATION_ID: _search_owner,
        RELATED_OPERATION_ID: _related_owner,
    }


@dataclass(frozen=True)
class ReadOperationAdapter:
    """Explicit direct-composition entrypoint; never a runtime singleton."""

    registry_store: VaultRegistryStore
    owners: Mapping[str, ReadOwner] = field(default_factory=build_read_operation_handlers)
    discovery: CapabilityDiscovery = field(default_factory=read_capability_discovery)

    def invoke(
        self, request: OperationRequest, carrier: RequestContextCarrier | None
    ) -> OperationOutcome:
        if request.operation_version != "ygg.operation.v1":
            return _outcome(request, "capability_unavailable", warning="unsupported operation version")
        if request.operation_id == DISCOVERY_OPERATION_ID:
            return _outcome(
                request,
                "succeeded",
                items=tuple(_capability_item(item) for item in self.discovery.capabilities),
            )
        owner = self.owners.get(request.operation_id)
        if owner is None:
            return _outcome(request, "capability_unavailable")
        if (
            not request.context.active_context_ref
            or request.context.vault_generation is None
            or carrier is None
            or (carrier.session_bearer is None and carrier.override_bearer is None)
        ):
            return _outcome(
                request,
                "missing_context",
                warning="explicit active context and selected-vault generation are required",
            )
        try:
            context = carrier.resolve()
        except BindingAuthorizationError:
            return _outcome(request, "context_denied")
        except Exception:
            # Reselection-required, principal mismatch, expired or unknown
            # selections, and an unavailable registry all fail closed alike.
            return _outcome(request, "context_unavailable")
        if (
            context.context_id != request.context.active_context_ref
            or str(context.generation) != str(request.context.vault_generation)
        ):
            return _outcome(request, "stale_context", context=context)
        try:
            # The window revalidates registry/binding truth under shared leases
            # and is held until the owner has produced its complete result.
            with context_bound_read_window(context, registry_store=self.registry_store) as roots:
                result = owner(request, context, roots, self.registry_store)
        except ContextBoundReadError:
            return _outcome(request, "context_unavailable", context=context)
        except Exception as exc:
            return _outcome(request, _owner_failure_state(exc), context=context)
        return _outcome(
            request,
            result.state,
            items=result.items,
            context=context,
            freshness=result.freshness,
            warning=result.warning,
        )


def _outcome(
    request: OperationRequest,
    state: str,
    *,
    items: tuple[OperationItemOutcome, ...] = (),
    context: ActiveContextSetV1 | None = None,
    freshness: Mapping[str, Any] | None = None,
    warning: str | None = None,
) -> OperationOutcome:
    extensions: dict[str, Any] = {
        "read_state": state,
        "authority_class": "read_only",
        "read_owner": READ_OWNERS.get(request.operation_id),
    }
    if context is not None:
        extensions["resolved_context"] = {
            "context_id": context.context_id,
            "generation": context.generation,
            "binding_ids": list(context.binding_ids),
        }
    if freshness:
        extensions["freshness"] = dict(freshness)
    return OperationOutcome(
        request.request_id,
        _STATUS_BY_STATE.get(state, OperationStatus.DEGRADED_READ),
        request.operation_id,
        request.context,
        provenance=request.provenance,
        items=items,
        warnings=() if warning is None else (warning,),
        extensions=extensions,
    )


def _owner_failure_state(exc: Exception) -> str:
    """Translate an owner's transport-shaped refusal without inventing success."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return "artifact_not_found"
    if status_code in {400, 422}:
        return "invalid_arguments"
    if status_code == 403 or isinstance(exc, PermissionError):
        return "artifact_inaccessible"
    if status_code == 409:
        return "identity_conflict"
    return "owner_unavailable"


def _capability_item(capability: CapabilityAvailability) -> OperationItemOutcome:
    return OperationItemOutcome(
        resource_id=capability.operation_id,
        status=OperationStatus.SUCCEEDED,
        payload={
            "operation_version": capability.operation_version,
            "support": capability.support.value,
            "reason": capability.reason,
            "read_owner": READ_OWNERS.get(capability.operation_id),
            **dict(capability.extensions),
        },
    )


def _item(
    stable_id: str | None,
    locator: str | None,
    context: ActiveContextSetV1,
    binding_id: str | None,
    *,
    owner: str,
    freshness: Mapping[str, Any],
    version: str | None = None,
    **fields: Any,
) -> OperationItemOutcome:
    vault_ids = {binding.vault_binding_id: binding.vault_id for binding in context.source_bindings}
    return OperationItemOutcome(
        resource_id=stable_id,
        status=OperationStatus.SUCCEEDED,
        resulting_version=version,
        payload={
            "stable_id": stable_id,
            "identity_state": "stable" if stable_id else "unavailable",
            "current_locator": locator,
            "vault_context": {
                "context_id": context.context_id,
                "context_generation": context.generation,
                "vault_binding_id": binding_id,
                "vault_id": vault_ids.get(binding_id) if binding_id else None,
            },
            "provenance": {"owner": owner, **dict(fields.pop("provenance", {}))},
            "freshness": dict(freshness),
            **fields,
        },
    )


def _source_freshness(context: ActiveContextSetV1) -> dict[str, Any]:
    return {"state": "source_read", "context_generation": context.generation}


def _target_identity(request: OperationRequest) -> str | None:
    target = request.targets[0] if len(request.targets) == 1 else {}
    value = target.get("artifact_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _limit(request: OperationRequest, default: int, maximum: int) -> int | None:
    value = request.arguments.get("limit", default)
    if type(value) is not int or not 1 <= value <= maximum:
        return None
    return value


@dataclass(frozen=True)
class _LocatedArtifact:
    root: ContextBoundReadRoot
    note: Mapping[str, object]
    notes: list[dict[str, object]]


def _locate_identity(
    stable_id: str, roots: tuple[ContextBoundReadRoot, ...]
) -> _LocatedArtifact | str:
    """Resolve a stable identity to exactly one owner-enumerated note.

    The Companion relation index owns the identity -> current-locator mapping
    (companion files never own a UUID; nested child vaults are pruned).  A
    locator is never accepted as identity.
    """
    from app.api.routes.companion import _collect_relation_notes, _resolve_human_uuid_scope

    found: list[_LocatedArtifact] = []
    for root in roots:
        notes = _collect_relation_notes(root.root)
        if any(note.get("artifact_uuid") == stable_id for note in notes):
            note = _resolve_human_uuid_scope(notes, artifact_uuid=stable_id)
            found.append(_LocatedArtifact(root, note, notes))
    if not found:
        return "artifact_not_found"
    if len(found) > 1:
        return "identity_conflict"
    return found[0]


def _list_owner(request, context, roots, registry_store) -> ReadResult:  # type: ignore[no-untyped-def]
    from app.api.routes.companion import _select_vault_notes
    from app.services.companion_note import is_companion_path

    limit = _limit(request, 250, 1000)
    query = request.arguments.get("query", "")
    if limit is None or not isinstance(query, str):
        return ReadResult("invalid_arguments", warning="limit must be 1..1000 and query a string")
    items: list[OperationItemOutcome] = []
    unreadable = 0
    freshness = _source_freshness(context)
    for root in roots:
        notes, _total, _filtered, _next, _prev, failed = _select_vault_notes(
            root.root, query=query, limit=limit
        )
        unreadable += failed
        for note in notes:
            # A companion retains its source UUID for continuity but never owns it.
            owns_identity = not is_companion_path(root.root / note.note_path, root.root)
            items.append(
                _item(
                    note.uuid if owns_identity else None, note.note_path, context, root.vault_binding_id,
                    owner=READ_OWNERS[LIST_OPERATION_ID], freshness=freshness,
                    title=note.title, kind=note.kind,
                )
            )
    if unreadable:
        return ReadResult(
            "partial", tuple(items[:limit]), freshness, f"{unreadable} note(s) could not be read"
        )
    return ReadResult("succeeded", tuple(items[:limit]), freshness)


def _read_owner(request, context, roots, registry_store) -> ReadResult:  # type: ignore[no-untyped-def]
    from app.api.routes.artifacts import _content_hash, _extract_title, _resolve_and_validate

    stable_id = _target_identity(request)
    if stable_id is None:
        return ReadResult("invalid_arguments", warning="exactly one target with artifact_id is required")
    located = _locate_identity(stable_id, roots)
    if isinstance(located, str):
        return ReadResult(located)
    root = located.root
    locator = str(located.note["note_path"])
    try:
        resolved = _resolve_and_validate(locator, root.root)
        body = resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ReadResult("artifact_not_found")
    except (OSError, UnicodeDecodeError):
        return ReadResult("artifact_inaccessible")
    freshness = _source_freshness(context)
    version = _content_hash(body)
    return ReadResult(
        "succeeded",
        (
            _item(
                stable_id, locator, context, root.vault_binding_id,
                owner=READ_OWNERS[READ_OPERATION_ID], freshness=freshness, version=version,
                title=_extract_title(body, fallback=resolved.stem), body=body,
            ),
        ),
        freshness,
    )


def _related_owner(request, context, roots, registry_store) -> ReadResult:  # type: ignore[no-untyped-def]
    from app.api.routes.companion import _rank_related_notes

    stable_id = _target_identity(request)
    limit = _limit(request, 10, 50)
    if stable_id is None or limit is None:
        return ReadResult("invalid_arguments", warning="one artifact_id target and limit 1..50 are required")
    located = _locate_identity(stable_id, roots)
    if isinstance(located, str):
        return ReadResult(located)
    freshness = _source_freshness(context)
    items = tuple(
        _item(
            result.artifact_uuid, result.note_path, context, located.root.vault_binding_id,
            owner=READ_OWNERS[RELATED_OPERATION_ID], freshness=freshness, title=result.title,
            provenance={
                "ranking_score": result.ranking_score,
                "signals": [signal.model_dump() for signal in result.ranking_signals],
            },
        )
        for result in _rank_related_notes(dict(located.note), located.notes, limit=limit)
    )
    return ReadResult("succeeded", items, freshness)


def _search_owner(request, context, roots, registry_store) -> ReadResult:  # type: ignore[no-untyped-def]
    from app.instance.context_settings import IncompatibleBindingSettingsError, resolve_context_settings
    from app.retrieval.capability import RetrievalRequest, retrieve
    from app.retrieval.hybrid import get_store

    query = request.arguments.get("query")
    limit = _limit(request, 10, 50)
    if not isinstance(query, str) or not query.strip() or limit is None:
        return ReadResult("invalid_arguments", warning="a non-empty query and limit 1..50 are required")
    try:
        settings = resolve_context_settings(context, registry_store=registry_store)
    except IncompatibleBindingSettingsError:
        return ReadResult("context_unavailable", warning="incompatible_binding_settings")
    try:
        response = retrieve(
            RetrievalRequest(
                query=query,
                k=limit,
                trace_id=request.request_id,
                scope=context.scope,
                active_context=context,
                settings_bundle_digest=settings.cache_bundle_digest,
                retrieval_tuning=settings.retrieval_tuning,
            )
        )
        indexed_total = len(get_store().all())
    except Exception:
        return ReadResult("index_unavailable", warning="retrieval index is unavailable")
    provenance = response.metadata.get("provenance", {})
    rejected = provenance.get("active_context", {}).get("rejected_unbound_hits", 0)
    freshness = {
        **dict(response.metadata.get("temporal_validity", {})),
        "source": "retrieval.durable_index",
        "context_generation": context.generation,
        "indexed_documents_for_context": max(indexed_total - int(rejected), 0),
    }
    if freshness["indexed_documents_for_context"] == 0:
        # An empty index for the selected bindings cannot answer "no matches".
        return ReadResult("index_unavailable", (), freshness, "no indexed documents for the selected bindings")
    items = tuple(
        _item(
            hit.doc_id, _hit_locator(hit), context, hit.payload.get("vault_binding_id"),
            owner=READ_OWNERS[SEARCH_OPERATION_ID], freshness=freshness,
            title=str(hit.payload.get("title") or ""), snippet=hit.snippet,
            provenance={"score": hit.score, "adapter": provenance.get("adapter")},
        )
        for hit in response.hits
        if hit.doc_id
    )
    return ReadResult("succeeded", items, freshness)


def _hit_locator(hit: Any) -> str | None:
    for key in ("note_path", "path", "source_note_path"):
        value = hit.payload.get(key)
        if isinstance(value, str) and value and not value.startswith("/"):
            return value
    return None


__all__ = [
    "DISCOVERY_OPERATION_ID",
    "LIST_OPERATION_ID",
    "READ_OPERATION_ID",
    "READ_OWNERS",
    "RELATED_OPERATION_ID",
    "SEARCH_OPERATION_ID",
    "ReadOperationAdapter",
    "ReadResult",
    "RequestContextCarrier",
    "build_read_operation_handlers",
    "read_capability_discovery",
]
