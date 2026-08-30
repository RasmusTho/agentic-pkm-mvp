from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import jsonschema
import pytest

from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import (
    sanitize_verification_closer_receipt,
    validate_verification_closer_receipt,
)
from app.dispatcher.verification_dispatch import (
    REPAIR_INTENT_ATTEMPT_KIND,
    VerificationDispatchLedger,
    build_repair_transition_evidence,
    plan_repair_progress_intents,
)
from tests.dispatcher.builderops_verification_fakes import FakeBuilderOpsClient
from tests.dispatcher.verification_helpers import HEAD, REPO, ledger, request


FINDING = "progress-admission"
DOMAIN = "review_code_correctness"
MECHANISM = "verification-repair-progress"
SECOND_HEAD = "b" * 40
SEED_HEAD = "0" * 40
MECHANISM_PATH = "app/dispatcher/verification_dispatch.py"
MECHANISM_PATH_SHA = hashlib.sha256(MECHANISM_PATH.encode()).hexdigest()


def _transition(
    base_head: str,
    repaired_head: str,
    *,
    path: str = MECHANISM_PATH,
    blob_sha: str | None = None,
    extra_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    return build_repair_transition_evidence(
        base_head_sha=base_head,
        repaired_head_sha=repaired_head,
        commits=[repaired_head],
        files=[
            {
                "path_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                "previous_path_sha256": None,
                "status": "modified",
                "blob_sha": blob_sha or repaired_head,
            }
            for candidate in (path, *extra_paths)
        ],
    )


def _repair_event(intent_id: str) -> dict[str, object]:
    return {
        "kind": "repair",
        "session_id": "repair-2",
        "capability": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "outcome": "fixed",
        "finding_id": FINDING,
        "failure_domain": DOMAIN,
        "mechanism_id": MECHANISM,
        "progress_intent_id": intent_id,
        "strongest": False,
    }


def _exercise_progress_intent_parity(
    state: Any,
    restart: Callable[[], Any],
) -> None:
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    holder = claimed.claimed_by
    lease_id = claimed.lease_id
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder=holder,
        lease_id=lease_id,
    )
    context = {"head": HEAD}
    loop.repair(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="repair-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
        transition_evidence=_transition(
            SEED_HEAD,
            HEAD,
            extra_paths=("docs/unrelated.md",),
        ),
    )
    loop.review(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="review-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context=context,
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )

    intent = plan_repair_progress_intents(
        state.attempts(run.run_id),
        current_head_sha=HEAD,
        validation_sha256="1" * 64,
    )[0]
    intent_id = str(intent["intent_id"])
    with pytest.raises(ValueError, match="ownership mismatch"):
        state.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            intent_id,
            "deterministic",
            "none",
            context,
            "admitted",
            intent,
            holder=holder,
            lease_id="stale-lease",
            idempotency_key=intent_id,
        )
    assert (
        state.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            intent_id,
            "deterministic",
            "none",
            context,
            "admitted",
            intent,
            holder=holder,
            lease_id=lease_id,
            idempotency_key=intent_id,
        )
        == 1
    )
    assert (
        state.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            intent_id,
            "deterministic",
            "none",
            context,
            "admitted",
            intent,
            holder=holder,
            lease_id=lease_id,
            idempotency_key=intent_id,
        )
        == 1
    )

    restarted = restart()
    assert restarted.attempts(run.run_id)[-1]["receipt"] == intent
    restarted.rebind_head(
        run.run_id,
        SECOND_HEAD,
        expected_head_sha=HEAD,
        observed_repository=REPO,
        observed_pr_number=3603,
        observed_head_sha=SECOND_HEAD,
        holder=holder,
        lease_id=lease_id,
    )
    restarted_loop = VerificationAgentLoop(
        restarted,
        run.run_id,
        holder=holder,
        lease_id=lease_id,
    )
    repair_context = {
        "head": SECOND_HEAD,
        "progress_validation_sha256": "2" * 64,
        "repair_transition_evidence": _transition(HEAD, SECOND_HEAD),
    }
    event = _repair_event(intent_id)
    restarted_loop.apply_events([event], context=repair_context)
    restarted_loop.apply_events([event], context=repair_context)
    attempts = restarted.attempts(run.run_id)
    repaired = [row for row in attempts if row["kind"] in {"standard_repair", "escalated_repair"}]
    assert len(repaired) == 2
    evidence = repaired[-1]["receipt"]["progress_evidence"]
    assert evidence["intent_id"] == intent_id
    assert evidence["reviewed_head_sha"] == HEAD
    assert evidence["repaired_head_sha"] == SECOND_HEAD

    restarted_loop.review(
        finding_id=FINDING,
        failure_domain=DOMAIN,
        mechanism_id=MECHANISM,
        session_id="review-2",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context=repair_context,
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )
    restarted.backoff(
        run.run_id,
        {"reason": "takeover-test"},
        "2000-01-01T00:00:00+00:00",
        holder=holder,
        lease_id=lease_id,
    )
    taken_over = restarted.claim(run.run_id, "verification-host")
    assert taken_over.claimed_by is not None
    assert taken_over.lease_id is not None
    assert taken_over.lease_id != lease_id
    next_intent = plan_repair_progress_intents(
        restarted.attempts(run.run_id),
        current_head_sha=SECOND_HEAD,
        validation_sha256="3" * 64,
    )[0]
    next_intent_id = str(next_intent["intent_id"])
    assert (
        restarted.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            next_intent_id,
            "deterministic",
            "none",
            {"head": SECOND_HEAD},
            "admitted",
            next_intent,
            holder=taken_over.claimed_by,
            lease_id=taken_over.lease_id,
            idempotency_key=next_intent_id,
        )
        == 2
    )
    with pytest.raises(ValueError, match="ownership mismatch"):
        restarted.record_attempt(
            run.run_id,
            REPAIR_INTENT_ATTEMPT_KIND,
            next_intent_id,
            "deterministic",
            "none",
            {"head": SECOND_HEAD},
            "admitted",
            next_intent,
            holder=holder,
            lease_id=lease_id,
            idempotency_key=next_intent_id,
        )


def test_progress_intent_round_trips_schema_and_consumer_without_authority_loss() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    intent_id = "repair-intent-" + "a" * 24
    receipt = {
        "verdict": "blocked",
        "head_sha": HEAD,
        "summary": "repair requires independent review",
        "receipt_ids": [],
        "retry_after": None,
        "review_events": [
            {
                **_repair_event(intent_id),
                "session_id": "repair-session",
            }
        ],
        "human_exception": None,
    }

    validate_verification_closer_receipt(receipt, schema)
    sanitized = sanitize_verification_closer_receipt(receipt)
    validate_verification_closer_receipt(sanitized, schema)
    assert sanitized["review_events"][0]["progress_intent_id"] == intent_id
    assert sanitized["review_events"][0]["mechanism_path_sha256"] is None

    blocking_review = json.loads(json.dumps(receipt))
    blocking_review["review_events"][0].update(
        {
            "kind": "review",
            "outcome": "blocking",
            "progress_intent_id": None,
            "mechanism_path_sha256": [MECHANISM_PATH_SHA],
            "strongest": None,
        }
    )
    validate_verification_closer_receipt(blocking_review, schema)
    sanitized_review = sanitize_verification_closer_receipt(blocking_review)
    validate_verification_closer_receipt(sanitized_review, schema)
    assert sanitized_review["review_events"][0][
        "mechanism_path_sha256"
    ] == [MECHANISM_PATH_SHA]

    unprojected_review = json.loads(json.dumps(blocking_review))
    unprojected_review["review_events"][0]["mechanism_path_sha256"] = None
    with pytest.raises(
        jsonschema.ValidationError,
        match="requires a mechanism path projection",
    ):
        validate_verification_closer_receipt(unprojected_review, schema)

    malformed = json.loads(json.dumps(receipt))
    malformed["review_events"][0]["progress_intent_id"] = "repair-intent-not-canonical"
    with pytest.raises(jsonschema.ValidationError):
        validate_verification_closer_receipt(malformed, schema)


def test_sqlite_progress_intent_is_fenced_monotonic_and_replay_safe(tmp_path) -> None:
    state = ledger(tmp_path)
    _exercise_progress_intent_parity(
        state,
        lambda: VerificationDispatchLedger(state.store),
    )


def test_builderops_progress_intent_is_fenced_monotonic_and_replay_safe() -> None:
    api = FakeBuilderOpsClient()
    state = BuilderOpsVerificationLedger(api, repository=REPO)
    _exercise_progress_intent_parity(
        state,
        lambda: BuilderOpsVerificationLedger(api, repository=REPO),
    )


@pytest.mark.parametrize(
    ("validation_after", "transition_path", "blob_sha", "message"),
    (
        ("1" * 64, MECHANISM_PATH, None, "progress evidence is unchanged"),
        (
            "2" * 64,
            "docs/unrelated.md",
            None,
            "does not change the reviewed mechanism",
        ),
        ("2" * 64, MECHANISM_PATH, HEAD, "progress evidence is unchanged"),
    ),
)
def test_repeated_repair_rejects_non_progressing_server_evidence(
    tmp_path,
    validation_after: str,
    transition_path: str,
    blob_sha: str | None,
    message: str,
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "verification-host")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    loop = VerificationAgentLoop(
        state,
        run.run_id,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    binding = {
        "finding_id": FINDING,
        "failure_domain": DOMAIN,
        "mechanism_id": MECHANISM,
    }
    loop.repair(
        **binding,
        session_id="repair-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context={"head": HEAD},
        outcome="fixed",
        transition_evidence=_transition(
            SEED_HEAD,
            HEAD,
            extra_paths=("docs/unrelated.md",),
        ),
    )
    loop.review(
        **binding,
        session_id="review-1",
        capability="gpt-5.6-terra",
        reasoning_effort="high",
        context={"head": HEAD},
        outcome="blocking",
        mechanism_path_sha256=[MECHANISM_PATH_SHA],
    )
    intent = plan_repair_progress_intents(
        state.attempts(run.run_id),
        current_head_sha=HEAD,
        validation_sha256="1" * 64,
    )[0]
    intent_id = str(intent["intent_id"])
    state.record_attempt(
        run.run_id,
        REPAIR_INTENT_ATTEMPT_KIND,
        intent_id,
        "deterministic",
        "none",
        {"head": HEAD},
        "admitted",
        intent,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
        idempotency_key=intent_id,
    )
    state.rebind_head(
        run.run_id,
        SECOND_HEAD,
        expected_head_sha=HEAD,
        observed_repository=REPO,
        observed_pr_number=3603,
        observed_head_sha=SECOND_HEAD,
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
    )
    with pytest.raises(ValueError, match=message):
        loop.apply_events(
            [_repair_event(intent_id)],
            context={
                "head": SECOND_HEAD,
                "progress_validation_sha256": validation_after,
                "repair_transition_evidence": _transition(
                    HEAD,
                    SECOND_HEAD,
                    path=transition_path,
                    blob_sha=blob_sha,
                ),
            },
        )

    assert [
        row["kind"]
        for row in state.attempts(run.run_id)
        if row["kind"] in {"standard_repair", "escalated_repair"}
    ] == ["standard_repair"]
