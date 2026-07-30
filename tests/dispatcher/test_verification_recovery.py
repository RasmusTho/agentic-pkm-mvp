from __future__ import annotations

import app.dispatcher.cli as dispatcher_cli
import pytest

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import VerificationConsumer
from tests.dispatcher.builderops_verification_fakes import (
    FakeBuilderOpsClient,
    FakeVerificationOutbox,
)
from tests.dispatcher.test_verification_consumer import (
    Auth,
    GREEN,
    Launcher,
    Truth,
    eligible_pr,
)
from tests.dispatcher.verification_helpers import HEAD, REPO, request


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
        effect_type="github.merge",
        payload={"repository": REPO, "pr_number": 3603, "head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="merge-after-verification",
    )

    restarted = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    recovered = restarted.recover_effect(
        operation_key,
        run_id=run.run_id,
        effect_type="github.merge",
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
    assert outbox.calls[-3:] == ["recover", "claim", "reconcile"]


class FailingIntentClient(FakeBuilderOpsClient):
    def transition_task(self, **values):
        if values.get("outbox") is not None:
            raise RuntimeError("simulated pre-effect commit failure")
        return super().transition_task(**values)


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


class LostReconcileResponseOutbox(FakeVerificationOutbox):
    def reconcile(self, claim, *, observed_applied: bool, evidence):
        super().reconcile(
            claim,
            observed_applied=observed_applied,
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
