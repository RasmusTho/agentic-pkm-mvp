"""Host-neutral consumer for verification dispatch requests.

GitHub and Codex are injected boundaries.  The consumer owns eligibility,
dedupe, auth preflight, context minimisation, and launch receipts; the launched
``verification_closer`` remains the only mutation/merge authority.
"""

from __future__ import annotations

import hashlib
import json
import io
import os
import re
import signal
import subprocess
import tempfile
import threading
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence, cast

import jsonschema

from app.dispatcher.verification_dispatch import (
    VerificationBackoffPending,
    VerificationDispatchLedger,
    VerificationRun,
    VerificationSubscriptionBusy,
)
from app.dispatcher.verification_agent_loop import (
    HUMAN_EXCEPTION_PACKET_FIELDS,
    VerificationAgentLoop,
    valid_human_exception_packet,
)
from app.dispatcher.verification_contract import resolve_issue_contract


@dataclass(frozen=True)
class AuthReceipt:
    ok: bool
    auth_mode: str | None
    credential_store: str | None
    reason: str | None = None


class LiveTruthSource(Protocol):
    def pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]: ...

    def checks(self, repository: str, head_sha: str) -> Sequence[Mapping[str, object]]: ...


class ProcessResult(Protocol):
    returncode: int
    stdout: str | bytes
    stderr: str | bytes | None


ProcessRunner = Callable[..., ProcessResult]

_MAX_ARTIFACT_COMPRESSED_BYTES = 2_000_000
_MAX_ARTIFACT_MEMBERS = 16
_MAX_ARTIFACT_UNCOMPRESSED_BYTES = 2_000_000
_MAX_REQUEST_BYTES = 1_000_000


def verification_attempt_idempotency_key(
    session_id: str,
    capability: str,
    reasoning_effort: str,
    receipt: Mapping[str, object],
) -> str:
    payload = {
        "session_id": session_id,
        "capability": capability,
        "reasoning_effort": reasoning_effort,
        "receipt": dict(receipt),
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


_UNSUPPORTED_CODEX_SCHEMA_KEYWORDS = frozenset(
    {
        "allOf",
        "oneOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
    }
)


def validate_codex_output_schema(schema: Mapping[str, object]) -> None:
    """Fail before launch when a receipt schema exceeds Codex's response subset."""

    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ValueError(f"invalid output schema: {exc.message}") from exc

    if schema.get("type") != "object":
        raise ValueError("Codex output schema root must be an object")

    def walk(node: object, pointer: str = "") -> None:
        if isinstance(node, Mapping):
            for keyword in _UNSUPPORTED_CODEX_SCHEMA_KEYWORDS.intersection(node):
                location = f"{pointer}/{keyword}" or f"/{keyword}"
                raise ValueError(
                    f"unsupported output-schema keyword at {location}: {keyword}"
                )
            if node.get("type") == "object" or "properties" in node:
                properties = node.get("properties")
                required = node.get("required")
                if not isinstance(properties, Mapping):
                    raise ValueError(f"Codex object schema at {pointer or '/'} lacks properties")
                if not isinstance(required, list) or set(required) != set(properties):
                    raise ValueError(
                        f"Codex object schema at {pointer or '/'} must require every property"
                    )
                if node.get("additionalProperties") is not False:
                    raise ValueError(
                        f"Codex object schema at {pointer or '/'} must set "
                        "additionalProperties=false"
                    )
            for key, value in node.items():
                walk(value, f"{pointer}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{pointer}/{index}")

    walk(schema)


def validate_verification_closer_receipt(
    receipt: Mapping[str, object], schema: Mapping[str, object]
) -> None:
    """Apply provider-safe structural validation plus local semantic invariants."""

    jsonschema.validate(receipt, schema)
    review_events = receipt.get("review_events")
    human_exception = receipt.get("human_exception")
    if receipt.get("verdict") == "needs_human" and (
        not isinstance(human_exception, Mapping)
        or set(human_exception) != HUMAN_EXCEPTION_PACKET_FIELDS
        or not valid_human_exception_packet(human_exception)
    ):
        raise jsonschema.ValidationError(
            "a needs_human receipt requires one complete canonical Human Exception packet"
        )
    if receipt.get("verdict") != "needs_human" and human_exception is not None:
        raise jsonschema.ValidationError(
            "only a needs_human receipt may carry a Human Exception packet"
        )
    if receipt.get("verdict") == "delivered" and (
        not isinstance(review_events, list) or len(review_events) < 2
    ):
        raise jsonschema.ValidationError(
            "a delivered receipt requires at least two review events"
        )
    if not isinstance(review_events, list):
        return
    for index, event in enumerate(review_events):
        if not isinstance(event, Mapping):
            continue
        if event.get("kind") == "repair" and not (
            isinstance(event.get("finding_id"), str) and event["finding_id"]
        ):
            raise jsonschema.ValidationError(
                f"repair review event {index} requires finding_id"
            )


class GhCliVerificationSource:
    """Read request artifacts and live truth with the host's authenticated gh CLI."""

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner if runner is not None else cast(ProcessRunner, subprocess.run)

    def _json(self, endpoint: str) -> object:
        result = self.runner(
            ["gh", "api", endpoint], capture_output=True, text=True, check=False, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(f"gh read failed for {endpoint}")
        return json.loads(result.stdout)

    def _artifact_bytes(self, endpoint: str, artifact_id: int) -> bytes:
        if self.runner is not subprocess.run:
            result = self.runner(
                ["gh", "api", endpoint],
                capture_output=True,
                text=False,
                check=False,
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(f"failed to download verification artifact {artifact_id}")
            if not isinstance(result.stdout, bytes):
                raise RuntimeError(f"verification artifact {artifact_id} was not binary")
            if len(result.stdout) > _MAX_ARTIFACT_COMPRESSED_BYTES:
                raise ValueError("verification artifact exceeds compressed size limit")
            return result.stdout

        timed_out = threading.Event()
        with tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                ["gh", "api", endpoint], stdout=subprocess.PIPE, stderr=stderr
            )
            assert process.stdout is not None

            def expire() -> None:
                timed_out.set()
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

            timer = threading.Timer(60, expire)
            timer.start()
            try:
                payload = process.stdout.read(_MAX_ARTIFACT_COMPRESSED_BYTES + 1)
                if len(payload) > _MAX_ARTIFACT_COMPRESSED_BYTES:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise ValueError("verification artifact exceeds compressed size limit")
                returncode = process.wait()
            finally:
                timer.cancel()
            if timed_out.is_set():
                raise RuntimeError(f"verification artifact {artifact_id} download timed out")
            if returncode != 0:
                raise RuntimeError(f"failed to download verification artifact {artifact_id}")
            return payload

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
            compressed_size = artifact.get("size_in_bytes")
            if (
                not isinstance(compressed_size, int)
                or isinstance(compressed_size, bool)
                or compressed_size < 0
            ):
                raise ValueError("verification artifact size metadata is malformed")
            if compressed_size > _MAX_ARTIFACT_COMPRESSED_BYTES:
                raise ValueError("verification artifact exceeds compressed size limit")
            payload = self._artifact_bytes(
                f"repos/{repository}/actions/artifacts/{artifact_id}/zip", artifact_id
            )
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = archive.infolist()
                if len(members) > _MAX_ARTIFACT_MEMBERS:
                    raise ValueError("verification artifact contains too many members")
                if sum(info.file_size for info in members) > _MAX_ARTIFACT_UNCOMPRESSED_BYTES:
                    raise ValueError("verification artifact exceeds uncompressed size limit")
                candidates = [
                    info
                    for info in members
                    if info.filename == "request.json" or info.filename.endswith("/request.json")
                ]
                if len(candidates) != 1:
                    raise ValueError("verification artifact must contain exactly one request.json")
                info = candidates[0]
                if info.file_size > _MAX_REQUEST_BYTES:
                    raise ValueError("verification request artifact exceeds size limit")
                request = json.loads(archive.read(info))
            if not isinstance(request, dict):
                raise ValueError("verification request artifact is not an object")
            if request.get("repository") != repository:
                raise ValueError("verification artifact repository mismatch")
            provenance = request.get("artifact_provenance")
            workflow_run = artifact.get("workflow_run")
            if not isinstance(provenance, Mapping) or not isinstance(
                workflow_run, Mapping
            ):
                raise ValueError("verification artifact workflow-run mismatch")
            if (
                provenance.get("workflow_run_id") != workflow_run.get("id")
                or provenance.get("repository_id") != workflow_run.get("repository_id")
                or workflow_run.get("head_repository_id")
                != workflow_run.get("repository_id")
            ):
                raise ValueError("verification artifact workflow-run mismatch")
            if provenance.get("artifact_name") != name:
                raise ValueError("verification artifact identity mismatch")
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

    def __init__(self, config_path: Path, runner: ProcessRunner | None = None) -> None:
        self.config_path = config_path
        self.runner = runner if runner is not None else cast(ProcessRunner, subprocess.run)

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


class CodexExecFailure(RuntimeError):
    def __init__(self, receipt: Mapping[str, object]) -> None:
        self.receipt = dict(receipt)
        super().__init__(
            f"codex exec failed closed (exit={receipt.get('returncode')}): "
            f"{receipt.get('stderr') or receipt.get('terminal_error') or 'no stderr'}"
        )


_RATE_LIMIT_CODES = {
    "credits_exhausted",
    "insufficient_credit",
    "insufficient_quota",
    "quota_exceeded",
    "rate_limit",
    "rate_limit_exceeded",
    "too_many_requests",
    "usage_limit",
    "usage_limit_reached",
}


def _is_rate_limit_exec_failure(detail: str) -> bool:
    """Classify raw process failure once, before it becomes a trusted receipt."""

    def structured_signal(value: object, key: str | None = None) -> bool:
        if isinstance(value, Mapping):
            return any(structured_signal(child, str(child_key)) for child_key, child in value.items())
        if isinstance(value, list):
            return any(structured_signal(child, key) for child in value)
        if key in {"status", "status_code", "http_status"} and value == 429:
            return True
        if key in {"code", "error_code", "reason", "type"} and isinstance(value, str):
            return value.strip().lower().replace("-", "_").replace(" ", "_") in _RATE_LIMIT_CODES
        return False

    for line in detail.splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if structured_signal(parsed):
            return True

    lowered = detail.lower()
    # Raw provider stderr is not trusted as a receipt field. Negated clauses
    # are removed before matching so "not a rate limit" cannot mint the
    # structured failure classification consumed by the ledger.
    evidence = re.sub(
        r"\b(?:no|not|never|without)\b[^.;\n]{0,80}"
        r"\b(?:rate[ _-]?limit|quota|credits?|usage[ _-]?limit)\b",
        "",
        lowered,
    )
    return "http 429" in evidence or any(
        token in evidence
        for token in (
            "rate limit exceeded",
            "rate_limit_exceeded",
            "credit exhausted",
            "credits exhausted",
            "insufficient credit",
            "insufficient_quota",
            "quota exceeded",
            "quota_exceeded",
            "too many requests",
            "usage limit reached",
            "usage_limit_reached",
        )
    )


class CodexExecLauncher:
    """Explicit least-privilege non-interactive verification coordinator."""

    def __init__(
        self,
        worktree: Path,
        receipt_schema: Path,
        context_path: Path,
        adapter_path: Path | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self.worktree = worktree
        self.receipt_schema = receipt_schema
        self.context_path = context_path
        self.runner = runner if runner is not None else cast(ProcessRunner, subprocess.run)
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
        try:
            schema = json.loads(self.receipt_schema.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("verification closer receipt schema is unavailable") from exc
        if not isinstance(schema, Mapping):
            raise ValueError("verification closer receipt schema must be an object")
        validate_codex_output_schema(schema)

        # This generic launcher writes only non-secret request identity into its
        # isolated worktree. Host service configuration stays outside Git.
        self.context_path.write_text(
            json.dumps(context_pack, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "CODEX_API_KEY"}}
        stop_heartbeat = threading.Event()
        stdout_complete = threading.Event()
        authority_lost = threading.Event()
        heartbeat_failures: list[Exception] = []
        authority_loss_outcome = "heartbeat_authority_lost"
        heartbeat_thread: threading.Thread | None = None
        parent_watchdog_thread: threading.Thread | None = None
        stderr_thread: threading.Thread | None = None
        stderr_chunks: list[str] = []
        process: subprocess.Popen[str] | None = None
        process_group_id: int | None = None
        process_lock = threading.Lock()
        lines: Iterable[str | bytes]

        def signal_process_group(sig: int) -> bool:
            if process_group_id is None:
                return False
            try:
                os.killpg(process_group_id, sig)
            except ProcessLookupError:
                return False
            return True

        def process_group_is_alive() -> bool:
            if process_group_id is None:
                return False
            try:
                os.killpg(process_group_id, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                # The group still exists. This should not occur for our own
                # child, but fail closed instead of assuming it is gone.
                return True
            return True

        def terminate_and_reap_child() -> None:
            nonlocal process_group_id
            with process_lock:
                if process is None:
                    return
                if process_group_id is not None:
                    signal_process_group(signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        signal_process_group(signal.SIGKILL)
                        process.wait(timeout=5)
                    else:
                        # The direct child may exit while a descendant keeps
                        # the inherited stdout pipe and execution authority.
                        # The private process group lets us remove that
                        # residual without signalling unrelated processes.
                        if process_group_is_alive():
                            signal_process_group(signal.SIGKILL)
                    process_group_id = None
                    return
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)

        def record_authority_loss(
            exc: Exception, *, outcome: str = "heartbeat_authority_lost"
        ) -> None:
            nonlocal authority_loss_outcome
            if not authority_lost.is_set():
                heartbeat_failures.append(exc)
                authority_loss_outcome = outcome
                authority_lost.set()
            # Cleanup must progress in the authority-losing thread.  The
            # foreground reader may still be blocked in stdout until the child
            # exits and closes its pipe, so deferring wait/kill until after the
            # event loop would leave the old coordinator alive indefinitely.
            terminate_and_reap_child()

        if self.runner is subprocess.run:
            process = subprocess.Popen(
                self.command(resume_session_id), cwd=self.worktree, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
            )
            process_group_id = getattr(process, "pid", None)
            assert process.stdout is not None
            lines = process.stdout
            stderr = process.stderr
            assert stderr is not None

            def drain_stderr() -> None:
                while chunk := stderr.read(4096):
                    stderr_chunks.append(chunk)
                    if sum(map(len, stderr_chunks)) > 16_384:
                        stderr_chunks[:] = ["".join(stderr_chunks)[-16_384:]]

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()

            def watch_parent_liveness() -> None:
                while not stop_heartbeat.wait(0.25):
                    if process is None or process.poll() is None:
                        continue
                    # A normal parent may exit just before the reader drains
                    # its final buffered events and observes EOF. Only treat
                    # the exit as authority loss when stdout remains open
                    # beyond a bounded drain grace, which indicates an
                    # inherited pipe held by a surviving descendant.
                    if stdout_complete.wait(5):
                        return
                    if not stop_heartbeat.is_set():
                        record_authority_loss(
                            RuntimeError(
                                "coordinator parent exited while stdout remained open"
                            ),
                            outcome="parent_exit_authority_lost",
                        )
                    return

            parent_watchdog_thread = threading.Thread(
                target=watch_parent_liveness, daemon=True
            )
            parent_watchdog_thread.start()
            if on_heartbeat:
                def pulse() -> None:
                    while not stop_heartbeat.wait(30):
                        try:
                            on_heartbeat()
                        except Exception as exc:
                            record_authority_loss(exc)
                            return
                heartbeat_thread = threading.Thread(target=pulse, daemon=True)
                heartbeat_thread.start()
        else:
            result = self.runner(
                self.command(resume_session_id), cwd=self.worktree, env=env,
                capture_output=True, text=True, check=False,
            )
            lines = result.stdout.splitlines()
            stderr_chunks = [str(getattr(result, "stderr", "") or "")[-16_384:]]
        thread_id: str | None = resume_session_id
        terminal: dict[str, object] | None = None
        terminal_error: str | None = None
        for line in lines:
            if authority_lost.is_set():
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") in {"turn.failed", "error"}:
                terminal_error = json.dumps(event, sort_keys=True)
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
                if on_thread_started:
                    try:
                        on_thread_started(event["thread_id"])
                    except Exception as exc:
                        record_authority_loss(
                            exc, outcome="thread_start_authority_lost"
                        )
                        break
            if on_heartbeat:
                try:
                    on_heartbeat()
                except Exception as exc:
                    record_authority_loss(exc)
                    break
            if authority_lost.is_set():
                break
            if event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, Mapping) and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str):
                        try:
                            candidate = json.loads(text)
                            validate_verification_closer_receipt(candidate, schema)
                        except (json.JSONDecodeError, jsonschema.ValidationError):
                            continue
                        terminal = candidate
        stdout_complete.set()
        if self.runner is subprocess.run:
            assert process is not None
            if authority_lost.is_set():
                stop_heartbeat.set()
                terminate_and_reap_child()
            else:
                process.wait()
                # A clean direct-parent exit is not sufficient to release
                # coordinator authority: descendants can detach their stdio
                # yet remain in the private process group. Remove any such
                # residual group before a valid terminal receipt may return.
                if process_group_is_alive():
                    terminate_and_reap_child()
                else:
                    process_group_id = None
            if stderr_thread:
                stderr_thread.join(timeout=1)
            returncode = process.returncode
            stop_heartbeat.set()
            if heartbeat_thread:
                heartbeat_thread.join(timeout=1)
            if parent_watchdog_thread:
                parent_watchdog_thread.join(timeout=1)
        else:
            returncode = result.returncode
        if authority_lost.is_set():
            failure = heartbeat_failures[0] if heartbeat_failures else RuntimeError(
                "unknown heartbeat failure"
            )
            raise CodexExecFailure(
                {
                    "outcome": authority_loss_outcome,
                    "failure_class": "authority_loss",
                    "returncode": returncode,
                    "stderr": authority_loss_outcome.replace("_", " "),
                    "terminal_error": f"{type(failure).__name__}: {failure}",
                    "session_id": thread_id,
                }
            )
        if returncode != 0 or terminal_error is not None:
            detail = "".join(stderr_chunks).strip() or terminal_error or "no stderr"
            failure_class = (
                "rate_limit" if _is_rate_limit_exec_failure(detail) else "execution"
            )
            raise CodexExecFailure(
                {
                    "outcome": "codex_exec_failed",
                    "failure_class": failure_class,
                    "returncode": returncode,
                    "stderr": detail[-16_384:],
                    "terminal_error": terminal_error,
                    "session_id": thread_id,
                }
            )
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
    *,
    expected_head_sha: str | None = None,
) -> str | None:
    if not isinstance(pr.get("number"), int) or isinstance(pr.get("number"), bool):
        return "malformed_pr"
    if pr.get("state") != "open" or pr.get("merged_at") is not None:
        return "closed_unmerged_or_merged"
    if pr.get("draft") is True:
        return "draft"
    if _nested(pr, "head", "sha") != (expected_head_sha or run.head_sha):
        return "stale_head"
    issue_contract = resolve_issue_contract(pr.get("body"))
    linked_issue = run.request.get("linked_issue")
    supporting_issues = run.request.get("supporting_issues")
    if (
        issue_contract is None
        or issue_contract[0] != linked_issue
        or list(issue_contract[1]) != supporting_issues
    ):
        return "governing_issue_mismatch"
    return _checks_rejection(checks)


def delivered_live_truth_rejection(
    run: VerificationRun,
    pr: Mapping[str, object],
    checks: Sequence[Mapping[str, object]],
    *,
    expected_head_sha: str,
) -> str | None:
    """Validate exact post-merge truth for a coordinator-delivered receipt."""

    number = pr.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        return "malformed_pr"
    if number != run.pr_number:
        return "pr_mismatch"
    if _nested(pr, "base", "repo", "full_name") != run.repository:
        return "repository_mismatch"
    if _nested(pr, "head", "sha") != expected_head_sha:
        return "stale_head"
    issue_contract = resolve_issue_contract(pr.get("body"))
    if (
        issue_contract is None
        or issue_contract[0] != run.request.get("linked_issue")
        or list(issue_contract[1]) != run.request.get("supporting_issues")
    ):
        return "governing_issue_mismatch"
    if (
        pr.get("state") != "closed"
        or pr.get("merged") is not True
        or not isinstance(pr.get("merged_at"), str)
        or not pr["merged_at"]
    ):
        return "closed_unmerged"
    merge_commit_sha = pr.get("merge_commit_sha")
    if not isinstance(merge_commit_sha, str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}", merge_commit_sha
    ):
        return "missing_merge_evidence"
    return _checks_rejection(checks)


def _checks_rejection(checks: Sequence[Mapping[str, object]]) -> str | None:
    if not checks:
        return "missing_checks"
    required_checks = {"Unit tests (not pg)"}
    latest: dict[str, tuple[tuple[int, str, int], Mapping[str, object]]] = {}
    for index, check in enumerate(checks):
        name = check.get("name")
        key = name if isinstance(name, str) and name else f"__unnamed_{index}"
        check_id = check.get("id")
        rank = (
            check_id if isinstance(check_id, int) and not isinstance(check_id, bool) else -1,
            str(check.get("started_at") or check.get("completed_at") or ""),
            index,
        )
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, check)
    if not required_checks.issubset(latest):
        return "missing_checks"
    for required in required_checks:
        check = latest[required][1]
        if check.get("status") != "completed" or check.get("conclusion") != "success":
            return "checks_not_green"
    for _, check in latest.values():
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
        "requested_head_sha": run.requested_head_sha,
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
        return receipt.get("failure_class") == "rate_limit" or (
            receipt.get("verdict") == "retry"
            and isinstance(receipt.get("retry_after"), str)
            and bool(str(receipt["retry_after"]).strip())
        )

    @staticmethod
    def _retry_hint(receipt: Mapping[str, object]) -> object:
        encoded = json.dumps(receipt, sort_keys=True).lower()
        match = re.search(
            r"(?:retry after|try again in)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*"
            r"(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b",
            encoded,
        )
        if not match:
            return receipt.get("retry_after")
        unit = match.group(2)[0]
        return f"{match.group(1)}{unit}"

    def _terminal_event_application_failure(
        self,
        run: VerificationRun,
        lease_id: str,
        exc: ValueError,
    ) -> VerificationRun:
        receipt = {
            "outcome": "receipt_event_application_failed",
            "error_type": type(exc).__name__,
            "head_sha": run.head_sha,
        }
        try:
            return self.ledger.terminal(
                run.run_id,
                "failed",
                receipt,
                reason="receipt_event_application_failed",
                holder=self.holder,
                lease_id=lease_id,
            )
        except ValueError:
            # Event application and terminal fencing share the exact lease.
            # If ownership changed between them, preserve the newer live truth
            # rather than mutating under an expired or replacement token.
            current = self.ledger.get(run.run_id)
            if current is not None:
                return current
            raise

    @staticmethod
    def _pending_delivered_receipt(
        run: VerificationRun,
    ) -> Mapping[str, object] | None:
        terminal = run.terminal_receipt
        if run.status not in {"backoff", "claimed", "running"} or not isinstance(
            terminal, Mapping
        ):
            return None
        pending = terminal.get("pending_terminal_receipt")
        if not isinstance(pending, Mapping) or pending.get("verdict") != "delivered":
            return None
        return pending

    def _replay_pending_delivered(
        self, run: VerificationRun, receipt: Mapping[str, object]
    ) -> VerificationRun:
        """Revalidate one persisted delivered receipt through merged live truth."""
        auth = self.auth.check()
        if not auth.ok:
            try:
                return self.ledger.defer_unclaimed(
                    run.run_id,
                    {
                        "outcome": "blocked",
                        "reason": auth.reason,
                        "auth_mode": auth.auth_mode,
                        "pending_terminal_receipt": dict(receipt),
                    },
                    _retry_at(),
                )
            except ValueError:
                current = self.ledger.get(run.run_id)
                assert current is not None
                return current
        try:
            claimed = self.ledger.claim(run.run_id, self.holder)
        except (VerificationSubscriptionBusy, VerificationBackoffPending):
            current = self.ledger.get(run.run_id)
            assert current is not None
            return current
        lease_id = claimed.lease_id or ""
        receipt_head = receipt.get("head_sha")
        if not isinstance(receipt_head, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}", receipt_head
        ):
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                dict(receipt),
                reason="receipt_head_mismatch",
                holder=self.holder,
                lease_id=lease_id,
            )
        try:
            live_pr = self.truth.pull_request(claimed.repository, claimed.pr_number)
            live_checks = self.truth.checks(claimed.repository, receipt_head)
            rejection = delivered_live_truth_rejection(
                claimed,
                live_pr,
                live_checks,
                expected_head_sha=receipt_head,
            )
        except Exception as exc:
            return self.ledger.backoff(
                claimed.run_id,
                {
                    "outcome": "blocked",
                    "reason": "postlaunch_live_truth_unavailable",
                    "error_type": type(exc).__name__,
                    "pending_terminal_receipt": dict(receipt),
                },
                _retry_at(),
                holder=self.holder,
                lease_id=lease_id,
            )
        if rejection:
            if rejection in {"missing_checks", "checks_not_green"}:
                return self.ledger.backoff(
                    claimed.run_id,
                    {
                        "outcome": "deferred",
                        "reason": rejection,
                        "pending_terminal_receipt": dict(receipt),
                    },
                    _retry_at(),
                    holder=self.holder,
                    lease_id=lease_id,
                )
            reason = (
                "receipt_head_mismatch"
                if rejection == "stale_head"
                else f"receipt_live_truth_{rejection}"
            )
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                dict(receipt),
                reason=reason,
                holder=self.holder,
                lease_id=lease_id,
            )
        review_events = receipt.get("review_events")
        events = review_events if isinstance(review_events, list) else []
        loop = VerificationAgentLoop(
            self.ledger,
            claimed.run_id,
            holder=self.holder,
            lease_id=lease_id,
        )
        if events:
            try:
                loop.apply_events(events, context=context_pack(claimed, live_pr))
            except ValueError as exc:
                return self._terminal_event_application_failure(
                    claimed, lease_id, exc
                )
        try:
            return self.ledger.terminal(
                claimed.run_id,
                "completed",
                dict(receipt),
                holder=self.holder,
                lease_id=lease_id,
            )
        except ValueError as exc:
            if "two fresh clean reviews" not in str(exc):
                raise
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                dict(receipt),
                reason="closure_gate_not_proven",
                holder=self.holder,
                lease_id=lease_id,
            )

    def consume(self, request: Mapping[str, object]) -> VerificationRun:
        run = self.ledger.ingest(request)
        if run.status in {"completed", "failed", "needs_human", "superseded"}:
            return run
        if run.status in {"claimed", "running"} and self._lease_is_live(run):
            # An active delivery is already owned. Restart recovery is an
            # explicit operation so replayed artifacts cannot duplicate it.
            return run
        pending_delivered = self._pending_delivered_receipt(run)
        if pending_delivered is not None:
            return self._replay_pending_delivered(run, pending_delivered)
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
        return self._launch_after_live_fence(claimed)

    def _launch_after_live_fence(self, claimed: VerificationRun) -> VerificationRun:
        """Re-read authority after auth and claim, immediately before launch."""
        try:
            pr = self.truth.pull_request(claimed.repository, claimed.pr_number)
            checks = self.truth.checks(claimed.repository, claimed.head_sha)
            rejection = live_truth_rejection(claimed, pr, checks)
        except Exception as exc:
            return self.ledger.backoff(
                claimed.run_id,
                {
                    "outcome": "blocked",
                    "reason": "prelaunch_live_truth_unavailable",
                    "error_type": type(exc).__name__,
                },
                _retry_at(),
                holder=self.holder,
                lease_id=claimed.lease_id or "",
            )
        if rejection:
            receipt = {"outcome": "launch_rejected", "reason": rejection}
            if rejection in {"missing_checks", "checks_not_green"}:
                return self.ledger.backoff(
                    claimed.run_id,
                    receipt,
                    _retry_at(),
                    holder=self.holder,
                    lease_id=claimed.lease_id or "",
                )
            return self.ledger.terminal(
                claimed.run_id,
                "superseded",
                receipt,
                reason=rejection,
                holder=self.holder,
                lease_id=claimed.lease_id or "",
            )
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

        try:
            session_id, receipt = self.launcher.launch(
                pack,
                resume_session_id=claimed.coordinator_session_id,
                on_thread_started=started,
                on_heartbeat=heartbeat,
            )
        except CodexExecFailure as exc:
            failed_session = exc.receipt.get("session_id")
            if str(exc.receipt.get("outcome", "")).endswith("_authority_lost"):
                retry_after = _retry_at()
                failure_receipt = {
                    **exc.receipt,
                    "api_fallback": False,
                    "retry_after": retry_after,
                }
                try:
                    return self.ledger.backoff(
                        claimed.run_id,
                        failure_receipt,
                        retry_after=retry_after,
                        holder=self.holder,
                        lease_id=lease_id,
                    )
                except ValueError:
                    try:
                        return self.ledger.defer_unclaimed(
                            claimed.run_id, failure_receipt, retry_after
                        )
                    except ValueError:
                        current = self.ledger.get(claimed.run_id)
                        if current is not None:
                            return current
                        raise
            rate_limited = self._rate_limited(exc.receipt)
            if isinstance(failed_session, str) and failed_session:
                self.ledger.record_attempt(
                    claimed.run_id,
                    "verification",
                    failed_session,
                    self.launcher.config.model,
                    self.launcher.config.reasoning_effort,
                    pack,
                    "rate_limited" if rate_limited else "launch_failed",
                    exc.receipt,
                    holder=self.holder,
                    lease_id=lease_id,
                )
            if rate_limited:
                retry_after = _retry_at(self._retry_hint(exc.receipt))
                return self.ledger.backoff(
                    claimed.run_id,
                    {
                        "outcome": "rate_limited",
                        "api_fallback": False,
                        "retry_after": retry_after,
                        "failure_receipt": exc.receipt,
                    },
                    retry_after=retry_after,
                    holder=self.holder,
                    lease_id=lease_id,
                )
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                exc.receipt,
                reason="codex_exec_failed",
                holder=self.holder,
                lease_id=lease_id,
            )
        except (RuntimeError, ValueError) as exc:
            # A zero-exit launcher can still fail its terminal contract (for
            # example, no thread identity or no schema-valid final receipt).
            # Once claim/start has happened that failure needs the same exact
            # lease-fenced outcome as every other post-claim technical seam;
            # otherwise a malformed coordinator response strands a live run.
            retry_after = _retry_at()
            failure_receipt = {
                "outcome": "launcher_contract_failed",
                "reason": "invalid_coordinator_output",
                "error_type": type(exc).__name__,
                "api_fallback": False,
                "retry_after": retry_after,
            }
            try:
                return self.ledger.backoff(
                    claimed.run_id,
                    failure_receipt,
                    retry_after=retry_after,
                    holder=self.holder,
                    lease_id=lease_id,
                )
            except ValueError:
                # The lease may have expired or changed while the launcher
                # failed. Never mutate without the exact token; recovery owns
                # expired runs and a newer holder owns a replacement lease.
                current = self.ledger.get(claimed.run_id)
                if current is not None:
                    return current
                raise
        current = self.ledger.get(claimed.run_id)
        if current is not None and current.status == "claimed":
            started(session_id)
        config = self.launcher.config
        structured_rate_limit = (
            receipt.get("verdict") == "retry" and self._rate_limited(receipt)
        )
        self.ledger.record_attempt(
            claimed.run_id,
            "verification",
            session_id,
            config.model,
            config.reasoning_effort,
            pack,
            "rate_limited" if structured_rate_limit else "launched",
            receipt,
            holder=self.holder,
            lease_id=lease_id,
            idempotency_key=verification_attempt_idempotency_key(
                session_id,
                config.model,
                config.reasoning_effort,
                receipt,
            ),
        )
        if structured_rate_limit:
            return self.ledger.backoff(
                claimed.run_id,
                {"outcome": "rate_limited", "api_fallback": False, "receipt": dict(receipt)},
                retry_after=_retry_at(receipt.get("retry_after")),
                holder=self.holder,
                lease_id=lease_id,
            )
        receipt_head = receipt.get("head_sha")
        if not isinstance(receipt_head, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}", receipt_head
        ):
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                dict(receipt),
                reason="receipt_head_mismatch",
                holder=self.holder,
                lease_id=lease_id,
            )
        verdict = receipt.get("verdict")
        if verdict == "retry":
            if receipt_head != claimed.head_sha:
                return self.ledger.terminal(
                    claimed.run_id,
                    "failed",
                    dict(receipt),
                    reason="receipt_head_mismatch",
                    holder=self.holder,
                    lease_id=lease_id,
                )
            return self.ledger.backoff(
                claimed.run_id, dict(receipt), _retry_at(receipt.get("retry_after")),
                holder=self.holder, lease_id=lease_id,
            )
        review_events = receipt.get("review_events")
        events = review_events if isinstance(review_events, list) else []
        changed_head = receipt_head != claimed.head_sha
        if changed_head and not any(
            isinstance(event, Mapping) and event.get("kind") == "repair"
            for event in events
        ):
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                dict(receipt),
                reason="receipt_head_mismatch",
                holder=self.holder,
                lease_id=lease_id,
            )

        # Receipt acceptance is tied to a fresh authenticated GitHub read. A
        # repair may advance only to the exact current PR head; arbitrary or
        # stale receipt heads never reach the review ledger.
        try:
            live_pr = self.truth.pull_request(claimed.repository, claimed.pr_number)
            live_checks = self.truth.checks(claimed.repository, receipt_head)
            rejection = (
                delivered_live_truth_rejection(
                    claimed,
                    live_pr,
                    live_checks,
                    expected_head_sha=receipt_head,
                )
                if verdict == "delivered"
                else live_truth_rejection(
                    claimed,
                    live_pr,
                    live_checks,
                    expected_head_sha=receipt_head,
                )
            )
        except Exception as exc:
            return self.ledger.backoff(
                claimed.run_id,
                {
                    "outcome": "blocked",
                    "reason": "postlaunch_live_truth_unavailable",
                    "error_type": type(exc).__name__,
                    "pending_terminal_receipt": dict(receipt),
                },
                _retry_at(),
                holder=self.holder,
                lease_id=lease_id,
            )
        transient = rejection in {"missing_checks", "checks_not_green"}
        if changed_head and (rejection is None or transient):
            live_pr_number = live_pr.get("number")
            assert isinstance(live_pr_number, int) and not isinstance(live_pr_number, bool)
            claimed = self.ledger.rebind_head(
                claimed.run_id,
                receipt_head,
                expected_head_sha=claimed.head_sha,
                observed_repository=claimed.repository,
                observed_pr_number=live_pr_number,
                observed_head_sha=str(_nested(live_pr, "head", "sha") or ""),
                holder=self.holder,
                lease_id=lease_id,
            )
        if rejection:
            if transient:
                repair_events = [
                    event
                    for event in events
                    if isinstance(event, Mapping) and event.get("kind") == "repair"
                ]
                if len(repair_events) != len(events):
                    return self.ledger.terminal(
                        claimed.run_id,
                        "failed",
                        dict(receipt),
                        reason="reviews_before_checks_green",
                        holder=self.holder,
                        lease_id=lease_id,
                    )
                if repair_events:
                    pack = context_pack(claimed, live_pr)
                    try:
                        VerificationAgentLoop(
                            self.ledger,
                            claimed.run_id,
                            holder=self.holder,
                            lease_id=lease_id,
                        ).apply_events(repair_events, context=pack)
                    except ValueError as exc:
                        return self._terminal_event_application_failure(
                            claimed, lease_id, exc
                        )
                return self.ledger.backoff(
                    claimed.run_id,
                    {
                        "outcome": "deferred",
                        "reason": rejection,
                        "head_sha": claimed.head_sha,
                    },
                    _retry_at(),
                    holder=self.holder,
                    lease_id=lease_id,
                )
            reason = (
                "receipt_head_mismatch"
                if rejection == "stale_head"
                else f"receipt_live_truth_{rejection}"
            )
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                dict(receipt),
                reason=reason,
                holder=self.holder,
                lease_id=lease_id,
            )

        pack = context_pack(claimed, live_pr)
        loop = VerificationAgentLoop(
            self.ledger,
            claimed.run_id,
            holder=self.holder,
            lease_id=lease_id,
        )
        if events:
            try:
                loop.apply_events(events, context=pack)
            except ValueError as exc:
                return self._terminal_event_application_failure(
                    claimed, lease_id, exc
                )
        if verdict == "needs_human":
            human_exception = receipt.get("human_exception")
            if (
                not isinstance(human_exception, Mapping)
                or set(human_exception) != HUMAN_EXCEPTION_PACKET_FIELDS
                or not valid_human_exception_packet(human_exception)
            ):
                return self.ledger.terminal(
                    claimed.run_id,
                    "failed",
                    dict(receipt),
                    reason="invalid_human_exception_packet",
                    holder=self.holder,
                    lease_id=lease_id,
                )
            assert isinstance(human_exception, Mapping)
            failure_class = str(human_exception["failure_class"])
            loop.stop(
                failure_class,
                {
                    **dict(human_exception),
                    "governing_issue": claimed.request.get("linked_issue"),
                    "head_sha": claimed.head_sha,
                    "receipt_ids": receipt.get("receipt_ids", []),
                    "summary": receipt.get("summary", ""),
                },
            )
            terminal = self.ledger.get(claimed.run_id)
            if terminal is None:
                raise RuntimeError("verification exception terminal state was not persisted")
            return terminal
        status = (
            {
                "delivered": "completed",
                "blocked": "failed",
            }.get(verdict)
            if isinstance(verdict, str)
            else None
        )
        if status is None:
            return self.ledger.terminal(
                claimed.run_id, "failed", dict(receipt), reason="invalid_verdict",
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
                claimed.run_id, "failed", dict(receipt), reason="closure_gate_not_proven",
                holder=self.holder, lease_id=lease_id,
            )

    def recover(self, run_id: str) -> VerificationRun:
        run = self.ledger.get(run_id)
        if run is None or run.status != "running" or not run.coordinator_session_id or not run.context_pack:
            raise ValueError("verification run is not resumable")
        if self._lease_is_live(run):
            return run
        pr = self.truth.pull_request(run.repository, run.pr_number)
        observed_head = _nested(pr, "head", "sha")
        if not isinstance(observed_head, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}", observed_head
        ):
            raise ValueError("verification run is no longer resumable: malformed_pr")
        if observed_head != run.head_sha:
            raise ValueError("verification run is no longer resumable: stale_head")
        checks = self.truth.checks(run.repository, run.head_sha)
        rejection = live_truth_rejection(
            run,
            pr,
            checks,
            expected_head_sha=run.head_sha,
        )
        if rejection:
            raise ValueError(f"verification run is no longer resumable: {rejection}")
        if not self.auth.check().ok:
            raise ValueError("verification auth preflight failed")
        claimed = self.ledger.claim(run.run_id, self.holder)
        return self._launch_after_live_fence(claimed)
