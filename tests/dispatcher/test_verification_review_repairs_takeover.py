from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Callable

import pytest

from app.dispatcher.verification_consumer import (
    CodexExecLauncher,
    GhCliVerificationSource,
    VerificationConsumer,
    _governing_contract_matches,
    _trusted_evidence_urls,
)
from app.dispatcher.verification_agent_loop import valid_human_exception_packet
from app.dispatcher.verification_dispatch import (
    VerificationDispatchLedger,
    _live_observed_verification_request,
)
from tests.dispatcher.test_verification_consumer import (
    Auth,
    GREEN,
    Launcher,
    Truth,
    eligible_pr,
    green_checks,
)
from tests.dispatcher.test_verification_dispatch import _migrated_legacy_ledger
from tests.dispatcher.verification_helpers import (
    HEAD,
    REPO,
    ledger,
    pre_trust_request,
    request,
)


REPAIRED_HEAD = "b" * 40
SECOND_REPAIRED_HEAD = "d" * 40
THIRD_REPAIRED_HEAD = "e" * 40
PRODUCER_HEAD = "c" * 40
PRODUCER_RUN_ID = 123
REPOSITORY_ID = 456
SYNTHETIC_PRIVATE_VALUE = "SYNTHETIC_PRIVATE_VALUE"


def _receipt() -> dict[str, object]:
    _, receipt = Launcher().launch({})
    return receipt


def test_coordinator_subprocess_receives_only_minimal_non_secret_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, object]] = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = "\n".join(
            (
                json.dumps(
                    {
                        "type": "thread.started",
                        "thread_id": "01900000-0000-7000-8000-000000000101",
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(_receipt()),
                        },
                    }
                ),
            )
        )

    def runner(_command: list[str], **kwargs: object) -> Result:
        captured.append(dict(kwargs))
        return Result()

    monkeypatch.setenv("GH_TOKEN", SYNTHETIC_PRIVATE_VALUE)
    monkeypatch.setenv("DATABASE_PASSWORD", SYNTHETIC_PRIVATE_VALUE)
    monkeypatch.setenv("SYNTHETIC_UNRELATED_ENV", SYNTHETIC_PRIVATE_VALUE)
    launcher = CodexExecLauncher(
        tmp_path,
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )

    launcher.launch({"head_sha": HEAD})

    env = captured[0]["env"]
    assert isinstance(env, dict)
    expected_host_keys = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_COLOR",
        "PATH",
        "TERM",
        "TMPDIR",
    }
    assert set(env).issubset(
        expected_host_keys | {"PKM_VERIFICATION_PROCESS_TREE"}
    )
    assert env.get("HOME") == os.environ.get("HOME")
    assert env.get("PATH") == os.environ.get("PATH")
    assert SYNTHETIC_PRIVATE_VALUE not in env.values()


@pytest.mark.parametrize("location", ["top", "nested"])
def test_unknown_request_fields_never_reach_sqlite(
    tmp_path: Path, location: str
) -> None:
    state = ledger(tmp_path)
    payload = request()
    if location == "top":
        payload["synthetic_secret_field"] = SYNTHETIC_PRIVATE_VALUE
    else:
        live_truth = dict(payload["live_truth"])
        live_truth["synthetic_secret_field"] = {
            "nested": SYNTHETIC_PRIVATE_VALUE
        }
        payload["live_truth"] = live_truth

    with pytest.raises(ValueError, match="unknown properties") as captured:
        state.ingest(payload)

    assert SYNTHETIC_PRIVATE_VALUE not in str(captured.value)
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_runs").fetchone()[0] == 0
    assert SYNTHETIC_PRIVATE_VALUE.encode() not in state.store.db_path.read_bytes()


class _ModelOptionLauncher(Launcher):
    def launch(self, context_pack, **kwargs):
        session_id, receipt = super().launch(context_pack, **kwargs)
        packet = receipt["human_exception"]
        assert isinstance(packet, dict)
        packet["options"] = [
            {
                "id": "model-option-alpha",
                "label": "Model label alpha",
                "consequence": "Model consequence alpha",
            },
            {
                "id": "model-option-beta",
                "label": "Model label beta",
                "consequence": "Model consequence beta",
            },
            {
                "id": "model-option-gamma",
                "label": "Model label gamma",
                "consequence": "Model consequence gamma",
            },
        ]
        packet["no_action_option"] = "model-option-alpha"
        packet["recommended_option"] = "model-option-beta"
        return session_id, receipt


def test_model_option_ids_are_pseudonymized_with_relationships_remapped(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _ModelOptionLauncher(),
        "host",
    ).consume(request())

    with state.store._connect() as conn:
        row = conn.execute(
            "SELECT packet_json FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()
    assert row is not None
    packet = json.loads(row["packet_json"])
    assert [option["id"] for option in packet["options"]] == [
        "hold",
        "authorize",
        "select-alternative",
    ]
    assert packet["no_action_option"] == packet["options"][0]["id"]
    assert packet["recommended_option"] == packet["options"][1]["id"]
    encoded = json.dumps(packet, sort_keys=True)
    assert "model-option-alpha" not in encoded
    assert "model-option-beta" not in encoded
    assert "model-option-gamma" not in encoded


class _EvidenceUrlLauncher(Launcher):
    def launch(self, context_pack, **kwargs):
        session_id, receipt = super().launch(context_pack, **kwargs)
        exact_urls = (
            f"https://github.com/{REPO}/issues/3603",
            f"https://github.com/{REPO}/pull/3603",
            f"https://github.com/{REPO}/actions/runs/99",
            f"https://github.com/{REPO}/actions/runs/123",
        )
        rejected_urls = (
            "https://github.com/synthetic-owner/synthetic-repository/issues/3603",
            f"https://github.com/{REPO}/issues/999999",
            f"https://github.com/{REPO}/pull/999999",
            f"https://github.com/{REPO}/actions/runs/999999",
        )
        packet = receipt["human_exception"]
        assert isinstance(packet, dict)
        packet["evidence"] = [" ".join((*exact_urls, *rejected_urls))]
        receipt["summary"] = " ".join((*exact_urls, *rejected_urls))
        return session_id, receipt


def test_durable_evidence_urls_are_bound_to_authenticated_run_identity(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    source, _ = _gh_source(request())
    authenticated = source.pending_requests(REPO)[0]
    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        _EvidenceUrlLauncher(),
        "host",
    ).consume(authenticated)

    with state.store._connect() as conn:
        packet_json = conn.execute(
            "SELECT packet_json FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0]
        request_json = conn.execute(
            "SELECT request_json FROM verification_runs WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0]
    durable = json.dumps(
        {
            "attempts": state.attempts(result.run_id),
            "packet": json.loads(packet_json),
            "request": json.loads(request_json),
            "terminal": result.terminal_receipt,
        },
        sort_keys=True,
    )
    for exact_url in (
        f"https://github.com/{REPO}/issues/3603",
        f"https://github.com/{REPO}/pull/3603",
        f"https://github.com/{REPO}/actions/runs/99",
        f"https://github.com/{REPO}/actions/runs/123",
    ):
        assert exact_url in durable
    assert "synthetic-owner" not in durable
    assert "/999999" not in durable


def _gh_source(
    payload: dict[str, object],
    *,
    producer_updates: dict[str, object] | None = None,
    listing_updates: dict[str, object] | None = None,
    source_updates: dict[str, object] | None = None,
) -> tuple[GhCliVerificationSource, list[str]]:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(payload))

    artifact_provenance = payload["artifact_provenance"]
    assert isinstance(artifact_provenance, dict)
    artifact_name = str(artifact_provenance["artifact_name"])
    producer = {
        "id": PRODUCER_RUN_ID,
        "run_attempt": 1,
        "name": "Verification Dispatch Request",
        "path": ".github/workflows/verification-dispatch-request.yml",
        "event": "workflow_run",
        "status": "completed",
        "conclusion": "success",
        "head_sha": PRODUCER_HEAD,
        "head_branch": "main",
        "repository": {"id": REPOSITORY_ID, "full_name": REPO},
        "head_repository": {"id": REPOSITORY_ID, "full_name": REPO},
    }
    producer.update(producer_updates or {})
    listing_run = {
        "id": PRODUCER_RUN_ID,
        "repository_id": REPOSITORY_ID,
        "head_repository_id": REPOSITORY_ID,
        "head_sha": PRODUCER_HEAD,
        "head_branch": "main",
    }
    listing_run.update(listing_updates or {})
    source = {
        "id": 99,
        "run_attempt": 1,
        "name": "CI Smoke",
        "path": ".github/workflows/ci-smoke.yaml",
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_sha": payload["current_head_sha"],
        "repository": {"id": REPOSITORY_ID, "full_name": REPO},
        "head_repository": {"id": REPOSITORY_ID, "full_name": REPO},
    }
    source.update(source_updates or {})

    class Result:
        returncode = 0

        def __init__(self, stdout: str | bytes) -> None:
            self.stdout = stdout

    endpoints: list[str] = []

    def runner(command: list[str], **_kwargs: object) -> Result:
        endpoint = command[-1]
        endpoints.append(endpoint)
        if endpoint.startswith(
            f"repos/{REPO}/actions/workflows/verification-dispatch-request.yml/runs"
            "?per_page=100&status=success&created=>="
        ):
            return Result(json.dumps({"workflow_runs": [{"id": PRODUCER_RUN_ID}]}))
        if endpoint.endswith(f"actions/runs/{PRODUCER_RUN_ID}/artifacts?per_page=100"):
            return Result(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 7,
                                "name": artifact_name,
                                "size_in_bytes": len(archive_bytes.getvalue()),
                                "expired": False,
                                "workflow_run": listing_run,
                            }
                        ]
                    }
                )
            )
        if re.search(r"actions/runs/[1-9][0-9]*\Z", endpoint) and not endpoint.endswith(
            "actions/runs/99"
        ):
            return Result(json.dumps(producer))
        if endpoint.endswith("artifacts/7/zip"):
            return Result(archive_bytes.getvalue())
        if endpoint.endswith("actions/runs/99"):
            return Result(json.dumps(source))
        raise AssertionError(f"unexpected GitHub read: {endpoint}")

    return GhCliVerificationSource(runner=runner), endpoints


def _live_observed_artifact(
    state: VerificationDispatchLedger,
    payload: dict[str, object],
    *,
    observed_supporting_issues: tuple[int, ...] | None = None,
) -> dict[str, object]:
    source, _ = _gh_source(payload)
    authenticated = source.pending_requests(REPO)[0]
    canonical_chain_token = state.canonical_chain_token(authenticated)
    supporting = payload.get("supporting_issues")
    closing = payload.get("closing_issues")
    assert isinstance(supporting, list)
    assert isinstance(closing, list)
    return _live_observed_verification_request(
        authenticated,
        observed_repository=payload["repository"],
        observed_pr_number=payload["pr_number"],
        observed_head_sha=payload["current_head_sha"],
        observed_state="open",
        observed_merged_at=None,
        observed_draft=False,
        observed_linked_issue=payload["linked_issue"],
        observed_closing_issues=tuple(closing),
        observed_supporting_issues=(
            observed_supporting_issues
            if observed_supporting_issues is not None
            else tuple(supporting)
        ),
        observed_final_review_rounds=payload["final_review_rounds"],
        canonical_chain_token=canonical_chain_token,
    )


def test_gh_source_authenticates_producer_before_reading_request_json() -> None:
    payload = request()
    source, endpoints = _gh_source(payload)

    assert source.pending_requests(REPO) == [payload]
    assert endpoints[0].startswith(
        f"repos/{REPO}/actions/workflows/verification-dispatch-request.yml/runs"
        "?per_page=100&status=success&created=>="
    )
    assert endpoints[1:] == [
        f"repos/{REPO}/actions/runs/{PRODUCER_RUN_ID}/artifacts?per_page=100",
        f"repos/{REPO}/actions/runs/{PRODUCER_RUN_ID}",
        f"repos/{REPO}/actions/artifacts/7/zip",
        f"repos/{REPO}/actions/runs/99",
    ]


@pytest.mark.parametrize(
    ("producer_updates", "listing_updates"),
    [
        ({"id": 999}, {}),
        ({"name": "Synthetic Producer"}, {}),
        ({"path": ".github/workflows/synthetic.yml"}, {}),
        ({"event": "pull_request"}, {}),
        ({"status": "in_progress"}, {}),
        ({"conclusion": "failure"}, {}),
        ({"head_sha": "d" * 40}, {}),
        ({"repository": {"id": REPOSITORY_ID, "full_name": "other/repo"}}, {}),
        ({}, {"id": 999}),
        ({}, {"head_repository_id": 999}),
    ],
)
def test_gh_source_rejects_untrusted_producer_before_artifact_download(
    producer_updates: dict[str, object], listing_updates: dict[str, object]
) -> None:
    source, endpoints = _gh_source(
        request(),
        producer_updates=producer_updates,
        listing_updates=listing_updates,
    )

    with pytest.raises(
        ValueError, match="verification artifact uploader workflow identity mismatch"
    ):
        source.pending_requests(REPO)

    expected_run_id = listing_updates.get("id", PRODUCER_RUN_ID)
    assert endpoints[-1] == f"repos/{REPO}/actions/runs/{expected_run_id}"
    assert not any(endpoint.endswith("artifacts/7/zip") for endpoint in endpoints)


def _record_exhausted_chain(
    state: VerificationDispatchLedger,
    payload: dict[str, object],
    *,
    expire_lease: bool = True,
    authenticate_with_live_observation: bool = False,
) -> tuple[str, list[dict[str, object]]]:
    run = state.ingest(
        _live_observed_artifact(state, payload)
        if authenticate_with_live_observation
        else payload
    )
    claimed = state.claim(run.run_id, "head-a-host")
    lease_id = claimed.lease_id or ""
    state.start(
        run.run_id,
        "head-a-host",
        lease_id,
        "01900000-0000-7000-8000-000000000102",
        {"head_sha": HEAD},
    )
    for index, kind in enumerate(
        ("standard_repair", "standard_repair", "escalated_repair", "escalated_repair"),
        start=1,
    ):
        state.record_attempt(
            run.run_id,
            kind,
            f"repair-session-{index}",
            "gpt-5.6-sol" if kind == "escalated_repair" else "gpt-5.6-terra",
            "xhigh" if kind == "escalated_repair" else "high",
            {"head_sha": HEAD},
            "repaired",
            {
                "finding_id": f"finding-{index}",
                "failure_domain": "review_code_correctness",
                "mechanism_id": "legacy-exhausted-chain",
                "head_sha": HEAD,
            },
            holder="head-a-host",
            lease_id=lease_id,
        )
    for index in range(1, 3):
        state.record_attempt(
            run.run_id,
            "review",
            f"review-session-{index}",
            "gpt-5.6-sol",
            "xhigh",
            {"head_sha": HEAD},
            "blocking" if index == 1 else "clean",
            {
                "finding_id": f"review-finding-{index}",
                "failure_domain": "review_code_correctness",
                "mechanism_id": "legacy-exhausted-chain",
                "head_sha": HEAD,
            },
            holder="head-a-host",
            lease_id=lease_id,
        )
    before = state.attempts(run.run_id)
    if expire_lease:
        with state.store._connect() as conn:
            conn.execute(
                "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
                ("2000-01-01T00:00:00+00:00", run.run_id),
            )
            conn.commit()
    return run.run_id, before


def _start_and_expire_head(
    state: VerificationDispatchLedger,
    run_id: str,
    head_sha: str,
    *,
    holder: str,
    session_id: str,
) -> None:
    claimed = state.claim(run_id, holder)
    lease_id = claimed.lease_id or ""
    state.start(
        run_id,
        holder,
        lease_id,
        session_id,
        {"head_sha": head_sha},
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", run_id),
        )
        conn.commit()


def _durable_verification_snapshot(
    state: VerificationDispatchLedger, run_id: str
) -> dict[str, object]:
    with state.store._connect() as conn:
        run = conn.execute(
            "SELECT * FROM verification_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        assert run is not None
        chain_runs = conn.execute(
            """
            SELECT * FROM verification_runs
            WHERE repository=? AND pr_number=? AND stage=?
            ORDER BY created_at, run_id
            """,
            (run["repository"], run["pr_number"], run["stage"]),
        ).fetchall()
        run_ids = [row["run_id"] for row in chain_runs]
        placeholders = ", ".join("?" for _ in run_ids)
        attempts = conn.execute(
            f"""
            SELECT * FROM verification_attempts
            WHERE run_id IN ({placeholders})
            ORDER BY run_id, created_at, attempt_id
            """,
            run_ids,
        ).fetchall()
        exceptions = conn.execute(
            f"""
            SELECT * FROM verification_exceptions
            WHERE run_id IN ({placeholders})
            ORDER BY run_id, exception_id
            """,
            run_ids,
        ).fetchall()
        run_count = conn.execute(
            "SELECT COUNT(*) FROM verification_runs"
        ).fetchone()[0]
    return {
        "runs": [dict(row) for row in chain_runs],
        "attempts": [dict(row) for row in attempts],
        "exceptions": [dict(row) for row in exceptions],
        "run_count": run_count,
    }


def _insert_valid_attempt_authority_change(
    state: VerificationDispatchLedger, run_id: str
) -> None:
    """Insert the same production row shape as a fresh clean review attempt."""

    context = {"head_sha": HEAD}
    with state.store._connect() as conn:
        final_repair = conn.execute(
            """
            SELECT attempt_id FROM verification_attempts
            WHERE run_id=? AND attempt_kind IN ('standard_repair', 'escalated_repair')
            ORDER BY created_at DESC, attempt_id DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        review_count = conn.execute(
            """
            SELECT COUNT(*) FROM verification_attempts
            WHERE run_id=? AND attempt_kind='review'
            """,
            (run_id,),
        ).fetchone()[0]
        assert final_repair is not None
        conn.execute(
            """
            INSERT INTO verification_attempts (
                attempt_id, run_id, attempt_kind, ordinal, session_id,
                capability, reasoning_effort, context_hash, outcome,
                receipt_json, created_at
            ) VALUES (?, ?, 'review', ?, ?, ?, ?, ?, 'clean', ?, ?)
            """,
            (
                "vattempt-delayed-observation-review",
                run_id,
                review_count + 1,
                "delayed-observation-review-session",
                "gpt-5.6-terra",
                "high",
                hashlib.sha256(
                    json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                json.dumps(
                    {
                        "head_sha": HEAD,
                        "reviewed_attempt_id": final_repair["attempt_id"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "2030-01-01T00:00:00.000000+00:00",
            ),
        )
        conn.commit()


def _insert_valid_exception_authority_change(
    state: VerificationDispatchLedger, run_id: str
) -> None:
    """Insert the exact durable shape produced by ``ledger.exception``."""

    failure_class = "authority-critical"
    packet: dict[str, object] = {
        "failure_class": failure_class,
        "original_intent": "verify and close the governed pull request",
        "current_state": "canonical verification authority changed",
        "tried_actions": ["re-read the canonical verification chain"],
        "evidence": [f"verification run {run_id}"],
        "why_unsafe": "continuing would accept stale authority",
        "options": [
            {
                "id": "hold",
                "label": "Hold",
                "consequence": "delivery remains paused",
            },
            {
                "id": "restart",
                "label": "Restart",
                "consequence": "delivery restarts from live authority",
            },
        ],
        "no_action_option": "hold",
        "recommended_option": "hold",
        "recommendation_rationale": "authority must be revalidated first",
        "consequence_of_doing_nothing": "delivery remains blocked",
    }
    assert valid_human_exception_packet(packet)
    exception_id = "vexception-" + hashlib.sha256(
        f"{run_id}:{failure_class}:{HEAD}".encode()
    ).hexdigest()[:16]
    with state.store._connect() as conn:
        conn.execute(
            """
            INSERT INTO verification_exceptions (
                exception_id, run_id, failure_class, head_sha, packet_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exception_id,
                run_id,
                failure_class,
                HEAD,
                json.dumps(
                    packet,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "2030-01-01T00:00:00.000000+00:00",
                "2030-01-01T00:00:00.000000+00:00",
            ),
        )
        conn.commit()


def _insert_inert_legacy_audit_authority_change(
    state: VerificationDispatchLedger, head_sha: str
) -> None:
    """Insert the quarantined row shape produced by the legacy migration."""

    legacy_request = pre_trust_request(head_sha)
    idempotency_key = legacy_request["idempotency_key"]
    assert isinstance(idempotency_key, str)
    with state.store._connect() as conn:
        conn.execute(
            """
            INSERT INTO verification_runs (
                run_id, idempotency_key, contract_version, repository,
                pr_number, head_sha, current_head_sha, stage, request_json,
                supporting_authority_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 'legacy_untrusted', ?, ?)
            """,
            (
                f"vrun-{idempotency_key[:16]}",
                idempotency_key,
                legacy_request["contract_version"],
                legacy_request["repository"],
                legacy_request["pr_number"],
                head_sha,
                head_sha,
                legacy_request["stage"],
                json.dumps(
                    legacy_request,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
                "2030-01-01T00:00:00.000000+00:00",
                "2030-01-01T00:00:00.000000+00:00",
            ),
        )
        conn.commit()


def _assert_delayed_observation_rejected_without_mutation(
    state: VerificationDispatchLedger,
    run_id: str,
    delayed_observation: dict[str, object],
) -> None:
    snapshot_after_authority_change = _durable_verification_snapshot(state, run_id)
    database_after_authority_change = state.store.db_path.read_bytes()

    with pytest.raises(
        ValueError, match="verification canonical authority changed during live observation"
    ):
        state.ingest(delayed_observation)

    assert _durable_verification_snapshot(state, run_id) == snapshot_after_authority_change
    assert state.store.db_path.read_bytes() == database_after_authority_change
def _record_backoff_chain(
    state: VerificationDispatchLedger,
    *,
    retry_after: str,
    payload: dict[str, object] | None = None,
) -> tuple[str, dict[str, object]]:
    run_id, _ = _record_exhausted_chain(
        state, payload or request(), expire_lease=False
    )
    running = state.get(run_id)
    assert running is not None
    assert running.lease_id is not None
    state.exception(
        run_id,
        "synthetic_failure",
        {"summary": "bounded synthetic exception", "head_sha": HEAD},
        holder="head-a-host",
        lease_id=running.lease_id,
    )
    state.backoff(
        run_id,
        {"outcome": "launcher_contract_failed", "error_type": "RuntimeError"},
        retry_after,
        holder="head-a-host",
        lease_id=running.lease_id,
    )
    return run_id, _durable_verification_snapshot(state, run_id)


def test_authenticated_live_head_rebinds_expired_backoff_chain(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _record_backoff_chain(
        state, retry_after="2000-01-01T00:00:00+00:00"
    )

    reopened = state.ingest(
        _live_observed_artifact(state, request(REPAIRED_HEAD))
    )

    assert reopened.run_id == run_id
    assert reopened.status == "queued"
    assert reopened.requested_head_sha == HEAD
    assert reopened.current_head_sha == REPAIRED_HEAD
    assert reopened.claimed_by is None
    assert reopened.lease_id is None
    assert reopened.coordinator_session_id is None
    assert reopened.context_pack is None
    assert reopened.terminal_receipt is None
    assert reopened.retry_after is None


def test_expired_backoff_rebind_preserves_cumulative_chain_evidence(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, before = _record_backoff_chain(
        state, retry_after="2000-01-01T00:00:00+00:00"
    )

    reopened = state.ingest(
        _live_observed_artifact(state, request(REPAIRED_HEAD))
    )
    after = _durable_verification_snapshot(state, run_id)

    assert reopened.run_id == run_id
    assert after["attempts"] == before["attempts"]
    assert after["exceptions"] == before["exceptions"]
    assert after["run_count"] == before["run_count"] == 1
    assert [attempt["kind"] for attempt in state.attempts(run_id)] == [
        "standard_repair",
        "standard_repair",
        "escalated_repair",
        "escalated_repair",
        "review",
        "review",
    ]


def test_consumer_rebinds_expired_backoff_and_launches_head_b_fresh(
    tmp_path: Path,
) -> None:
    class HeadBLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            session_id, receipt = super().launch(context_pack, **kwargs)
            receipt["head_sha"] = REPAIRED_HEAD
            return session_id, receipt

    state = ledger(tmp_path)
    run_id, before = _record_backoff_chain(
        state, retry_after="2000-01-01T00:00:00+00:00"
    )
    source, _ = _gh_source(request(REPAIRED_HEAD))
    authenticated = source.pending_requests(REPO)[0]
    launcher = HeadBLauncher()

    result = VerificationConsumer(
        state,
        Truth(
            eligible_pr(head={"ref": "branch", "sha": REPAIRED_HEAD}),
            green_checks(REPAIRED_HEAD),
        ),
        Auth(),
        launcher,
        "head-b-host",
    ).consume(authenticated)

    after = _durable_verification_snapshot(state, run_id)
    assert result.run_id == run_id
    assert result.requested_head_sha == HEAD
    assert result.current_head_sha == REPAIRED_HEAD
    assert result.status == "needs_human"
    assert len(launcher.calls) == 1
    context_pack, resume_session_id = launcher.calls[0]
    assert context_pack["head_sha"] == REPAIRED_HEAD
    assert resume_session_id is None
    assert after["attempts"][: len(before["attempts"])] == before["attempts"]
    assert after["exceptions"][: len(before["exceptions"])] == before["exceptions"]
    assert after["run_count"] == before["run_count"] == 1


@pytest.mark.parametrize("failure", ["unexpired", "unauthenticated", "stale_live_head"])
def test_backoff_head_rebind_rejects_untrusted_or_premature_transition(
    tmp_path: Path, failure: str
) -> None:
    state = ledger(tmp_path)
    retry_after = (
        "2999-01-01T00:00:00+00:00"
        if failure == "unexpired"
        else "2000-01-01T00:00:00+00:00"
    )
    run_id, before = _record_backoff_chain(state, retry_after=retry_after)
    payload = request(REPAIRED_HEAD)
    if failure == "unauthenticated":
        incoming: dict[str, object] = payload
    elif failure == "stale_live_head":
        source, _ = _gh_source(payload)
        authenticated = source.pending_requests(REPO)[0]
        token = state.canonical_chain_token(authenticated)
        incoming = _live_observed_verification_request(
            authenticated,
            observed_repository=REPO,
            observed_pr_number=payload["pr_number"],
            observed_head_sha=HEAD,
            observed_state="open",
            observed_merged_at=None,
            observed_draft=False,
            observed_linked_issue=payload["linked_issue"],
            observed_closing_issues=tuple(payload["closing_issues"]),
            observed_supporting_issues=(),
            observed_final_review_rounds=payload["final_review_rounds"],
            canonical_chain_token=token,
        )
    else:
        incoming = _live_observed_artifact(state, payload)

    with pytest.raises(ValueError, match="artifact head does not match canonical run"):
        state.ingest(incoming)

    assert _durable_verification_snapshot(state, run_id) == before


def test_expired_backoff_rebind_rejects_authority_drift(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, before = _record_backoff_chain(
        state,
        retry_after="2000-01-01T00:00:00+00:00",
        payload=original,
    )

    removed_support = request(REPAIRED_HEAD)
    with pytest.raises(ValueError, match="artifact head does not match canonical run"):
        state.ingest(_live_observed_artifact(state, removed_support))

    wrong_governor = request(REPAIRED_HEAD)
    wrong_governor["linked_issue"] = 999999
    wrong_governor["closing_issues"] = [999999]
    with pytest.raises(ValueError, match="governing issue mismatch"):
        state.ingest(_live_observed_artifact(state, wrong_governor))

    assert _durable_verification_snapshot(state, run_id) == before


def test_expired_backoff_rebind_rejects_canonical_chain_race(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _record_backoff_chain(
        state, retry_after="2000-01-01T00:00:00+00:00"
    )
    incoming = _live_observed_artifact(state, request(REPAIRED_HEAD))
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET retry_after=? WHERE run_id=?",
            ("1999-01-01T00:00:00+00:00", run_id),
        )
        conn.commit()
    before = _durable_verification_snapshot(state, run_id)

    with pytest.raises(ValueError, match="canonical authority changed"):
        state.ingest(incoming)

    assert _durable_verification_snapshot(state, run_id) == before


def test_first_authenticated_new_head_reopens_expired_chain_without_budget_reset(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, before = _record_exhausted_chain(state, request())
    authenticated = _live_observed_artifact(state, request(REPAIRED_HEAD))

    reopened = state.ingest(authenticated)

    assert reopened.run_id == run_id
    assert reopened.status == "queued"
    assert reopened.requested_head_sha == HEAD
    assert reopened.current_head_sha == REPAIRED_HEAD
    assert reopened.claimed_by is None
    assert reopened.lease_id is None
    assert reopened.lease_expires_at is None
    assert reopened.coordinator_session_id is None
    assert reopened.context_pack is None
    assert reopened.retry_after is None
    assert reopened.terminal_receipt is None
    assert state.attempts(run_id) == before
    assert [attempt["kind"] for attempt in before] == [
        "standard_repair",
        "standard_repair",
        "escalated_repair",
        "escalated_repair",
        "review",
        "review",
    ]


def test_authenticated_new_head_accepts_monotonic_supporting_issue_extension(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, before = _record_exhausted_chain(state, original)
    repaired = request(REPAIRED_HEAD)
    repaired["supporting_issues"] = [3626, 3783, 3784]
    reopened = state.ingest(_live_observed_artifact(state, repaired))

    assert reopened.run_id == run_id
    assert reopened.status == "queued"
    assert reopened.current_head_sha == REPAIRED_HEAD
    assert state.attempts(run_id) == before


def test_successive_takeovers_enforce_durable_cumulative_supporting_authority(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, before = _record_exhausted_chain(state, original)
    repaired = request(REPAIRED_HEAD)
    repaired["supporting_issues"] = [3626, 3783]
    first_takeover = state.ingest(_live_observed_artifact(state, repaired))
    assert first_takeover.request["supporting_issues"] == [3626]
    assert first_takeover.supporting_authority == (3626, 3783)
    claimed = state.claim(run_id, "head-b-host")
    lease_id = claimed.lease_id or ""
    state.start(
        run_id,
        "head-b-host",
        lease_id,
        "01900000-0000-7000-8000-000000000103",
        {"head_sha": REPAIRED_HEAD},
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", run_id),
        )
        conn.commit()

    rolled_back = request(SECOND_REPAIRED_HEAD)
    rolled_back["supporting_issues"] = [3626]
    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        state.ingest(_live_observed_artifact(state, rolled_back))

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.requested_head_sha == HEAD
    assert retained.current_head_sha == REPAIRED_HEAD
    assert retained.request["supporting_issues"] == [3626]
    assert retained.supporting_authority == (3626, 3783)
    assert state.attempts(run_id) == before
    with state.store._connect() as conn:
        durable = conn.execute(
            "SELECT supporting_authority_json FROM verification_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
    assert durable is not None
    assert json.loads(durable["supporting_authority_json"]) == [3626, 3783]

    extended = request(THIRD_REPAIRED_HEAD)
    extended["supporting_issues"] = [3626, 3783, 3784]
    second_takeover = state.ingest(_live_observed_artifact(state, extended))

    assert first_takeover.run_id == second_takeover.run_id == run_id
    assert second_takeover.status == "queued"
    assert second_takeover.requested_head_sha == HEAD
    assert second_takeover.current_head_sha == THIRD_REPAIRED_HEAD
    assert second_takeover.request["supporting_issues"] == [3626]
    assert second_takeover.supporting_authority == (3626, 3783, 3784)
    assert state.attempts(run_id) == before
    with state.store._connect() as conn:
        durable = conn.execute(
            "SELECT supporting_authority_json FROM verification_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
    assert durable is not None
    assert json.loads(durable["supporting_authority_json"]) == [3626, 3783, 3784]


def test_successive_takeover_cannot_replace_prior_supporting_evidence(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, before = _record_exhausted_chain(state, original)
    repaired = request(REPAIRED_HEAD)
    repaired["supporting_issues"] = [3626, 3783]
    state.ingest(_live_observed_artifact(state, repaired))
    claimed = state.claim(run_id, "head-b-host")
    lease_id = claimed.lease_id or ""
    state.start(
        run_id,
        "head-b-host",
        lease_id,
        "01900000-0000-7000-8000-000000000104",
        {"head_sha": REPAIRED_HEAD},
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at=? WHERE run_id=?",
            ("2000-01-01T00:00:00+00:00", run_id),
        )
        conn.commit()
    replacement = request(SECOND_REPAIRED_HEAD)
    replacement["supporting_issues"] = [3626, 999999]
    replacement_source, _ = _gh_source(replacement)

    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        state.ingest(replacement_source.pending_requests(REPO)[0])

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == REPAIRED_HEAD
    assert retained.request["supporting_issues"] == [3626]
    assert retained.supporting_authority == (3626, 3783)
    assert state.attempts(run_id) == before


def test_takeover_updates_cumulative_authority_projection(tmp_path: Path) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, _ = _record_exhausted_chain(state, original)
    repaired = request(REPAIRED_HEAD)
    repaired["supporting_issues"] = [3626, 3783]
    reopened = state.ingest(_live_observed_artifact(state, repaired))
    complete_body = "Governing-Issue: #3603\n\nFixes #3603\nRefs #3626\nRefs #3783"
    missing_extension = "Governing-Issue: #3603\n\nFixes #3603\nRefs #3626"

    assert reopened.run_id == run_id
    assert reopened.request["supporting_issues"] == [3626]
    assert reopened.supporting_authority == (3626, 3783)
    assert f"https://github.com/{REPO}/issues/3783" in _trusted_evidence_urls(
        reopened
    )
    assert _governing_contract_matches(reopened, complete_body)
    assert not _governing_contract_matches(reopened, missing_extension)


def test_terminal_stale_head_reopen_enforces_authenticated_cumulative_authority(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, before = _record_exhausted_chain(state, original)
    repaired = request(REPAIRED_HEAD)
    repaired["supporting_issues"] = [3626, 3783]
    state.ingest(_live_observed_artifact(state, repaired))
    claimed = state.claim(run_id, "head-b-host")
    lease_id = claimed.lease_id or ""
    state.backoff(
        run_id,
        {"outcome": "deferred", "reason": "checks_not_green"},
        "2000-01-01T00:00:00+00:00",
        holder="head-b-host",
        lease_id=lease_id,
    )
    state.supersede_unclaimed(
        run_id,
        {"outcome": "noop", "reason": "stale_head"},
        reason="stale_head",
    )

    rolled_back = request(SECOND_REPAIRED_HEAD)
    rolled_back["supporting_issues"] = [3626]
    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        state.ingest(rolled_back)
    rollback_source, _ = _gh_source(rolled_back)
    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        state.ingest(rollback_source.pending_requests(REPO)[0])

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "superseded"
    assert retained.current_head_sha == REPAIRED_HEAD
    assert retained.supporting_authority == (3626, 3783)
    assert state.attempts(run_id) == before
    assert f"https://github.com/{REPO}/issues/3783" in _trusted_evidence_urls(
        retained
    )
    assert _governing_contract_matches(
        retained,
        "Governing-Issue: #3603\nFixes #3603\nRefs #3626\nRefs #3783",
    )
    assert not _governing_contract_matches(
        retained,
        "Governing-Issue: #3603\nFixes #3603\nRefs #3626",
    )

    extended = request(THIRD_REPAIRED_HEAD)
    extended["supporting_issues"] = [3626, 3783, 3784]
    reopened = state.ingest(_live_observed_artifact(state, extended))

    assert reopened.run_id == run_id
    assert reopened.status == "queued"
    assert reopened.requested_head_sha == HEAD
    assert reopened.current_head_sha == THIRD_REPAIRED_HEAD
    assert reopened.supporting_authority == (3626, 3783, 3784)
    assert state.attempts(run_id) == before


def test_expired_head_reconciliation_rejects_unauthenticated_valid_artifact(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, before = _record_exhausted_chain(state, request())

    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        state.ingest(request(REPAIRED_HEAD))

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == HEAD
    assert state.attempts(run_id) == before


def test_new_head_reconciliation_rejects_authenticated_artifact_while_lease_is_live(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, before = _record_exhausted_chain(
        state, request(), expire_lease=False
    )
    authenticated = _live_observed_artifact(state, request(REPAIRED_HEAD))

    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        state.ingest(authenticated)

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == HEAD
    assert state.attempts(run_id) == before


@pytest.mark.parametrize(
    "incoming_supporting",
    [
        [],
        [999999],
    ],
)
def test_expired_head_reconciliation_rejects_supporting_issue_removal_or_replacement(
    tmp_path: Path, incoming_supporting: list[int]
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, before = _record_exhausted_chain(state, original)
    payload = request(REPAIRED_HEAD)
    payload["supporting_issues"] = incoming_supporting
    with pytest.raises(ValueError):
        state.ingest(_live_observed_artifact(state, payload))

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == HEAD
    assert state.attempts(run_id) == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(
            linked_issue=999999, closing_issues=[999999]
        ),
        lambda payload: payload.update(repository="other/repository"),
    ],
)
def test_expired_head_reconciliation_rejects_mismatched_primary_authority(
    tmp_path: Path, mutate: Callable[[dict[str, object]], None]
) -> None:
    state = ledger(tmp_path)
    run_id, before = _record_exhausted_chain(state, request())
    payload = request(REPAIRED_HEAD)
    mutate(payload)
    candidate: dict[str, object] = payload
    if payload.get("repository") == REPO:
        candidate = _live_observed_artifact(state, payload)

    with pytest.raises(ValueError):
        state.ingest(candidate)

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == HEAD
    assert state.attempts(run_id) == before


def test_expired_head_reconciliation_rejects_ambiguous_terminal_authority(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, before = _record_exhausted_chain(state, request())
    payload = request(REPAIRED_HEAD)
    with state.store._connect() as conn:
        conn.execute(
            """
            INSERT INTO verification_runs (
                run_id, idempotency_key, contract_version, repository,
                    pr_number, head_sha, current_head_sha, stage, request_json,
                    closing_authority_json, status, stop_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'failed', 'synthetic_terminal', ?, ?)
            """,
            (
                f"vrun-{str(payload['idempotency_key'])[:16]}",
                payload["idempotency_key"],
                payload["contract_version"],
                payload["repository"],
                payload["pr_number"],
                REPAIRED_HEAD,
                REPAIRED_HEAD,
                payload["stage"],
                    json.dumps(payload),
                    json.dumps(payload["closing_issues"]),
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    authenticated = _live_observed_artifact(state, payload)

    with pytest.raises(ValueError, match="canonical terminal chain is ambiguous"):
        state.ingest(authenticated)

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == HEAD
    assert state.attempts(run_id) == before


def test_delayed_observation_rejects_attempt_only_authority_change(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _record_exhausted_chain(state, request())
    delayed_observation = _live_observed_artifact(state, request(REPAIRED_HEAD))

    _insert_valid_attempt_authority_change(state, run_id)

    _assert_delayed_observation_rejected_without_mutation(
        state, run_id, delayed_observation
    )


def test_delayed_observation_rejects_exception_only_authority_change(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _record_exhausted_chain(state, request())
    delayed_observation = _live_observed_artifact(state, request(REPAIRED_HEAD))

    _insert_valid_exception_authority_change(state, run_id)

    _assert_delayed_observation_rejected_without_mutation(
        state, run_id, delayed_observation
    )


def test_delayed_observation_rejects_cumulative_authority_only_change(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _record_exhausted_chain(state, request())
    delayed_observation = _live_observed_artifact(state, request(REPAIRED_HEAD))

    with state.store._connect() as conn:
        conn.execute(
            """
            UPDATE verification_runs
            SET supporting_authority_json='[3626]'
            WHERE run_id=?
            """,
            (run_id,),
        )
        conn.commit()

    _assert_delayed_observation_rejected_without_mutation(
        state, run_id, delayed_observation
    )


def test_delayed_observation_rejects_inert_legacy_audit_only_change(
    tmp_path: Path,
) -> None:
    state, _ = _migrated_legacy_ledger(tmp_path)
    run_id, _ = _record_exhausted_chain(
        state,
        request(REPAIRED_HEAD),
        authenticate_with_live_observation=True,
    )
    delayed_observation = _live_observed_artifact(
        state, request(SECOND_REPAIRED_HEAD)
    )

    _insert_inert_legacy_audit_authority_change(state, THIRD_REPAIRED_HEAD)

    _assert_delayed_observation_rejected_without_mutation(
        state, run_id, delayed_observation
    )


def test_historical_authenticated_artifact_cannot_move_expired_chain_backward(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, _ = _record_exhausted_chain(state, request())
    delayed_source, _ = _gh_source(request(REPAIRED_HEAD))
    delayed_head_b = delayed_source.pending_requests(REPO)[0]
    durable_before: list[dict[str, object]] = []

    class AdvancingTruth(Truth):
        def pull_request(self, repository, pr_number):
            state.ingest(_live_observed_artifact(state, request(REPAIRED_HEAD)))
            _start_and_expire_head(
                state,
                run_id,
                REPAIRED_HEAD,
                holder="head-b-host",
                session_id="01900000-0000-7000-8000-000000000103",
            )
            state.ingest(
                _live_observed_artifact(state, request(SECOND_REPAIRED_HEAD))
            )
            _start_and_expire_head(
                state,
                run_id,
                SECOND_REPAIRED_HEAD,
                holder="head-c-host",
                session_id="01900000-0000-7000-8000-000000000104",
            )
            durable_before.append(_durable_verification_snapshot(state, run_id))
            return self.pr

    live_head_b = eligible_pr(head={"ref": "branch", "sha": REPAIRED_HEAD})

    with pytest.raises(
        ValueError, match="verification canonical authority changed during live observation"
    ):
        VerificationConsumer(
            state,
            AdvancingTruth(live_head_b, GREEN),
            Auth(),
            Launcher(),
            "head-c-host",
        ).consume(delayed_head_b)

    assert len(durable_before) == 1
    assert _durable_verification_snapshot(state, run_id) == durable_before[0]


def test_authenticated_intake_refetches_live_pr_after_ingest_before_rejection(
    tmp_path: Path,
) -> None:
    source, _ = _gh_source(request())
    authenticated = source.pending_requests(REPO)[0]

    class CorrectedAfterIntakeTruth(Truth):
        def __init__(self) -> None:
            super().__init__(eligible_pr(), GREEN)
            self.pull_calls = 0

        def pull_request(self, repository, pr_number):
            self.pull_calls += 1
            if self.pull_calls == 1:
                return eligible_pr(draft=True)
            return eligible_pr()

    truth = CorrectedAfterIntakeTruth()
    launcher = Launcher()
    result = VerificationConsumer(
        ledger(tmp_path), truth, Auth(ok=False), launcher, "host"
    ).consume(authenticated)

    assert truth.pull_calls == 2
    assert result.status == "backoff"
    assert result.stop_reason is None
    assert launcher.calls == []


def test_consumer_starts_authenticated_new_head_beside_inert_legacy_audit(
    tmp_path: Path,
) -> None:
    state, legacy = _migrated_legacy_ledger(tmp_path)
    source, _ = _gh_source(request(REPAIRED_HEAD))
    authenticated = source.pending_requests(REPO)[0]

    result = VerificationConsumer(
        state,
        Truth(eligible_pr(head={"ref": "branch", "sha": REPAIRED_HEAD}), GREEN),
        Auth(ok=False),
        Launcher(),
        "host",
    ).consume(authenticated)

    assert result.status == "backoff"
    assert result.authority_state == "canonical"
    assert result.current_head_sha == REPAIRED_HEAD
    assert result.run_id != legacy.run_id
    assert state.get(legacy.run_id) == legacy
    assert {run.run_id for run in state.list()} == {legacy.run_id, result.run_id}


def test_reconciled_new_head_replay_is_idempotent(tmp_path: Path) -> None:
    state = ledger(tmp_path)
    run_id, _ = _record_exhausted_chain(state, request())
    first = state.ingest(
        _live_observed_artifact(state, request(REPAIRED_HEAD))
    )
    claimed = state.claim(run_id, "head-b-host")
    terminal = state.terminal(
        run_id,
        "failed",
        {"outcome": "blocked", "head_sha": REPAIRED_HEAD},
        reason="synthetic_terminal",
        holder="head-b-host",
        lease_id=claimed.lease_id or "",
    )
    before_replay = _durable_verification_snapshot(state, run_id)

    restarted = VerificationDispatchLedger(state.store)
    replay_source, _ = _gh_source(request(REPAIRED_HEAD))
    replay = VerificationConsumer(
        restarted,
        Truth(
            eligible_pr(
                head={"ref": "branch", "sha": REPAIRED_HEAD},
                state="closed",
                merged_at="2026-07-15T08:00:00Z",
            ),
            GREEN,
        ),
        Auth(),
        Launcher(),
        "head-b-host",
    ).consume(replay_source.pending_requests(REPO)[0])

    assert first.run_id == replay.run_id == terminal.run_id == run_id
    assert replay == terminal
    assert replay.current_head_sha == REPAIRED_HEAD
    assert _durable_verification_snapshot(state, run_id) == before_replay


def test_live_supporting_authority_drift_rejects_takeover_before_mutation(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, _ = _record_exhausted_chain(state, original)
    incoming = request(REPAIRED_HEAD)
    incoming["supporting_issues"] = [3626, 3783]
    source, _ = _gh_source(incoming)
    authenticated = source.pending_requests(REPO)[0]
    live_pr = eligible_pr(
        head={"ref": "branch", "sha": REPAIRED_HEAD},
        body=(
            "Governing-Issue: #3603\n\nFixes #3603\nRefs #3626\n"
            "Final-Review-Rounds: 1"
        ),
    )
    before = _durable_verification_snapshot(state, run_id)
    launcher = Launcher()

    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        VerificationConsumer(
            state, Truth(live_pr, GREEN), Auth(), launcher, "head-b-host"
        ).consume(authenticated)

    assert launcher.calls == []
    assert _durable_verification_snapshot(state, run_id) == before


@pytest.mark.parametrize(
    ("live_pr", "reason"),
    [
        (eligible_pr(draft=True), "draft"),
        (eligible_pr(state="closed"), "closed_unmerged_or_merged"),
        (
            eligible_pr(head={"ref": "branch", "sha": REPAIRED_HEAD}),
            "stale_head",
        ),
        (
            eligible_pr(
                body=(
                    "Governing-Issue: #999999\n\nFixes #999999\n"
                    "Final-Review-Rounds: 1"
                )
            ),
            "governing_issue_mismatch",
        ),
    ],
)
def test_authenticated_initial_ineligible_observation_preserves_supersession(
    tmp_path: Path, live_pr: dict[str, object], reason: str
) -> None:
    state = ledger(tmp_path)
    source, _ = _gh_source(request())
    authenticated = source.pending_requests(REPO)[0]

    result = VerificationConsumer(
        state, Truth(live_pr, GREEN), Auth(), Launcher(), "host"
    ).consume(authenticated)

    assert result.status == "superseded"
    assert result.stop_reason == reason


def test_authenticated_exact_terminal_replay_remains_idempotent(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    terminal = state.terminal(
        run.run_id,
        "failed",
        {"outcome": "blocked"},
        reason="synthetic_terminal",
        holder="host",
        lease_id=claimed.lease_id or "",
    )
    before = _durable_verification_snapshot(state, run.run_id)
    source, _ = _gh_source(request())
    authenticated = source.pending_requests(REPO)[0]
    merged_live_pr = eligible_pr(
        state="closed", merged_at="2026-07-15T08:00:00Z"
    )

    replay = VerificationConsumer(
        state, Truth(merged_live_pr, GREEN), Auth(), Launcher(), "host"
    ).consume(authenticated)

    assert replay == terminal
    assert _durable_verification_snapshot(state, run.run_id) == before
