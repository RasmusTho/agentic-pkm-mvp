from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
import sqlite3
from threading import Event, Lock, Thread

import pytest

import app.dispatcher.verification_dispatch as verification_dispatch
from app.dispatcher.verification_contract import MAX_CLOSING_ISSUES
from app.dispatcher.verification_dispatch import VerificationRun
from tests.dispatcher.verification_helpers import (
    b4e2310_pre_trust_request,
    downgrade_verification_schema_to_v3,
    ledger,
    pre_trust_request,
    request,
)
from app.dispatcher.store import SqliteStore


CLAIM_PRE_LOCK = "2030-01-01T00:00:00.000000+00:00"
CLAIM_POST_LOCK = "2030-01-01T00:00:20.000000+00:00"


def _canonical_v1_request(*, supporting_issues: list[int]) -> dict[str, object]:
    payload = request()
    payload["contract_version"] = "verification_dispatch_request.v1"
    payload["supporting_issues"] = supporting_issues
    payload.pop("closing_issues")
    identity = {
        "contract_version": payload["contract_version"],
        "head_sha": payload["current_head_sha"],
        "pr_number": payload["pr_number"],
        "repository": payload["repository"],
        "stage": payload["stage"],
    }
    payload["idempotency_key"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def _write_deployed_v1_run(
    state,
    *,
    supporting_issues: list[int],
) -> tuple[str, dict[str, object]]:
    original = state.ingest(request())
    payload = _canonical_v1_request(supporting_issues=supporting_issues)
    idempotency_key = payload["idempotency_key"]
    assert isinstance(idempotency_key, str)
    run_id = f"vrun-{idempotency_key[:16]}"
    with sqlite3.connect(state.store.db_path) as conn:
        conn.execute(
            """
            UPDATE verification_runs
            SET run_id=?, idempotency_key=?, contract_version=?, request_json=?,
                supporting_authority_json=?, closing_authority_json='[3603]',
                status='running', claimed_by='host', lease_id='legacy-lease',
                lease_expires_at='2030-01-01T00:00:00+00:00',
                last_heartbeat_at='2026-07-16T10:00:00+00:00',
                coordinator_session_id='01900000-0000-7000-8000-000000000002',
                context_pack_json='{"legacy":"context"}'
            WHERE run_id=?
            """,
            (
                run_id,
                idempotency_key,
                payload["contract_version"],
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                json.dumps(supporting_issues, separators=(",", ":")),
                original.run_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO verification_attempts (
                attempt_id, run_id, attempt_kind, ordinal, session_id,
                capability, reasoning_effort, context_hash, outcome,
                finding_id, failure_domain, mechanism_id, receipt_json, created_at
            ) VALUES (
                'attempt-v1-closure', ?, 'standard_repair', 1,
                '01900000-0000-7000-8000-000000000002', 'gpt-5.6-terra',
                'high', 'legacy-context-hash', 'fixed', 'F-v1-ambiguous',
                'review_code_correctness', 'legacy-closing-authority',
                '{"legacy":true}', '2026-07-16T10:00:01+00:00'
            )
            """,
            (run_id,),
        )
        conn.commit()
    return run_id, payload


def _migrated_legacy_ledger(tmp_path, legacy_request: dict | None = None):
    state = ledger(tmp_path)
    original = state.ingest(request())
    if legacy_request is None:
        legacy_request = pre_trust_request()
    legacy_key = legacy_request["idempotency_key"]
    assert isinstance(legacy_key, str)
    legacy_run_id = f"vrun-{legacy_key[:16]}"
    with sqlite3.connect(state.store.db_path) as conn:
        conn.execute(
            "UPDATE verification_runs SET run_id=?, idempotency_key=?, "
            "contract_version=?, request_json=? WHERE run_id=?",
            (
                legacy_run_id,
                legacy_key,
                legacy_request["contract_version"],
                json.dumps(
                    legacy_request,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                original.run_id,
            ),
        )
        conn.execute("ALTER TABLE verification_runs DROP COLUMN supporting_authority_json")
        downgrade_verification_schema_to_v3(conn)
        conn.commit()
    migrated = verification_dispatch.VerificationDispatchLedger(
        SqliteStore(state.store.db_path)
    )
    legacy = migrated.get(legacy_run_id)
    assert legacy is not None
    assert legacy.status == "legacy_untrusted"
    return migrated, legacy


def _live_observed_request(state, payload: dict[str, object]):
    authenticated = verification_dispatch._authenticated_verification_request(
        payload
    )
    token = state.canonical_chain_token(authenticated)
    supporting = payload["supporting_issues"]
    closing = payload["closing_issues"]
    assert isinstance(supporting, list)
    assert isinstance(closing, list)
    return verification_dispatch._live_observed_verification_request(
        authenticated,
        observed_repository=payload["repository"],
        observed_pr_number=payload["pr_number"],
        observed_head_sha=payload["current_head_sha"],
        observed_state="open",
        observed_merged_at=None,
        observed_draft=False,
        observed_linked_issue=payload["linked_issue"],
        observed_closing_issues=tuple(closing),
        observed_supporting_issues=tuple(supporting),
        canonical_chain_token=token,
    )


def test_shared_request_fixture_carries_governing_issue() -> None:
    payload = request()

    assert payload["linked_issue"] == 3603
    assert payload["supporting_issues"] == []


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ((), "credential"),
        (("source_workflow",), "token"),
        (("artifact_provenance",), "secret"),
        (("evidence_pack",), "private_key"),
        (("live_truth",), "authorization"),
    ],
)
def test_ingest_rejects_unknown_request_properties_before_persistence(
    tmp_path, path: tuple[str, ...], field: str
) -> None:
    state = ledger(tmp_path)
    payload = request()
    target: dict[str, object] = payload
    for component in path:
        nested = target[component]
        assert isinstance(nested, dict)
        target = nested
    target[field] = "must-not-persist"

    with pytest.raises(ValueError, match="unknown properties"):
        state.ingest(payload)

    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 0


def test_ingest_persists_canonical_request_projection(tmp_path) -> None:
    state = ledger(tmp_path)
    payload = request()

    run = state.ingest(payload)

    with state.store._connect() as conn:
        stored = conn.execute(
            "SELECT request_json FROM verification_runs WHERE run_id=?", (run.run_id,)
        ).fetchone()[0]
    assert json.loads(stored) == payload
    assert run.request == payload
    assert run.request is not payload
    for key in (
        "source_workflow",
        "artifact_provenance",
        "evidence_pack",
        "live_truth",
    ):
        assert run.request[key] is not payload[key]


def test_canonical_request_projection_preserves_idempotent_replay(tmp_path) -> None:
    state = ledger(tmp_path)
    first_payload = request()
    replay_payload = json.loads(json.dumps(first_payload))

    first = state.ingest(first_payload)
    replay = state.ingest(replay_payload)

    assert replay.run_id == first.run_id
    assert replay.request == first.request
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 1


_INERT_MUTATION_ENTRYPOINTS = [
    lambda state, run: state.claim(run.run_id, "host"),
    lambda state, run: state.heartbeat(run.run_id, "host", "lease"),
    lambda state, run: state.start(
        run.run_id, "host", "lease", "session", {"head": run.head_sha}
    ),
    lambda state, run: state.terminal(
        run.run_id,
        "failed",
        {"outcome": "blocked"},
        holder="host",
        lease_id="lease",
    ),
    lambda state, run: state.rebind_head(
        run.run_id,
        "b" * 40,
        expected_head_sha=run.head_sha,
        observed_repository=run.repository,
        observed_pr_number=run.pr_number,
        observed_head_sha="b" * 40,
        holder="host",
        lease_id="lease",
    ),
    lambda state, run: state.backoff(
        run.run_id,
        {"outcome": "retry"},
        "2030-01-01T00:00:00+00:00",
        holder="host",
        lease_id="lease",
    ),
    lambda state, run: state.defer_unclaimed(
        run.run_id,
        {"outcome": "retry"},
        "2030-01-01T00:00:00+00:00",
    ),
    lambda state, run: state.supersede_unclaimed(
        run.run_id, {"outcome": "superseded"}, reason="stale_head"
    ),
    lambda state, run: state.record_attempt(
        run.run_id,
        "review",
        "session",
        "terra",
        "high",
        {"head": run.head_sha},
        "clean",
        holder="host",
        lease_id="lease",
    ),
    lambda state, run: state.record_attempt_batch(
        run.run_id,
        "batch",
        1,
        run.head_sha,
        lambda _attempts, _attempt_id: [],
        holder="host",
        lease_id="lease",
    ),
    lambda state, run: state.exception(
        run.run_id,
        "technical",
        {"failure_class": "technical"},
        holder="host",
        lease_id="lease",
    ),
]


def _assert_inert_legacy_run_rejects_mutation(
    tmp_path, legacy_request: dict | None, mutation
) -> None:
    """Shared mutation-fencing contract for every recognized historical shape."""
    state, legacy = _migrated_legacy_ledger(tmp_path, legacy_request)
    if legacy_request is not None:
        assert legacy.request == legacy_request
    with state.store._connect() as conn:
        before = dict(
            conn.execute(
                "SELECT * FROM verification_runs WHERE run_id=?", (legacy.run_id,)
            ).fetchone()
        )

    with pytest.raises(ValueError, match="legacy verification audit is not executable"):
        mutation(state, legacy)

    with state.store._connect() as conn:
        after = dict(
            conn.execute(
                "SELECT * FROM verification_runs WHERE run_id=?", (legacy.run_id,)
            ).fetchone()
        )
    assert after == before


@pytest.mark.parametrize("mutation", _INERT_MUTATION_ENTRYPOINTS)
def test_inert_legacy_run_rejects_every_mutation_entrypoint(
    tmp_path, mutation
) -> None:
    _assert_inert_legacy_run_rejects_mutation(tmp_path, None, mutation)


@pytest.mark.parametrize("mutation", _INERT_MUTATION_ENTRYPOINTS)
def test_inert_artifact_provenance_legacy_run_rejects_mutations(
    tmp_path, mutation
) -> None:
    legacy_request = b4e2310_pre_trust_request()
    assert "artifact_provenance" in legacy_request
    _assert_inert_legacy_run_rejects_mutation(tmp_path, legacy_request, mutation)


def test_authenticated_artifact_starts_fresh_chain_beside_inert_legacy_audit(
    tmp_path,
) -> None:
    state, legacy = _migrated_legacy_ledger(tmp_path)
    with pytest.raises(
        ValueError, match="legacy verification audit requires an authenticated artifact"
    ):
        state.ingest(request("b" * 40))
    assert [run.run_id for run in state.list()] == [legacy.run_id]

    authenticated = verification_dispatch._authenticated_verification_request(
        request("b" * 40)
    )

    current = state.ingest(authenticated)

    assert current.status == "queued"
    assert current.authority_state == "canonical"
    assert current.run_id != legacy.run_id
    assert state.get(legacy.run_id) == legacy
    assert {run.run_id for run in state.list()} == {legacy.run_id, current.run_id}
    assert state.closure_ready(legacy.run_id) is False


def test_authenticated_same_head_v2_recovers_inert_audit_and_budget(tmp_path) -> None:
    initial = ledger(tmp_path)
    run_id, legacy_request = _write_deployed_v1_run(
        initial, supporting_issues=[]
    )
    state = ledger(tmp_path)
    legacy = state.get(run_id)
    assert legacy is not None
    assert legacy.status == "legacy_untrusted"
    attempts_before = state.attempts(run_id)
    budget_before = state.repair_budget_projection(run_id)
    observed = _live_observed_request(state, request())

    recovered = state.ingest(observed)

    assert recovered.run_id == run_id
    assert recovered.status == "queued"
    assert recovered.authority_state == "canonical"
    assert recovered.request == request()
    assert state.attempts(run_id) == attempts_before
    assert state.repair_budget_projection(run_id) == budget_before
    with state.store._connect() as conn:
        rows = conn.execute("SELECT * FROM verification_runs").fetchall()
    assert len(rows) == 1
    audit = json.loads(rows[0]["legacy_recovery_audit_json"])
    assert audit["contract"] == "verification_legacy_recovery_audit.v1"
    quarantined = audit["quarantined_row"]
    assert quarantined["status"] == "legacy_untrusted"
    assert json.loads(quarantined["request_json"]) == legacy_request
    assert quarantined["idempotency_key"] == legacy_request["idempotency_key"]


def test_concurrent_same_head_v2_recovery_converges_on_one_canonical_run(
    tmp_path,
) -> None:
    initial = ledger(tmp_path)
    run_id, _ = _write_deployed_v1_run(initial, supporting_issues=[])
    state = ledger(tmp_path)
    first = _live_observed_request(state, request())
    second = _live_observed_request(state, request())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(state.ingest, (first, second)))

    assert {result.run_id for result in results} == {run_id}
    assert {result.status for result in results} == {"queued"}
    with state.store._connect() as conn:
        row_count = conn.execute(
            "SELECT COUNT(*) FROM verification_runs"
        ).fetchone()[0]
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM verification_runs "
            "WHERE legacy_recovery_audit_json IS NOT NULL"
        ).fetchone()[0]
    assert row_count == audit_count == 1


def test_same_head_v2_recovery_without_fresh_live_fence_is_non_mutating(
    tmp_path,
) -> None:
    initial = ledger(tmp_path)
    run_id, _ = _write_deployed_v1_run(initial, supporting_issues=[])
    state = ledger(tmp_path)
    before = state.get(run_id)
    authenticated = verification_dispatch._authenticated_verification_request(
        request()
    )

    with pytest.raises(
        ValueError,
        match="canonical authority changed during live observation",
    ):
        state.ingest(authenticated)

    assert state.get(run_id) == before


def test_same_head_v2_recovery_rejects_intervening_ledger_write(
    tmp_path,
) -> None:
    initial = ledger(tmp_path)
    run_id, _ = _write_deployed_v1_run(initial, supporting_issues=[])
    state = ledger(tmp_path)
    observed = _live_observed_request(state, request())
    with state.store._connect() as conn:
        conn.execute(
            """
            INSERT INTO verification_attempts (
                attempt_id, run_id, attempt_kind, ordinal, session_id,
                capability, reasoning_effort, context_hash, outcome,
                finding_id, failure_domain, mechanism_id,
                receipt_json, created_at
            ) VALUES (
                'attempt-after-observation', ?, 'standard_repair', 2,
                '01900000-0000-7000-8000-000000000003', 'gpt-5.6-terra',
                'high', 'intervening-context', 'fixed', 'F-intervening',
                'review_code_correctness', 'legacy-closing-authority', '{}',
                '2026-07-16T10:00:02+00:00'
            )
            """,
            (run_id,),
        )
        conn.commit()

    with pytest.raises(
        ValueError,
        match="canonical authority changed during live observation",
    ):
        state.ingest(observed)

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "legacy_untrusted"
    assert len(state.attempts(run_id)) == 2


@pytest.mark.parametrize("corruption", ["legacy_as_queued", "canonical_as_legacy"])
def test_legacy_classification_pair_fails_closed_when_corrupted(
    tmp_path, corruption: str
) -> None:
    state, legacy = _migrated_legacy_ledger(tmp_path)
    with state.store._connect() as conn:
        if corruption == "legacy_as_queued":
            conn.execute(
                "UPDATE verification_runs SET status='queued' WHERE run_id=?",
                (legacy.run_id,),
            )
        else:
            conn.execute(
                "UPDATE verification_runs SET request_json=? WHERE run_id=?",
                (json.dumps(request(), sort_keys=True), legacy.run_id),
            )
        conn.commit()

    with pytest.raises(ValueError):
        state.get(legacy.run_id)
    with pytest.raises(ValueError):
        state.claim(legacy.run_id, "host")


_REQUEST_SCALAR_PATHS: tuple[tuple[str | int, ...], ...] = (
    ("contract_version",),
    ("stage",),
    ("repository",),
    ("pr_number",),
    ("linked_issue",),
    ("supporting_issues", 0),
    ("base_ref",),
    ("head_ref",),
    ("current_head_sha",),
    ("source_workflow", "name"),
    ("source_workflow", "run_id"),
    ("source_workflow", "run_attempt"),
    ("source_workflow", "head_sha"),
    ("artifact_provenance", "workflow_run_id"),
    ("artifact_provenance", "repository_id"),
    ("artifact_provenance", "artifact_name"),
    ("evidence_pack", "contract"),
    ("evidence_pack", "workflow_name"),
    ("evidence_pack", "artifact_name"),
    ("evidence_pack", "repository"),
    ("evidence_pack", "pr_number"),
    ("evidence_pack", "head_sha"),
    ("live_truth", "repository"),
    ("live_truth", "pr_number"),
    ("live_truth", "current_head_sha"),
    ("live_truth", "source_run_id"),
    ("generated_at",),
    ("idempotency_key",),
)


def _replace_request_path(
    payload: dict[str, object], path: tuple[str | int, ...], value: object
) -> None:
    target: object = payload
    for component in path[:-1]:
        if isinstance(component, int):
            assert isinstance(target, list)
            target = target[component]
        else:
            assert isinstance(target, dict)
            target = target[component]
    final = path[-1]
    if isinstance(final, int):
        assert isinstance(target, list)
        target[final] = value
    else:
        assert isinstance(target, dict)
        target[final] = value


@pytest.mark.parametrize(
    "path", _REQUEST_SCALAR_PATHS, ids=lambda path: ".".join(map(str, path))
)
@pytest.mark.parametrize(
    "invalid_scalar",
    [{"secret": "must-not-persist"}, ["must-not-persist"], True],
    ids=("object", "list", "boolean"),
)
def test_ingest_rejects_noncanonical_type_for_every_request_scalar(
    tmp_path,
    path: tuple[str | int, ...],
    invalid_scalar: object,
) -> None:
    state = ledger(tmp_path)
    payload = request()
    payload["supporting_issues"] = [3626]
    _replace_request_path(payload, path, invalid_scalar)

    with pytest.raises(ValueError) as rejected:
        state.ingest(payload)

    assert "must-not-persist" not in str(rejected.value)
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    "path",
    [
        ("pr_number",),
        ("linked_issue",),
        ("source_workflow", "run_id"),
        ("evidence_pack", "pr_number"),
        ("live_truth", "pr_number"),
        ("live_truth", "source_run_id"),
    ],
    ids=lambda path: ".".join(path),
)
def test_ingest_rejects_boolean_identity_aliases(
    tmp_path, path: tuple[str, ...]
) -> None:
    state = ledger(tmp_path)
    payload = request()
    _replace_request_path(payload, path, True)

    with pytest.raises(ValueError):
        state.ingest(payload)

    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 0


def test_legacy_unknown_field_replay_fails_closed_without_exposure_or_mutation(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    secret = "legacy-private-key-must-not-escape"
    with state.store._connect() as conn:
        legacy = dict(run.request)
        legacy["credential"] = {"private_key": secret}
        conn.execute(
            "UPDATE verification_runs SET request_json=? WHERE run_id=?",
            (json.dumps(legacy), run.run_id),
        )
        conn.execute(
            """
            INSERT INTO verification_attempts (
                attempt_id, run_id, attempt_kind, ordinal, session_id, capability,
                reasoning_effort, context_hash, outcome, receipt_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-attempt",
                run.run_id,
                "standard_repair",
                1,
                "legacy-session",
                "sol",
                "xhigh",
                "legacy-context",
                "failed",
                None,
                "2026-07-15T00:00:00+00:00",
            ),
        )
        conn.commit()
        before_run = dict(
            conn.execute(
                "SELECT * FROM verification_runs WHERE run_id=?", (run.run_id,)
            ).fetchone()
        )
        before_attempts = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM verification_attempts WHERE run_id=?", (run.run_id,)
            )
        ]

    with pytest.raises(ValueError) as direct_read:
        state.get(run.run_id)
    with pytest.raises(ValueError) as replay:
        state.ingest(request())

    assert secret not in str(direct_read.value)
    assert secret not in str(replay.value)
    with state.store._connect() as conn:
        after_run = dict(
            conn.execute(
                "SELECT * FROM verification_runs WHERE run_id=?", (run.run_id,)
            ).fetchone()
        )
        after_attempts = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM verification_attempts WHERE run_id=?", (run.run_id,)
            )
        ]
    assert after_run == before_run
    assert after_attempts == before_attempts


_VERIFICATION_MUTATION_TABLES = (
    ("verification_runs", "run_id"),
    ("verification_attempts", "attempt_id"),
    ("verification_exceptions", "exception_id"),
    ("dispatcher_events", "event_id"),
    ("dispatcher_leases", "lease_id"),
)


def _verification_state_snapshot(state) -> dict[str, list[dict[str, object]]]:
    with state.store._connect() as conn:
        return {
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {key}")]
            for table, key in _VERIFICATION_MUTATION_TABLES
        }


@pytest.mark.parametrize(
    "mutation",
    [
        "ingest",
        "claim",
        "heartbeat",
        "start",
        "terminal",
        "rebind_head",
        "backoff",
        "defer_unclaimed",
        "supersede_unclaimed",
        "record_attempt",
        "record_attempt_batch",
        "exception",
    ],
)
@pytest.mark.parametrize(
    "corruption",
    [
        "unknown_request_field",
        "noncanonical_run_id",
        "idempotency_key_mismatch",
        "contract_version_mismatch",
        "repository_mismatch",
        "pr_number_mismatch",
        "head_sha_mismatch",
        "stage_mismatch",
        "malformed_current_head_sha",
        "malformed_verified_head_sha",
        "inconsistent_verified_current_heads",
        "verified_head_on_uncompleted_run",
        "malformed_supporting_authority",
    ],
)
def test_every_ledger_mutation_rejects_corrupted_run_before_durable_change(
    tmp_path, mutation: str, corruption: str
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = None
    if mutation not in {
        "ingest",
        "claim",
        "defer_unclaimed",
        "supersede_unclaimed",
    }:
        claimed = state.claim(run.run_id, "coordinator")
        assert claimed.lease_id is not None

    secret = "corrupted-row-private-key-must-not-escape"
    raw_corruption = secret
    target_run_id = run.run_id
    with state.store._connect() as conn:
        if corruption == "unknown_request_field":
            corrupted_request = dict(run.request)
            corrupted_request["credential"] = {"private_key": secret}
            conn.execute(
                "UPDATE verification_runs SET request_json=? WHERE run_id=?",
                (json.dumps(corrupted_request), run.run_id),
            )
        elif corruption == "noncanonical_run_id":
            target_run_id = f"vrun-{secret}"
            conn.execute(
                "UPDATE verification_runs SET run_id=? WHERE run_id=?",
                (target_run_id, run.run_id),
            )
        elif corruption == "idempotency_key_mismatch":
            conn.execute(
                "UPDATE verification_runs SET idempotency_key=? WHERE run_id=?",
                (secret, run.run_id),
            )
        elif corruption == "contract_version_mismatch":
            conn.execute(
                "UPDATE verification_runs SET contract_version=? WHERE run_id=?",
                (secret, run.run_id),
            )
        elif corruption == "repository_mismatch":
            conn.execute(
                "UPDATE verification_runs SET repository=? WHERE run_id=?",
                (secret, run.run_id),
            )
        elif corruption == "pr_number_mismatch":
            raw_corruption = "999999999"
            conn.execute(
                "UPDATE verification_runs SET pr_number=? WHERE run_id=?",
                (int(raw_corruption), run.run_id),
            )
        elif corruption == "head_sha_mismatch":
            conn.execute(
                "UPDATE verification_runs SET head_sha=? WHERE run_id=?",
                (secret, run.run_id),
            )
        elif corruption == "stage_mismatch":
            conn.execute(
                "UPDATE verification_runs SET stage=? WHERE run_id=?",
                (secret, run.run_id),
            )
        elif corruption == "malformed_current_head_sha":
            conn.execute(
                "UPDATE verification_runs SET current_head_sha=? WHERE run_id=?",
                (secret, run.run_id),
            )
        elif corruption == "malformed_verified_head_sha":
            conn.execute(
                "UPDATE verification_runs SET verified_head_sha=? WHERE run_id=?",
                (secret, run.run_id),
            )
        elif corruption == "malformed_supporting_authority":
            conn.execute(
                "UPDATE verification_runs SET supporting_authority_json=? "
                "WHERE run_id=?",
                (json.dumps({"private_key": secret}), run.run_id),
            )
        else:
            assert corruption in {
                "inconsistent_verified_current_heads",
                "verified_head_on_uncompleted_run",
            }
            raw_corruption = (
                "b" * 40 if corruption.startswith("inconsistent") else run.head_sha
            )
            conn.execute(
                "UPDATE verification_runs SET verified_head_sha=? WHERE run_id=?",
                (raw_corruption, run.run_id),
            )
        conn.commit()

    before = _verification_state_snapshot(state)
    lease_id = claimed.lease_id if claimed is not None else "unused-lease"
    assert lease_id is not None

    with pytest.raises(ValueError) as rejected:
        if mutation == "ingest":
            state.ingest(request())
        elif mutation == "claim":
            state.claim(target_run_id, "coordinator")
        elif mutation == "heartbeat":
            state.heartbeat(target_run_id, "coordinator", lease_id)
        elif mutation == "start":
            state.start(
                target_run_id,
                "coordinator",
                lease_id,
                "session",
                {"head": run.head_sha},
            )
        elif mutation == "terminal":
            state.terminal(
                target_run_id,
                "failed",
                {"outcome": "blocked"},
                holder="coordinator",
                lease_id=lease_id,
            )
        elif mutation == "rebind_head":
            state.rebind_head(
                target_run_id,
                "b" * 40,
                expected_head_sha=run.head_sha,
                observed_repository=run.repository,
                observed_pr_number=run.pr_number,
                observed_head_sha="b" * 40,
                holder="coordinator",
                lease_id=lease_id,
            )
        elif mutation == "backoff":
            state.backoff(
                target_run_id,
                {"outcome": "deferred"},
                "2030-01-01T00:00:00+00:00",
                holder="coordinator",
                lease_id=lease_id,
            )
        elif mutation == "defer_unclaimed":
            state.defer_unclaimed(
                target_run_id,
                {"outcome": "deferred"},
                "2030-01-01T00:00:00+00:00",
            )
        elif mutation == "supersede_unclaimed":
            state.supersede_unclaimed(
                target_run_id, {"outcome": "superseded"}, reason="stale_head"
            )
        elif mutation == "record_attempt":
            state.record_attempt(
                target_run_id,
                "standard_repair",
                "session",
                "sol",
                "xhigh",
                {"head": run.head_sha},
                "failed",
                holder="coordinator",
                lease_id=lease_id,
            )
        elif mutation == "record_attempt_batch":
            state.record_attempt_batch(
                target_run_id,
                "batch",
                1,
                run.head_sha,
                lambda _attempts, _attempt_id: [],
                holder="coordinator",
                lease_id=lease_id,
            )
        else:
            assert mutation == "exception"
            state.exception(
                target_run_id,
                "requires_human",
                {"summary": "blocked"},
                holder="coordinator",
                lease_id=lease_id,
            )

    assert secret not in str(rejected.value)
    assert raw_corruption not in str(rejected.value)
    assert _verification_state_snapshot(state) == before


class _ClaimClock:
    def __init__(self) -> None:
        self._value = CLAIM_PRE_LOCK
        self._lock = Lock()
        self.samples: list[str] = []

    def now(self) -> str:
        with self._lock:
            self.samples.append(self._value)
            return self._value

    def future(self, seconds: int) -> str:
        current = datetime.fromisoformat(self.now())
        return (current + timedelta(seconds=seconds)).isoformat(timespec="microseconds")

    def cross_lock_wait(self) -> None:
        with self._lock:
            self._value = CLAIM_POST_LOCK


class _ClaimConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        write_attempted: Event,
        write_acquired: Event,
    ) -> None:
        self._connection = connection
        self._write_attempted = write_attempted
        self._write_acquired = write_acquired

    def __enter__(self) -> _ClaimConnection:
        self._connection.__enter__()
        return self

    def __exit__(self, *args: object) -> bool | None:
        return self._connection.__exit__(*args)

    def execute(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> sqlite3.Cursor:
        if " ".join(sql.lower().split()).startswith("begin immediate"):
            self._write_attempted.set()
            result = self._connection.execute(sql, parameters)
            self._write_acquired.set()
            return result
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


def _claim_across_write_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ttl_seconds: int,
) -> tuple[VerificationRun, _ClaimClock, Event]:
    state = ledger(tmp_path)
    run = state.ingest(request())
    raw_connect = state.store._connect
    blocker = raw_connect()
    blocker.execute("BEGIN IMMEDIATE")
    write_attempted = Event()
    write_acquired = Event()
    clock = _ClaimClock()

    def instrumented_connect() -> _ClaimConnection:
        return _ClaimConnection(raw_connect(), write_attempted, write_acquired)

    monkeypatch.setattr(state.store, "_connect", instrumented_connect)
    monkeypatch.setattr(verification_dispatch, "_now", clock.now)
    monkeypatch.setattr(verification_dispatch, "_future", clock.future)
    outcome: dict[str, object] = {}

    def claim() -> None:
        try:
            outcome["result"] = state.claim(
                run.run_id, "post-lock-coordinator", ttl_seconds=ttl_seconds
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=claim, daemon=True)
    worker.start()
    try:
        assert write_attempted.wait(timeout=2), "claim never attempted the SQLite write lock"
        assert worker.is_alive(), "claim did not wait on the competing SQLite writer"
        clock.cross_lock_wait()
        blocker.commit()
        worker.join(timeout=5)
    finally:
        if blocker.in_transaction:
            blocker.rollback()
        blocker.close()
        worker.join(timeout=5)

    assert not worker.is_alive(), "claim did not finish after the lock was released"
    assert "error" not in outcome, outcome
    claimed = outcome.get("result")
    assert isinstance(claimed, VerificationRun), outcome
    return claimed, clock, write_acquired


def test_claim_lock_wait_samples_time_after_authoritative_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claimed, clock, write_acquired = _claim_across_write_lock(
        tmp_path, monkeypatch, ttl_seconds=10
    )

    assert write_acquired.is_set()
    assert clock.samples
    assert clock.samples[0] == CLAIM_POST_LOCK


def test_claim_lock_wait_never_commits_already_expired_lease(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ttl_seconds = 10
    claimed, _clock, write_acquired = _claim_across_write_lock(
        tmp_path, monkeypatch, ttl_seconds=ttl_seconds
    )

    expected_expiry = (
        datetime.fromisoformat(CLAIM_POST_LOCK) + timedelta(seconds=ttl_seconds)
    ).isoformat(timespec="microseconds")
    assert write_acquired.is_set()
    assert claimed.lease_expires_at == expected_expiry


def test_existing_schema_v2_upgrades_to_current_verification_schema(tmp_path) -> None:
    db = tmp_path / "dispatcher.sqlite3"
    initial = SqliteStore(db)
    initial.initialize()
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE verification_exceptions")
        conn.execute("DROP TABLE verification_attempts")
        conn.execute("DROP TABLE verification_runs")
        conn.execute("UPDATE dispatcher_meta SET value='2' WHERE key='schema_version'")
        conn.commit()

    upgraded = SqliteStore(db)
    upgraded.list_tasks()
    with sqlite3.connect(db) as conn:
        version = conn.execute(
            "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'verification_%'"
            )
        }
    assert version == "6"
    assert tables == {"verification_runs", "verification_attempts", "verification_exceptions"}


def test_existing_schema_v3_backfills_current_head_without_losing_request_audit(
    tmp_path,
) -> None:
    db = tmp_path / "dispatcher.sqlite3"
    state = ledger(tmp_path)
    original = state.ingest(request())
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE verification_runs DROP COLUMN verified_head_sha")
        conn.execute("ALTER TABLE verification_runs DROP COLUMN current_head_sha")
        conn.execute("ALTER TABLE verification_runs DROP COLUMN supporting_authority_json")
        downgrade_verification_schema_to_v3(conn)
        conn.commit()

    migrated = ledger(tmp_path).get(original.run_id)

    assert migrated is not None
    assert migrated.requested_head_sha == original.requested_head_sha
    assert migrated.head_sha == original.requested_head_sha
    assert migrated.verified_head_sha is None
    with sqlite3.connect(db) as conn:
        supporting_authority, closing_authority = conn.execute(
            "SELECT supporting_authority_json, closing_authority_json "
            "FROM verification_runs WHERE run_id=?",
            (original.run_id,),
        ).fetchone()
    assert json.loads(supporting_authority) == original.request["supporting_issues"]
    assert json.loads(closing_authority) == original.request["closing_issues"]


def test_schema_v4_backfills_closing_authority_without_resetting_chain(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    original = state.ingest(request())
    claim = state.claim(original.run_id, "host")
    assert claim.lease_id is not None
    state.start(
        original.run_id,
        "host",
        claim.lease_id,
        "01900000-0000-7000-8000-000000000001",
        {"head_sha": original.head_sha},
    )
    state.record_attempt(
        original.run_id,
        "standard_repair",
        "01900000-0000-7000-8000-000000000001",
        "gpt-5.6-terra",
        "high",
        {"head_sha": original.head_sha},
        "fixed",
        {
            "finding_id": "F-v4",
            "failure_domain": "review_code_correctness",
            "mechanism_id": "closing-authority",
        },
        holder="host",
        lease_id=claim.lease_id,
    )
    before_attempts = state.attempts(original.run_id)
    with sqlite3.connect(state.store.db_path) as conn:
        conn.execute("ALTER TABLE verification_runs DROP COLUMN closing_authority_json")
        conn.execute("UPDATE dispatcher_meta SET value='4' WHERE key='schema_version'")
        conn.commit()

    migrated_state = ledger(tmp_path)
    migrated = migrated_state.get(original.run_id)

    assert migrated is not None
    assert migrated.closing_authority == (3603,)
    assert migrated.status == "running"
    assert migrated.repair_budget_policy == "v2"
    assert migrated_state.attempts(original.run_id) == before_attempts


def test_schema_v5_adds_legacy_recovery_audit_without_resetting_chain(
    tmp_path,
) -> None:
    state = ledger(tmp_path)
    original = state.ingest(request())
    with sqlite3.connect(state.store.db_path) as conn:
        conn.execute(
            "ALTER TABLE verification_runs DROP COLUMN legacy_recovery_audit_json"
        )
        conn.execute(
            "UPDATE dispatcher_meta SET value='5' WHERE key='schema_version'"
        )
        conn.commit()

    migrated_state = ledger(tmp_path)
    migrated = migrated_state.get(original.run_id)

    assert migrated == original
    with sqlite3.connect(state.store.db_path) as conn:
        version = conn.execute(
            "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
        ).fetchone()[0]
        audit = conn.execute(
            "SELECT legacy_recovery_audit_json FROM verification_runs "
            "WHERE run_id=?",
            (original.run_id,),
        ).fetchone()[0]
    assert version == "6"
    assert audit is None


@pytest.mark.parametrize("supporting_issues", [[], [3626]])
@pytest.mark.parametrize("existing_schema", ["3", "4", "5"])
def test_schema_reconciliation_quarantines_v1_without_authenticated_closure(
    tmp_path, existing_schema: str, supporting_issues: list[int]
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _write_deployed_v1_run(
        state,
        supporting_issues=supporting_issues,
    )
    if existing_schema == "3":
        with sqlite3.connect(state.store.db_path) as conn:
            conn.execute("ALTER TABLE verification_runs DROP COLUMN supporting_authority_json")
            downgrade_verification_schema_to_v3(conn)
            conn.commit()
    elif existing_schema == "4":
        with sqlite3.connect(state.store.db_path) as conn:
            conn.execute(
                "ALTER TABLE verification_runs DROP COLUMN closing_authority_json"
            )
            conn.execute("UPDATE dispatcher_meta SET value='4' WHERE key='schema_version'")
            conn.commit()

    migrated_state = ledger(tmp_path)
    migrated = migrated_state.get(run_id)

    assert migrated is not None
    assert migrated.status == "legacy_untrusted"
    assert migrated.authority_state == "legacy_untrusted"
    assert migrated.supporting_authority == ()
    assert migrated.closing_authority == ()
    assert migrated.claimed_by is None
    assert migrated.lease_id is None
    assert migrated.coordinator_session_id is None
    assert migrated.context_pack is None
    assert migrated.repair_budget_policy == ("v1" if existing_schema == "3" else "v2")
    attempts = migrated_state.attempts(run_id)
    assert len(attempts) == 1
    assert attempts[0]["attempt_id"] == "attempt-v1-closure"
    assert attempts[0]["kind"] == "standard_repair"
    budget = migrated_state.repair_budget_projection(run_id)
    assert budget["policy_version"] == migrated.repair_budget_policy
    mechanism = budget["mechanisms"][0]
    assert mechanism["standard_used"] == 1
    assert mechanism["standard_remaining"] == 1
    assert mechanism["escalated_used"] == 0
    assert mechanism["escalated_remaining"] == 2


@pytest.mark.parametrize("supporting_issues", [[], [3626]])
def test_ingest_rejects_v1_without_authenticated_closure_before_persistence(
    tmp_path, supporting_issues: list[int]
) -> None:
    payload = _canonical_v1_request(supporting_issues=supporting_issues)
    state = ledger(tmp_path)

    with pytest.raises(ValueError, match="fresh v2 artifact"):
        state.ingest(payload)

    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 0


def test_ingest_rejects_over_limit_closing_authority_before_persistence(
    tmp_path,
) -> None:
    payload = request()
    extra = [4000 + index for index in range(MAX_CLOSING_ISSUES)]
    payload["closing_issues"] = [3603, *extra]
    payload["supporting_issues"] = extra
    state = ledger(tmp_path)

    with pytest.raises(ValueError, match="closing issues are malformed"):
        state.ingest(payload)

    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 0


def test_ingest_claim_and_terminal_lifecycle_is_idempotent(tmp_path) -> None:
    state = ledger(tmp_path)
    first = state.ingest(request())
    assert state.ingest(request()).run_id == first.run_id
    claimed = state.claim(first.run_id, "coordinator")
    assert state.heartbeat(first.run_id, "coordinator", claimed.lease_id).lease_id == claimed.lease_id
    running = state.start(first.run_id, "coordinator", claimed.lease_id, "thread-1", {"head": first.head_sha})
    assert running.status == "running"
    done = state.terminal(first.run_id, "failed", {"outcome": "blocked"}, holder="coordinator", lease_id=claimed.lease_id)
    assert done.status == "failed"
    with pytest.raises(ValueError):
        state.terminal(first.run_id, "failed", {"outcome": "other"}, holder="coordinator", lease_id=claimed.lease_id)

    assert state.ingest(request()).status == "failed"
    with pytest.raises(ValueError, match="canonical chain is terminal: failed"):
        state.ingest(request("b" * 40))


def test_same_head_terminal_replay_rejects_conflicting_closing_set(tmp_path) -> None:
    state = ledger(tmp_path)
    original_request = request()
    original_request["supporting_issues"] = [3626]
    first = state.ingest(original_request)
    claimed = state.claim(first.run_id, "coordinator")
    assert claimed.lease_id is not None
    state.start(
        first.run_id,
        "coordinator",
        claimed.lease_id,
        "thread-closing-authority",
        {"head": first.head_sha},
    )
    state.terminal(
        first.run_id,
        "failed",
        {"outcome": "blocked"},
        holder="coordinator",
        lease_id=claimed.lease_id,
    )
    conflicting_request = json.loads(json.dumps(original_request))
    conflicting_request["closing_issues"] = [3626]

    with pytest.raises(ValueError, match="idempotency authority conflict"):
        state.ingest(conflicting_request)

    stored = state.get(first.run_id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.closing_authority == (3603,)
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 1


def test_duplicate_and_concurrent_claims_start_one_run(tmp_path) -> None:
    state = ledger(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda _: state.ingest(request()), range(4)))
    assert len({run.run_id for run in runs}) == 1
    run_id = runs[0].run_id

    def claim(holder: str) -> bool:
        try:
            state.claim(run_id, holder)
        except ValueError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, ["one", "two"]))
    assert outcomes.count(True) == 1

    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (run_id,),
        )
        conn.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        recovered = list(pool.map(claim, ["recovery-one", "recovery-two"]))
    assert recovered.count(True) == 1
