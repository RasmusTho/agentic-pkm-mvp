"""Emit a ContextBundle from a RetrievalResponse (CONTEXT-BUNDLES-02)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExcludedItem,
    ExpiryPosture,
    IncludedItem,
    ItemProvenance,
)
from app.retrieval.capability import RetrievalResponse


@dataclass(frozen=True)
class RetrievalBundleResult:
    """Holds both the emitted bundle and the original ranked candidates.

    Keeping ranked_candidates separate from bundle.included preserves the
    contract boundary between "what matched" and "what was selected for
    human-facing output."
    """

    bundle: ContextBundle
    ranked_candidates: list[dict[str, Any]] = field(default_factory=list)


def emit_retrieval_bundle(
    response: RetrievalResponse,
    selected_ids: list[str],
    excluded: list[ExcludedItem] | None = None,
    scope: BundleScope | None = None,
    bundle_id: str | None = None,
) -> RetrievalBundleResult:
    """Wrap retrieval results in an inspectable ContextBundle.

    ``selected_ids`` names the hits chosen for human-facing output.
    All ranked hits are preserved in ``ranked_candidates`` so callers
    can inspect what was not selected without looking inside the bundle.

    ``may_write`` is always False — retrieval output does not authorize
    writeback without an explicit downstream governed action.
    """
    selected_set = set(selected_ids)

    ranked_candidates: list[dict[str, Any]] = [
        {
            "artifact_id": hit.object_id,
            "doc_id": hit.doc_id,
            "score": hit.score,
            "source_ref": hit.source_ref,
        }
        for hit in response.hits
    ]

    included: list[IncludedItem] = []
    for hit in response.hits:
        if hit.object_id not in selected_set:
            continue
        included.append(
            IncludedItem(
                artifact_id=hit.object_id,
                path=hit.source_ref,
                reason="selected from ranked retrieval results",
                retrieval_score=hit.score,
                provenance=ItemProvenance(origin="retrieval"),
            )
        )

    bundle = ContextBundle(
        id=bundle_id or str(uuid.uuid4()),
        created_at=datetime.now(tz=timezone.utc),
        trigger=BundleTrigger(
            type="retrieval",
            source=response.trace_id,
        ),
        intended_use=["answer"],
        scope=scope or BundleScope(),
        included=included,
        excluded=excluded or [],
        authority=AuthorityFlags(
            may_answer=True,
            may_orient=False,
            may_resurface=False,
            may_propose=False,
            may_write=False,
        ),
        expiry=ExpiryPosture(),
    )

    return RetrievalBundleResult(bundle=bundle, ranked_candidates=ranked_candidates)
