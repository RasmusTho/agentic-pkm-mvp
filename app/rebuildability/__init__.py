"""Bounded rebuildability contracts for Product projections."""

from .product_total_loss import (
    PRODUCT_REPLAY_RECIPE_VERSION,
    ProductReadiness,
    ProductReplayRefusal,
    ProductReplayTuple,
    evaluate_product_store_readiness,
    product_replay_provenance,
)
from .product_projection_rebuild import (
    DurableProjectionWork,
    ProjectionRelation,
    ProjectionReplayQueue,
    ProjectionReplaySummary,
    ProductProjectionReplayRefusal,
    ProductProjectionTargets,
    RECONSTRUCTABLE_QUEUE_EVENTS,
    RetainedProjectionSource,
    rebuild_product_projections,
)

__all__ = [
    "PRODUCT_REPLAY_RECIPE_VERSION",
    "ProductReadiness",
    "ProductReplayRefusal",
    "ProductReplayTuple",
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
    "rebuild_product_projections",
]
