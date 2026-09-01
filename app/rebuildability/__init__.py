"""Bounded rebuildability contracts for Product projections."""

from .product_total_loss import (
    PRODUCT_REPLAY_RECIPE_VERSION,
    ProductReadiness,
    ProductReplayRefusal,
    ProductReplayTuple,
    canonical_product_source_text,
    evaluate_product_store_readiness,
    product_replay_provenance,
)
from .product_projection_rebuild import (
    DbOutboxProjectionQueue,
    DurableProjectionWork,
    ProjectionRelation,
    ProjectionReplayQueue,
    ProjectionReplaySummary,
    ProductProjectionReplayRefusal,
    ProductProjectionTargets,
    RECONSTRUCTABLE_QUEUE_EVENTS,
    RetainedProjectionSource,
    load_durable_projection_work,
    rebuild_product_projections,
)

__all__ = [
    "DbOutboxProjectionQueue",
    "PRODUCT_REPLAY_RECIPE_VERSION",
    "ProductReadiness",
    "ProductReplayRefusal",
    "ProductReplayTuple",
    "canonical_product_source_text",
    "evaluate_product_store_readiness",
    "product_replay_provenance",
    "DurableProjectionWork",
    "ProjectionRelation",
    "ProjectionReplayQueue",
    "ProjectionReplaySummary",
    "ProductProjectionReplayRefusal",
    "ProductProjectionTargets",
    "RECONSTRUCTABLE_QUEUE_EVENTS",
    "RetainedProjectionSource",
    "load_durable_projection_work",
    "rebuild_product_projections",
]
