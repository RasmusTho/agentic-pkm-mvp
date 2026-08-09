from __future__ import annotations

import app.dispatcher.cli as dispatcher_cli
import pytest

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_consumer import (
    VerificationConsumer,
    context_pack,
)
from app.dispatcher.verification_dispatch import (
    VerificationSubscriptionBusy,
    _authenticated_verification_request,
    _live_observed_verification_request,
)
from tests.dispatcher.builderops_verification_fakes import (
    FakeBuilderOpsClient,
    FakeVerificationOutbox,
)
from tests.dispatcher.test_verification_consumer import (
    Auth,
    GREEN,
    Launcher,
    Truth,
    _merge_comments,
    _merge_plan,
    _open_neutralized_recovery_evidence,
    eligible_pr,
    merged_pr,
)
from tests.dispatcher.verification_helpers import HEAD, REPO, request

NEXT_HEAD = "b" * 40


def test_restart_resumes_from_api_receipts_without_duplicate_attempt() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    first = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    run = first.ingest(request())
    claimed = first.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    ordinal = first.record_attempt(
        run.run_id,
        "verification",
        "session-1",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "passed",
        {"head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="verification-success",
    )
    operation_key = first.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={"repository": REPO, "pr_number": 3603, "head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="merge-after-verification",
    )
    outbox.claims[operation_key][
        "expires_at"
    ] = "2000-01-01T00:00:00+00:00"

    restarted = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    recovered = restarted.recover_effect(
        operation_key,
        run_id=run.run_id,
        effect_type="model.verification_coordinator",
    )
    restarted.finish_effect(
        operation_key,
        observed_applied=False,
        evidence={"readback": "not_merged", "head_sha": HEAD},
    )
    replayed_ordinal = restarted.record_attempt(
        run.run_id,
        "verification",
        "session-1",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "passed",
        {"head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="verification-success",
    )

    assert replayed_ordinal == ordinal == 1
    assert len(api.attempt_rows[run.run_id]) == 1
    assert recovered["operation_key"] == operation_key
    assert outbox.calls[-2:] == ["recover", "reconcile"]


def test_api_consumer_recovery_requires_a_fresh_task_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        VerifiedLauncher(),
        holder="verification-host",
    )
    run = consumer.consume(request())
    monkeypatch.setattr(consumer, "_lease_is_live", lambda _run: False)
    monkeypatch.setattr(
        ledger,
        "claim",
        lambda _run_id, _holder: run,
    )
    recover_calls = outbox.calls.count("recover")

    with pytest.raises(
        VerificationSubscriptionBusy, match="fresh recovery fence"
    ):
        consumer.recover(run.run_id)

    assert outbox.calls.count("recover") == recover_calls


def test_api_ledger_marks_every_active_recovery_as_new_fence_required() -> None:
    api = FakeBuilderOpsClient()
    ledger = BuilderOpsVerificationLedger(api, repository=REPO)
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    task = api.tasks[run.run_id]
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    recovered = ledger.claim(run.run_id, "verification-host")

    claim_calls = [
        values for name, values in api.calls if name == "claim_task"
    ]
    assert claim_calls[0]["require_new_fence"] is False
    assert claim_calls[1]["require_new_fence"] is True
    assert recovered.lease_id != claimed.lease_id


class FailingIntentClient(FakeBuilderOpsClient):
    def transition_task(self, **values):
        if values.get("outbox") is not None:
            raise RuntimeError("simulated pre-effect commit failure")
        return super().transition_task(**values)


class CrashBeforeFirstTaskCompletionClient(FakeBuilderOpsClient):
    def __init__(self) -> None:
        super().__init__()
        self.crash_before_completion = True

    def complete_task(self, **values):
        if self.crash_before_completion:
            self.crash_before_completion = False
            raise SystemExit(
                "simulated crash after dead letter before task completion"
            )
        return super().complete_task(**values)


class CrashAfterThreadStartLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        if on_thread_started:
            on_thread_started("01900000-0000-7000-8000-000000000099")
        raise RuntimeError("simulated response loss after thread start")


class CrashBeforeThreadStartLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        raise SystemExit(
            "simulated host crash before thread-start persistence"
        )


class LostReconcileResponseOutbox(FakeVerificationOutbox):
    def reconcile(
        self,
        claim,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence,
    ):
        super().reconcile(
            claim,
            observed_applied=observed_applied,
            terminal_unknown=terminal_unknown,
            evidence=evidence,
        )
        raise RuntimeError("simulated reconciliation response loss")


class LostUnknownResponseOutbox(FakeVerificationOutbox):
    def mark_unknown(self, claim, *, detail: str):
        super().mark_unknown(claim, detail=detail)
        raise RuntimeError("simulated mark-unknown response loss")


class CrashAfterDurableAttemptOutbox(FakeVerificationOutbox):
    def mark_unknown(self, claim, *, detail: str):
        super().mark_unknown(claim, detail=detail)
        raise SystemExit(
            "simulated host crash after durable model attempt"
        )


class CrashAfterSucceededReconciliationOutbox(FakeVerificationOutbox):
    def reconcile(
        self,
        claim,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence,
    ):
        super().reconcile(
            claim,
            observed_applied=observed_applied,
            terminal_unknown=terminal_unknown,
            evidence=evidence,
        )
        raise SystemExit(
            "simulated crash after succeeded model reconciliation"
        )


class InvalidClaimOutbox(FakeVerificationOutbox):
    def __init__(self, api, *, failure: str) -> None:
        super().__init__(api)
        self.failure = failure

    def claim(self, operation_key: str):
        claim = super().claim(operation_key)
        if self.failure == "expired":
            claim["expires_at"] = "2000-01-01T00:00:00+00:00"
        elif self.failure == "ineligible":
            claim["effect_eligible"] = False
        return claim


class VerifiedLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        session = (
            resume_session_id
            or "01900000-0000-7000-8000-000000000088"
        )
        if on_thread_started:
            on_thread_started(session)
        return session, {
            "verdict": "verified",
            "head_sha": HEAD,
            "summary": "review gates passed; host owns merge",
            "receipt_ids": ["host-fenced-review"],
            "retry_after": None,
            "review_events": [
                {
                    "kind": "review",
                    "session_id": "host-fenced-review",
                    "capability": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                    "outcome": "clean",
                    "finding_id": None,
                    "failure_domain": None,
                    "mechanism_id": None,
                    "strongest": True,
                }
            ],
            "human_exception": None,
        }


@pytest.mark.parametrize(
    "recovery_shape", ("merged", "open-neutralized")
)
@pytest.mark.parametrize("outbox_state", ("claimed", "unknown"))
def test_special_merge_recovery_reconciles_retained_model_effect(
    recovery_shape: str,
    outbox_state: str,
) -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    session_id = "01900000-0000-7000-8000-000000000077"
    running = ledger.start(
        run.run_id,
        "verification-host",
        claimed.lease_id,
        session_id,
        context_pack(
            claimed,
            eligible_pr(),
            repair_budget=ledger.repair_budget_projection(run.run_id),
        ),
    )
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={
            "repository": running.repository,
            "governing_issue": running.request["linked_issue"],
            "pr_number": running.pr_number,
            "head_sha": running.current_head_sha,
            "workflow_identity": running.request.get("source_workflow"),
            "secret_ref": "host-secret:builderops/model-session",
            "scopes": ["model:execute"],
        },
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="retained-special-model-effect",
    )
    if outbox_state == "unknown":
        ledger.abandon_effect(
            operation_key, detail="simulated process loss"
        )
    task = api.tasks[run.run_id]
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    outbox.claims[operation_key][
        "expires_at"
    ] = "2000-01-01T00:00:00+00:00"

    if recovery_shape == "merged":
        plan = _merge_plan(HEAD, run_id=run.run_id)
        live_pr = merged_pr(body=plan["neutralized_body"])
        comments = _merge_comments(
            live_pr, phase="prepared", run_id=run.run_id
        )
    else:
        plan, live_pr, comments = (
            _open_neutralized_recovery_evidence(run_id=run.run_id)
        )

    class RecoveryTruth(Truth):
        recovery_comments = comments

        def pull_request_comments(self, repository, pr_number):
            return self.recovery_comments

    truth = RecoveryTruth(live_pr, GREEN)

    class RecoveryLauncher(Launcher):
        def launch(
            self,
            context_pack,
            *,
            resume_session_id=None,
            on_thread_started=None,
            on_heartbeat=None,
        ):
            if recovery_shape == "open-neutralized":
                truth.pr = eligible_pr(body=plan["original_body"])
                truth._last_pr = truth.pr
                return super().launch(
                    context_pack,
                    resume_session_id=resume_session_id,
                    on_thread_started=on_thread_started,
                    on_heartbeat=on_heartbeat,
                )
            return super().launch(
                context_pack,
                resume_session_id=resume_session_id,
                on_thread_started=on_thread_started,
                on_heartbeat=on_heartbeat,
            )

    launcher = RecoveryLauncher()
    recovered = VerificationConsumer(
        ledger,
        truth,
        Auth(),
        launcher,
        holder="verification-host",
    ).recover(run.run_id)

    assert recovered.status == (
        "failed" if recovery_shape == "merged" else "needs_human"
    ), recovered
    if recovery_shape == "merged":
        assert (
            recovered.stop_reason
            == "receipt_live_truth_closed_unmerged_or_merged"
        )
    assert launcher.calls[0][1] == session_id
    assert list(outbox.states) == [operation_key]
    assert outbox.states[operation_key] == "succeeded"
    assert "recover" in outbox.calls


def test_fenced_attempt_commit_gates_external_effect() -> None:
    api = FailingIntentClient()
    launcher = Launcher()
    consumer = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api,
            repository=REPO,
            effect_outbox=FakeVerificationOutbox(api),
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        launcher,
        holder="verification-host",
    )

    result = consumer.consume(request())

    assert result.status == "backoff"
    assert launcher.calls == []


def test_api_consumer_persists_verified_merge_ready_without_github_effect() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    launcher = VerifiedLauncher()
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        launcher,
        holder="verification-host",
    )

    result = consumer.consume(request())

    assert result.status == "running"
    marker = ledger.merge_ready_receipt(result.run_id)
    assert marker is not None
    assert marker["head_sha"] == HEAD
    assert marker["closing_issues"] == [3603]
    assert marker["final_review_rounds"] == 1
    assert launcher.calls[0][0]["merge_execution_mode"] == (
        "host_fenced_executor"
    )
    assert not any(
        isinstance(values.get("outbox"), dict)
        and values["outbox"].get("effect_type") == "github.merge"
        for name, values in api.calls
        if name == "transition_task"
    )


@pytest.mark.parametrize("failure", ("expired", "ineligible"))
def test_model_launch_requires_current_eligible_outbox_claim(
    failure: str,
) -> None:
    api = FakeBuilderOpsClient()
    launcher = Launcher()
    consumer = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api,
            repository=REPO,
            effect_outbox=InvalidClaimOutbox(api, failure=failure),
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        launcher,
        holder="verification-host",
    )

    result = consumer.consume(request())

    assert result.status == "backoff"
    assert launcher.calls == []


def test_unknown_model_effect_restart_resumes_same_session_after_reconciliation() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    first_launcher = CrashAfterThreadStartLauncher()
    first = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        first_launcher,
        holder="verification-host",
    )

    first_result = first.consume(request())

    assert first_result.status == "backoff"
    assert len(first_launcher.calls) == 1
    assert "unknown" in outbox.calls
    task = api.tasks[first_result.run_id]
    task["payload"]["run"]["retry_after"] = "2000-01-01T00:00:00+00:00"

    restarted_launcher = Launcher()
    restarted = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        restarted_launcher,
        holder="verification-host",
    )
    recovered = restarted.recover(first_result.run_id)

    assert recovered.status == "needs_human"
    assert len(restarted_launcher.calls) == 1
    assert (
        restarted_launcher.calls[0][1]
        == "01900000-0000-7000-8000-000000000099"
    )
    assert len(first_launcher.calls) == 1


def test_pre_thread_start_crash_dead_letters_without_relaunch() -> None:
    api = CrashBeforeFirstTaskCompletionClient()
    outbox = FakeVerificationOutbox(api)
    first_launcher = CrashBeforeThreadStartLauncher()
    first = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        first_launcher,
        holder="verification-host",
    )

    with pytest.raises(SystemExit, match="thread-start persistence"):
        first.consume(request())

    run_id = next(iter(api.tasks))
    task = api.tasks[run_id]
    assert task["state"] == "claimed"
    assert task["payload"]["run"]["coordinator_session_id"] is None
    assert task["payload"]["run"]["context_pack"] is None
    operation_keys = list(outbox.states)
    assert len(operation_keys) == 1
    assert outbox.states[operation_keys[0]] == "claimed"
    outbox.claims[operation_keys[0]][
        "expires_at"
    ] = "2000-01-01T00:00:00+00:00"
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    restarted_launcher = VerifiedLauncher()
    restarted = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        restarted_launcher,
        holder="verification-host",
    )
    with pytest.raises(SystemExit, match="before task completion"):
        restarted.recover(run_id)

    assert restarted_launcher.calls == []
    assert list(outbox.states) == operation_keys
    assert outbox.states[operation_keys[0]] == "dead_letter"
    assert outbox.evidence[operation_keys[0]] == {
        "outcome": "indeterminate_pre_session_model_effect",
        "head_sha": HEAD,
        "provider_session_id": None,
        "relaunch_performed": False,
    }
    effect_intents = [
        values
        for name, values in api.calls
        if name == "transition_task"
        and isinstance(values.get("outbox"), dict)
    ]
    assert len(effect_intents) == 1

    task = api.tasks[run_id]
    assert task["state"] == "claimed"
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    final_launcher = VerifiedLauncher()
    final = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        final_launcher,
        holder="verification-host",
    )
    recovered = final.recover(run_id)

    assert recovered.status == "failed"
    assert final_launcher.calls == []
    assert list(outbox.states) == operation_keys


@pytest.mark.parametrize(
    ("session_id", "persisted_context"),
    (
        (
            "01900000-0000-7000-8000-000000000099",
            None,
        ),
        (
            None,
            {"head_sha": HEAD},
        ),
        (
            "01900000-0000-7000-8000-000000000099",
            {},
        ),
    ),
)
def test_pre_thread_start_recovery_rejects_partial_session_state_without_mutation(
    session_id, persisted_context
) -> None:
    api = CrashBeforeFirstTaskCompletionClient()
    outbox = FakeVerificationOutbox(api)
    first = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        CrashBeforeThreadStartLauncher(),
        holder="verification-host",
    )

    with pytest.raises(SystemExit, match="thread-start persistence"):
        first.consume(request())

    run_id = next(iter(api.tasks))
    task = api.tasks[run_id]
    task["payload"]["run"]["coordinator_session_id"] = session_id
    task["payload"]["run"]["context_pack"] = persisted_context
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    operation_key = next(iter(outbox.states))
    before_calls = list(outbox.calls)
    restarted_launcher = VerifiedLauncher()
    restarted = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        restarted_launcher,
        holder="verification-host",
    )

    with pytest.raises(ValueError, match="partial_model_session_state"):
        restarted.recover(run_id)

    assert restarted_launcher.calls == []
    assert outbox.states[operation_key] == "claimed"
    assert operation_key not in outbox.evidence
    assert outbox.calls == before_calls + ["status"]


def test_recovery_reconciles_durable_model_attempt_without_relaunch() -> None:
    api = FakeBuilderOpsClient()
    outbox = CrashAfterDurableAttemptOutbox(api)
    first_launcher = VerifiedLauncher()
    first = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        first_launcher,
        holder="verification-host",
    )

    with pytest.raises(SystemExit, match="durable model attempt"):
        first.consume(request())

    run_id = next(iter(api.tasks))
    task = api.tasks[run_id]
    assert len(api.attempt_rows[run_id]) == 1
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    restarted_launcher = VerifiedLauncher()
    restarted = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        restarted_launcher,
        holder="verification-host",
    )
    recovered = restarted.recover(run_id)

    assert recovered.status == "running"
    assert restarted_launcher.calls == []
    assert len(first_launcher.calls) == 1
    assert restarted.ledger.merge_ready_receipt(run_id) is not None
    assert outbox.states
    assert set(outbox.states.values()) == {"succeeded"}


def test_succeeded_model_effect_recovery_applies_attempt_without_relaunch() -> None:
    api = FakeBuilderOpsClient()
    outbox = CrashAfterSucceededReconciliationOutbox(api)
    first_launcher = VerifiedLauncher()
    first = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        first_launcher,
        holder="verification-host",
    )

    with pytest.raises(
        SystemExit, match="succeeded model reconciliation"
    ):
        first.consume(request())

    run_id = next(iter(api.tasks))
    assert len(api.attempt_rows[run_id]) == 1
    assert set(outbox.states.values()) == {"succeeded"}
    task = api.tasks[run_id]
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    restarted_launcher = VerifiedLauncher()
    restarted = VerificationConsumer(
        BuilderOpsVerificationLedger(
            api, repository=REPO, effect_outbox=outbox
        ),
        Truth(eligible_pr(), GREEN),
        Auth(),
        restarted_launcher,
        holder="verification-host",
    )
    recovered = restarted.recover(run_id)

    assert recovered.status == "running"
    assert restarted_launcher.calls == []
    assert len(first_launcher.calls) == 1
    assert len(api.attempt_rows[run_id]) == 2
    assert restarted.ledger.merge_ready_receipt(run_id) is not None


def test_api_ledger_low_convergence_still_needs_one_fresh_review() -> None:
    api = FakeBuilderOpsClient()
    ledger = BuilderOpsVerificationLedger(api, repository=REPO)
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    loop = VerificationAgentLoop(
        ledger,
        run.run_id,
        holder="verification-host",
        lease_id=claimed.lease_id,
    )
    context = {"head_sha": HEAD}
    loop.repair(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="effect-recovery",
        session_id="fix-1",
        capability="gpt-5.6-sol",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
    )
    with pytest.raises(ValueError):
        loop.repair(
            finding_id="F2",
            failure_domain="review_code_correctness",
            mechanism_id="effect-recovery",
            session_id="fix-2",
            capability="gpt-5.6-sol",
            reasoning_effort="high",
            context=context,
            outcome="fixed",
        )
    loop.review(
        finding_id="F1",
        failure_domain="review_code_correctness",
        mechanism_id="effect-recovery",
        session_id="blocking-review",
        capability="gpt-5.6-sol",
        reasoning_effort="xhigh",
        context=context,
        outcome="blocking",
    )
    loop.repair(
        finding_id="F2",
        failure_domain="review_code_correctness",
        mechanism_id="effect-recovery",
        session_id="fix-2",
        capability="gpt-5.6-sol",
        reasoning_effort="high",
        context=context,
        outcome="fixed",
    )
    loop.review(
        session_id="clean-review-1",
        capability="gpt-5.6-sol",
        reasoning_effort="xhigh",
        context=context,
        outcome="clean",
    )
    assert ledger.closure_ready(run.run_id) is True


def test_api_ledger_late_blocking_review_revokes_merge_readiness() -> None:
    api = FakeBuilderOpsClient()
    ledger = BuilderOpsVerificationLedger(api, repository=REPO)
    run = ledger.ingest(request(final_review_rounds=2))
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    ledger.record_attempt(
        run.run_id,
        "verification",
        "verification-session",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "passed",
        {"head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="late-blocker-verification",
    )
    loop = VerificationAgentLoop(
        ledger,
        run.run_id,
        holder="verification-host",
        lease_id=claimed.lease_id,
    )
    context = {"head_sha": HEAD}
    for review_number in (1, 2):
        loop.review(
            session_id=f"clean-review-{review_number}",
            capability="gpt-5.6-sol",
            reasoning_effort="xhigh",
            context=context,
            outcome="clean",
        )
    assert ledger.closure_ready(run.run_id) is True
    verified_receipt = VerifiedLauncher().launch({})[1]
    ledger.mark_merge_ready(
        run.run_id,
        verified_receipt,
        holder="verification-host",
        lease_id=claimed.lease_id,
    )
    assert ledger.merge_ready_receipt(run.run_id) is not None

    loop.review(
        finding_id="F-late",
        failure_domain="review_code_correctness",
        mechanism_id="merge-authority",
        session_id="blocking-review-3",
        capability="gpt-5.6-sol",
        reasoning_effort="xhigh",
        context=context,
        outcome="blocking",
    )

    assert ledger.closure_ready(run.run_id) is False
    with pytest.raises(
        ValueError,
        match="final consecutive clean review rounds",
    ):
        ledger.merge_ready_receipt(run.run_id)
    with pytest.raises(
        ValueError,
        match="fresh verified review gate",
    ):
        ledger.mark_merge_ready(
            run.run_id,
            verified_receipt,
            holder="verification-host",
            lease_id=claimed.lease_id,
        )


def _live_takeover_request(
    ledger: BuilderOpsVerificationLedger,
    head_sha: str,
):
    payload = request(head_sha)
    authenticated = _authenticated_verification_request(payload)
    token = ledger.canonical_chain_token(authenticated)
    return _live_observed_verification_request(
        authenticated,
        observed_repository=REPO,
        observed_pr_number=3603,
        observed_head_sha=head_sha,
        observed_state="open",
        observed_merged_at=None,
        observed_draft=False,
        observed_linked_issue=3603,
        observed_closing_issues=(3603,),
        observed_supporting_issues=(),
        observed_final_review_rounds=1,
        canonical_chain_token=token,
    )


def test_head_takeover_terminalizes_prior_model_effect_and_clears_binding() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={"repository": REPO, "head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="prior-head-model",
    )
    ledger.abandon_effect(
        operation_key, detail="simulated prior-head process loss"
    )
    ledger.backoff(
        run.run_id,
        {"outcome": "retry"},
        "2000-01-01T00:00:00+00:00",
        holder="verification-host",
        lease_id=claimed.lease_id,
    )

    taken_over = ledger.ingest(
        _live_takeover_request(ledger, NEXT_HEAD)
    )

    assert taken_over.current_head_sha == NEXT_HEAD
    assert taken_over.status == "queued"
    assert outbox.states[operation_key] == "succeeded"
    assert ledger.pending_effect_binding(run.run_id) is None
    assert outbox.evidence[operation_key] == {
        "outcome": "terminal_no_effect",
        "reason": "head_superseded",
        "old_head_sha": HEAD,
        "new_head_sha": NEXT_HEAD,
        "model_output_applied": False,
    }


def test_attempt_commit_preserves_effect_identity_until_reconciliation() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    first = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    run = first.ingest(request())
    claimed = first.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    operation_key = first.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={"repository": REPO, "head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="first-model-effect",
    )
    first.record_attempt(
        run.run_id,
        "verification",
        "session-after-effect",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "passed",
        {"head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="attempt-after-effect",
    )
    first.abandon_effect(
        operation_key, detail="simulated crash before reconciliation"
    )

    restarted = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    with pytest.raises(
        ValueError, match="requires reconciliation before retry"
    ):
        restarted.begin_effect(
            run.run_id,
            effect_type="model.verification_coordinator",
            payload={"repository": REPO, "head_sha": HEAD},
            holder="verification-host",
            lease_id=claimed.lease_id,
            idempotency_key="must-not-create-a-second-effect",
        )

    effect_intents = [
        values
        for name, values in api.calls
        if name == "transition_task" and values.get("outbox") is not None
    ]
    assert len(effect_intents) == 1


def test_terminal_effect_reconciliation_response_loss_reads_durable_status() -> None:
    api = FakeBuilderOpsClient()
    outbox = LostReconcileResponseOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={"repository": REPO, "head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="lost-terminal-response",
    )

    ledger.finish_effect(
        operation_key,
        observed_applied=True,
        evidence={"outcome": "model_receipt_durably_recorded"},
    )

    assert outbox.states[operation_key] == "succeeded"
    assert outbox.calls[-2:] == ["reconcile", "status"]


def test_mark_unknown_response_loss_continues_from_durable_status() -> None:
    api = FakeBuilderOpsClient()
    outbox = LostUnknownResponseOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={"repository": REPO, "head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="lost-unknown-response",
    )

    ledger.finish_effect(
        operation_key,
        observed_applied=True,
        evidence={"outcome": "model_receipt_durably_recorded"},
    )

    assert outbox.states[operation_key] == "succeeded"
    assert outbox.calls[-3:] == ["unknown", "status", "reconcile"]


def test_verification_cli_never_constructs_dispatcher_sqlite(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dispatcher_cli,
        "_make_store",
        lambda: (_ for _ in ()).throw(
            AssertionError("verification command opened dispatcher SQLite")
        ),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_cmd_verification_status",
        lambda _args, store: 0 if store is None else 1,
    )

    assert (
        dispatcher_cli.main(
            ["verification-status", "--repo", REPO, "--json"]
        )
        == 0
    )
