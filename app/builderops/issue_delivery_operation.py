"""Authenticated destination adapter for one approved Issue delivery.

FCA-ID-A owns admission.  This module adds only the destination reservation,
pre-launch attempt, observed entry and replay fences needed by FCA-ID-B.  The
actual Git/GitHub mutation remains owned by the protected host executor from
``issue_delivery_effect_executor``.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneClientError,
    ControlPlaneNotFoundError,
)
from app.builderops.control_plane.issue_delivery import (
    OPERATION_TYPE,
    PERMITTED_EFFECTS,
    canonical_hash,
    destination_resource_key,
    manifest_hash,
    normalize_manifest,
    delivery_source_pair,
    SECOND_CONTRACT_VERSION,
    tracking_repository,
)
from app.builderops.control_plane.models import EnvelopeValidationError, canonical_repository
from app.builderops.epic_dispatch import CodexIssueSessionLauncher, IssueSessionLauncher


class IssueDeliveryOperationError(RuntimeError):
    """An operation is unresolved or unavailable and must not be relaunched."""

    def __init__(self, message: str, *, session_id: str | None = None) -> None:
        self.session_id = session_id
        super().__init__(message)


class IssueDeliveryOperationRefused(IssueDeliveryOperationError):
    """A changed, stale or unsupported operation cannot cross a gate."""


def _require_protected_host_executor(value: Any) -> Any:
    """Accept only the repository-owned executor class at the effect boundary."""

    from app.builderops.issue_delivery_effect_executor import IssueDeliveryHostExecutor

    if not isinstance(value, IssueDeliveryHostExecutor):
        raise IssueDeliveryOperationRefused(
            "production Issue delivery requires the exact protected host executor"
        )
    return value


class _OperationClient(Protocol):
    def issue_delivery_authority(
        self, *, manifest: Mapping[str, Any], purpose: str
    ) -> dict[str, Any]: ...

    def issue_delivery_operation_record(
        self,
        *,
        envelope: Mapping[str, Any],
        record_id: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        operation_key: str,
        approval_id: str,
        approval_manifest_hash: str,
    ) -> dict[str, Any]: ...

    def issue_delivery_operation_record_read(
        self, *, repository: str, record_id: str
    ) -> dict[str, Any]: ...


_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_RECORD_STATES = {
    "reservation": "reserved",
    "attempt": "attempted",
    "entry": "active",
    "terminal": "terminal",
}
_WORKER_RESERVED_HOST_EFFECT_FIELDS = frozenset(
    {"effect_receipts", "host_effect_refs"}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _record_hash(record: Mapping[str, Any]) -> str:
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise IssueDeliveryOperationRefused("destination receipt payload is malformed")
    declared = payload.get("receipt_hash")
    if not isinstance(declared, str) or _SHA256.fullmatch(declared) is None:
        raise IssueDeliveryOperationRefused("destination receipt hash is missing")
    if _digest({key: value for key, value in payload.items() if key != "receipt_hash"}) != declared:
        raise IssueDeliveryOperationRefused("destination receipt hash is corrupt")
    return declared


def _worker_supplies_host_effect_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in _WORKER_RESERVED_HOST_EFFECT_FIELDS
            or _worker_supplies_host_effect_field(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_worker_supplies_host_effect_field(item) for item in value)
    return False


def _bound_issue_delivery_approval(
    approval: Mapping[str, Any], *, allow_legacy_normalization: bool = True
) -> dict[str, Any]:
    """Validate the immutable approval without touching live destination state."""

    raw_destination = approval.get("destination")
    admitted_binding = isinstance(raw_destination, Mapping) and all(
        isinstance(raw_destination.get(name), str)
        and bool(str(raw_destination.get(name)).strip())
        for name in ("resolved_checkout", "resolved_worktree")
    )
    try:
        normalized = (
            dict(approval)
            if admitted_binding or not allow_legacy_normalization
            else normalize_manifest(dict(approval))
        )
    except Exception as exc:
        raise IssueDeliveryOperationRefused("committed Issue-delivery approval is invalid") from exc
    value = dict(approval)
    if value.get("approval_manifest_hash") != manifest_hash(value):
        raise IssueDeliveryOperationRefused("Issue-delivery approval hash is corrupt")
    destination = value.get("destination")
    if not isinstance(destination, Mapping):
        raise IssueDeliveryOperationRefused("Issue-delivery destination is missing")
    context = value.get("context")
    plan = context.get("dispatch_plan") if isinstance(context, Mapping) else None
    packs = plan.get("context_packs") if isinstance(plan, Mapping) else None
    if not isinstance(plan, Mapping) or not isinstance(packs, list) or len(packs) != 1:
        raise IssueDeliveryOperationRefused("approval does not bind one context pack")
    worktree_plan = packs[0].get("branch_worktree_plan") if isinstance(packs[0], Mapping) else None
    if (
        not isinstance(worktree_plan, Mapping)
        or plan.get("run_id") != destination.get("run_id")
        or worktree_plan.get("branch") != destination.get("branch")
        or worktree_plan.get("worktree") != destination.get("worktree")
    ):
        raise IssueDeliveryOperationRefused("approved context and destination are not bound")
    if set(value.get("permitted_effects", ())) != set(PERMITTED_EFFECTS):
        raise IssueDeliveryOperationRefused("Issue-delivery effect grant is incomplete")
    # Retain the prior parser as a full immutable-contract preflight.  Its
    # value must not trigger a filesystem lookup during recovery.
    del normalized
    return value


def _bind_dispatch_plan(
    approval: Mapping[str, Any], plan: Mapping[str, Any], *, expected_plan_hash: str | None
) -> None:
    context = approval.get("context")
    approved = context.get("dispatch_plan") if isinstance(context, Mapping) else None
    approved_hash = context.get("expected_plan_hash") if isinstance(context, Mapping) else None
    if (
        not isinstance(approved, Mapping)
        or canonical_hash(plan) != canonical_hash(approved)
        or not isinstance(approved_hash, str)
        or canonical_hash(approved) != approved_hash
        or (expected_plan_hash is not None and expected_plan_hash != approved_hash)
    ):
        raise IssueDeliveryOperationRefused("dispatch plan differs from approved Issue-delivery plan")


def _operation_record_id(operation_key: str, kind: str) -> str:
    if kind not in _RECORD_STATES:
        raise IssueDeliveryOperationRefused("unsupported destination receipt kind")
    return f"issue-delivery-{kind}:{operation_key}"


def _read_operation_record(
    client: _OperationClient,
    *,
    approval: Mapping[str, Any],
    repository: str,
    approval_id: str,
    operation_key: str,
    approval_manifest_hash: str,
    kind: str,
) -> dict[str, Any] | None:
    try:
        record = client.issue_delivery_operation_record_read(
            repository=repository,
            record_id=_operation_record_id(operation_key, kind),
        )
    except ControlPlaneNotFoundError:
        return None
    except ControlPlaneClientError as exc:
        raise IssueDeliveryOperationRefused("destination receipt lookup is unavailable") from exc
    if not isinstance(record, dict) or record.get("record_type") != "BuilderOpsReceipt":
        raise IssueDeliveryOperationRefused("destination receipt is malformed")
    payload = record.get("payload")
    if (
        not isinstance(payload, Mapping)
        or payload.get("repository") != repository
        or payload.get("operation_key") != operation_key
        or payload.get("approval_id") != approval_id
        or payload.get("approval_manifest_hash") != approval_manifest_hash
    ):
        raise IssueDeliveryOperationRefused("destination receipt is bound to another operation")
    allowed = {_RECORD_STATES[kind], "launch_unknown"} if kind == "terminal" else {_RECORD_STATES[kind]}
    if record.get("state") not in allowed:
        raise IssueDeliveryOperationRefused("destination receipt state is invalid")
    _record_hash(record)
    return record


def _valid_host_effect_refs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 5:
        raise IssueDeliveryOperationRefused("protected host effect references are malformed")
    refs: list[dict[str, str]] = []
    for ref in value:
        if (
            not isinstance(ref, Mapping)
            or set(ref) != {"operation_key", "request_sha256", "effect_slot_sha256"}
            or any(
                not isinstance(item, str) or _SHA256.fullmatch(item) is None
                for item in (
                    ref.get("operation_key"),
                    ref.get("request_sha256"),
                    ref.get("effect_slot_sha256"),
                )
            )
        ):
            raise IssueDeliveryOperationRefused("protected host effect references are malformed")
        refs.append(
            {
                "operation_key": str(ref["operation_key"]),
                "request_sha256": str(ref["request_sha256"]),
                "effect_slot_sha256": str(ref["effect_slot_sha256"]),
            }
        )
    if len({tuple(ref.values()) for ref in refs}) != len(refs):
        raise IssueDeliveryOperationRefused("protected host effect references are malformed")
    return refs


@dataclass(frozen=True)
class IssueDeliveryOperationObservation:
    """Authenticated durable operation state, gathered without preparation."""

    state: Literal["not_started", "reserved", "reconciliation_required", "active", "terminal", "launch_unknown"]
    run_id: str
    issue_number: int
    context_pack_id: str
    session_id: str | None = None
    worker_receipt: dict[str, Any] | None = None
    host_effect_refs: list[dict[str, str]] | None = None


def observe_issue_delivery_operation(
    approval: Mapping[str, Any],
    *,
    client: _OperationClient,
    plan: Mapping[str, Any],
    expected_plan_hash: str | None,
    repo_root: Path,
) -> IssueDeliveryOperationObservation:
    """Read one exact operation before any fresh destination preparation.

    Only authenticated 404s are absence.  Every other authority, transport or
    receipt-shape failure remains fail-closed rather than becoming a new launch.
    """

    value = _bound_issue_delivery_approval(
        approval, allow_legacy_normalization=False
    )
    destination = value["destination"]
    assert isinstance(destination, Mapping)
    configured_root = str(repo_root.absolute())
    approved_roots = {
        str(Path(str(destination[name])).absolute())
        for name in ("checkout", "worktree", "resolved_checkout", "resolved_worktree")
        if isinstance(destination.get(name), str)
    }
    if configured_root not in approved_roots:
        raise IssueDeliveryOperationRefused(
            "repo-root must equal the approved checkout or dedicated worktree"
        )
    _bind_dispatch_plan(value, plan, expected_plan_hash=expected_plan_hash)
    try:
        reply = client.issue_delivery_authority(manifest=value, purpose="readback")
    except ControlPlaneClientError as exc:
        raise IssueDeliveryOperationRefused("current Issue-delivery readback authority is unavailable") from exc
    repository = canonical_repository(str(value["repository"]))
    approval_id = str(value["approval_id"])
    operation_key = str(value["operation_key"])
    approval_manifest_hash = str(value["approval_manifest_hash"])
    if (
        not isinstance(reply, Mapping)
        or reply.get("approval") != value
        or reply.get("purpose") != "readback"
        or reply.get("operation_key") != operation_key
        or type(reply.get("authority_epoch")) is not int
    ):
        raise IssueDeliveryOperationRefused("current Issue-delivery readback authority does not match approval")
    issue = value.get("issue")
    context = value.get("context")
    approved_plan = context.get("dispatch_plan") if isinstance(context, Mapping) else None
    packs = approved_plan.get("context_packs") if isinstance(approved_plan, Mapping) else None
    if (
        not isinstance(issue, Mapping)
        or type(issue.get("number")) is not int
        or not isinstance(packs, list)
        or not isinstance(packs[0], Mapping)
        or not isinstance(packs[0].get("context_pack_id"), str)
        or not isinstance(destination.get("run_id"), str)
    ):
        raise IssueDeliveryOperationRefused("approved operation identity is incomplete")
    read = lambda kind: _read_operation_record(
        client,
        approval=value,
        repository=repository,
        approval_id=approval_id,
        operation_key=operation_key,
        approval_manifest_hash=approval_manifest_hash,
        kind=kind,
    )
    reservation = read("reservation")
    attempt = read("attempt")
    entry = read("entry")
    terminal = read("terminal")
    base = {
        "run_id": destination["run_id"],
        "issue_number": issue["number"],
        "context_pack_id": packs[0]["context_pack_id"],
    }
    if attempt is None:
        if entry is not None or terminal is not None:
            raise IssueDeliveryOperationRefused("destination receipt predecessor is missing")
        return IssueDeliveryOperationObservation(
            state="reserved" if reservation is not None else "not_started", **base
        )
    if reservation is None:
        raise IssueDeliveryOperationRefused("destination receipt predecessor is missing")
    attempt_payload = attempt["payload"]
    if (
        attempt_payload.get("attempt_id") != f"{operation_key}:attempt"
        or attempt_payload.get("reservation_receipt_hash") != _record_hash(reservation)
    ):
        raise IssueDeliveryOperationRefused("destination attempt receipt is malformed")
    if entry is not None:
        entry_payload = entry["payload"]
        session_id = entry_payload.get("session_id")
        if (
            entry_payload.get("attempt_id") != f"{operation_key}:attempt"
            or entry_payload.get("attempt_receipt_hash") != _record_hash(attempt)
            or not isinstance(session_id, str)
            or _SESSION.fullmatch(session_id) is None
        ):
            raise IssueDeliveryOperationRefused("destination entry receipt is malformed")
    if terminal is None:
        if entry is None:
            return IssueDeliveryOperationObservation(state="reconciliation_required", **base)
        return IssueDeliveryOperationObservation(
            state="active", session_id=str(entry["payload"]["session_id"]), **base
        )
    terminal_payload = terminal["payload"]
    if terminal_payload.get("attempt_receipt_hash") != _record_hash(attempt):
        raise IssueDeliveryOperationRefused("destination terminal receipt is malformed")
    refs = _valid_host_effect_refs(terminal_payload.get("host_effect_refs"))
    if terminal["state"] == "launch_unknown":
        if terminal_payload.get("worker_receipt") is not None:
            raise IssueDeliveryOperationRefused("launch-unknown receipt cannot claim a worker outcome")
        terminal_session_id = terminal_payload.get("session_id")
        if terminal_session_id is not None and (
            not isinstance(terminal_session_id, str)
            or _SESSION.fullmatch(terminal_session_id) is None
        ):
            raise IssueDeliveryOperationRefused("destination terminal session id is malformed")
        entry_session_id = None if entry is None else entry["payload"]["session_id"]
        if terminal_session_id is None:
            session_id = entry_session_id
        elif entry_session_id is not None and terminal_session_id != entry_session_id:
            raise IssueDeliveryOperationRefused("destination terminal session id conflicts with entry")
        else:
            session_id = terminal_session_id
        return IssueDeliveryOperationObservation(
            state="launch_unknown", session_id=session_id, host_effect_refs=refs, **base
        )
    worker_receipt = terminal_payload.get("worker_receipt")
    session_id = terminal_payload.get("session_id")
    if (
        entry is None
        or terminal_payload.get("entry_receipt_hash") != _record_hash(entry)
        or not isinstance(worker_receipt, Mapping)
        or _worker_supplies_host_effect_field(worker_receipt)
        or not isinstance(session_id, str)
        or _SESSION.fullmatch(session_id) is None
        or entry["payload"].get("session_id") != session_id
    ):
        raise IssueDeliveryOperationRefused("destination terminal receipt is malformed")
    return IssueDeliveryOperationObservation(
        state="terminal",
        session_id=session_id,
        worker_receipt=dict(worker_receipt),
        host_effect_refs=refs,
        **base,
    )


def _verify_workflow_root(approval: Mapping[str, Any], root: Path | None) -> list[dict[str, str]]:
    """Independently authenticate the protected hub checkout and pinned Git bytes."""
    from app.builderops.issue_delivery_effect_executor import _repository_from_remote

    if root is None or not root.is_absolute() or root.is_symlink():
        raise IssueDeliveryOperationRefused("explicit protected workflow root is required")
    root = root.resolve(strict=True)
    workflow = approval["workflow"]

    def git(*args: str) -> bytes:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
        if result.returncode:
            raise IssueDeliveryOperationRefused("trusted workflow Git identity is unavailable")
        return result.stdout

    if (Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != root
        or _repository_from_remote(git("remote", "get-url", "origin").decode().strip()) != workflow["repository"]
        or git("rev-parse", "HEAD").decode().strip() != workflow["source_revision"]
        or root == Path(approval["destination"]["checkout"]).resolve()):
        raise IssueDeliveryOperationRefused("trusted workflow repository or commit changed")
    artifacts = []
    for artifact in workflow["artifacts"]:
        path = root / artifact["path"]
        tree = git("ls-tree", workflow["source_revision"], "--", artifact["path"]).decode()
        if (not tree.startswith("100644 blob ") or not path.is_file() or path.is_symlink()
            or any(parent.is_symlink() for parent in path.parents if parent != root)):
            raise IssueDeliveryOperationRefused("trusted workflow artifact is non-regular or unavailable")
        digest = hashlib.sha256(git("show", f"{workflow['source_revision']}:{artifact['path']}")).hexdigest()
        if digest != artifact["sha256"] or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise IssueDeliveryOperationRefused("trusted workflow artifact differs from immutable pin")
        artifacts.append({"path": artifact["path"], "sha256": digest})
    return sorted(artifacts, key=lambda item: item["path"])


def _default_live_binding_reader(
    approval: Mapping[str, Any], *, trusted_workflow_root: Path | None = None,
) -> Mapping[str, Any]:
    """Re-read the approved checkout/worktree/Git/artifact identity."""

    destination = approval.get("destination")
    workflow = approval.get("workflow")
    source = approval.get("source")
    if not isinstance(destination, Mapping) or not isinstance(workflow, Mapping) or not isinstance(source, Mapping):
        raise IssueDeliveryOperationRefused("approved destination binding is incomplete")
    checkout = Path(str(destination["checkout"])).resolve()
    worktree = Path(str(destination["worktree"])).resolve()
    for raw_name, frozen_name, current in (
        ("checkout", "resolved_checkout", checkout),
        ("worktree", "resolved_worktree", worktree),
    ):
        frozen = destination.get(frozen_name)
        if frozen is not None and str(current) != str(frozen):
            raise IssueDeliveryOperationRefused(
                f"approved destination {raw_name} identity changed after approval"
            )
    if not checkout.is_dir() or not worktree.is_dir():
        raise IssueDeliveryOperationRefused("approved destination is unavailable")

    def git(path: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, check=False
        )
        if result.returncode or not result.stdout.strip():
            raise IssueDeliveryOperationRefused("approved destination Git identity is unavailable")
        return result.stdout.strip()

    if git(checkout, "rev-parse", "HEAD") != str(destination["base_sha"]):
        raise IssueDeliveryOperationRefused("destination checkout base changed after approval")
    if Path(git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
        raise IssueDeliveryOperationRefused("destination checkout repository identity changed")
    if Path(git(worktree, "rev-parse", "--show-toplevel")).resolve() != worktree:
        raise IssueDeliveryOperationRefused("destination worktree repository identity changed")
    branch = git(worktree, "symbolic-ref", "--short", "HEAD")
    if branch.removeprefix("refs/heads/") != str(destination["branch"]).removeprefix("refs/heads/"):
        raise IssueDeliveryOperationRefused("destination worktree branch changed after approval")
    common_checkout = Path(git(checkout, "rev-parse", "--git-common-dir"))
    common_worktree = Path(git(worktree, "rev-parse", "--git-common-dir"))
    if not common_checkout.is_absolute():
        common_checkout = checkout / common_checkout
    if not common_worktree.is_absolute():
        common_worktree = worktree / common_worktree
    if common_checkout.resolve() != common_worktree.resolve():
        raise IssueDeliveryOperationRefused("destination Git common-dir changed after approval")
    remote = git(checkout, "remote", "get-url", "origin")
    match = re.search(r"(?:github\.com[:/])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$", remote, re.I)
    try:
        remote_repository = canonical_repository(match.group(1)) if match is not None else None
        approved_repository = canonical_repository(str(approval["repository"]))
    except (TypeError, ValueError, EnvelopeValidationError) as exc:
        raise IssueDeliveryOperationRefused("approved destination repository remote identity is malformed") from exc
    if remote_repository != approved_repository:
        raise IssueDeliveryOperationRefused("destination repository remote identity changed")
    artifacts: list[dict[str, str]] = []
    for artifact in ([] if approval.get("contract_version") == SECOND_CONTRACT_VERSION else workflow.get("artifacts", [])):
        if not isinstance(artifact, Mapping):
            raise IssueDeliveryOperationRefused("approved workflow artifact is malformed")
        path = checkout / str(artifact["path"])
        if not path.is_file() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != checkout):
            raise IssueDeliveryOperationRefused("approved workflow artifact is unavailable")
        artifacts.append({"path": str(artifact["path"]), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    artifacts.sort(key=lambda item: item["path"])
    if approval.get("contract_version") == SECOND_CONTRACT_VERSION:
        artifacts = _verify_workflow_root(approval, trusted_workflow_root)
    return {
        "checkout": str(checkout),
        "worktree": str(worktree),
        "branch": str(destination["branch"]),
        "source_revision": str(source["revision"]),
        "base_sha": str(destination["base_sha"]),
        "workflow_hash": str(workflow["content_hash"]),
        "workflow_artifacts": artifacts,
        **({"delivery_sources": delivery_source_pair(approval)} if delivery_source_pair(approval) else {}),
    }


class IssueDeliveryOperationAdapter:
    """Launcher-shaped adapter for exactly one authenticated operation."""

    def __init__(
        self,
        approval: Mapping[str, Any],
        *,
        client: _OperationClient,
        launcher: IssueSessionLauncher | None = None,
        repo_root: Path | None = None,
        approval_file: Path | None = None,
        now: Callable[[], str] = _utc_now,
        live_binding_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        protected_executor: Any | None = None,
        require_protected_composition: bool = False,
    ) -> None:
        value = _bound_issue_delivery_approval(approval)
        self.approval = value
        self.client = client
        destination = value.get("destination")
        if not isinstance(destination, Mapping):
            raise IssueDeliveryOperationRefused("Issue-delivery destination is missing")
        admitted_binding = all(
            isinstance(destination.get(name), str)
            and bool(str(destination.get(name)).strip())
            for name in ("resolved_checkout", "resolved_worktree")
        )
        selected_root = repo_root
        if selected_root is None and launcher is not None:
            candidate = getattr(launcher, "repo_root", None)
            if isinstance(candidate, (Path, str)):
                selected_root = candidate if isinstance(candidate, Path) else Path(candidate)
        checkout_root = Path(
            str(destination["resolved_checkout"] if admitted_binding else destination["checkout"])
        )
        worktree_root = Path(
            str(destination["resolved_worktree"] if admitted_binding else destination["worktree"])
        )
        raw_checkout_root = Path(str(destination["checkout"]))
        raw_worktree_root = Path(str(destination["worktree"]))
        self.repo_root = selected_root or worktree_root
        if self.repo_root not in {
            checkout_root,
            worktree_root,
            raw_checkout_root,
            raw_worktree_root,
        }:
            raise IssueDeliveryOperationRefused("launcher repository root differs from approval")
        bound_launcher: IssueSessionLauncher
        if launcher is None:
            bound_launcher = CodexIssueSessionLauncher(
                repo_root=self.repo_root,
                effect_gate_approval_file=approval_file,
                effect_gate_checkout_root=checkout_root,
            )
        else:
            bound_launcher = launcher
            if approval_file is not None and isinstance(launcher, CodexIssueSessionLauncher):
                bound = getattr(launcher, "effect_gate_approval_file", None)
                if bound is None or bound.resolve() != approval_file.resolve():
                    raise IssueDeliveryOperationRefused("launcher approval binding differs from approval")
            elif approval_file is not None:
                nested = getattr(launcher, "launcher", None)
                bound = getattr(nested, "effect_gate_approval_file", None)
                if isinstance(nested, CodexIssueSessionLauncher) and (
                    not isinstance(bound, Path) or bound.resolve() != approval_file.resolve()
                ):
                    raise IssueDeliveryOperationRefused("launcher approval binding differs from approval")
        self.launcher = bound_launcher
        self.now = now
        self.live_binding_reader = live_binding_reader or _default_live_binding_reader
        self.protected_executor = protected_executor
        self.require_protected_composition = require_protected_composition
        if require_protected_composition:
            from app.builderops.issue_delivery_effect_executor import (
                ContentOnlyIssueDeliverySessionLauncher,
                IssueDeliveryHostExecutor,
                PreparedIssueDeliveryWorker,
            )

            if not isinstance(self.launcher, PreparedIssueDeliveryWorker):
                raise IssueDeliveryOperationRefused(
                    "production Issue delivery requires the prepared content-only launcher"
                )
            if not isinstance(
                self.launcher.launcher, ContentOnlyIssueDeliverySessionLauncher
            ):
                raise IssueDeliveryOperationRefused(
                    "production Issue delivery requires the isolated content-only launcher"
                )
            protected_executor = _require_protected_host_executor(protected_executor)
            if (
                live_binding_reader is None
                or getattr(live_binding_reader, "__self__", None)
                is not protected_executor
                or getattr(live_binding_reader, "__func__", None)
                is not IssueDeliveryHostExecutor.live_binding
            ):
                raise IssueDeliveryOperationRefused(
                    "production Issue delivery requires the protected host live-binding reader"
                )
        self.repository = canonical_repository(str(value["repository"]))
        self.approval_id = str(value["approval_id"])
        self.operation_key = str(value["operation_key"])
        self.approval_manifest_hash = str(value["approval_manifest_hash"])
        self.run_id = str(destination["run_id"])
        issue = value["issue"]
        self.destination_resource_key = destination_resource_key(
            self.repository, issue["number"], destination
        )

    @classmethod
    def from_env(cls, approval: Mapping[str, Any], **kwargs: Any) -> "IssueDeliveryOperationAdapter":
        client = BuilderOpsControlPlaneClient(ClientConfig.from_env(), max_retries=0)
        return cls(approval, client=client, **kwargs)

    def _require_launcher_binding(self) -> None:
        """A real child must carry the same committed approval into its gates."""

        launcher = self.launcher
        if not isinstance(launcher, CodexIssueSessionLauncher):
            nested = getattr(launcher, "launcher", None)
            if isinstance(nested, CodexIssueSessionLauncher):
                launcher = nested
            else:
                return
        path = getattr(launcher, "effect_gate_approval_file", None)
        if not isinstance(path, Path):
            raise IssueDeliveryOperationRefused("Issue-delivery launcher approval file is required")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IssueDeliveryOperationRefused("Issue-delivery launcher approval file is unavailable") from exc
        bound = document.get("approval", document) if isinstance(document, Mapping) else None
        if not isinstance(bound, Mapping) or dict(bound) != self.approval:
            raise IssueDeliveryOperationRefused("Issue-delivery launcher approval file differs from approval")

    def _default_target(self, effect: str | None = None) -> dict[str, Any]:
        destination = self.approval["destination"]
        issue = self.approval["issue"]
        target: dict[str, Any] = {
            "repository": tracking_repository(self.approval) if effect in {"issue_claim", "closure_reconciliation"} else self.repository,
            "issue_number": issue["number"],
            "checkout": str(Path(str(destination["checkout"])).resolve()),
            "worktree": str(Path(str(destination["worktree"])).resolve()),
            "branch": destination["branch"],
        }
        parent = self.approval.get("parent_evidence")
        if effect in {"issue_claim", "closure_reconciliation"} and isinstance(parent, Mapping) and parent.get("kind") == "issue":
            target["parent_repository"] = parent["repository"]
            target["parent_issue_number"] = parent["number"]
        return target

    def _validate_effect_target(
        self, effect: str, target: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        """Bind a concrete effect resource to the immutable approval.

        Owner wrappers may supply only the Issue resource for an Issue API
        call.  Every other field is inherited from the approved destination,
        while PR and parent bindings remain explicit for merge/closure.
        """

        if target is None:
            raise IssueDeliveryOperationRefused("effect target is required; targetless mutation is refused")
        if not isinstance(target, Mapping):
            raise IssueDeliveryOperationRefused("effect target binding is malformed")
        expected = self._default_target(effect)
        raw_target = dict(target)
        partial_resource_target = False
        if effect in {"issue_claim", "closure_reconciliation"} and raw_target and set(raw_target).issubset({"repository", "issue_number"}):
            if "issue_number" not in raw_target:
                raise IssueDeliveryOperationRefused("effect target Issue is required for mutation")
            if type(raw_target["issue_number"]) is not int:
                raise IssueDeliveryOperationRefused("effect target Issue must identify an existing Issue")
            partial_resource_target = True
            raw_target = {
                "repository": raw_target.get("repository", expected["repository"]),
                "issue_number": raw_target["issue_number"],
            }

        allowed = {
            "repository", "issue_number", "checkout", "worktree", "branch",
            "pr_number", "pr_repository", "pr_issue_number", "pr_head_ref",
            "pr_base_ref", "parent_repository", "parent_issue_number",
        }
        if set(raw_target) - allowed:
            raise IssueDeliveryOperationRefused("effect target binding contains unrelated fields")
        pr_fields = {
            "pr_number", "pr_repository", "pr_issue_number", "pr_head_ref", "pr_base_ref"
        }
        parent_fields = {"parent_repository", "parent_issue_number"}
        if effect not in {"review_merge", "closure_reconciliation"} and pr_fields & set(raw_target):
            raise IssueDeliveryOperationRefused("effect target binding contains unrelated fields")
        if effect not in {"issue_claim", "closure_reconciliation"} and parent_fields & set(raw_target):
            raise IssueDeliveryOperationRefused("effect target binding contains unrelated fields")
        try:
            target_repository = canonical_repository(str(raw_target.get("repository")))
        except (TypeError, ValueError, EnvelopeValidationError) as exc:
            raise IssueDeliveryOperationRefused("effect target repository is malformed") from exc
        if target_repository != expected["repository"]:
            raise IssueDeliveryOperationRefused("effect target repository differs from approval")
        if "issue_number" not in raw_target:
            raise IssueDeliveryOperationRefused("effect target Issue is required")
        issue_number = raw_target["issue_number"]
        if type(issue_number) is not int:
            raise IssueDeliveryOperationRefused("effect target Issue must identify an existing Issue")
        if issue_number != expected["issue_number"]:
            raise IssueDeliveryOperationRefused("effect target Issue differs from approval")
        for field in ("checkout", "worktree"):
            if field in raw_target:
                value = raw_target[field]
                if not isinstance(value, str) or Path(value).resolve() != Path(expected[field]).resolve():
                    raise IssueDeliveryOperationRefused(f"effect target {field} differs from approval")
            elif field == "worktree" and not partial_resource_target:
                # A full target is expected to carry the selected worktree;
                # the partial Issue form is the sole compatibility exception.
                raise IssueDeliveryOperationRefused("effect target worktree differs from approval")
        if "branch" in raw_target and raw_target["branch"] != expected["branch"]:
            raise IssueDeliveryOperationRefused("effect target branch differs from approval")
        elif "branch" not in raw_target and not partial_resource_target:
            raise IssueDeliveryOperationRefused("effect target branch differs from approval")

        parent = self.approval.get("parent_evidence")
        if effect in {"issue_claim", "closure_reconciliation"}:
            if isinstance(parent, Mapping) and parent.get("kind") == "issue":
                if "parent_repository" not in raw_target or "parent_issue_number" not in raw_target:
                    raw_target = {
                        **expected, **raw_target,
                        "parent_repository": parent["repository"],
                        "parent_issue_number": parent["number"],
                    }
                try:
                    parent_repo = canonical_repository(str(raw_target["parent_repository"]))
                except (TypeError, ValueError, EnvelopeValidationError) as exc:
                    raise IssueDeliveryOperationRefused("effect target parent repository is malformed") from exc
                if parent_repo != canonical_repository(str(parent["repository"])) or raw_target.get("parent_issue_number") != parent["number"]:
                    raise IssueDeliveryOperationRefused("effect target parent Issue differs from approval")
            elif "parent_repository" in raw_target or "parent_issue_number" in raw_target:
                raise IssueDeliveryOperationRefused("effect target parent Issue is not approved")

        if effect in {"review_merge", "closure_reconciliation"} and not partial_resource_target:
            if not pr_fields.issubset(raw_target):
                raise IssueDeliveryOperationRefused("effect target PR binding is incomplete")
            try:
                pr_repository = canonical_repository(str(raw_target["pr_repository"]))
            except (TypeError, ValueError, EnvelopeValidationError) as exc:
                raise IssueDeliveryOperationRefused("effect target PR repository is malformed") from exc
            if (
                type(raw_target["pr_number"]) is not int or raw_target["pr_number"] <= 0
                or pr_repository != self.repository
                or type(raw_target["pr_issue_number"]) is not int
                or raw_target["pr_issue_number"] != expected["issue_number"]
                or raw_target["pr_head_ref"] != expected["branch"]
                or raw_target["pr_base_ref"] != self.approval["destination"]["base_ref"]
            ):
                raise IssueDeliveryOperationRefused("effect target PR differs from approved destination")
        return {**expected, **raw_target} if partial_resource_target else dict(raw_target)

    def _live_binding(self, *, include_current_facts: bool = True) -> dict[str, Any]:
        destination = self.approval["destination"]
        workflow = self.approval["workflow"]
        if include_current_facts:
            checkout = Path(str(destination["checkout"])).resolve()
            worktree = Path(str(destination["worktree"])).resolve()
        else:
            # Entry/terminal are observations of the already admitted
            # process.  Their binding comes from the immutable approval; a
            # missing derived proof falls back to the stored legacy raw path,
            # never to an eager filesystem lookup.
            checkout = destination.get("resolved_checkout", destination.get("checkout"))
            worktree = destination.get("resolved_worktree", destination.get("worktree"))
            if not isinstance(checkout, str) or not isinstance(worktree, str):
                raise IssueDeliveryOperationRefused(
                    "immutable destination identity is unavailable"
                )
        expected_base: dict[str, Any] = {
            "checkout": str(checkout),
            "worktree": str(worktree),
            "branch": str(destination["branch"]),
            "source_revision": str(self.approval["source"]["revision"]),
            "base_sha": str(destination["base_sha"]),
            "workflow_hash": str(workflow["content_hash"]),
            "workflow_artifacts": sorted(
                [
                    {"path": str(item["path"]), "sha256": str(item["sha256"])}
                    for item in workflow["artifacts"]
                ],
                key=lambda item: item["path"],
            ),
        }
        if delivery_source_pair(self.approval):
            expected_base["delivery_sources"] = delivery_source_pair(self.approval)
        # Entry/terminal are observations of an already-started process.  Do
        # not re-read mutable paths, Git, artifacts, or current authority for
        # those receipts: their exact approval and predecessor hashes are
        # checked by the authenticated persistence owner instead.
        if not include_current_facts:
            return expected_base
        for raw_name, frozen_name in (("checkout", "resolved_checkout"), ("worktree", "resolved_worktree")):
            try:
                current_identity = Path(str(destination[raw_name])).resolve()
            except (OSError, RuntimeError) as exc:
                raise IssueDeliveryOperationRefused(
                    f"approved destination {raw_name} cannot be resolved"
                ) from exc
            frozen = destination.get(frozen_name, str(current_identity))
            if current_identity != Path(str(frozen)):
                raise IssueDeliveryOperationRefused(
                    f"approved destination {raw_name} identity changed after approval"
                )
        observed = dict(self.live_binding_reader(self.approval))
        # Protected composition adds fresh Issue/source/profile facts to the
        # same observation.  Compare the immutable destination binding as its
        # own exact field set first; comparing the entire mapping here would
        # reject every valid protected observation before its fresh facts can
        # be checked below.
        if any(observed.get(key) != value for key, value in expected_base.items()):
            raise IssueDeliveryOperationRefused("destination source or workflow binding changed")
        expected = dict(expected_base)
        if self.require_protected_composition and include_current_facts:
            issue = self.approval["issue"]
            source = self.approval["source"]
            profile = self.approval["profile"]
            current_issue = observed.get("current_issue")
            current_source = observed.get("current_source")
            current_profile = observed.get("current_profile")
            expected_issue = {
                "number": issue["number"],
                "node_id": issue["node_id"],
                "state": "open",
                "body_hash": issue["body_hash"],
                "acceptance_criteria_hash": issue["acceptance_criteria_hash"],
            }
            expected_source = {
                "revision": source["revision"],
                "refs": list(source.get("refs", [])),
            }
            expected_profile = dict(profile)
            if (
                not isinstance(current_issue, Mapping)
                or dict(current_issue) != expected_issue
                or not isinstance(current_source, Mapping)
                or dict(current_source) != expected_source
                or not isinstance(current_profile, Mapping)
                or dict(current_profile) != expected_profile
            ):
                raise IssueDeliveryOperationRefused(
                    "current Issue/source/profile facts do not match approval"
                )
            expected["current_issue"] = expected_issue
            expected["current_source"] = expected_source
            expected["current_profile"] = expected_profile
        return expected

    def _authority(self, effect: str, *, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if effect not in PERMITTED_EFFECTS:
            raise IssueDeliveryOperationRefused(f"effect is not permitted: {effect}")
        bound = self._validate_effect_target(effect, target)
        try:
            reply = self.client.issue_delivery_authority(manifest=self.approval, purpose="execute")
        except ControlPlaneClientError as exc:
            raise IssueDeliveryOperationRefused("current Issue-delivery authority is unavailable") from exc
        if reply.get("approval") != self.approval or reply.get("purpose") != "execute" or reply.get("operation_key") != self.operation_key or type(reply.get("authority_epoch")) is not int:
            raise IssueDeliveryOperationRefused("current Issue-delivery authority does not match approval")
        return {
            "effect": effect,
            "target": bound,
            "authority_epoch": reply["authority_epoch"],
            "observed_at": reply.get("observed_at"),
            "approval_manifest_hash": self.approval_manifest_hash,
            "live_binding": self._live_binding(),
        }

    def authorize_effect(self, effect: str, *, target: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Freshly recheck permission and destination before an owning effect."""

        return self._authority(effect, target=target)

    effect_gate = authorize_effect
    recheck_authority = authorize_effect

    def execute_effect(self, request: Any) -> Any:
        """Delegate a typed effect to the #5558 protected host executor."""

        try:
            protected_executor = _require_protected_host_executor(
                self.protected_executor
            )
        except IssueDeliveryOperationRefused as exc:
            raise IssueDeliveryOperationRefused(
                "protected host executor is unavailable"
            ) from exc
        from app.builderops.issue_delivery_effect_executor import IssueDeliveryEffectRequest

        if not isinstance(request, IssueDeliveryEffectRequest):
            raise IssueDeliveryOperationRefused(
                "Issue-delivery host effects require the typed effect request"
            )
        return protected_executor.execute(request)

    def _build_effect_request(
        self,
        proposal: Mapping[str, Any],
    ) -> Any:
        """Bind one closed typed proposal to host-owned exact fields."""

        if set(proposal) != {"effect_kind", "target"}:
            raise IssueDeliveryOperationRefused(
                "worker effect proposal must contain only effect_kind and target"
            )
        effect_kind = proposal.get("effect_kind")
        if effect_kind not in {"claim", "publication", "merge", "closure", "parent_evidence"}:
            raise IssueDeliveryOperationRefused("worker effect proposal kind is unsupported")
        target = proposal.get("target")
        if not isinstance(target, Mapping):
            raise IssueDeliveryOperationRefused("worker effect proposal target is malformed")
        from app.builderops.issue_delivery_effect_executor import (
            EffectDestination,
            IssueDeliveryEffectRequest,
            FrozenIssueDeliveryDestination,
        )

        frozen = getattr(self.launcher, "frozen_destination", None)
        if not isinstance(frozen, FrozenIssueDeliveryDestination):
            raise IssueDeliveryOperationRefused(
                "typed effect proposal requires the frozen host destination"
            )
        try:
            isolation = _require_protected_host_executor(
                self.protected_executor
            ).worker_isolation
        except (IssueDeliveryOperationRefused, ValueError) as exc:
            raise IssueDeliveryOperationRefused(
                "completed worker isolation receipt is unavailable"
            ) from exc
        destination = EffectDestination.model_validate(
            {
                "repository": self.repository,
                **frozen.binding.as_manifest(),
                "frozen_identity_sha256": frozen.identity_sha256,
            }
        )
        profile = self.approval.get("profile")
        verification = profile.get("verification_profile") if isinstance(profile, Mapping) else None
        workflow = self.approval.get("workflow")
        artifacts = {
            str(item.get("path")): str(item.get("sha256"))
            for item in workflow.get("artifacts", [])
            if isinstance(item, Mapping)
        } if isinstance(workflow, Mapping) else {}
        executor_artifact = "app/builderops/issue_delivery_effect_executor.py"
        isolation_artifact = "app/builderops/issue_delivery_worker_isolation.py"
        if executor_artifact not in artifacts or isolation_artifact not in artifacts:
            raise IssueDeliveryOperationRefused("approved effect executor artifacts are unavailable")
        request = IssueDeliveryEffectRequest.model_validate(
            {
                "contract": "builderops.issue-delivery-effect.v1",
                "effect_kind": effect_kind,
                "approval": self.approval,
                "approval_id": self.approval_id,
                "approved_operation_key": self.operation_key,
                "approval_manifest_hash": self.approval_manifest_hash,
                "repository": self.repository,
                "issue_number": self.approval["issue"]["number"],
                "issue_body_hash": self.approval["issue"]["body_hash"],
                "acceptance_criteria_hash": self.approval["issue"]["acceptance_criteria_hash"],
                "run_id": self.run_id,
                "source_revision": self.approval["source"]["revision"],
                "workflow_hash": self.approval["workflow"]["content_hash"],
                "profile_hash": self.approval["profile"]["content_hash"],
                "verification_profile_hash": verification["content_hash"]
                if isinstance(verification, Mapping)
                else None,
                "authority_epoch": self.approval["authority_epoch"],
                "destination": destination,
                "worker_isolation": isolation,
                "executor_artifact_sha256": artifacts[executor_artifact],
                "worker_isolation_artifact_sha256": artifacts[isolation_artifact],
                "target": target,
            }
        )
        return request

    def _host_claim_proposal(self) -> dict[str, Any]:
        """Build the sole claim target from immutable host-approved identity."""

        issue = self.approval["issue"]
        return {
            "effect_kind": "claim",
            "target": {
                "kind": "claim",
                "issue_number": issue["number"],
                "issue_node_id": issue["node_id"],
                "expected_state": "open",
                "expected_label": "agent:ready",
            },
        }

    def _execute_bound_effect(self, request: Any) -> tuple[dict[str, str], Any]:
        """Execute one host-built request and verify its durable ledger binding."""

        receipt = self.execute_effect(request)
        from app.builderops.issue_delivery_effect_executor import (
            IssueDeliveryEffectReceipt,
        )

        if not isinstance(receipt, IssueDeliveryEffectReceipt):
            raise IssueDeliveryOperationRefused(
                "protected host executor returned a malformed receipt"
            )
        protected_executor = _require_protected_host_executor(self.protected_executor)
        expected_operation_key = protected_executor.ledger.operation_key(
            effect_slot_sha256=request.effect_slot_sha256,
            effect_type={
                "claim": "github.issue-delivery.claim.v1",
                "publication": "github.issue-delivery.publication.v1",
                "merge": "github.issue-delivery.merge.v1",
                "closure": "github.issue-delivery.closure.v1",
                "parent_evidence": "github.issue-delivery.parent-evidence.v1",
            }[request.effect_kind],
        )
        status = protected_executor.ledger.status(receipt.operation_key)
        payload = status.get("payload")
        if (
            receipt.operation_key != expected_operation_key
            or receipt.request_sha256 != request.content_sha256
            or receipt.effect_kind != request.effect_kind
            or receipt.repository != self.repository
            or receipt.issue_number != self.approval["issue"]["number"]
            or status.get("operation_key") != expected_operation_key
            or not isinstance(payload, Mapping)
            or payload.get("contract") != "builderops.issue-delivery-effect.v1"
            or payload.get("request_sha256") != request.content_sha256
            or payload.get("effect_slot_sha256") != request.effect_slot_sha256
            or payload.get("approval_id") != self.approval_id
            or payload.get("approved_operation_key") != self.operation_key
            or payload.get("repository") != self.repository
            or payload.get("issue_number") != self.approval["issue"]["number"]
            or payload.get("run_id") != self.run_id
            or payload.get("effect_kind") != request.effect_kind
        ):
            raise IssueDeliveryOperationRefused(
                "protected host effect receipt is foreign or unbound"
            )
        return (
            {
                "operation_key": receipt.operation_key,
                "request_sha256": receipt.request_sha256,
                "effect_slot_sha256": request.effect_slot_sha256,
            },
            receipt,
        )

    def _execute_pre_entry_claim(self) -> dict[str, str]:
        """Require one host-owned, readback-confirmed claim before child entry."""

        request = self._build_effect_request(self._host_claim_proposal())
        self.authorize_effect(
            "issue_claim", target=self._default_target("issue_claim")
        )
        ref, receipt = self._execute_bound_effect(request)
        if receipt.outcome != "applied":
            raise IssueDeliveryOperationRefused(
                "pre-entry Issue claim was not readback-confirmed"
            )
        return ref

    def _execute_proposed_effects(
        self,
        worker_receipt: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        proposals = worker_receipt.get("effect_requests")
        if proposals is None:
            return []
        # One of the five durable host-reference slots is reserved for the
        # mandatory pre-entry claim; content-only worker proposals occupy the
        # remaining post-worker slots.
        if not isinstance(proposals, list) or len(proposals) > 4:
            raise IssueDeliveryOperationRefused("worker effect proposals are not a bounded list")
        refs: list[dict[str, str]] = []
        permission_by_kind = {
            "publication": "publication",
            "merge": "review_merge",
            "closure": "closure_reconciliation",
            "parent_evidence": "closure_reconciliation",
        }
        for raw_proposal in proposals:
            if not isinstance(raw_proposal, Mapping):
                raise IssueDeliveryOperationRefused("worker effect proposal is malformed")
            if raw_proposal.get("effect_kind") == "claim":
                raise IssueDeliveryOperationRefused(
                    "worker may not propose the host-owned Issue claim"
                )
            request = self._build_effect_request(dict(raw_proposal))
            if request.effect_kind != "parent_evidence":
                approval_path = getattr(self.launcher, "effect_gate_approval_file", None)
                nested_launcher = getattr(self.launcher, "launcher", None)
                if approval_path is None:
                    approval_path = getattr(
                        nested_launcher, "effect_gate_approval_file", None
                    )
                gate_target = self._default_target(
                    permission_by_kind[request.effect_kind]
                )
                typed_target = request.target.model_dump(mode="json")
                if request.effect_kind in {"merge", "closure"}:
                    gate_target.update(
                        {
                            "pr_number": typed_target.get("pr_number"),
                            "pr_repository": self.repository,
                            "pr_issue_number": self.approval["issue"]["number"],
                            "pr_head_ref": typed_target.get(
                                "branch", self.approval["destination"]["branch"]
                            ),
                            "pr_base_ref": typed_target.get(
                                "base_ref", self.approval["destination"]["base_ref"]
                            ),
                        }
                    )
                enforce_child_effect_gate(
                    permission_by_kind[request.effect_kind],
                    target=gate_target,
                    approval_path=approval_path,
                    adapter=self,
                )
            ref, receipt = self._execute_bound_effect(request)
            refs.append(ref)
            if receipt.outcome == "unknown":
                # An admitted transport may still complete.  Do not let a
                # later publication/merge/closure proposal run until this
                # exact effect has been independently reconciled.
                break
        return refs

    def bind_dispatch_plan(self, plan: Mapping[str, Any], *, expected_plan_hash: str | None = None) -> None:
        _bind_dispatch_plan(self.approval, plan, expected_plan_hash=expected_plan_hash)

    def _record_id(self, kind: str) -> str:
        return _operation_record_id(self.operation_key, kind)

    # Stable internal names retained for owner wrappers that classify the
    # target/receipt boundary explicitly.
    _default_effect_target = _default_target

    def _read(self, kind: str) -> dict[str, Any] | None:
        return _read_operation_record(
            self.client,
            approval=self.approval,
            repository=self.repository,
            approval_id=self.approval_id,
            operation_key=self.operation_key,
            approval_manifest_hash=self.approval_manifest_hash,
            kind=kind,
        )

    _read_record = _read

    def _write_with_ownership(
        self, kind: str, state: str, body: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        if state != _RECORD_STATES[kind] and not (kind == "terminal" and state == "launch_unknown"):
            raise IssueDeliveryOperationRefused("destination receipt state is invalid")
        payload = {
            "schema": f"builderops.issue-delivery-{kind}.v1",
            "repository": self.repository,
            "operation_type": OPERATION_TYPE,
            "operation_key": self.operation_key,
            "approval_id": self.approval_id,
            "approval_manifest_hash": self.approval_manifest_hash,
            "live_binding": self._live_binding(
                include_current_facts=kind in {"reservation", "attempt"}
            ),
            **dict(body),
        }
        payload["receipt_hash"] = _digest(payload)
        try:
            reply = self.client.issue_delivery_operation_record(
                envelope={"repository": self.repository, "scope": "issue-delivery-operation", "stack": "builderops-control-plane", "source_refs": [f"issue-delivery-approval:{self.approval_id}", f"operation:{self.operation_key}"]},
                record_id=self._record_id(kind),
                state=state,
                payload=payload,
                idempotency_key=f"issue-delivery-operation:{kind}:{self.operation_key}",
                operation_key=self.operation_key,
                approval_id=self.approval_id,
                approval_manifest_hash=self.approval_manifest_hash,
            )
        except ControlPlaneClientError as exc:
            existing = self._read(kind)
            if existing is not None:
                return existing, False
            raise IssueDeliveryOperationRefused("destination receipt was not durably committed") from exc
        if type(reply.get("replayed")) is not bool:
            raise IssueDeliveryOperationRefused("destination receipt commit response is malformed")
        existing = self._read(kind)
        if existing is None:
            raise IssueDeliveryOperationRefused("destination receipt commit has no authoritative readback")
        return existing, not reply["replayed"]

    def _write(self, kind: str, state: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._write_with_ownership(kind, state, body)[0]

    _write_record = _write

    def reserve(self) -> dict[str, Any]:
        existing = self._read("reservation")
        if existing is not None:
            return existing
        destination = dict(self.approval["destination"])
        self._authority("repository_worktree", target=self._default_target("repository_worktree"))
        return self._write(
            "reservation",
            "reserved",
            {
                "destination": destination,
                "destination_resource_key": self.destination_resource_key,
                "issue_number": self.approval["issue"]["number"],
                "proposed_run": {"run_id": self.run_id},
                "reserved_at": self.now(),
            },
        )

    def _record_attempt(self) -> tuple[dict[str, Any], bool]:
        reservation = self.reserve()
        existing = self._read("attempt")
        if existing is not None:
            return existing, False
        reservation_payload = reservation.get("payload")
        destination_resource_key = (
            reservation_payload.get("destination_resource_key")
            if isinstance(reservation_payload, Mapping)
            else None
        )
        if not isinstance(destination_resource_key, str) or len(destination_resource_key) != 64:
            raise IssueDeliveryOperationRefused(
                "destination reservation resource identity is malformed"
            )
        body = {
            "reservation_receipt_hash": _record_hash(reservation),
            "attempt_id": f"{self.operation_key}:attempt",
            "destination_resource_key": destination_resource_key,
            "attempted_at": self.now(),
        }
        return self._write_with_ownership("attempt", "attempted", body)

    def record_attempt(self) -> dict[str, Any]:
        return self._record_attempt()[0]

    def record_entry(self, *, session_id: str, state: str = "active") -> dict[str, Any]:
        if not isinstance(session_id, str) or _SESSION.fullmatch(session_id.strip()) is None:
            raise IssueDeliveryOperationRefused("observed session id is malformed")
        attempt = self._read("attempt")
        if attempt is None:
            raise IssueDeliveryOperationRefused(
                "destination attempt receipt is required before entry observation"
            )
        existing = self._read("entry")
        if existing is not None:
            if existing["payload"].get("session_id") != session_id:
                raise IssueDeliveryOperationRefused("destination entry is bound to another session")
            return existing
        attempt_payload = attempt.get("payload")
        destination_resource_key = (
            attempt_payload.get("destination_resource_key")
            if isinstance(attempt_payload, Mapping)
            else None
        )
        if not isinstance(destination_resource_key, str) or len(destination_resource_key) != 64:
            raise IssueDeliveryOperationRefused("destination attempt resource identity is malformed")
        return self._write("entry", state, {"attempt_receipt_hash": _record_hash(attempt), "attempt_id": f"{self.operation_key}:attempt", "destination_resource_key": destination_resource_key, "session_id": session_id, "entered_at": self.now()})

    def record_terminal(
        self,
        *,
        session_id: str | None,
        worker_receipt: Mapping[str, Any] | None,
        host_effect_refs: list[dict[str, str]] | None = None,
        state: str = "terminal",
    ) -> dict[str, Any]:
        existing = self._read("terminal")
        if existing is not None:
            return existing
        if worker_receipt is not None and _worker_supplies_host_effect_field(worker_receipt):
            raise IssueDeliveryOperationRefused(
                "worker receipt must not supply protected host effect fields"
            )
        attempt = self._read("attempt")
        if attempt is None:
            raise IssueDeliveryOperationRefused(
                "destination attempt receipt is required before terminal observation"
            )
        entry = self._read("entry")
        if state == "terminal" and entry is None:
            raise IssueDeliveryOperationRefused("terminal receipt requires an observed entry")
        terminal_worker_receipt = (
            dict(worker_receipt) if worker_receipt is not None else None
        )
        attempt_payload = attempt.get("payload")
        destination_resource_key = (
            attempt_payload.get("destination_resource_key")
            if isinstance(attempt_payload, Mapping)
            else None
        )
        if not isinstance(destination_resource_key, str) or len(destination_resource_key) != 64:
            raise IssueDeliveryOperationRefused("destination attempt resource identity is malformed")
        refs = _valid_host_effect_refs(list(host_effect_refs or []))
        return self._write("terminal", state, {"attempt_receipt_hash": _record_hash(attempt), "destination_resource_key": destination_resource_key, "entry_receipt_hash": _record_hash(entry) if state == "terminal" and entry is not None else None, "session_id": session_id, "worker_receipt": terminal_worker_receipt, "host_effect_refs": refs, "observed_at": self.now()})

    def _selected_context(self, context_pack: Mapping[str, Any]) -> None:
        context = self.approval["context"]
        plan = context["dispatch_plan"]
        selected = plan["context_packs"]
        if not isinstance(selected, list) or len(selected) != 1 or canonical_hash(selected[0]) != canonical_hash(context_pack):
            raise IssueDeliveryOperationRefused("launch context differs from approved context")

    def launch(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
        on_entry: Callable[[str], None] | None = None,
        effect_gate: Callable[..., Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        if execution_routing is not None:
            raise IssueDeliveryOperationRefused("Issue-delivery adapter does not permit canary routing")
        self._selected_context(context_pack)
        terminal = self._read("terminal")
        entry = self._read("entry")
        if terminal is not None:
            if terminal.get("state") != "terminal":
                raise IssueDeliveryOperationError("existing launch is unresolved; replacement launch is forbidden", session_id=(entry or {}).get("payload", {}).get("session_id"))
            payload = terminal["payload"]
            reservation = self._read("reservation")
            attempt = self._read("attempt")
            return {
                "session_id": payload.get("session_id"),
                "worker_receipt": payload.get("worker_receipt"),
                "host_effect_refs": payload.get("host_effect_refs"),
                "operation_state": "terminal",
                "fresh_session": False,
                "stop_support": "unsupported",
                "reservation_receipt_hash": _record_hash(reservation) if reservation else None,
                "attempt_receipt_hash": _record_hash(attempt) if attempt else None,
                "entry_receipt_hash": _record_hash(entry) if entry else None,
            }
        if entry is not None:
            raise IssueDeliveryOperationError("existing active launch requires reconciliation; relaunch is forbidden", session_id=entry["payload"].get("session_id"))
        if self._read("attempt") is not None:
            raise IssueDeliveryOperationError("existing launch attempt has no observed entry; replacement launch is forbidden")
        self._require_launcher_binding()
        self.reserve()
        _attempt, owns_attempt = self._record_attempt()
        if not owns_attempt:
            raise IssueDeliveryOperationError("another dispatcher owns the launch attempt; reconciliation is required")
        pre_entry_host_refs: list[dict[str, str]] = []
        try:
            def observe_entry(session_id: str) -> None:
                self.record_entry(session_id=session_id)
                if on_entry is not None:
                    on_entry(session_id)

            def gate(effect: str, *, target: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
                result = self.authorize_effect(effect, target=target)
                if effect_gate is not None:
                    effect_gate(effect, target=target)
                return result

            launch_kwargs: dict[str, Any] = {
                "on_entry": observe_entry,
                "effect_gate": gate,
            }
            if self.require_protected_composition:
                protected_executor = _require_protected_host_executor(
                    self.protected_executor
                )

                def pre_process_entry() -> None:
                    protected_executor.bind_completed_worker()
                    pre_entry_host_refs.append(self._execute_pre_entry_claim())

                launch_kwargs["pre_process_entry"] = pre_process_entry
                launch_kwargs["pre_spawn_entry"] = lambda: self._authority(
                    "repository_worktree",
                    target=self._default_target("repository_worktree"),
                )
            result = self.launcher.launch(context_pack, **launch_kwargs)
            if not isinstance(result, Mapping):
                raise IssueDeliveryOperationError("launcher returned a non-object result")
            session_id = result.get("session_id")
            if not isinstance(session_id, str) or _SESSION.fullmatch(session_id.strip()) is None:
                self.record_terminal(
                    session_id=None,
                    worker_receipt=None,
                    host_effect_refs=pre_entry_host_refs,
                    state="launch_unknown",
                )
                raise IssueDeliveryOperationError("launcher returned no observed session entry")
            entry = self.record_entry(session_id=session_id)
            receipt = result.get("worker_receipt")
            if isinstance(receipt, Mapping):
                if _worker_supplies_host_effect_field(receipt):
                    raise IssueDeliveryOperationRefused(
                        "worker receipt must not supply protected host effect fields"
                    )
                host_effect_refs = (
                    [
                        *pre_entry_host_refs,
                        *self._execute_proposed_effects(receipt),
                    ]
                    if receipt.get("effect_requests") is not None
                    else pre_entry_host_refs
                )
                self.record_terminal(
                    session_id=session_id,
                    worker_receipt=receipt,
                    host_effect_refs=host_effect_refs,
                )
                # Keep the returned dispatch result aligned with the durable
                # terminal observation.  Callers must be able to inspect the
                # protected host receipts without performing a second local
                # reconstruction; the control plane remains authoritative.
                result = {
                    **dict(result),
                    "worker_receipt": receipt,
                    "host_effect_refs": host_effect_refs,
                }
            reservation = self._read("reservation")
            attempt = self._read("attempt")
            return {
                **dict(result),
                "operation_state": "terminal" if isinstance(receipt, Mapping) else "active",
                "fresh_session": True,
                "stop_support": "unsupported",
                "reservation_receipt_hash": _record_hash(reservation) if reservation else None,
                "attempt_receipt_hash": _record_hash(attempt) if attempt else None,
                "entry_receipt_hash": _record_hash(entry),
            }
        except IssueDeliveryOperationError:
            raise
        except Exception as exc:
            session_id = getattr(exc, "session_id", None)
            if not isinstance(session_id, str) or _SESSION.fullmatch(session_id.strip()) is None:
                session_id = None
            if session_id is not None:
                try:
                    self.record_entry(session_id=session_id)
                except IssueDeliveryOperationError as entry_exc:
                    raise IssueDeliveryOperationError("launcher response was lost and entry observation is unavailable", session_id=session_id) from entry_exc
            try:
                self.record_terminal(
                    session_id=session_id,
                    worker_receipt=None,
                    host_effect_refs=pre_entry_host_refs,
                    state="launch_unknown",
                )
            except IssueDeliveryOperationError as terminal_exc:
                raise IssueDeliveryOperationError("launcher outcome is ambiguous; destination reconciliation is required", session_id=session_id) from terminal_exc
            raise IssueDeliveryOperationError("launcher outcome is ambiguous; replacement launch is forbidden", session_id=session_id) from exc

    def stop(self) -> dict[str, str]:
        return {"stop_support": "unsupported", "stop_status": "unsupported"}


def enforce_child_effect_gate(
    effect: str,
    *,
    target: Mapping[str, Any] | None = None,
    approval_path: Path | None = None,
    adapter: IssueDeliveryOperationAdapter | None = None,
) -> None:
    """Recheck an effect through the already-bound authenticated adapter.

    The worker may carry an approval-file path only as a binding witness.  It
    must never cause this seam to construct a second ambient-environment
    client: the adapter's injected authenticated client and live reader are
    the effect authority for the whole launch.
    """

    if adapter is None:
        raise IssueDeliveryOperationRefused(
            "child Issue-delivery gate requires the bound host adapter"
        )
    try:
        if approval_path is not None:
            adapter._require_launcher_binding()
        adapter.authorize_effect(effect, target=target)
    except IssueDeliveryOperationError:
        raise
    except Exception as exc:
        raise IssueDeliveryOperationRefused("child Issue-delivery authority is unavailable") from exc


__all__ = [
    "IssueDeliveryOperationAdapter",
    "IssueDeliveryOperationError",
    "IssueDeliveryOperationRefused",
    "enforce_child_effect_gate",
    "_default_live_binding_reader",
]
