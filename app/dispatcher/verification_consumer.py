"""Host-neutral consumer for verification dispatch requests.

GitHub and Codex are injected boundaries.  The consumer owns eligibility,
dedupe, auth preflight, context minimisation, and launch receipts; the launched
``verification_closer`` remains the only mutation/merge authority.
"""

from __future__ import annotations

import json
import io
import os
import subprocess
import threading
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

import jsonschema

from app.dispatcher.verification_dispatch import (
    VerificationBackoffPending,
    VerificationDispatchLedger,
    VerificationRun,
    VerificationSubscriptionBusy,
)


@dataclass(frozen=True)
class AuthReceipt:
    ok: bool
    auth_mode: str | None
    credential_store: str | None
    reason: str | None = None


class LiveTruthSource(Protocol):
    def pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]: ...

    def checks(self, repository: str, head_sha: str) -> Sequence[Mapping[str, object]]: ...


class GhCliVerificationSource:
    """Read request artifacts and live truth with the host's authenticated gh CLI."""

    def __init__(self, runner=subprocess.run) -> None:
        self.runner = runner

    def _json(self, endpoint: str) -> object:
        result = self.runner(
            ["gh", "api", endpoint], capture_output=True, text=True, check=False, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh read failed for {endpoint}")
        return json.loads(result.stdout)

    def pending_requests(
        self, repository: str, *, limit: int = 20
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("artifact request limit must be positive")
        payload = self._json(f"repos/{repository}/actions/artifacts?per_page=100")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("artifacts"), list):
            raise RuntimeError("malformed GitHub artifact listing")
        requests: list[dict[str, object]] = []
        for artifact in payload["artifacts"]:
            if len(requests) >= limit:
                break
            if not isinstance(artifact, Mapping):
                continue
            name, artifact_id = artifact.get("name"), artifact.get("id")
            if (
                not isinstance(name, str)
                or not name.startswith("verification-dispatch-")
                or artifact.get("expired") is True
                or not isinstance(artifact_id, int)
                or isinstance(artifact_id, bool)
            ):
                continue
            result = self.runner(
                ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"],
                capture_output=True,
                text=False,
                check=False,
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(f"failed to download verification artifact {artifact_id}")
            with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
                candidates = [
                    info
                    for info in archive.infolist()
                    if info.filename == "request.json" or info.filename.endswith("/request.json")
                ]
                if len(candidates) != 1:
                    raise ValueError("verification artifact must contain exactly one request.json")
                info = candidates[0]
                if info.file_size > 1_000_000:
                    raise ValueError("verification request artifact exceeds size limit")
                request = json.loads(archive.read(info))
            if not isinstance(request, dict):
                raise ValueError("verification request artifact is not an object")
            requests.append(request)
        return requests

    def pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        payload = self._json(f"repos/{repository}/pulls/{pr_number}")
        if not isinstance(payload, Mapping):
            raise RuntimeError("malformed GitHub pull request response")
        return payload

    def checks(self, repository: str, head_sha: str) -> Sequence[Mapping[str, object]]:
        payload = self._json(f"repos/{repository}/commits/{head_sha}/check-runs?per_page=100")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("check_runs"), list):
            raise RuntimeError("malformed GitHub check-runs response")
        return [row for row in payload["check_runs"] if isinstance(row, Mapping)]


class CoordinatorLauncher(Protocol):
    config: "LaunchConfig"

    def launch(
        self,
        context_pack: Mapping[str, object],
        *,
        resume_session_id: str | None = None,
        on_thread_started: Callable[[str], None] | None = None,
        on_heartbeat: Callable[[], None] | None = None,
    ) -> tuple[str, Mapping[str, object]]: ...


class AuthPreflight(Protocol):
    def check(self) -> AuthReceipt: ...


class CodexChatGPTAuthPreflight:
    """Check saved ChatGPT login and keyring policy without reading auth.json."""

    def __init__(self, config_path: Path, runner=subprocess.run) -> None:
        self.config_path = config_path
        self.runner = runner

    def check(self) -> AuthReceipt:
        try:
            config = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return AuthReceipt(False, None, None, "host Codex config unavailable")
        mode = config.get("forced_login_method")
        store = config.get("cli_auth_credentials_store")
        if mode != "chatgpt" or store != "keyring":
            return AuthReceipt(False, str(mode or ""), str(store or ""), "ChatGPT/keyring policy mismatch")
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        result = self.runner(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            return AuthReceipt(False, "chatgpt", "keyring", "codex login status failed")
        return AuthReceipt(True, "chatgpt", "keyring")


@dataclass(frozen=True)
class LaunchConfig:
    adapter_name: str
    model: str
    reasoning_effort: str
    sandbox: str
    developer_instructions: str


class CodexExecLauncher:
    """Explicit least-privilege non-interactive verification coordinator."""

    def __init__(
        self,
        worktree: Path,
        receipt_schema: Path,
        context_path: Path,
        adapter_path: Path | None = None,
        runner=subprocess.run,
    ) -> None:
        self.worktree = worktree
        self.receipt_schema = receipt_schema
        self.context_path = context_path
        self.runner = runner
        self.adapter_path = adapter_path or worktree / ".codex/agents/verification-closer.toml"
        try:
            adapter = tomllib.loads(self.adapter_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError("verification closer adapter is unavailable") from exc
        required = {
            "name": "verification_closer",
            "model": "gpt-5.6-terra",
            "model_reasoning_effort": "high",
            "sandbox_mode": "workspace-write",
        }
        if any(adapter.get(key) != value for key, value in required.items()):
            raise ValueError("verification closer adapter contract mismatch")
        instructions = adapter.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise ValueError("verification closer developer instructions are missing")
        self.config = LaunchConfig(
            adapter_name="verification_closer",
            model="gpt-5.6-terra",
            reasoning_effort="high",
            sandbox="workspace-write",
            developer_instructions=instructions.strip(),
        )

    def command(self, resume_session_id: str | None = None) -> list[str]:
        command = [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            self.config.sandbox,
            "--model",
            self.config.model,
            "-c",
            f'model_reasoning_effort="{self.config.reasoning_effort}"',
            "--output-schema",
            str(self.receipt_schema),
        ]
        if resume_session_id:
            command += ["resume", resume_session_id]
        return command + [
            f"Use the registered {self.config.adapter_name} adapter.\n"
            f"{self.config.developer_instructions}\n"
            "Read the immutable "
            f"dispatch context at {self.context_path}; load and obey "
            ".codex/skills/verification-and-closure/SKILL.md."
        ]

    def launch(
        self,
        context_pack: Mapping[str, object],
        *,
        resume_session_id: str | None = None,
        on_thread_started: Callable[[str], None] | None = None,
        on_heartbeat: Callable[[], None] | None = None,
    ) -> tuple[str, Mapping[str, object]]:
        # This generic launcher writes only non-secret request identity into its
        # isolated worktree. Host service configuration stays outside Git.
        self.context_path.write_text(
            json.dumps(context_pack, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        stop_heartbeat = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        if self.runner is subprocess.run:
            process = subprocess.Popen(
                self.command(resume_session_id), cwd=self.worktree, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            assert process.stdout is not None
            lines = process.stdout
            if on_heartbeat:
                def pulse() -> None:
                    while not stop_heartbeat.wait(30):
                        on_heartbeat()
                heartbeat_thread = threading.Thread(target=pulse, daemon=True)
                heartbeat_thread.start()
        else:
            result = self.runner(
                self.command(resume_session_id), cwd=self.worktree, env=env,
                capture_output=True, text=True, check=False,
            )
            lines = result.stdout.splitlines()
        thread_id: str | None = resume_session_id
        terminal: dict[str, object] | None = None
        schema = json.loads(self.receipt_schema.read_text(encoding="utf-8"))
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
                if on_thread_started:
                    on_thread_started(thread_id)
            if on_heartbeat:
                on_heartbeat()
            if event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, Mapping) and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str):
                        try:
                            candidate = json.loads(text)
                            jsonschema.validate(candidate, schema)
                        except (json.JSONDecodeError, jsonschema.ValidationError):
                            continue
                        terminal = candidate
        if self.runner is subprocess.run:
            process.wait()
            stop_heartbeat.set()
            if heartbeat_thread:
                heartbeat_thread.join(timeout=1)
        if not thread_id:
            raise RuntimeError("codex exec produced no thread identity")
        if terminal is None:
            raise RuntimeError("codex exec produced no schema-valid final agent receipt")
        return thread_id, terminal


def _nested(mapping: Mapping[str, object], *keys: str) -> object:
    value: object = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def live_truth_rejection(
    run: VerificationRun,
    pr: Mapping[str, object],
    checks: Sequence[Mapping[str, object]],
) -> str | None:
    if not isinstance(pr.get("number"), int) or isinstance(pr.get("number"), bool):
        return "malformed_pr"
    if pr.get("state") != "open" or pr.get("merged_at") is not None:
        return "closed_unmerged_or_merged"
    if pr.get("draft") is True:
        return "draft"
    if _nested(pr, "head", "sha") != run.head_sha:
        return "stale_head"
    if not checks:
        return "missing_checks"
    for check in checks:
        if check.get("status") != "completed" or check.get("conclusion") not in {
            "success", "neutral", "skipped"
        }:
            return "checks_not_green"
    return None


def context_pack(run: VerificationRun, pr: Mapping[str, object]) -> dict[str, object]:
    """Return the immutable minimum; no issue/diff/log/untrusted body text."""
    linked_issue = run.request.get("linked_issue")
    return {
        "contract": "verification_closer_dispatch_context.v1",
        "run_id": run.run_id,
        "repository": run.repository,
        "pr_number": run.pr_number,
        "linked_issue": linked_issue if isinstance(linked_issue, int) else None,
        "base_ref": _nested(pr, "base", "ref"),
        "head_ref": _nested(pr, "head", "ref"),
        "head_sha": run.head_sha,
        "stage": run.stage,
        "verification_skill": ".codex/skills/verification-and-closure/SKILL.md",
        "agent_adapter": ".codex/agents/verification-closer.toml",
        "idempotency_key": run.idempotency_key,
    }


def _retry_at(value: object = None) -> str:
    now = datetime.now(timezone.utc)
    delay = timedelta(minutes=15)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        delay = timedelta(seconds=max(1, min(float(value), 3600)))
    elif isinstance(value, str):
        stripped = value.strip().lower()
        try:
            parsed = datetime.fromisoformat(stripped.replace("z", "+00:00"))
            if parsed.tzinfo is not None:
                bounded = min(max(parsed.astimezone(timezone.utc), now + timedelta(seconds=1)), now + timedelta(hours=1))
                return bounded.isoformat(timespec="microseconds")
        except ValueError:
            pass
        if stripped.endswith(("s", "m", "h")):
            try:
                amount = float(stripped[:-1])
                multiplier = {"s": 1, "m": 60, "h": 3600}[stripped[-1]]
                delay = timedelta(seconds=max(1, min(amount * multiplier, 3600)))
            except ValueError:
                pass
    return (now + delay).isoformat(timespec="microseconds")


class VerificationConsumer:
    def __init__(
        self,
        ledger: VerificationDispatchLedger,
        truth: LiveTruthSource,
        auth: AuthPreflight,
        launcher: CoordinatorLauncher,
        holder: str,
    ) -> None:
        self.ledger, self.truth, self.auth, self.launcher, self.holder = (
            ledger, truth, auth, launcher, holder
        )

    @staticmethod
    def _lease_is_live(run: VerificationRun) -> bool:
        if not run.lease_expires_at:
            return False
        return datetime.fromisoformat(run.lease_expires_at.replace("Z", "+00:00")) > datetime.now(
            timezone.utc
        )

    @staticmethod
    def _rate_limited(receipt: Mapping[str, object]) -> bool:
        encoded = json.dumps(receipt, sort_keys=True).lower()
        return any(token in encoded for token in ("rate limit", "rate_limit", "credit exhausted"))

    def consume(self, request: Mapping[str, object]) -> VerificationRun:
        run = self.ledger.ingest(request)
        if run.status in {"completed", "failed", "needs_human", "superseded"}:
            return run
        if run.status in {"claimed", "running"} and self._lease_is_live(run):
            # An active delivery is already owned. Restart recovery is an
            # explicit operation so replayed artifacts cannot duplicate it.
            return run
        pr = self.truth.pull_request(run.repository, run.pr_number)
        checks = self.truth.checks(run.repository, run.head_sha)
        rejection = live_truth_rejection(run, pr, checks)
        if rejection:
            if rejection in {"missing_checks", "checks_not_green"}:
                return self.ledger.defer_unclaimed(
                    run.run_id,
                    {"outcome": "deferred", "reason": rejection},
                    _retry_at(),
                )
            return self.ledger.supersede_unclaimed(
                run.run_id, {"outcome": "noop", "reason": rejection}, reason=rejection
            )
        auth = self.auth.check()
        if not auth.ok:
            try:
                claimed = self.ledger.claim(run.run_id, self.holder)
            except (VerificationSubscriptionBusy, VerificationBackoffPending):
                current = self.ledger.get(run.run_id)
                assert current is not None
                return current
            return self.ledger.backoff(
                claimed.run_id,
                {"outcome": "blocked", "reason": auth.reason, "auth_mode": auth.auth_mode},
                retry_after=_retry_at(),
                holder=self.holder,
                lease_id=claimed.lease_id or "",
            )
        try:
            claimed = self.ledger.claim(run.run_id, self.holder)
        except (VerificationSubscriptionBusy, VerificationBackoffPending):
            current = self.ledger.get(run.run_id)
            assert current is not None
            return current
        return self._launch(claimed, pr)

    def _launch(
        self, claimed: VerificationRun, pr: Mapping[str, object]
    ) -> VerificationRun:
        lease_id = claimed.lease_id
        if not lease_id:
            raise RuntimeError("claimed verification run has no lease token")
        pack = context_pack(claimed, pr)

        def started(session_id: str) -> None:
            current = self.ledger.get(claimed.run_id)
            if current is not None and current.status == "claimed":
                self.ledger.start(claimed.run_id, self.holder, lease_id, session_id, pack)

        def heartbeat() -> None:
            self.ledger.heartbeat(claimed.run_id, self.holder, lease_id)

        session_id, receipt = self.launcher.launch(
            pack,
            resume_session_id=claimed.coordinator_session_id,
            on_thread_started=started,
            on_heartbeat=heartbeat,
        )
        current = self.ledger.get(claimed.run_id)
        if current is not None and current.status == "claimed":
            started(session_id)
        config = self.launcher.config
        self.ledger.record_attempt(
            claimed.run_id,
            "verification",
            session_id,
            config.model,
            config.reasoning_effort,
            pack,
            "rate_limited" if self._rate_limited(receipt) else "launched",
            receipt,
        )
        if self._rate_limited(receipt):
            return self.ledger.backoff(
                claimed.run_id,
                {"outcome": "rate_limited", "api_fallback": False, "receipt": dict(receipt)},
                retry_after=_retry_at(receipt.get("retry_after")),
                holder=self.holder,
                lease_id=lease_id,
            )
        if receipt.get("head_sha") != claimed.head_sha:
            return self.ledger.terminal(
                claimed.run_id, "needs_human", dict(receipt),
                reason="receipt_head_mismatch", holder=self.holder, lease_id=lease_id,
            )
        verdict = receipt.get("verdict")
        if verdict == "retry":
            return self.ledger.backoff(
                claimed.run_id, dict(receipt), _retry_at(receipt.get("retry_after")),
                holder=self.holder, lease_id=lease_id,
            )
        status = {"delivered": "completed", "blocked": "failed", "needs_human": "needs_human"}.get(verdict)
        if status is None:
            return self.ledger.terminal(
                claimed.run_id, "needs_human", dict(receipt), reason="invalid_verdict",
                holder=self.holder, lease_id=lease_id,
            )
        try:
            return self.ledger.terminal(
                claimed.run_id, status, dict(receipt), holder=self.holder, lease_id=lease_id
            )
        except ValueError as exc:
            if status != "completed" or "two fresh clean reviews" not in str(exc):
                raise
            return self.ledger.terminal(
                claimed.run_id, "needs_human", dict(receipt), reason="closure_gate_not_proven",
                holder=self.holder, lease_id=lease_id,
            )

    def recover(self, run_id: str) -> VerificationRun:
        run = self.ledger.get(run_id)
        if run is None or run.status != "running" or not run.coordinator_session_id or not run.context_pack:
            raise ValueError("verification run is not resumable")
        if self._lease_is_live(run):
            return run
        pr = self.truth.pull_request(run.repository, run.pr_number)
        checks = self.truth.checks(run.repository, run.head_sha)
        rejection = live_truth_rejection(run, pr, checks)
        if rejection:
            raise ValueError(f"verification run is no longer resumable: {rejection}")
        if not self.auth.check().ok:
            raise ValueError("verification auth preflight failed")
        claimed = self.ledger.claim(run.run_id, self.holder)
        return self._launch(claimed, pr)
