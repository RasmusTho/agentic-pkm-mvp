from __future__ import annotations

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.index.artifact_metadata import (
    _embedding_identity_dict,
    build_indexed_unit_payload,
    canonicalize_indexable_text,
    compute_content_hash,
    compute_indexed_content_hash,
)

pytestmark = pytest.mark.not_pg


class _DuckIdentity:
    """Duck-typed identity object exposing the same attributes as
    EmbeddingIdentity without being a dataclass instance."""

    def __init__(self, provider: str, model: str, dim: int, normalize: bool) -> None:
        self.provider = provider
        self.model = model
        self.dim = dim
        self.normalize = normalize


def test_embedding_identity_dict_variants() -> None:
    """`_embedding_identity_dict` must project the same provider/model/dim/
    normalize shape regardless of whether `identity` is a dataclass instance,
    a plain dict, `None`, or a duck-typed object (#3054 regression guard: the
    mypy false-positive this issue targeted was already resolved by an
    unrelated refactor in #3096 that replaced the asdict(is_dataclass(...))
    pattern with explicit field enumeration; this test locks in the
    documented behavior across all supported input shapes)."""
    expected = {
        "provider": "mock",
        "model": "mock-embedding",
        "dim": 3,
        "normalize": True,
    }

    dataclass_instance = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3, normalize=True)
    assert _embedding_identity_dict(dataclass_instance) == expected

    plain_dict = {"provider": "mock", "model": "mock-embedding", "dim": 3, "normalize": True}
    assert _embedding_identity_dict(plain_dict) == expected

    assert _embedding_identity_dict(None) == {}

    duck_typed = _DuckIdentity(provider="mock", model="mock-embedding", dim=3, normalize=True)
    assert _embedding_identity_dict(duck_typed) == expected


def test_panel_only_canonicalization_collapses_whitespace_only_remainder() -> None:
    panel_only = "\n%% AI:Start %%\nTransient panel text.\n%% AI:End %%\n\n"

    assert canonicalize_indexable_text({"content": panel_only}) == ""
    assert compute_indexed_content_hash(panel_only) == compute_content_hash("")

    meaningful_whitespace = "\n  Retained text.  \n"
    assert canonicalize_indexable_text({"content": meaningful_whitespace}) == meaningful_whitespace


def test_indexed_unit_payload_binds_aliases_and_hash_to_exact_text() -> None:
    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3, normalize=True)
    canonical = "retained canonical bytes"

    payload = build_indexed_unit_payload(
        object_id="11111111-1111-1111-1111-111111111111",
        kind="note",
        source_ref="unit-test://exact-aliases",
        payload={"content": "stale raw content", "text": "stale raw text"},
        text=canonical,
        embedding_identity=identity,
    )

    assert payload["content"] == canonical
    assert payload["text"] == canonical
    assert payload["provenance"]["content_hash"] == compute_content_hash(canonical)
