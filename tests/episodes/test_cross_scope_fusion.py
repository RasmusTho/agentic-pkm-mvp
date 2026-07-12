"""Cross-scope fusion gate tests (ERE-08, #3183) -- the engine's most likely leak, closed by design.

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/GATE_CROSS_SCOPE_FUSION.md``; ADR-0054 §5; ADR-0028
("similarity is not permission"); ``docs/architecture/cross-scope-flow.md``.

Deny-by-default is HARD LAW: NO cross-scope path (fused episode, cross-scope artifact binding, or
cross-scope closure-decay influence) exists without an explicit ``CrossScopeFlow`` admitting the
``episode_fuse`` operation. These tests exercise all three gated seams:

- AC2: the split-scope sibling cross-link carries no foreign-scope content. Verify:
  ``test_sibling_link_carries_no_foreign_scope_content``
- AC3: an explicit flow admits exactly one fused episode + a receipt referencing the flow. Verify:
  ``test_explicit_flow_admits_fusion_with_receipt``
- AC4 (enforcement): assignment never binds across scopes unflowed. Verify:
  ``test_assignment_never_crosses_scope_unflowed``
- AC5: closed-episode decay never crosses scopes. Verify: ``test_closure_decay_does_not_cross_scope``
- AC6: denied fusions are audit-logged, not notified. Verify: ``test_denied_fusion_audited_silently``

(AC1's production-path enforcement lives in
``tests/invariants/test_cross_scope_flow.py::test_episode_fusion_denied_without_flow``.)

No live Postgres: the fusion/emission seam writes only the vault (tmp_path), and the assignment and
decay gates are exercised as the pure production functions they are.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.episodes import segmenter
from app.episodes.assignment import (
    ArtifactCandidate,
    BASIS_PROVENANCE,
    EpisodeBoundsRecord,
    compute_assignments,
)
from app.episodes.closure_decay import (
    CLOSURE_DECAY_STEP_DOWN_FACTOR,
    admit_closed_ids_for_scope,
    derive_closure_salience,
)
from app.episodes.cross_scope_fusion import (
    CROSS_SCOPE_SIBLING_MARKER,
    EPISODE_FUSE_OPERATION,
    FLOW_REF_CAUSATION_PREFIX,
)
from app.episodes.notes import episode_note_rel_path, parse_episode_note
from app.episodes.segmenter import ClosedSegment, _deterministic_episode_id
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg

_WORK = "scope:work/project-alpha"
_PRIVATE = "scope:private/journal"


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-blocked"})


def _dt(minute: int) -> datetime:
    return datetime(2026, 7, 12, 9, minute, 0, tzinfo=timezone.utc)


def _segment(
    *,
    scope: str,
    start_min: int,
    end_min: int,
    provenance: str,
    protagonists: tuple[str, ...] = (),
    goal: tuple[str, ...] = (),
) -> ClosedSegment:
    """Two overlapping mixed-scope segments model one lived situation spanning two scopes."""
    return ClosedSegment(
        scope=scope,
        start=_dt(start_min),
        end=_dt(end_min),
        heimdal_session_id=None,
        protagonists=protagonists,
        goal=goal,
        derived_from=(provenance,),
    )


def _flow_for(source: str, target: str) -> "callable":
    """A flow_provider that grants episode_fuse for exactly one direction (source -> target)."""

    flow = {
        "flow_id": "flow-ere08-test",
        "source_scope": source,
        "target_scope": target,
        "allowed_operations": [EPISODE_FUSE_OPERATION],
        "evidence_roles_allowed": ["background"],
    }

    def provider(src: str, tgt: str):
        if src == source and tgt == target:
            return flow
        return None

    return provider


# ---------------------------------------------------------------------------
# AC2: the split-scope sibling cross-link carries NO foreign-scope content
# ---------------------------------------------------------------------------


def test_sibling_link_carries_no_foreign_scope_content(tmp_path: Path) -> None:
    # Two overlapping episodes, one per scope, each carrying content the OTHER must never see.
    work = _segment(
        scope=_WORK, start_min=0, end_min=30, provenance="vault.activity:work-row-777",
        protagonists=("mention:work-colleague",), goal=("goal:work-roadmap",),
    )
    private = _segment(
        scope=_PRIVATE, start_min=10, end_min=40, provenance="heimdal.observations:private-obs-999",
        protagonists=("mention:therapist",), goal=("goal:private-health",),
    )

    summary = segmenter._emit_proposals_with_fusion_gate(
        [work, private], vault_root=tmp_path, write_guard=_allow_guard(), flow_provider=None
    )

    # Deny-by-default: two split notes, no fused note.
    assert summary["fused"] == []
    assert summary["fusions_denied"] == 1

    work_id = _deterministic_episode_id(work)
    private_id = _deterministic_episode_id(private)
    work_text = (tmp_path / episode_note_rel_path(work_id)).read_text(encoding="utf-8")
    private_text = (tmp_path / episode_note_rel_path(private_id)).read_text(encoding="utf-8")

    # Each note carries ONLY the content-free, scope-neutral sibling marker in causation.
    assert parse_episode_note(work_text)["causation"] == [CROSS_SCOPE_SIBLING_MARKER]
    assert parse_episode_note(private_text)["causation"] == [CROSS_SCOPE_SIBLING_MARKER]

    # The work note must contain NONE of the private episode's identifying content, anywhere.
    private_tokens = [
        _PRIVATE, private_id, "heimdal.observations:private-obs-999",
        "mention:therapist", "goal:private-health",
    ]
    for token in private_tokens:
        assert token not in work_text, f"work note leaked private-scope content: {token!r}"

    # ...and symmetrically, the private note leaks none of the work episode's content.
    work_tokens = [
        _WORK, work_id, "vault.activity:work-row-777", "mention:work-colleague", "goal:work-roadmap",
    ]
    for token in work_tokens:
        assert token not in private_text, f"private note leaked work-scope content: {token!r}"


# ---------------------------------------------------------------------------
# AC3: an explicit flow admits exactly ONE fused episode + a receipt referencing the flow
# ---------------------------------------------------------------------------


def test_explicit_flow_admits_fusion_with_receipt(tmp_path: Path) -> None:
    work = _segment(scope=_WORK, start_min=0, end_min=30, provenance="vault.activity:w1")
    private = _segment(scope=_PRIVATE, start_min=10, end_min=40, provenance="heimdal.observations:p1")

    # A flow granting episode_fuse work -> private (segments are sorted by scope: private < work,
    # so the pair is evaluated private->work first, then work->private; the grant admits the latter).
    summary = segmenter._emit_proposals_with_fusion_gate(
        [work, private],
        vault_root=tmp_path,
        write_guard=_allow_guard(),
        flow_provider=_flow_for(_WORK, _PRIVATE),
    )

    # Exactly one fused episode, no split proposals, no denial.
    assert len(summary["fused"]) == 1
    assert summary["proposed"] == []
    assert summary["fusions_denied"] == 0
    fused_id = summary["fused"][0]

    # The fused note lives in the flow's target scope and carries the flow reference in causation.
    fused_text = (tmp_path / episode_note_rel_path(fused_id)).read_text(encoding="utf-8")
    fused_fields = parse_episode_note(fused_text)
    assert fused_fields["scope"] == _PRIVATE
    assert fused_fields["causation"] == [f"{FLOW_REF_CAUSATION_PREFIX}flow-ere08-test"]
    # derived_from unions both scopes' provenance (the flow authorizes exactly this crossing).
    assert set(fused_fields["derived_from"]) == {"vault.activity:w1", "heimdal.observations:p1"}

    # A receipt exists, referencing the flow + the constituent per-scope episodes.
    receipt_path = tmp_path / "episodes" / "receipts" / f"{fused_id}.md"
    assert receipt_path.exists()
    receipt_text = receipt_path.read_text(encoding="utf-8")
    assert "flow-ere08-test" in receipt_text
    assert EPISODE_FUSE_OPERATION in receipt_text

    # The split per-scope notes were NOT written (the pair fused into one).
    assert not (tmp_path / episode_note_rel_path(_deterministic_episode_id(work))).exists()
    assert not (tmp_path / episode_note_rel_path(_deterministic_episode_id(private))).exists()


def test_fusion_receipt_precedes_fused_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Receipt-before-note ordering (ADR-0054 §5): if the fused-note write fails, the receipt is
    already durable -- proving the receipt is written first, never after the note."""
    work = _segment(scope=_WORK, start_min=0, end_min=30, provenance="vault.activity:w1")
    private = _segment(scope=_PRIVATE, start_min=10, end_min=40, provenance="heimdal.observations:p1")

    boom = RuntimeError("note write blows up AFTER the receipt")
    monkeypatch.setattr(
        segmenter, "_emit_fused_note", lambda *a, **k: (_ for _ in ()).throw(boom)
    )

    with pytest.raises(RuntimeError):
        segmenter._emit_proposals_with_fusion_gate(
            [work, private],
            vault_root=tmp_path,
            write_guard=_allow_guard(),
            flow_provider=_flow_for(_WORK, _PRIVATE),
        )

    # The receipt survived even though the note write failed -> receipt came first.
    receipts = list((tmp_path / "episodes" / "receipts").glob("*.md"))
    assert len(receipts) == 1
    assert "flow-ere08-test" in receipts[0].read_text(encoding="utf-8")


def test_blocked_guard_writes_no_fusion_receipt_or_note(tmp_path: Path) -> None:
    """Guard-at-seam: a blocked write guard means neither the receipt nor the fused note is written
    (the receipt write asserts the guard first, so a fused episode can never exist un-receipted)."""
    work = _segment(scope=_WORK, start_min=0, end_min=30, provenance="vault.activity:w1")
    private = _segment(scope=_PRIVATE, start_min=10, end_min=40, provenance="heimdal.observations:p1")

    with pytest.raises(WritesBlockedError):
        segmenter._emit_proposals_with_fusion_gate(
            [work, private],
            vault_root=tmp_path,
            write_guard=_blocking_guard(),
            flow_provider=_flow_for(_WORK, _PRIVATE),
        )

    assert not (tmp_path / "episodes" / "receipts").exists() or not list(
        (tmp_path / "episodes" / "receipts").glob("*.md")
    )


# ---------------------------------------------------------------------------
# AC4 (enforcement): assignment never binds across scopes unflowed
# ---------------------------------------------------------------------------


def test_assignment_never_crosses_scope_unflowed() -> None:
    # A cross-scope artifact/episode pair that would bind on provenance IF scope were ignored.
    artifact = ArtifactCandidate(
        artifact_ref="vault.activity:x1", scope=_WORK, observed_at=_dt(5)
    )
    episode = EpisodeBoundsRecord(
        episode_id="ep-00000000-0000-4000-8000-000000000001",
        scope=_PRIVATE,
        start=_dt(0),
        end=_dt(30),
        derived_from=("vault.activity:x1",),  # provenance-anchored, but WRONG scope
    )

    # Production path: no flow_provider -> deny-by-default -> zero cross-scope bindings.
    assert compute_assignments([artifact], [episode]) == []

    # An explicit flow admitting episode_fuse (artifact.scope -> episode.scope) admits the binding.
    decisions = compute_assignments(
        [artifact], [episode], flow_provider=_flow_for(_WORK, _PRIVATE)
    )
    assert len(decisions) == 1
    assert decisions[0].basis == BASIS_PROVENANCE
    assert decisions[0].episode_id == episode.episode_id

    # Same-scope binding is unaffected by the gate (still binds without any flow).
    same_scope_episode = EpisodeBoundsRecord(
        episode_id="ep-00000000-0000-4000-8000-000000000002",
        scope=_WORK,
        start=_dt(0),
        end=_dt(30),
        derived_from=("vault.activity:x1",),
    )
    assert len(compute_assignments([artifact], [same_scope_episode])) == 1


# ---------------------------------------------------------------------------
# AC5: closed-episode decay never crosses scopes
# ---------------------------------------------------------------------------


def test_closure_decay_does_not_cross_scope() -> None:
    # A work-scope closed episode must never dampen a private-scope artifact bound to it.
    closed_scopes = {"ep-work-closed": _WORK}
    episode_ref = ["ep-work-closed"]

    # Cross-scope, no flow: the closed work episode is NOT admitted -> no dampening for a private
    # artifact (fail-open to full salience -- work scope never influences private ranking).
    admitted_cross = admit_closed_ids_for_scope(
        {"ep-work-closed"}, closed_scopes, _PRIVATE, flow_provider=None
    )
    assert admitted_cross == set()
    factor_cross, salience_cross = derive_closure_salience(episode_ref, admitted_cross)
    assert factor_cross == 1.0
    assert salience_cross == {}

    # Same scope: admitted -> ordinary ERE-06 step-down.
    admitted_same = admit_closed_ids_for_scope(
        {"ep-work-closed"}, closed_scopes, _WORK, flow_provider=None
    )
    assert admitted_same == {"ep-work-closed"}
    factor_same, salience_same = derive_closure_salience(episode_ref, admitted_same)
    assert factor_same == CLOSURE_DECAY_STEP_DOWN_FACTOR
    assert salience_same != {}

    # Cross-scope WITH an explicit flow (work -> private): admitted, so it may dampen.
    admitted_flow = admit_closed_ids_for_scope(
        {"ep-work-closed"}, closed_scopes, _PRIVATE, flow_provider=_flow_for(_WORK, _PRIVATE)
    )
    assert admitted_flow == {"ep-work-closed"}


# ---------------------------------------------------------------------------
# AC6: denied fusions are audit-logged, not notified
# ---------------------------------------------------------------------------


def test_denied_fusion_audited_silently(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    work = _segment(scope=_WORK, start_min=0, end_min=30, provenance="vault.activity:w1")
    private = _segment(scope=_PRIVATE, start_min=10, end_min=40, provenance="heimdal.observations:p1")

    with caplog.at_level(logging.INFO, logger="app.episodes.segmenter"):
        summary = segmenter._emit_proposals_with_fusion_gate(
            [work, private], vault_root=tmp_path, write_guard=_allow_guard(), flow_provider=None
        )

    # The denial IS audited (a log line naming only scopes + reason, never episode content).
    audit_lines = [
        r.getMessage() for r in caplog.records if "episode_fuse DENIED (audited, not notified)" in r.getMessage()
    ]
    assert len(audit_lines) == 1
    assert _WORK in audit_lines[0] and _PRIVATE in audit_lines[0]

    # Silent to the user: the two normal per-scope proposals are still emitted (nothing about the
    # denial is surfaced as a note field or an extra artifact -- only the ordinary split proposals).
    assert summary["fusions_denied"] == 1
    assert len(summary["proposed"]) == 2
    assert summary["fused"] == []
