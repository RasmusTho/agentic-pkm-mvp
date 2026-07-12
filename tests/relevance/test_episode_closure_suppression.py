"""Moment suppression for closed-episode-only basis artifacts (ERE-06, #3181, AC5).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md`` -- "Moment proposals
whose basis artifacts bind only to closed episodes are suppressed in the deterministic evaluator
(open-loop-pressure drop)." Mixed-basis Moments (any basis note unbound or bound to an open
episode) survive.

Vault-native throughout (the deterministic evaluator, CRE-03, reads no external source and touches
no DB): closure resolution reads the Episode notes' own frontmatter directly
(``app.episodes.closure_decay.read_closed_episode_ids_from_vault``).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.episodes.notes import render_episode_note
from app.relevance.evaluator import DeterministicRelevanceEvaluator

TODAY = date(2026, 7, 11)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_episode_note(vault: Path, *, episode_id: str, closed: bool) -> None:
    fields = {
        "episode_id": episode_id,
        "scope": "work",
        "title": "Fixture episode",
        "time": {"start": "2026-07-10T09:00:00+00:00", "closed": closed, "end": "2026-07-10T10:00:00+00:00"},
        "space": [],
        "protagonists": [],
        "goal": [],
        "causation": [],
        "parent_episode": None,
        "segmentation": "proposed",
        "derived_from": [],
    }
    _write(vault / "episodes" / f"{episode_id}.md", render_episode_note(fields))


def _write_open_task_note(vault: Path, rel: str, *, episode_ref) -> None:
    frontmatter_lines = ["---", "uuid: " + rel.replace("/", "-")]
    if episode_ref is not None:
        if isinstance(episode_ref, list):
            frontmatter_lines.append("episode_ref:")
            for ref in episode_ref:
                frontmatter_lines.append(f"  - {ref}")
        else:
            frontmatter_lines.append(f"episode_ref: {episode_ref}")
    frontmatter_lines.append("---")
    body = "\n".join(frontmatter_lines) + "\n\n# Note\n\n- [ ] an open loop\n"
    _write(vault / rel, body)


def test_closed_episode_moments_suppressed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    episode_id = "ep-a1a1a1a1-2222-4333-8444-555555555555"
    _write_episode_note(vault, episode_id=episode_id, closed=True)
    _write_open_task_note(vault, "Projects/ClosedOnly.md", episode_ref=[episode_id])

    evaluator = DeterministicRelevanceEvaluator(vault, today=TODAY)
    moments = evaluator.evaluate()

    assert moments == []


def test_open_episode_moments_survive(tmp_path: Path) -> None:
    """Control: the SAME shape, but the episode is still open -- the Moment must survive."""
    vault = tmp_path / "vault"
    episode_id = "ep-b2b2b2b2-2222-4333-8444-555555555555"
    _write_episode_note(vault, episode_id=episode_id, closed=False)
    _write_open_task_note(vault, "Projects/OpenOnly.md", episode_ref=[episode_id])

    evaluator = DeterministicRelevanceEvaluator(vault, today=TODAY)
    moments = evaluator.evaluate()

    assert len(moments) == 1
    assert any("Projects/OpenOnly.md" == ref.ref for ref in moments[0].surfaced_refs)


def test_mixed_basis_moments_survive(tmp_path: Path) -> None:
    """A Moment grounded on BOTH a closed-episode note and an unbound note survives -- only a
    Moment whose EVERY basis artifact is closed-only is suppressed."""
    vault = tmp_path / "vault"
    episode_id = "ep-c3c3c3c3-2222-4333-8444-555555555555"
    _write_episode_note(vault, episode_id=episode_id, closed=True)
    _write_open_task_note(vault, "Projects/ClosedOnly.md", episode_ref=[episode_id])
    _write_open_task_note(vault, "Projects/Unbound.md", episode_ref=None)

    evaluator = DeterministicRelevanceEvaluator(vault, today=TODAY)
    moments = evaluator.evaluate()

    assert len(moments) == 1
    refs = {ref.ref for ref in moments[0].surfaced_refs}
    assert "Projects/ClosedOnly.md" in refs
    assert "Projects/Unbound.md" in refs
