from __future__ import annotations

import hashlib

import pytest

from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_dispatch import (
    REPAIR_INTENT_ATTEMPT_KIND,
    build_repair_transition_evidence,
    plan_repair_progress_intents,
)
from tests.dispatcher.verification_helpers import ledger, request

MECHANISM_PATH = "app/dispatcher/verification_agent_loop.py"
MECHANISM_PATH_SHA = hashlib.sha256(MECHANISM_PATH.encode()).hexdigest()
OTHER_MECHANISM_PATH_SHA = hashlib.sha256(
    b"app/dispatcher/verification_dispatch.py"
).hexdigest()


def _transition(base_head: str, repaired_head: str) -> dict[str, object]:
    return build_repair_transition_evidence(
        base_head_sha=base_head,
        repaired_head_sha=repaired_head,
        commits=[repaired_head],
        files=[
            {
                "path_sha256": MECHANISM_PATH_SHA,
                "previous_path_sha256": None,
                "status": "modified",
                "blob_sha": repaired_head,
            }
        ],
    )


def test_distinct_findings_have_no_numeric_stop_and_require_rereview(
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
            mechanism_path_sha256=[MECHANISM_PATH_SHA],
        )


def test_v2_blocking_review_requires_projection_before_ledger_mutation(
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
    )
    repair_event = {
        "kind": "repair",
        "finding_id": "F1",
        "failure_domain": "review_code_correctness",
        "mechanism_id": "parser",
        "session_id": "repair-1",
        "capability": "terra",
        "reasoning_effort": "high",
        "outcome": "fixed",
        "strongest": False,
    }
    loop.apply_events([repair_event], context={"head": run.head_sha})

    with pytest.raises(ValueError, match="requires a mechanism path projection"):
        loop.review(
            finding_id="F1",
            failure_domain="review_code_correctness",
            mechanism_id="parser",
            session_id="review-1",
            capability="terra",
            reasoning_effort="high",
            context={"head": run.head_sha},
            outcome="blocking",
        )
    assert len(state.attempts(run.run_id)) == 1

    blocking_event = {
        "kind": "review",
        "finding_id": "F1",
        "failure_domain": "review_code_correctness",
        "mechanism_id": "parser",
        "session_id": "review-1",
        "capability": "terra",
        "reasoning_effort": "high",
        "outcome": "blocking",
        "strongest": None,
    }
    with pytest.raises(ValueError, match="requires a mechanism path projection"):
        loop.apply_events([blocking_event], context={"head": run.head_sha})
    assert len(state.attempts(run.run_id)) == 1


def test_same_blocking_round_cannot_replace_mechanism_path_projection(
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
    )
    loop.repair(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="parser",
        session_id="repair-1",
        capability="terra",
        reasoning_effort="high",
        context={"head": run.head_sha},
        outcome="fixed",
    )
    review = {
        "finding_id": "F1",
        "failure_domain": "review_code_correctness",
        "mechanism_id": "parser",
        "session_id": "review-round",
        "capability": "terra",
        "reasoning_effort": "high",
        "context": {"head": run.head_sha},
        "outcome": "blocking",
    }
    loop.review(**review, mechanism_path_sha256=[MECHANISM_PATH_SHA])

    with pytest.raises(ValueError, match="blocking review requires repair"):
        loop.review(
            **review,
            mechanism_path_sha256=[OTHER_MECHANISM_PATH_SHA],
        )
    attempts = state.attempts(run.run_id)
    assert len(attempts) == 2
    assert attempts[-1]["receipt"]["mechanism_path_sha256"] == [
        MECHANISM_PATH_SHA
    ]

def test_repeated_non_converging_repair_requires_progress_evidence(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(state, run.run_id, holder="host", lease_id=claimed.lease_id)
    context = {"head": run.head_sha}
    loop.repair(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="parser",
        session_id="fix-1",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
        transition_evidence=_transition("0" * 40, run.head_sha),
    )
    loop.review(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="parser",
        session_id="review-1",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )
    with pytest.raises(ValueError, match="pre-launch progress intent"):
        loop.repair(
            finding_id="F1",
            failure_domain="review_code_correctness",
            mechanism_id="parser",
            session_id="fix-2",
            capability="terra",
            reasoning_effort="high",
            context=context,
            outcome="fixed",
        )


def test_progressing_repair_rounds_have_no_numeric_stop_and_require_rereview(tmp_path) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    loop = VerificationAgentLoop(state, run.run_id, holder="host", lease_id=claimed.lease_id)
    context = {"head": run.head_sha}
    loop.repair(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="parser",
        session_id="fix-0",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
        transition_evidence=_transition("0" * 40, run.head_sha),
    )
    loop.review(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="parser",
        session_id="review-0",
        capability="terra",
        reasoning_effort="high",
        context=context,
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )
    for index in range(1, 6):
        current = state.get(run.run_id)
        assert current is not None
        intents = plan_repair_progress_intents(
            state.attempts(run.run_id),
            current_head_sha=current.head_sha,
            validation_sha256=f"{index:064x}",
        )
        assert len(intents) == 1
        intent = intents[0]
        state.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            str(intent["intent_id"]),
            "deterministic",
            "none",
            {"head": current.head_sha},
            "admitted",
            intent,
            holder="host",
            lease_id=claimed.lease_id,
            idempotency_key=str(intent["intent_id"]),
        )
        repaired_head = f"{index + 100:040x}"
        state.rebind_head(
            run.run_id,
            repaired_head,
            expected_head_sha=current.head_sha,
            observed_repository=run.repository,
            observed_pr_number=run.pr_number,
            observed_head_sha=repaired_head,
            holder="host",
            lease_id=claimed.lease_id,
        )
        context = {"head": repaired_head}
        loop.repair(
            finding_id="F1",
            failure_domain="review_code_correctness",
            mechanism_id="parser",
            session_id=f"fix-{index}",
            capability="terra",
            reasoning_effort="high",
            context=context,
            outcome="fixed",
            progress_intent_id=str(intent["intent_id"]),
            validation_sha256=f"{index + 200:064x}",
            transition_evidence=_transition(current.head_sha, repaired_head),
        )
        loop.review(
            finding_id="F1",
            failure_domain="review_code_correctness",
            mechanism_id="parser",
            session_id=f"review-{index}",
            capability="terra",
            reasoning_effort="high",
            context=context,
            outcome="blocking",
            mechanism_path_sha256=[MECHANISM_PATH_SHA],
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
                    "mechanism_path_sha256": [MECHANISM_PATH_SHA],
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
