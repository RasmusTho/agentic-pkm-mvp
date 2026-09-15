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
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ControlPlaneNotFoundError,
)
from app.builderops.control_plane.models import canonical_repository
from app.builderops.issue_delivery_worker_isolation import (
    ISOLATION_RECEIPT_CONTRACT,
    LinuxSystemdCodexIssueSessionLauncher,
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
    "claim": "github.issue-delivery.claim.v1",
    "publication": "github.issue-delivery.publication.v1",
    "merge": "github.issue-delivery.merge.v1",
    "closure": "github.issue-delivery.closure.v1",
    "parent_evidence": "github.issue-delivery.parent-evidence.v1",
}
_PERMISSIONS = {
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
        return cls.model_validate({"repository": repository, **dict(destination)})

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


class PublicationTarget(_StrictModel):
    kind: Literal["publication"]
    issue_number: int = Field(gt=0)
    branch: str = Field(min_length=1, max_length=512)
    base_ref: str = Field(min_length=1, max_length=256)
    base_sha: str = Field(pattern=_HEX_40)
    head_sha: str = Field(pattern=_HEX_40)
    title_sha256: str = Field(pattern=_HEX_64)
    body_sha256: str = Field(pattern=_HEX_64)
    expected_remote_ref_state: Literal["absent"]


class MergeTarget(_StrictModel):
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


class IssueDeliveryEffectRequest(_StrictModel):
    contract: Literal["builderops.issue-delivery-effect.v1"]
    effect_kind: Literal["claim", "publication", "merge", "closure", "parent_evidence"]
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
    target: EffectTarget

    @field_validator("repository")
    @classmethod
    def _repository(cls, value: str) -> str:
        return canonical_repository(value)

    @model_validator(mode="after")
    def _closed_identity(self) -> "IssueDeliveryEffectRequest":
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


class EffectReadback(_StrictModel):
    request_sha256: str = Field(pattern=_HEX_64)
    outcome: Literal["applied", "not_applied", "unknown"]
    evidence: EffectReadbackEvidence


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
        return value


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
    def operation_key(self, *, request_sha256: str, effect_type: str) -> str: ...

    def begin(
        self,
        *,
        request_sha256: str,
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

    def mark_unknown(self, claim: Mapping[str, Any], *, detail: str) -> None: ...

    def reconcile(
        self,
        claim: Mapping[str, Any],
        *,
        observed_applied: bool,
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


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
        worker_isolation: WorkerIsolationBinding,
        transport: IssueDeliveryEffectTransport,
        trusted_executor_artifact: Path = Path(__file__),
        trusted_worker_isolation_artifact: Path = Path(__file__).with_name(
            "issue_delivery_worker_isolation.py"
        ),
    ) -> None:
        self.authority = authority
        self.ledger = ledger
        self.repository_authority = repository_authority
        self.credentials = credentials
        self.destination = destination
        self.frozen_destination = frozen_destination
        self.worker_isolation = worker_isolation
        self.transport = transport
        self.trusted_executor_artifact = trusted_executor_artifact.resolve()
        self.trusted_worker_isolation_artifact = (
            trusted_worker_isolation_artifact.resolve()
        )

    def execute(
        self, request: IssueDeliveryEffectRequest
    ) -> IssueDeliveryEffectReceipt:
        self._validate_static_request(request, current_artifacts=False)
        frozen = self._request_destination(request)
        effect_type = _EFFECT_TYPES[request.effect_kind]
        operation_key = self.ledger.operation_key(
            request_sha256=request.content_sha256,
            effect_type=effect_type,
        )
        status = self.ledger.status(operation_key)
        state = status.get("status")
        if state != "missing":
            self._validate_recovery_intent(status, request, effect_type, operation_key)
            if state == "succeeded":
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
                request_sha256=request.content_sha256,
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
            self._validate_target_authority(
                request,
                self.transport.validate_target(request),
            )
        except Exception as exc:
            self._record_known_no_effect(claim, request, reason=type(exc).__name__)
            raise
        credential = self.credentials.resolve(
            repository=request.repository,
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
        try:
            self.transport.apply(request, credential)
            detail = "effect transport returned; source readback required"
        except Exception as exc:
            detail = f"effect outcome unknown: {type(exc).__name__}"
        return self._mark_unknown_and_readback(
            claim,
            operation_key,
            request,
            detail=detail,
        )

    def _mark_unknown_and_readback(
        self,
        claim: Mapping[str, Any],
        operation_key: str,
        request: IssueDeliveryEffectRequest,
        *,
        detail: str,
    ) -> IssueDeliveryEffectReceipt:
        try:
            self.ledger.mark_unknown(claim, detail=detail)
        except Exception:
            # This is a retry of the local, fenced state transition only.  It
            # never calls the external effect transport again.  Read status
            # before and after so a lost response converges on durable unknown.
            status = self.ledger.status(operation_key)
            if status.get("status") == "claimed":
                try:
                    self.ledger.mark_unknown(claim, detail=detail)
                except Exception:
                    pass
            status = self.ledger.status(operation_key)
            if status.get("status") != "unknown":
                return self._receipt(
                    "unknown",
                    operation_key,
                    request,
                    {"outcome": "unknown", "readback": "durable-fence-unavailable"},
                )
        return self._readback_and_reconcile(operation_key, request)

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
        manifest = self.repository_authority.delivery_manifest(
            request.repository,
            request.destination.base_sha,
        )
        if (
            manifest.repository != request.repository
            or manifest.base_sha != request.destination.base_sha
            or _EFFECT_TYPES[request.effect_kind] not in manifest.allowed_effects
        ):
            raise ValueError("protected repository manifest does not authorize effect")
        return manifest

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
        if (
            approval.get("contract_version") != "fca-issue-delivery.v1"
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
            or approval.get("destination")
            != request.destination.unfrozen().as_manifest()
            or _PERMISSIONS[request.effect_kind]
            not in set(approval.get("permitted_effects", ()))
            or request.worker_isolation != self.worker_isolation
        ):
            raise ValueError("Issue-delivery request does not match exact approval")
        target = request.target
        if isinstance(
            target, (ClaimTarget, PublicationTarget, MergeTarget, ClosureTarget)
        ):
            if target.issue_number != request.issue_number:
                raise ValueError("Issue-delivery target addresses another Issue")
        if isinstance(target, ClaimTarget) and target.issue_node_id != issue.get(
            "node_id"
        ):
            raise ValueError("Issue-delivery claim node changed")
        if isinstance(target, (PublicationTarget, MergeTarget)) and (
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
        if not isinstance(artifacts, Sequence):
            raise ValueError("Issue-delivery workflow artifacts are unavailable")
        expected = {
            EXECUTOR_ARTIFACT: (
                request.executor_artifact_sha256,
                self.trusted_executor_artifact,
            ),
            WORKER_ISOLATION_ARTIFACT: (
                request.worker_isolation_artifact_sha256,
                self.trusted_worker_isolation_artifact,
            ),
        }
        for artifact_path, (digest, actual_path) in expected.items():
            matches = [
                item
                for item in artifacts
                if isinstance(item, Mapping) and item.get("path") == artifact_path
            ]
            if (
                len(matches) != 1
                or matches[0].get("sha256") != digest
                or _file_sha256(actual_path) != digest
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
            "repository": request.repository,
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
            "contract": CONTRACT,
            "request_sha256": request.content_sha256,
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
            or payload.get("contract") != CONTRACT
            or payload.get("request_sha256") != request.content_sha256
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
            or status.get("request_sha256", request.content_sha256)
            != request.content_sha256
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
        if not binding.worktree.exists():
            binding.worktree.parent.mkdir(parents=True, exist_ok=True)
            branch = self._git(
                binding.checkout,
                "show-ref",
                "--verify",
                f"refs/heads/{binding.branch}",
                check=False,
            )
            if branch.returncode == 0:
                raise ValueError("approved Issue-delivery branch already exists")
            self._git(
                binding.checkout,
                "worktree",
                "add",
                "-b",
                binding.branch,
                str(binding.worktree),
                binding.base_sha,
            )
        frozen = self._observe(binding, require_base_head=True)
        if frozen.binding.as_manifest() != approval.get("destination"):
            raise ValueError("prepared destination differs from approval")
        return frozen

    def assert_frozen(
        self,
        frozen: FrozenIssueDeliveryDestination,
        approval: Mapping[str, Any],
    ) -> None:
        if frozen.binding.as_manifest() != approval.get("destination"):
            raise ValueError("frozen Issue-delivery destination is not approved")
        try:
            observed = self._observe(frozen.binding, require_base_head=False)
        except Exception as exc:
            raise ValueError("Issue-delivery destination Git identity changed") from exc
        if observed != frozen:
            raise ValueError("Issue-delivery destination Git identity changed")

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

    @staticmethod
    def _task_id(request_sha256: str) -> str:
        return f"issue-delivery-effect:{request_sha256}"

    def operation_key(self, *, request_sha256: str, effect_type: str) -> str:
        return _canonical_hash(
            {
                "repository": self.repository,
                "idempotency_key": f"delivery-effect-intent:{request_sha256}",
                "effect_type": effect_type,
            }
        )

    def _ensure_task_claim(
        self,
        *,
        task_id: str,
        request_sha256: str,
    ) -> Mapping[str, Any]:
        initial = {
            "contract": CONTRACT,
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "repository": self.repository,
            "request_sha256": request_sha256,
        }
        try:
            self.client.get_task(repository=self.repository, task_id=task_id)
        except ControlPlaneNotFoundError:
            self.client.transition_task(
                envelope=self.envelope,
                task_id=task_id,
                to_state="ready",
                idempotency_key=f"delivery-effect-task-ready:{request_sha256}",
                request=initial,
            )
        claimed = self.client.claim_task(
            envelope=self.envelope,
            task_id=task_id,
            idempotency_key=f"delivery-effect-task-claim:{request_sha256}",
            request=initial,
        )
        lease = claimed.get("lease")
        if not isinstance(lease, Mapping):
            raise ValueError("Issue-delivery effect task lease is unavailable")
        return lease

    def begin(
        self,
        *,
        request_sha256: str,
        effect_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        operation_key = self.operation_key(
            request_sha256=request_sha256,
            effect_type=effect_type,
        )
        task_id = self._task_id(request_sha256)
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
            request_sha256=request_sha256,
        )
        task = self.client.get_task(repository=self.repository, task_id=task_id)
        result = self.client.transition_task(
            envelope=self.envelope,
            task_id=task_id,
            to_state="claimed",
            idempotency_key=f"delivery-effect-intent:{request_sha256}",
            request={
                "contract": CONTRACT,
                "approval_id": self.approval_id,
                "run_id": self.run_id,
                "request_sha256": request_sha256,
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
        return claim

    def claim_for_readback(self, operation_key: str) -> Mapping[str, Any]:
        status = self.status(operation_key)
        claim = self._claims.get(operation_key)
        recovery_kind = "original_attempt"
        if claim is not None and not self._claim_is_current(claim):
            self._claims.pop(operation_key, None)
            claim = None
        if claim is None:
            claim = dict(self.outbox.recover(operation_key))
            self._claims[operation_key] = claim
            recovery_kind = "recovered_attempt"
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

    def mark_unknown(self, claim: Mapping[str, Any], *, detail: str) -> None:
        self.outbox.mark_unknown(claim, detail=detail)

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
        result = self.outbox.reconcile(
            claim,
            observed_applied=observed_applied,
            evidence=evidence,
        )
        self._claims.pop(str(claim["operation_key"]), None)
        return result


class ContentOnlyIssueDeliverySessionLauncher(LinuxSystemdCodexIssueSessionLauncher):
    """The #5559 OS-principal launcher with a closed content-only prompt."""

    def prompt(self, context_pack: Mapping[str, Any]) -> str:
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
            "Implement and validate only the approved repository content change. You must not run Git or GitHub lifecycle effects, write Git metadata, resolve repository credentials, claim or close an Issue, publish a branch or PR, or merge. When a host effect is needed, propose only typed claim, publication, merge, closure, or exact parent-evidence requests matching builderops.issue-delivery-effect.v1. The protected host executor owns every such effect after fresh revalidation. Return content-change and validation evidence without claiming delivery.\n"
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
    ) -> Mapping[str, Any]:
        plan = context_pack.get("branch_worktree_plan")
        if not isinstance(plan, Mapping) or plan.get("worktree") != str(
            self.frozen_destination.binding.worktree
        ):
            raise ValueError("Issue-delivery context targets another worktree")
        self.destination.assert_frozen(self.frozen_destination, self.approval)
        result = dict(
            self.launcher.launch(
                context_pack,
                execution_routing=execution_routing,
            )
        )
        receipt = result.get("isolation_receipt")
        if not isinstance(receipt, Mapping):
            raise ValueError("Issue-delivery child isolation receipt is unavailable")
        result["worker_isolation"] = WorkerIsolationBinding.from_receipt(
            receipt
        ).model_dump(mode="json")
        return result


__all__ = [
    "BuilderOpsIssueDeliveryEffectLedger",
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
]
