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
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from app.dispatcher.verification_dispatch import VerificationDispatchLedger, VerificationRun


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
    def launch(
        self, context_pack: Mapping[str, object], *, resume_session_id: str | None = None
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


class CodexExecLauncher:
    """Explicit least-privilege non-interactive verification coordinator."""

    def __init__(
        self,
        worktree: Path,
        receipt_schema: Path,
        context_path: Path,
        runner=subprocess.run,
    ) -> None:
        self.worktree = worktree
        self.receipt_schema = receipt_schema
        self.context_path = context_path
        self.runner = runner

    def command(self, resume_session_id: str | None = None) -> list[str]:
        command = [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "--output-schema",
            str(self.receipt_schema),
        ]
        if resume_session_id:
            command += ["resume", resume_session_id]
        return command + [
            "Use the registered verification_closer adapter. Read the immutable "
            f"dispatch context at {self.context_path}; load and obey "
            ".codex/skills/verification-and-closure/SKILL.md."
        ]

    def launch(
        self, context_pack: Mapping[str, object], *, resume_session_id: str | None = None
    ) -> tuple[str, Mapping[str, object]]:
        # This generic launcher writes only non-secret request identity into its
        # isolated worktree. Host service configuration stays outside Git.
        self.context_path.write_text(
            json.dumps(context_pack, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        result = self.runner(
            self.command(resume_session_id),
            cwd=self.worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        thread_id: str | None = resume_session_id
        terminal: dict[str, object] = {"returncode": result.returncode}
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
            if event.get("type") in {"turn.completed", "turn.failed", "error"}:
                terminal = event
        if not thread_id:
            raise RuntimeError("codex exec produced no thread identity")
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


class VerificationConsumer:
    def __init__(
        self,
        ledger: VerificationDispatchLedger,
        truth: LiveTruthSource,
        auth: AuthPreflight,
        launcher: CoordinatorLauncher,
        holder: str,
        capability: str = "verification_closer_adapter",
        reasoning_effort: str = "configured",
    ) -> None:
        self.ledger, self.truth, self.auth, self.launcher, self.holder = (
            ledger, truth, auth, launcher, holder
        )
        self.capability = capability
        self.reasoning_effort = reasoning_effort

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
            return self.ledger.terminal(
                run.run_id, "superseded", {"outcome": "noop", "reason": rejection}, reason=rejection
            )
        auth = self.auth.check()
        if not auth.ok:
            claimed = self.ledger.claim(run.run_id, self.holder)
            return self.ledger.backoff(
                claimed.run_id,
                {"outcome": "blocked", "reason": auth.reason, "auth_mode": auth.auth_mode},
                retry_after="auth_required",
            )
        claimed = self.ledger.claim(run.run_id, self.holder)
        pack = context_pack(claimed, pr)
        session_id, receipt = self.launcher.launch(
            pack, resume_session_id=claimed.coordinator_session_id
        )
        self.ledger.record_attempt(
            claimed.run_id,
            "verification",
            session_id,
            self.capability,
            self.reasoning_effort,
            pack,
            "rate_limited" if self._rate_limited(receipt) else "launched",
            receipt,
        )
        if self._rate_limited(receipt):
            return self.ledger.backoff(
                claimed.run_id,
                {"outcome": "rate_limited", "api_fallback": False, "receipt": dict(receipt)},
                retry_after=str(receipt.get("retry_after") or "bounded_backoff"),
            )
        return self.ledger.start(claimed.run_id, self.holder, session_id, pack)

    def recover(self, run_id: str) -> VerificationRun:
        run = self.ledger.get(run_id)
        if run is None or run.status != "running" or not run.coordinator_session_id or not run.context_pack:
            raise ValueError("verification run is not resumable")
        session_id, _ = self.launcher.launch(
            run.context_pack, resume_session_id=run.coordinator_session_id
        )
        if session_id != run.coordinator_session_id:
            raise RuntimeError("resume changed coordinator session identity")
        return run
