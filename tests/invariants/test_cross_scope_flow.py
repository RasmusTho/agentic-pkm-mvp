"""Invariant skeletons: similarity is not permission; crossing scopes needs a typed flow.

Invariant registry: docs/testing/invariant-tests.md
  :: similarity_not_permission, cross_scope_only_via_flow, retrieve_scope_prefilter,
     parent_aggregation_not_sibling_sharing, sync_preserves_boundaries
Issues: #2550 (registry), #2552 (skeletons).
Contracts: docs/architecture/cross-scope-flow.md (#2539), docs/architecture/retrieval-contract.md (#2548).

Runtime skeletons xfail *only* on the missing runtime import (require_future_runtime); their
assertions run for real once the runtime exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tests.invariants._helpers import load_schema, require_future_runtime


def test_scope_prefilter_asserted_in_schema() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter
    # Static companion (schema_enforced): a RetrievalResult pins scope_policy_prefiltered=true, so
    # eligibility-before-ranking is asserted in the data shape itself.
    rr = load_schema("retrieval-result.schema.json")
    flag = rr["properties"]["scope_policy_prefiltered"]
    assert flag.get("const") is True
    assert "scope_policy_prefiltered" in rr.get("required", [])


def test_retrieve_scope_prefilter() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter
    rca = require_future_runtime(
        "retrieval",
        "Runtime retrieval prefilter not implemented yet; protects retrieve_scope_prefilter (#2550).",
    )
    result = rca.retrieve(query="state machine", active_scope_id="scope:work/project-alpha")
    # Out-of-scope material is excluded before ranking, not merely ranked lower.
    for candidate in result.candidate_items:
        assert candidate.metadata_bundle.scope_id == "scope:work/project-alpha"


def test_similarity_is_not_permission() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: similarity_not_permission
    rca = require_future_runtime(
        "retrieval",
        "Runtime ranking/admission not implemented yet; protects similarity_not_permission (#2550).",
    )
    # A Project Beta doc is highly similar to a Project Alpha query, but similarity must not admit it.
    result = rca.retrieve(query="telemetry state machine", active_scope_id="scope:work/project-alpha")
    admitted = [c for c in result.candidate_items if c.admissibility_status == "admitted"]
    assert all(c.metadata_bundle.scope_id == "scope:work/project-alpha" for c in admitted)


def test_cross_scope_only_via_flow() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow
    gov = require_future_runtime(
        "cross_scope",
        "Runtime CrossScopeFlow enforcement not implemented yet; protects cross_scope_only_via_flow (#2550).",
    )
    # With no flow, a cross-scope operation must be denied.
    decision = gov.evaluate(
        source_scope="scope:general/programming",
        target_scope="scope:work/project-alpha",
        operation="cite",
        flow=None,
    )
    assert decision.allowed is False


def test_episode_fusion_denied_without_flow(tmp_path: Path) -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow (ERE-08 #3183)
    # Enforcement on the PRODUCTION fusion path (app.episodes.segmenter): mixed-scope co-occurring
    # signals with NO CrossScopeFlow produce split per-scope episodes and NO fused note --
    # evaluate(..., flow=None) denial honored at the real fusion call site (ADR-0054 §5; ADR-0028
    # "similarity is not permission"). This is the engine's most likely leak, closed by design.
    from app.episodes import cross_scope_fusion
    from app.episodes.notes import episode_note_rel_path, parse_episode_note
    from app.episodes.segmenter import ClosedSegment, _deterministic_episode_id
    from app.write_guard import WriteGuard

    def _dt(minute: int) -> datetime:
        return datetime(2026, 7, 12, 9, minute, 0, tzinfo=timezone.utc)

    work = ClosedSegment(
        scope="scope:work/project-alpha", start=_dt(0), end=_dt(30), heimdal_session_id=None,
        protagonists=(), goal=(), derived_from=("vault.activity:w1",),
    )
    private = ClosedSegment(
        scope="scope:private/journal", start=_dt(10), end=_dt(40), heimdal_session_id=None,
        protagonists=(), goal=(), derived_from=("heimdal.observations:p1",),
    )

    # Production emission with NO flow_provider -> every cross-scope decision denies.
    from app.episodes import segmenter

    result = segmenter._emit_proposals_with_fusion_gate(
        [work, private],
        vault_root=tmp_path,
        write_guard=WriteGuard(lambda: {"state": "healthy", "reason": None}),
        flow_provider=None,
    )

    # Denied: two split per-scope proposals, no fused note, one audited denial.
    assert result["fused"] == []
    assert result["fusions_denied"] == 1
    assert len(result["proposed"]) == 2

    # Each scope kept its own episode; neither is a cross-scope fused note.
    work_id = _deterministic_episode_id(work)
    private_id = _deterministic_episode_id(private)
    work_fields = parse_episode_note(
        (tmp_path / episode_note_rel_path(work_id)).read_text(encoding="utf-8")
    )
    private_fields = parse_episode_note(
        (tmp_path / episode_note_rel_path(private_id)).read_text(encoding="utf-8")
    )
    assert work_fields["scope"] == "scope:work/project-alpha"
    assert private_fields["scope"] == "scope:private/journal"
    # The content-free sibling marker is the ONLY cross-link (no fused episode was constructed).
    assert work_fields["causation"] == [cross_scope_fusion.CROSS_SCOPE_SIBLING_MARKER]
    assert private_fields["causation"] == [cross_scope_fusion.CROSS_SCOPE_SIBLING_MARKER]
    # No fusion receipt was written (a receipt exists only for an ALLOWED fuse).
    assert not (tmp_path / "episodes" / "receipts").exists()


def test_parent_aggregation_not_sibling_sharing() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: parent_aggregation_not_sibling_sharing
    wsp = require_future_runtime(
        "scope",
        "Runtime scope/aggregation not implemented yet; protects parent_aggregation_not_sibling_sharing (#2550).",
    )
    # Alpha and Beta share a parent, but Alpha must not reach Beta without an Alpha->Beta flow.
    visible = wsp.aggregated_scopes(active_scope_id="scope:work/project-alpha")
    assert "scope:work/project-beta" not in visible


def test_sync_preserves_boundaries() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: sync_preserves_boundaries
    sfc = require_future_runtime(
        "sync",
        "Runtime sync/federation not implemented yet; protects sync_preserves_boundaries (#2550).",
    )
    merged = sfc.merge_replica(object_id="obj-1")
    # A replica merge never changes scope/authority by last-writer-wins.
    assert merged.scope_id_unchanged
    assert merged.authority_state_unchanged
