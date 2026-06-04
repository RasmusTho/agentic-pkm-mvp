"""Emit a ``ContextBundle`` from the real retrieval capability (#1562).

The typed-contract emitter ``emit_retrieval_bundle`` exists but was never called
in production. This module wires it into the real retrieval capability
(``app.retrieval.capability``) so production retrieval produces an inspectable
bundle against the live vault/index and records a runtime creation receipt.

Boundaries preserved:
- ranked candidates (what matched) stay distinct from the selected included
  items (what was chosen for human-facing output),
- ``may_write`` stays false — retrieval output never authorizes writeback,
- no direct DB access here; retrieval goes through the capability/ports layer,
- no persistence or promotion — the creation receipt is in-memory trace only
  (durable projection lands in #1565).
"""
from __future__ import annotations

from app.context_bundles.schema import BundleScope, ExcludedItem
from app.receipts.bundle_receipts import BundleReceipt, record_creation_receipt
from app.retrieval.bundle_emission import RetrievalBundleResult, emit_retrieval_bundle
from app.retrieval.capability import RetrievalRequest, RetrievalResponse, retrieve


def emit_bundle_from_response(
    response: RetrievalResponse,
    *,
    selected_ids: list[str] | None = None,
    excluded: list[ExcludedItem] | None = None,
    scope: BundleScope | None = None,
    bundle_id: str | None = None,
) -> tuple[RetrievalBundleResult, BundleReceipt]:
    """Emit an inspectable bundle from a real ``RetrievalResponse``.

    ``selected_ids`` names the hits chosen for human-facing output; when omitted
    every ranked hit is selected. The full ranked set is preserved separately on
    ``RetrievalBundleResult.ranked_candidates`` so the candidates-vs-selected
    boundary stays visible. A creation receipt is recorded for audit.
    """
    selected = (
        selected_ids
        if selected_ids is not None
        else [hit.object_id for hit in response.hits]
    )
    result = emit_retrieval_bundle(
        response,
        selected_ids=selected,
        excluded=excluded,
        scope=scope,
        bundle_id=bundle_id,
    )
    receipt = record_creation_receipt(result.bundle)
    return result, receipt


def retrieve_and_emit_bundle(
    request: RetrievalRequest,
    *,
    selected_ids: list[str] | None = None,
    excluded: list[ExcludedItem] | None = None,
    scope: BundleScope | None = None,
    bundle_id: str | None = None,
) -> tuple[RetrievalBundleResult, BundleReceipt]:
    """Run the real retrieval capability and emit a bundle from the response."""
    response = retrieve(request)
    return emit_bundle_from_response(
        response,
        selected_ids=selected_ids,
        excluded=excluded,
        scope=scope,
        bundle_id=bundle_id,
    )


__all__ = ["emit_bundle_from_response", "retrieve_and_emit_bundle"]
