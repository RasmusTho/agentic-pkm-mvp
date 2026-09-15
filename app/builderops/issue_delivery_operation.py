"""Authenticated destination adapter for the first Issue-delivery operation.

FCA-ID-A owns admission.  This module owns only the destination side of the
same operation: it records a reservation, one pre-launch attempt, and the
separate observed Codex entry through the existing BuilderOps receipt owner.
It never creates a worker, queue, store, or fallback route of its own.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneClientError,
    ControlPlaneNotFoundError,
)
from app.builderops.control_plane.issue_delivery import (
    CONTRACT_VERSION,
    OPERATION_TYPE,
    PERMITTED_EFFECTS,
    canonical_hash,
    manifest_hash,
)
from app.builderops.control_plane.models import EnvelopeValidationError, canonical_repository
from app.builderops.epic_dispatch import (
    CodexIssueSessionLauncher,
    IssueSessionLauncher,
)


class IssueDeliveryOperationError(RuntimeError):
    """A destination operation is unavailable or must remain unresolved."""

    def __init__(self, message: str, *, session_id: str | None = None) -> None:
        self.session_id = session_id
        super().__init__(message)


class IssueDeliveryOperationRefused(IssueDeliveryOperationError):
    """A stale, changed, or unsupported operation cannot cross an effect gate."""


def enforce_child_effect_gate(
    effect: str,
    target: Mapping[str, Any] | None = None,
) -> None:
    """Synchronously re-authorize a child-owned lifecycle effect.

    The destination launcher exports only the non-secret path to the committed
    approval.  Existing owner wrappers call this function immediately before
    their external mutation, so a worker cannot turn a stale parent preflight into
    continuing authority.  With no exported approval this is a no-op for all
    existing non-issue-delivery workflows.
    """

    approval_path = os.environ.get("BUILDEROPS_ISSUE_DELIVERY_APPROVAL_FILE", "").strip()
    if not approval_path:
        return
    if effect not in PERMITTED_EFFECTS:
        raise IssueDeliveryOperationRefused(
            f"effect is not permitted by the approved Issue operation: {effect}"
        )
    try:
        document = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IssueDeliveryOperationRefused(
            "child Issue-delivery approval is unavailable"
        ) from exc
    approval = document.get("approval", document) if isinstance(document, Mapping) else None
    if not isinstance(approval, Mapping):
        raise IssueDeliveryOperationRefused("child Issue-delivery approval is malformed")
    client = BuilderOpsControlPlaneClient(ClientConfig.from_env(), max_retries=0)
    try:
        destination = approval.get("destination")
        checkout = (
            Path(str(destination["checkout"]))
            if isinstance(destination, Mapping) and destination.get("checkout")
            else Path.cwd()
        )
        adapter = IssueDeliveryOperationAdapter(
            approval,
            client=client,
            repo_root=checkout,
        )
        adapter.authorize_effect(effect, target=target)
    except IssueDeliveryOperationError:
        raise
    except Exception as exc:
        raise IssueDeliveryOperationRefused(
            "child Issue-delivery authority is unavailable"
        ) from exc
    finally:
        client.close()


def _default_live_binding_reader(approval: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read the destination checkout and approved workflow artifacts locally."""

    destination = approval["destination"]
    checkout = Path(str(destination["checkout"])).resolve()
    if str(checkout) != str(destination["resolved_checkout"]):
        raise IssueDeliveryOperationRefused(
            "approved destination checkout identity changed after approval"
        )
    worktree = Path(str(destination["worktree"])).resolve()
    if str(worktree) != str(destination["resolved_worktree"]):
        raise IssueDeliveryOperationRefused(
            "approved destination worktree identity changed after approval"
        )
    if not checkout.is_dir():
        raise IssueDeliveryOperationRefused(
            "approved destination checkout is unavailable for live binding"
        )
    git = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if git.returncode != 0 or git.stdout.strip() != str(destination["base_sha"]):
        raise IssueDeliveryOperationRefused(
            "destination checkout base changed after approval"
        )
    workflow = approval["workflow"]
    artifacts = workflow["artifacts"]
    observed_artifacts: list[dict[str, str]] = []
    for artifact in artifacts:
        path = checkout / str(artifact["path"])
        if (
            not path.is_file()
            or path.is_symlink()
            or any(parent.is_symlink() for parent in path.parents if parent != checkout)
        ):
            raise IssueDeliveryOperationRefused(
                "approved workflow artifact is unavailable for live binding"
            )
        observed_artifacts.append(
            {
                "path": str(artifact["path"]),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    observed_artifacts.sort(key=lambda item: item["path"])
    return {
        "checkout": str(checkout),
        "worktree": str(worktree),
        "branch": str(destination["branch"]),
        "source_revision": str(approval["source"]["revision"]),
        "base_sha": str(destination["base_sha"]),
        "workflow_hash": str(workflow["content_hash"]),
        "workflow_artifacts": observed_artifacts,
    }


class _OperationClient(Protocol):
    def issue_delivery_authority(
        self,
        *,
        manifest: Mapping[str, Any],
        purpose: str,
        path: str = "/v1/issue-delivery/authority",
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
        path: str = "/v1/issue-delivery/operation-record",
    ) -> dict[str, Any]: ...

    def issue_delivery_operation_record_read(
        self, *, repository: str, record_id: str
    ) -> dict[str, Any]: ...


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECORD_KINDS = {
    "reservation": "reserved",
    "attempt": "attempted",
    "entry": "active",
    "terminal": "terminal",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _text(value: Any, name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise IssueDeliveryOperationRefused(f"{name} is required")
    return value.strip()


def _record_hash(record: Mapping[str, Any]) -> str:
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise IssueDeliveryOperationRefused("destination receipt payload is malformed")
    declared = payload.get("receipt_hash")
    if not isinstance(declared, str) or not _SHA256.fullmatch(declared):
        raise IssueDeliveryOperationRefused("destination receipt hash is missing")
    without_hash = {key: value for key, value in payload.items() if key != "receipt_hash"}
    if _json_hash(without_hash) != declared:
        raise IssueDeliveryOperationRefused("destination receipt hash is corrupt")
    return declared


class IssueDeliveryOperationAdapter:
    """Run exactly one approved Issue through the existing Codex launcher.

    The adapter is intentionally a launcher-shaped object, so
    ``dispatch_issue_sessions`` can use it without growing another execution
    engine.  ``launcher`` remains the existing ``CodexIssueSessionLauncher``;
    only the destination receipts and current effect gates are added around
    it.
    """

    def __init__(
        self,
        approval: Mapping[str, Any],
        *,
        client: _OperationClient,
        launcher: IssueSessionLauncher | None = None,
        repo_root: Path | None = None,
        now: Callable[[], str] = _utc_now,
        live_binding_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.approval = self._validate_approval(approval)
        self.client = client
        if repo_root is not None:
            selected_root = repo_root
        elif launcher is not None:
            candidate_root = getattr(launcher, "repo_root", Path.cwd())
            selected_root = (
                candidate_root
                if isinstance(candidate_root, Path)
                else Path(str(candidate_root))
            )
        else:
            selected_root = Path.cwd()
        self.launcher = launcher or CodexIssueSessionLauncher(repo_root=selected_root)
        self.repo_root = selected_root.resolve()
        destination = self.approval["destination"]
        if self.repo_root != Path(destination["resolved_checkout"]):
            raise IssueDeliveryOperationRefused(
                "launcher repository root differs from approved destination checkout"
            )
        context = self.approval["context"]
        dispatch_plan = context["dispatch_plan"]
        context_pack = dispatch_plan["context_packs"][0]
        worktree_plan = context_pack["branch_worktree_plan"]
        if (
            dispatch_plan["run_id"] != destination["run_id"]
            or worktree_plan["branch"] != destination["branch"]
            or worktree_plan["worktree"] != destination["worktree"]
            or Path(destination["worktree"]).resolve()
            != Path(destination["resolved_worktree"])
        ):
            raise IssueDeliveryOperationRefused(
                "approved context and destination are not bound to one run"
            )
        self.now = now
        self.repository = canonical_repository(self.approval["repository"])
        self.approval_id = self.approval["approval_id"]
        self.operation_key = self.approval["operation_key"]
        self.approval_manifest_hash = self.approval["approval_manifest_hash"]
        self.destination_identity = destination["identity"]
        self.run_id = destination["run_id"]
        self.live_binding_reader = live_binding_reader or _default_live_binding_reader

    @classmethod
    def from_env(
        cls,
        approval: Mapping[str, Any],
        *,
        launcher: IssueSessionLauncher | None = None,
        repo_root: Path | None = None,
    ) -> "IssueDeliveryOperationAdapter":
        return cls(
            approval,
            client=BuilderOpsControlPlaneClient(ClientConfig.from_env(), max_retries=0),
            launcher=launcher,
            repo_root=repo_root,
        )

    @staticmethod
    def _validate_approval(approval: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(approval, Mapping):
            raise IssueDeliveryOperationRefused("committed Issue-delivery approval is required")
        value = dict(approval)
        if value.get("contract_version") != CONTRACT_VERSION or value.get("operation_type") != OPERATION_TYPE:
            raise IssueDeliveryOperationRefused("unsupported Issue-delivery approval")
        for name in ("repository", "approval_id", "operation_key", "approval_manifest_hash"):
            _text(value.get(name), name)
        if not _ID.fullmatch(str(value["approval_id"])) or not _ID.fullmatch(str(value["operation_key"])):
            raise IssueDeliveryOperationRefused("Issue-delivery identity is malformed")
        try:
            canonical_repository(str(value["repository"]))
        except (TypeError, ValueError, EnvelopeValidationError) as exc:
            raise IssueDeliveryOperationRefused(
                "Issue-delivery repository identity is malformed"
            ) from exc
        if not _SHA256.fullmatch(str(value["approval_manifest_hash"])):
            raise IssueDeliveryOperationRefused("Issue-delivery approval hash is malformed")
        if manifest_hash(value) != value["approval_manifest_hash"]:
            raise IssueDeliveryOperationRefused("Issue-delivery approval hash is corrupt")
        destination = value.get("destination")
        if not isinstance(destination, Mapping):
            raise IssueDeliveryOperationRefused("Issue-delivery destination is missing")
        for name in (
            "identity",
            "run_id",
            "checkout",
            "resolved_checkout",
            "worktree",
            "resolved_worktree",
            "branch",
            "base_ref",
        ):
            _text(destination.get(name), f"destination {name}", limit=1024)
        for raw_name, frozen_name in (
            ("checkout", "resolved_checkout"),
            ("worktree", "resolved_worktree"),
        ):
            try:
                resolved = Path(str(destination[raw_name])).resolve()
            except (OSError, RuntimeError) as exc:
                raise IssueDeliveryOperationRefused(
                    f"destination {raw_name} cannot be resolved"
                ) from exc
            if resolved != Path(str(destination[frozen_name])):
                raise IssueDeliveryOperationRefused(
                    f"destination {frozen_name} does not match approved identity"
                )
        if destination.get("branch", "").removeprefix("refs/heads/") == destination.get("base_ref", "").removeprefix("refs/heads/"):
            raise IssueDeliveryOperationRefused("destination branch must be isolated from base ref")
        context = value.get("context")
        if not isinstance(context, Mapping):
            raise IssueDeliveryOperationRefused("Issue-delivery context is missing")
        dispatch_plan = context.get("dispatch_plan")
        packs = dispatch_plan.get("context_packs") if isinstance(dispatch_plan, Mapping) else None
        if (
            not isinstance(dispatch_plan, Mapping)
            or not isinstance(dispatch_plan.get("run_id"), str)
            or not isinstance(packs, list)
            or len(packs) != 1
            or not isinstance(packs[0], Mapping)
            or not isinstance(packs[0].get("branch_worktree_plan"), Mapping)
        ):
            raise IssueDeliveryOperationRefused(
                "approval does not bind one complete context pack"
            )
        worktree_plan = packs[0]["branch_worktree_plan"]
        for name in ("branch", "worktree"):
            _text(worktree_plan.get(name), f"context worktree plan {name}", limit=1024)
        if set(value.get("permitted_effects", ())) != set(PERMITTED_EFFECTS):
            raise IssueDeliveryOperationRefused("Issue-delivery effect grant is incomplete")
        return value

    def _default_effect_target(self, effect: str) -> dict[str, Any]:
        destination = self.approval["destination"]
        issue = self.approval["issue"]
        target: dict[str, Any] = {
            "repository": self.repository,
            "issue_number": issue["number"],
            "checkout": str(destination["resolved_checkout"]),
            "worktree": str(destination["resolved_worktree"]),
            "branch": destination["branch"],
        }
        parent = self.approval.get("parent_evidence")
        if effect == "closure_reconciliation" and isinstance(parent, Mapping) and parent.get("kind") == "issue":
            target["parent_repository"] = parent["repository"]
            target["parent_issue_number"] = parent["number"]
        return target

    def _validate_effect_target(
        self,
        effect: str,
        target: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Bind a concrete owner effect to the approved Issue destination."""

        expected = self._default_effect_target(effect)
        if target is None:
            return expected
        if not isinstance(target, Mapping):
            raise IssueDeliveryOperationRefused("effect target binding is malformed")
        mutation_target: tuple[str, int] | None = None
        mutation_repository: str | None = None
        partial_resource_target = False
        raw_target = dict(target)
        if effect == "closure_reconciliation" and set(raw_target).issubset(
            {"repository", "issue_number"}
        ) and raw_target:
            # Boundary classifiers may know only the exact GitHub mutation
            # target (for example an Issue comment endpoint); the immutable
            # checkout/branch binding still comes from the approval.  Keep the
            # context binding in the ordinary target fields while checking
            # the mutation resource separately below.
            partial_resource_target = True
            raw_mutation_repository = raw_target.get("repository", expected["repository"])
            mutation_issue = raw_target.get("issue_number")
            if "issue_number" not in raw_target:
                raise IssueDeliveryOperationRefused(
                    "effect target Issue is required for closure mutation"
                )
            if isinstance(raw_mutation_repository, str):
                mutation_repository = raw_mutation_repository
                if type(mutation_issue) is int:
                    mutation_target = (raw_mutation_repository, mutation_issue)
            target = {
                **expected,
                "repository": expected["repository"],
                "issue_number": expected["issue_number"],
            }
        allowed = {
            "repository",
            "issue_number",
            "checkout",
            "worktree",
            "branch",
            "pr_number",
            "pr_repository",
            "pr_issue_number",
            "pr_head_ref",
            "pr_base_ref",
            "parent_repository",
            "parent_issue_number",
        }
        if set(target) - allowed:
            raise IssueDeliveryOperationRefused("effect target binding contains unrelated fields")
        try:
            target_repository = canonical_repository(str(target.get("repository")))
        except (TypeError, ValueError, EnvelopeValidationError) as exc:
            raise IssueDeliveryOperationRefused(
                "effect target repository is malformed"
            ) from exc
        if target_repository != expected["repository"]:
            raise IssueDeliveryOperationRefused("effect target repository differs from approval")
        if type(target.get("issue_number")) is not int or target["issue_number"] != expected["issue_number"]:
            raise IssueDeliveryOperationRefused("effect target Issue differs from approval")
        if "checkout" in target:
            value = target["checkout"]
            if (
                not isinstance(value, str)
                or Path(value).resolve() != Path(expected["checkout"]).resolve()
            ):
                raise IssueDeliveryOperationRefused(
                    "effect target checkout differs from approval"
                )
        for field in ("worktree",):
            value = target.get(field)
            if not isinstance(value, str) or Path(value).resolve() != Path(expected[field]).resolve():
                raise IssueDeliveryOperationRefused(
                    f"effect target {field} differs from approval"
                )
        if target.get("branch") != expected["branch"]:
            raise IssueDeliveryOperationRefused("effect target branch differs from approval")
        parent = self.approval.get("parent_evidence")
        if effect == "closure_reconciliation":
            if isinstance(parent, Mapping) and parent.get("kind") == "issue":
                if "parent_repository" not in target or "parent_issue_number" not in target:
                    # Existing closure owner wrappers do not know the parent
                    # fields independently; bind them to the committed
                    # approval while still rejecting any caller-supplied drift.
                    target = {
                        **dict(expected),
                        **dict(target),
                        "parent_repository": parent["repository"],
                        "parent_issue_number": parent["number"],
                    }
                if (
                    target.get("parent_repository") != parent["repository"]
                    or target.get("parent_issue_number") != parent["number"]
                ):
                    raise IssueDeliveryOperationRefused(
                        "effect target parent Issue differs from approval"
                    )
            elif "parent_repository" in target or "parent_issue_number" in target:
                raise IssueDeliveryOperationRefused(
                    "effect target parent Issue is not approved"
                )
            if mutation_target is not None:
                try:
                    canonical_mutation_repository = canonical_repository(mutation_target[0])
                except (TypeError, ValueError, EnvelopeValidationError) as exc:
                    raise IssueDeliveryOperationRefused(
                        "effect target mutation repository is malformed"
                    ) from exc
                effect_issue = mutation_target[1]
                approved_targets = {(expected["repository"], expected["issue_number"])}
                if isinstance(parent, Mapping) and parent.get("kind") == "issue":
                    approved_targets.add((parent["repository"], parent["number"]))
                if (
                    (canonical_mutation_repository, effect_issue) not in approved_targets
                ):
                    raise IssueDeliveryOperationRefused(
                        "effect target mutation Issue differs from approved closure targets"
                    )
            elif mutation_repository is not None:
                try:
                    canonical_mutation_repository = canonical_repository(mutation_repository)
                except (TypeError, ValueError, EnvelopeValidationError) as exc:
                    raise IssueDeliveryOperationRefused(
                        "effect target mutation repository is malformed"
                    ) from exc
                if canonical_mutation_repository != expected["repository"]:
                    raise IssueDeliveryOperationRefused(
                        "effect target mutation repository differs from approval"
                    )
        if effect in {"review_merge", "closure_reconciliation"} and not partial_resource_target:
            pr_fields = {
                "pr_number",
                "pr_repository",
                "pr_issue_number",
                "pr_head_ref",
                "pr_base_ref",
            }
            if not pr_fields.issubset(target):
                raise IssueDeliveryOperationRefused(
                    "effect target PR binding is incomplete"
                )
            try:
                target_pr_repository = canonical_repository(str(target["pr_repository"]))
            except (TypeError, ValueError, EnvelopeValidationError) as exc:
                raise IssueDeliveryOperationRefused(
                    "effect target PR repository is malformed"
                ) from exc
            if (
                type(target["pr_number"]) is not int
                or target["pr_number"] <= 0
                or target_pr_repository != expected["repository"]
                or type(target["pr_issue_number"]) is not int
                or target["pr_issue_number"] != expected["issue_number"]
                or target["pr_head_ref"] != expected["branch"]
                or target["pr_base_ref"] != self.approval["destination"]["base_ref"]
            ):
                raise IssueDeliveryOperationRefused(
                    "effect target PR differs from approved destination"
                )
        return dict(target)

    def _authority(
        self,
        effect: str,
        *,
        target: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if effect not in PERMITTED_EFFECTS:
            raise IssueDeliveryOperationRefused(
                f"effect is not permitted by the approved Issue operation: {effect}"
            )
        target_binding = self._validate_effect_target(effect, target)
        try:
            reply = self.client.issue_delivery_authority(
                manifest=self.approval, purpose="execute"
            )
        except ControlPlaneClientError as exc:
            raise IssueDeliveryOperationRefused(
                "current Issue-delivery authority is unavailable"
            ) from exc
        if (
            reply.get("approval") != self.approval
            or reply.get("purpose") != "execute"
            or reply.get("operation_key") != self.operation_key
            or type(reply.get("authority_epoch")) is not int
            or not isinstance(reply.get("observed_at"), str)
        ):
            raise IssueDeliveryOperationRefused(
                "current Issue-delivery authority does not match approval"
            )
        live_binding = self._live_binding()
        return {
            "effect": effect,
            "authority_epoch": reply["authority_epoch"],
            "observed_at": reply["observed_at"],
            "approval_manifest_hash": self.approval_manifest_hash,
            "live_binding": live_binding,
            "target": target_binding,
        }

    def _live_binding(self) -> dict[str, Any]:
        destination = self.approval["destination"]
        for raw_name, frozen_name in (
            ("checkout", "resolved_checkout"),
            ("worktree", "resolved_worktree"),
        ):
            try:
                current_identity = Path(str(destination[raw_name])).resolve()
            except (OSError, RuntimeError) as exc:
                raise IssueDeliveryOperationRefused(
                    f"approved destination {raw_name} cannot be resolved"
                ) from exc
            if current_identity != Path(str(destination[frozen_name])):
                raise IssueDeliveryOperationRefused(
                    f"approved destination {raw_name} identity changed after approval"
                )
        observed = self.live_binding_reader(self.approval)
        expected_destination = destination
        expected_workflow = self.approval["workflow"]
        observed_artifacts: list[dict[str, str]] = [
            {
                "path": str(artifact["path"]),
                "sha256": str(artifact["sha256"]),
            }
            for artifact in expected_workflow["artifacts"]
        ]
        observed_artifacts.sort(key=lambda item: item["path"])
        expected = {
            "checkout": str(expected_destination["resolved_checkout"]),
            "worktree": str(expected_destination["resolved_worktree"]),
            "branch": str(expected_destination["branch"]),
            "source_revision": str(self.approval["source"]["revision"]),
            "base_sha": str(expected_destination["base_sha"]),
            "workflow_hash": str(expected_workflow["content_hash"]),
            "workflow_artifacts": observed_artifacts,
        }
        if dict(observed) != expected:
            raise IssueDeliveryOperationRefused(
                "destination source or workflow binding changed after approval"
            )
        return expected

    def authorize_effect(
        self,
        effect: str,
        *,
        target: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Recheck fresh permission before a real repository effect."""

        return self._authority(effect, target=target)

    # Alias used by effect owners that call this a gate rather than an
    # authorization check.
    effect_gate = authorize_effect
    recheck_authority = authorize_effect

    def bind_dispatch_plan(
        self,
        plan: Mapping[str, Any],
        *,
        expected_plan_hash: str | None = None,
    ) -> None:
        """Require dispatch to consume the plan frozen by FCA-ID-A.

        The launcher receives only a context pack, so checking that pack at
        launch time is not sufficient to prevent a caller from replacing the
        surrounding run or selected Issue.  Compare the complete plan before
        any reservation or attempt receipt is written.
        """

        approved_context = self.approval.get("context")
        approved_plan = (
            approved_context.get("dispatch_plan")
            if isinstance(approved_context, Mapping)
            else None
        )
        if not isinstance(approved_plan, Mapping):
            raise IssueDeliveryOperationRefused(
                "approval does not contain one frozen dispatch plan"
            )
        if canonical_hash(plan) != canonical_hash(approved_plan):
            raise IssueDeliveryOperationRefused(
                "dispatch plan differs from approved Issue-delivery plan"
            )
        approved_plan_hash = (
            approved_context.get("expected_plan_hash")
            if isinstance(approved_context, Mapping)
            else None
        )
        if (
            not isinstance(approved_plan_hash, str)
            or canonical_hash(approved_plan) != approved_plan_hash
        ):
            raise IssueDeliveryOperationRefused(
                "approved dispatch plan hash is missing or corrupt"
            )
        if expected_plan_hash is not None and expected_plan_hash != approved_plan_hash:
            raise IssueDeliveryOperationRefused(
                "dispatch plan hash differs from approved Issue-delivery plan"
            )

    def _record_id(self, kind: str) -> str:
        if kind not in _RECORD_KINDS:
            raise IssueDeliveryOperationRefused("unsupported destination receipt kind")
        return f"issue-delivery-{kind}:{self.operation_key}"

    def _read_record(self, kind: str) -> dict[str, Any] | None:
        record_id = self._record_id(kind)
        try:
            record = self.client.issue_delivery_operation_record_read(
                repository=self.repository, record_id=record_id
            )
        except ControlPlaneNotFoundError:
            return None
        except ControlPlaneClientError as exc:
            # A missing response is not a negative lookup.  Preserve
            # reconciliation-needed state so a retry cannot launch twice.
            raise IssueDeliveryOperationRefused(
                "destination receipt lookup is unavailable"
            ) from exc
        if not isinstance(record, dict):
            raise IssueDeliveryOperationRefused("destination receipt lookup is malformed")
        self._assert_record_binding(record, kind)
        return record

    def _assert_record_binding(self, record: Mapping[str, Any], kind: str) -> None:
        payload = record.get("payload")
        if (
            record.get("record_type") != "BuilderOpsReceipt"
            or record.get("state") not in {
                _RECORD_KINDS[kind],
                "launch_unknown" if kind == "terminal" else _RECORD_KINDS[kind],
            }
            or not isinstance(payload, Mapping)
            or payload.get("repository") != self.repository
            or payload.get("operation_key") != self.operation_key
            or payload.get("approval_id") != self.approval_id
            or payload.get("approval_manifest_hash") != self.approval_manifest_hash
        ):
            raise IssueDeliveryOperationRefused(
                "destination receipt is bound to a different operation"
            )
        _record_hash(record)

    def _write_record(
        self,
        kind: str,
        state: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        if state != _RECORD_KINDS[kind] and not (
            kind == "terminal" and state == "launch_unknown"
        ):
            raise IssueDeliveryOperationRefused("destination receipt state is invalid")
        self._authority("repository_worktree" if kind in {"reservation", "attempt"} else "closure_reconciliation")
        payload = {
            "schema": f"builderops.issue-delivery-{kind}.v1",
            "repository": self.repository,
            "operation_type": OPERATION_TYPE,
            "operation_key": self.operation_key,
            "approval_id": self.approval_id,
            "approval_manifest_hash": self.approval_manifest_hash,
            "live_binding": self._live_binding(),
            **dict(body),
        }
        payload["receipt_hash"] = _json_hash(payload)
        try:
            reply = self.client.issue_delivery_operation_record(
                envelope={
                    "repository": self.repository,
                    "scope": "issue-delivery-operation",
                    "stack": "builderops-control-plane",
                    "source_refs": [
                        f"issue-delivery-approval:{self.approval_id}",
                        f"operation:{self.operation_key}",
                    ],
                },
                record_id=self._record_id(kind),
                state=state,
                payload=payload,
                idempotency_key=f"issue-delivery-operation:{kind}:{self.operation_key}",
                operation_key=self.operation_key,
                approval_id=self.approval_id,
                approval_manifest_hash=self.approval_manifest_hash,
            )
        except ControlPlaneClientError as exc:
            # A concurrent writer may have committed the exact record while
            # this request was in flight.  Re-read the destination-owned
            # record before surfacing failure; an unavailable lookup remains
            # unresolved and must never be interpreted as permission to retry.
            try:
                existing = self._read_record(kind)
            except IssueDeliveryOperationError:
                existing = None
            if existing is not None:
                return existing
            raise IssueDeliveryOperationRefused(
                "destination receipt was not durably committed"
            ) from exc
        if type(reply.get("replayed")) is not bool:
            raise IssueDeliveryOperationRefused(
                "destination receipt commit response is missing replay ownership"
            )
        record = self._read_record(kind)
        if record is None:
            raise IssueDeliveryOperationRefused(
                "destination receipt commit has no authoritative readback"
            )
        return record

    def _write_record_with_ownership(
        self,
        kind: str,
        state: str,
        body: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Return a receipt and whether this caller created its idempotency key."""

        # Keep the public record helper stable while retaining the service's
        # replay bit for the one race where two dispatchers pass the negative
        # lookup before either external launch.
        existing_before = self._read_record(kind)
        if existing_before is not None:
            return existing_before, False
        record_id = self._record_id(kind)
        if state != _RECORD_KINDS[kind] and not (
            kind == "terminal" and state == "launch_unknown"
        ):
            raise IssueDeliveryOperationRefused("destination receipt state is invalid")
        self._authority(
            "repository_worktree"
            if kind in {"reservation", "attempt"}
            else "closure_reconciliation"
        )
        payload = {
            "schema": f"builderops.issue-delivery-{kind}.v1",
            "repository": self.repository,
            "operation_type": OPERATION_TYPE,
            "operation_key": self.operation_key,
            "approval_id": self.approval_id,
            "approval_manifest_hash": self.approval_manifest_hash,
            **dict(body),
        }
        payload["receipt_hash"] = _json_hash(payload)
        try:
            reply = self.client.issue_delivery_operation_record(
                envelope={
                    "repository": self.repository,
                    "scope": "issue-delivery-operation",
                    "stack": "builderops-control-plane",
                    "source_refs": [
                        f"issue-delivery-approval:{self.approval_id}",
                        f"operation:{self.operation_key}",
                    ],
                },
                record_id=record_id,
                state=state,
                payload=payload,
                idempotency_key=f"issue-delivery-operation:{kind}:{self.operation_key}",
                operation_key=self.operation_key,
                approval_id=self.approval_id,
                approval_manifest_hash=self.approval_manifest_hash,
            )
        except ControlPlaneClientError as exc:
            existing = self._read_record(kind)
            if existing is not None:
                return existing, False
            raise IssueDeliveryOperationRefused(
                "destination receipt was not durably committed"
            ) from exc
        if type(reply.get("replayed")) is not bool:
            raise IssueDeliveryOperationRefused(
                "destination receipt commit response is missing replay ownership"
            )
        record = self._read_record(kind)
        if record is None:
            raise IssueDeliveryOperationRefused(
                "destination receipt commit has no authoritative readback"
            )
        return record, not reply["replayed"]

    def reserve(self) -> dict[str, Any]:
        """Reserve the proposed destination/run exactly once."""

        self._authority("repository_worktree")
        existing = self._read_record("reservation")
        if existing is not None:
            return existing
        destination = dict(self.approval["destination"])
        return self._write_record(
            "reservation",
            "reserved",
            {
                "destination": destination,
                "proposed_run": {"run_id": self.run_id},
                "reserved_at": self.now(),
            },
        )

    def record_attempt(self) -> dict[str, Any]:
        """Persist one unique attempt before crossing the launcher boundary."""

        record, _fresh = self._record_attempt()
        return record

    def _record_attempt(self) -> tuple[dict[str, Any], bool]:
        reservation = self.reserve()
        existing = self._read_record("attempt")
        if existing is not None:
            return existing, False
        reservation_hash = _record_hash(reservation)
        return self._write_record_with_ownership(
            "attempt",
            "attempted",
            {
                "reservation_receipt_hash": reservation_hash,
                "attempt_id": f"{self.operation_key}:attempt",
                "attempted_at": self.now(),
                # Attempt ownership is an authority-bearing write too.  Bind
                # the observed checkout/workflow to it before the service
                # accepts the receipt, just as for reservation/entry writes.
                "live_binding": self._live_binding(),
            },
        )

    def record_entry(
        self,
        *,
        session_id: str,
        state: str = "active",
    ) -> dict[str, Any]:
        """Persist the actual observed Codex process/session independently."""

        session_id = _text(session_id, "observed session id", limit=256)
        attempt = self.record_attempt()
        existing = self._read_record("entry")
        if existing is not None:
            payload = existing["payload"]
            if payload.get("session_id") != session_id:
                raise IssueDeliveryOperationRefused(
                    "destination entry is bound to another session"
                )
            return existing
        return self._write_record(
            "entry",
            state,
            {
                "attempt_receipt_hash": _record_hash(attempt),
                "attempt_id": attempt["payload"]["attempt_id"],
                "session_id": session_id,
                "entered_at": self.now(),
            },
        )

    def record_terminal(
        self,
        *,
        session_id: str | None,
        worker_receipt: Mapping[str, Any] | None,
        state: str = "terminal",
    ) -> dict[str, Any]:
        """Record a terminal or launch-unknown observation without stop claims."""

        existing = self._read_record("terminal")
        if existing is not None:
            return existing
        entry = self._read_record("entry")
        attempt = self.record_attempt()
        return self._write_record(
            "terminal",
            state,
            {
                "attempt_receipt_hash": _record_hash(attempt),
                # A launch-unknown outcome proves only the attempt and any
                # separately observed entry.  It must not claim that entry as
                # a verified terminal predecessor; the service rejects that
                # combination by design.
                "entry_receipt_hash": (
                    None
                    if state == "launch_unknown"
                    else _record_hash(entry) if entry is not None else None
                ),
                "session_id": session_id,
                "worker_receipt": dict(worker_receipt) if worker_receipt is not None else None,
                "observed_at": self.now(),
            },
        )

    def launch(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Reserve, attempt, observe entry, then delegate to the existing launcher."""

        if execution_routing is not None:
            raise IssueDeliveryOperationRefused("Issue-delivery adapter does not permit canary routing")
        selected = self.approval.get("context", {}).get("dispatch_plan", {}).get("context_packs", [])
        if not isinstance(selected, list) or len(selected) != 1:
            raise IssueDeliveryOperationRefused("approval does not bind one context pack")
        if canonical_hash(selected[0]) != canonical_hash(context_pack):
            raise IssueDeliveryOperationRefused("launch context differs from approved context")

        terminal = self._read_record("terminal")
        entry = self._read_record("entry")
        if terminal is not None:
            state = terminal.get("state")
            if state != "terminal":
                raise IssueDeliveryOperationError(
                    "existing launch is unresolved; replacement launch is forbidden",
                    session_id=(entry or {}).get("payload", {}).get("session_id"),
                )
            terminal_payload = terminal.get("payload", {})
            return {
                "session_id": terminal_payload.get("session_id") or (entry or {}).get("payload", {}).get("session_id"),
                "worker_receipt": terminal_payload.get("worker_receipt"),
                "operation_state": "terminal",
                "reservation_receipt_hash": _record_hash(self._read_record("reservation") or {}),
                "attempt_receipt_hash": _record_hash(self._read_record("attempt") or {}),
                "entry_receipt_hash": _record_hash(entry) if entry is not None else None,
                "stop_support": "unsupported",
                "fresh_session": False,
            }
        if entry is not None:
            raise IssueDeliveryOperationError(
                "existing active launch requires destination reconciliation; relaunch is forbidden",
                session_id=entry.get("payload", {}).get("session_id"),
            )
        # An attempt is the point after which the launcher boundary may have
        # been crossed.  If entry/terminal observation is missing, preserve the
        # ambiguity and require reconciliation instead of treating the attempt
        # as a harmless preflight artifact and launching a second worker.
        attempt = self._read_record("attempt")
        if attempt is not None:
            raise IssueDeliveryOperationError(
                "existing launch attempt has no observed entry; replacement launch is forbidden"
            )

        self.reserve()
        _attempt, owns_attempt = self._record_attempt()
        if not owns_attempt:
            raise IssueDeliveryOperationError(
                "another dispatcher owns the launch attempt; reconciliation is required"
            )
        try:
            def observe_entry(observed_session_id: str) -> None:
                self.record_entry(session_id=observed_session_id)

            result = self.launcher.launch(
                context_pack,
                on_entry=observe_entry,
                effect_gate=self.authorize_effect,
            )
            if not isinstance(result, Mapping):
                raise IssueDeliveryOperationError("existing launcher returned a non-object result")
            session_id = result.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                self.record_terminal(session_id=None, worker_receipt=None, state="launch_unknown")
                raise IssueDeliveryOperationError("launcher returned no observed session entry")
            entry = self.record_entry(session_id=session_id)
            worker_receipt = result.get("worker_receipt")
            if isinstance(worker_receipt, Mapping):
                self.record_terminal(session_id=session_id, worker_receipt=worker_receipt)
            return {
                **dict(result),
                "operation_state": "terminal" if isinstance(worker_receipt, Mapping) else "active",
                "fresh_session": True,
                "reservation_receipt_hash": _record_hash(self._read_record("reservation") or {}),
                "attempt_receipt_hash": _record_hash(self._read_record("attempt") or {}),
                "entry_receipt_hash": _record_hash(entry),
                "stop_support": "unsupported",
            }
        except IssueDeliveryOperationError:
            raise
        except Exception as exc:
            session_id = getattr(exc, "session_id", None)
            if not isinstance(session_id, str) or not session_id.strip():
                session_id = None
            if session_id is not None:
                try:
                    self.record_entry(session_id=session_id)
                except IssueDeliveryOperationError as entry_exc:
                    raise IssueDeliveryOperationError(
                        "launcher response was lost and entry observation is unavailable",
                        session_id=session_id,
                    ) from entry_exc
            try:
                self.record_terminal(
                    session_id=session_id,
                    worker_receipt=None,
                    state="launch_unknown",
                )
            except IssueDeliveryOperationError as terminal_exc:
                raise IssueDeliveryOperationError(
                    "launcher outcome is ambiguous; destination reconciliation is required",
                    session_id=session_id,
                ) from terminal_exc
            raise IssueDeliveryOperationError(
                "launcher outcome is ambiguous; replacement launch is forbidden",
                session_id=session_id,
            ) from exc

    def stop(self) -> dict[str, str]:
        """The selected launcher has no stop/control API."""

        return {"stop_support": "unsupported", "stop_status": "unsupported"}


__all__ = [
    "IssueDeliveryOperationAdapter",
    "IssueDeliveryOperationError",
    "IssueDeliveryOperationRefused",
    "enforce_child_effect_gate",
]


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Recheck one Issue-delivery effect gate")
    parser.add_argument("--effect", choices=sorted(PERMITTED_EFFECTS), required=True)
    parser.add_argument("--target-json", help="JSON object identifying the concrete effect target")
    parser.add_argument("--repository")
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--worktree")
    parser.add_argument("--branch")
    args = parser.parse_args()
    target: Mapping[str, Any] | None = None
    if args.target_json is not None:
        if any(
            value is not None
            for value in (args.repository, args.issue_number, args.worktree, args.branch)
        ):
            raise SystemExit("--target-json cannot be combined with scalar target options")
        try:
            parsed = json.loads(args.target_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--target-json must be valid JSON: {exc}") from exc
        if not isinstance(parsed, Mapping):
            raise SystemExit("--target-json must contain an object")
        target = parsed
    elif any(
        value is not None
        for value in (args.repository, args.issue_number, args.worktree, args.branch)
    ):
        if None in (args.repository, args.issue_number, args.worktree, args.branch):
            raise SystemExit(
                "--repository, --issue-number, --worktree, and --branch are required together"
            )
        target = {
            "repository": args.repository,
            "issue_number": args.issue_number,
            "worktree": args.worktree,
            "branch": args.branch,
        }
    enforce_child_effect_gate(args.effect, target=target)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
