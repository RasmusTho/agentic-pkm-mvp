"""Read-only Context Bundle route (#1560, real emission wired in #1562).

Exposes the production surface for Context Bundles: a GET route that returns an
inspectable ``ContextBundle`` envelope. Without a ``query`` it returns the
self-describing construction envelope (#1560). With a ``query`` it emits a real
bundle from the production retrieval capability (#1562), keeping ranked
candidates distinct from the selected items. Read-only: no vault mutation,
authority flags surfaced verbatim, ``may_write`` never upgraded here.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.request_active_context import current_scoped_route_read, scoped_route_read
from app.context_bundles.construction import build_inspectable_bundle
from app.context_bundles.runtime_registry import get_emitted_bundle, register_emitted_bundle
from app.context_bundles.schema import AuthorityFlags, ContextBundle
from app.retrieval.capability import RetrievalRequest
from app.retrieval.production_bundle import retrieve_and_emit_bundle

router = APIRouter()


def _scope_emitted_bundle(bundle: ContextBundle, intended_use: list[str] | None) -> ContextBundle:
    if not intended_use:
        return bundle
    uses = list(dict.fromkeys(intended_use))
    return bundle.model_copy(
        update={
            "intended_use": uses,
            "authority": AuthorityFlags(
                may_answer="answer" in uses,
                may_orient="orient" in uses,
                may_resurface="resurface" in uses,
                may_propose="propose" in uses or "propose_edit" in uses,
                may_write=False,
            ),
        },
        deep=True,
    )


def _bundle_not_found(bundle_id: str) -> HTTPException:
    # One answer for an unknown, foreign or unstamped id: existence is never revealed.
    return HTTPException(
        status_code=404,
        detail=f"context bundle {bundle_id!r} was not emitted for this active context",
    )


@router.get("/context-bundles/{bundle_id}", response_model=ContextBundle)
@scoped_route_read
def get_context_bundle(
    bundle_id: str,
    query: str | None = None,
    intended_use: list[str] | None = Query(default=None),
) -> ContextBundle:
    """Return an inspectable, read-only ``ContextBundle`` envelope.

    When ``query`` is supplied, the bundle is emitted from the real retrieval
    capability against the live vault/index and recorded in the process-local
    emitted-bundle registry; otherwise the typed-contract construction envelope
    is returned.

    A scoped read (MVR-05B4c5) retrieves only from the request's bindings and
    registers the bundle under the request binding; without ``query`` it reads
    the binding's own emitted bundle, and an unknown, foreign or unstamped id is
    the same not-found.
    """
    scoped = current_scoped_route_read()
    if scoped is not None and scoped.vault_binding_id is None:
        raise _bundle_not_found(bundle_id)
    if query:
        result, _receipt = retrieve_and_emit_bundle(
            RetrievalRequest(
                query=query,
                trace_id=bundle_id,
                active_context=scoped.context if scoped is not None else None,
            ),
            bundle_id=bundle_id,
        )
        bundle = _scope_emitted_bundle(result.bundle, intended_use)
        return register_emitted_bundle(
            bundle, vault_binding_id=scoped.vault_binding_id if scoped is not None else None
        )
    if scoped is not None:
        emitted = get_emitted_bundle(bundle_id, vault_binding_id=scoped.vault_binding_id)
        if emitted is None:
            raise _bundle_not_found(bundle_id)
        return emitted
    return build_inspectable_bundle(bundle_id)


__all__ = ["router"]
