"""Composition of the AUTOOPS-03 read owners that live in the API layer.

``app.operations`` may not import ``app.api`` (import-linter interaction
contract), so the Companion vault-browser, relation-index and artifact-note
owners are bound here and handed to the dormant ``ReadOperationAdapter``.  This
module installs no route; it only names the production read owners.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.api.routes.artifacts import _content_hash, _extract_title, _resolve_and_validate
from app.api.routes.companion import (
    _collect_relation_notes,
    _rank_related_notes,
    _resolve_human_uuid_scope,
    _select_vault_notes,
)
from app.instance.context_bound_read import ContextBoundReadRoot
from app.instance.vault_registry import VaultRegistryStore
from app.operations.contracts import OperationItemOutcome
from app.operations.read_operations import (
    LIST_OPERATION_ID,
    READ_OPERATION_ID,
    READ_OWNERS,
    RELATED_OPERATION_ID,
    SEARCH_OPERATION_ID,
    ReadOperationAdapter,
    ReadOwner,
    ReadResult,
    bounded_limit,
    read_item,
    search_read_owner,
    source_freshness,
    target_identity,
)
from app.services.companion_note import is_companion_path


def build_read_operation_handlers() -> dict[str, ReadOwner]:
    """The production read owners admitted by AUTOOPS-03."""
    return {
        LIST_OPERATION_ID: _list_owner,
        READ_OPERATION_ID: _read_owner,
        SEARCH_OPERATION_ID: search_read_owner,
        RELATED_OPERATION_ID: _related_owner,
    }


def build_read_operation_adapter(registry_store: VaultRegistryStore) -> ReadOperationAdapter:
    """Explicit direct composition; never a runtime singleton."""
    return ReadOperationAdapter(registry_store=registry_store, owners=build_read_operation_handlers())


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
    limit = bounded_limit(request, 250, 1000)
    query = request.arguments.get("query", "")
    if limit is None or not isinstance(query, str):
        return ReadResult("invalid_arguments", warning="limit must be 1..1000 and query a string")
    items: list[OperationItemOutcome] = []
    unreadable = 0
    freshness = source_freshness(context)
    for root in roots:
        notes, _total, _filtered, _next, _prev, failed = _select_vault_notes(
            root.root, query=query, limit=limit
        )
        unreadable += failed
        for note in notes:
            # A companion retains its source UUID for continuity but never owns it.
            owns_identity = not is_companion_path(root.root / note.note_path, root.root)
            items.append(
                read_item(
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
    stable_id = target_identity(request)
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
    freshness = source_freshness(context)
    version = _content_hash(body)
    return ReadResult(
        "succeeded",
        (
            read_item(
                stable_id, locator, context, root.vault_binding_id,
                owner=READ_OWNERS[READ_OPERATION_ID], freshness=freshness, version=version,
                title=_extract_title(body, fallback=resolved.stem), body=body,
            ),
        ),
        freshness,
    )


def _related_owner(request, context, roots, registry_store) -> ReadResult:  # type: ignore[no-untyped-def]
    stable_id = target_identity(request)
    limit = bounded_limit(request, 10, 50)
    if stable_id is None or limit is None:
        return ReadResult("invalid_arguments", warning="one artifact_id target and limit 1..50 are required")
    located = _locate_identity(stable_id, roots)
    if isinstance(located, str):
        return ReadResult(located)
    freshness = source_freshness(context)
    items = tuple(
        read_item(
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


__all__ = ["build_read_operation_adapter", "build_read_operation_handlers"]
