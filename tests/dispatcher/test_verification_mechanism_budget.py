from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.dispatcher import control_plane
from app.dispatcher.cli import _compact_verification_run
from app.dispatcher.config import load_paths
from app.dispatcher.store import SqliteStore
from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_consumer import (
    CodexExecLauncher,
    ReceiptContractError,
    VerificationConsumer,
    context_pack,
    load_and_validate_verification_closer_receipt,
)
from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.test_verification_consumer import (
    Auth,
    GREEN,
    Launcher,
    RateLimitedLauncher,
    Truth,
    eligible_pr,
)
from tests.dispatcher.verification_helpers import HEAD, ledger, request


CODE = "review_code_correctness"
STATIC = "static_quality"


def _claimed_loop(tmp_path):
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    assert claimed.lease_id is not None
    return (
        state,
        run,
        VerificationAgentLoop(
            state,
            run.run_id,
            holder="host",
            lease_id=claimed.lease_id,
            strongest_capability="sol",
        ),
    )


def _repair(
    loop: VerificationAgentLoop,
    finding: str,
    mechanism: str,
    index: int,
    *,
    domain: str = CODE,
    strongest: bool = False,
) -> int:
    return loop.repair(
        finding_id=finding,
        failure_domain=domain,
        mechanism_id=mechanism,
        session_id=f"repair-{index}",
        capability="sol" if strongest else "terra",
        reasoning_effort="xhigh" if strongest else "high",
        context={"head_sha": HEAD},
        outcome="fixed",
        strongest=strongest,
    )


def _blocking_review(
    loop: VerificationAgentLoop,
    finding: str,
    mechanism: str,
    index: int,
    *,
    domain: str = CODE,
) -> int:
    return loop.review(
        finding_id=finding,
        failure_domain=domain,
        mechanism_id=mechanism,
        session_id=f"review-{index}",
        capability="terra",
        reasoning_effort="high",
        context={"head_sha": HEAD},
        outcome="blocking",
    )


def test_repair_event_requires_stable_domain_mechanism_binding(tmp_path) -> None:
    state, run, loop = _claimed_loop(tmp_path)

    with pytest.raises(ValueError, match="failure domain"):
        _repair(loop, "F0", "parser", 0, domain="invented-domain")

    _repair(loop, "F1", "parser", 1)
    _blocking_review(loop, "F1", "parser", 1)
    with pytest.raises(ValueError, match="finding binding"):
        _repair(loop, "F1", "different-mechanism", 2)

    attempts = state.attempts(run.run_id)
    assert attempts[0]["failure_domain"] == CODE
    assert attempts[0]["mechanism_id"] == "parser"
    assert attempts[0]["finding_id"] == "F1"


def test_standard_budget_is_partitioned_by_domain_and_mechanism(tmp_path) -> None:
    _state, _run, loop = _claimed_loop(tmp_path)

    _repair(loop, "F1", "parser", 1)
    _blocking_review(loop, "F1", "parser", 1)
    _repair(loop, "F2", "parser", 2)
    _blocking_review(loop, "F2", "parser", 2)

    _repair(loop, "F3", "formatter", 3)
    _blocking_review(loop, "F3", "formatter", 3)
    _repair(loop, "F4", "parser", 4, domain=STATIC)
    _blocking_review(loop, "F4", "parser", 4, domain=STATIC)

    with pytest.raises(ValueError, match="standard_repair budget exhausted"):
        _repair(loop, "F5", "parser", 5)


def test_capability_escalation_is_scoped_to_the_exhausted_mechanism(tmp_path) -> None:
    _state, _run, loop = _claimed_loop(tmp_path)

    _repair(loop, "F1", "parser", 1)
    _blocking_review(loop, "F1", "parser", 1)
    _repair(loop, "F2", "parser", 2)
    _blocking_review(loop, "F2", "parser", 2)

    with pytest.raises(ValueError, match="same failure mechanism"):
        _repair(loop, "F3", "formatter", 3, strongest=True)
    _repair(loop, "F3", "parser", 3, strongest=True)


def test_keyed_budget_batch_is_atomic_and_replay_safe(tmp_path) -> None:
    state, run, loop = _claimed_loop(tmp_path)
    context = {"head_sha": HEAD}
    valid = [
        {
            "kind": "repair",
            "finding_id": "F1",
            "failure_domain": CODE,
            "mechanism_id": "parser",
            "session_id": "repair-1",
            "capability": "terra",
            "reasoning_effort": "high",
            "outcome": "fixed",
            "strongest": False,
        },
        {
            "kind": "review",
            "finding_id": "F1",
            "failure_domain": CODE,
            "mechanism_id": "parser",
            "session_id": "review-1",
            "capability": "terra",
            "reasoning_effort": "high",
            "outcome": "blocking",
            "strongest": None,
        },
        {
            "kind": "repair",
            "finding_id": "F2",
            "failure_domain": CODE,
            "mechanism_id": "parser",
            "session_id": "repair-2",
            "capability": "terra",
            "reasoning_effort": "high",
            "outcome": "fixed",
            "strongest": False,
        },
    ]
    valid = [
        *valid,
        {
            "kind": "review",
            "finding_id": "F2",
            "failure_domain": CODE,
            "mechanism_id": "parser",
            "session_id": "review-2",
            "capability": "terra",
            "reasoning_effort": "high",
            "outcome": "blocking",
            "strongest": None,
        },
        {
            "kind": "repair",
            "finding_id": "F3",
            "failure_domain": CODE,
            "mechanism_id": "formatter",
            "session_id": "repair-3",
            "capability": "terra",
            "reasoning_effort": "high",
            "outcome": "fixed",
            "strongest": False,
        },
    ]
    invalid = [
        *valid[:-1],
        {
            "kind": "repair",
            "finding_id": "F3",
            "failure_domain": CODE,
            "mechanism_id": "parser",
            "session_id": "repair-3",
            "capability": "terra",
            "reasoning_effort": "high",
            "outcome": "fixed",
            "strongest": False,
        },
    ]

    with pytest.raises(ValueError, match="standard_repair budget exhausted"):
        loop.apply_events(invalid, context=context)
    assert state.attempts(run.run_id) == []

    loop.apply_events(valid, context=context)
    before = state.attempts(run.run_id)
    loop.apply_events(valid, context=context)
    assert state.attempts(run.run_id) == before


def test_v1_migration_preserves_legacy_budget_and_v2_takeover_is_monotonic(
    tmp_path,
) -> None:
    db = tmp_path / "dispatcher.sqlite3"
    state = VerificationDispatchLedger(SqliteStore(db))
    legacy_run = state.ingest(request())
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO verification_attempts (
                attempt_id, run_id, attempt_kind, ordinal, session_id,
                capability, reasoning_effort, context_hash, outcome,
                finding_id, failure_domain, mechanism_id, receipt_json, created_at
            ) VALUES (?, ?, 'standard_repair', 1, 'pre-migration', 'terra',
                      'high', 'legacy-context', 'fixed', ?, ?, ?, ?, ?)
            """,
            (
                "vattempt-pre-migration",
                legacy_run.run_id,
                "F1",
                CODE,
                "parser",
                '{"finding_id":"F1","head_sha":"' + HEAD + '"}',
                "2026-07-15T00:00:00+00:00",
            ),
        )
        conn.execute("ALTER TABLE verification_attempts DROP COLUMN finding_id")
        conn.execute("ALTER TABLE verification_attempts DROP COLUMN failure_domain")
        conn.execute("ALTER TABLE verification_attempts DROP COLUMN mechanism_id")
        conn.execute("ALTER TABLE verification_runs DROP COLUMN repair_budget_policy")
        conn.execute(
            "UPDATE dispatcher_meta SET value='3' WHERE key='schema_version'"
        )
        conn.commit()

    migrated = VerificationDispatchLedger(SqliteStore(db))
    legacy = migrated.get(legacy_run.run_id)
    assert legacy is not None
    assert legacy.repair_budget_policy == "v1"
    claimed = migrated.claim(legacy.run_id, "legacy-host")
    assert claimed.lease_id is not None
    migrated.record_attempt(
        legacy.run_id,
        "standard_repair",
        "legacy-2",
        "terra",
        "high",
        {"head_sha": HEAD},
        "fixed",
        {
            "finding_id": "F2",
            "failure_domain": CODE,
            "mechanism_id": "formatter",
            "head_sha": HEAD,
        },
        holder="legacy-host",
        lease_id=claimed.lease_id,
    )
    with pytest.raises(ValueError, match="standard_repair budget exhausted"):
        migrated.record_attempt(
            legacy.run_id,
            "standard_repair",
            "legacy-3",
            "terra",
            "high",
            {"head_sha": HEAD},
            "fixed",
            {
                "finding_id": "F3",
                "failure_domain": CODE,
                "mechanism_id": "third",
                "head_sha": HEAD,
            },
            holder="legacy-host",
            lease_id=claimed.lease_id,
        )
    migrated.terminal(
        legacy.run_id,
        "failed",
        {"outcome": "legacy-budget-preserved"},
        holder="legacy-host",
        lease_id=claimed.lease_id,
    )
    with migrated.store._connect() as conn:
        conn.execute(
            "DELETE FROM verification_attempts WHERE run_id=?", (legacy.run_id,)
        )
        conn.execute("DELETE FROM verification_runs WHERE run_id=?", (legacy.run_id,))
        conn.commit()
    post_migration = migrated.ingest(request("b" * 40))
    assert post_migration.repair_budget_policy == "v2"

    fresh_state = ledger(tmp_path / "fresh")
    fresh_run = fresh_state.ingest(request())
    first_claim = fresh_state.claim(fresh_run.run_id, "first-host")
    assert first_claim.repair_budget_policy == "v2"
    assert first_claim.lease_id is not None
    fresh_state.record_attempt(
        fresh_run.run_id,
        "standard_repair",
        "first-repair",
        "terra",
        "high",
        {"head_sha": HEAD},
        "fixed",
        {
            "finding_id": "F1",
            "failure_domain": CODE,
            "mechanism_id": "parser",
            "head_sha": HEAD,
        },
        holder="first-host",
        lease_id=first_claim.lease_id,
    )
    with fresh_state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", fresh_run.run_id),
        )
        conn.commit()
    takeover = fresh_state.claim(fresh_run.run_id, "second-host")
    assert takeover.repair_budget_policy == "v2"
    assert len(fresh_state.attempts(fresh_run.run_id)) == 1


def test_context_exposes_sanitized_remaining_budget(tmp_path) -> None:
    state, run, loop = _claimed_loop(tmp_path)
    _repair(loop, "private finding text", "parser", 1)

    projection = state.repair_budget_projection(run.run_id)
    pack = context_pack(run, eligible_pr(), repair_budget=projection)
    status = _compact_verification_run(run, repair_budget=projection)

    assert pack["repair_budget"] == status["repair_budget"]
    assert pack["repair_budget"] == {
        "policy_version": "v2",
        "mechanism_count": 1,
        "truncated": False,
        "omitted_count": 0,
        "mechanisms": [
            {
                "failure_domain": CODE,
                "mechanism_id": "mechanism-b17d45121150928f",
                "standard_used": 1,
                "standard_remaining": 1,
                "escalated_used": 0,
                "escalated_remaining": 2,
            }
        ],
    }
    assert "private finding text" not in str(pack)
    assert "parser" not in str(pack)


def test_projection_signals_truncation_and_keeps_most_recent_mechanisms(
    tmp_path,
) -> None:
    state, run, loop = _claimed_loop(tmp_path)
    for index in range(33):
        mechanism = f"mechanism-{index:016x}"
        _repair(loop, f"F{index}", mechanism, index)
        _blocking_review(loop, f"F{index}", mechanism, index)

    projection = state.repair_budget_projection(run.run_id)

    assert projection["mechanism_count"] == 33
    assert projection["truncated"] is True
    assert projection["omitted_count"] == 1
    mechanisms = projection["mechanisms"]
    assert isinstance(mechanisms, list)
    assert len(mechanisms) == 32
    assert mechanisms[0]["mechanism_id"] == "mechanism-0000000000000020"
    assert all(
        item["mechanism_id"] != "mechanism-0000000000000000"
        for item in mechanisms
    )
    assert mechanisms[0]["standard_used"] == 1
    assert mechanisms[0]["escalated_used"] == 0


def test_budget_exhaustion_never_mints_human_exception(tmp_path) -> None:
    state, run, loop = _claimed_loop(tmp_path)
    _repair(loop, "F1", "parser", 1)
    _blocking_review(loop, "F1", "parser", 1)
    _repair(loop, "F2", "parser", 2)
    _blocking_review(loop, "F2", "parser", 2)

    with pytest.raises(ValueError, match="standard_repair budget exhausted"):
        _repair(loop, "F3", "parser", 3)

    current = state.get(run.run_id)
    assert current is not None
    assert current.status in {"claimed", "running"}
    with state.store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (run.run_id,),
        ).fetchone()[0] == 0


def test_v1_pending_receipt_replay_accepts_legacy_unbound_event_shape(
    tmp_path,
) -> None:
    state, run, loop = _claimed_loop(tmp_path)
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET repair_budget_policy='v1' WHERE run_id=?",
            (run.run_id,),
        )
        conn.commit()
    receipt = {
        "verdict": "blocked",
        "head_sha": HEAD,
        "summary": "legacy repair",
        "receipt_ids": ["repair-1"],
        "retry_after": None,
        "review_events": [
            {
                "kind": "repair",
                "session_id": "repair-1",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "outcome": "fixed",
                "finding_id": "F1",
                "strongest": False,
            }
        ],
        "human_exception": None,
    }
    schema = (
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
    )

    with pytest.raises(ReceiptContractError):
        load_and_validate_verification_closer_receipt(
            receipt,
            schema,
            trusted_repository="RasmusTho/agentic-pkm-mvp",
            trusted_evidence_urls=frozenset(),
        )
    migrated = load_and_validate_verification_closer_receipt(
        receipt,
        schema,
        trusted_repository="RasmusTho/agentic-pkm-mvp",
        trusted_evidence_urls=frozenset(),
        repair_budget_policy="v1",
    )
    events = migrated["review_events"]
    assert isinstance(events, list)
    assert events[0]["failure_domain"] is None
    assert events[0]["mechanism_id"] is None
    for _ in range(2):
        loop.apply_events(events, context={"head_sha": HEAD})
    attempts = state.attempts(run.run_id)
    assert len(attempts) == 1
    assert attempts[0]["kind"] == "standard_repair"
    assert attempts[0]["finding_id"] is None
    assert attempts[0]["failure_domain"] is None
    assert attempts[0]["mechanism_id"] is None


def _v1_backoff_run(tmp_path):
    """Park one pending policy-v1 run in backoff with a stored session.

    Mirrors the production migration outage shape: the run row carries
    ``repair_budget_policy='v1'``, a first launch rate-limited into backoff
    (persisting a coordinator session id to resume), and the retry window is
    already open.
    """

    state = ledger(tmp_path)
    run = state.ingest(request())
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET repair_budget_policy='v1' WHERE run_id=?",
            (run.run_id,),
        )
        conn.commit()
    truth = Truth(eligible_pr(), GREEN)
    first = VerificationConsumer(
        state,
        truth,
        Auth(),
        RateLimitedLauncher(),
        "host",
    ).consume(request())
    assert first.status == "backoff"
    assert first.coordinator_session_id is not None
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (run.run_id,),
        )
        conn.commit()
    return state, run, truth, first


def test_resumed_v1_launcher_accepts_legacy_repair_receipt(tmp_path) -> None:
    state, run, truth, first = _v1_backoff_run(tmp_path)

    class LegacyRepairLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            resume_session_id = kwargs.get("resume_session_id")
            self.calls.append((context_pack, resume_session_id))
            if callback := kwargs.get("on_thread_started"):
                callback(resume_session_id)
            return resume_session_id, {
                "verdict": "blocked",
                "head_sha": HEAD,
                "summary": "legacy repair",
                "receipt_ids": ["repair-v1"],
                "retry_after": None,
                "review_events": [
                    {
                        "kind": "repair",
                        "session_id": "repair-v1",
                        "capability": "gpt-5.6-terra",
                        "reasoning_effort": "high",
                        "outcome": "fixed",
                        "finding_id": "F1",
                        "strongest": False,
                    }
                ],
                "human_exception": None,
            }

    launcher = LegacyRepairLauncher()
    VerificationConsumer(state, truth, Auth(), launcher, "host").consume(request())

    assert launcher.calls[0][1] == first.coordinator_session_id
    repairs = [
        attempt
        for attempt in state.attempts(run.run_id)
        if attempt["kind"] == "standard_repair"
    ]
    assert len(repairs) == 1
    assert repairs[0]["failure_domain"] is None
    assert repairs[0]["mechanism_id"] is None


def test_v1_pending_clean_review_receipt_ignores_legacy_binding_fields(
    tmp_path,
) -> None:
    """A migrated policy-v1 pending receipt may carry a clean review event
    with a stale ``finding_id``/``failure_domain``/``mechanism_id`` left over
    from the legacy schema (the legacy application ignored those fields on a
    clean outcome). Replay must not terminalize the run as an invalid
    persisted receipt, and the legacy binding must never become durable."""

    state, run, truth, first = _v1_backoff_run(tmp_path)

    class LegacyCleanReviewLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            resume_session_id = kwargs.get("resume_session_id")
            self.calls.append((context_pack, resume_session_id))
            if callback := kwargs.get("on_thread_started"):
                callback(resume_session_id)
            return resume_session_id, {
                "verdict": "blocked",
                "head_sha": HEAD,
                "summary": "legacy clean review carries stale binding",
                "receipt_ids": ["review-v1"],
                "retry_after": None,
                "review_events": [
                    {
                        "kind": "review",
                        "session_id": "review-v1",
                        "capability": "gpt-5.6-terra",
                        "reasoning_effort": "high",
                        "outcome": "clean",
                        "finding_id": "F1",
                        "failure_domain": CODE,
                        "mechanism_id": "parser",
                        "strongest": None,
                    }
                ],
                "human_exception": None,
            }

    launcher = LegacyCleanReviewLauncher()
    result = VerificationConsumer(state, truth, Auth(), launcher, "host").consume(
        request()
    )

    assert launcher.calls[0][1] == first.coordinator_session_id
    assert result.status == "failed"
    assert isinstance(result.terminal_receipt, dict)
    assert result.terminal_receipt.get("outcome") != "invalid_persisted_verification_receipt"
    assert result.stop_reason != "invalid_receipt_contract"
    reviews = [
        attempt
        for attempt in state.attempts(run.run_id)
        if attempt["kind"] == "review"
    ]
    assert len(reviews) == 1
    assert reviews[0]["outcome"] == "clean"
    assert reviews[0]["finding_id"] is None
    assert reviews[0]["failure_domain"] is None
    assert reviews[0]["mechanism_id"] is None


def test_v2_clean_review_rejects_failure_binding_fields(tmp_path) -> None:
    """Policy-v2 clean review events must still fail closed on any binding
    field — the legacy-compatibility scrub is scoped to policy-v1 only."""

    schema = (
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
    )
    receipt = {
        "verdict": "blocked",
        "head_sha": HEAD,
        "summary": "v2 clean review must not carry a failure binding",
        "receipt_ids": ["review-v2"],
        "retry_after": None,
        "review_events": [
            {
                "kind": "review",
                "session_id": "review-v2",
                "capability": "terra",
                "reasoning_effort": "high",
                "outcome": "clean",
                "finding_id": "F1",
                "failure_domain": CODE,
                "mechanism_id": "parser",
                "strongest": None,
            }
        ],
        "human_exception": None,
    }

    with pytest.raises(ReceiptContractError):
        load_and_validate_verification_closer_receipt(
            receipt,
            schema,
            trusted_repository="RasmusTho/agentic-pkm-mvp",
            trusted_evidence_urls=frozenset(),
            repair_budget_policy="v2",
        )

    # Unset/default policy (not policy-v1) must also stay strict.
    with pytest.raises(ReceiptContractError):
        load_and_validate_verification_closer_receipt(
            receipt,
            schema,
            trusted_repository="RasmusTho/agentic-pkm-mvp",
            trusted_evidence_urls=frozenset(),
        )


def _coordinator_stream(*agent_message_payloads: object) -> str:
    """One codex-exec JSONL stream: thread start plus final agent messages."""

    lines = [
        json.dumps(
            {
                "type": "thread.started",
                "thread_id": "01900000-0000-7000-8000-000000000042",
            }
        )
    ]
    lines += [
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(payload),
                },
            }
        )
        for payload in agent_message_payloads
    ]
    return "\n".join(lines) + "\n"


def _stream_launcher(tmp_path: Path, stdout: str) -> CodexExecLauncher:
    """A real CodexExecLauncher whose process runner replays one stream."""

    class Result:
        returncode = 0
        stderr = ""

    Result.stdout = stdout

    def runner(command, **kwargs):
        return Result()

    repo_root = Path(__file__).resolve().parents[2]
    return CodexExecLauncher(
        tmp_path,
        repo_root / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=repo_root / ".codex/agents/verification-closer.toml",
        runner=runner,
    )


def test_v1_real_launcher_stream_filter_accepts_legacy_clean_review_receipt(
    tmp_path,
) -> None:
    """The CodexExecLauncher raw JSONL stream pre-filter must not swallow a
    policy-v1 legacy clean-review terminal message: doing so leaves the
    launcher with no schema-valid terminal receipt and misclassifies the run
    as a launcher contract failure before
    ``load_and_validate_verification_closer_receipt`` ever sees the receipt.
    The stub-launcher tests above bypass this filter, so this test drives the
    real launcher with a fake process runner."""

    state = ledger(tmp_path)
    run = state.ingest(request())
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET repair_budget_policy='v1' WHERE run_id=?",
            (run.run_id,),
        )
        conn.commit()

    legacy_receipt = {
        "verdict": "blocked",
        "head_sha": HEAD,
        "summary": "legacy clean review carries stale binding",
        "receipt_ids": ["review-v1-stream"],
        "retry_after": None,
        "review_events": [
            {
                "kind": "review",
                "session_id": "review-v1-stream",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "outcome": "clean",
                "finding_id": "F1",
                "failure_domain": CODE,
                "mechanism_id": "parser",
                "strongest": None,
            }
        ],
        "human_exception": None,
    }
    launcher = _stream_launcher(
        tmp_path,
        _coordinator_stream(legacy_receipt),
    )
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        launcher,
        "host",
    ).consume(request())

    # A blocked verdict terminates as failed; the legacy binding must be
    # neither a launcher-contract misclassification nor a receipt-contract
    # rejection, and it must never become durable.
    assert result.status == "failed"
    assert result.stop_reason != "invalid_receipt_contract"
    assert isinstance(result.terminal_receipt, dict)
    assert result.terminal_receipt.get("outcome") != "launcher_contract_failed"
    reviews = [
        attempt
        for attempt in state.attempts(run.run_id)
        if attempt["kind"] == "review"
    ]
    assert len(reviews) == 1
    assert reviews[0]["outcome"] == "clean"
    assert reviews[0]["finding_id"] is None
    assert reviews[0]["failure_domain"] is None
    assert reviews[0]["mechanism_id"] is None


@pytest.mark.parametrize("policy", ["v1", "v2"])
def test_strict_terminal_receipt_outranks_trailing_legacy_candidate(
    tmp_path, policy
) -> None:
    """A strictly-valid final receipt must win over trailing legacy-shaped
    stream garbage. The legacy fallback selection widened what the stream
    pre-filter matches; with last-match-wins it could let a later
    legacy-shaped agent message clobber an earlier strictly-valid receipt,
    which the consumer then rejects under the run's real policy —
    terminalizing a run that had already produced a correct receipt."""

    state = ledger(tmp_path)
    run = state.ingest(request())
    if policy == "v1":
        with state.store._connect() as conn:
            conn.execute(
                "UPDATE verification_runs SET repair_budget_policy='v1' "
                "WHERE run_id=?",
                (run.run_id,),
            )
            conn.commit()
    else:
        current = state.get(run.run_id)
        assert current is not None
        assert current.repair_budget_policy == "v2"

    strict_receipt = {
        "verdict": "blocked",
        "head_sha": HEAD,
        "summary": "strict final receipt",
        "receipt_ids": ["strict-1"],
        "retry_after": None,
        "review_events": None,
        "human_exception": None,
    }
    trailing_legacy = {
        "verdict": "blocked",
        "head_sha": HEAD,
        "summary": "trailing legacy-shaped message",
        "receipt_ids": ["legacy-1"],
        "retry_after": None,
        "review_events": [
            {
                "kind": "review",
                "session_id": "legacy-trailing",
                "capability": "gpt-5.6-terra",
                "reasoning_effort": "high",
                "outcome": "clean",
                "finding_id": "F1",
                "failure_domain": CODE,
                "mechanism_id": "parser",
                "strongest": None,
            }
        ],
        "human_exception": None,
    }
    launcher = _stream_launcher(
        tmp_path,
        _coordinator_stream(strict_receipt, trailing_legacy),
    )
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        launcher,
        "host",
    ).consume(request())

    # The strict receipt (no review events) is the selected terminal for both
    # policies; the trailing legacy candidate is discarded, never rejected
    # under the run's policy and never applied durably.
    assert result.status == "failed"
    assert result.stop_reason != "invalid_receipt_contract"
    assert isinstance(result.terminal_receipt, dict)
    assert result.terminal_receipt.get("review_events") is None
    assert result.terminal_receipt.get("outcome") != "launcher_contract_failed"
    assert [
        attempt
        for attempt in state.attempts(run.run_id)
        if attempt["kind"] == "review"
    ] == []


def test_declared_v4_missing_budget_identity_fails_closed_without_repair(
    tmp_path,
) -> None:
    state, run, loop = _claimed_loop(tmp_path)
    _repair(loop, "F1", "parser", 1)
    _blocking_review(loop, "F1", "parser", 1)
    _repair(loop, "F2", "parser", 2)
    db = state.store.db_path
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE verification_attempts DROP COLUMN mechanism_id")
        conn.commit()

    paths = load_paths({"DISPATCHER_STATE_DIR": str(tmp_path)})
    paths.events_path.touch()
    proof = control_plane.health(paths)
    assert proof["ok"] is False
    assert "mechanism_id" in proof["db"]["error"]

    with pytest.raises(ValueError, match="mechanism_id"):
        VerificationDispatchLedger(SqliteStore(db))
    with sqlite3.connect(db) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(verification_attempts)"
            ).fetchall()
        }
        assert "mechanism_id" not in columns
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_attempts WHERE run_id=?",
            (run.run_id,),
        ).fetchone()[0] == 3
        assert conn.execute(
            "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
        ).fetchone()[0] == "6"
