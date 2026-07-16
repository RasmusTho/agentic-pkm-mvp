"""Host-neutral consumer for verification dispatch requests.

GitHub and Codex are injected boundaries.  The consumer owns eligibility,
dedupe, auth preflight, context minimisation, and launch receipts; the launched
``verification_closer`` remains the only mutation/merge authority.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import io
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol, Sequence, cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import jsonschema

from app.dispatcher.verification_dispatch import (
    VerificationBackoffPending,
    VerificationDispatchLedger,
    VerificationRun,
    VerificationSubscriptionBusy,
    REPAIR_FAILURE_DOMAINS,
    _AuthenticatedVerificationRequest,
    _authenticated_verification_request,
    _live_observed_verification_request,
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

_COORDINATOR_REQUIRED_ENVIRONMENT = ("HOME", "PATH")
_COORDINATOR_OPTIONAL_ENVIRONMENT = (
    "LANG",
    "LANGUAGE",
    "LC_ADDRESS",
    "LC_ALL",
    "LC_COLLATE",
    "LC_CTYPE",
    "LC_IDENTIFICATION",
    "LC_MEASUREMENT",
    "LC_MESSAGES",
    "LC_MONETARY",
    "LC_NAME",
    "LC_NUMERIC",
    "LC_PAPER",
    "LC_TELEPHONE",
    "LC_TIME",
    "TEMP",
    "TMP",
    "TMPDIR",
)


def _coordinator_environment(base: Mapping[str, str]) -> dict[str, str]:
    """Return the non-secret runtime environment allowed into Codex children."""

    if any(not base.get(key) for key in _COORDINATOR_REQUIRED_ENVIRONMENT):
        raise RuntimeError("verification coordinator required environment unavailable")
    return {
        key: base[key]
        for key in (
            *_COORDINATOR_REQUIRED_ENVIRONMENT,
            *_COORDINATOR_OPTIONAL_ENVIRONMENT,
        )
        if base.get(key)
    }

CANONICAL_RECEIPT_SCHEMA_PATH = (
    Path(__file__).resolve().parent
    / "schemas/verification_closer_receipt.schema.json"
)
_VERIFICATION_SOURCE_PATH = ".github/workflows/ci.yml"
_VERIFICATION_ARTIFACT_NAME = re.compile(
    r"verification-dispatch-(?P<pr_number>[1-9][0-9]*)-(?P<head_sha>[0-9a-fA-F]{40})\Z"
)


class ReceiptContractError(ValueError):
    """Untrusted launcher output failed the canonical receipt contract."""


class WholeTreeContainment(Protocol):
    """One launch-scoped host boundary that can prove descendant cleanup."""

    def environment(self, base: Mapping[str, str]) -> dict[str, str]: ...

    def attach(self, root_pid: int) -> None: ...

    def cleanup(self) -> bool: ...


class TaggedProcessTreeCleanup:
    """Best-effort escape cleanup; deliberately never claims kernel proof."""

    _ENV_KEY = "PKM_VERIFICATION_PROCESS_TREE"

    def __init__(self) -> None:
        self.token = secrets.token_hex(32)
        self._known_pids: set[int] = set()
        self._root_pid: int | None = None
        self._stop = threading.Event()
        self._tracker: threading.Thread | None = None

    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        return {**base, self._ENV_KEY: self.token}

    @staticmethod
    def _children_of(parent_pid: int) -> set[int]:
        proc = Path("/proc")
        if proc.is_dir():
            children: set[int] = set()
            for entry in proc.iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    status = (entry / "status").read_text(encoding="utf-8")
                except (OSError, PermissionError):
                    continue
                match = re.search(r"(?m)^PPid:\s+(\d+)$", status)
                if match and int(match.group(1)) == parent_pid:
                    children.add(int(entry.name))
            return children
        if sys.platform == "darwin":
            try:
                libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
                list_children = libproc.proc_listchildpids
                list_children.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
                list_children.restype = ctypes.c_int
                buffer = (ctypes.c_int * 4096)()
                count = list_children(
                    parent_pid, buffer, ctypes.sizeof(buffer)
                )
            except (OSError, AttributeError):
                return set()
            count = max(0, count)
            return {int(buffer[index]) for index in range(count) if buffer[index] > 0}
        return set()

    def _sample_descendants(self) -> None:
        frontier = {self._root_pid} if self._root_pid is not None else set()
        frontier |= set(self._known_pids)
        observed: set[int] = set()
        while frontier:
            parent = frontier.pop()
            children = self._children_of(parent)
            new_children = children - observed
            observed |= new_children
            frontier |= new_children
        self._known_pids |= observed

    def attach(self, root_pid: int) -> None:
        self._root_pid = root_pid

        def track() -> None:
            while not self._stop.wait(0.01):
                self._sample_descendants()

        self._tracker = threading.Thread(target=track, daemon=True)
        self._tracker.start()

    def _tagged_pids(self) -> set[int]:
        marker = f"{self._ENV_KEY}={self.token}"
        proc = Path("/proc")
        if proc.is_dir():
            found: set[int] = set()
            for entry in proc.iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    environ = (entry / "environ").read_bytes()
                except (OSError, PermissionError):
                    continue
                if marker.encode() in environ.split(b"\0"):
                    found.add(int(entry.name))
            return found
        try:
            result = subprocess.run(
                ["ps", "-axeww", "-o", "pid=,command="],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        found = set()
        for line in result.stdout.splitlines():
            pid_text, _, command = line.strip().partition(" ")
            if marker in command and pid_text.isdigit():
                found.add(int(pid_text))
        return found

    def cleanup(self) -> bool:
        self._stop.set()
        if self._tracker:
            self._tracker.join(timeout=0.2)
        self._sample_descendants()
        own_pid = os.getpid()
        targets = (self._known_pids | self._tagged_pids()) - {own_pid}
        for pid in targets:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        def still_alive(pids: set[int]) -> set[int]:
            alive: set[int] = set()
            for pid in pids:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    pass
                alive.add(pid)
            return alive

        deadline = time.monotonic() + 0.5
        while targets and time.monotonic() < deadline:
            targets = still_alive(targets)
            if targets:
                time.sleep(0.01)
        for pid in targets:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 0.5
        while targets and time.monotonic() < deadline:
            targets = still_alive(targets)
            if targets:
                time.sleep(0.01)
        # An inherited marker lets us remove observed setsid escapes, but a
        # process can erase its environment. Only a stronger host adapter may
        # return True and authorize a terminal receipt.
        return False

_MAX_ARTIFACT_COMPRESSED_BYTES = 2_000_000
_MAX_ARTIFACT_MEMBERS = 16
_MAX_ARTIFACT_UNCOMPRESSED_BYTES = 2_000_000
_MAX_REQUEST_BYTES = 1_000_000
_VERIFICATION_REQUEST_WORKFLOW_NAME = "Verification Dispatch Request"
_VERIFICATION_REQUEST_WORKFLOW_PATH = (
    ".github/workflows/verification-dispatch-request.yml"
)


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
        "uniqueItems",
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
    receipt: Mapping[str, object],
    schema: Mapping[str, object],
    *,
    allow_legacy_unbound_repairs: bool = False,
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
        binding = (
            event.get("finding_id"),
            event.get("failure_domain"),
            event.get("mechanism_id"),
        )
        requires_binding = event.get("kind") == "repair" or (
            event.get("kind") == "review" and event.get("outcome") == "blocking"
        )
        if requires_binding and not allow_legacy_unbound_repairs and not all(
            isinstance(value, str) and bool(value) for value in binding
        ):
            raise jsonschema.ValidationError(
                f"review event {index} requires a stable finding, failure domain, "
                "and mechanism binding"
            )
        if event.get("kind") == "review" and event.get("outcome") == "clean" and any(
            value is not None for value in binding
        ):
            raise jsonschema.ValidationError(
                f"clean review event {index} cannot carry a failure binding"
            )


def _normalize_v1_review_event(event: Mapping[str, object]) -> dict[str, object]:
    """Normalize one policy-v1 review event before validation.

    Policy-v1 pending receipts predate the policy-v2 binding contract: the
    legacy schema allowed ``finding_id``/``failure_domain``/``mechanism_id``
    on every review event, and the legacy application ignored those fields
    on a clean review. Fill in missing binding keys as ``None`` so schema
    validation sees the key, and scrub a clean review's binding fields to
    ``None`` so a stale legacy value is never treated as authoritative
    failure-domain or mechanism data, nor carried into durable state.
    """

    normalized: dict[str, object] = {
        **dict(event),
        "failure_domain": event.get("failure_domain"),
        "mechanism_id": event.get("mechanism_id"),
    }
    if event.get("kind") == "review" and event.get("outcome") == "clean":
        normalized["finding_id"] = None
        normalized["failure_domain"] = None
        normalized["mechanism_id"] = None
    return normalized


def _v1_compatible_receipt_candidate(
    receipt: Mapping[str, object],
) -> dict[str, object]:
    """Project one receipt onto its policy-v1 compatible validation shape."""

    candidate = dict(receipt)
    events = candidate.get("review_events")
    if isinstance(events, list):
        candidate["review_events"] = [
            _normalize_v1_review_event(event) if isinstance(event, Mapping) else event
            for event in events
        ]
    return candidate


def load_and_validate_verification_closer_receipt(
    receipt: object,
    schema_path: Path,
    *,
    trusted_repository: str,
    trusted_evidence_urls: frozenset[str],
    repair_budget_policy: str | None = None,
) -> Mapping[str, object]:
    """Validate untrusted launcher output against the canonical receipt contract."""

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptContractError(
            "verification closer receipt schema is unavailable"
        ) from exc
    if not isinstance(schema, Mapping):
        raise ReceiptContractError(
            "verification closer receipt schema must be an object"
        )
    try:
        validate_codex_output_schema(schema)
    except (ValueError, jsonschema.SchemaError) as exc:
        raise ReceiptContractError("verification closer receipt schema is invalid") from exc
    if not isinstance(receipt, Mapping):
        raise ReceiptContractError("verification closer receipt must be an object")
    candidate = (
        _v1_compatible_receipt_candidate(receipt)
        if repair_budget_policy == "v1"
        else dict(receipt)
    )
    allow_legacy = repair_budget_policy == "v1"
    try:
        validate_verification_closer_receipt(
            candidate,
            schema,
            allow_legacy_unbound_repairs=allow_legacy,
        )
    except jsonschema.ValidationError as exc:
        raise ReceiptContractError("verification closer receipt is invalid") from exc
    sanitized = sanitize_verification_closer_receipt(
        candidate,
        trusted_repository=trusted_repository,
        trusted_evidence_urls=trusted_evidence_urls,
    )
    try:
        validate_verification_closer_receipt(
            sanitized,
            schema,
            allow_legacy_unbound_repairs=allow_legacy,
        )
    except jsonschema.ValidationError as exc:
        raise ReceiptContractError(
            "sanitized verification closer receipt is invalid"
        ) from exc
    return sanitized


class _InvalidVerificationArtifact(ValueError):
    """A single artifact candidate failed authenticated validation."""


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

    def _request_from_artifact(
        self, repository: str, artifact: Mapping[str, object]
    ) -> dict[str, object] | None:
        name, artifact_id = artifact.get("name"), artifact.get("id")
        artifact_identity = (
            _VERIFICATION_ARTIFACT_NAME.fullmatch(name)
            if isinstance(name, str)
            else None
        )
        if (
            artifact_identity is None
            or artifact.get("expired") is True
            or not isinstance(artifact_id, int)
            or isinstance(artifact_id, bool)
            or artifact_id <= 0
        ):
            return None
        try:
            compressed_size = artifact.get("size_in_bytes")
            if (
                not isinstance(compressed_size, int)
                or isinstance(compressed_size, bool)
                or compressed_size < 0
            ):
                raise _InvalidVerificationArtifact(
                    "verification artifact size metadata is malformed"
                )
            if compressed_size > _MAX_ARTIFACT_COMPRESSED_BYTES:
                raise _InvalidVerificationArtifact(
                    "verification artifact exceeds compressed size limit"
                )
            workflow_run = artifact.get("workflow_run")
            if not isinstance(workflow_run, Mapping):
                raise _InvalidVerificationArtifact(
                    "verification artifact workflow-run mismatch"
                )
            uploader_run_id = workflow_run.get("id")
            if (
                not isinstance(uploader_run_id, int)
                or isinstance(uploader_run_id, bool)
                or uploader_run_id <= 0
            ):
                raise _InvalidVerificationArtifact(
                    "verification artifact workflow-run mismatch"
                )
            uploader_run = self._json(
                f"repos/{repository}/actions/runs/{uploader_run_id}"
            )
            uploader_repository = (
                uploader_run.get("repository")
                if isinstance(uploader_run, Mapping)
                else None
            )
            uploader_head_repository = (
                uploader_run.get("head_repository")
                if isinstance(uploader_run, Mapping)
                else None
            )
            uploader_head_sha = (
                uploader_run.get("head_sha")
                if isinstance(uploader_run, Mapping)
                else None
            )
            uploader_attempt = (
                uploader_run.get("run_attempt")
                if isinstance(uploader_run, Mapping)
                else None
            )
            if (
                not isinstance(uploader_run, Mapping)
                or not isinstance(uploader_repository, Mapping)
                or not isinstance(uploader_head_repository, Mapping)
                or uploader_run.get("id") != uploader_run_id
                or uploader_run.get("name") != _VERIFICATION_REQUEST_WORKFLOW_NAME
                or uploader_run.get("path") != _VERIFICATION_REQUEST_WORKFLOW_PATH
                or uploader_run.get("event") != "workflow_run"
                or uploader_run.get("status") != "completed"
                or uploader_run.get("conclusion") != "success"
                or not isinstance(uploader_attempt, int)
                or isinstance(uploader_attempt, bool)
                or uploader_attempt <= 0
                or not isinstance(uploader_head_sha, str)
                or not re.fullmatch(r"[0-9a-fA-F]{40}", uploader_head_sha)
                or uploader_head_sha != workflow_run.get("head_sha")
                or uploader_repository.get("id") != workflow_run.get("repository_id")
                or uploader_repository.get("full_name") != repository
                or uploader_head_repository.get("id")
                != workflow_run.get("head_repository_id")
                or uploader_head_repository.get("full_name") != repository
            ):
                raise _InvalidVerificationArtifact(
                    "verification artifact uploader workflow identity mismatch"
                )
            try:
                payload = self._artifact_bytes(
                    f"repos/{repository}/actions/artifacts/{artifact_id}/zip",
                    artifact_id,
                )
            except ValueError as exc:
                raise _InvalidVerificationArtifact(str(exc)) from exc
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    members = archive.infolist()
                    if len(members) > _MAX_ARTIFACT_MEMBERS:
                        raise _InvalidVerificationArtifact(
                            "verification artifact contains too many members"
                        )
                    if (
                        sum(info.file_size for info in members)
                        > _MAX_ARTIFACT_UNCOMPRESSED_BYTES
                    ):
                        raise _InvalidVerificationArtifact(
                            "verification artifact exceeds uncompressed size limit"
                        )
                    candidates = [
                        info
                        for info in members
                        if info.filename == "request.json"
                        or info.filename.endswith("/request.json")
                    ]
                    if len(candidates) != 1:
                        raise _InvalidVerificationArtifact(
                            "verification artifact must contain exactly one request.json"
                        )
                    info = candidates[0]
                    if info.file_size > _MAX_REQUEST_BYTES:
                        raise _InvalidVerificationArtifact(
                            "verification request artifact exceeds size limit"
                        )
                    request = json.loads(archive.read(info))
            except (
                json.JSONDecodeError,
                RuntimeError,
                UnicodeDecodeError,
                zipfile.BadZipFile,
                zipfile.LargeZipFile,
            ) as exc:
                raise _InvalidVerificationArtifact(
                    "verification request artifact is malformed"
                ) from exc
            if not isinstance(request, dict):
                raise _InvalidVerificationArtifact(
                    "verification request artifact is not an object"
                )
            if (
                request.get("repository") != repository
                or str(request.get("pr_number"))
                != artifact_identity.group("pr_number")
                or request.get("current_head_sha")
                != artifact_identity.group("head_sha")
            ):
                raise _InvalidVerificationArtifact(
                    "verification artifact repository mismatch"
                )
            provenance = request.get("artifact_provenance")
            if not isinstance(provenance, Mapping) or not isinstance(
                workflow_run, Mapping
            ):
                raise _InvalidVerificationArtifact(
                    "verification artifact workflow-run mismatch"
                )
            if (
                provenance.get("workflow_run_id") != workflow_run.get("id")
                or provenance.get("repository_id") != workflow_run.get("repository_id")
                or workflow_run.get("head_repository_id")
                != workflow_run.get("repository_id")
            ):
                raise _InvalidVerificationArtifact(
                    "verification artifact workflow-run mismatch"
                )
            if provenance.get("artifact_name") != name:
                raise _InvalidVerificationArtifact(
                    "verification artifact identity mismatch"
                )
            source_workflow = request.get("source_workflow")
            if not isinstance(source_workflow, Mapping):
                raise _InvalidVerificationArtifact(
                    "verification source workflow identity mismatch"
                )
            source_run_id = source_workflow.get("run_id")
            if (
                not isinstance(source_run_id, int)
                or isinstance(source_run_id, bool)
                or source_run_id <= 0
            ):
                raise _InvalidVerificationArtifact(
                    "verification source workflow identity mismatch"
                )
            source_run = self._json(
                f"repos/{repository}/actions/runs/{source_run_id}"
            )
            source_repository = (
                source_run.get("repository")
                if isinstance(source_run, Mapping)
                else None
            )
            source_head_repository = (
                source_run.get("head_repository")
                if isinstance(source_run, Mapping)
                else None
            )
            if (
                not isinstance(source_run, Mapping)
                or not isinstance(source_repository, Mapping)
                or not isinstance(source_head_repository, Mapping)
                or source_run.get("id") != source_run_id
                or source_run.get("name") != source_workflow.get("name")
                or source_run.get("name") != "CI"
                or source_run.get("path") != _VERIFICATION_SOURCE_PATH
                or source_run.get("run_attempt")
                != source_workflow.get("run_attempt")
                or source_run.get("head_sha") != source_workflow.get("head_sha")
                or source_run.get("head_sha") != request.get("current_head_sha")
                or source_run.get("event") != "pull_request"
                or source_run.get("status") != "completed"
                or source_run.get("conclusion") != "success"
                or source_repository.get("id")
                != workflow_run.get("repository_id")
                or source_repository.get("full_name") != repository
                or source_head_repository.get("id")
                != workflow_run.get("head_repository_id")
                or source_head_repository.get("full_name") != repository
            ):
                raise _InvalidVerificationArtifact(
                    "verification source workflow identity mismatch"
                )
            try:
                return _authenticated_verification_request(request)
            except ValueError as exc:
                raise _InvalidVerificationArtifact(
                    "verification request artifact is malformed"
                ) from exc
        except _InvalidVerificationArtifact:
            raise

    def pending_requests(
        self, repository: str, *, limit: int = 20
    ) -> list[dict[str, object]]:
        if limit <= 0:
            raise ValueError("artifact request limit must be positive")
        payload = self._json(f"repos/{repository}/actions/artifacts?per_page=100")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("artifacts"), list):
            raise RuntimeError("malformed GitHub artifact listing")
        requests: list[dict[str, object]] = []
        first_rejection: _InvalidVerificationArtifact | None = None
        for artifact in payload["artifacts"]:
            if len(requests) >= limit:
                break
            if not isinstance(artifact, Mapping):
                continue
            try:
                request = self._request_from_artifact(repository, artifact)
            except _InvalidVerificationArtifact as exc:
                if first_rejection is None:
                    first_rejection = exc
                continue
            if request is not None:
                requests.append(request)
        if not requests and first_rejection is not None:
            raise first_rejection
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
        workflow_payload = self._json(
            f"repos/{repository}/actions/runs?head_sha={head_sha}&per_page=100"
        )
        if not isinstance(workflow_payload, Mapping) or not isinstance(
            workflow_payload.get("workflow_runs"), list
        ):
            raise RuntimeError("malformed GitHub workflow-runs response")
        workflows_by_suite: dict[int, list[Mapping[str, object]]] = {}
        for workflow in workflow_payload["workflow_runs"]:
            if not isinstance(workflow, Mapping):
                continue
            suite_id = workflow.get("check_suite_id")
            if (
                not isinstance(suite_id, int)
                or isinstance(suite_id, bool)
                or workflow.get("head_sha") != head_sha
            ):
                continue
            workflows_by_suite.setdefault(suite_id, []).append(workflow)

        checks: list[Mapping[str, object]] = []
        for row in payload["check_runs"]:
            if not isinstance(row, Mapping):
                continue
            authenticated = dict(row)
            authenticated.pop("workflow_run", None)
            suite_id = _nested(row, "check_suite", "id")
            candidates = (
                workflows_by_suite.get(suite_id, [])
                if isinstance(suite_id, int) and not isinstance(suite_id, bool)
                else []
            )
            if len(candidates) == 1:
                workflow = candidates[0]
                authenticated["workflow_run"] = {
                    "id": workflow.get("id"),
                    "workflow_id": workflow.get("workflow_id"),
                    "path": workflow.get("path"),
                    "event": workflow.get("event"),
                    "head_sha": workflow.get("head_sha"),
                    "check_suite_id": workflow.get("check_suite_id"),
                    "run_attempt": workflow.get("run_attempt"),
                }
            checks.append(authenticated)
        return checks


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
        try:
            env = _coordinator_environment(os.environ)
        except RuntimeError:
            return AuthReceipt(
                False,
                "chatgpt",
                "keyring",
                "required runtime environment unavailable",
            )
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
            f"codex exec failed closed (exit={receipt.get('returncode')}, "
            f"class={receipt.get('failure_class') or 'execution'})"
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

_SAFE_FAILURE_OUTCOMES = frozenset(
    {
        "codex_exec_failed",
        "heartbeat_authority_lost",
        "parent_exit_authority_lost",
        "thread_start_authority_lost",
    }
)
_SAFE_FAILURE_CLASSES = frozenset({"authority_loss", "execution", "rate_limit"})
_SAFE_ERROR_TYPE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]{0,55}(?:Error|Exception)\Z"
)
_UNSAFE_DIAGNOSTIC_KEYS = frozenset(
    {
        "api_key",
        "credential",
        "credentials",
        "error",
        "exception",
        "exception_text",
        "path",
        "raw",
        "raw_event",
        "stderr",
        "terminal_error",
        "terminal_event",
        "token",
        "traceback",
    }
)
_MAX_RECEIPT_TEXT = 512
_MAX_RECEIPT_LIST_ITEMS = 16
_MAX_RECEIPT_IDS = 32
_SAFE_DURABLE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}\Z")
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])(?P<quote>[\"']?)(?P<key>[A-Za-z0-9_.-]*"
    r"(?:api[_ -]?key|access[_ -]?token|auth[_ -]?token|token|credential|"
    r"password|secret)[A-Za-z0-9_.-]*)(?P=quote)\s*(?::|=|\s)\s*"
    r"(?:\[REDACTED\]|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"[^\s;,)\]}]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN_VALUE = re.compile(
    r"(?i)\b(?:gh[pousr]_|github_pat_|glpat-|sk-|AIza)[A-Za-z0-9_-]{6,}"
)
_JWT_VALUE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_OPAQUE_SECRET_VALUE = re.compile(
    r"(?<![A-Za-z0-9+/=_-])(?=[A-Za-z0-9+/=_-]{20,}"
    r"(?![A-Za-z0-9+/=_-]))(?=[A-Za-z0-9+/=_-]*[0-9])"
    r"[A-Za-z0-9+/=_-]{20,}"
)
_ABSOLUTE_MACHINE_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]*|"
    r"\\\\[^\\\s]+\\[^\\\s]+(?:\\[^\\\s]+)*|"
    r"/(?:[^/\s,;:)\]}]+/)*[^/\s,;:)\]}]+)"
)
_SAFE_CAPABILITIES = frozenset(
    {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "luna", "terra", "sol"}
)
_SAFE_REASONING_EFFORTS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "max"}
)
_SAFE_EVENT_OUTCOMES = frozenset({"blocking", "clean", "fixed", "repaired"})
_CANONICAL_HUMAN_ACTION_COPY = {
    "hold": (
        "Keep delivery blocked",
        "No gated action is authorized; the linked verification delivery remains blocked.",
    ),
    "authorize": (
        "Authorize the linked gated action",
        "The linked gated action may proceed only through its remaining recorded gates.",
    ),
    "select-alternative": (
        "Select an alternative on the linked issue",
        "Delivery remains blocked until a different choice is recorded on the linked issue.",
    ),
}
_HTTPS_URL_CANDIDATE = re.compile(r"https://[^\s,;)\]}\"'<>]+", re.IGNORECASE)


def _safe_github_url_projection(
    value: str, *, trusted_repository: str | None
) -> str:
    """Retain only bounded, recognized GitHub evidence routes without secrets."""

    try:
        parsed = urlsplit(value)
        host = parsed.hostname.lower() if parsed.hostname is not None else ""
        port = parsed.port
    except ValueError:
        return "[REDACTED_URL]"
    if host not in {"github.com", "api.github.com"}:
        return "[REDACTED_URL]"
    if parsed.username is not None or parsed.password is not None or port is not None:
        return f"https://{host}/REDACTED"
    if "%" in parsed.path:
        return f"https://{host}/REDACTED"
    segments = [segment for segment in parsed.path.split("/") if segment]
    contains_private_component = any(
        _CREDENTIAL_ASSIGNMENT.search(segment)
        or _BEARER_VALUE.search(segment)
        or _KNOWN_TOKEN_VALUE.search(segment)
        or _JWT_VALUE.search(segment)
        or _OPAQUE_SECRET_VALUE.search(segment)
        or _ABSOLUTE_MACHINE_PATH.search(segment)
        for segment in segments
    )
    github_route = (
        len(segments) == 2
        or (
            len(segments) == 4
            and segments[2] in {"issue", "issues", "pull", "pulls"}
            and segments[3].isdigit()
        )
        or (
            len(segments) == 5
            and segments[2:4] == ["actions", "runs"]
            and segments[4].isdigit()
        )
        or (
            len(segments) == 7
            and segments[2:4] == ["actions", "runs"]
            and segments[4].isdigit()
            and segments[5] == "job"
            and segments[6].isdigit()
        )
    )
    api_route = (
        len(segments) == 3
        and segments[0] == "repos"
        or (
            len(segments) == 5
            and segments[0] == "repos"
            and segments[3] in {"issue", "issues", "pull", "pulls"}
            and segments[4].isdigit()
        )
        or (
            len(segments) == 6
            and segments[0] == "repos"
            and segments[3:5] == ["actions", "runs"]
            and segments[5].isdigit()
        )
    )
    recognized_route = (
        host == "github.com" and github_route
    ) or (host == "api.github.com" and api_route)
    repository_components = (
        segments[:2] if host == "github.com" else segments[1:3]
    )
    authenticated_repository = "/".join(repository_components)
    if (
        contains_private_component
        or not recognized_route
        or trusted_repository is None
        or authenticated_repository.casefold() != trusted_repository.casefold()
    ):
        return f"https://{host}/REDACTED"
    return f"https://{host}{parsed.path}"[:256]


def bounded_error_type(value: object) -> str | None:
    if isinstance(value, str) and _SAFE_ERROR_TYPE.fullmatch(value):
        return value
    return None


def bounded_coordinator_session_id(value: object) -> str | None:
    """Accept only the canonical UUID identity emitted by Codex threads."""

    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


def _sanitize_receipt_text(
    value: object,
    *,
    trusted_repository: str | None,
    trusted_evidence_urls: frozenset[str] | None = None,
    limit: int = _MAX_RECEIPT_TEXT,
) -> str:
    """Project untrusted prose onto canonical redaction plus safe evidence links."""

    canonical_urls = (
        {url.casefold(): url for url in trusted_evidence_urls}
        if trusted_evidence_urls is not None
        else None
    )
    safe_urls: list[str] = []
    for match in _HTTPS_URL_CANDIDATE.finditer(str(value)):
        candidate = _safe_github_url_projection(
            match.group(0), trusted_repository=trusted_repository
        )
        if candidate in {
            "[REDACTED_URL]",
            "https://github.com/REDACTED",
            "https://api.github.com/REDACTED",
        }:
            continue
        if canonical_urls is not None:
            canonical = canonical_urls.get(candidate.casefold())
            if canonical is None:
                continue
            candidate = canonical
        if candidate not in safe_urls:
            safe_urls.append(candidate)

    projection = "[REDACTED]"
    for url in safe_urls:
        extended = f"{projection} {url}"
        if len(extended) > limit:
            break
        projection = extended
    return projection[:limit]


def _sanitize_retry_after(value: object) -> str | float | int | None:
    """Retain only retry values with syntax consumed by the local scheduler."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            amount = float(value)
        except OverflowError:
            return None
        if not math.isfinite(amount) or amount <= 0:
            return None
        bounded = min(amount, 3600.0)
        return int(bounded) if bounded.is_integer() else bounded
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > 128:
        return None
    duration = re.fullmatch(
        r"(?P<amount>\d+(?:\.\d+)?)(?P<unit>[smh])",
        stripped,
        re.IGNORECASE,
    )
    if duration is not None:
        amount = float(duration.group("amount"))
        if not math.isfinite(amount) or amount <= 0:
            return None
        seconds = amount * {"s": 1, "m": 60, "h": 3600}[
            duration.group("unit").lower()
        ]
        bounded = min(seconds, 3600.0)
        return f"{bounded:g}s"
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _required_receipt_text(
    value: object,
    *,
    trusted_repository: str | None,
    trusted_evidence_urls: frozenset[str] | None,
) -> str:
    return (
        _sanitize_receipt_text(
            value,
            trusted_repository=trusted_repository,
            trusted_evidence_urls=trusted_evidence_urls,
        )
        or "[REDACTED]"
    )


def _pseudonymous_receipt_identifier(value: object, *, prefix: str) -> str:
    raw = str(value)
    if re.fullmatch(rf"{re.escape(prefix)}-[0-9a-f]{{16}}", raw):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _allowlisted_receipt_value(
    value: object, *, allowed: frozenset[str], fallback: str
) -> str:
    raw = str(value)
    return raw if raw in allowed else fallback


def _sanitize_review_event(event: Mapping[str, object]) -> dict[str, object]:
    finding = event.get("finding_id")
    mechanism = event.get("mechanism_id")
    return {
        "kind": event["kind"],
        "session_id": _pseudonymous_receipt_identifier(
            event["session_id"], prefix="review-session"
        ),
        "capability": _allowlisted_receipt_value(
            event["capability"],
            allowed=_SAFE_CAPABILITIES,
            fallback="unknown-capability",
        ),
        "reasoning_effort": _allowlisted_receipt_value(
            event["reasoning_effort"],
            allowed=_SAFE_REASONING_EFFORTS,
            fallback="unknown",
        ),
        "outcome": _allowlisted_receipt_value(
            event["outcome"],
            allowed=_SAFE_EVENT_OUTCOMES,
            fallback="recorded",
        ),
        "finding_id": (
            _pseudonymous_receipt_identifier(finding, prefix="finding")
            if finding is not None
            else None
        ),
        "failure_domain": (
            _allowlisted_receipt_value(
                event.get("failure_domain"),
                allowed=REPAIR_FAILURE_DOMAINS,
                fallback="review_code_correctness",
            )
            if event.get("failure_domain") is not None
            else None
        ),
        "mechanism_id": (
            _pseudonymous_receipt_identifier(mechanism, prefix="mechanism")
            if mechanism is not None
            else None
        ),
        "strongest": event.get("strongest"),
    }


def _sanitize_human_exception_packet(
    packet: Mapping[str, object],
    *,
    trusted_repository: str | None,
    trusted_evidence_urls: frozenset[str] | None,
) -> dict[str, object]:
    raw_options = packet["options"]
    assert isinstance(raw_options, list)
    raw_no_action = str(packet["no_action_option"])
    raw_recommended = str(packet["recommended_option"])
    option_ids: dict[str, str] = {}
    options: list[dict[str, object]] = []
    for option in raw_options[:3]:
        assert isinstance(option, Mapping)
        raw_id = str(option["id"])
        if raw_id == raw_no_action:
            safe_id = "hold"
        elif raw_id == raw_recommended:
            safe_id = "authorize"
        elif raw_recommended == raw_no_action and "authorize" not in option_ids.values():
            safe_id = "authorize"
        else:
            safe_id = "select-alternative"
        label, consequence = _CANONICAL_HUMAN_ACTION_COPY[safe_id]
        option_ids[raw_id] = safe_id
        options.append(
            {
                "id": safe_id,
                "label": label,
                "consequence": consequence,
            }
        )

    def safe_list(field: str) -> list[str]:
        values = packet[field]
        assert isinstance(values, list)
        return [
            _required_receipt_text(
                value,
                trusted_repository=trusted_repository,
                trusted_evidence_urls=trusted_evidence_urls,
            )
            for value in values[:_MAX_RECEIPT_LIST_ITEMS]
        ]

    return {
        "failure_class": packet["failure_class"],
        "original_intent": _required_receipt_text(
            packet["original_intent"],
            trusted_repository=trusted_repository,
            trusted_evidence_urls=trusted_evidence_urls,
        ),
        "current_state": _required_receipt_text(
            packet["current_state"],
            trusted_repository=trusted_repository,
            trusted_evidence_urls=trusted_evidence_urls,
        ),
        "tried_actions": safe_list("tried_actions"),
        "evidence": safe_list("evidence"),
        "why_unsafe": _required_receipt_text(
            packet["why_unsafe"],
            trusted_repository=trusted_repository,
            trusted_evidence_urls=trusted_evidence_urls,
        ),
        "options": options,
        "no_action_option": option_ids[raw_no_action],
        "recommended_option": option_ids[raw_recommended],
        "recommendation_rationale": (
            "The coordinator selected this canonical action; inspect the linked issue "
            "evidence before authorizing any gated effect."
        ),
        "consequence_of_doing_nothing": (
            "The verification delivery remains blocked until the linked owner decision "
            "is recorded."
        ),
    }


def sanitize_verification_closer_receipt(
    receipt: Mapping[str, object],
    *,
    trusted_repository: str | None = None,
    trusted_evidence_urls: frozenset[str] | None = None,
) -> dict[str, object]:
    """Project one schema-valid coordinator receipt onto its durable-safe form."""

    raw_receipt_ids = receipt["receipt_ids"]
    assert isinstance(raw_receipt_ids, list)
    raw_events = receipt.get("review_events")
    raw_exception = receipt.get("human_exception")
    retry_after = _sanitize_retry_after(receipt.get("retry_after"))
    return {
        "verdict": receipt["verdict"],
        "head_sha": receipt["head_sha"],
        "summary": _sanitize_receipt_text(
            receipt["summary"],
            trusted_repository=trusted_repository,
            trusted_evidence_urls=trusted_evidence_urls,
        ),
        "receipt_ids": [
            _pseudonymous_receipt_identifier(value, prefix="receipt")
            for value in raw_receipt_ids[:_MAX_RECEIPT_IDS]
        ],
        "retry_after": retry_after,
        "review_events": (
            [
                _sanitize_review_event(event)
                for event in raw_events[:_MAX_RECEIPT_LIST_ITEMS]
                if isinstance(event, Mapping)
            ]
            if isinstance(raw_events, list)
            else None
        ),
        "human_exception": (
            _sanitize_human_exception_packet(
                raw_exception,
                trusted_repository=trusted_repository,
                trusted_evidence_urls=trusted_evidence_urls,
            )
            if isinstance(raw_exception, Mapping)
            else None
        ),
    }


def sanitize_codex_failure_receipt(
    receipt: Mapping[str, object],
    *,
    failure_class: str | None = None,
) -> dict[str, object]:
    """Return the bounded failure fields permitted to cross durable boundaries."""

    raw_outcome = receipt.get("outcome")
    outcome = (
        raw_outcome
        if isinstance(raw_outcome, str) and raw_outcome in _SAFE_FAILURE_OUTCOMES
        else "codex_exec_failed"
    )
    raw_class = failure_class or receipt.get("failure_class")
    if not isinstance(raw_class, str) or raw_class not in _SAFE_FAILURE_CLASSES:
        raw_class = "authority_loss" if outcome.endswith("_authority_lost") else "execution"
    safe: dict[str, object] = {"outcome": outcome, "failure_class": raw_class}
    returncode = receipt.get("returncode")
    if isinstance(returncode, int) and not isinstance(returncode, bool):
        safe["returncode"] = returncode
    error_type = bounded_error_type(receipt.get("error_type"))
    if error_type is not None:
        safe["error_type"] = error_type
    session_id = bounded_coordinator_session_id(receipt.get("session_id"))
    if session_id is not None:
        safe["session_id"] = session_id
    return safe


def redact_durable_diagnostics(value: object) -> object:
    """Defence-in-depth redaction for status reads of pre-fix durable rows."""

    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.lower()
            if (
                normalized in _UNSAFE_DIAGNOSTIC_KEYS
                or normalized.endswith("_path")
                or normalized.endswith("_token")
                or "credential" in normalized
            ):
                continue
            if normalized == "session_id":
                safe_session_id = bounded_coordinator_session_id(child)
                if safe_session_id is not None:
                    redacted[key] = safe_session_id
                continue
            if normalized == "error_type":
                safe_error_type = bounded_error_type(child)
                if safe_error_type is not None:
                    redacted[key] = safe_error_type
                continue
            redacted[key] = redact_durable_diagnostics(child)
        return redacted
    if isinstance(value, list):
        return [
            redact_durable_diagnostics(child)
            for child in value[:_MAX_RECEIPT_LIST_ITEMS]
        ]
    if isinstance(value, str):
        return _sanitize_receipt_text(value, trusted_repository=None)
    return value


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

    # Free-form diagnostics are untrusted and ambiguous: contractions,
    # explicit false values, quoted examples, and provider prose cannot mint a
    # durable backoff classification. Only parsed provider fields above count.
    return False


def _local_now() -> datetime | None:
    """Return an aware local instant backed by the host's full timezone rules."""

    try:
        with Path("/etc/localtime").open("rb") as stream:
            local_zone = ZoneInfo.from_file(stream)
    except (OSError, ValueError):
        return None
    return datetime.now(local_zone)


def _is_future_local_wall_time(
    current: datetime, wall_time: datetime, *, max_delta: timedelta
) -> bool:
    """Accept a local wall time when at least one real fold is a future instant."""

    if current.tzinfo is None or wall_time.tzinfo is not None:
        return False
    try:
        current_utc = current.astimezone(timezone.utc)
        latest_utc = current_utc + max_delta
    except (OSError, OverflowError, ValueError):
        return False
    for fold in (0, 1):
        try:
            candidate = wall_time.replace(tzinfo=current.tzinfo, fold=fold)
            candidate_utc = candidate.astimezone(timezone.utc)
            round_trip = candidate_utc.astimezone(current.tzinfo)
        except (OSError, OverflowError, ValueError):
            continue
        if round_trip.replace(tzinfo=None) != wall_time:
            continue
        if current_utc <= candidate_utc <= latest_utc:
            return True
    return False


def _is_valid_codex_retry(retry: str) -> bool:
    if retry == "later":
        return True
    if not retry.startswith("at "):
        return False
    timestamp = retry.removeprefix("at ")
    current = _local_now()
    if current is None:
        return False
    current = current.replace(second=0, microsecond=0)
    clock = re.fullmatch(
        r"(?P<hour>[1-9]|1[0-2]):(?P<minute>[0-9]{2}) (?P<period>AM|PM)",
        timestamp,
    )
    if clock is not None:
        hour = int(clock.group("hour"))
        minute = int(clock.group("minute"))
        if minute > 59:
            return False
        hour = hour % 12 + (12 if clock.group("period") == "PM" else 0)
        candidate = datetime(
            current.year,
            current.month,
            current.day,
            hour=hour,
            minute=minute,
        )
        return _is_future_local_wall_time(
            current, candidate, max_delta=timedelta(days=1)
        )
    match = re.fullmatch(
        r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
        r"(?P<day>[1-9]|[12][0-9]|3[01])(?P<suffix>st|nd|rd|th), "
        r"(?P<year>[0-9]{4}) (?P<hour>[1-9]|1[0-2]):"
        r"(?P<minute>[0-9]{2}) (?P<period>AM|PM)",
        timestamp,
    )
    if match is None:
        return False
    day = int(match.group("day"))
    suffix = (
        "th"
        if 11 <= day % 100 <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    )
    if match.group("suffix") != suffix:
        return False
    minute = int(match.group("minute"))
    if minute > 59:
        return False
    hour = int(match.group("hour")) % 12 + (
        12 if match.group("period") == "PM" else 0
    )
    month = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }[match.group("month")]
    try:
        candidate = datetime(
            int(match.group("year")), month, day, hour, minute
        )
    except ValueError:
        return False
    if candidate.date() <= current.date():
        return False
    return _is_future_local_wall_time(
        current, candidate, max_delta=timedelta(days=5 * 366)
    )


def _is_codex_usage_limit_event(event: object) -> bool:
    """Recognize the bounded Codex CLI envelope for subscription exhaustion."""

    if (
        not isinstance(event, Mapping)
        or set(event) != {"type", "message"}
        or event.get("type") != "error"
    ):
        return False
    message = event.get("message")
    if not isinstance(message, str) or not message.isascii():
        return False
    retry_time = (
        r"(?:(?:[1-9]|1[0-2]):[0-9]{2} (?:AM|PM)|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
        r"(?:[1-9]|[12][0-9]|3[01])(?:st|nd|rd|th), [0-9]{4} "
        r"(?:[1-9]|1[0-2]):[0-9]{2} "
        r"(?:AM|PM))"
    )
    retry = rf"(?:later|at {retry_time})"
    limit_name = r"(?P<limit_name>[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?)"
    plan_copy = (
        r"(?:Upgrade to Pro \(https://chatgpt\.com/explore/pro\), visit "
        r"https://chatgpt\.com/codex/settings/usage to purchase more credits|"
        r"To get more access now, send a request to your admin|"
        r"Upgrade to Plus to continue using Codex "
        r"\(https://chatgpt\.com/explore/plus\),|"
        r"Visit https://chatgpt\.com/codex/settings/usage to purchase more credits)"
    )
    model_specific = re.fullmatch(
        rf"You've hit your usage limit for {limit_name}\. "
        rf"Switch to another model now, or try again (?P<retry>{retry})\.",
        message,
    )
    if model_specific is not None:
        if model_specific.group("limit_name").lower() == "codex":
            return False
        return _is_valid_codex_retry(model_specific.group("retry"))
    for pattern in (
        rf"You've hit your usage limit\. {plan_copy} or try again (?P<retry>{retry})\.",
        rf"You've hit your usage limit\. Try again (?P<retry>{retry})\.",
    ):
        match = re.fullmatch(pattern, message)
        if match is not None:
            return _is_valid_codex_retry(match.group("retry"))
    return False


class CodexExecLauncher:
    """Explicit least-privilege non-interactive verification coordinator."""

    def __init__(
        self,
        worktree: Path,
        receipt_schema: Path,
        context_path: Path,
        adapter_path: Path | None = None,
        runner: ProcessRunner | None = None,
        containment_factory: Callable[[], WholeTreeContainment] | None = None,
        cleanup_tracker_factory: Callable[[], WholeTreeContainment] | None = None,
    ) -> None:
        self.worktree = worktree
        self.receipt_schema = receipt_schema
        self.context_path = context_path
        self.runner = runner if runner is not None else cast(ProcessRunner, subprocess.run)
        self.containment_factory = containment_factory or TaggedProcessTreeCleanup
        self.cleanup_tracker_factory = (
            cleanup_tracker_factory or TaggedProcessTreeCleanup
        )
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
        base_env = _coordinator_environment(os.environ)
        try:
            containment = self.containment_factory()
            cleanup_tracker = (
                containment
                if isinstance(containment, TaggedProcessTreeCleanup)
                else self.cleanup_tracker_factory()
            )
            env = containment.environment(base_env)
            if cleanup_tracker is not containment:
                env = cleanup_tracker.environment(env)
        except Exception:
            raise RuntimeError("verification containment setup failed") from None
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
        containment_proven = False
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

        def cleanup_process_tree() -> bool:
            if cleanup_tracker is not containment:
                try:
                    cleanup_tracker.cleanup()
                except Exception:
                    pass
            try:
                return bool(containment.cleanup())
            except Exception:
                return False

        def terminate_and_reap_child() -> None:
            nonlocal containment_proven, process_group_id
            with process_lock:
                if process is None:
                    return
                try:
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
                    else:
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
                except Exception:
                    # A broken process adapter must not replace the safe
                    # launcher failure or skip bounded emergency cleanup.
                    try:
                        signal_process_group(signal.SIGKILL)
                    except Exception:
                        pass
                    try:
                        process.kill()
                    except Exception:
                        pass
                    try:
                        process.wait(timeout=5)
                    except Exception:
                        pass
                finally:
                    process_group_id = None
                    containment_proven = (
                        cleanup_process_tree() or containment_proven
                    )

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
            try:
                process_group_id = getattr(process, "pid", None)
                if process_group_id is not None:
                    if cleanup_tracker is not containment:
                        cleanup_tracker.attach(process_group_id)
                    containment.attach(process_group_id)
                if process.stdout is None or process.stderr is None:
                    raise RuntimeError("coordinator process pipes unavailable")
                lines = process.stdout
                stderr = process.stderr
            except Exception:
                terminate_and_reap_child()
                raise RuntimeError("verification coordinator setup failed") from None

            def drain_stderr() -> None:
                while chunk := stderr.read(4096):
                    stderr_chunks.append(chunk)
                    if sum(map(len, stderr_chunks)) > 16_384:
                        stderr_chunks[:] = ["".join(stderr_chunks)[-16_384:]]

            try:
                stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
                stderr_thread.start()
            except Exception:
                stop_heartbeat.set()
                terminate_and_reap_child()
                raise RuntimeError("verification coordinator setup failed") from None

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

            try:
                parent_watchdog_thread = threading.Thread(
                    target=watch_parent_liveness, daemon=True
                )
                parent_watchdog_thread.start()
            except Exception:
                stop_heartbeat.set()
                terminate_and_reap_child()
                raise RuntimeError("verification coordinator setup failed") from None
            if on_heartbeat:
                def pulse() -> None:
                    while not stop_heartbeat.wait(30):
                        try:
                            on_heartbeat()
                        except Exception as exc:
                            record_authority_loss(exc)
                            return
                try:
                    heartbeat_thread = threading.Thread(target=pulse, daemon=True)
                    heartbeat_thread.start()
                except Exception:
                    stop_heartbeat.set()
                    terminate_and_reap_child()
                    raise RuntimeError(
                        "verification coordinator setup failed"
                    ) from None
        else:
            result = self.runner(
                self.command(resume_session_id), cwd=self.worktree, env=env,
                capture_output=True, text=True, check=False,
            )
            lines = result.stdout.splitlines()
            stderr_chunks = [str(getattr(result, "stderr", "") or "")[-16_384:]]
        thread_id: str | None = resume_session_id
        terminal_strict: dict[str, object] | None = None
        terminal_fallback: dict[str, object] | None = None
        terminal_error: str | None = None
        terminal_rate_limited = False
        try:
            for line in lines:
                if authority_lost.is_set():
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") in {"turn.failed", "error"}:
                    terminal_error = json.dumps(event, sort_keys=True)
                    terminal_rate_limited = (
                        _is_codex_usage_limit_event(event)
                        or terminal_rate_limited
                    )
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
                            except json.JSONDecodeError:
                                continue
                            try:
                                validate_verification_closer_receipt(candidate, schema)
                            except jsonschema.ValidationError:
                                # A resumed policy-v1 coordinator may emit a
                                # receipt in the legacy shape (missing binding
                                # keys, or a clean review carrying stale
                                # binding fields) that the strict contract
                                # rejects. This stream filter only selects the
                                # terminal candidate; the consumer re-validates
                                # it through
                                # load_and_validate_verification_closer_receipt
                                # with the run's actual repair_budget_policy,
                                # so a policy-v2 run still fails closed there
                                # (with the accurate invalid_receipt_contract
                                # reason) instead of being misclassified as a
                                # launcher contract failure here. A fallback
                                # match is ranked below every strict match: a
                                # trailing legacy-shaped message must never
                                # clobber a strictly-valid final receipt the
                                # stream already produced.
                                if not isinstance(candidate, Mapping):
                                    continue
                                try:
                                    validate_verification_closer_receipt(
                                        _v1_compatible_receipt_candidate(candidate),
                                        schema,
                                        allow_legacy_unbound_repairs=True,
                                    )
                                except jsonschema.ValidationError:
                                    continue
                                terminal_fallback = dict(candidate)
                            else:
                                terminal_strict = candidate
        except Exception:
            stop_heartbeat.set()
            terminate_and_reap_child()
            raise RuntimeError("verification coordinator stream failed") from None
        stdout_complete.set()
        if self.runner is subprocess.run:
            assert process is not None
            try:
                if authority_lost.is_set():
                    stop_heartbeat.set()
                    terminate_and_reap_child()
                else:
                    process.wait()
                    # A clean direct-parent exit is not sufficient to release
                    # coordinator authority: descendants can detach their stdio
                    # yet remain in the private process group. Remove any such
                    # residual without accepting a terminal receipt early.
                    if process_group_is_alive():
                        terminate_and_reap_child()
                    else:
                        process_group_id = None
                        containment_proven = cleanup_process_tree()
            except Exception:
                stop_heartbeat.set()
                terminate_and_reap_child()
                raise RuntimeError("verification coordinator process failed") from None
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
                    "error_type": type(failure).__name__,
                    "returncode": returncode,
                    "stderr": authority_loss_outcome.replace("_", " "),
                    "terminal_error": f"{type(failure).__name__}: {failure}",
                    "session_id": thread_id,
                }
            )
        if returncode != 0 or terminal_error is not None:
            stderr_detail = "".join(stderr_chunks).strip()
            detail = stderr_detail or terminal_error or "no stderr"
            failure_class = (
                "rate_limit"
                if terminal_rate_limited
                or any(
                    _is_rate_limit_exec_failure(candidate)
                    for candidate in (stderr_detail, terminal_error)
                    if candidate
                )
                else "execution"
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
        if self.runner is subprocess.run and not containment_proven:
            raise RuntimeError(
                "whole-process-tree containment unavailable; terminal receipt rejected"
            )
        if not thread_id:
            raise RuntimeError("codex exec produced no thread identity")
        # The latest strictly-valid receipt always outranks any legacy-shaped
        # fallback candidate; the fallback is used only when the whole stream
        # produced no strict match.
        terminal = terminal_strict if terminal_strict is not None else terminal_fallback
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


def _trusted_evidence_urls(run: VerificationRun) -> frozenset[str]:
    """Derive the only durable evidence links from authenticated run identity."""

    repository = run.repository
    web_base = f"https://github.com/{repository}"
    api_base = f"https://api.github.com/repos/{repository}"
    urls = {web_base, api_base}

    def positive_int(value: object) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return None

    issue_numbers = [positive_int(run.request.get("linked_issue"))]
    issue_numbers.extend(positive_int(value) for value in run.supporting_authority)
    for issue_number in issue_numbers:
        if issue_number is not None:
            urls.add(f"{web_base}/issues/{issue_number}")
            urls.add(f"{api_base}/issues/{issue_number}")

    urls.add(f"{web_base}/pull/{run.pr_number}")
    urls.add(f"{api_base}/pulls/{run.pr_number}")

    workflow_run_ids = {
        positive_int(_nested(run.request, "source_workflow", "run_id")),
        positive_int(_nested(run.request, "live_truth", "source_run_id")),
        positive_int(_nested(run.request, "artifact_provenance", "workflow_run_id")),
    }
    for workflow_run_id in workflow_run_ids:
        if workflow_run_id is not None:
            urls.add(f"{web_base}/actions/runs/{workflow_run_id}")
            urls.add(f"{api_base}/actions/runs/{workflow_run_id}")

    return frozenset(urls)


def _governing_contract_matches(run: VerificationRun, pr_body: object) -> bool:
    issue_contract = resolve_issue_contract(pr_body)
    return bool(
        issue_contract is not None
        and issue_contract[0] == run.request.get("linked_issue")
        and set(run.supporting_authority).issubset(issue_contract[1])
    )


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
    if not _governing_contract_matches(run, pr.get("body")):
        return "governing_issue_mismatch"
    return _checks_rejection(
        checks, expected_head_sha=expected_head_sha or run.head_sha
    )


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
    if not _governing_contract_matches(run, pr.get("body")):
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
    return _checks_rejection(checks, expected_head_sha=expected_head_sha)


def _checks_rejection(
    checks: Sequence[Mapping[str, object]], *, expected_head_sha: str
) -> str | None:
    if not checks:
        return "missing_checks"
    required_checks = {"Unit tests (not pg)": ".github/workflows/ci.yml"}
    latest: dict[str, tuple[tuple[int, str, int], Mapping[str, object]]] = {}
    for index, check in enumerate(checks):
        name = check.get("name")
        required_workflow = required_checks.get(name) if isinstance(name, str) else None
        if required_workflow is not None:
            suite_id = _nested(check, "check_suite", "id")
            workflow_run_id = _nested(check, "workflow_run", "id")
            if (
                _nested(check, "app", "slug") != "github-actions"
                or not isinstance(suite_id, int)
                or isinstance(suite_id, bool)
                or not isinstance(workflow_run_id, int)
                or isinstance(workflow_run_id, bool)
                or _nested(check, "workflow_run", "check_suite_id") != suite_id
                or _nested(check, "workflow_run", "path") != required_workflow
                or _nested(check, "workflow_run", "event") != "pull_request"
                or _nested(check, "workflow_run", "head_sha") != expected_head_sha
            ):
                continue
        key = name if isinstance(name, str) and name else f"__unnamed_{index}"
        check_id = check.get("id")
        rank = (
            check_id if isinstance(check_id, int) and not isinstance(check_id, bool) else -1,
            str(check.get("started_at") or check.get("completed_at") or ""),
            index,
        )
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, check)
    if not required_checks.keys() <= latest.keys():
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


def context_pack(
    run: VerificationRun,
    pr: Mapping[str, object],
    *,
    repair_budget: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return the immutable minimum; no issue/diff/log/untrusted body text."""
    linked_issue = run.request.get("linked_issue")
    return {
        "contract": "verification_closer_dispatch_context.v1",
        "run_id": run.run_id,
        "repository": run.repository,
        "pr_number": run.pr_number,
        "linked_issue": linked_issue if isinstance(linked_issue, int) else None,
        "head_sha": run.head_sha,
        "requested_head_sha": run.requested_head_sha,
        "stage": run.stage,
        "verification_skill": ".codex/skills/verification-and-closure/SKILL.md",
        "agent_adapter": ".codex/agents/verification-closer.toml",
        "idempotency_key": run.idempotency_key,
        "repair_budget": dict(repair_budget) if repair_budget is not None else {
            "policy_version": run.repair_budget_policy,
            "mechanism_count": 0,
            "truncated": False,
            "omitted_count": 0,
            "mechanisms": [],
        },
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
        receipt_schema: Path | None = None,
    ) -> None:
        self.ledger, self.truth, self.auth, self.launcher, self.holder = (
            ledger, truth, auth, launcher, holder
        )
        self.receipt_schema = receipt_schema or CANONICAL_RECEIPT_SCHEMA_PATH

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
        try:
            receipt = load_and_validate_verification_closer_receipt(
                receipt,
                self.receipt_schema,
                trusted_repository=run.repository,
                trusted_evidence_urls=_trusted_evidence_urls(run),
                repair_budget_policy=run.repair_budget_policy,
            )
        except ReceiptContractError as exc:
            try:
                claimed = self.ledger.claim(run.run_id, self.holder)
            except (VerificationSubscriptionBusy, VerificationBackoffPending):
                current = self.ledger.get(run.run_id)
                assert current is not None
                return current
            cause = exc.__cause__
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                {
                    "outcome": "invalid_persisted_verification_receipt",
                    "error_type": type(cause).__name__ if cause else type(exc).__name__,
                },
                reason="invalid_receipt_contract",
                holder=self.holder,
                lease_id=claimed.lease_id or "",
            )
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
        if changed_head:
            live_pr_number = live_pr.get("number")
            assert isinstance(live_pr_number, int) and not isinstance(
                live_pr_number, bool
            )
            try:
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
            except ValueError:
                current = self.ledger.get(claimed.run_id)
                if current is not None:
                    return current
                raise
        loop = VerificationAgentLoop(
            self.ledger,
            claimed.run_id,
            holder=self.holder,
            lease_id=lease_id,
        )
        if events:
            try:
                loop.apply_events(
                    events,
                    context=context_pack(
                        claimed,
                        live_pr,
                        repair_budget=self.ledger.repair_budget_projection(
                            claimed.run_id
                        ),
                    ),
                )
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
        intake_pr: Mapping[str, object] | None = None
        if isinstance(request, _AuthenticatedVerificationRequest):
            repository = request.get("repository")
            pr_number = request.get("pr_number")
            if (
                not isinstance(repository, str)
                or not isinstance(pr_number, int)
                or isinstance(pr_number, bool)
                or pr_number <= 0
            ):
                raise ValueError("malformed authenticated verification request")
            canonical_chain_token = self.ledger.canonical_chain_token(request)
            intake_pr = self.truth.pull_request(repository, pr_number)
            issue_contract = resolve_issue_contract(intake_pr.get("body"))
            request = _live_observed_verification_request(
                request,
                observed_repository=_nested(
                    intake_pr, "base", "repo", "full_name"
                ),
                observed_pr_number=intake_pr.get("number"),
                observed_head_sha=_nested(intake_pr, "head", "sha"),
                observed_state=intake_pr.get("state"),
                observed_merged_at=intake_pr.get("merged_at"),
                observed_draft=intake_pr.get("draft"),
                observed_linked_issue=(
                    issue_contract[0] if issue_contract is not None else None
                ),
                observed_supporting_issues=(
                    issue_contract[1] if issue_contract is not None else None
                ),
                canonical_chain_token=canonical_chain_token,
            )
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
        pack = context_pack(
            claimed,
            pr,
            repair_budget=self.ledger.repair_budget_projection(claimed.run_id),
        )

        def started(session_id: str) -> None:
            safe_session_id = bounded_coordinator_session_id(session_id)
            if safe_session_id is None:
                raise ValueError("invalid coordinator session identity")
            current = self.ledger.get(claimed.run_id)
            if current is not None and current.status == "claimed":
                self.ledger.start(
                    claimed.run_id,
                    self.holder,
                    lease_id,
                    safe_session_id,
                    pack,
                )

        def heartbeat() -> None:
            self.ledger.heartbeat(claimed.run_id, self.holder, lease_id)

        try:
            resume_session_id = bounded_coordinator_session_id(
                claimed.coordinator_session_id
            )
            if (
                claimed.coordinator_session_id is not None
                and resume_session_id is None
            ):
                raise ValueError("invalid stored coordinator session identity")
            session_id, receipt = self.launcher.launch(
                pack,
                resume_session_id=resume_session_id,
                on_thread_started=started,
                on_heartbeat=heartbeat,
            )
            receipt = load_and_validate_verification_closer_receipt(
                receipt,
                self.receipt_schema,
                trusted_repository=claimed.repository,
                trusted_evidence_urls=_trusted_evidence_urls(claimed),
                repair_budget_policy=claimed.repair_budget_policy,
            )
            safe_session_id = bounded_coordinator_session_id(session_id)
            if safe_session_id is None:
                raise ValueError("invalid returned coordinator session identity")
            current = self.ledger.get(claimed.run_id)
            if current is not None and current.status == "claimed":
                started(safe_session_id)
                current = self.ledger.get(claimed.run_id)
            if (
                current is not None
                and current.coordinator_session_id != safe_session_id
            ):
                raise ValueError("coordinator session identity mismatch")
            session_id = safe_session_id
        except ReceiptContractError as exc:
            cause = exc.__cause__
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                {
                    "outcome": "invalid_verification_receipt",
                    "error_type": type(cause).__name__ if cause else type(exc).__name__,
                },
                reason="invalid_receipt_contract",
                holder=self.holder,
                lease_id=lease_id,
            )
        except CodexExecFailure as exc:
            raw_failure = exc.receipt
            rate_limited = self._rate_limited(raw_failure)
            retry_hint = self._retry_hint(raw_failure) if rate_limited else None
            failure_receipt = sanitize_codex_failure_receipt(
                raw_failure,
                failure_class="rate_limit" if rate_limited else None,
            )
            failed_session = failure_receipt.get("session_id")
            if str(failure_receipt.get("outcome", "")).endswith("_authority_lost"):
                retry_after = _retry_at()
                failure_receipt = {
                    **failure_receipt,
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
            if isinstance(failed_session, str) and failed_session:
                self.ledger.record_attempt(
                    claimed.run_id,
                    "verification",
                    failed_session,
                    self.launcher.config.model,
                    self.launcher.config.reasoning_effort,
                    pack,
                    "rate_limited" if rate_limited else "launch_failed",
                    failure_receipt,
                    holder=self.holder,
                    lease_id=lease_id,
                )
            if rate_limited:
                retry_after = _retry_at(retry_hint)
                return self.ledger.backoff(
                    claimed.run_id,
                    {
                        "outcome": "rate_limited",
                        "api_fallback": False,
                        "retry_after": retry_after,
                        "failure_receipt": failure_receipt,
                    },
                    retry_after=retry_after,
                    holder=self.holder,
                    lease_id=lease_id,
                )
            return self.ledger.terminal(
                claimed.run_id,
                "failed",
                failure_receipt,
                reason="codex_exec_failed",
                holder=self.holder,
                lease_id=lease_id,
            )
        except Exception as exc:
            # A zero-exit launcher can still fail its terminal contract (for
            # example, no thread identity, a process OS error, or no
            # schema-valid final receipt).
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
                    pack = context_pack(
                        claimed,
                        live_pr,
                        repair_budget=self.ledger.repair_budget_projection(
                            claimed.run_id
                        ),
                    )
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

        pack = context_pack(
            claimed,
            live_pr,
            repair_budget=self.ledger.repair_budget_projection(claimed.run_id),
        )
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
