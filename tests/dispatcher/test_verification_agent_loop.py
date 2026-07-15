from __future__ import annotations

import pytest

from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from tests.dispatcher.verification_helpers import ledger, request


def test_pr_wide_two_plus_two_budget_and_independent_rereview(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(state, run.run_id, holder="host", lease_id=claimed.lease_id, strongest_capability="sol")
    context = {"head": run.head_sha}
    loop.repair(finding_id="F1", session_id="fix-1", capability="terra", reasoning_effort="high", context=context, outcome="fixed")
    with pytest.raises(ValueError):
        loop.review(session_id="fix-1", capability="terra", reasoning_effort="high", context=context, outcome="clean")
    loop.review(session_id="review-1", capability="terra", reasoning_effort="high", context=context, outcome="blocking")
    loop.repair(finding_id="F2", session_id="fix-2", capability="terra", reasoning_effort="high", context=context, outcome="fixed")
    with pytest.raises(ValueError):
        loop.repair(finding_id="F3", session_id="fix-3", capability="terra", reasoning_effort="high", context=context, outcome="fixed")
    loop.review(session_id="review-2", capability="terra", reasoning_effort="high", context=context, outcome="blocking")
    loop.repair(finding_id="F3", session_id="fix-3", capability="sol", reasoning_effort="xhigh", context=context, outcome="fixed", strongest=True)
    loop.review(session_id="review-3", capability="sol", reasoning_effort="xhigh", context=context, outcome="blocking")
    loop.repair(finding_id="F4", session_id="fix-4", capability="sol", reasoning_effort="xhigh", context=context, outcome="fixed", strongest=True)
    with pytest.raises(ValueError):
        loop.repair(finding_id="F5", session_id="fix-5", capability="sol", reasoning_effort="xhigh", context=context, outcome="fixed", strongest=True)


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
        "options": ["hold", "authorize"],
        "recommended_option": "hold",
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
    loop.repair(finding_id="F1", session_id="coordinator", capability="terra", reasoning_effort="high", context=context, outcome="fixed")
    with pytest.raises(ValueError):
        loop.review(session_id="coordinator", capability="terra", reasoning_effort="high", context=context, outcome="clean")
    assert loop.review(session_id="fresh-review", capability="terra", reasoning_effort="high", context=context, outcome="clean") == 1
