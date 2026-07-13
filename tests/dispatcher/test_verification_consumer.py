from __future__ import annotations

from dataclasses import dataclass
import io
import json
import zipfile

import pytest

from app.dispatcher.verification_consumer import (
    AuthReceipt,
    CodexChatGPTAuthPreflight,
    CodexExecLauncher,
    GhCliVerificationSource,
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
    def __init__(self): self.calls = []
    def launch(self, context_pack, *, resume_session_id=None):
        self.calls.append((context_pack, resume_session_id))
        return resume_session_id or "thread-new", {"type": "turn.completed"}


class RateLimitedLauncher(Launcher):
    def launch(self, context_pack, *, resume_session_id=None):
        self.calls.append((context_pack, resume_session_id))
        return resume_session_id or "thread-rate", {
            "type": "error", "message": "rate limit exhausted", "retry_after": "1h"
        }


def eligible_pr(**updates):
    value = {
        "number": 3603, "state": "open", "draft": False, "merged_at": None,
        "base": {"ref": "main"}, "head": {"ref": "branch", "sha": HEAD},
    }
    value.update(updates)
    return value


GREEN = [{"status": "completed", "conclusion": "success"}]


def test_gh_source_fetches_bounded_artifact_and_live_truth_without_shell(tmp_path) -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("verification-dispatch/request.json", json.dumps(request()))

    class Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        endpoint = command[-1]
        if endpoint.endswith("actions/artifacts?per_page=100"):
            return Result(json.dumps({"artifacts": [{"id": 7, "name": "verification-dispatch-3603-head", "expired": False}]}))
        if endpoint.endswith("artifacts/7/zip"):
            return Result(archive_bytes.getvalue())
        if "/pulls/3603" in endpoint:
            return Result(json.dumps(eligible_pr()))
        return Result(json.dumps({"check_runs": GREEN}))

    source = GhCliVerificationSource(runner=runner)
    assert source.pending_requests("RasmusTho/agentic-pkm-mvp") == [request()]
    assert source.pull_request("RasmusTho/agentic-pkm-mvp", 3603)["number"] == 3603
    assert source.checks("RasmusTho/agentic-pkm-mvp", HEAD) == GREEN
    assert all(call[:2] == ["gh", "api"] for call in calls)


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
    assert result.status == "superseded"
    assert result.stop_reason == reason
    assert launcher.calls == []


def test_eligible_request_invokes_registered_verification_closer_with_minimal_context(tmp_path) -> None:
    launcher = Launcher()
    result = VerificationConsumer(
        ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host"
    ).consume(request())
    assert result.status == "running"
    pack, resumed = launcher.calls[0]
    assert resumed is None
    assert pack["agent_adapter"] == ".codex/agents/verification-closer.toml"
    assert pack["verification_skill"] == ".codex/skills/verification-and-closure/SKILL.md"
    assert "body" not in pack and "credentials" not in pack


def test_codex_launcher_uses_explicit_noninteractive_flags_and_no_api_env(tmp_path, monkeypatch) -> None:
    calls = []

    class Result:
        returncode = 0
        stdout = '{"type":"thread.started","thread_id":"thread-1"}\n{"type":"turn.completed"}\n'

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-pass")
    schema = tmp_path / "receipt.schema.json"
    schema.write_text("{}", encoding="utf-8")
    launcher = CodexExecLauncher(tmp_path, schema, tmp_path / "context.json", runner=runner)
    session, _ = launcher.launch({"head_sha": HEAD})
    command, kwargs = calls[0]
    assert session == "thread-1"
    assert command[:2] == ["codex", "exec"]
    assert ["--json", "--sandbox", "workspace-write", "--output-schema"] == [
        command[2], command[3], command[4], command[5]
    ]
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "CODEX_API_KEY" not in kwargs["env"]
    resumed = launcher.command("thread-1")
    assert resumed[:7] == command[:7]
    assert resumed[7:9] == ["resume", "thread-1"]


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


def test_restart_recovers_without_duplicate_agent_or_mutation(tmp_path) -> None:
    launcher = Launcher()
    consumer = VerificationConsumer(ledger(tmp_path), Truth(eligible_pr(), GREEN), Auth(), launcher, "host")
    running = consumer.consume(request())
    assert consumer.recover(running.run_id).run_id == running.run_id
    assert launcher.calls[-1][1] == "thread-new"
    assert consumer.consume(request()).run_id == running.run_id
    assert len(launcher.calls) == 2

    with consumer.ledger.store._connect() as conn:
        conn.execute(
            "UPDATE verification_runs SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE run_id=?",
            (running.run_id,),
        )
        conn.commit()
    resumed = consumer.consume(request())
    assert resumed.status == "running"
    assert launcher.calls[-1][1] == "thread-new"


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
