"""Unit tests for the shared episode_ref projection helper (ERE-05, #3180).

``app.ingest.episode_ref.episode_ref_from_frontmatter`` is the single source every store-payload
producer imports (vault_alpha / vault_root / alpha_human_flows / external / reflection_consumer) so
the vault-canonical episode_ref carry can never drift between producers -- the round-3 audit found a
second producer that had a divergent (absent) carry. These lock the projection rules.
"""

from __future__ import annotations

from app.ingest.episode_ref import UNBOUND, episode_ref_from_frontmatter


def test_absent_or_none_frontmatter_defaults_unbound() -> None:
    assert episode_ref_from_frontmatter(None) == UNBOUND
    assert episode_ref_from_frontmatter({}) == UNBOUND
    assert episode_ref_from_frontmatter({"title": "x"}) == UNBOUND


def test_valid_sentinels_pass_through() -> None:
    assert episode_ref_from_frontmatter({"episode_ref": "unbound"}) == "unbound"
    assert episode_ref_from_frontmatter({"episode_ref": "pending"}) == "pending"


def test_non_empty_id_list_passes_through_as_list() -> None:
    assert episode_ref_from_frontmatter({"episode_ref": ["ep-1"]}) == ["ep-1"]
    assert episode_ref_from_frontmatter({"episode_ref": ("ep-1", "ep-2")}) == ["ep-1", "ep-2"]


def test_malformed_values_fall_back_to_unbound() -> None:
    # Out-of-shape values never smuggle through (mirrors envelope._episode_ref_from_payload).
    assert episode_ref_from_frontmatter({"episode_ref": "bogus"}) == UNBOUND
    assert episode_ref_from_frontmatter({"episode_ref": []}) == UNBOUND
    assert episode_ref_from_frontmatter({"episode_ref": ["", "ok"]}) == UNBOUND
    assert episode_ref_from_frontmatter({"episode_ref": [1, 2]}) == UNBOUND
    assert episode_ref_from_frontmatter({"episode_ref": {"nested": "dict"}}) == UNBOUND
