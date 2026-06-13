from __future__ import annotations

from companion_ui.workspace.memory_review_drawer import (
    MEMORY_REVIEW_CALLOUT,
    materialized_memory_surface,
    memory_authority_posture_surface,
    recall_provenance_surface,
)


def test_materialized_memory_shows_provenance_and_agent_label() -> None:
    html = materialized_memory_surface(
        {
            "title": "Explicit semantic memory",
            "artifact_path": "Agent Memory/explicit-semantic-memory.md",
            "artifact_class": "agentic_memory",
            "agent_promoted": True,
            "labels": ["agent-promoted-memory"],
            "promoted_from_candidate_id": "candidate-123",
            "source_refs": ["note:source.md", "session:2026-06-13T09:00:00Z"],
            "derived_from": "vault:source.md",
            "generated_by": "companion_agent",
            "decided_by": "companion-ui:reviewer",
            "decided_at": "2026-06-13T09:01:00Z",
        }
    )

    assert 'data-testid="materialized-memory-surface"' in html
    assert 'data-agent-promoted="true"' in html
    assert 'data-human-authored="false"' in html
    assert "Agent-promoted memory" in html
    assert "agent-promoted-memory" in html
    assert "candidate-123" in html
    assert "note:source.md" in html
    assert "session:2026-06-13T09:00:00Z" in html
    assert "companion-ui:reviewer" in html


def test_recall_provenance_is_rendered() -> None:
    html = recall_provenance_surface(
        {
            "why_now": "Current answer needs the user's concise-summary preference.",
            "authority_limits": [
                "memory_is_supporting_input_not_source_of_truth",
                "does_not_authorize_writeback",
            ],
            "receipt_reference": "recall-receipt-123",
            "may_answer": True,
            "may_propose": True,
            "may_write": False,
        }
    )

    assert 'data-testid="memory-recall-provenance"' in html
    assert 'data-may-answer="true"' in html
    assert 'data-may-propose="true"' in html
    assert 'data-may-write="false"' in html
    assert "Current answer needs the user" in html
    assert "memory_is_supporting_input_not_source_of_truth" in html
    assert "does_not_authorize_writeback" in html
    assert "recall-receipt-123" in html


def test_unreviewed_memory_posture_visible() -> None:
    html = memory_authority_posture_surface(
        {
            "authority": "non_authoritative",
            "authority_role": "candidate",
            "review_posture": "unreviewed",
            "semantic_authority": False,
        }
    )

    assert 'data-testid="memory-authority-posture"' in html
    assert 'data-authority="non_authoritative"' in html
    assert 'data-authority-role="candidate"' in html
    assert 'data-semantic-authority="false"' in html
    assert MEMORY_REVIEW_CALLOUT in html
    assert "unreviewed" in html
