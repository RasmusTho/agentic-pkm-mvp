"""Migration utilities for embedding provider tagging.

Handles:
- Detecting untagged embeddings
- Auto-tagging legacy embeddings
- Migrating embeddings between providers
- Zero data loss: all vectors preserved
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding

if TYPE_CHECKING:
    pass


def detect_untagged_embeddings(embeddings: list[TaggedEmbedding]) -> list[TaggedEmbedding]:
    """Detect embeddings that lack provider/model tags.

    These are typically embeddings created before tagging was implemented.

    Args:
        embeddings: List of potentially untagged embeddings

    Returns:
        List of untagged embeddings (tag is None or fields are empty)
    """
    untagged = []
    for emb in embeddings:
        if emb.tag is None:
            untagged.append(emb)
        elif not emb.tag.provider or not emb.tag.model:
            untagged.append(emb)
    return untagged


def auto_tag_legacy(
    embeddings: list[TaggedEmbedding],
    provider: str = "legacy",
    model: str = "unknown",
) -> list[TaggedEmbedding]:
    """Auto-tag untagged embeddings with legacy provider/model.

    This enables migrations: old embeddings get tagged with 'legacy/unknown'
    so they remain queryable and can be later re-embedded with new providers.

    Guarantees:
    - All vectors preserved (no data loss)
    - All embeddings remain searchable
    - Can be queried later by provider/model
    - Idempotent (re-tagging already-tagged embeddings is a no-op)

    Args:
        embeddings: List of embeddings (may be tagged or untagged)
        provider: Provider tag for untagged embeddings (default 'legacy')
        model: Model tag for untagged embeddings (default 'unknown')

    Returns:
        New list with all embeddings tagged (untagged ones get legacy tag)
    """
    result = []
    legacy_tag = EmbeddingTag(provider=provider, model=model)

    for emb in embeddings:
        # If already tagged, keep it as-is
        if emb.tag is not None and emb.tag.provider and emb.tag.model:
            result.append(emb)
        else:
            # Create new TaggedEmbedding with legacy tag, preserving all other data
            tagged = TaggedEmbedding(
                id=emb.id,
                uuid=emb.uuid,
                text=emb.text,
                vector=emb.vector,
                tag=legacy_tag,
                created_at=emb.created_at,
                version=emb.version,
            )
            result.append(tagged)

    return result


def migrate_provider(
    embeddings: list[TaggedEmbedding],
    from_provider: str,
    to_provider: str,
    to_model: str,
) -> list[TaggedEmbedding]:
    """Migrate embeddings from one provider to another.

    Used when:
    - Changing embedding provider (e.g., OpenAI -> Anthropic)
    - Switching models (e.g., text-embedding-3-small -> text-embedding-3-large)

    Guarantees:
    - Only specified provider is changed
    - Vectors remain unchanged (migration of vectors requires re-embedding)
    - All other embeddings remain untouched
    - Idempotent

    Note: This changes the tag but NOT the vector. If you need to change
    the vector itself, you must re-embed using the new provider.

    Args:
        embeddings: List of embeddings
        from_provider: Source provider to migrate from (e.g., 'openai')
        to_provider: Target provider (e.g., 'anthropic')
        to_model: Target model identifier

    Returns:
        New list with matching embeddings re-tagged
    """
    result = []
    new_tag = EmbeddingTag(provider=to_provider, model=to_model)

    for emb in embeddings:
        if emb.tag.provider == from_provider:
            # Re-tag with new provider, keep everything else
            migrated = TaggedEmbedding(
                id=emb.id,
                uuid=emb.uuid,
                text=emb.text,
                vector=emb.vector,
                tag=new_tag,
                created_at=emb.created_at,
                version=emb.version,
            )
            result.append(migrated)
        else:
            # Keep as-is
            result.append(emb)

    return result


def count_by_provider_for_migration(
    embeddings: list[TaggedEmbedding],
    provider: str,
) -> int:
    """Count how many embeddings would be affected by a migration.

    Args:
        embeddings: List of embeddings
        provider: Provider to migrate from

    Returns:
        Count of embeddings from that provider
    """
    return sum(1 for emb in embeddings if emb.tag.provider == provider)
