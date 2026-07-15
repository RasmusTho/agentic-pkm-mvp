from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path
from threading import Condition, Thread
import zipfile

import pytest
import jsonschema

import app.dispatcher.verification_consumer as verification_consumer

from app.dispatcher.verification_consumer import (
    AuthReceipt,
    CodexChatGPTAuthPreflight,
    CodexExecFailure,
    CodexExecLauncher,
    GhCliVerificationSource,
    LaunchConfig,
    VerificationConsumer,
)
from tests.dispatcher.verification_helpers import HEAD, ledger, request


@dataclass
class Truth:
    pr: dict[str, object]
    check_rows: list[dict[str, object]]

    def pull_request(self, repository, pr_number):
        return self.pr

    def checks(self, repository, head_sha):
        return self.check_rows


class Auth:
    def __init__(self, ok=True): self.ok = ok
    def check(self): return AuthReceipt(self.ok, "chatgpt", "keyring", None if self.ok else "auth")


class Launcher:
    config = LaunchConfig("verification_closer", "gpt-5.6-terra", "high", "workspace-write", "instructions")
    def __init__(self): self.calls = []
    def launch(self, context_pack, *, resume_session_id=None, on_thread_started=None, on_heartbeat=None):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "thread-new"
        if on_thread_started: on_thread_started(session)
        if on_heartbeat: on_heartbeat()
        return session, {
            "verdict": "needs_human",
            "head_sha": HEAD,
            "summary": "test",
            "receipt_ids": [],
            "human_exception": {
                "failure_class": "authority-critical",
                "original_intent": "verify and close the governing issue",
                "current_state": "exact head is green but authority is missing",
                "tried_actions": ["validated CI and review evidence"],
                "evidence": ["PR #3620"],
                "why_unsafe": "continuation requires authority outside the issue",
                "options": ["hold", "authorize"],
                "recommended_option": "hold",
                "consequence_of_doing_nothing": "the delivery remains blocked",
            },
        }


class RateLimitedLauncher(Launcher):
    def launch(self, context_pack, *, resume_session_id=None, on_thread_started=None, on_heartbeat=None):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "thread-rate"
        if on_thread_started: on_thread_started(session)
        return session, {
            "verdict": "retry", "head_sha": HEAD, "summary": "rate limit exhausted", "receipt_ids": [], "retry_after": "1h"
        }


class DeliveredLauncher(Launcher):
    def launch(
        self,
        context_pack,
        *,
        resume_session_id=None,
        on_thread_started=None,
        on_heartbeat=None,
    ):
        self.calls.append((context_pack, resume_session_id))
        session = resume_session_id or "thread-delivered"
        if on_thread_started:
            on_thread_started(session)
        return session, {
            "verdict": "delivered",
            "head_sha": HEAD,
            "summary": "verified and merged",
            "receipt_ids": ["review-1", "review-2"],
            "review_events": [
                {
                    "kind": "review",
                    "session_id": "review-1",
                    "capability": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "outcome": "clean",
                },
                {
                    "kind": "review",
                    "session_id": "review-2",
                    "capability": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "outcome": "clean",
                },
            ],
        }


class TransitionTruth:
    def __init__(self, terminal_pr: dict[str, object]) -> None:
        self.prs = iter([eligible_pr(), eligible_pr(), terminal_pr])

    def pull_request(self, repository, pr_number):
        return next(self.prs)

    def checks(self, repository, head_sha):
        return GREEN


def eligible_pr(**updates):
    value = {
        "number": 3603, "state": "open", "draft": False, "merged_at": None,
        "body": "Governing-Issue: #3603\n\nRefs #3603",
        "base": {"ref": "main"}, "head": {"ref": "branch", "sha": HEAD},
    }
    value.update(updates)
    return value


def test_live_governing_issue_drift_fails_closed_before_launch(tmp_path) -> None:
    launcher = Launcher()
    pr = eligible_pr(body="Governing-Issue: #3626\n\nFixes #3626")

    result = VerificationConsumer(
        ledger(tmp_path), Truth(pr, GREEN), Auth(), launcher, "host"
    ).consume(request())

    assert result.status == "superseded"
    assert result.stop_reason == "governing_issue_mismatch"
    assert launcher.calls == []


def test_head_move_during_auth_fails_closed_before_launch(tmp_path) -> None:
    truth = Truth(eligible_pr(), GREEN)
    launcher = Launcher()

    class MovingAuth(Auth):
        def check(self):
            truth.pr = eligible_pr(head={"ref": "branch", "sha": "b" * 40})
            return super().check()

    result = VerificationConsumer(
        ledger(tmp_path), truth, MovingAuth(), launcher, "host"
    ).consume(request())

    assert result.status == "superseded"
    assert result.stop_reason == "stale_head"
    assert launcher.calls == []


def test_governing_issue_move_during_auth_fails_closed_before_launch(tmp_path) -> None:
    truth = Truth(eligible_pr(), GREEN)
    launcher = Launcher()

    class MovingAuth(Auth):
        def check(self):
            truth.pr = eligible_pr(
                body="Governing-Issue: #3626\n\nFixes #3626"
            )
            return super().check()

    result = VerificationConsumer(
        ledger(tmp_path), truth, MovingAuth(), launcher, "host"
    ).consume(request())

    assert result.status == "superseded"
    assert result.stop_reason == "governing_issue_mismatch"
    assert launcher.calls == []


def merged_pr(**updates: object) -> dict[str, object]:
    value = eligible_pr(
        state="closed",
        merged=True,
        merged_at="2026-07-15T00:00:00Z",
        merge_commit_sha="b" * 40,
        base={
            "ref": "main",
            "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"},
        },
    )
    value.update(updates)
    return value


GREEN = [{"status": "completed", "conclusion": "success"}]


def artifact_request(**updates: object) -> dict[str, object]:
    value = request()
    value["artifact_provenance"] = {
        "workflow_run_id": 123,
        "repository_id": 456,
        "artifact_name": f"verification-dispatch-3603-{HEAD}",
    }
    value.update(updates)
    return value


def test_gh_source_fetches_bounded_artifact_and_live_truth_without_shell(tmp_path) -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr(
            "verification-dispatch/request.json", json.dumps(artifact_request())
        )

    class Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        endpoint = command[-1]
        if endpoint.endswith("actions/artifacts?per_page=100"):
            return Result(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 7,
                                "name": f"verification-dispatch-3603-{HEAD}",
                                "size_in_bytes": len(archive_bytes.getvalue()),
                                "expired": False,
                                "workflow_run": {
                                    "id": 123,
                                    "repository_id": 456,
                                    "head_repository_id": 456,
                                },
                            }
                        ]
                    }
                )
            )
        if endpoint.endswith("artifacts/7/zip"):
            return Result(archive_bytes.getvalue())
        if "/pulls/3603" in endpoint:
            return Result(json.dumps(eligible_pr()))
        return Result(json.dumps({"check_runs": GREEN}))

    source = GhCliVerificationSource(runner=runner)
    assert source.pending_requests("RasmusTho/agentic-pkm-mvp") == [artifact_request()]
    assert source.pull_request("RasmusTho/agentic-pkm-mvp", 3603)["number"] == 3603
    assert source.checks("RasmusTho/agentic-pkm-mvp", HEAD) == GREEN
    assert all(call[:2] == ["gh", "api"] for call in calls)


def _artifact_source_for_request(payload: dict[str, object], *, workflow_run_id: int = 123):
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(payload))

    class Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[-1].endswith("actions/artifacts?per_page=100"):
            return Result(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": 7,
                                "name": f"verification-dispatch-3603-{HEAD}",
                                "size_in_bytes": len(archive_bytes.getvalue()),
                                "expired": False,
                                "workflow_run": {
                                    "id": workflow_run_id,
                                    "repository_id": 456,
                                    "head_repository_id": 456,
                                },
                            }
                        ]
                    }
                )
            )
        return Result(archive_bytes.getvalue())

    return GhCliVerificationSource(runner=runner), calls


def test_pending_request_rejects_oversized_archive_before_buffering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(
                b"x" * (verification_consumer._MAX_ARTIFACT_COMPRESSED_BYTES + 1)
            )
            self.returncode: int | None = None
            self.terminate_calls = 0
            self.wait_calls = 0

        def terminate(self) -> None:
            self.terminate_calls += 1
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    process = Process()
    source = GhCliVerificationSource()
    monkeypatch.setattr(
        source,
        "_json",
        lambda _endpoint: {
            "artifacts": [
                {
                    "id": 7,
                    "name": f"verification-dispatch-3603-{HEAD}",
                    # Even stale or lying metadata cannot bypass the stream cap.
                    "size_in_bytes": 1,
                    "expired": False,
                    "workflow_run": {
                        "id": 123,
                        "repository_id": 456,
                        "head_repository_id": 456,
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        verification_consumer.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    monkeypatch.setattr(
        verification_consumer.io,
        "BytesIO",
        lambda *_args, **_kwargs: pytest.fail("oversized artifact reached BytesIO"),
    )

    with pytest.raises(ValueError, match="compressed size limit"):
        source.pending_requests("RasmusTho/agentic-pkm-mvp")

    assert process.terminate_calls == 1
    assert process.wait_calls >= 1


def test_pending_request_rejects_oversized_archive_members() -> None:
    archives: list[bytes] = []
    member_archive = io.BytesIO()
    with zipfile.ZipFile(member_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(artifact_request()))
        for index in range(verification_consumer._MAX_ARTIFACT_MEMBERS):
            archive.writestr(f"extra-{index}.txt", "x")
    archives.append(member_archive.getvalue())

    aggregate_archive = io.BytesIO()
    with zipfile.ZipFile(aggregate_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(artifact_request()))
        archive.writestr(
            "large.txt",
            b"x" * verification_consumer._MAX_ARTIFACT_UNCOMPRESSED_BYTES,
        )
    archives.append(aggregate_archive.getvalue())

    for payload in archives:
        class Result:
            def __init__(self, stdout):
                self.returncode = 0
                self.stdout = stdout

        def runner(command, **kwargs):
            if command[-1].endswith("actions/artifacts?per_page=100"):
                return Result(
                    json.dumps(
                        {
                            "artifacts": [
                                {
                                    "id": 7,
                                    "name": f"verification-dispatch-3603-{HEAD}",
                                    "size_in_bytes": len(payload),
                                    "expired": False,
                                    "workflow_run": {
                                        "id": 123,
                                        "repository_id": 456,
                                        "head_repository_id": 456,
                                    },
                                }
                            ]
                        }
                    )
                )
            return Result(payload)

        with pytest.raises(ValueError, match="too many members|uncompressed size limit"):
            GhCliVerificationSource(runner=runner).pending_requests(
                "RasmusTho/agentic-pkm-mvp"
            )


def test_pending_request_rejects_repository_mismatch() -> None:
    source, calls = _artifact_source_for_request(
        artifact_request(repository="attacker/redirected-repo")
    )

    with pytest.raises(ValueError, match="artifact repository mismatch"):
        source.pending_requests("RasmusTho/agentic-pkm-mvp")

    assert len(calls) == 2


def test_pending_request_rejects_workflow_run_mismatch() -> None:
    source, calls = _artifact_source_for_request(
        artifact_request(), workflow_run_id=999
    )

    with pytest.raises(ValueError, match="artifact workflow-run mismatch"):
        source.pending_requests("RasmusTho/agentic-pkm-mvp")

    assert len(calls) == 2


@pytest.mark.parametrize("pr,checks,reason", [
    ({}, GREEN, "malformed_pr"),
    (eligible_pr(draft=True), GREEN, "draft"),
    (eligible_pr(state="closed"), GREEN, "closed_unmerged_or_merged"),
    (eligible_pr(head={"ref": "branch", "sha": "b" * 40}), GREEN, "stale_head"),
    (eligible_pr(), [], "missing_checks"),
])
def test_live_truth_gate_rejects_ineligible_requests(tmp_path, pr, checks, reason) -> None:
    launcher = Launcher()
    result = VerificationConsumer(ledger(tmp_path), Truth(pr, checks), Auth(), launcher, "host").consume(request())
    assert result.status == ("backoff" if reason == "missing_checks" else "superseded")
    assert result.stop_reason == (None if reason == "missing_checks" else reason)
    assert launcher.calls == []


def test_eligible_request_invokes_registered_verification_closer_with_minimal_context(tmp_path) -> None:
    launcher = Launcher()
    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    assert result.status == "needs_human"
    pack, resumed = launcher.calls[0]
    assert resumed is None
    assert pack["agent_adapter"] == ".codex/agents/verification-closer.toml"
    assert pack["verification_skill"] == ".codex/skills/verification-and-closure/SKILL.md"
    assert "body" not in pack and "credentials" not in pack


def test_needs_human_receipt_persists_deduplicated_exception(tmp_path) -> None:
    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), Launcher(), "host"
    ).consume(request())

    assert result.status == "needs_human"
    assert result.stop_reason == "authority-critical"
    assert result.terminal_receipt is not None
    exception_id = result.terminal_receipt["exception_id"]
    with state.store._connect() as conn:
        rows = conn.execute(
            "SELECT exception_id, failure_class, head_sha, packet_json "
            "FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["exception_id"] == exception_id
    assert rows[0]["failure_class"] == "authority-critical"
    assert rows[0]["head_sha"] == HEAD
    packet = json.loads(rows[0]["packet_json"])
    assert packet["governing_issue"] == 3603
    assert packet["summary"] == "test"
    assert packet["recommended_option"] == "hold"


def test_needs_human_receipt_requires_valid_complete_owner_packet(tmp_path) -> None:
    class IncompleteHumanLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            receipt["human_exception"] = {
                "failure_class": "coordinator_needs_human",
            }
            return session, receipt

    state = ledger(tmp_path)
    result = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), IncompleteHumanLauncher(), "host"
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == "invalid_human_exception_packet"
    with state.store._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (result.run_id,),
        ).fetchone()[0] == 0


def test_technical_receipt_failures_never_require_owner(tmp_path) -> None:
    class InvalidVerdictLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            receipt["verdict"] = "unknown"
            receipt["human_exception"] = None
            return session, receipt

    class InvalidHeadLauncher(Launcher):
        def launch(self, context_pack, **kwargs):
            session, receipt = super().launch(context_pack, **kwargs)
            receipt["head_sha"] = "not-a-sha"
            return session, receipt

    for launcher, reason in (
        (InvalidVerdictLauncher(), "invalid_verdict"),
        (InvalidHeadLauncher(), "receipt_head_mismatch"),
    ):
        state = ledger(tmp_path / reason)
        result = VerificationConsumer(
            state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
        ).consume(request())

        assert result.status == "failed"
        assert result.stop_reason == reason
        with state.store._connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
                (result.run_id,),
            ).fetchone()[0] == 0


def test_needs_human_receipt_replay_is_idempotent(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = Launcher()
    consumer = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    )

    first = consumer.consume(request())
    second = consumer.consume(request())

    assert second == first
    assert len(launcher.calls) == 1
    with state.store._connect() as conn:
        exception_count = conn.execute(
            "SELECT COUNT(*) FROM verification_exceptions WHERE run_id=?",
            (first.run_id,),
        ).fetchone()[0]
    assert exception_count == 1


def test_delivered_receipt_accepts_matching_post_merge_live_truth(tmp_path) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        TransitionTruth(merged_pr()),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "completed"
    assert result.verified_head_sha == HEAD


@pytest.mark.parametrize(
    ("terminal_pr", "reason"),
    [
        (
            merged_pr(merged=False, merged_at=None, merge_commit_sha=None),
            "receipt_live_truth_closed_unmerged",
        ),
        (
            merged_pr(head={"ref": "branch", "sha": "b" * 40}),
            "receipt_head_mismatch",
        ),
        (
            merged_pr(
                base={"ref": "main", "repo": {"full_name": "attacker/redirect"}}
            ),
            "receipt_live_truth_repository_mismatch",
        ),
        (
            merged_pr(merge_commit_sha=None),
            "receipt_live_truth_missing_merge_evidence",
        ),
    ],
)
def test_delivered_receipt_rejects_closed_unmerged_or_mismatched_merge(
    tmp_path, terminal_pr, reason
) -> None:
    result = VerificationConsumer(
        ledger(tmp_path),
        TransitionTruth(terminal_pr),
        Auth(),
        DeliveredLauncher(),
        "host",
    ).consume(request())

    assert result.status == "failed"
    assert result.stop_reason == reason


def test_codex_launcher_uses_explicit_noninteractive_flags_and_no_api_env(tmp_path, monkeypatch) -> None:
    calls = []

    class Result:
        returncode = 0
        stdout = '{"type":"thread.started","thread_id":"thread-1"}\n{"type":"item.completed","item":{"type":"agent_message","text":"{\\"verdict\\":\\"blocked\\",\\"head_sha\\":\\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\",\\"summary\\":\\"test\\",\\"receipt_ids\\":[],\\"retry_after\\":null,\\"review_events\\":null,\\"human_exception\\":null}"}}\n'

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-pass")
    schema = tmp_path / "receipt.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string"},
                    "head_sha": {"type": "string"},
                    "summary": {"type": "string"},
                    "receipt_ids": {"type": "array", "items": {"type": "string"}},
                    "retry_after": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "review_events": {"type": "null"},
                    "human_exception": {"type": "null"},
                },
                "required": [
                    "verdict",
                    "head_sha",
                    "summary",
                    "receipt_ids",
                    "retry_after",
                    "review_events",
                    "human_exception",
                ],
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    launcher = CodexExecLauncher(tmp_path, schema, tmp_path / "context.json", adapter_path=Path(__file__).resolve().parents[2] / ".codex/agents/verification-closer.toml", runner=runner)
    session, _ = launcher.launch({"head_sha": HEAD})
    command, kwargs = calls[0]
    assert session == "thread-1"
    assert command[:2] == ["codex", "exec"]
    assert command[2:5] == ["--json", "--sandbox", "workspace-write"]
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "CODEX_API_KEY" not in kwargs["env"]
    resumed = launcher.command("thread-1")
    assert resumed[:11] == command[:11]
    assert "resume" in resumed and resumed[resumed.index("resume") + 1] == "thread-1"


class _AuthorityLossOutput:
    def __init__(self, lines: list[str]) -> None:
        self.lines = iter(lines)
        self.reads = 0

    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = next(self.lines)
        self.reads += 1
        return line


class _AuthorityLossProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = _AuthorityLossOutput(lines)
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _BlockedAuthorityLossOutput:
    def __init__(
        self, process: _IgnoringTerminateProcess, lines: list[str]
    ) -> None:
        self.process = process
        self.lines = iter(lines)
        self.reads = 0

    def __iter__(self):
        return self

    def __next__(self) -> str:
        with self.process.condition:
            while not self.process.stdout_released:
                self.process.condition.wait()
        line = next(self.lines)
        self.reads += 1
        return line


class _IgnoringTerminateProcess:
    def __init__(self, lines: list[str]) -> None:
        self.condition = Condition()
        self.stdout_released = False
        self.stdout = _BlockedAuthorityLossOutput(self, lines)
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9
        self.release_stdout()

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            raise verification_consumer.subprocess.TimeoutExpired("codex", timeout)
        return self.returncode

    def release_stdout(self) -> None:
        with self.condition:
            self.stdout_released = True
            self.condition.notify_all()


class _DescendantHeldStdoutProcess(_IgnoringTerminateProcess):
    def __init__(self, lines: list[str]) -> None:
        super().__init__(lines)
        self.pid = 42_023
        self.descendant_alive = True
        self.group_signals: list[tuple[int, int]] = []

    def killpg(self, process_group_id: int, sig: int) -> None:
        self.group_signals.append((process_group_id, sig))
        if process_group_id != self.pid or not self.descendant_alive:
            raise ProcessLookupError(process_group_id)
        if sig == verification_consumer.signal.SIGTERM:
            # The direct parent exits, but its descendant ignores SIGTERM and
            # retains the inherited stdout pipe.
            self.returncode = -verification_consumer.signal.SIGTERM
        elif sig == verification_consumer.signal.SIGKILL:
            self.descendant_alive = False
            self.release_stdout()


def _authority_loss_launcher(tmp_path: Path) -> CodexExecLauncher:
    return CodexExecLauncher(
        tmp_path,
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
    )


def _late_terminal_lines() -> list[str]:
    receipt = {
        "verdict": "needs_human",
        "head_sha": HEAD,
        "summary": "must not be accepted after authority loss",
        "receipt_ids": [],
        "retry_after": None,
        "review_events": None,
    }
    return [
        json.dumps({"type": "thread.started", "thread_id": "thread-lost"}) + "\n",
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(receipt)},
            }
        )
        + "\n",
    ]


def test_heartbeat_authority_loss_terminates_codex_child(tmp_path, monkeypatch) -> None:
    process = _AuthorityLossProcess(_late_terminal_lines())
    monkeypatch.setattr(verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process)

    def lose_authority() -> None:
        raise RuntimeError("verification lease heartbeat rejected")

    with pytest.raises(CodexExecFailure) as exc_info:
        _authority_loss_launcher(tmp_path).launch(
            {"head_sha": HEAD}, on_heartbeat=lose_authority
        )

    assert exc_info.value.receipt["outcome"] == "heartbeat_authority_lost"
    assert process.terminate_calls == 1
    assert process.wait_calls >= 1
    assert process.poll() is not None


def _background_authority_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_IgnoringTerminateProcess, CodexExecFailure]:
    process = _IgnoringTerminateProcess(_late_terminal_lines())
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )
    event_wait = verification_consumer.threading.Event.wait

    def accelerated_wait(event, timeout=None):
        if timeout is not None:
            timeout = min(timeout, 0.01)
        return event_wait(event, timeout)

    monkeypatch.setattr(
        verification_consumer.threading.Event, "wait", accelerated_wait
    )
    outcome: dict[str, BaseException] = {}

    def launch() -> None:
        try:
            _authority_loss_launcher(tmp_path).launch(
                {"head_sha": HEAD},
                on_heartbeat=lambda: (_ for _ in ()).throw(
                    RuntimeError("verification lease heartbeat rejected")
                ),
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=launch, daemon=True)
    worker.start()
    try:
        worker.join(timeout=0.5)
        assert not worker.is_alive(), {
            "launcher_still_blocked": True,
            "terminate_calls": process.terminate_calls,
            "wait_calls": process.wait_calls,
        }
    finally:
        process.release_stdout()
        worker.join(timeout=1)

    error = outcome.get("error")
    assert isinstance(error, CodexExecFailure), outcome
    return process, error


def test_background_heartbeat_authority_loss_kills_blocked_codex_child(
    tmp_path, monkeypatch
) -> None:
    process, error = _background_authority_loss(tmp_path, monkeypatch)

    assert error.receipt["outcome"] == "heartbeat_authority_lost"
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls >= 2
    assert process.poll() == -9


def test_background_authority_loss_rejects_late_stdout(
    tmp_path, monkeypatch
) -> None:
    process, error = _background_authority_loss(tmp_path, monkeypatch)

    assert error.receipt["session_id"] is None
    assert process.stdout.reads == 1


def _process_group_authority_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_DescendantHeldStdoutProcess, CodexExecFailure, dict[str, object]]:
    process = _DescendantHeldStdoutProcess(_late_terminal_lines())
    popen_kwargs: dict[str, object] = {}

    def popen(*args, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setattr(verification_consumer.subprocess, "Popen", popen)
    monkeypatch.setattr(verification_consumer.os, "killpg", process.killpg)
    event_wait = verification_consumer.threading.Event.wait

    def accelerated_wait(event, timeout=None):
        if timeout is not None:
            timeout = min(timeout, 0.01)
        return event_wait(event, timeout)

    monkeypatch.setattr(
        verification_consumer.threading.Event, "wait", accelerated_wait
    )
    outcome: dict[str, BaseException] = {}

    def launch() -> None:
        try:
            _authority_loss_launcher(tmp_path).launch(
                {"head_sha": HEAD},
                on_heartbeat=lambda: (_ for _ in ()).throw(
                    RuntimeError("verification lease heartbeat rejected")
                ),
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=launch, daemon=True)
    worker.start()
    try:
        worker.join(timeout=0.5)
        assert not worker.is_alive(), {
            "launcher_still_blocked": True,
            "group_signals": process.group_signals,
            "parent_returncode": process.returncode,
            "wait_calls": process.wait_calls,
        }
    finally:
        process.release_stdout()
        worker.join(timeout=1)

    error = outcome.get("error")
    assert isinstance(error, CodexExecFailure), outcome
    return process, error, popen_kwargs


def test_authority_loss_terminates_process_group_when_descendant_holds_stdout(
    tmp_path, monkeypatch
) -> None:
    process, error, popen_kwargs = _process_group_authority_loss(
        tmp_path, monkeypatch
    )

    assert error.receipt["outcome"] == "heartbeat_authority_lost"
    assert popen_kwargs["start_new_session"] is True
    assert process.returncode == -verification_consumer.signal.SIGTERM
    assert not process.descendant_alive


def test_authority_loss_kills_only_coordinator_process_group(
    tmp_path, monkeypatch
) -> None:
    process, _, _ = _process_group_authority_loss(tmp_path, monkeypatch)

    assert process.group_signals == [
        (process.pid, verification_consumer.signal.SIGTERM),
        (process.pid, 0),
        (process.pid, verification_consumer.signal.SIGKILL),
    ]


def test_process_group_authority_loss_rejects_late_descendant_output(
    tmp_path, monkeypatch
) -> None:
    process, error, _ = _process_group_authority_loss(tmp_path, monkeypatch)

    assert error.receipt["session_id"] is None
    assert process.stdout.reads == 1


def test_thread_start_authority_loss_terminates_codex_child(
    tmp_path, monkeypatch
) -> None:
    process = _AuthorityLossProcess(_late_terminal_lines())
    monkeypatch.setattr(
        verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process
    )

    def reject_thread_start(_session_id: str) -> None:
        raise ValueError("verification start ownership mismatch")

    with pytest.raises(CodexExecFailure) as exc_info:
        _authority_loss_launcher(tmp_path).launch(
            {"head_sha": HEAD}, on_thread_started=reject_thread_start
        )

    assert exc_info.value.receipt["outcome"] == "thread_start_authority_lost"
    assert process.terminate_calls == 1
    assert process.wait_calls >= 1
    assert process.poll() is not None
    assert process.stdout.reads == 1


def test_authority_lost_child_output_is_rejected(tmp_path, monkeypatch) -> None:
    process = _AuthorityLossProcess(_late_terminal_lines())
    monkeypatch.setattr(verification_consumer.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(CodexExecFailure, match="heartbeat authority lost"):
        _authority_loss_launcher(tmp_path).launch(
            {"head_sha": HEAD},
            on_heartbeat=lambda: (_ for _ in ()).throw(RuntimeError("lease lost")),
        )

    assert process.stdout.reads == 1


def test_heartbeat_authority_loss_persists_one_backoff_receipt(tmp_path) -> None:
    state = ledger(tmp_path)

    class AuthorityLostLauncher(Launcher):
        def launch(
            self,
            context_pack,
            *,
            resume_session_id=None,
            on_thread_started=None,
            on_heartbeat=None,
        ):
            if on_thread_started:
                on_thread_started("thread-lost")
            with state.store._connect() as conn:
                conn.execute(
                    "UPDATE verification_runs "
                    "SET lease_expires_at='2000-01-01T00:00:00+00:00'"
                )
                conn.commit()
            raise CodexExecFailure(
                {
                    "outcome": "heartbeat_authority_lost",
                    "returncode": -15,
                    "stderr": "heartbeat authority lost",
                    "terminal_error": "ValueError: verification heartbeat ownership mismatch",
                    "session_id": "thread-lost",
                }
            )

    result = VerificationConsumer(
        state,
        Truth(eligible_pr(), GREEN),
        Auth(),
        AuthorityLostLauncher(),
        "host",
    ).consume(request())

    assert result.status == "backoff"
    assert result.terminal_receipt["outcome"] == "heartbeat_authority_lost"
    with state.store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verification_attempts").fetchone()[0] == 0


def test_auth_preflight_requires_chatgpt_keyring_and_login_status(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'forced_login_method = "chatgpt"\ncli_auth_credentials_store = "keyring"\n',
        encoding="utf-8",
    )
    calls = []

    class Result:
        returncode = 0

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    receipt = CodexChatGPTAuthPreflight(config, runner=runner).check()
    assert receipt == AuthReceipt(True, "chatgpt", "keyring")
    assert calls[0][0] == ["codex", "login", "status"]


def test_process_runner_injection_preserves_falsey_callable(tmp_path) -> None:
    class FalseRunner:
        def __bool__(self) -> bool:
            return False

        def __call__(self, *args, **kwargs):
            raise AssertionError("the injected runner should not be called by construction")

    runner = FalseRunner()
    config = tmp_path / "config.toml"
    config.write_text(
        'forced_login_method = "chatgpt"\ncli_auth_credentials_store = "keyring"\n',
        encoding="utf-8",
    )
    launcher = CodexExecLauncher(
        tmp_path,
        tmp_path / "receipt.schema.json",
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2] / ".codex/agents/verification-closer.toml",
        runner=runner,
    )

    assert GhCliVerificationSource(runner=runner).runner is runner
    assert CodexChatGPTAuthPreflight(config, runner=runner).runner is runner
    assert launcher.runner is runner


def test_production_receipt_schema_uses_codex_subset_and_preserves_semantics() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "app/dispatcher/schemas/verification_closer_receipt.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    verification_consumer.validate_codex_output_schema(schema)
    assert "allOf" not in json.dumps(schema)
    assert "oneOf" not in json.dumps(schema)

    valid = {
        "verdict": "delivered",
        "head_sha": HEAD,
        "summary": "verified",
        "receipt_ids": ["review-1", "review-2"],
        "retry_after": None,
        "review_events": [
            {
                "kind": "review",
                "session_id": "review-1",
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "outcome": "clean",
                "finding_id": None,
                "strongest": None,
            },
            {
                "kind": "review",
                "session_id": "review-2",
                "capability": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "outcome": "clean",
                "finding_id": None,
                "strongest": None,
            },
        ],
        "human_exception": None,
    }
    verification_consumer.validate_verification_closer_receipt(valid, schema)

    without_reviews = dict(valid, review_events=None)
    with pytest.raises(jsonschema.ValidationError, match="two review events"):
        verification_consumer.validate_verification_closer_receipt(without_reviews, schema)

    repair_without_finding = dict(valid)
    repair_without_finding["review_events"] = [
        dict(valid["review_events"][0], kind="repair"),  # type: ignore[index]
        valid["review_events"][1],  # type: ignore[index]
    ]
    with pytest.raises(jsonschema.ValidationError, match="finding_id"):
        verification_consumer.validate_verification_closer_receipt(
            repair_without_finding, schema
        )


def test_codex_launcher_rejects_unsupported_schema_before_process_start(tmp_path) -> None:
    schema = tmp_path / "receipt.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"verdict": {"type": "string"}},
                "required": ["verdict"],
                "additionalProperties": False,
                "allOf": [{"properties": {"verdict": {"const": "delivered"}}}],
            }
        ),
        encoding="utf-8",
    )

    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("invalid schema must fail before process start")

    launcher = CodexExecLauncher(
        tmp_path,
        schema,
        tmp_path / "context.json",
        adapter_path=Path(__file__).resolve().parents[2]
        / ".codex/agents/verification-closer.toml",
        runner=runner,
    )
    with pytest.raises(ValueError, match=r"unsupported output-schema keyword.*allOf"):
        launcher.launch({"head_sha": HEAD})
    assert calls == []


def test_restart_recovers_without_duplicate_agent_or_mutation(tmp_path) -> None:
    launcher = Launcher()
    state = ledger(tmp_path)
    consumer = VerificationConsumer(state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host")
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "original")
    running = state.start(run.run_id, "original", claimed.lease_id, "thread-new", {"head_sha": HEAD})
    assert consumer.recover(running.run_id).run_id == running.run_id
    assert launcher.calls == []

    with consumer.ledger.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (running.run_id,),
        )
        conn.commit()
    resumed = consumer.recover(running.run_id)
    assert resumed.status == "needs_human"
    assert launcher.calls[-1][1] == "thread-new"


def test_recover_rejects_live_head_movement_before_resume(tmp_path) -> None:
    moved_head = "b" * 40

    class MovingTruth:
        def __init__(self) -> None:
            self.pull_calls = 0
            self.check_calls = 0

        def pull_request(self, repository, pr_number):
            self.pull_calls += 1
            return eligible_pr(head={"ref": "branch", "sha": moved_head})

        def checks(self, repository, head_sha):
            self.check_calls += 1
            raise AssertionError("stale recovery must not fetch replacement-head checks")

    class UnreachedAuth:
        def __init__(self) -> None:
            self.calls = 0

        def check(self):
            self.calls += 1
            raise AssertionError("stale recovery must not run auth preflight")

    state = ledger(tmp_path)
    launcher = Launcher()
    truth = MovingTruth()
    auth = UnreachedAuth()
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "original")
    running = state.start(
        run.run_id,
        "original",
        claimed.lease_id,
        "old-session",
        {"head_sha": HEAD},
    )
    with state.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (running.run_id,),
        )
        conn.commit()

    consumer = VerificationConsumer(state, truth, auth, launcher, "replacement")
    with pytest.raises(ValueError, match="no longer resumable: stale_head"):
        consumer.recover(running.run_id)

    current = state.get(running.run_id)
    assert current is not None
    assert current.status == "running"
    assert current.head_sha == HEAD
    assert current.coordinator_session_id == "old-session"
    assert truth.pull_calls == 1
    assert truth.check_calls == 0
    assert auth.calls == 0
    assert launcher.calls == []


def test_rate_limit_queues_without_api_fallback_or_duplicate(tmp_path) -> None:
    state = ledger(tmp_path)
    launcher = RateLimitedLauncher()
    queued = VerificationConsumer(
        state, Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    assert queued.status == "backoff"
    assert queued.terminal_receipt["api_fallback"] is False
    assert state.ingest(request()).run_id == queued.run_id
    with state.store._connect() as conn:
        attempts = conn.execute(
            "SELECT attempt_kind, outcome FROM verification_attempts"
        ).fetchall()
    assert [(row[0], row[1]) for row in attempts] == [("verification", "rate_limited")]
