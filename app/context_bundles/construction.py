"""Construct a read-only, inspectable ``ContextBundle`` envelope (#1560).

This is the production *construction route* source for the Context Bundles
runtime integration wave. It assembles a self-describing bundle envelope from
the typed-contract building blocks in :mod:`app.context_bundles.schema`,
establishing the route response contract before real-vault emission lands in
#1562.

It performs no retrieval, no direct DB access, and no vault mutation. Authority
flags are stated verbatim: the envelope may support answering, orienting, and
resurfacing, but ``may_write`` is never defaulted to true. Writeback authority
is granted only by a downstream governed action, never by this read surface.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.context_bundles.schema import (
    AuthorityFlags,
    BundleReceipts,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExcludedItem,
    ExpiryPosture,
    IncludedItem,
    ItemProvenance,
)


def build_inspectable_bundle(bundle_id: str) -> ContextBundle:
    """Build a self-describing, read-only ``ContextBundle`` envelope.

    The envelope demonstrates the route response contract: identity, trigger,
    intended use, scope, an included item, a visible exclusion, authority flags,
    and an expiry posture. Real included/excluded content is sourced from the
    live retrieval path in #1562; this slice only establishes the route shape.
    """
    return ContextBundle(
        id=bundle_id,
        created_at=datetime.now(tz=timezone.utc),
        trigger=BundleTrigger(type="construction", source="context-bundles-route"),
        intended_use=["answer", "orient", "resurface"],
        scope=BundleScope(),
        included=[
            IncludedItem(
                artifact_id="contract-example",
                reason=(
                    "inspectable construction envelope from typed-contract "
                    "building blocks (real emission lands in #1562)"
                ),
                source_role="evidence",
                provenance=ItemProvenance(origin="typed-contract"),
            )
        ],
        excluded=[
            ExcludedItem(
                artifact_id="out-of-scope-example",
                reason="excluded to keep exclusion tracking visible for review",
            )
        ],
        authority=AuthorityFlags(
            may_answer=True,
            may_orient=True,
            may_resurface=True,
            may_propose=False,
            may_write=False,
        ),
        expiry=ExpiryPosture(
            stale_after=None,
            reason="construction envelope is not tied to a live retrieval snapshot",
        ),
        receipts=BundleReceipts(),
    )


__all__ = ["build_inspectable_bundle"]
