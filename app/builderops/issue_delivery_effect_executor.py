"""Host-fenced Git and GitHub effects for one approved Issue delivery.

The Issue worker is a content-only process running through the distinct Linux
principal contract in :mod:`issue_delivery_worker_isolation`.  It can propose
one of the closed request types below, but only this host-side executor can
claim the existing BuilderOps outbox intent, resolve a repository-scoped host
credential, invoke an effect transport, and reconcile source readback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ControlPlaneNotFoundError,
)
from app.builderops.control_plane.issue_delivery import (
    CANDIDATE_CONTRACT_VERSION, TWO_SOURCE_VERSIONS, delivery_source_pair,
    tracking_repository, workflow_artifacts,
)
from app.builderops.control_plane.models import canonical_repository
from app.builderops.issue_delivery_worker_isolation import (
    ISOLATION_RECEIPT_CONTRACT,
    LinuxSystemdCodexIssueSessionLauncher,
    reobserve_worker_completion,
)
from app.dispatcher.verification_merge import (
    BuilderOpsOutboxExecutor,
    HostCredentialResolver,
    ProtectedDeliveryManifest,
)

CONTRACT = "builderops.issue-delivery-effect.v1"
WORKER_BINDING_CONTRACT: Literal["builderops.issue-delivery-worker-binding.v1"] = (
    "builderops.issue-delivery-worker-binding.v1"
)
EXECUTOR_ARTIFACT = "app/builderops/issue_delivery_effect_executor.py"
WORKER_ISOLATION_ARTIFACT = "app/builderops/issue_delivery_worker_isolation.py"
_HEX_40 = r"^[0-9a-f]{40}$"
_HEX_64 = r"^[0-9a-f]{64}$"
_EFFECT_TYPES = {
    "candidate_prepare": "git.issue-delivery.candidate-prepare.v1",
    "claim": "github.issue-delivery.claim.v1",
    "publication": "github.issue-delivery.publication.v1",
    "merge": "github.issue-delivery.merge.v1",
    "closure": "github.issue-delivery.closure.v1",
    "parent_evidence": "github.issue-delivery.parent-evidence.v1",
}
_PERMISSIONS = {
    "candidate_prepare": "repository_worktree",
    "claim": "issue_claim",
    "publication": "publication",
    "merge": "review_merge",
    "closure": "closure_reconciliation",
    "parent_evidence": "closure_reconciliation",
}
_READBACK_CLAIM_FIELDS = frozenset(
    {
        "repository",
        "operation_key",
        "worker_id",
        "fencing_token",
        "intent_lsn",
        "claim_lsn",
        "receipt_sequence",
        "expires_at",
        "effect_type",
        "payload",
    }
)
_EFFECT_CLAIM_IDENTITY_FIELDS = frozenset(
    {
        "repository",
        "operation_key",
        "worker_id",
        "fencing_token",
        "intent_lsn",
        "claim_lsn",
        "receipt_sequence",
        "expires_at",
        "task_id",
        "effect_type",
    }
)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        resolved = path.resolve(strict=True)
        if resolved != path or not resolved.is_file():
            raise ValueError("trusted Issue-delivery artifact is unavailable")
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("trusted Issue-delivery artifact is unavailable") from exc


def _safe_receipt_value(value: object) -> None:
    """Keep durable payloads and returned receipts free of raw secrets/paths."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in {
                "checkout",
                "worktree",
                "local_path",
                "secret",
                "password",
                "token",
                "authorization",
                "credential",
                "credential_value",
                "private_key",
            }:
                raise ValueError(
                    "Issue-delivery receipt contains a secret or local path"
                )
            _safe_receipt_value(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _safe_receipt_value(child)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkerIsolationBinding(_StrictModel):
    """Non-secret proof that the proposing child used the #5559 boundary."""

    contract: Literal["builderops.issue-delivery-worker-binding.v1"] = (
        WORKER_BINDING_CONTRACT
    )
    isolation_contract: Literal["builderops_issue_delivery_worker_isolation_receipt.v1"]
    profile_id: str = Field(min_length=1, max_length=64)
    profile_version: Literal[1]
    profile_sha256: str = Field(pattern=_HEX_64)
    receipt_sha256: str = Field(pattern=_HEX_64)
    executor_uid: int = Field(ge=0)
    executor_gid: int = Field(ge=0)
    worker_uid: int = Field(gt=0)
    worker_gid: int = Field(gt=0)
    worker_supplementary_gids: tuple[int, ...]
    repository_credential_probe: Literal["denied"]
    worker_write_access_probe: Literal["worktree-writable-git-denied"]
    git_metadata_write_denied: Literal[True]
    no_new_privileges: Literal[True]
    worktree_identity_sha256: str = Field(pattern=_HEX_64)
    executable_set_identity_sha256: str = Field(pattern=_HEX_64)
    command_sha256: str = Field(pattern=_HEX_64)
    isolation_properties_sha256: str = Field(pattern=_HEX_64)

    @model_validator(mode="after")
    def _distinct_principal(self) -> "WorkerIsolationBinding":
        if self.worker_uid == self.executor_uid or self.worker_gid == self.executor_gid:
            raise ValueError("Issue-delivery worker requires a distinct OS principal")
        if self.worker_supplementary_gids:
            raise ValueError("Issue-delivery worker supplementary groups must be empty")
        return self

    @classmethod
    def from_receipt(cls, receipt: Mapping[str, Any]) -> "WorkerIsolationBinding":
        executor = receipt.get("executor")
        worker = receipt.get("worker")
        if receipt.get("contract") != ISOLATION_RECEIPT_CONTRACT:
            raise ValueError("Issue-delivery worker isolation receipt is unsupported")
        if not isinstance(executor, Mapping) or not isinstance(worker, Mapping):
            raise ValueError("Issue-delivery worker OS principals are unavailable")
        if receipt.get("git_metadata_write_denied") is not True:
            raise ValueError("Issue-delivery worker Git metadata denial is unproven")
        if receipt.get("probe_result") != "denied":
            raise ValueError("Issue-delivery repository credential denial is unproven")
        if receipt.get("worker_write_access_probe_result") != (
            "worktree-writable-git-denied"
        ):
            raise ValueError("Issue-delivery content-only write boundary is unproven")
        return cls(
            isolation_contract=ISOLATION_RECEIPT_CONTRACT,
            profile_id=receipt.get("profile_id"),
            profile_version=receipt.get("profile_version"),
            profile_sha256=receipt.get("profile_sha256"),
            receipt_sha256=_canonical_hash(dict(receipt)),
            executor_uid=executor.get("uid"),
            executor_gid=executor.get("gid"),
            worker_uid=worker.get("uid"),
            worker_gid=worker.get("gid"),
            worker_supplementary_gids=tuple(worker.get("supplementary_gids", ())),
            repository_credential_probe=receipt.get("probe_result"),
            worker_write_access_probe=receipt.get("worker_write_access_probe_result"),
            git_metadata_write_denied=receipt.get("git_metadata_write_denied"),
            no_new_privileges=receipt.get("no_new_privileges"),
            worktree_identity_sha256=receipt.get("worktree_identity_sha256"),
            executable_set_identity_sha256=receipt.get(
                "executable_set_identity_sha256"
            ),
            command_sha256=receipt.get("command_sha256"),
            isolation_properties_sha256=receipt.get("isolation_properties_sha256"),
        )


class DestinationBinding(_StrictModel):
    identity: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=256)
    host_identity: str = Field(min_length=1, max_length=256)
    system_identity: str = Field(min_length=1, max_length=256)
    channel: str = Field(min_length=1, max_length=64)
    repository: str
    checkout: Path
    worktree: Path
    branch: str = Field(min_length=1, max_length=512)
    base_ref: str = Field(min_length=1, max_length=256)
    base_sha: str = Field(pattern=_HEX_40)

    @field_validator("repository")
    @classmethod
    def _repository(cls, value: str) -> str:
        return canonical_repository(value)

    @model_validator(mode="after")
    def _paths_and_refs(self) -> "DestinationBinding":
        if not self.checkout.is_absolute() or not self.worktree.is_absolute():
            raise ValueError("Issue-delivery destination paths must be absolute")
        checkout = PurePath(self.checkout)
        worktree = PurePath(self.worktree)
        if (
            checkout == worktree
            or checkout.is_relative_to(worktree)
            or worktree.is_relative_to(checkout)
        ):
            raise ValueError("Issue-delivery checkout and worktree must be distinct")
        if self.branch == self.base_ref:
            raise ValueError("Issue-delivery branch must differ from base ref")
        return self

    @classmethod
    def from_approval(cls, approval: Mapping[str, Any]) -> "DestinationBinding":
        destination = approval.get("destination")
        repository = approval.get("repository")
        if not isinstance(destination, Mapping) or not isinstance(repository, str):
            raise ValueError("Issue-delivery approval destination is incomplete")
        # Admission records the resolved path as the durable destination
        # identity.  Once present, use that canonical value for every
        # host-side binding rather than comparing a raw symlink spelling to a
        # frozen canonical binding later in the effect path.
        normalized = {
            key: value
            for key, value in destination.items()
            if key not in {"resolved_checkout", "resolved_worktree"}
        }
        for raw_name, frozen_name in (
            ("checkout", "resolved_checkout"),
            ("worktree", "resolved_worktree"),
        ):
            frozen = destination.get(frozen_name)
            if frozen is not None:
                if not isinstance(frozen, str) or not frozen:
                    raise ValueError(
                        f"Issue-delivery destination {frozen_name} is malformed"
                    )
                normalized[raw_name] = frozen
        return cls.model_validate({"repository": repository, **normalized})

    def as_manifest(self) -> dict[str, object]:
        return {
            "identity": self.identity,
            "run_id": self.run_id,
            "host_identity": self.host_identity,
            "system_identity": self.system_identity,
            "channel": self.channel,
            "checkout": str(self.checkout),
            "worktree": str(self.worktree),
            "branch": self.branch,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
        }


def _approved_destination_manifest(
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    """Return canonical destination fields for frozen-path comparisons.

    Admission adds ``resolved_*`` fields as immutable symlink proofs.  Verify
    them against the current raw paths, then normalize the comparison to the
    same canonical path form captured by the protected host destination.
    """

    destination = approval.get("destination")
    if not isinstance(destination, Mapping):
        raise ValueError("Issue-delivery approval destination is incomplete")
    normalized = dict(destination)
    for raw_name, frozen_name in (
        ("checkout", "resolved_checkout"),
        ("worktree", "resolved_worktree"),
    ):
        raw_value = normalized.get(raw_name)
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("Issue-delivery destination path is malformed")
        resolved_path = str(Path(raw_value).resolve())
        supplied_path = normalized.pop(frozen_name, None)
        if supplied_path is not None and supplied_path != resolved_path:
            raise ValueError(
                f"destination {frozen_name} does not match its approved path"
            )
        normalized[raw_name] = resolved_path
    repository = approval.get("repository")
    if not isinstance(repository, str):
        raise ValueError("Issue-delivery approval repository is incomplete")
    return DestinationBinding.model_validate(
        {"repository": repository, **normalized}
    ).as_manifest()


def _immutable_approved_destination_manifest(
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the admitted destination identity without reopening raw aliases.

    Recovery validates the immutable paths captured at admission.  Fresh
    execution instead uses :func:`_approved_destination_manifest` and must
    resolve the currently named paths before it can reach an effect.
    """

    destination = approval.get("destination")
    repository = approval.get("repository")
    if not isinstance(destination, Mapping) or not isinstance(repository, str):
        raise ValueError("Issue-delivery approval destination is incomplete")
    normalized = dict(destination)
    for raw_name, frozen_name in (
        ("checkout", "resolved_checkout"),
        ("worktree", "resolved_worktree"),
    ):
        frozen = destination.get(frozen_name)
        if not isinstance(frozen, str) or not frozen:
            raise ValueError(f"Issue-delivery destination {frozen_name} is malformed")
        normalized[raw_name] = frozen
        normalized.pop(frozen_name, None)
    return DestinationBinding.model_validate(
        {"repository": repository, **normalized}
    ).as_manifest()


@dataclass(frozen=True)
class FrozenIssueDeliveryDestination:
    binding: DestinationBinding
    origin_url: str
    git_directory: Path
    common_git_directory: Path
    checkout_device: int
    checkout_inode: int
    worktree_device: int
    worktree_inode: int
    git_directory_device: int
    git_directory_inode: int
    common_git_device: int
    common_git_inode: int
    identity_sha256: str

    @classmethod
    def capture(
        cls,
        binding: DestinationBinding,
        *,
        git_directory: Path,
        common_git_directory: Path,
        origin_url: str,
    ) -> "FrozenIssueDeliveryDestination":
        checkout = binding.checkout.resolve(strict=True)
        worktree = binding.worktree.resolve(strict=True)
        git_dir = git_directory.resolve(strict=True)
        common = common_git_directory.resolve(strict=True)
        checkout_stat = checkout.stat()
        worktree_stat = worktree.stat()
        git_stat = git_dir.stat()
        common_stat = common.stat()
        identity = {
            "binding": binding.model_dump(mode="json"),
            "origin_url": origin_url,
            "git_directory": str(git_dir),
            "common_git_directory": str(common),
            "checkout_device": checkout_stat.st_dev,
            "checkout_inode": checkout_stat.st_ino,
            "worktree_device": worktree_stat.st_dev,
            "worktree_inode": worktree_stat.st_ino,
            "git_directory_device": git_stat.st_dev,
            "git_directory_inode": git_stat.st_ino,
            "common_git_device": common_stat.st_dev,
            "common_git_inode": common_stat.st_ino,
        }
        return cls(
            binding=binding,
            origin_url=origin_url,
            git_directory=git_dir,
            common_git_directory=common,
            checkout_device=checkout_stat.st_dev,
            checkout_inode=checkout_stat.st_ino,
            worktree_device=worktree_stat.st_dev,
            worktree_inode=worktree_stat.st_ino,
            git_directory_device=git_stat.st_dev,
            git_directory_inode=git_stat.st_ino,
            common_git_device=common_stat.st_dev,
            common_git_inode=common_stat.st_ino,
            identity_sha256=_canonical_hash(identity),
        )


class EffectDestination(DestinationBinding):
    frozen_identity_sha256: str = Field(pattern=_HEX_64)

    def unfrozen(self) -> DestinationBinding:
        return DestinationBinding.model_validate(
            self.model_dump(mode="json", exclude={"frozen_identity_sha256"})
        )


class ClaimTarget(_StrictModel):
    kind: Literal["claim"]
    issue_number: int = Field(gt=0)
    issue_node_id: str = Field(min_length=1, max_length=256)
    expected_state: Literal["open"]
    expected_label: Literal["agent:ready"]


class _DiffTarget(_StrictModel):
    diff_sha256: str | None = Field(default=None, pattern=_HEX_64)

    @model_serializer(mode="wrap")
    def _legacy_bytes(self, handler: Any) -> dict[str, Any]:
        value = handler(self)
        if self.diff_sha256 is None:
            value.pop("diff_sha256", None)
        return value


class PublicationTarget(_DiffTarget):
    kind: Literal["publication"]
    issue_number: int = Field(gt=0)
    branch: str = Field(min_length=1, max_length=512)
    base_ref: str = Field(min_length=1, max_length=256)
    base_sha: str = Field(pattern=_HEX_40)
    head_sha: str = Field(pattern=_HEX_40)
    title_sha256: str = Field(pattern=_HEX_64)
    body_sha256: str = Field(pattern=_HEX_64)
    expected_remote_ref_state: Literal["absent"]


class MergeTarget(_DiffTarget):
    kind: Literal["merge"]
    issue_number: int = Field(gt=0)
    pr_number: int = Field(gt=0)
    branch: str = Field(min_length=1, max_length=512)
    base_ref: str = Field(min_length=1, max_length=256)
    base_sha: str = Field(pattern=_HEX_40)
    head_sha: str = Field(pattern=_HEX_40)


class ClosureTarget(_StrictModel):
    kind: Literal["closure"]
    issue_number: int = Field(gt=0)
    pr_number: int = Field(gt=0)
    merge_commit_sha: str = Field(pattern=_HEX_40)
    expected_issue_state: Literal["open"]


class ParentEvidenceTarget(_StrictModel):
    kind: Literal["parent_evidence"]
    repository: str
    issue_number: int = Field(gt=0)
    issue_node_id: str = Field(min_length=1, max_length=256)
    expected_state: Literal["open"]
    child_issue_number: int = Field(gt=0)
    parent_contract_sha256: str = Field(pattern=_HEX_64)
    relationship_sha256: str = Field(pattern=_HEX_64)
    evidence_kind: Literal["pr_receipt_comment", "child_ledger_writeback"]
    evidence_sha256: str = Field(pattern=_HEX_64)
    pr_number: int | None = Field(default=None, gt=0)

    @model_serializer(mode="wrap")
    def _without_absent_pr(self, handler: Any) -> dict[str, Any]:
        value = handler(self)
        if self.pr_number is None:
            value.pop("pr_number", None)
        return value

    @field_validator("repository")
    @classmethod
    def _repository(cls, value: str) -> str:
        return canonical_repository(value)


EffectTarget = Annotated[
    ClaimTarget
    | PublicationTarget
    | MergeTarget
    | ClosureTarget
    | ParentEvidenceTarget,
    Field(discriminator="kind"),
]


class CandidatePath(_StrictModel):
    path: str = Field(min_length=1, max_length=512)
    old_mode: Literal["000000", "100644"]
    new_mode: Literal["000000", "100644"]
    old_blob: str = Field(pattern=_HEX_40)
    new_blob: str = Field(pattern=_HEX_40)
    bytes_sha256: str = Field(pattern=_HEX_64)
    length: int = Field(ge=0, le=2 * 1024 * 1024)


class CandidateTarget(_StrictModel):
    kind: Literal["candidate_prepare"]
    issue_number: int = Field(gt=0)
    branch: str
    base_ref: str
    base_sha: str = Field(pattern=_HEX_40)
    expected_head_sha: str = Field(pattern=_HEX_40)
    snapshot_sha256: str = Field(pattern=_HEX_64)
    paths: tuple[CandidatePath, ...] = Field(min_length=1, max_length=128)
    index_sha256: str = Field(pattern=_HEX_64)
    commit_message_sha256: str = Field(pattern=_HEX_64)
    identity: Literal["BuilderOps Candidate <candidate@builderops.invalid>"]
    timestamp: int = Field(gt=0)
    tree_oid: str = Field(pattern=_HEX_40)
    commit_oid: str = Field(pattern=_HEX_40)
    completion_sha256: str = Field(pattern=_HEX_64)


class IssueDeliveryEffectRequest(_StrictModel):
    contract: Literal["builderops.issue-delivery-effect.v1", "builderops.issue-delivery-effect.v2"]
    effect_kind: Literal["claim", "publication", "merge", "closure", "parent_evidence", "candidate_prepare"]
    approval: dict[str, Any]
    approval_id: str = Field(min_length=1, max_length=256)
    approved_operation_key: str = Field(min_length=1, max_length=256)
    approval_manifest_hash: str = Field(pattern=_HEX_64)
    repository: str
    issue_number: int = Field(gt=0)
    issue_body_hash: str = Field(pattern=_HEX_64)
    acceptance_criteria_hash: str = Field(pattern=_HEX_64)
    run_id: str = Field(min_length=1, max_length=256)
    source_revision: str = Field(pattern=_HEX_40)
    workflow_hash: str = Field(pattern=_HEX_64)
    profile_hash: str = Field(pattern=_HEX_64)
    verification_profile_hash: str = Field(pattern=_HEX_64)
    authority_epoch: int = Field(gt=0)
    destination: EffectDestination
    worker_isolation: WorkerIsolationBinding
    executor_artifact_sha256: str = Field(pattern=_HEX_64)
    worker_isolation_artifact_sha256: str = Field(pattern=_HEX_64)
    target: EffectTarget | CandidateTarget

    @field_validator("repository")
    @classmethod
    def _repository(cls, value: str) -> str:
        return canonical_repository(value)

    @model_validator(mode="after")
    def _closed_identity(self) -> "IssueDeliveryEffectRequest":
        candidate_version = self.approval.get("contract_version") == CANDIDATE_CONTRACT_VERSION
        if (self.contract == "builderops.issue-delivery-effect.v2") != candidate_version:
            raise ValueError("effect wire version does not match approval")
        if self.effect_kind == "candidate_prepare" and not candidate_version:
            raise ValueError("candidate preparation requires v3")
        if self.target.kind != self.effect_kind:
            raise ValueError("Issue-delivery target kind does not match effect")
        if self.destination.repository != self.repository:
            raise ValueError("Issue-delivery destination repository changed")
        if self.destination.run_id != self.run_id:
            raise ValueError("Issue-delivery destination run changed")
        return self

    @property
    def content_sha256(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))

    @property
    def effect_repository(self) -> str:
        if not delivery_source_pair(self.approval):
            return self.repository
        if isinstance(self.target, ParentEvidenceTarget):
            return str(self.target.repository)
        return tracking_repository(self.approval) if self.effect_kind in {"claim", "closure"} else self.repository

    @property
    def effect_slot_sha256(self) -> str:
        """Stable slot for one approved semantic effect.

        Mutable effect content stays bound by ``content_sha256`` in the durable
        payload, but cannot allocate a second operation while an earlier
        attempt for the same approved target remains unresolved.
        """

        target = self.target.model_dump(mode="json")
        semantic_fields = {
            "candidate_prepare": ("issue_number", "branch", "base_ref", "base_sha"),
            "claim": ("issue_number", "issue_node_id"),
            "publication": ("issue_number", "branch", "base_ref", "base_sha"),
            "merge": (
                "issue_number",
                "pr_number",
                "branch",
                "base_ref",
                "base_sha",
            ),
            "closure": ("issue_number", "pr_number"),
            "parent_evidence": (
                "repository",
                "issue_number",
                "issue_node_id",
                "child_issue_number",
                "parent_contract_sha256",
                "relationship_sha256",
                "evidence_kind",
            ),
        }[self.effect_kind]
        return _canonical_hash(
            {
                "approval_id": self.approval_id,
                "approved_operation_key": self.approved_operation_key,
                "run_id": self.run_id,
                "repository": self.repository,
                "destination_identity_sha256": self.destination.frozen_identity_sha256,
                "effect_kind": self.effect_kind,
                "target": {field: target[field] for field in semantic_fields},
            }
        )


class EffectAuthorityReadback(_StrictModel):
    request_sha256: str = Field(pattern=_HEX_64)
    repository: str
    issue_number: int = Field(gt=0)
    issue_body_hash: str = Field(pattern=_HEX_64)
    acceptance_criteria_hash: str = Field(pattern=_HEX_64)
    source_revision: str = Field(pattern=_HEX_40)
    profile_hash: str = Field(pattern=_HEX_64)
    verification_profile_hash: str = Field(pattern=_HEX_64)
    target: EffectTarget

    @field_validator("repository")
    @classmethod
    def _repository(cls, value: str) -> str:
        return canonical_repository(value)


class EffectReadbackEvidence(_StrictModel):
    source: Literal["github-authoritative-readback"]
    observed_target_sha256: str = Field(pattern=_HEX_64)
    effect_repository: str | None = None

    @model_serializer(mode="wrap")
    def _without_absent_repository(self, handler: Any) -> dict[str, Any]:
        value = handler(self)
        if self.effect_repository is None:
            value.pop("effect_repository", None)
        return value


class LocalCandidateReadbackEvidence(_StrictModel):
    source: Literal["local-git-candidate"] = "local-git-candidate"
    observed_target_sha256: str = Field(pattern=_HEX_64)
    effect_repository: str
    effect_slot_sha256: str = Field(pattern=_HEX_64)
    destination_identity_sha256: str = Field(pattern=_HEX_64)
    expected_parent: str = Field(pattern=_HEX_40)
    observed_parent: str = Field(pattern=_HEX_40)
    expected_tree: str = Field(pattern=_HEX_40)
    observed_tree: str = Field(pattern=_HEX_40)
    expected_commit: str = Field(pattern=_HEX_40)
    observed_commit: str = Field(pattern=_HEX_40)
    branch: str
    observed_head: str = Field(pattern=_HEX_40)
    index_tree: str = Field(pattern=_HEX_40)
    content_snapshot_sha256: str = Field(pattern=_HEX_64)
    complete_diff_sha256: str = Field(pattern=_HEX_64)
    partial: Literal[False] = False


class EffectReadback(_StrictModel):
    request_sha256: str = Field(pattern=_HEX_64)
    outcome: Literal["applied", "not_applied", "unknown"]
    evidence: EffectReadbackEvidence | LocalCandidateReadbackEvidence


@dataclass(frozen=True)
class IssueDeliveryEffectReceipt:
    outcome: Literal["applied", "retry_after_readback", "unknown"]
    operation_key: str
    request_sha256: str
    effect_kind: str
    repository: str
    issue_number: int
    destination_identity_sha256: str
    worker_isolation_receipt_sha256: str
    readback: Mapping[str, object]
    delivery_sources: Mapping[str, str] | None = None

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "contract": "builderops.issue-delivery-effect-receipt.v1",
            "outcome": self.outcome,
            "operation_key": self.operation_key,
            "request_sha256": self.request_sha256,
            "effect_kind": self.effect_kind,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "destination_identity_sha256": self.destination_identity_sha256,
            "worker_isolation_receipt_sha256": self.worker_isolation_receipt_sha256,
            "readback": dict(self.readback),
        }
        _safe_receipt_value(value)
        if self.delivery_sources is not None:
            value["delivery_sources"] = dict(self.delivery_sources)
            if self.delivery_sources.get("contract_version") == CANDIDATE_CONTRACT_VERSION:
                value["contract"] = "builderops.issue-delivery-effect-receipt.v2"
        return value


@dataclass(frozen=True)
class CandidateSnapshot:
    target: CandidateTarget
    objects: tuple[tuple[str, bytes, str], ...]


class LocalCandidateApplicator:
    """Finite, hook/filter-free Git application; the executor owns its fence."""

    def __init__(self, frozen: FrozenIssueDeliveryDestination) -> None:
        self.frozen = frozen
        self.snapshot: CandidateSnapshot | None = None

    def git(self, *args: str, data: bytes | None = None) -> bytes:
        env = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0"}
        result = subprocess.run(["git", "--no-replace-objects", "-C", str(self.frozen.binding.worktree),
            "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args],
            input=data, capture_output=True, env=env, check=False)
        if result.returncode:
            raise ValueError("candidate Git observation or effect failed")
        return result.stdout

    @staticmethod
    def oid(kind: str, data: bytes) -> str:
        return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()

    def entries(self, revision: str) -> dict[str, tuple[str, str]]:
        values = {}
        for row in self.git("ls-tree", "-rz", "--full-tree", revision).split(b"\0"):
            if row:
                meta, name = row.split(b"\t", 1)
                mode, kind, oid = meta.decode().split()
                if kind != "blob":
                    raise ValueError("candidate source contains unsupported Git entries")
                values[name.decode("utf-8")] = (mode, oid)
        return values

    def index_matches(self, revision: str) -> bool:
        values = {}
        for row in self.git("ls-files", "--stage", "-z").split(b"\0"):
            if row:
                meta, name = row.split(b"\t", 1)
                mode, oid, stage = meta.decode().split()
                if stage != "0":
                    return False
                values[name.decode("utf-8")] = (mode, oid)
        return values == self.entries(revision)

    def capture(self, approval: Mapping[str, Any], completion_sha256: str, *, head: str | None = None,
                index_sha256: str | None = None, index_revision: str | None = None) -> CandidateSnapshot:
        binding = self.frozen.binding
        for path, device, inode in ((binding.checkout, self.frozen.checkout_device, self.frozen.checkout_inode),
                (binding.worktree, self.frozen.worktree_device, self.frozen.worktree_inode),
                (self.frozen.git_directory, self.frozen.git_directory_device, self.frozen.git_directory_inode),
                (self.frozen.common_git_directory, self.frozen.common_git_device, self.frozen.common_git_inode)):
            metadata = path.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or path.resolve(strict=True) != path or (metadata.st_dev, metadata.st_ino) != (device, inode):
                raise ValueError("candidate frozen filesystem identity changed")
        if (Path(self.git("rev-parse", "--path-format=absolute", "--git-dir").decode().strip()) != self.frozen.git_directory
            or Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()) != self.frozen.common_git_directory
            or self.git("remote", "get-url", "origin").decode().strip() != self.frozen.origin_url):
            raise ValueError("candidate frozen Git identity changed")
        expected_head = head or binding.base_sha
        if (self.git("rev-parse", "HEAD").decode().strip() != expected_head
            or self.git("symbolic-ref", "HEAD").decode().strip() != f"refs/heads/{binding.branch}"
            or not self.index_matches(index_revision or expected_head)):
            raise ValueError("candidate head or index changed")
        common = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
        config = self.git("config", "--local", "--no-includes", "--name-only", "--list").decode().splitlines()
        if (any(key.startswith(("filter.", "include.", "includeif.", "extensions.", "core.worktree", "core.fsmonitor")) for key in config)
            or (common / "objects/info/alternates").exists()
            or self.git("for-each-ref", "refs/replace").strip()):
            raise ValueError("candidate repository has unsupported configuration")
        index = Path(self.git("rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip())
        original_index_hash = index_sha256 or _file_sha256(index)
        base = self.entries(binding.base_sha)
        current: dict[str, tuple[str, str]] = {}
        contents: dict[str, bytes] = {}
        total = 0
        def refuse_incomplete_inventory(error: OSError) -> None:
            raise ValueError("candidate directory inventory unavailable") from error
        for directory, dirs, files in os.walk(binding.worktree, followlinks=False,
                                               onerror=refuse_incomplete_inventory):
            for name in list(dirs):
                path = Path(directory) / name
                if path.is_symlink():
                    raise ValueError("candidate contains a symlink directory")
            for name in files:
                path = Path(directory) / name
                relative = path.relative_to(binding.worktree).as_posix()
                if relative == ".git":
                    continue
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or path.resolve(strict=True) != path:
                    raise ValueError("candidate contains a non-regular file")
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    data = stream.read(2 * 1024 * 1024 + 1)
                    after = os.fstat(stream.fileno())
                    if len(data) > 2 * 1024 * 1024 or any(getattr(after, key) != getattr(metadata, key) for key in ("st_ino", "st_dev", "st_mtime_ns", "st_ctime_ns", "st_size", "st_mode", "st_nlink")):
                        raise ValueError("candidate file unavailable or too large")
                mode = "100755" if metadata.st_mode & 0o111 else "100644"
                current[relative] = (mode, self.oid("blob", data))
                if current[relative] != base.get(relative):
                    contents[relative] = data
                    total += len(data)
        changed = sorted(key for key in base.keys() | current.keys() if base.get(key) != current.get(key))
        allowed = approval["target_policies"][binding.repository]["documentation_paths"]
        if not changed or len(changed) > 128 or total > 8 * 1024 * 1024:
            raise ValueError("candidate delta is empty or unbounded")
        rows = []
        objects = []
        for relative_path in changed:
            old_mode, old_blob = base.get(relative_path, ("000000", "0" * 40))
            new_mode, new_blob = current.get(relative_path, ("000000", "0" * 40))
            if relative_path not in allowed or old_mode not in {"000000", "100644"} or new_mode not in {"000000", "100644"}:
                raise ValueError("candidate delta exceeds exact documentation envelope")
            data = contents.get(relative_path, b"")
            rows.append(CandidatePath(path=relative_path, old_mode=old_mode, new_mode=new_mode, old_blob=old_blob,
                new_blob=new_blob, bytes_sha256=hashlib.sha256(data).hexdigest(), length=len(data)))
            if new_mode != "000000":
                objects.append(("blob", data, new_blob))
        tree: dict[str, Any] = {}
        for relative_path, entry in current.items():
            parent = tree
            parts = relative_path.split("/")
            for part in parts[:-1]:
                parent = parent.setdefault(part, {})
            parent[parts[-1]] = entry
        def tree_object(node: dict[str, Any]) -> str:
            data = b""
            for name in sorted(node, key=lambda key: (key + ("/" if isinstance(node[key], dict) else "")).encode()):
                item = node[name]
                mode, oid = ("40000", tree_object(item)) if isinstance(item, dict) else item
                data += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid)
            oid = self.oid("tree", data)
            objects.append(("tree", data, oid))
            return oid
        tree_oid = tree_object(tree)
        identity = "BuilderOps Candidate <candidate@builderops.invalid>"
        timestamp = int(datetime.fromisoformat(str(approval["approved_at"]).replace("Z", "+00:00")).timestamp())
        message = f"Prepare approved documentation for Issue #{approval['issue']['number']}\n".encode()
        commit = (f"tree {tree_oid}\nparent {binding.base_sha}\nauthor {identity} {timestamp} +0000\n"
                  f"committer {identity} {timestamp} +0000\n\n").encode() + message
        commit_oid = self.oid("commit", commit)
        objects.append(("commit", commit, commit_oid))
        target = CandidateTarget(kind="candidate_prepare", issue_number=approval["issue"]["number"],
            branch=binding.branch, base_ref=binding.base_ref, base_sha=binding.base_sha,
            expected_head_sha=binding.base_sha, paths=tuple(rows),
            snapshot_sha256=_canonical_hash([row.model_dump(mode="json") for row in rows]),
            index_sha256=original_index_hash, commit_message_sha256=hashlib.sha256(message).hexdigest(),
            identity=identity, timestamp=timestamp, tree_oid=tree_oid, commit_oid=commit_oid,
            completion_sha256=completion_sha256)
        return CandidateSnapshot(target, tuple(objects))

    def validate(self, request: IssueDeliveryEffectRequest) -> None:
        target = request.target
        if not isinstance(target, CandidateTarget):
            raise ValueError("candidate target required")
        observed = self.capture(request.approval, target.completion_sha256)
        if observed.target != target:
            raise ValueError("candidate snapshot changed")
        self.snapshot = observed

    def write_object(self, kind: str, content: bytes) -> str:
        return self.git("hash-object", "-w", "-t", kind, "--stdin", data=content).decode().strip()

    def apply(self, request: IssueDeliveryEffectRequest) -> None:
        # Called only after the executor acknowledges its durable dispatch fence.
        self.validate(request)
        snapshot = self.snapshot
        if snapshot is None:
            raise ValueError("candidate bytes unavailable")
        for kind, data, oid in snapshot.objects:
            self.validate(request)
            if self.write_object(kind, data) != oid:
                raise ValueError("candidate object identity mismatch")
        self.validate(request)
        self.git("update-ref", f"refs/heads/{snapshot.target.branch}", snapshot.target.commit_oid,
                 snapshot.target.expected_head_sha)
        before_index = self.capture(request.approval, snapshot.target.completion_sha256,
            head=snapshot.target.commit_oid, index_revision=snapshot.target.base_sha)
        if before_index.target != snapshot.target:
            raise ValueError("candidate input changed before index reconciliation")
        self.git("read-tree", snapshot.target.commit_oid)

    def readback(self, request: IssueDeliveryEffectRequest) -> EffectReadback:
        target = request.target
        if not isinstance(target, CandidateTarget):
            raise ValueError("candidate target required")
        observed = self.capture(request.approval, target.completion_sha256, head=target.commit_oid,
                                index_sha256=target.index_sha256)
        commit = self.git("cat-file", "commit", target.commit_oid)
        if observed.target != target or commit != observed.objects[-1][1]:
            raise ValueError("candidate readback incomplete")
        raw = self.git("diff-tree", "--no-commit-id", "--raw", "-z", "-r", "--no-abbrev",
                       "-M", "-C", "--find-copies-harder", target.base_sha, target.commit_oid, "--")
        diff = _parse_documentation_diff(raw, target.base_sha, target.commit_oid,
                                        request.approval["target_policies"][request.repository]["documentation_paths"])
        return EffectReadback(outcome="applied", request_sha256=request.content_sha256,
            evidence=LocalCandidateReadbackEvidence(observed_target_sha256=_canonical_hash(target.model_dump(mode="json")),
                effect_repository=request.effect_repository, effect_slot_sha256=request.effect_slot_sha256,
                destination_identity_sha256=self.frozen.identity_sha256,
                expected_parent=target.base_sha, observed_parent=commit.splitlines()[1].split()[1].decode(),
                expected_tree=target.tree_oid, observed_tree=commit.splitlines()[0].split()[1].decode(),
                expected_commit=target.commit_oid, observed_commit=self.oid("commit", commit),
                branch=target.branch, observed_head=self.git("rev-parse", "HEAD").decode().strip(),
                index_tree=observed.target.tree_oid, content_snapshot_sha256=observed.target.snapshot_sha256,
                complete_diff_sha256=_canonical_hash(diff)))


class IssueDeliveryAuthorityReader(Protocol):
    def issue_delivery_authority(
        self, *, manifest: Mapping[str, Any], purpose: str
    ) -> Mapping[str, Any]: ...


class IssueDeliveryDestinationAuthority(Protocol):
    def assert_frozen(
        self,
        frozen: FrozenIssueDeliveryDestination,
        approval: Mapping[str, Any],
    ) -> None: ...


class IssueDeliveryRepositoryAuthority(Protocol):
    def protected_base_sha(self, repository: str) -> str: ...

    def issue_delivery_source(self, repository: str, number: int) -> Mapping[str, Any]: ...

    def current_pr_head(self, repository: str, pr_number: int) -> str: ...

    def merge_readback(self, repository: str, pr_number: int) -> Mapping[str, object]: ...

    def required_gates(self, repository: str, pr_number: int, head_sha: str,
                       *, verification_checks: tuple[str, ...] | None = None) -> Mapping[str, bool]: ...

    def delivery_manifest(
        self, repository: str, base_sha: str
    ) -> ProtectedDeliveryManifest: ...


class IssueDeliveryEffectTransport(Protocol):
    def validate_target(
        self, request: IssueDeliveryEffectRequest
    ) -> EffectAuthorityReadback: ...

    def apply(
        self, request: IssueDeliveryEffectRequest, credential: object
    ) -> None: ...

    def readback(self, request: IssueDeliveryEffectRequest) -> EffectReadback: ...


class IssueDeliveryEffectLedger(Protocol):
    def operation_key(
        self, *, effect_slot_sha256: str, effect_type: str
    ) -> str: ...

    def begin(
        self,
        *,
        effect_slot_sha256: str,
        effect_type: str,
        payload: Mapping[str, Any],
    ) -> str: ...

    def status(self, operation_key: str) -> Mapping[str, Any]: ...

    def claim_effect(
        self,
        operation_key: str,
        *,
        effect_type: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def claim_for_readback(self, operation_key: str) -> Mapping[str, Any]: ...

    def revalidate_effect_claim(
        self, claim: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def mark_unknown(
        self, claim: Mapping[str, Any], *, detail: str
    ) -> Mapping[str, Any]: ...

    def reconcile(
        self,
        claim: Mapping[str, Any],
        *,
        observed_applied: bool,
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


def complete_documentation_diff(root: Path, base_sha: str, head_sha: str, allowed_paths: Sequence[str]) -> dict[str, Any]:
    """Read the full two-tree delta, including modes and both copy/rename paths."""
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), "diff-tree", "--no-commit-id", "--raw", "-z", "-r",
         "--no-abbrev", "-M", "-C", "--find-copies-harder", base_sha, head_sha, "--"],
        capture_output=True, check=True,
    )
    return _parse_documentation_diff(result.stdout, base_sha, head_sha, allowed_paths)


def _parse_documentation_diff(raw: bytes, base_sha: str, head_sha: str, allowed_paths: Sequence[str]) -> dict[str, Any]:
    parts = raw.decode("utf-8", errors="strict").split("\0")
    changes: list[dict[str, Any]] = []
    index = 0
    while index < len(parts) - 1:
        fields = parts[index].split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise ValueError("complete diff is malformed")
        old_mode, new_mode, old_blob, new_blob, status = fields
        old_mode = old_mode[1:]
        count = 2 if status[0] in {"R", "C"} else 1
        paths = parts[index + 1:index + 1 + count]
        if (len(paths) != count or any(path not in allowed_paths for path in paths)
            or old_mode not in {"100644", "000000"} or new_mode not in {"100644", "000000"}
            or status[0] not in {"A", "M", "D", "R", "C"}):
            raise ValueError("complete diff contains a forbidden path or non-regular mode")
        changes.append({"old_mode": old_mode, "new_mode": new_mode, "old_blob": old_blob,
                        "new_blob": new_blob, "status": status, "paths": paths})
        index += count + 1
    if not changes:
        raise ValueError("documentation candidate has no complete diff")
    return {"base_sha": base_sha, "head_sha": head_sha, "changes": changes}


def _policy_binding(manifest: ProtectedDeliveryManifest) -> dict[str, Any]:
    return {
        "repository": manifest.repository, "base_sha": manifest.base_sha,
        "blob_sha": manifest.blob_sha, "content_sha256": manifest.content_sha256,
        "credential_id": manifest.credential_id,
        "rotation_generation": manifest.credential_generation,
        "allowed_effects": list(manifest.allowed_effects),
        "documentation_paths": list(manifest.documentation_paths),
        "verification_profile": manifest.verification_profile,
        "required_checks": list(manifest.required_checks),
    }


def _v2_authority_bindings(
    approval: Mapping[str, Any], *, repository_authority: IssueDeliveryRepositoryAuthority,
    credentials: HostCredentialResolver, trusted_workflow_root: Path | None,
    check_current_bases: bool = True, completed_merge_sha: str | None = None,
    completed_closure: bool = False,
) -> Mapping[str, Any]:
    """Reread both sources and every exact target grant before any new effect."""
    from app.builderops.issue_delivery_operation import _verify_workflow_root
    from app.builderops.issue_delivery_readback import _source_hashes

    _verify_workflow_root(approval, trusted_workflow_root)
    destination = approval["destination"]
    checkout = Path(destination["checkout"])
    def git(*args: str) -> str:
        result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, check=False)
        if result.returncode:
            raise ValueError("consumer Git source unavailable")
        return result.stdout.strip()
    if (git("rev-parse", "HEAD") != approval["source"]["revision"]
        or _repository_from_remote(git("remote", "get-url", "origin")) != approval["repository"]
        or str(checkout.resolve()) != destination.get("resolved_checkout", str(checkout.resolve()))):
        raise ValueError("consumer source identity changed")
    for repository, expected in approval["target_policies"].items():
        current_base = completed_merge_sha if repository == approval["repository"] and completed_merge_sha else expected["base_sha"]
        if check_current_bases and repository_authority.protected_base_sha(repository) != current_base:
            raise ValueError("target protected base changed")
        observed = repository_authority.delivery_manifest(repository, current_base)
        if _policy_binding(observed) != {**expected, "base_sha": current_base}:
            raise ValueError("target policy or verification profile changed")
        credentials.resolve(repository=repository, credential_id=observed.credential_id,
                            rotation_generation=observed.credential_generation)
    issue = approval["issue"]
    source = repository_authority.issue_delivery_source(tracking_repository(approval), issue["number"])
    body_hash, ac_hash = _source_hashes(source)
    if (source.get("number") != issue["number"] or source.get("node_id") != issue["node_id"]
        or source.get("html_url", source.get("url", "")).casefold() != issue["url"].casefold()
        or source.get("state") != ("closed" if completed_closure else "open") or body_hash != issue["body_hash"]
        or ac_hash != issue["acceptance_criteria_hash"]):
        raise ValueError("hub tracking Issue identity or contract changed")
    return source


def validate_installed_v2_admission(approval: Mapping[str, Any], *, require_ready: bool = True) -> None:
    """The service uses the host-installed readers; caller input cannot install them."""
    if approval.get("contract_version") not in TWO_SOURCE_VERSIONS:
        return
    runtime = _HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME
    if runtime is None:
        raise ValueError("v2 protected host authority readers are unavailable")
    source = _v2_authority_bindings(approval, repository_authority=runtime.repository_authority,
                                  credentials=runtime.credentials, trusted_workflow_root=runtime.trusted_workflow_root)
    if require_ready:
        labels = {item["name"] if isinstance(item, Mapping) else item for item in source.get("labels", [])}
        if {item for item in labels if item.startswith("agent:")} != {"agent:ready"}:
            raise ValueError("tracking Issue is not independently ready")


class IssueDeliveryHostExecutor:
    """The only Issue-delivery component allowed to resolve effect identity."""

    def __init__(
        self,
        *,
        authority: IssueDeliveryAuthorityReader,
        ledger: IssueDeliveryEffectLedger,
        repository_authority: IssueDeliveryRepositoryAuthority,
        credentials: HostCredentialResolver,
        destination: IssueDeliveryDestinationAuthority,
        frozen_destination: FrozenIssueDeliveryDestination,
        transport: IssueDeliveryEffectTransport,
        prepared_worker: PreparedIssueDeliveryWorker | None = None,
        completion_reader: Callable[[str], Mapping[str, Any]] | None = None,
        expected_isolation_profile_sha256: str | None = None,
        live_binding_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        trusted_executor_artifact: Path = Path(__file__),
        trusted_worker_isolation_artifact: Path = Path(__file__).with_name(
            "issue_delivery_worker_isolation.py"
        ),
        trusted_workflow_root: Path = Path(__file__).resolve().parents[2],
    ) -> None:
        self.authority = authority
        self.ledger = ledger
        self.repository_authority = repository_authority
        self.credentials = credentials
        self.destination = destination
        self.frozen_destination = frozen_destination
        self.candidate_applicator = LocalCandidateApplicator(frozen_destination)
        self._completion: dict[str, Any] | None = None
        self._completion_bindings: dict[str, Any] | None = None
        # A protected executor always starts unbound.  Only the prepared
        # launcher it was given can later supply the one durable host receipt.
        self._worker_isolation: WorkerIsolationBinding | None = None
        self._prepared_worker = prepared_worker
        self._completion_reader = completion_reader
        self.recovered_candidate_terminal: Mapping[str, Any] | None = None
        self._expected_isolation_profile_sha256 = expected_isolation_profile_sha256
        self.transport = transport
        self._live_binding_reader = live_binding_reader
        self.trusted_executor_artifact = trusted_executor_artifact.resolve()
        self.trusted_worker_isolation_artifact = (
            trusted_worker_isolation_artifact.resolve()
        )
        self.trusted_workflow_root = trusted_workflow_root.resolve()

    @property
    def worker_isolation(self) -> WorkerIsolationBinding:
        """Return the one host-observed launch binding after it is frozen."""

        if self._worker_isolation is None:
            raise ValueError("completed worker receipt is unavailable")
        return self._worker_isolation

    def bind_completed_worker(self) -> None:
        """Freeze exactly one host-produced pre-spawn receipt for this launcher."""

        if self._worker_isolation is not None:
            raise ValueError("completed worker receipt is already bound")
        prepared = self._prepared_worker
        expected_profile = self._expected_isolation_profile_sha256
        if type(prepared) is not PreparedIssueDeliveryWorker or not isinstance(
            expected_profile, str
        ):
            raise ValueError("completed worker receipt is unavailable")
        launcher = prepared.launcher
        if not isinstance(launcher, ContentOnlyIssueDeliverySessionLauncher):
            raise ValueError("prepared worker launcher is invalid")
        if launcher.expected_profile_sha256 != expected_profile:
            raise ValueError("prepared worker profile differs from host pin")
        binding = WorkerIsolationBinding.from_receipt(
            launcher.completed_isolation_receipt()
        )
        if binding.profile_sha256 != expected_profile:
            raise ValueError("completed worker receipt profile differs from host pin")
        self._worker_isolation = binding

    def live_binding(self, approval: Mapping[str, Any], *, post_merge_observation: bool = False) -> Mapping[str, Any]:
        """Return fresh destination/source/profile facts for FCA-ID-B admission.

        The protected executor owns this seam, but the source/profile readers
        remain host-configured dependencies.  A missing reader is a hard
        refusal; echoing the immutable approval here would turn a stale
        manifest into a false live observation.
        """

        if self._live_binding_reader is None:
            raise ValueError("protected host live source/profile reader is unavailable")
        observed = self._live_binding_reader(approval)
        if not isinstance(observed, Mapping):
            raise ValueError("protected host live source/profile binding is malformed")
        if delivery_source_pair(approval):
            from app.builderops.issue_delivery_operation import _default_live_binding_reader
            current = _v2_authority_bindings(approval, repository_authority=self.repository_authority,
                                            credentials=self.credentials, trusted_workflow_root=self.trusted_workflow_root,
                                            check_current_bases=not post_merge_observation)
            observed = {**observed, **_default_live_binding_reader(approval, trusted_workflow_root=self.trusted_workflow_root)}
            observed["current_issue"] = {key: current[key] for key in ("number", "node_id", "state")}
            from app.builderops.issue_delivery_readback import _source_hashes
            body, ac = _source_hashes(current)
            observed["current_issue"].update(body_hash=body, acceptance_criteria_hash=ac)
        return dict(observed)

    def prepare_candidate(self, approval: Mapping[str, Any], bindings: Mapping[str, Any]) -> CandidateTarget:
        if approval.get("contract_version") != CANDIDATE_CONTRACT_VERSION or self._prepared_worker is None:
            raise ValueError("candidate preparation requires the v3 host composition")
        self._completion_bindings = dict(bindings)
        self._completion = self._prepared_worker.launcher.completed_worker_observation(bindings)
        snapshot = self.candidate_applicator.capture(approval, _canonical_hash(self._completion))
        self.candidate_applicator.snapshot = snapshot
        return snapshot.target

    def _validate_candidate_completion(self, request: IssueDeliveryEffectRequest) -> None:
        if self._completion_reader is None or self._completion_bindings is None or self._completion is None:
            raise ValueError("candidate completion witness unavailable")
        observed = reobserve_worker_completion(self._completion, self._completion_reader)
        if observed != self._completion or not isinstance(request.target, CandidateTarget) or request.target.completion_sha256 != _canonical_hash(observed):
            raise ValueError("candidate completion witness changed")

    def restore_candidate_binding(self, terminal: Mapping[str, Any]) -> None:
        """Restore only a directly authenticated terminal, then observe the same host."""
        payload = terminal["payload"]
        if not isinstance(self.ledger, BuilderOpsIssueDeliveryEffectLedger):
            raise ValueError("candidate recovery requires the native authenticated ledger")
        actual = self.ledger.client.issue_delivery_operation_record_read(
            repository=payload["repository"], record_id=f"issue-delivery-terminal:{payload['operation_key']}")
        if actual != terminal or payload["schema"] != "builderops.issue-delivery-terminal.v2":
            raise ValueError("retained candidate terminal is unauthenticated")
        from app.builderops.control_plane.issue_delivery import validate_worker_completion
        candidate = payload["candidate_binding"]
        completion = validate_worker_completion(candidate["completion"])
        if (candidate["completion_sha256"] != _canonical_hash(completion)
            or completion["destination_sha256"] != self.frozen_destination.identity_sha256
            or completion["approval_id"] != payload["approval_id"] or completion["operation_key"] != payload["operation_key"]
            or completion["profile_sha256"] != self._expected_isolation_profile_sha256
            or self._completion_reader is None):
            raise ValueError("retained candidate binding changed")
        reobserve_worker_completion(completion, self._completion_reader)
        self._completion = completion
        self._completion_bindings = {k: v for k, v in completion.items() if k not in {"contract", "observation", "profile_sha256", "isolation_receipt_sha256"}}
        self._worker_isolation = WorkerIsolationBinding.model_validate({**candidate["worker_isolation"], "repository_credential_probe": "denied"})
        self.recovered_candidate_terminal = actual

    def read_candidate(self, request: IssueDeliveryEffectRequest) -> IssueDeliveryEffectReceipt:
        """Read-only replay. A missing intent or partial Git effect never permits dispatch."""
        self._validate_static_request(request, current_artifacts=False)
        self._validate_candidate_completion(request)
        operation = self.ledger.operation_key(effect_slot_sha256=request.effect_slot_sha256,
            effect_type=_EFFECT_TYPES["candidate_prepare"])
        status = self.ledger.status(operation)
        if status.get("status") == "missing":
            return self._receipt("unknown", operation, request, {"outcome": "unknown", "readback": "candidate-intent-missing"})
        self._validate_recovery_intent(status, request, _EFFECT_TYPES["candidate_prepare"], operation)
        if status.get("status") == "succeeded":
            # Historical reconciliation alone is not evidence of current ref/index/content.
            self._fresh_readback_authority(request)
            readback = self.candidate_applicator.readback(request)
            return self._receipt("applied", operation, request, readback.evidence.model_dump(mode="json"))
        return self._readback_and_reconcile(operation, request)

    def candidate_binding(self, target: CandidateTarget) -> dict[str, Any]:
        if self._completion is None or target.completion_sha256 != _canonical_hash(self._completion):
            raise ValueError("candidate completion binding unavailable")
        return {"completion": self._completion, "completion_sha256": target.completion_sha256,
                "target": target.model_dump(mode="json"),
                # The closed retained representation omits this invariant literal,
                # not a credential or a grant; the authenticated isolation hash remains.
                "worker_isolation": self.worker_isolation.model_dump(mode="json", exclude={"repository_credential_probe"})}

    def execute(
        self, request: IssueDeliveryEffectRequest
    ) -> IssueDeliveryEffectReceipt:
        if request.approval.get("contract_version") == CANDIDATE_CONTRACT_VERSION and self._prepared_worker is None:
            raise ValueError("reconstructed candidate permits readback only")
        if request.approval.get("contract_version") == CANDIDATE_CONTRACT_VERSION and request.effect_kind not in {"claim", "candidate_prepare"}:
            raise ValueError("v3 remote continuation is not implemented")
        self._validate_static_request(request, current_artifacts=False)
        frozen = self._request_destination(request)
        effect_type = _EFFECT_TYPES[request.effect_kind]
        operation_key = self.ledger.operation_key(
            effect_slot_sha256=request.effect_slot_sha256,
            effect_type=effect_type,
        )
        status = self.ledger.status(operation_key)
        state = status.get("status")
        if state != "missing":
            self._validate_recovery_intent(status, request, effect_type, operation_key)
            if state == "succeeded":
                if request.effect_kind == "candidate_prepare":
                    return self.read_candidate(request)
                evidence = status.get("reconciliation_evidence")
                if not isinstance(evidence, Mapping):
                    raise ValueError("settled Issue-delivery effect lacks readback")
                return self._receipt("applied", operation_key, request, evidence)
            if state in {"claimed", "unknown"}:
                return self._reconcile_existing(operation_key, request)
            if state != "pending":
                raise ValueError("Issue-delivery effect intent is not executable")

        first_manifest = self._fresh_execute_authority(request, frozen)
        payload = self._effect_payload(request, first_manifest)
        if state == "missing":
            operation_key = self.ledger.begin(
                effect_slot_sha256=request.effect_slot_sha256,
                effect_type=effect_type,
                payload=payload,
            )
            status = self.ledger.status(operation_key)
        else:
            self._validate_persisted_manifest(status, first_manifest)
        self._validate_intent(status, request, effect_type, payload, operation_key)
        if status.get("status") != "pending":
            raise ValueError("Issue-delivery effect intent is not pending")
        claim = self.ledger.claim_effect(
            operation_key,
            effect_type=effect_type,
            payload=payload,
        )
        self._validate_effect_claim(
            claim,
            operation_key,
            effect_type,
            payload,
            repository=request.repository,
        )
        try:
            final_manifest = self._fresh_execute_authority(request, frozen)
            if final_manifest != first_manifest:
                raise ValueError("protected repository manifest changed before effect")
            if request.effect_kind == "candidate_prepare":
                self._validate_candidate_completion(request)
                self.candidate_applicator.validate(request)
            else:
                self._validate_target_authority(request, self.transport.validate_target(request))
        except Exception as exc:
            self._record_known_no_effect(claim, request, reason=type(exc).__name__)
            raise
        credential = self.credentials.resolve(
            repository=request.effect_repository,
            credential_id=final_manifest.credential_id,
            rotation_generation=final_manifest.credential_generation,
        )
        fresh_claim = self.ledger.revalidate_effect_claim(claim)
        self._validate_revalidated_effect_claim(
            fresh_claim,
            claim,
            operation_key,
            effect_type,
            payload,
            repository=request.repository,
        )
        if not self._commit_dispatch(claim, operation_key):
            return self._receipt(
                "unknown",
                operation_key,
                request,
                {"outcome": "unknown", "readback": "dispatch-fence-unavailable"},
            )
        try:
            if request.effect_kind == "candidate_prepare":
                self._validate_candidate_completion(request)
                self.candidate_applicator.apply(request)
            else:
                self.transport.apply(request, credential)
        except Exception:
            pass
        return self._readback_and_reconcile(operation_key, request)

    def _commit_dispatch(
        self,
        claim: Mapping[str, Any],
        operation_key: str,
    ) -> bool:
        """Durably consume the exact fence before any external effect call."""

        try:
            committed = self.ledger.mark_unknown(
                claim,
                detail="effect dispatch committed; source readback required",
            )
        except Exception:
            # Only the same authenticated transition may be retried after a
            # lost response. The ledger never treats an unrelated recovered
            # ``unknown`` row as proof that this dispatcher committed.
            try:
                committed = self.ledger.mark_unknown(
                    claim,
                    detail="effect dispatch committed; source readback required",
                )
            except Exception:
                return False
        try:
            self._validate_dispatch_commit(committed, claim, operation_key)
        except ValueError:
            return False
        return True

    def _reconcile_existing(
        self,
        operation_key: str,
        request: IssueDeliveryEffectRequest,
    ) -> IssueDeliveryEffectReceipt:
        return self._readback_and_reconcile(operation_key, request)

    def _readback_and_reconcile(
        self,
        operation_key: str,
        request: IssueDeliveryEffectRequest,
    ) -> IssueDeliveryEffectReceipt:
        self._fresh_readback_authority(request)
        try:
            claim = self.ledger.claim_for_readback(operation_key)
        except Exception:
            return self._receipt(
                "unknown",
                operation_key,
                request,
                {"outcome": "unknown", "readback": "recovery-fence-unavailable"},
            )
        status = self.ledger.status(operation_key)
        payload = status.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("unknown Issue-delivery effect lost its payload")
        self._validate_readback_claim(
            claim,
            operation_key,
            _EFFECT_TYPES[request.effect_kind],
            payload,
        )
        try:
            if request.effect_kind == "candidate_prepare":
                self._validate_candidate_completion(request)
                readback = self.candidate_applicator.readback(request)
            else:
                readback = self.transport.readback(request)
        except Exception:
            return self._receipt(
                "unknown",
                operation_key,
                request,
                {"outcome": "unknown", "readback": "source-unavailable"},
            )
        if readback.request_sha256 != request.content_sha256:
            raise ValueError("Issue-delivery readback belongs to another request")
        if readback.evidence.observed_target_sha256 != _canonical_hash(
            request.target.model_dump(mode="json")
        ):
            raise ValueError("Issue-delivery readback target changed")
        if delivery_source_pair(request.approval) and readback.evidence.effect_repository != request.effect_repository:
            raise ValueError("Issue-delivery readback addresses another effect repository")
        readback_evidence = readback.evidence.model_dump(mode="json")
        _safe_receipt_value(readback_evidence)
        evidence = {
            "outcome": readback.outcome,
            "request_sha256": readback.request_sha256,
            **readback_evidence,
        }
        if readback.outcome == "unknown":
            return self._receipt("unknown", operation_key, request, evidence)
        applied = readback.outcome == "applied"
        if not applied:
            return self._receipt(
                "unknown",
                operation_key,
                request,
                {
                    **evidence,
                    "retry_refused": "committed-dispatch-may-still-complete",
                },
            )
        self.ledger.reconcile(
            claim,
            observed_applied=applied,
            evidence=evidence,
        )
        return self._receipt(
            "applied" if applied else "retry_after_readback",
            operation_key,
            request,
            evidence,
        )

    def _fresh_execute_authority(
        self,
        request: IssueDeliveryEffectRequest,
        frozen: FrozenIssueDeliveryDestination,
    ) -> ProtectedDeliveryManifest:
        authority = self.authority.issue_delivery_authority(
            manifest=request.approval,
            purpose="execute",
        )
        approved = authority.get("approval")
        if (
            not isinstance(approved, Mapping)
            or dict(approved) != request.approval
            or authority.get("operation_key") != request.approved_operation_key
            or authority.get("authority_epoch") != request.authority_epoch
        ):
            raise ValueError("Issue-delivery execute authority changed")
        self._validate_static_request(request, current_artifacts=True)
        self.destination.assert_frozen(frozen, approved)
        if request.effect_kind == "candidate_prepare":
            self._validate_candidate_completion(request)
            self.candidate_applicator.validate(request)
        if delivery_source_pair(approved):
            merge_sha, closed = self._completed_transitions(request)
            current = _v2_authority_bindings(approved, repository_authority=self.repository_authority,
                                            credentials=self.credentials, trusted_workflow_root=self.trusted_workflow_root,
                                            completed_merge_sha=merge_sha, completed_closure=closed)
            labels = {item["name"] if isinstance(item, Mapping) else item for item in current.get("labels", [])}
            expected_labels = set() if closed else {"agent:ready"} if request.effect_kind == "claim" else {"agent:in-progress"}
            if {item for item in labels if item.startswith("agent:")} != expected_labels:
                raise ValueError("foreign tracking Issue claim")
            if request.effect_kind != "claim":
                claim_request = request.model_copy(update={"effect_kind": "claim", "target": ClaimTarget(
                    kind="claim", issue_number=request.issue_number, issue_node_id=approved["issue"]["node_id"],
                    expected_state="open", expected_label="agent:ready")})
                claimed = self.ledger.status(self.ledger.operation_key(effect_slot_sha256=claim_request.effect_slot_sha256,
                                                                     effect_type=_EFFECT_TYPES["claim"]))
                if claimed.get("status") != "succeeded" or claimed.get("payload", {}).get("request_sha256") != claim_request.content_sha256:
                    raise ValueError("tracking claim is not owned by this operation")
            self._validate_complete_diff(request)
        policy_base = (approved["target_policies"][request.effect_repository]["base_sha"]
                       if delivery_source_pair(approved) else request.destination.base_sha)
        manifest = self.repository_authority.delivery_manifest(
            request.effect_repository,
            policy_base,
        )
        if (
            manifest.repository != request.effect_repository
            or manifest.base_sha != policy_base
            or _EFFECT_TYPES[request.effect_kind] not in manifest.allowed_effects
        ):
            raise ValueError("protected repository manifest does not authorize effect")
        return manifest

    def _completed_transitions(self, request: IssueDeliveryEffectRequest) -> tuple[str | None, bool]:
        """Only our durable merge plus independent GitHub evidence advances the base."""
        target = request.target
        if not isinstance(target, (ClosureTarget, ParentEvidenceTarget)):
            return None, False
        if target.pr_number is None:
            raise ValueError("post-merge evidence requires an exact consumer PR")
        candidate = request.model_copy(update={"effect_kind": "merge", "target": MergeTarget(
            kind="merge", issue_number=request.issue_number, pr_number=target.pr_number,
            branch=request.destination.branch, base_ref=request.destination.base_ref,
            base_sha=request.destination.base_sha, head_sha=request.source_revision)})
        status = self.ledger.status(self.ledger.operation_key(
            effect_slot_sha256=candidate.effect_slot_sha256, effect_type=_EFFECT_TYPES["merge"]))
        payload = status.get("payload", {})
        if status.get("status") != "succeeded" or payload.get("delivery_sources") != delivery_source_pair(request.approval):
            raise ValueError("post-merge effect lacks its own successful merge")
        prior_target = MergeTarget.model_validate(payload.get("target"))
        prior = candidate.model_copy(update={"target": prior_target})
        if payload.get("request_sha256") != prior.content_sha256:
            raise ValueError("prior merge binding changed")
        observed = self.repository_authority.merge_readback(request.repository, target.pr_number)
        sha = observed.get("merge_commit_sha")
        if (observed.get("merged") is not True or observed.get("head_sha") != prior_target.head_sha
            or not isinstance(sha, str) or not re.fullmatch(_HEX_40, sha)
            or isinstance(target, ClosureTarget) and sha != target.merge_commit_sha):
            raise ValueError("independent merge readback differs from this operation")
        closed = False
        if isinstance(target, ParentEvidenceTarget):
            closure = request.model_copy(update={"effect_kind": "closure", "target": ClosureTarget(
                kind="closure", issue_number=request.issue_number, pr_number=target.pr_number,
                merge_commit_sha=sha, expected_issue_state="open")})
            prior_closure = self.ledger.status(self.ledger.operation_key(
                effect_slot_sha256=closure.effect_slot_sha256, effect_type=_EFFECT_TYPES["closure"]))
            closed = prior_closure.get("status") == "succeeded" and prior_closure.get("payload", {}).get("request_sha256") == closure.content_sha256
        return sha, closed

    def _validate_complete_diff(self, request: IssueDeliveryEffectRequest) -> None:
        target = request.target
        if not isinstance(target, (PublicationTarget, MergeTarget)):
            return
        policy = request.approval["target_policies"][request.repository]
        observed = complete_documentation_diff(request.destination.worktree, target.base_sha,
                                               target.head_sha, policy["documentation_paths"])
        if target.diff_sha256 != _canonical_hash(observed):
            raise ValueError("complete candidate diff binding changed")
        head = subprocess.run(["git", "-C", str(request.destination.worktree), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        if head != target.head_sha:
            raise ValueError("candidate head changed")
        if isinstance(target, MergeTarget):
            if self.repository_authority.current_pr_head(request.repository, target.pr_number) != target.head_sha:
                raise ValueError("merge head changed")
            gates = self.repository_authority.required_gates(request.repository, target.pr_number, target.head_sha,
                                                              verification_checks=tuple(policy["required_checks"]))
            if not gates or any(value is not True for value in gates.values()):
                raise ValueError("consumer required verification is unavailable")

    def _fresh_readback_authority(
        self,
        request: IssueDeliveryEffectRequest,
    ) -> None:
        authority = self.authority.issue_delivery_authority(
            manifest=request.approval,
            purpose="readback",
        )
        approved = authority.get("approval")
        if (
            not isinstance(approved, Mapping)
            or dict(approved) != request.approval
            or authority.get("operation_key") != request.approved_operation_key
        ):
            raise ValueError("Issue-delivery readback authority changed")
        # Epoch, expiry, execute permission, live destination, and current
        # artifacts deliberately do not gate reconciliation of a prior attempt.
        self._validate_static_request(request, current_artifacts=False)

    def _validate_static_request(
        self,
        request: IssueDeliveryEffectRequest,
        *,
        current_artifacts: bool,
    ) -> None:
        approval = request.approval
        issue = approval.get("issue")
        source = approval.get("source")
        workflow = approval.get("workflow")
        profile = approval.get("profile")
        verification = (
            profile.get("verification_profile")
            if isinstance(profile, Mapping)
            else None
        )
        try:
            approved_destination = (
                _approved_destination_manifest(approval)
                if current_artifacts
                else _immutable_approved_destination_manifest(approval)
            )
        except ValueError as exc:
            raise ValueError("Issue-delivery approval destination is invalid") from exc
        if (
            approval.get("contract_version") not in {"fca-issue-delivery.v1", *TWO_SOURCE_VERSIONS}
            or approval.get("operation_type") != "deliver_ready_issue"
            or approval.get("approval_id") != request.approval_id
            or approval.get("operation_key") != request.approved_operation_key
            or approval.get("approval_manifest_hash") != request.approval_manifest_hash
            or approval.get("authority_epoch") != request.authority_epoch
            or canonical_repository(str(approval.get("repository")))
            != request.repository
            or not isinstance(issue, Mapping)
            or issue.get("number") != request.issue_number
            or issue.get("body_hash") != request.issue_body_hash
            or issue.get("acceptance_criteria_hash") != request.acceptance_criteria_hash
            or not isinstance(source, Mapping)
            or source.get("revision") != request.source_revision
            or not isinstance(workflow, Mapping)
            or workflow.get("content_hash") != request.workflow_hash
            or not isinstance(profile, Mapping)
            or profile.get("content_hash") != request.profile_hash
            or not isinstance(verification, Mapping)
            or verification.get("content_hash") != request.verification_profile_hash
            or approved_destination != request.destination.unfrozen().as_manifest()
            or _PERMISSIONS[request.effect_kind]
            not in set(approval.get("permitted_effects", ()))
            or request.worker_isolation != self.worker_isolation
        ):
            raise ValueError("Issue-delivery request does not match exact approval")
        target = request.target
        if isinstance(
            target, (ClaimTarget, PublicationTarget, MergeTarget, ClosureTarget, CandidateTarget)
        ):
            if target.issue_number != request.issue_number:
                raise ValueError("Issue-delivery target addresses another Issue")
        if isinstance(target, ClaimTarget) and target.issue_node_id != issue.get(
            "node_id"
        ):
            raise ValueError("Issue-delivery claim node changed")
        if isinstance(target, (PublicationTarget, MergeTarget, CandidateTarget)) and (
            target.branch != request.destination.branch
            or target.base_ref != request.destination.base_ref
            or target.base_sha != request.destination.base_sha
        ):
            raise ValueError("Issue-delivery Git target broadened destination")
        if isinstance(target, ParentEvidenceTarget):
            self._validate_parent_target(target, approval)
        if current_artifacts:
            self._validate_artifacts(request, workflow)

    @staticmethod
    def _validate_parent_target(
        target: ParentEvidenceTarget,
        approval: Mapping[str, Any],
    ) -> None:
        parent = approval.get("parent_evidence")
        relationship = (
            parent.get("relationship") if isinstance(parent, Mapping) else None
        )
        permission = (
            parent.get("write_permission") if isinstance(parent, Mapping) else None
        )
        required_effect = (
            "pr_receipt_comments"
            if target.evidence_kind == "pr_receipt_comment"
            else "child_generated_ledger_writeback"
        )
        if (
            not isinstance(parent, Mapping)
            or parent.get("kind") != "issue"
            or target.repository
            != tracking_repository(approval)
            or canonical_repository(str(parent.get("repository"))) != target.repository
            or parent.get("number") != target.issue_number
            or parent.get("node_id") != target.issue_node_id
            or target.child_issue_number
            != approval.get("issue", {}).get("number")
            or parent.get("contract_hash") != target.parent_contract_sha256
            or not isinstance(relationship, Mapping)
            or _canonical_hash(relationship) != target.relationship_sha256
            or relationship.get("authenticated") is not True
            or relationship.get("child_issue_number")
            != approval.get("issue", {}).get("number")
            or not isinstance(permission, Mapping)
            or permission.get("scope") != "parent_evidence:write"
            or required_effect not in set(permission.get("effects", ()))
        ):
            raise ValueError("parent evidence target is foreign or broadened")

    def _validate_artifacts(
        self,
        request: IssueDeliveryEffectRequest,
        workflow: Mapping[str, Any],
    ) -> None:
        artifacts = workflow.get("artifacts")
        if delivery_source_pair(request.approval):
            from app.builderops.issue_delivery_operation import _verify_workflow_root
            _verify_workflow_root(request.approval, self.trusted_workflow_root)
            if (self.trusted_executor_artifact != self.trusted_workflow_root / EXECUTOR_ARTIFACT
                or self.trusted_worker_isolation_artifact != self.trusted_workflow_root / WORKER_ISOLATION_ARTIFACT):
                raise ValueError("executor artifacts are outside pinned workflow root")
        if not isinstance(artifacts, Sequence):
            raise ValueError("Issue-delivery workflow artifacts are unavailable")
        request_digests = {
            EXECUTOR_ARTIFACT: request.executor_artifact_sha256,
            WORKER_ISOLATION_ARTIFACT: request.worker_isolation_artifact_sha256,
        }
        trusted_paths = {
            artifact_path: self.trusted_workflow_root / PurePath(artifact_path)
            for artifact_path in workflow_artifacts(request.approval["contract_version"])
        }
        trusted_paths[EXECUTOR_ARTIFACT] = self.trusted_executor_artifact
        trusted_paths[WORKER_ISOLATION_ARTIFACT] = (
            self.trusted_worker_isolation_artifact
        )
        for artifact_path in sorted(workflow_artifacts(request.approval["contract_version"])):
            matches = [
                item
                for item in artifacts
                if isinstance(item, Mapping) and item.get("path") == artifact_path
            ]
            digest = matches[0].get("sha256") if len(matches) == 1 else None
            if (
                len(matches) != 1
                or request_digests.get(artifact_path, digest) != digest
                or not trusted_paths[artifact_path].is_file()
                or _file_sha256(trusted_paths[artifact_path]) != digest
            ):
                raise ValueError("trusted Issue-delivery artifact changed")

    def _request_destination(
        self,
        request: IssueDeliveryEffectRequest,
    ) -> FrozenIssueDeliveryDestination:
        if (
            request.destination.frozen_identity_sha256
            != self.frozen_destination.identity_sha256
            or request.destination.unfrozen() != self.frozen_destination.binding
        ):
            raise ValueError("Issue-delivery request does not match frozen destination")
        return self.frozen_destination

    @staticmethod
    def _validate_target_authority(
        request: IssueDeliveryEffectRequest,
        observed: EffectAuthorityReadback,
    ) -> None:
        expected = {
            "request_sha256": request.content_sha256,
            "repository": request.effect_repository,
            "issue_number": request.issue_number,
            "issue_body_hash": request.issue_body_hash,
            "acceptance_criteria_hash": request.acceptance_criteria_hash,
            "source_revision": request.source_revision,
            "profile_hash": request.profile_hash,
            "verification_profile_hash": request.verification_profile_hash,
            "target": request.target.model_dump(mode="json"),
        }
        if observed.model_dump(mode="json") != expected:
            raise ValueError(
                "Issue-delivery target/source/profile changed before effect"
            )

    @staticmethod
    def _effect_payload(
        request: IssueDeliveryEffectRequest,
        manifest: ProtectedDeliveryManifest,
    ) -> dict[str, Any]:
        payload = {
            "contract": request.contract,
            "request_sha256": request.content_sha256,
            "effect_slot_sha256": request.effect_slot_sha256,
            "approval_id": request.approval_id,
            "approved_operation_key": request.approved_operation_key,
            "repository": request.repository,
            "issue_number": request.issue_number,
            "issue_body_hash": request.issue_body_hash,
            "acceptance_criteria_hash": request.acceptance_criteria_hash,
            "run_id": request.run_id,
            "effect_kind": request.effect_kind,
            "source_revision": request.source_revision,
            "workflow_hash": request.workflow_hash,
            "profile_hash": request.profile_hash,
            "verification_profile_hash": request.verification_profile_hash,
            "authority_epoch": request.authority_epoch,
            "destination_identity_sha256": request.destination.frozen_identity_sha256,
            "worker_isolation_binding_sha256": _canonical_hash(
                request.worker_isolation.model_dump(mode="json")
            ),
            "executor_artifact_sha256": request.executor_artifact_sha256,
            "worker_isolation_artifact_sha256": request.worker_isolation_artifact_sha256,
            "protected_manifest_sha256": manifest.content_sha256,
            "protected_manifest_blob_sha": manifest.blob_sha,
            # These exact key names are the existing control plane's admitted
            # opaque credential metadata.  No resolved bearer value crosses
            # into the transaction/outbox payload.
            "credential_id": manifest.credential_id,
            "rotation_generation": manifest.credential_generation,
            "target": request.target.model_dump(mode="json"),
        }
        if delivery_source_pair(request.approval):
            payload["approval_manifest_hash"] = request.approval["approval_manifest_hash"]
            payload["delivery_sources"] = delivery_source_pair(request.approval)
            payload["effect_repository"] = request.effect_repository
            payload["target_policies_sha256"] = _canonical_hash(request.approval["target_policies"])
        _safe_receipt_value(payload)
        return payload

    @staticmethod
    def _validate_persisted_manifest(
        status: Mapping[str, Any],
        manifest: ProtectedDeliveryManifest,
    ) -> None:
        payload = status.get("payload")
        if (
            not isinstance(payload, Mapping)
            or payload.get("protected_manifest_sha256") != manifest.content_sha256
            or payload.get("protected_manifest_blob_sha") != manifest.blob_sha
            or payload.get("credential_id") != manifest.credential_id
            or payload.get("rotation_generation") != manifest.credential_generation
        ):
            raise ValueError("protected repository manifest changed before effect")

    @staticmethod
    def _validate_recovery_intent(
        status: Mapping[str, Any],
        request: IssueDeliveryEffectRequest,
        effect_type: str,
        operation_key: str,
    ) -> None:
        payload = status.get("payload")
        if (
            status.get("operation_key") != operation_key
            or status.get("effect_type") != effect_type
            or not isinstance(payload, Mapping)
            or payload.get("contract") != request.contract
            or payload.get("request_sha256") != request.content_sha256
            or payload.get("effect_slot_sha256") != request.effect_slot_sha256
            or payload.get("approval_id") != request.approval_id
            or payload.get("approved_operation_key") != request.approved_operation_key
            or payload.get("repository") != request.repository
            or payload.get("issue_number") != request.issue_number
            or payload.get("run_id") != request.run_id
            or payload.get("effect_kind") != request.effect_kind
            or payload.get("destination_identity_sha256")
            != request.destination.frozen_identity_sha256
            or payload.get("worker_isolation_binding_sha256")
            != _canonical_hash(request.worker_isolation.model_dump(mode="json"))
            or payload.get("target") != request.target.model_dump(mode="json")
            or not isinstance(payload.get("protected_manifest_sha256"), str)
            or not isinstance(payload.get("protected_manifest_blob_sha"), str)
        ):
            raise ValueError("Issue-delivery recovery intent is foreign or changed")
        if delivery_source_pair(request.approval) and (
            payload.get("delivery_sources") != delivery_source_pair(request.approval)
            or payload.get("effect_repository") != request.effect_repository
            or payload.get("target_policies_sha256") != _canonical_hash(request.approval["target_policies"])
            or payload.get("approval_manifest_hash") != request.approval["approval_manifest_hash"]
        ):
            raise ValueError("Issue-delivery recovery authority binding changed")

    @staticmethod
    def _validate_intent(
        status: Mapping[str, Any],
        request: IssueDeliveryEffectRequest,
        effect_type: str,
        payload: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        if (
            status.get("operation_key") != operation_key
            or status.get("effect_type") != effect_type
            or status.get("effect_slot_sha256", request.effect_slot_sha256)
            != request.effect_slot_sha256
            or not isinstance(status.get("payload"), Mapping)
            or dict(status["payload"]) != dict(payload)
        ):
            raise ValueError("Issue-delivery outbox intent is foreign or changed")

    @staticmethod
    def _claim_expiry(claim: Mapping[str, Any]) -> datetime:
        expires_at = claim.get("expires_at")
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Issue-delivery effect claim expiry is malformed") from exc
        if expiry.tzinfo is None:
            raise ValueError("Issue-delivery effect claim expiry is not timezone-aware")
        return expiry.astimezone(timezone.utc)

    @classmethod
    def _validate_effect_claim(
        cls,
        claim: Mapping[str, Any],
        operation_key: str,
        effect_type: str,
        payload: Mapping[str, Any],
        *,
        repository: str,
    ) -> None:
        expiry = cls._claim_expiry(claim)
        fencing_token = claim.get("fencing_token")
        receipt_sequence = claim.get("receipt_sequence")
        if (
            claim.get("repository") != canonical_repository(repository)
            or claim.get("operation_key") != operation_key
            or claim.get("effect_type") != effect_type
            or claim.get("effect_eligible") is not True
            or not isinstance(claim.get("task_id"), str)
            or not claim["task_id"]
            or not isinstance(claim.get("worker_id"), str)
            or not claim["worker_id"]
            or not isinstance(fencing_token, int)
            or isinstance(fencing_token, bool)
            or fencing_token < 1
            or not isinstance(receipt_sequence, int)
            or isinstance(receipt_sequence, bool)
            or receipt_sequence < 1
            or not isinstance(claim.get("intent_lsn"), str)
            or not claim["intent_lsn"]
            or not isinstance(claim.get("claim_lsn"), str)
            or not claim["claim_lsn"]
            or expiry <= datetime.now(timezone.utc)
            or not isinstance(claim.get("payload"), Mapping)
            or dict(claim["payload"]) != dict(payload)
        ):
            raise ValueError("Issue-delivery effect claim is not exact authority")

    @classmethod
    def _validate_revalidated_effect_claim(
        cls,
        current: Mapping[str, Any],
        original: Mapping[str, Any],
        operation_key: str,
        effect_type: str,
        payload: Mapping[str, Any],
        *,
        repository: str,
    ) -> None:
        missing = _EFFECT_CLAIM_IDENTITY_FIELDS.difference(current)
        if missing:
            raise ValueError("fresh Issue-delivery effect fence is incomplete")
        for field in _EFFECT_CLAIM_IDENTITY_FIELDS - {"expires_at"}:
            if current.get(field) != original.get(field):
                raise ValueError("Issue-delivery effect fence changed before transport")
        if cls._claim_expiry(current) != cls._claim_expiry(original):
            raise ValueError("Issue-delivery effect fence changed before transport")
        merged = {**original, **current}
        cls._validate_effect_claim(
            merged,
            operation_key,
            effect_type,
            payload,
            repository=repository,
        )

    @staticmethod
    def _validate_readback_claim(
        claim: Mapping[str, Any],
        operation_key: str,
        effect_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        if (
            claim.get("operation_key") != operation_key
            or claim.get("effect_type") != effect_type
            or claim.get("readback_only") is not True
            or claim.get("effect_eligible") is not False
            or claim.get("recovery_kind")
            not in {"original_attempt", "recovered_attempt"}
            or not isinstance(claim.get("payload"), Mapping)
            or dict(claim["payload"]) != dict(payload)
        ):
            raise ValueError("Issue-delivery readback fence is not exact")

    @staticmethod
    def _validate_dispatch_commit(
        committed: Mapping[str, Any],
        original: Mapping[str, Any],
        operation_key: str,
    ) -> None:
        if committed.get("status") != "unknown":
            raise ValueError("Issue-delivery dispatch commit is not durable")
        for field in _EFFECT_CLAIM_IDENTITY_FIELDS:
            if committed.get(field) != original.get(field):
                raise ValueError("Issue-delivery dispatch commit fence changed")

    def _record_known_no_effect(
        self,
        claim: Mapping[str, Any],
        request: IssueDeliveryEffectRequest,
        *,
        reason: str,
    ) -> None:
        self.ledger.mark_unknown(claim, detail="effect refused before transport")
        readback_claim = self.ledger.claim_for_readback(str(claim["operation_key"]))
        payload = claim.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("Issue-delivery effect claim lost its exact payload")
        self._validate_readback_claim(
            readback_claim,
            str(claim["operation_key"]),
            _EFFECT_TYPES[request.effect_kind],
            payload,
        )
        self.ledger.reconcile(
            readback_claim,
            observed_applied=False,
            evidence={
                "outcome": "not_applied",
                "request_sha256": request.content_sha256,
                "transport_invoked": False,
                "reason_class": reason,
            },
        )

    @staticmethod
    def _receipt(
        outcome: Literal["applied", "retry_after_readback", "unknown"],
        operation_key: str,
        request: IssueDeliveryEffectRequest,
        readback: Mapping[str, object],
    ) -> IssueDeliveryEffectReceipt:
        _safe_receipt_value(readback)
        return IssueDeliveryEffectReceipt(
            outcome=outcome,
            operation_key=operation_key,
            request_sha256=request.content_sha256,
            effect_kind=request.effect_kind,
            repository=request.repository,
            issue_number=request.issue_number,
            destination_identity_sha256=request.destination.frozen_identity_sha256,
            worker_isolation_receipt_sha256=request.worker_isolation.receipt_sha256,
            readback=dict(readback),
            delivery_sources=delivery_source_pair(request.approval) or None,
        )


class GitIssueDeliveryDestination:
    """Host-owned preparation and identity freeze for a linked worktree."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.runner = runner

    def prepare(self, approval: Mapping[str, Any]) -> FrozenIssueDeliveryDestination:
        binding = DestinationBinding.from_approval(approval)
        if not binding.checkout.is_dir():
            raise ValueError("approved Issue-delivery checkout is absent")
        # Admission/start may only use a destination that the owner/release
        # path prepared beforehand.  This method freezes and verifies the
        # destination; it must never create directories, branches, or
        # worktrees before authenticated approval and a durable reservation.
        if not binding.worktree.is_dir():
            raise ValueError("approved Issue-delivery worktree is absent; prepare it before admission")
        frozen = self._observe(binding, require_base_head=True)
        try:
            approved_destination = _approved_destination_manifest(approval)
        except ValueError as exc:
            raise ValueError("prepared destination differs from approval") from exc
        if approved_destination != frozen.binding.as_manifest():
            raise ValueError("prepared destination differs from approval")
        if frozen.binding.repository != approval.get("repository"):
            raise ValueError("prepared destination differs from approval")
        return frozen

    def assert_frozen(
        self,
        frozen: FrozenIssueDeliveryDestination,
        approval: Mapping[str, Any],
    ) -> None:
        try:
            approved_destination = _approved_destination_manifest(approval)
        except ValueError as exc:
            raise ValueError(
                "frozen Issue-delivery destination is not approved"
            ) from exc
        if (
            approved_destination != frozen.binding.as_manifest()
            or frozen.binding.repository != approval.get("repository")
        ):
            raise ValueError("frozen Issue-delivery destination is not approved")
        try:
            observed = self._observe(frozen.binding, require_base_head=False)
        except Exception as exc:
            raise ValueError("Issue-delivery destination Git identity changed") from exc
        if observed != frozen:
            raise ValueError("Issue-delivery destination Git identity changed")

    def recover(self, approval: Mapping[str, Any], identity_sha256: str) -> FrozenIssueDeliveryDestination:
        """Observe retained topology, not a clean-base preparation or Git repair."""
        frozen = self._observe(DestinationBinding.from_approval(approval), require_base_head=False)
        if frozen.identity_sha256 != identity_sha256:
            raise ValueError("retained candidate destination identity changed")
        self.assert_frozen(frozen, approval)
        return frozen

    def _observe(
        self,
        binding: DestinationBinding,
        *,
        require_base_head: bool,
    ) -> FrozenIssueDeliveryDestination:
        checkout = Path(
            self._git(binding.checkout, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
        worktree = Path(
            self._git(binding.worktree, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
        checkout_common = Path(
            self._git(
                binding.checkout,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ).stdout.strip()
        ).resolve()
        worktree_common = Path(
            self._git(
                binding.worktree,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ).stdout.strip()
        ).resolve()
        git_directory = Path(
            self._git(
                binding.worktree,
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
            ).stdout.strip()
        ).resolve()
        branch = self._git(binding.worktree, "branch", "--show-current").stdout.strip()
        head = self._git(binding.worktree, "rev-parse", "HEAD").stdout.strip().lower()
        origin = self._git(
            binding.worktree, "remote", "get-url", "origin"
        ).stdout.strip()
        if (
            checkout != binding.checkout.resolve(strict=True)
            or worktree != binding.worktree.resolve(strict=True)
            or checkout_common != worktree_common
            or branch != binding.branch
            or (require_base_head and head != binding.base_sha)
            or self._git(
                binding.worktree,
                "merge-base",
                "--is-ancestor",
                binding.base_sha,
                "HEAD",
                check=False,
            ).returncode
            != 0
            or _repository_from_remote(origin) != binding.repository
        ):
            raise ValueError("Issue-delivery destination Git identity is not exact")
        return FrozenIssueDeliveryDestination.capture(
            binding,
            git_directory=git_directory,
            common_git_directory=worktree_common,
            origin_url=origin,
        )

    def _git(
        self,
        cwd: Path,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = self.runner(
            ["git", "-C", str(cwd), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise ValueError("Issue-delivery destination Git preflight failed")
        return result


def _repository_from_remote(remote: str) -> str:
    parsed = urlsplit(remote)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Issue-delivery origin must be credential-free GitHub HTTPS")
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return canonical_repository(path)


class BuilderOpsIssueDeliveryEffectLedger:
    """Issue-delivery adapter over the existing authenticated task/outbox API."""

    def __init__(
        self,
        client: BuilderOpsControlPlaneClient,
        *,
        repository: str,
        run_id: str,
        approval_id: str,
        worker_id: str,
        claim_ttl_seconds: int = 300,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if claim_ttl_seconds <= 0:
            raise ValueError("Issue-delivery outbox claim TTL must be positive")
        self.client = client
        self.repository = canonical_repository(repository)
        self.run_id = run_id
        self.approval_id = approval_id
        self.worker_id = worker_id
        self.claim_ttl_seconds = claim_ttl_seconds
        self.clock = clock
        self.envelope = {
            "repository": self.repository,
            "scope": "issue-delivery-executor",
            "stack": "builderops-control-plane",
            "source_refs": [f"issue-delivery-approval:{approval_id}"],
            "schema_version": 1,
        }
        self.outbox = BuilderOpsOutboxExecutor(
            client,
            repository=self.repository,
            worker_id=worker_id,
            source_ref=f"issue-delivery-approval:{approval_id}",
            scope="issue-delivery-executor",
            claim_ttl_seconds=claim_ttl_seconds,
        )
        self._claims: dict[str, Mapping[str, Any]] = {}
        self._claim_recovery_kinds: dict[str, str] = {}

    @staticmethod
    def _task_id(effect_slot_sha256: str) -> str:
        return f"issue-delivery-effect:{effect_slot_sha256}"

    def operation_key(
        self, *, effect_slot_sha256: str, effect_type: str
    ) -> str:
        return _canonical_hash(
            {
                "repository": self.repository,
                "idempotency_key": f"delivery-effect-intent:{effect_slot_sha256}",
                "effect_type": effect_type,
            }
        )

    def _ensure_task_claim(
        self,
        *,
        task_id: str,
        effect_slot_sha256: str,
    ) -> Mapping[str, Any]:
        initial = {
            "contract": CONTRACT,
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "repository": self.repository,
            "effect_slot_sha256": effect_slot_sha256,
        }
        try:
            self.client.get_task(repository=self.repository, task_id=task_id)
        except ControlPlaneNotFoundError:
            self.client.transition_task(
                envelope=self.envelope,
                task_id=task_id,
                to_state="ready",
                idempotency_key=f"delivery-effect-ingest:{effect_slot_sha256}",
                request=initial,
            )
        claimed = self.client.claim_task(
            envelope=self.envelope,
            task_id=task_id,
            idempotency_key=f"delivery-effect-claim:{effect_slot_sha256}",
            request=initial,
        )
        lease = claimed.get("lease")
        if not isinstance(lease, Mapping):
            raise ValueError("Issue-delivery effect task lease is unavailable")
        return lease

    def begin(
        self,
        *,
        effect_slot_sha256: str,
        effect_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        operation_key = self.operation_key(
            effect_slot_sha256=effect_slot_sha256,
            effect_type=effect_type,
        )
        task_id = self._task_id(effect_slot_sha256)
        existing = self.status(operation_key)
        if existing.get("status") != "missing":
            if (
                existing.get("task_id") != task_id
                or existing.get("effect_type") != effect_type
                or existing.get("payload") != dict(payload)
            ):
                raise ValueError("existing Issue-delivery effect intent is foreign")
            return operation_key
        lease = self._ensure_task_claim(
            task_id=task_id,
            effect_slot_sha256=effect_slot_sha256,
        )
        task = self.client.get_task(repository=self.repository, task_id=task_id)
        result = self.client.transition_task(
            envelope=self.envelope,
            task_id=task_id,
            to_state="claimed",
            idempotency_key=f"delivery-effect-intent:{effect_slot_sha256}",
            request={
                "contract": CONTRACT,
                "approval_id": self.approval_id,
                "run_id": self.run_id,
                "effect_slot_sha256": effect_slot_sha256,
                "effect_type": effect_type,
            },
            outbox={"effect_type": effect_type, "payload": dict(payload)},
            lease=lease,
            expected_states=("claimed",),
            expected_version=int(task["version"]),
        )
        committed = result.get("result")
        if (
            not isinstance(committed, Mapping)
            or committed.get("operation_key") != operation_key
        ):
            raise ValueError("BuilderOps returned inconsistent effect identity")
        return operation_key

    def status(self, operation_key: str) -> Mapping[str, Any]:
        return self.outbox.status(operation_key)

    def claim_effect(
        self,
        operation_key: str,
        *,
        effect_type: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        claim = self.outbox.claim(operation_key)
        if claim.get("effect_type") != effect_type or claim.get("payload") != dict(
            payload
        ):
            raise ValueError("BuilderOps returned foreign effect claim")
        self._claims[operation_key] = dict(claim)
        self._claim_recovery_kinds[operation_key] = "original_attempt"
        return claim

    def claim_for_readback(self, operation_key: str) -> Mapping[str, Any]:
        status = self.status(operation_key)
        claim = self._claims.get(operation_key)
        recovery_kind = self._claim_recovery_kinds.get(
            operation_key, "original_attempt"
        )
        if claim is not None and not self._claim_is_current(claim):
            self._claims.pop(operation_key, None)
            self._claim_recovery_kinds.pop(operation_key, None)
            claim = None
        if claim is None:
            claim = dict(self.outbox.recover(operation_key))
            self._claims[operation_key] = claim
            recovery_kind = "recovered_attempt"
            self._claim_recovery_kinds[operation_key] = recovery_kind
        normalized = {key: claim[key] for key in _READBACK_CLAIM_FIELDS if key in claim}
        normalized.setdefault("effect_type", status.get("effect_type"))
        normalized.setdefault("payload", status.get("payload"))
        normalized["readback_only"] = True
        normalized["effect_eligible"] = False
        normalized["recovery_kind"] = recovery_kind
        if not _READBACK_CLAIM_FIELDS.issubset(normalized):
            raise ValueError("BuilderOps readback fence is incomplete")
        return normalized

    def revalidate_effect_claim(
        self, claim: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return self.outbox.revalidate_effect(claim)

    def _claim_is_current(self, claim: Mapping[str, Any]) -> bool:
        expires_at = claim.get("expires_at")
        if not isinstance(expires_at, str):
            return False
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return expiry > now.astimezone(timezone.utc)

    def mark_unknown(
        self, claim: Mapping[str, Any], *, detail: str
    ) -> Mapping[str, Any]:
        return self.outbox.mark_unknown(claim, detail=detail)

    def reconcile(
        self,
        claim: Mapping[str, Any],
        *,
        observed_applied: bool,
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if (
            claim.get("readback_only") is not True
            or claim.get("effect_eligible") is not False
        ):
            raise ValueError(
                "Issue-delivery reconciliation requires readback-only fence"
            )
        known_no_effect = evidence.get("transport_invoked") is False
        if not observed_applied and not known_no_effect:
            return {
                "status": "unknown",
                "retry_refused": "committed-dispatch-may-still-complete",
            }
        result = self.outbox.reconcile(
            claim,
            observed_applied=observed_applied,
            evidence=evidence,
        )
        self._claims.pop(str(claim["operation_key"]), None)
        self._claim_recovery_kinds.pop(str(claim["operation_key"]), None)
        return result


class ContentOnlyIssueDeliverySessionLauncher(LinuxSystemdCodexIssueSessionLauncher):
    """The #5559 OS-principal launcher with a closed content-only prompt."""

    def prompt(self, context_pack: Mapping[str, Any]) -> str:
        if context_pack.get("delivery_sources", {}).get("contract_version") == CANDIDATE_CONTRACT_VERSION:
            return ("Edit only the approved documentation content. Git administration and all effects belong to the host. "
                    "Return only JSON with contract=builderops.issue-delivery-content-result.v1, status=completed|failed, "
                    "summary, validation=[{name,outcome=passed|failed|not_run,summary}]. No identities or effect proposals.\n"
                    + json.dumps(context_pack, sort_keys=True))
        try:
            serialized = json.dumps(
                context_pack,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Issue-delivery context pack is not JSON") from exc
        return (
            "Use the registered slice_implementer execution role as a content-only worker.\n"
            f"{self.developer_instructions}\n"
            "Implement and validate only the approved repository content change. You must not run Git or GitHub lifecycle effects, write Git metadata, resolve repository credentials, claim or close an Issue, publish a branch or PR, or merge. The host independently claims the approved Issue before this worker enters. When a later host effect is needed, propose only typed publication, merge, closure, or exact parent-evidence requests in an optional effect_requests list; each item must contain only effect_kind and its complete typed target. The protected host executor binds the approved request fields and owns every effect after fresh revalidation. Return content-change and validation evidence without claiming delivery.\n"
            f"{serialized}\n"
        )


@dataclass(frozen=True)
class PreparedIssueDeliveryWorker:
    """Host prepares/freezes destination before constructing the child launcher."""

    approval: Mapping[str, Any]
    destination: GitIssueDeliveryDestination
    frozen_destination: FrozenIssueDeliveryDestination
    launcher: ContentOnlyIssueDeliverySessionLauncher

    @classmethod
    def create(
        cls,
        *,
        approval: Mapping[str, Any],
        destination: GitIssueDeliveryDestination,
        launcher_factory: Callable[
            [FrozenIssueDeliveryDestination],
            ContentOnlyIssueDeliverySessionLauncher,
        ],
    ) -> "PreparedIssueDeliveryWorker":
        frozen = destination.prepare(approval)
        launcher = launcher_factory(frozen)
        if not isinstance(launcher, ContentOnlyIssueDeliverySessionLauncher):
            raise ValueError("Issue-delivery child lacks the content-only OS boundary")
        return cls(
            approval=dict(approval),
            destination=destination,
            frozen_destination=frozen,
            launcher=launcher,
        )

    def launch(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
        on_entry: Callable[[str], None] | None = None,
        effect_gate: Callable[..., Mapping[str, Any]] | None = None,
        pre_process_entry: Callable[[], None] | None = None,
        pre_spawn_entry: Callable[[], None] | None = None,
    ) -> Mapping[str, Any]:
        plan = context_pack.get("branch_worktree_plan")
        if not isinstance(plan, Mapping) or not isinstance(plan.get("worktree"), str):
            raise ValueError("Issue-delivery context targets another worktree")
        # Preserve the frozen Git/topology fence before accepting any textual
        # spelling of the plan path. A missing or replaced worktree remains a
        # destination failure, not a path-alias compatibility case.
        self.destination.assert_frozen(self.frozen_destination, self.approval)
        try:
            planned_worktree = Path(str(plan["worktree"])).resolve(strict=True)
            approved_worktree = Path(
                str(
                    self.approval["destination"].get(
                        "resolved_worktree",
                        self.approval["destination"]["worktree"],
                    )
                )
            ).resolve(strict=True)
        except (KeyError, OSError, TypeError) as exc:
            raise ValueError("Issue-delivery context targets another worktree") from exc
        if (
            planned_worktree != self.frozen_destination.binding.worktree
            or approved_worktree != self.frozen_destination.binding.worktree
        ):
            raise ValueError("Issue-delivery context targets another worktree")
        launch_kwargs: dict[str, Any] = {
            "execution_routing": execution_routing,
        }
        if on_entry is not None:
            launch_kwargs["on_entry"] = on_entry
        if effect_gate is not None:
            launch_kwargs["effect_gate"] = effect_gate
        if pre_process_entry is not None:
            launch_kwargs["pre_process_entry"] = pre_process_entry
        if pre_spawn_entry is not None:
            launch_kwargs["pre_spawn_entry"] = pre_spawn_entry
        return dict(self.launcher.launch(context_pack, **launch_kwargs))


@dataclass(frozen=True)
class HostIssueDeliveryExecutorRuntime:
    """Host-installed dependencies for the sole production effect executor.

    This object is installed by the privileged process bootstrap, never parsed
    from a worker context, CLI argument, or ``module:callable`` environment
    selector.  The repository package intentionally supplies no default: an
    unconfigured host cannot cross an Issue-delivery effect gate.
    """

    repository_authority: IssueDeliveryRepositoryAuthority
    credentials: HostCredentialResolver
    transport: IssueDeliveryEffectTransport
    isolation_profile_sha256: str
    live_binding_reader: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    worker_id: str = "issue-delivery-host"
    trusted_workflow_root: Path | None = None
    completion_reader: Callable[[str], Mapping[str, Any]] | None = None


_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME: HostIssueDeliveryExecutorRuntime | None = None


def install_host_issue_delivery_executor_runtime(
    runtime: HostIssueDeliveryExecutorRuntime,
) -> None:
    """Install one host-owned composition before accepting production CLI work."""

    global _HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME
    if _HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME is not None:
        raise ValueError("Issue-delivery host executor runtime is already installed")
    if not isinstance(runtime, HostIssueDeliveryExecutorRuntime):
        raise ValueError("Issue-delivery host executor runtime is invalid")
    if not runtime.worker_id.strip():
        raise ValueError("Issue-delivery host executor worker identity is required")
    if (
        len(runtime.isolation_profile_sha256) != 64
        or any(character not in "0123456789abcdef" for character in runtime.isolation_profile_sha256)
    ):
        raise ValueError("Issue-delivery host executor profile hash is invalid")
    _HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME = runtime


def build_host_issue_delivery_executor(
    *,
    approval: Mapping[str, Any],
    client: BuilderOpsControlPlaneClient,
    prepared: PreparedIssueDeliveryWorker | None = None,
) -> IssueDeliveryHostExecutor:
    """Build the fixed host-owned executor used by ``dispatch-sessions``.

    There is deliberately no pluggable factory reference at this boundary.
    Deployment/bootstrap may install one typed dependency bundle, while CLI
    users and worker input can only select the already approved operation.
    """

    runtime = _HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME
    if runtime is None:
        raise ValueError("Issue-delivery host executor runtime is unavailable")
    terminal = None
    if prepared is None:
        if approval.get("contract_version") != CANDIDATE_CONTRACT_VERSION or runtime.completion_reader is None:
            raise ValueError("candidate readback composition is unavailable")
        terminal = client.issue_delivery_operation_record_read(
            repository=str(approval["repository"]),
            record_id=f"issue-delivery-terminal:{approval['operation_key']}")
        if (not terminal or terminal["payload"].get("schema") != "builderops.issue-delivery-terminal.v2"
            or terminal["payload"].get("approval_id") != approval["approval_id"]
            or terminal["payload"].get("approval_manifest_hash") != approval["approval_manifest_hash"]
            or not terminal["payload"].get("candidate_binding")):
            raise ValueError("authenticated candidate terminal is unavailable")
        destination = GitIssueDeliveryDestination()
        frozen = destination.recover(approval, terminal["payload"]["candidate_binding"]["completion"]["destination_sha256"])
    elif type(prepared) is not PreparedIssueDeliveryWorker:
        raise ValueError("Issue-delivery prepared worker is invalid")
    elif dict(prepared.approval) != dict(approval):
        raise ValueError("Issue-delivery prepared worker is bound to another approval")
    if prepared is not None:
        if not isinstance(prepared.launcher, ContentOnlyIssueDeliverySessionLauncher):
            raise ValueError("Issue-delivery prepared worker launcher is invalid")
        if prepared.launcher.expected_profile_sha256 != runtime.isolation_profile_sha256:
            raise ValueError("Issue-delivery prepared worker profile differs from host pin")
        destination, frozen = prepared.destination, prepared.frozen_destination
    if approval.get("contract_version") == CANDIDATE_CONTRACT_VERSION:
        if runtime.completion_reader is None:
            raise ValueError("Issue-delivery host completion observer is unavailable")
        if prepared is not None:
            prepared.launcher._completion_reader = runtime.completion_reader
    repository = canonical_repository(str(approval.get("repository", "")))
    destination_data = approval.get("destination")
    if not isinstance(destination_data, Mapping):
        raise ValueError("Issue-delivery approval destination is unavailable")
    executor = IssueDeliveryHostExecutor(
        authority=client,
        ledger=BuilderOpsIssueDeliveryEffectLedger(
            client,
            repository=repository,
            run_id=str(destination_data.get("run_id", "")),
            approval_id=str(approval.get("approval_id", "")),
            worker_id=runtime.worker_id,
        ),
        repository_authority=runtime.repository_authority,
        credentials=runtime.credentials,
        destination=destination,
        frozen_destination=frozen,
        transport=runtime.transport,
        prepared_worker=prepared,
        completion_reader=runtime.completion_reader,
        expected_isolation_profile_sha256=runtime.isolation_profile_sha256,
        live_binding_reader=runtime.live_binding_reader,
        **({"trusted_workflow_root": runtime.trusted_workflow_root,
            "trusted_executor_artifact": runtime.trusted_workflow_root / EXECUTOR_ARTIFACT,
            "trusted_worker_isolation_artifact": runtime.trusted_workflow_root / WORKER_ISOLATION_ARTIFACT}
           if runtime.trusted_workflow_root is not None else {}),
    )
    if terminal is not None:
        executor.restore_candidate_binding(terminal)
    return executor


__all__ = [
    "BuilderOpsIssueDeliveryEffectLedger",
    "HostIssueDeliveryExecutorRuntime",
    "ContentOnlyIssueDeliverySessionLauncher",
    "DestinationBinding",
    "EffectAuthorityReadback",
    "EffectReadback",
    "FrozenIssueDeliveryDestination",
    "GitIssueDeliveryDestination",
    "IssueDeliveryEffectReceipt",
    "IssueDeliveryEffectRequest",
    "IssueDeliveryHostExecutor",
    "PreparedIssueDeliveryWorker",
    "WorkerIsolationBinding",
    "build_host_issue_delivery_executor",
    "install_host_issue_delivery_executor_runtime",
]
