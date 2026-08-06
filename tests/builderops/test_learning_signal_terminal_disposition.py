"""Terminal LearningSignal dispositions must name a linked successor artifact.

Issue #4267: a `LearningSignal` marked `superseded` or `discarded` without a
linked successor artifact (Issue, PR, or PromotionIntent) reads as "handled"
while the underlying divergence stays unrepaired. These tests exercise the
production write path (`SqliteBuilderOpsStore.transition_record_state` /
`create_record`) rather than the validation helper in isolation, and the
observe-only completeness report that flags legacy records.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.completeness_report import build_completeness_report
from app.builderops.models import BuilderOpsValidationError
from app.builderops.store import SqliteBuilderOpsStore


def _actor() -> dict[str, str]:
    return {"actor_type": "agent", "id": "agent-4267"}


def _source_ref(ref: str = "#4267") -> list[dict[str, str]]:
    return [{"ref_type": "github_issue", "ref": ref, "authority_surface": "github"}]


@pytest.fixture()
def store(tmp_path: Path) -> SqliteBuilderOpsStore:
    s = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    s.initialize()
    return s


def _create_signal(store: SqliteBuilderOpsStore, signal_id: str) -> dict[str, object]:
    return store.create_learning_signal(
        id=signal_id,
        summary="publish-pr templates omit the BuilderOps Routing section",
        content="Templates in .codex/skills/publish-pr/SKILL.md fail pr-contract.",
        signal_type="workflow_divergence",
        idempotency_key=f"create:{signal_id}",
        source_refs=_source_ref(),
        created_by=_actor(),
    )


@pytest.mark.parametrize("terminal_state", ["superseded", "discarded"])
def test_superseded_signal_requires_linked_successor_artifact(
    store: SqliteBuilderOpsStore, terminal_state: str
) -> None:
    """The production transition path refuses a bare terminal disposition."""

    signal = _create_signal(store, f"lrn_4267_{terminal_state}")
    lease = store.acquire_lease(signal["id"], actor=_actor())

    # Negative path: no successor artifact -> the transition fails loud and the
    # record stays in its previous state.
    with pytest.raises(BuilderOpsValidationError, match="successor_refs"):
        store.transition_record_state(
            signal["id"],
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key=f"transition:{signal['id']}:bare",
            source_refs=_source_ref(),
            summary="Mark signal handled",
            action=terminal_state,
            receipt_body="Bare status transition without a successor artifact.",
            lifecycle_state=terminal_state,
        )
    unchanged = store.get_record(signal["id"])
    assert unchanged is not None
    assert unchanged["lifecycle_state"] == "active"

    # Success path: the same transition with a successor artifact lands, and
    # the record durably names what enacted the divergence.
    result = store.transition_record_state(
        signal["id"],
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key=f"transition:{signal['id']}:linked",
        source_refs=_source_ref(),
        summary="Mark signal handled with successor",
        action=terminal_state,
        receipt_body="Repair delivered by #4192 (fix for #4187).",
        lifecycle_state=terminal_state,
        successor_refs=[
            {"ref_type": "github_pr", "ref": "#4192", "authority_surface": "github"},
        ],
    )
    updated = result["record"]
    assert updated["lifecycle_state"] == terminal_state
    assert {"ref_type": "github_pr", "ref": "#4192", "authority_surface": "github"} in (
        updated["successor_refs"]
    )
    persisted = store.get_record(signal["id"])
    assert persisted is not None
    assert persisted["successor_refs"] == updated["successor_refs"]


def test_successor_refs_must_name_issue_pr_or_promotion_intent(
    store: SqliteBuilderOpsStore,
) -> None:
    """A successor pointing at another BuilderOps signal does not terminate one."""

    signal = _create_signal(store, "lrn_4267_wrong_ref_type")
    lease = store.acquire_lease(signal["id"], actor=_actor())

    with pytest.raises(BuilderOpsValidationError, match="ref_type"):
        store.transition_record_state(
            signal["id"],
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key=f"transition:{signal['id']}:signal-ref",
            source_refs=_source_ref(),
            summary="Supersede with another signal",
            action="superseded",
            receipt_body="Replaced by a newer signal; no repair artifact linked.",
            lifecycle_state="superseded",
            successor_refs=[
                {"ref_type": "builderops_object", "ref": "lrn_newer_signal"},
            ],
        )


def test_signal_created_in_terminal_state_requires_successor(
    store: SqliteBuilderOpsStore,
) -> None:
    """Creation directly into a terminal state is held to the same contract."""

    with pytest.raises(BuilderOpsValidationError, match="successor_refs"):
        store.create_learning_signal(
            id="lrn_4267_created_terminal",
            summary="Pre-superseded signal",
            content="Should not be creatable without a successor artifact.",
            signal_type="workflow_divergence",
            lifecycle_state="superseded",
            idempotency_key="create:lrn_4267_created_terminal",
            source_refs=_source_ref(),
            created_by=_actor(),
        )


def test_completeness_report_flags_legacy_terminal_signal_without_successor() -> None:
    """Legacy terminal records without a successor are machine-flaggable."""

    legacy = {
        "id": "lrn_20260602_legacy",
        "object_type": "LearningSignal",
        "lifecycle_state": "superseded",
        "created_at": "2026-06-02T00:00:00Z",
        "summary": "publish-pr templates omit BuilderOps Routing",
        "signal_type": "workflow_divergence",
    }
    linked = {
        "id": "lrn_20260602_linked",
        "object_type": "LearningSignal",
        "lifecycle_state": "superseded",
        "created_at": "2026-06-02T00:00:00Z",
        "summary": "Signal with linked successor",
        "signal_type": "workflow_divergence",
        "successor_refs": [
            {"ref_type": "github_issue", "ref": "#4187"},
        ],
    }
    report = build_completeness_report(
        records=[legacy, linked],
        storage={"available": True, "source": "fixture"},
    )

    flagged = report["terminal_signals_missing_successor_refs"]
    assert [entry["id"] for entry in flagged] == ["lrn_20260602_legacy"]
    assert flagged[0]["lifecycle_state"] == "superseded"
    assert report["complete"] is False
    assert "terminal_signals_missing_successor_refs=1" in report["receipt_body"]
