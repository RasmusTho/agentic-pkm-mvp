"""#2998 (EXP-5) -- `connect.cluster_emergence` -> `create.overview` handoff.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §1.1,
§2.1, §5 (EXP-5 first AC).

Covers the issue's first Acceptance Criterion:

- A `connect.cluster_emergence` finding, once accepted, hands off to a
  `create.overview` draft over the cluster's member notes.

Plus the discipline that keeps the handoff candidate-only:

- Cluster detection itself never materializes an overview -- it only emits
  propose-track `CurationFinding` records, exactly like every other
  `connect.*` class (`connect_proposals_candidate_only`).
- The handoff function is a pure conversion step: it never calls
  `run_create_pass` and performs no acceptance-state check of its own --
  wiring "only after acceptance" is the caller's responsibility, proven here
  by driving the handoff through the real staged-draft lifecycle once a
  cluster's member sources are supplied.
- An incomplete member-source mapping fails loud rather than silently
  synthesizing a partial overview.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.curation.findings import CONNECT_FINDING_CLASSES, FindingClass, FindingTrack, track_for_class
from app.expansion.connect import (
    ClusterEmergenceConfig,
    ClusterEmergenceReport,
    cluster_emergence_to_create_request,
    compute_cluster_finding_id,
    find_cluster_emergence,
)
from app.expansion.create import OutputKind, SourceInput, run_create_pass
from app.proposals.declined_ledger import DeclinedLedger
from app.write_guard import WriteGuard


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _related_unlinked_finding(note_uuid: str, other_uuid: str, *, basis: str) -> "object":
    from app.expansion.connect import _make_connect_findings  # noqa: PLC0415 (test-only reach-in)
    from app.expansion.connect import _NoteCandidate

    a = _NoteCandidate(note_uuid=note_uuid, rel_path=f"{note_uuid}.md", scope="work", language="en", span=f"span-{note_uuid}", score=0.9)
    b = _NoteCandidate(note_uuid=other_uuid, rel_path=f"{other_uuid}.md", scope="work", language="en", span=f"span-{other_uuid}", score=0.9)
    return _make_connect_findings(
        finding_class=FindingClass.CONNECT_RELATED_UNLINKED,
        candidates=(a, b),
        observed=f"{note_uuid} and {other_uuid} share unlinked related content",
        proposed=f"consider linking {note_uuid} <-> {other_uuid}",
        basis=basis,
    )


def _triangle_pair_findings() -> tuple:
    """Three mutually-related pairs (a-b, b-c, a-c) -> one 3-member cluster."""
    findings = []
    findings.extend(_related_unlinked_finding("uuid-a", "uuid-b", basis="high|shared-1"))
    findings.extend(_related_unlinked_finding("uuid-b", "uuid-c", basis="high|shared-2"))
    findings.extend(_related_unlinked_finding("uuid-a", "uuid-c", basis="high|shared-3"))
    return tuple(findings)


# ---------------------------------------------------------------------------
# Candidate-only: cluster detection never materializes anything
# ---------------------------------------------------------------------------


def test_cluster_emergence_class_is_candidate_only() -> None:
    assert FindingClass.CONNECT_CLUSTER_EMERGENCE in CONNECT_FINDING_CLASSES
    assert track_for_class(FindingClass.CONNECT_CLUSTER_EMERGENCE) == FindingTrack.PROPOSE


def test_cluster_of_three_related_pairs_is_detected() -> None:
    report = find_cluster_emergence(_triangle_pair_findings())

    assert isinstance(report, ClusterEmergenceReport)
    assert report.clusters_found == 1
    member_uuids = {f.note_uuid for f in report.findings}
    assert member_uuids == {"uuid-a", "uuid-b", "uuid-c"}
    for finding in report.findings:
        assert finding.finding_class == FindingClass.CONNECT_CLUSTER_EMERGENCE
        assert finding.track == FindingTrack.PROPOSE
        # a draft theme label marked uncertain (spec §1.1)
        assert "uncertain" in finding.span


def test_pair_below_min_cluster_size_is_not_a_cluster() -> None:
    """A single related-unlinked pair (2 members) never reaches
    hub-worthiness (spec §1.1: "cluster member refs (>=3)")."""
    pair_only = _related_unlinked_finding("uuid-x", "uuid-y", basis="high|only-pair")
    report = find_cluster_emergence(tuple(pair_only))
    assert report.clusters_found == 0
    assert report.findings == ()


def test_cluster_finding_id_is_order_independent() -> None:
    """The same member set produces the identical finding_id regardless of
    set construction/iteration order -- idempotency discipline mirrors
    `compute_connect_finding_id`'s pair case, extended to N members."""
    id_a = compute_cluster_finding_id(member_uuids=frozenset({"uuid-a", "uuid-b", "uuid-c"}))
    id_b = compute_cluster_finding_id(member_uuids=frozenset({"uuid-c", "uuid-a", "uuid-b"}))
    assert id_a == id_b


def test_declined_cluster_is_suppressed(tmp_path: Path) -> None:
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    pair_findings = _triangle_pair_findings()

    first = find_cluster_emergence(pair_findings, config=ClusterEmergenceConfig(declined_ledger=ledger))
    assert first.clusters_found == 1
    finding_id = first.findings[0].finding_id
    ledger.record_decline(finding_id, finding_class="connect.cluster_emergence", write_guard=_allow_all_guard())

    second = find_cluster_emergence(pair_findings, config=ClusterEmergenceConfig(declined_ledger=ledger))
    assert second.findings == ()
    assert second.suppressed_by_decline == 1


# ---------------------------------------------------------------------------
# AC1: accepted cluster finding -> create.overview draft over the cluster
# ---------------------------------------------------------------------------


def _member_sources() -> dict[str, SourceInput]:
    return {
        "uuid-a": SourceInput(
            object_id="uuid-a", note_path="a.md", text="Alpha note about topic X.", quoted_spans=("Alpha note about topic X.",), language="en"
        ),
        "uuid-b": SourceInput(
            object_id="uuid-b", note_path="b.md", text="Beta note about topic X.", quoted_spans=("Beta note about topic X.",), language="en"
        ),
        "uuid-c": SourceInput(
            object_id="uuid-c", note_path="c.md", text="Gamma note about topic X.", quoted_spans=("Gamma note about topic X.",), language="en"
        ),
    }


def test_accepted_cluster_finding_hands_off_to_overview_draft(tmp_path: Path) -> None:
    """AC1: a `connect.cluster_emergence` finding, once accepted, hands off to
    a `create.overview` draft over the cluster's member notes -- driven
    through the REAL staged-draft lifecycle (`run_create_pass`), not a mock."""
    report = find_cluster_emergence(_triangle_pair_findings())
    assert report.clusters_found == 1
    member_uuids = {f.note_uuid for f in report.findings}

    # The handoff runs only AFTER acceptance -- simulated here by the caller
    # supplying the member set (as an accepted-finding's acceptance handler
    # would) rather than the finding object itself.
    request = cluster_emergence_to_create_request(
        member_uuids, member_sources=_member_sources(), title="Topic X overview"
    )
    assert request.kind == OutputKind.OVERVIEW
    assert {s.object_id for s in request.sources} == member_uuids

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"
    draft_report = run_create_pass(
        request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard()
    )

    assert draft_report.activatable is True
    assert draft_report.kind == OutputKind.OVERVIEW
    draft_text = (vault_root / draft_report.draft_path).read_text(encoding="utf-8")
    for uuid in member_uuids:
        assert uuid in draft_text
    assert "authority_state: proposal" in draft_text
    assert "- [ ]" in draft_text
    assert "- [x]" not in draft_text  # still staged, not yet accepted into canonical


def test_handoff_never_calls_run_create_pass_itself() -> None:
    """The handoff function is a pure conversion step -- building the request
    performs no vault I/O and no draft materialization on its own. Checked
    against the function's CODE, not its docstring (which explains the
    invariant in prose and legitimately names `run_create_pass`)."""
    import inspect

    from app.expansion import connect as connect_module

    source = inspect.getsource(connect_module.cluster_emergence_to_create_request)
    _, _, code_only = source.partition('"""')
    _, _, code_only = code_only.partition('"""')
    assert "run_create_pass(" not in code_only


def test_handoff_fails_loud_on_incomplete_member_sources() -> None:
    """A missing member source raises rather than silently synthesizing an
    overview over a subset of the cluster."""
    incomplete_sources = {"uuid-a": _member_sources()["uuid-a"], "uuid-b": _member_sources()["uuid-b"]}
    with pytest.raises(ValueError):
        cluster_emergence_to_create_request(
            {"uuid-a", "uuid-b", "uuid-c"}, member_sources=incomplete_sources, title="Incomplete"
        )


def test_handoff_fails_loud_on_empty_member_set() -> None:
    with pytest.raises(ValueError):
        cluster_emergence_to_create_request(set(), member_sources={}, title="Empty")
