from __future__ import annotations

import inspect
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from app.activation.gate import ConsumingAuthority
from app.agent_memory.candidate import MemoryType
from app.agent_memory.provisional_memory import (
    ProvisionalMarkdownArtifact,
    ProvisionalReconciliationState,
    ProvisionalSensitivity,
    rebuild_provisional_memory,
)
from app.agent_memory import provisional_write as provisional_write_module
from app.agent_memory.provisional_write import (
    load_provisional_markdown,
    render_provisional_markdown,
)
from app.agent_memory.recall_explanation import ActivationReason, RecallUseRight
from app.write_guard import WriteGuard


def test_write_endpoint_cannot_promote_or_authorize_apply() -> None:
    source = inspect.getsource(provisional_write_module)
    assert "materialize_promoted_memory" not in source
    assert "mark_terminal" not in source
    assert "promotion_state" not in source

    record_source = inspect.getsource(
        provisional_write_module.write_provisional_memory
    )
    assert "assert_provisional_trust_tier" in record_source
    assert "write_note_relative" in record_source


def test_sync_is_not_an_execution_bus(tmp_path: Path) -> None:
    memory_id = UUID("12345678-1234-4abc-8def-1234567890ab")
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="A file appearing is not a transition.",
        created_by="human://owner",
        created_at="2026-07-15T00:00:00Z",
        provenance_event_ids=("event-1",),
    )
    path = tmp_path / "Memory" / "Provisional" / f"{memory_id}.md"
    path.parent.mkdir(parents=True)
    path.write_text(render_provisional_markdown(artifact), encoding="utf-8")

    loaded = load_provisional_markdown(path, vault_root=tmp_path)
    reconciliation = rebuild_provisional_memory(
        memory_id=memory_id,
        artifact_ref=artifact.artifact_ref,
        artifact=loaded,
        receipts=(),
    )

    assert reconciliation.state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
    assert reconciliation.record is None
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_loader_rejects_filename_frontmatter_uuid_mismatch(tmp_path: Path) -> None:
    memory_id = UUID("12345678-1234-4abc-8def-1234567890ab")
    other_id = UUID("22345678-1234-4abc-8def-1234567890ab")
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="A copied file cannot acquire another identity.",
        created_by="human://owner",
        created_at="2026-07-15T00:00:00Z",
        provenance_event_ids=("event-1",),
    )
    path = tmp_path / "Memory" / "Provisional" / f"{other_id}.md"
    path.parent.mkdir(parents=True)
    path.write_text(render_provisional_markdown(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="physical provisional Markdown path"):
        load_provisional_markdown(path, vault_root=tmp_path)


@pytest.mark.parametrize(
    "filename",
    [
        "12345678-1234-4ABC-8DEF-1234567890AB.md",
        "{12345678-1234-4abc-8def-1234567890ab}.md",
    ],
)
def test_loader_rejects_noncanonical_uuid_filename_aliases(
    tmp_path: Path,
    filename: str,
) -> None:
    memory_id = UUID("12345678-1234-4abc-8def-1234567890ab")
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="UUID textual aliases are not canonical identity.",
        created_by="human://owner",
        created_at="2026-07-15T00:00:00Z",
        provenance_event_ids=("event-1",),
    )
    path = tmp_path / "Memory" / "Provisional" / filename
    path.parent.mkdir(parents=True)
    path.write_text(render_provisional_markdown(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="filename is not canonical"):
        load_provisional_markdown(path, vault_root=tmp_path)


@pytest.mark.parametrize(
    "injected_frontmatter",
    [
        "promotion_state: promoted\nauthority_receipt_ref: forged\n",
        "authority_state: canonical\n",
    ],
)
def test_loader_rejects_unmodeled_or_duplicate_authority_frontmatter(
    tmp_path: Path,
    injected_frontmatter: str,
) -> None:
    memory_id = UUID("12345678-1234-4abc-8def-1234567890ab")
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="Visible authority claims must never be ignored.",
        created_by="human://owner",
        created_at="2026-07-15T00:00:00Z",
        provenance_event_ids=("event-1",),
    )
    path = tmp_path / "Memory" / "Provisional" / f"{memory_id}.md"
    path.parent.mkdir(parents=True)
    rendered = render_provisional_markdown(artifact)
    path.write_text(
        rendered.replace("---\n", f"---\n{injected_frontmatter}", 1),
        encoding="utf-8",
    )

    with pytest.raises((ValueError, yaml.YAMLError)):
        load_provisional_markdown(path, vault_root=tmp_path)


@pytest.mark.parametrize(
    "replacement",
    [
        "provenance_event_ids: event-1",
        "provenance_event_ids: {event-1: forged}",
    ],
)
def test_loader_rejects_non_sequence_provenance(
    tmp_path: Path,
    replacement: str,
) -> None:
    memory_id = UUID("12345678-1234-4abc-8def-1234567890ab")
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="Provenance shape must be structural, not coerced.",
        created_by="human://owner",
        created_at="2026-07-15T00:00:00Z",
        provenance_event_ids=("event-1",),
    )
    path = tmp_path / "Memory" / "Provisional" / f"{memory_id}.md"
    path.parent.mkdir(parents=True)
    rendered = render_provisional_markdown(artifact)
    path.write_text(
        rendered.replace("provenance_event_ids:\n- event-1", replacement),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a non-empty string sequence"):
        load_provisional_markdown(path, vault_root=tmp_path)


def _recall_candidate(tmp_path: Path):  # type: ignore[no-untyped-def]
    from app.agent_memory.provisional_recall import retrieve_relevant_provisional

    vault = tmp_path / "vault"
    vault.mkdir()
    store = provisional_write_module.ProvisionalReceiptStore(tmp_path / "receipts.jsonl")
    provisional_write_module.write_provisional_memory(
        provisional_write_module.ProvisionalWriteRequest(
            scope_id="scope-personal",
            principal_id="principal-1",
            memory_type=MemoryType.POLICY_MEMORY,
            sensitivity=ProvisionalSensitivity.PRIVATE,
            content="Production recall guards cannot authorize tools.",
            provenance_event_ids=("event-guard",),
        ),
        vault_root=vault,
        receipt_store=store,
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    search = retrieve_relevant_provisional(
        "Which guards authorize tools?",
        vault_root=vault,
        receipt_store=store,
        active_scope_id="scope-personal",
    )
    return search.candidates[0]


def test_recall_path_invokes_low_trust_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent_memory import provisional_recall
    from app.agents.ask import graph as ask_graph
    from app.agents.ask.state import AgentState

    candidate = _recall_candidate(tmp_path)
    calls: list[str] = []
    real_inbound = provisional_recall.evaluate_admissibility
    real_outbound = provisional_recall.evaluate_provisional_memory_authority

    def _inbound(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        calls.append("admissibility")
        return real_inbound(*args, **kwargs)  # type: ignore[arg-type]

    def _outbound(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        calls.append("authority")
        return real_outbound(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(provisional_recall, "evaluate_admissibility", _inbound)
    monkeypatch.setattr(
        provisional_recall,
        "evaluate_provisional_memory_authority",
        _outbound,
    )

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ask_graph,
        "retrieve_relevant_provisional",
        lambda *args, **kwargs: provisional_recall.ProvisionalRecallSearch(
            candidates=(candidate,),
            excluded=(),
        ),
    )
    monkeypatch.setattr(ask_graph, "_active_recall_vault_root", lambda: tmp_path)
    monkeypatch.setattr(ask_graph, "_resolve_domain_scope", lambda: "scope-personal")
    monkeypatch.setenv("PROVISIONAL_RECALL_RECEIPTS_PATH", str(tmp_path / "recall.jsonl"))

    state = ask_graph._recall_node(  # noqa: SLF001 - verifies the production graph node
        AgentState(query="Which guards authorize tools?"),
        ask_settings=object(),
    )
    envelope = ask_graph.build_ask_envelope(state)
    provisional_bundle = next(
        item["metadata_bundle"]
        for item in envelope["retrieved_items"]
        if item["metadata_bundle"]["object_id"] == candidate.record.artifact_ref
    )

    assert state.recalled
    assert calls == ["admissibility", "authority"]
    assert provisional_bundle["authority_state"] == "noncanonical"
    assert provisional_bundle["memory_state"] == "unreviewed"
    assert provisional_bundle["provenance_event_ids"] == ["event-guard"]


def test_provisional_memory_cannot_reach_action_authority(tmp_path: Path) -> None:
    from app.agent_memory.provisional_recall import activate_provisional_recall

    result = activate_provisional_recall(
        _recall_candidate(tmp_path),
        consuming_authority=ConsumingAuthority.GOVERNED_EXECUTION,
        active_scope_id="scope-personal",
        use_right=RecallUseRight.ACTION_AUTHORIZING,
        activation_reason=ActivationReason.AUTHORITY_SIGNAL,
        citation_reference="proposal://quoted-but-not-authority",
        receipt_path=tmp_path / "recall.jsonl",
    )

    assert result.admitted is False
    assert result.may_answer is False
    assert result.may_propose is False
    assert result.may_write is False
    assert "provisional_memory_never_action_authoritative" in (
        result.authority_decision.blocked_reasons
    )
