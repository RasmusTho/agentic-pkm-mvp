from __future__ import annotations

import pytest

from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from tests.dispatcher.verification_helpers import ledger, request


def test_progressing_repair_rounds_have_no_numeric_stop_and_require_rereview(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder="host",
        lease_id=claimed.lease_id,
        strongest_capability="sol",
    )
    context = {"head": run.head_sha}
    for index in range(1, 7):
        strongest = index >= 4
        capability = "sol" if strongest else "terra"
        reasoning = "xhigh" if strongest else "high"
        expected_ordinal = index - 3 if strongest else index
        assert loop.repair(
            finding_id=f"F{index}",
            failure_domain="review_code_correctness",
            mechanism_id="parser",
            session_id=f"fix-{index}",
            capability=capability,
            reasoning_effort=reasoning,
            context=context,
            outcome="fixed",
            strongest=strongest,
        ) == expected_ordinal
        with pytest.raises(ValueError, match="fresh blocking review"):
            loop.repair(
                finding_id=f"F{index}-unreviewed",
                failure_domain="review_code_correctness",
                mechanism_id="parser",
                session_id=f"fix-{index}-unreviewed",
                capability=capability,
                reasoning_effort=reasoning,
                context=context,
                outcome="fixed",
                strongest=strongest,
            )
        loop.review(
            finding_id=f"F{index}",
            failure_domain="review_code_correctness",
            mechanism_id="parser",
            session_id=f"review-{index}",
            capability=capability,
            reasoning_effort=reasoning,
            context=context,
            outcome="blocking",
        )


def test_event_batch_allows_repairs_beyond_legacy_two_plus_two_budget(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder="host",
        lease_id=claimed.lease_id,
        strongest_capability="sol",
    )
    events: list[dict[str, object]] = []
    for index in range(1, 7):
        strongest = index >= 4
        capability = "sol" if strongest else "terra"
        reasoning = "xhigh" if strongest else "high"
        events.extend(
            [
                {
                    "kind": "repair",
                    "session_id": f"fix-{index}",
                    "capability": capability,
                    "reasoning_effort": reasoning,
                    "outcome": "fixed",
                    "finding_id": f"F{index}",
                    "failure_domain": "review_code_correctness",
                    "mechanism_id": "parser",
                    "strongest": strongest,
                },
                {
                    "kind": "review",
                    "session_id": f"review-{index}",
                    "capability": capability,
                    "reasoning_effort": reasoning,
                    "outcome": "blocking",
                    "finding_id": f"F{index}",
                    "failure_domain": "review_code_correctness",
                    "mechanism_id": "parser",
                },
            ]
        )

    with pytest.raises(ValueError, match="fresh blocking review"):
        loop.apply_events([events[0], events[2]], context={"head": run.head_sha})
    assert state.attempts(run.run_id) == []

    loop.apply_events(events, context={"head": run.head_sha})

    repairs = [
        attempt
        for attempt in state.attempts(run.run_id)
        if attempt["kind"] in {"standard_repair", "escalated_repair"}
    ]
    assert len(repairs) == 6


def test_tcd_can_select_strongest_capability_before_two_standard_attempts(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder="host",
        lease_id=claimed.lease_id,
        strongest_capability="sol",
    )

    assert loop.repair(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="parser",
        session_id="fix-1",
        capability="sol",
        reasoning_effort="xhigh",
        context={"head": run.head_sha},
        outcome="fixed",
        strongest=True,
    ) == 1


def test_terminal_stop_routes_one_deduplicated_owner_decision(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(state, run.run_id, holder="host", lease_id=claimed.lease_id)
    packet = {
        "failure_class": "authority-critical",
        "original_intent": "verify and close",
        "current_state": "authority is missing",
        "tried_actions": ["checked the governing contract"],
        "evidence": ["issue #3603"],
        "why_unsafe": "continuation would expand authority",
        "options": [
            {"id": "hold", "label": "Hold", "consequence": "delivery waits"},
            {
                "id": "authorize",
                "label": "Authorize",
                "consequence": "delivery continues",
            },
        ],
        "no_action_option": "hold",
        "recommended_option": "hold",
        "recommendation_rationale": "authority has not been granted",
        "consequence_of_doing_nothing": "the delivery remains blocked",
    }
    first = loop.stop("authority-critical", packet)
    assert first.startswith("vexception-")
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_exceptions").fetchone()[0] == 1


def test_terminal_stop_rejects_invented_class_or_incomplete_packet(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(
        state, run.run_id, holder="host", lease_id=claimed.lease_id
    )

    with pytest.raises(ValueError, match="invalid Human Exception"):
        loop.stop(
            "coordinator_needs_human",
            {"failure_class": "coordinator_needs_human", "options": ["hold"]},
        )


def test_coordinator_resumes_but_reviewers_start_fresh(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(state, run.run_id, holder="host", lease_id=claimed.lease_id)
    context = {"head": run.head_sha}
    loop.repair(finding_id="F1", failure_domain="review_code_correctness", mechanism_id="parser", session_id="coordinator", capability="terra", reasoning_effort="high", context=context, outcome="fixed")
    with pytest.raises(ValueError):
        loop.review(session_id="coordinator", capability="terra", reasoning_effort="high", context=context, outcome="clean")
    assert loop.review(session_id="fresh-review", capability="terra", reasoning_effort="high", context=context, outcome="clean") == 1
