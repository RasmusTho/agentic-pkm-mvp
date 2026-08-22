"""Provider-free contract types for the governed archival flow.

This package defines vocabulary and adapter seams only.  It deliberately has no
storage, provider, persistence, or production-producer dependency.
"""

from .contracts import (
    ArchivalAdapter,
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    AuthorityOwner,
    Durability,
    Liveness,
    PolicyProfile,
    Provenance,
    Receipt,
    RepresentationDescriptor,
    RepresentationRef,
    TransitionStage,
)

__all__ = [
    "ArchivalAdapter",
    "ArtifactClass",
    "ArtifactDescriptor",
    "ArtifactIdentity",
    "AuthorityOwner",
    "Durability",
    "Liveness",
    "PolicyProfile",
    "Provenance",
    "Receipt",
    "RepresentationDescriptor",
    "RepresentationRef",
    "TransitionStage",
]
