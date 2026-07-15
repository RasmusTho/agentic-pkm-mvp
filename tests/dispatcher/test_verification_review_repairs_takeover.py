from __future__ import annotations

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
from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.test_verification_consumer import (
    Auth,
    GREEN,
    Launcher,
    Truth,
    eligible_pr,
)
from tests.dispatcher.verification_helpers import HEAD, REPO, ledger, request


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
        "name": "CI",
        "path": ".github/workflows/ci.yml",
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
        if endpoint.endswith("actions/artifacts?per_page=100"):
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


def test_gh_source_authenticates_producer_before_reading_request_json() -> None:
    payload = request()
    source, endpoints = _gh_source(payload)

    assert source.pending_requests(REPO) == [payload]
    assert endpoints == [
        f"repos/{REPO}/actions/artifacts?per_page=100",
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
) -> tuple[str, list[dict[str, object]]]:
    run = state.ingest(payload)
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
            {"finding_id": f"finding-{index}", "head_sha": HEAD},
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
            {"finding_id": f"review-finding-{index}", "head_sha": HEAD},
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


def test_first_authenticated_new_head_reopens_expired_chain_without_budget_reset(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    run_id, before = _record_exhausted_chain(state, request())
    source, _ = _gh_source(request(REPAIRED_HEAD))
    authenticated = source.pending_requests(REPO)[0]

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
    source, _ = _gh_source(repaired)

    reopened = state.ingest(source.pending_requests(REPO)[0])

    assert reopened.run_id == run_id
    assert reopened.status == "queued"
    assert reopened.current_head_sha == REPAIRED_HEAD
    assert state.attempts(run_id) == before


def test_successive_takeovers_preserve_monotonic_supporting_evidence(
    tmp_path: Path,
) -> None:
    state = ledger(tmp_path)
    original = request()
    original["supporting_issues"] = [3626]
    run_id, before = _record_exhausted_chain(state, original)
    repaired = request(REPAIRED_HEAD)
    repaired["supporting_issues"] = [3626, 3783]
    source, _ = _gh_source(repaired)

    first_takeover = state.ingest(source.pending_requests(REPO)[0])
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
    rollback_source, _ = _gh_source(rolled_back)
    with pytest.raises(
        ValueError, match="verification artifact head does not match canonical run"
    ):
        state.ingest(rollback_source.pending_requests(REPO)[0])

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
    extension_source, _ = _gh_source(extended)
    second_takeover = state.ingest(extension_source.pending_requests(REPO)[0])

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
    source, _ = _gh_source(repaired)
    state.ingest(source.pending_requests(REPO)[0])
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
    source, _ = _gh_source(repaired)

    reopened = state.ingest(source.pending_requests(REPO)[0])
    complete_body = "Governing-Issue: #3603\n\nFixes #3626\nFixes #3783"
    missing_extension = "Governing-Issue: #3603\n\nFixes #3626"

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
    source, _ = _gh_source(repaired)
    state.ingest(source.pending_requests(REPO)[0])
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
        "Governing-Issue: #3603\nFixes #3626\nFixes #3783",
    )
    assert not _governing_contract_matches(
        retained,
        "Governing-Issue: #3603\nFixes #3626",
    )

    extended = request(THIRD_REPAIRED_HEAD)
    extended["supporting_issues"] = [3626, 3783, 3784]
    extension_source, _ = _gh_source(extended)
    reopened = state.ingest(extension_source.pending_requests(REPO)[0])

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
    source, _ = _gh_source(request(REPAIRED_HEAD))
    authenticated = source.pending_requests(REPO)[0]

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
    source, _ = _gh_source(payload)

    with pytest.raises(ValueError):
        state.ingest(source.pending_requests(REPO)[0])

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == HEAD
    assert state.attempts(run_id) == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(linked_issue=999999),
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
        source, _ = _gh_source(payload)
        candidate = source.pending_requests(REPO)[0]

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
                status, stop_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'failed', 'synthetic_terminal', ?, ?)
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
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    source, _ = _gh_source(payload)
    authenticated = source.pending_requests(REPO)[0]

    with pytest.raises(ValueError, match="canonical terminal chain is ambiguous"):
        state.ingest(authenticated)

    retained = state.get(run_id)
    assert retained is not None
    assert retained.status == "running"
    assert retained.current_head_sha == HEAD
    assert state.attempts(run_id) == before
