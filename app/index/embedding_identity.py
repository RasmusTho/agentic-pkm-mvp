"""Pre-dispatch guards for the vector index's primary embedding identity."""

from __future__ import annotations

from app.components.embeddings import EmbeddingIdentity


class IndexEmbeddingIdentityMismatch(RuntimeError):
    """The selected primary model cannot write to the index's established identity."""


def ensure_index_primary_identity(index: object, requested: EmbeddingIdentity) -> None:
    """Reject a known identity drift before inference or any vector replacement.

    Empty or legacy indexes may not expose an established identity. Their normal
    upsert path remains responsible for initialization and backend-specific
    validation. An existing primary identity remains authoritative until the
    governed index rebuild/reconcile path changes it.
    """
    get_identity = getattr(index, "get_identity", None)
    if not callable(get_identity):
        return
    stored = get_identity()
    if stored is None:
        return

    fields = ("provider", "model", "dim", "normalize")
    if all(getattr(stored, field) == getattr(requested, field) for field in fields):
        return

    raise IndexEmbeddingIdentityMismatch(
        "Embedding identity mismatch "
        f"(stored provider={stored.provider} model={stored.model} dim={stored.dim} "
        f"normalize={stored.normalize}; requested provider={requested.provider} "
        f"model={requested.model} dim={requested.dim} normalize={requested.normalize}). "
        "Run 'python -m app.cli index rebuild' to rebuild embeddings."
    )
