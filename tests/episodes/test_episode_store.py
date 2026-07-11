"""ERE-02 (#3177): guarded episode-note write seam.

- AC2 (enforcement): the write path asserts WriteGuard *at the production seam*, before any
  filesystem mutation. Verify:
  ``tests/episodes/test_episode_store.py::test_episode_write_asserts_guard_at_seam``
- AC3: a proposed episode write is proposal class -- no DecisionToken/AuthorityReceipt. Verify:
  ``tests/episodes/test_episode_store.py::test_proposed_episode_is_proposal_class_no_authority_receipt``
- AC4: fused episode_id minting cannot collide with a Heimdal per-session episode_id. Verify:
  ``tests/episodes/test_episode_store.py::test_fused_id_space_disjoint_from_heimdal_session_ids``
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import uuid
from pathlib import Path

import pytest

from app.episodes import store as episode_store
from app.episodes.ids import EpisodeIdCollisionError, is_fused_episode_id, mint_episode_id
from app.episodes.store import (
    EPISODE_WRITE_ACTION,
    EpisodeWriteResult,
    write_episode_note,
)
from app.knowledge.contracts import WriteReceipt
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-blocked"})


def _imported_module_names(source: str) -> set[str]:
    """Module names this source imports, parsed via ``ast`` so comments/docstrings that
    merely *mention* a module name (as this file's own docstrings do, to explain the
    invariant) can never masquerade as a real import."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _referenced_names(source: str) -> set[str]:
    """Every bare identifier referenced anywhere in ``source`` (ast.Name nodes only --
    excludes string/comment/docstring text)."""
    tree = ast.parse(source)
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _called_attribute_paths(source: str) -> set[str]:
    """Every call target in ``source`` as a dotted string (e.g. ``write_guard.assert_writes_allowed``),
    parsed via ``ast`` so it reflects real calls, not comment text."""
    tree = ast.parse(source)
    return {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}


def _write(vault_root: Path, write_guard: WriteGuard, **overrides) -> EpisodeWriteResult:
    kwargs = dict(
        title="Debugging session",
        scope="work",
        start="2026-07-11T10:00:00+00:00",
        vault_root=vault_root,
        write_guard=write_guard,
    )
    kwargs.update(overrides)
    return write_episode_note(**kwargs)


# ---------------------------------------------------------------------------
# AC2 -- guard-at-seam
# ---------------------------------------------------------------------------


def test_episode_write_asserts_guard_at_seam(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"

    with pytest.raises(WritesBlockedError) as exc_info:
        _write(vault_root, _blocking_guard())

    assert exc_info.value.action == EPISODE_WRITE_ACTION
    assert exc_info.value.state == "safe_mode"
    # Atomic: a blocked guard means zero bytes touched, not a partial write.
    assert not vault_root.exists() or not any(vault_root.rglob("*.md"))


def test_episode_write_asserted_inside_the_production_seam_not_a_helper() -> None:
    """The guard assertion must live inside ``write_note_relative`` (the real production
    seam #2910 hardened), not a caller-side wrapper this module could route around. Assert
    it directly against the source of ``write_episode_note``: no local
    ``write_guard.assert_writes_allowed`` call exists here -- the guard is threaded through
    to the shared knowledge-write port instead."""
    source = inspect.getsource(episode_store.write_episode_note)
    calls = _called_attribute_paths(source)
    assert "write_guard.assert_writes_allowed" not in calls
    assert "write_note_relative" in calls


def test_episode_write_succeeds_when_guard_allows(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    result = _write(vault_root, _allow_guard())
    assert isinstance(result.receipt, WriteReceipt)
    note_path = vault_root / "episodes" / f"{result.episode_id}.md"
    assert note_path.exists()


# ---------------------------------------------------------------------------
# AC3 -- proposal class carries no authority
# ---------------------------------------------------------------------------


def test_proposed_episode_is_proposal_class_no_authority_receipt(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    result = _write(vault_root, _allow_guard())  # segmentation defaults to "proposed"

    assert result.fields["segmentation"] == "proposed"

    # The result carries only a plain WriteReceipt -- never a DecisionToken/AuthorityReceipt.
    field_names = {f.name for f in dataclasses.fields(result)}
    assert field_names == {"receipt", "episode_id", "fields"}
    assert isinstance(result.receipt, WriteReceipt)
    assert type(result.receipt).__name__ == "WriteReceipt"

    # Structural guarantee, not just this call's behavior: the write seam module never
    # imports the governed-write protocol (PolicyDecision -> DecisionToken -> AuthorityReceipt).
    # A proposal-class write cannot reach governed_write because the seam has no path to it.
    # Parsed via ast (imports + bare-name references only) so this can't be fooled by --
    # or accidentally tripped by -- the module's own explanatory comments/docstrings.
    store_source = inspect.getsource(episode_store)
    imported_modules = _imported_module_names(store_source)
    assert not any("governed_write" in m for m in imported_modules)
    referenced = _referenced_names(store_source)
    assert "DecisionToken" not in referenced
    assert "AuthorityReceipt" not in referenced
    assert "PolicyDecision" not in referenced


def test_accepted_and_recut_segmentations_also_avoid_governance(tmp_path: Path) -> None:
    """Every segmentation value goes through the same seam -- acceptance is a state reached
    by silence, not a governed transition (ADR-0051 §5)."""
    vault_root = tmp_path / "vault"
    for segmentation in ("accepted", "re-cut"):
        result = _write(vault_root, _allow_guard(), segmentation=segmentation)
        assert result.fields["segmentation"] == segmentation
        assert type(result.receipt).__name__ == "WriteReceipt"


# ---------------------------------------------------------------------------
# AC4 -- fused id space disjoint from Heimdal per-session ids
# ---------------------------------------------------------------------------


def test_fused_id_space_disjoint_from_heimdal_session_ids(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"

    # A minted id always has the fused shape and is therefore never a raw Heimdal session id.
    minted = mint_episode_id()
    assert is_fused_episode_id(minted)

    # A raw Heimdal-style session id (no ep- prefix; Heimdal never mandates that shape)
    # cannot be reused directly as the fused episode_id.
    raw_heimdal_session_id = str(uuid.uuid4())
    assert not is_fused_episode_id(raw_heimdal_session_id)

    with pytest.raises(EpisodeIdCollisionError):
        _write(vault_root, _allow_guard(), episode_id=raw_heimdal_session_id)
    # Rejected before any filesystem mutation.
    assert not any(vault_root.rglob("*.md"))

    # The same raw session id is legitimate as a *derived_from* boundary hint.
    result = _write(
        vault_root,
        _allow_guard(),
        derived_from=[raw_heimdal_session_id],
    )
    assert result.fields["derived_from"] == [raw_heimdal_session_id]
    assert is_fused_episode_id(result.episode_id)

    # A fused id cannot echo itself out of derived_from either (self-derivation collision).
    self_id = mint_episode_id()
    with pytest.raises(EpisodeIdCollisionError):
        _write(
            vault_root,
            _allow_guard(),
            episode_id=self_id,
            derived_from=[self_id],
        )
