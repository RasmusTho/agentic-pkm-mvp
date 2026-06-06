"""Read-only Context Bundle route (#1560, real emission wired in #1562).

Exposes the production surface for Context Bundles: a GET route that returns an
inspectable ``ContextBundle`` envelope. Without a ``query`` it returns the
self-describing construction envelope (#1560). With a ``query`` it emits a real
bundle from the production retrieval capability (#1562), keeping ranked
candidates distinct from the selected items. Read-only: no vault mutation,
authority flags surfaced verbatim, ``may_write`` never upgraded here.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.context_bundles.construction import build_inspectable_bundle
from app.context_bundles.runtime_registry import register_emitted_bundle
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


@router.get("/context-bundles/{bundle_id}", response_model=ContextBundle)
async def get_context_bundle(
    bundle_id: str,
    query: str | None = None,
    intended_use: list[str] | None = Query(default=None),
) -> ContextBundle:
    """Return an inspectable, read-only ``ContextBundle`` envelope.

    When ``query`` is supplied, the bundle is emitted from the real retrieval
    capability against the live vault/index and recorded in the process-local
    emitted-bundle registry; otherwise the typed-contract construction envelope
    is returned.
    """
    if query:
        result, _receipt = retrieve_and_emit_bundle(
            RetrievalRequest(query=query, trace_id=bundle_id),
            bundle_id=bundle_id,
        )
        bundle = _scope_emitted_bundle(result.bundle, intended_use)
        return register_emitted_bundle(bundle)
    return build_inspectable_bundle(bundle_id)


__all__ = ["router"]
