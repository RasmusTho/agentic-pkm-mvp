"""Protected host execution contract for one approved Issue delivery."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Any, Mapping, cast
from types import SimpleNamespace

import psycopg
import pytest
from pydantic import ValidationError

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
)
from app.builderops.issue_delivery_effect_executor import (
    BuilderOpsIssueDeliveryEffectLedger,
    ContentOnlyIssueDeliverySessionLauncher,
    DestinationBinding,
    EXECUTOR_ARTIFACT,
    EffectReadback,
    FrozenIssueDeliveryDestination,
    GitIssueDeliveryDestination,
    HostIssueDeliveryExecutorRuntime,
    IssueDeliveryEffectReceipt,
    IssueDeliveryEffectRequest,
    IssueDeliveryHostExecutor,
    PreparedIssueDeliveryWorker,
    WORKER_ISOLATION_ARTIFACT,
    WorkerIsolationBinding,
    build_host_issue_delivery_executor,
)
from app.builderops import issue_delivery_effect_executor as effect_executor_module
from app.builderops.control_plane.issue_delivery import (
    REQUIRED_WORKFLOW_ARTIFACTS,
    canonical_hash,
)
from app.builderops.control_plane.models import Lease, TransactionResult
from app.builderops.issue_delivery_worker_isolation import (
    LinuxSystemdCodexIssueSessionLauncher,
)
from app.dispatcher.verification_merge import (
    BuilderOpsOutboxExecutor,
    ProtectedDeliveryManifest,
)

from tests.builderops.issue_delivery_production_harness import (
    REPOSITORY,
    _ProductionHarness,
    _Transport,
    _approval,
    _destination,
    _isolation,
    _isolation_receipt,
    _production_client,
    _production_manifest,
    _production_registry,
    _request,
    _sha,
)

@pytest.mark.pg
def test_bifrost_executor_binds_distinct_consumer_and_workflow_roots(issue_delivery_production_harness) -> None:
    harness = issue_delivery_production_harness(bifrost=True)
    assert harness.workflow_root != harness.checkout
    assert not (harness.checkout / EXECUTOR_ARTIFACT).exists()
    binding = harness.executor.live_binding(harness.approval)
    assert binding["delivery_sources"]["issue_repository"] == REPOSITORY
    assert binding["delivery_sources"]["workflow_source_revision"] != binding["source_revision"]
    request = harness.completed_request()
    receipt = harness.executor.execute(request)
    assert receipt.outcome == "applied"
    status = harness.ledger.status(receipt.operation_key)
    assert status["payload"]["credential_id"] == "hub-effect"
    assert status["payload"]["effect_repository"] == REPOSITORY
    assert status["payload"]["delivery_sources"] == binding["delivery_sources"]
    assert harness.source_state is not None
    reads = harness.source_state["reads"]
    assert any("/rasmustho/bifrost/contents/" in path for path in reads)
    assert any(f"/{REPOSITORY}/issues/" in path for path in reads)
    artifact = harness.workflow_root / EXECUTOR_ARTIFACT
    artifact.write_text(artifact.read_text() + "\n# drift\n")
    from app.builderops.issue_delivery_operation import IssueDeliveryOperationRefused
    with pytest.raises(IssueDeliveryOperationRefused):
        harness.executor.live_binding(harness.approval)
    assert harness.transport.apply_calls == 1
    assert harness.executor.execute(request).outcome == "applied"
    assert harness.transport.apply_calls == 1


def _bifrost_candidate_request(harness, effect_kind, change="allowed"):
    root = harness.worktree
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    document = root / "docs/guide.md"
    document.parent.mkdir(exist_ok=True)
    document.write_text("Documented client behavior.\n")
    if change in {"swift", "script", "policy"}:
        name = {"swift": "Client.swift", "script": "setup.sh", "policy": ".builderops/delivery-manifest.json"}[change]
        extra = root / name
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("extra effect\n")
    elif change == "rename":
        (root / "tracked.txt").rename(root / "docs/renamed.md")
    elif change == "delete":
        (root / "tracked.txt").unlink()
    elif change == "copy":
        document.write_bytes((root / "tracked.txt").read_bytes())
    elif change == "symlink":
        document.unlink()
        document.symlink_to("../tracked.txt")
    elif change == "executable":
        document.chmod(0o755)
    git("add", ".")
    git("commit", "-m", "documentation candidate")
    head = git("rev-parse", "HEAD")
    base = harness.approval["destination"]["base_sha"]
    # Independent selected-document claim: it is intentionally insufficient
    # for every extra-path case. The protected production caller reads all trees.
    diff = {"base_sha": base, "head_sha": head, "changes": [{
        "old_mode": "000000", "new_mode": "100644", "old_blob": "0" * 40,
        "new_blob": git("rev-parse", "HEAD:docs/guide.md"), "status": "A", "paths": ["docs/guide.md"],
    }]}
    target = {"kind": effect_kind, "issue_number": harness.approval["issue"]["number"],
              "branch": harness.approval["destination"]["branch"], "base_ref": "main",
              "base_sha": base, "head_sha": head, "diff_sha256": canonical_hash(diff)}
    if effect_kind == "publication":
        target.update(title_sha256="1" * 64, body_sha256="2" * 64, expected_remote_ref_state="absent")
    else:
        target["pr_number"] = 6000
    harness.source_state["head"] = head
    claim = harness.completed_request()
    return IssueDeliveryEffectRequest.model_validate({**claim.model_dump(mode="json"), "effect_kind": effect_kind, "target": target})


@pytest.mark.pg
@pytest.mark.parametrize("drift", [None, "foreign_base", "foreign_merge", "unmerged", "policy"])
def test_bifrost_closure_requires_owned_merge_transition(issue_delivery_production_harness, drift) -> None:
    harness = issue_delivery_production_harness(bifrost=True)
    harness.transport.readbacks = ["applied"] * 4
    harness.executor.execute(harness.completed_request())
    merge = _bifrost_candidate_request(harness, "merge")
    assert harness.executor.execute(merge).outcome == "applied"
    request = IssueDeliveryEffectRequest.model_validate({**merge.model_dump(mode="json"), "effect_kind": "closure", "target": {
        "kind": "closure", "issue_number": merge.issue_number, "pr_number": 6000,
        "merge_commit_sha": "3" * 40, "expected_issue_state": "open"}})
    if drift == "foreign_base":
        harness.source_state["bases"][merge.repository] = "4" * 40
    elif drift == "foreign_merge":
        harness.source_state["head"] = "4" * 40
    elif drift == "unmerged":
        harness.source_state["merged"] = False
    elif drift == "policy":
        harness.source_state["documents"][merge.repository]["credential_id"] = "foreign-effect"
    if drift is None:
        assert harness.executor.execute(request).outcome == "applied"
        assert harness.source_state["issue"]["state"] == "closed"
        assert harness.executor.execute(request).outcome == "applied"
        assert harness.transport.apply_calls == 3
    else:
        with pytest.raises(ValueError):
            harness.executor.execute(request)
        assert harness.transport.apply_calls == 2


@pytest.mark.pg
@pytest.mark.parametrize("effect_kind", ["publication", "merge"])
@pytest.mark.parametrize("change", ["allowed", "swift", "script", "policy", "rename", "copy", "delete", "symlink", "executable", "head", "diff", "review"])
def test_bifrost_publication_and_merge_enforce_complete_diff(issue_delivery_production_harness, effect_kind, change) -> None:
    harness = issue_delivery_production_harness(bifrost=True)
    harness.executor.execute(harness.completed_request())
    request = _bifrost_candidate_request(harness, effect_kind, change)
    if change == "diff":
        request = request.model_copy(update={"target": request.target.model_copy(update={"diff_sha256": "0" * 64})})
    elif change == "head":
        request = request.model_copy(update={"target": request.target.model_copy(update={"head_sha": harness.approval["source"]["revision"]})})
    elif change == "review":
        if effect_kind == "publication":
            # Publication need not already have review; merge does.
            change = "allowed"
        harness.source_state["reviews"] = []
    if change == "allowed":
        result = harness.executor.execute(request)
        assert result.outcome == "applied"
        status = harness.ledger.status(result.operation_key)
        assert status["payload"]["credential_id"] == "consumer-effect"
        assert status["payload"]["target"]["diff_sha256"] == request.target.diff_sha256
        assert harness.transport.apply_calls == 2
    else:
        with pytest.raises(ValueError):
            harness.executor.execute(request)
        assert harness.transport.apply_calls == 1


class _Authority:
    def __init__(self, approval: Mapping[str, Any]) -> None:
        self.approval = deepcopy(dict(approval))
        self.revoked = False
        self.readback_revoked = False
        self.epoch_drifted = False
        self.reads: list[str] = []

    def issue_delivery_authority(
        self, *, manifest: Mapping[str, Any], purpose: str
    ) -> Mapping[str, Any]:
        assert dict(manifest) == self.approval
        self.reads.append(purpose)
        if purpose == "execute" and self.revoked:
            raise ValueError("permission revoked")
        if purpose == "readback" and self.readback_revoked:
            raise ValueError("readback permission revoked")
        return {
            "approval": deepcopy(self.approval),
            "operation_key": self.approval["operation_key"],
            "authority_epoch": self.approval["authority_epoch"]
            + (1 if self.epoch_drifted else 0),
            "purpose": purpose,
        }


class _DestinationGuard:
    def __init__(self, frozen: FrozenIssueDeliveryDestination) -> None:
        self.frozen = frozen
        self.drifted = False
        self.checks = 0

    def assert_frozen(
        self, frozen: FrozenIssueDeliveryDestination, approval: Mapping[str, Any]
    ) -> None:
        del approval
        self.checks += 1
        if frozen != self.frozen or self.drifted:
            raise ValueError("destination changed")


class _RepositoryAuthority:
    def __init__(self) -> None:
        self.drifted = False

    def delivery_manifest(
        self, repository: str, base_sha: str
    ) -> ProtectedDeliveryManifest:
        return ProtectedDeliveryManifest(
            repository=repository,
            base_sha=base_sha,
            blob_sha=("5" if not self.drifted else "6") * 40,
            content_sha256=("7" if not self.drifted else "8") * 64,
            credential_id="github-writer",
            credential_generation=3,
            allowed_effects=(
                "github.issue-delivery.claim.v1",
                "github.issue-delivery.publication.v1",
                "github.issue-delivery.merge.v1",
                "github.issue-delivery.closure.v1",
                "github.issue-delivery.parent-evidence.v1",
            ),
        )


class _Credentials:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(
        self, *, repository: str, credential_id: str, rotation_generation: int
    ) -> object:
        assert (repository, credential_id, rotation_generation) == (
            REPOSITORY,
            "github-writer",
            3,
        )
        self.calls += 1
        return object()


class _BlockingCredentials(_Credentials):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def resolve(
        self, *, repository: str, credential_id: str, rotation_generation: int
    ) -> object:
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test credential fence was not released")
        return super().resolve(
            repository=repository,
            credential_id=credential_id,
            rotation_generation=rotation_generation,
        )


class _Ledger:
    def __init__(self) -> None:
        self.state = "missing"
        self.intent: dict[str, Any] | None = None
        self.effect_claim: dict[str, Any] | None = None
        self.recovery_claims = 0
        self.reconciliations: list[tuple[bool, Mapping[str, Any]]] = []
        self.lose_next_unknown_write = False
        self.effect_revalidation_override: Mapping[str, Any] | None = None

    def operation_key(
        self, *, effect_slot_sha256: str, effect_type: str
    ) -> str:
        assert effect_slot_sha256 and effect_type
        return "outbox-operation"

    def begin(
        self,
        *,
        effect_slot_sha256: str,
        effect_type: str,
        payload: Mapping[str, Any],
    ) -> str:
        self.intent = {
            "effect_slot_sha256": effect_slot_sha256,
            "effect_type": effect_type,
            "task_id": f"issue-delivery-effect:{effect_slot_sha256}",
            "payload": dict(payload),
        }
        self.state = "pending"
        return "outbox-operation"

    def status(self, operation_key: str) -> Mapping[str, Any]:
        return {
            "operation_key": operation_key,
            "status": self.state,
            **(self.intent or {}),
        }

    def claim_effect(
        self, operation_key: str, *, effect_type: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        assert self.intent is not None
        self.effect_claim = {
            "operation_key": operation_key,
            "effect_type": effect_type,
            "task_id": self.intent["task_id"],
            "payload": dict(payload),
            "effect_eligible": True,
            "fencing_token": 1,
            "receipt_sequence": 1,
            "claim_lsn": "0/1",
            "intent_lsn": "0/1",
            "worker_id": "host-executor",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "repository": REPOSITORY,
        }
        self.state = "claimed"
        return dict(self.effect_claim)

    def revalidate_effect_claim(
        self, claim: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        current = {
            key: value
            for key, value in claim.items()
            if key not in {"payload", "effect_eligible"}
        }
        current["effect_eligible"] = True
        if self.effect_revalidation_override:
            current.update(self.effect_revalidation_override)
        return current

    def claim_for_readback(self, operation_key: str) -> Mapping[str, Any]:
        assert self.effect_claim is not None
        self.recovery_claims += 1
        return {
            **self.effect_claim,
            "operation_key": operation_key,
            "effect_eligible": False,
            "readback_only": True,
            "recovery_kind": "recovered_attempt",
        }

    def mark_unknown(
        self, claim: Mapping[str, Any], *, detail: str
    ) -> Mapping[str, Any]:
        assert claim["effect_eligible"] is True and detail
        self.state = "unknown"
        if self.lose_next_unknown_write:
            self.lose_next_unknown_write = False
            raise TimeoutError("unknown transition response lost")
        return {**claim, "status": "unknown"}

    def reconcile(
        self,
        claim: Mapping[str, Any],
        *,
        observed_applied: bool,
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        assert claim["readback_only"] is True
        assert claim["effect_eligible"] is False
        self.reconciliations.append((observed_applied, dict(evidence)))
        self.state = "succeeded" if observed_applied else "pending"
        return {"status": self.state}


def _executor(tmp_path: Path, *, effect_kind: str = "claim", parent: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    executor_artifact = tmp_path / "issue_delivery_effect_executor.py"
    isolation_artifact = tmp_path / "issue_delivery_worker_isolation.py"
    executor_artifact.write_text("host executor\n", encoding="utf-8")
    isolation_artifact.write_text("worker isolation\n", encoding="utf-8")
    workflow_root = tmp_path / "workflow-root"
    for artifact_path in REQUIRED_WORKFLOW_ARTIFACTS:
        if artifact_path in {EXECUTOR_ARTIFACT, WORKER_ISOLATION_ARTIFACT}:
            continue
        trusted_artifact = workflow_root / artifact_path
        trusted_artifact.parent.mkdir(parents=True, exist_ok=True)
        trusted_artifact.write_text(
            f"trusted workflow artifact: {artifact_path}\n", encoding="utf-8"
        )
    destination = _destination(tmp_path)
    isolation = _isolation()
    approval = _approval(
        destination,
        executor_artifact,
        isolation_artifact,
        workflow_root,
        parent=parent,
    )
    request = _request(
        approval,
        destination,
        isolation,
        executor_artifact,
        isolation_artifact,
        effect_kind=effect_kind,
    )
    authority = _Authority(approval)
    destination_guard = _DestinationGuard(destination)
    repository = _RepositoryAuthority()
    credentials = _Credentials()
    ledger = _Ledger()
    transport = _Transport()
    launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)
    launcher._expected_profile_sha256 = isolation.profile_sha256
    launcher._isolation_runner = SimpleNamespace(receipt=_isolation_receipt())
    prepared = PreparedIssueDeliveryWorker(
        approval=dict(approval),
        destination=cast(GitIssueDeliveryDestination, destination_guard),
        frozen_destination=destination,
        launcher=launcher,
    )
    executor = IssueDeliveryHostExecutor(
        authority=authority,
        ledger=ledger,
        repository_authority=repository,
        credentials=credentials,
        destination=destination_guard,
        frozen_destination=destination,
        transport=transport,
        prepared_worker=prepared,
        expected_isolation_profile_sha256=isolation.profile_sha256,
        trusted_executor_artifact=executor_artifact,
        trusted_worker_isolation_artifact=isolation_artifact,
        trusted_workflow_root=workflow_root,
    )
    executor.bind_completed_worker()
    return (
        executor,
        request,
        authority,
        destination_guard,
        repository,
        credentials,
        ledger,
        transport,
    )


def test_fixed_host_executor_factory_binds_only_the_completed_prepared_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        original_executor,
        _request,
        authority,
        destination,
        repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path)
    runtime = HostIssueDeliveryExecutorRuntime(
        repository_authority=repository,
        credentials=credentials,
        transport=transport,
        isolation_profile_sha256=_request.worker_isolation.profile_sha256,
        live_binding_reader=lambda approval: {
            "checkout": approval["destination"]["resolved_checkout"],
            "worktree": approval["destination"]["resolved_worktree"],
        },
    )
    launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)
    launcher._expected_profile_sha256 = _request.worker_isolation.profile_sha256
    launcher._isolation_runner = SimpleNamespace(receipt=None)
    prepared = PreparedIssueDeliveryWorker(
        approval=dict(_request.approval),
        destination=cast(GitIssueDeliveryDestination, destination),
        frozen_destination=original_executor.frozen_destination,
        launcher=launcher,
    )
    monkeypatch.setattr(
        effect_executor_module, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", runtime
    )
    built = build_host_issue_delivery_executor(
        approval=_request.approval,
        client=cast(BuilderOpsControlPlaneClient, authority),
        prepared=prepared,
    )
    assert type(built) is IssueDeliveryHostExecutor
    assert built.transport is transport
    assert built.live_binding(_request.approval)["checkout"] == _request.approval[
        "destination"
    ]["resolved_checkout"]
    with pytest.raises(ValueError, match="completed worker receipt is unavailable"):
        built.execute(_request)
    assert ledger.state == "missing"
    assert credentials.calls == 0
    assert transport.apply_calls == 0

    launcher._isolation_runner.receipt = _isolation_receipt()
    built.bind_completed_worker()
    assert built.worker_isolation == _request.worker_isolation
    with pytest.raises(ValueError, match="already bound"):
        built.bind_completed_worker()

    mismatched_launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)
    mismatched_launcher._expected_profile_sha256 = "f" * 64
    mismatched_launcher._isolation_runner = SimpleNamespace(receipt=None)
    mismatched_prepared = PreparedIssueDeliveryWorker(
        approval=dict(_request.approval),
        destination=cast(GitIssueDeliveryDestination, destination),
        frozen_destination=original_executor.frozen_destination,
        launcher=mismatched_launcher,
    )
    with pytest.raises(ValueError, match="profile differs"):
        build_host_issue_delivery_executor(
            approval=_request.approval,
            client=cast(BuilderOpsControlPlaneClient, authority),
            prepared=mismatched_prepared,
        )


def test_production_fixture_keeps_operation_and_host_outbox_scopes_separate(
    tmp_path: Path,
) -> None:
    registry = _production_registry(tmp_path)
    operation = registry.current_credential("issue-delivery-operation")
    host = registry.current_credential("issue-delivery-host")

    assert operation is not None and host is not None
    assert "outbox:write" not in operation.scopes
    assert "outbox:write" in host.scopes
    assert operation.principal == host.principal == "destination:shared"


@pytest.mark.pg
def test_worker_has_no_ambient_repository_mutation_identity(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    harness = issue_delivery_production_harness()
    assert isinstance(
        harness.prepared_worker.launcher,
        ContentOnlyIssueDeliverySessionLauncher,
    )
    assert issubclass(
        ContentOnlyIssueDeliverySessionLauncher,
        LinuxSystemdCodexIssueSessionLauncher,
    )
    assert harness.preparation_observed == (True,)
    request = harness.completed_request()
    isolation = request.worker_isolation
    assert isolation.worker_uid != isolation.executor_uid
    assert isolation.worker_gid != isolation.executor_gid
    assert isolation.worker_supplementary_gids == ()
    assert isolation.repository_credential_probe == "denied"
    assert isolation.git_metadata_write_denied is True
    receipt = harness.executor.execute(request)
    assert receipt.outcome == "applied"
    status = harness.ledger.status(receipt.operation_key)
    assert status["status"] == "succeeded"
    assert status["payload"]["worker_isolation_binding_sha256"] == canonical_hash(
        isolation.model_dump(mode="json")
    )
    assert harness.transport.apply_calls == 1


@pytest.mark.pg
def test_production_harness_keeps_immutable_approvals_distinct(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    first = issue_delivery_production_harness()
    second = issue_delivery_production_harness()
    assert first.approval["approval_id"] != second.approval["approval_id"]
    assert first.approval["operation_key"] != second.approval["operation_key"]
    assert first.owner.issue_delivery_readback(
        repository=REPOSITORY,
        approval_id=str(first.approval["approval_id"]),
    )["approval"] == first.approval
    assert second.owner.issue_delivery_readback(
        repository=REPOSITORY,
        approval_id=str(second.approval["approval_id"]),
    )["approval"] == second.approval


@pytest.mark.pg
@pytest.mark.parametrize("effect_kind", ["claim", "publication", "merge", "closure"])
def test_host_executor_applies_only_exact_authorized_delivery_effect(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    effect_kind: str,
) -> None:
    harness = issue_delivery_production_harness(effect_kind=effect_kind)
    request = harness.completed_request()
    receipt = harness.executor.execute(request)
    assert receipt.outcome == "applied"
    assert harness.ledger.status(receipt.operation_key)["status"] == "succeeded"
    assert harness.transport.apply_calls == 1
    assert harness.credentials.calls == 1
    serialized = receipt.as_dict()
    assert "worktree" not in serialized
    assert "credential" not in serialized
    broadened = request.model_dump(mode="json")
    broadened["target"]["other_issue"] = 5559
    with pytest.raises(ValidationError):
        IssueDeliveryEffectRequest.model_validate(broadened)


@pytest.mark.pg
def test_revocation_and_target_drift_fail_closed(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    revoked = issue_delivery_production_harness()
    credential_manifest = json.loads(
        revoked.registry.manifest_path.read_text(encoding="utf-8")
    )
    credential_manifest["credentials"][1]["revoked"] = True
    revoked.registry.manifest_path.write_text(
        json.dumps(credential_manifest), encoding="utf-8"
    )
    with pytest.raises(Exception, match="revoked|credential"):
        revoked.executor.execute(revoked.completed_request())
    assert revoked.transport.apply_calls == revoked.credentials.calls == 0

    drifted = issue_delivery_production_harness()
    drifted.transport.target_override = {"source_revision": "b" * 40}
    with pytest.raises(ValueError, match="target/source/profile"):
        drifted.executor.execute(drifted.completed_request())
    assert drifted.transport.apply_calls == drifted.credentials.calls == 0
    assert drifted.ledger.status(
        drifted.ledger.operation_key(
            effect_slot_sha256=drifted.completed_request().effect_slot_sha256,
            effect_type="github.issue-delivery.claim.v1",
        )
    )["status"] == "pending"


@pytest.mark.pg
def test_host_prepares_and_freezes_destination_before_entry(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    harness = issue_delivery_production_harness()
    assert harness.preparation_observed == (True,)
    assert harness.worktree.is_dir()
    assert harness.frozen.binding.worktree == harness.worktree
    moved = harness.worktree.with_name("issue-delivery-moved")
    harness.worktree.rename(moved)
    try:
        with pytest.raises(ValueError, match="Git identity"):
            harness.executor.execute(harness.completed_request())
    finally:
        moved.rename(harness.worktree)
    assert harness.transport.apply_calls == harness.credentials.calls == 0


def test_unit_worker_binding_rejects_ambient_repository_identity() -> None:
    assert issubclass(
        ContentOnlyIssueDeliverySessionLauncher, LinuxSystemdCodexIssueSessionLauncher
    )
    receipt = _isolation_receipt()
    binding = WorkerIsolationBinding.from_receipt(receipt)
    assert binding.worker_uid != binding.executor_uid
    assert binding.worker_gid != binding.executor_gid
    assert binding.worker_supplementary_gids == ()
    assert binding.git_metadata_write_denied is True
    assert binding.repository_credential_probe == "denied"

    same_user = deepcopy(receipt)
    same_user["worker"]["uid"] = same_user["executor"]["uid"]
    with pytest.raises(ValueError, match="distinct OS principal"):
        WorkerIsolationBinding.from_receipt(same_user)

    mutable_git = deepcopy(receipt)
    mutable_git["git_metadata_write_denied"] = False
    with pytest.raises(ValueError, match="Git metadata"):
        WorkerIsolationBinding.from_receipt(mutable_git)

    launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)
    launcher.developer_instructions = "Implement the bounded content change."
    prompt = launcher.prompt({"branch_worktree_plan": {"worktree": "/worktrees/5558"}})
    assert "propose only typed" in prompt
    assert "host independently claims the approved Issue before this worker enters" in prompt
    assert "typed claim," not in prompt
    assert "must not run Git or GitHub lifecycle effects" in prompt
    assert "Self-claim" not in prompt


def test_host_executor_requires_host_owned_live_binding_reader(tmp_path: Path) -> None:
    executor, request, *_ = _executor(tmp_path)

    with pytest.raises(ValueError, match="live source/profile reader"):
        executor.live_binding(request.approval)

    observed = {
        "checkout": "/approved/checkout",
        "worktree": "/approved/worktree",
        "current_issue": {"state": "open"},
    }
    executor._live_binding_reader = lambda approval: (
        observed if approval == request.approval else {}
    )
    assert executor.live_binding(request.approval) == observed


def test_host_executor_accepts_admitted_resolved_destination_request(
    tmp_path: Path,
) -> None:
    executor, request, *_rest = _executor(tmp_path)
    # Production requests carry admission-side resolved path proofs; the
    # host strips them only after validating those proofs against the raw
    # approved paths.
    executor._validate_static_request(request, current_artifacts=False)

    # The request carries the frozen canonical destination, while an admitted
    # approval may retain a user-facing symlink spelling alongside its
    # resolved proof.  Static host validation must normalize that pair rather
    # than rejecting an otherwise exact frozen destination.
    checkout_link = tmp_path / "checkout-link"
    worktree_link = tmp_path / "worktree-link"
    checkout_link.symlink_to(request.destination.checkout, target_is_directory=True)
    worktree_link.symlink_to(request.destination.worktree, target_is_directory=True)
    symlinked_payload = request.model_dump(mode="json")
    symlinked_destination = symlinked_payload["approval"]["destination"]
    symlinked_destination["checkout"] = str(checkout_link)
    symlinked_destination["worktree"] = str(worktree_link)
    symlinked_destination["resolved_checkout"] = str(
        request.destination.checkout.resolve()
    )
    symlinked_destination["resolved_worktree"] = str(
        request.destination.worktree.resolve()
    )
    symlinked = IssueDeliveryEffectRequest.model_validate(symlinked_payload)
    executor._validate_static_request(symlinked, current_artifacts=False)

    tampered_payload = request.model_dump(mode="json")
    tampered_payload["approval"]["destination"]["resolved_worktree"] = str(
        (tmp_path / "retargeted").resolve()
    )
    tampered = IssueDeliveryEffectRequest.model_validate(tampered_payload)
    with pytest.raises(ValueError, match="request does not match exact approval"):
        executor._validate_static_request(tampered, current_artifacts=False)
    with pytest.raises(ValueError, match="approval destination is invalid"):
        executor._validate_static_request(tampered, current_artifacts=True)


@pytest.mark.parametrize("effect_kind", ["claim", "publication", "merge", "closure"])
def test_unit_host_executor_applies_only_exact_authorized_delivery_effect(
    tmp_path: Path, effect_kind: str
) -> None:
    (
        executor,
        request,
        _authority,
        destination,
        _repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path, effect_kind=effect_kind)
    receipt = executor.execute(request)
    assert receipt.outcome == "applied"
    assert (
        receipt.as_dict()["destination_identity_sha256"]
        == request.destination.frozen_identity_sha256
    )
    assert "worktree" not in receipt.as_dict()
    assert transport.apply_calls == 1
    assert credentials.calls == 1
    assert destination.checks == 2
    assert ledger.reconciliations[-1][0] is True
    assert ledger.intent is not None
    assert "worker_isolation" not in ledger.intent["payload"]
    assert "worker_isolation_binding_sha256" in ledger.intent["payload"]

    incomplete = request.model_dump(mode="json")
    incomplete.pop("profile_hash")
    with pytest.raises(ValidationError):
        IssueDeliveryEffectRequest.model_validate(incomplete)
    broadened = request.model_dump(mode="json")
    broadened["target"]["other_issue"] = 5559
    with pytest.raises(ValidationError):
        IssueDeliveryEffectRequest.model_validate(broadened)
    with pytest.raises(ValidationError):
        EffectReadback.model_validate(
            {
                "request_sha256": request.content_sha256,
                "outcome": "applied",
                "evidence": {
                    "source": "github-authoritative-readback",
                    "observed_target_sha256": _sha(
                        json.dumps(
                            request.target.model_dump(mode="json"), sort_keys=True
                        ).encode()
                    ),
                    "local_path": "/tmp/leak",
                },
            }
        )


def test_unit_unknown_effect_requires_readback_before_retry(tmp_path: Path) -> None:
    (
        executor,
        request,
        authority,
        _destination_guard,
        _repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path)
    transport.raise_on_apply = True
    transport.readbacks = ["unknown", "not_applied", "applied"]
    ledger.lose_next_unknown_write = True

    first = executor.execute(request)
    assert first.outcome == "unknown"
    assert transport.apply_calls == 1
    assert ledger.state == "unknown"
    assert authority.reads[-1] == "readback"

    authority.revoked = True
    # A retry in the same host process retains the one frozen host receipt.
    # A restarted executor cannot reconstruct it from worker output.
    second = executor.execute(request)
    assert second.outcome == "unknown"
    assert second.readback["retry_refused"] == "committed-dispatch-may-still-complete"
    assert ledger.state == "unknown"
    assert ledger.recovery_claims == 2
    assert transport.apply_calls == 1
    assert credentials.calls == 1
    assert authority.reads[-1] == "readback"

    changed_request = request.model_copy(
        update={"approval": {**request.approval, "request_note": "changed"}}
    )
    assert changed_request.effect_slot_sha256 == request.effect_slot_sha256
    assert changed_request.content_sha256 != request.content_sha256
    with pytest.raises(ValueError, match="foreign or changed"):
        executor.execute(changed_request)
    assert transport.apply_calls == 1

    (
        denied_executor,
        denied_request,
        denied_authority,
        _denied_destination,
        _denied_repository,
        _denied_credentials,
        denied_ledger,
        denied_transport,
    ) = _executor(tmp_path / "readback-revoked")
    denied_transport.on_apply = lambda: setattr(
        denied_authority, "readback_revoked", True
    )
    with pytest.raises(ValueError, match="readback permission revoked"):
        denied_executor.execute(denied_request)
    assert denied_transport.apply_calls == 1
    assert denied_ledger.state == "unknown"
    assert denied_transport.readbacks == ["applied", "applied"]


def test_unknown_effect_readback_uses_immutable_destination_after_alias_drift(
    tmp_path: Path,
) -> None:
    (
        executor,
        request,
        authority,
        _destination_guard,
        _repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path / "recovery")
    alias = tmp_path / "recovery-worktree-alias"
    alias.symlink_to(request.destination.worktree, target_is_directory=True)
    approval = deepcopy(request.approval)
    approval["destination"]["worktree"] = str(alias)
    approval["destination"]["resolved_worktree"] = str(request.destination.worktree)
    authority.approval = deepcopy(approval)
    request = request.model_copy(update={"approval": approval})
    transport.raise_on_apply = True
    transport.readbacks = ["unknown", "applied"]

    first = executor.execute(request)
    assert first.outcome == "unknown"
    assert transport.apply_calls == credentials.calls == 1
    assert ledger.state == "unknown"

    alias.unlink()
    retarget = tmp_path / "retarget"
    retarget.mkdir()
    alias.symlink_to(retarget, target_is_directory=True)

    recovered = executor.execute(request)
    assert recovered.outcome == "applied"
    assert transport.apply_calls == credentials.calls == 1
    assert ledger.recovery_claims == 2
    assert authority.reads[-1] == "readback"

    foreign_approval = deepcopy(approval)
    foreign_approval["destination"]["resolved_worktree"] = str(retarget)
    authority.approval = deepcopy(foreign_approval)
    foreign_request = request.model_copy(update={"approval": foreign_approval})
    with pytest.raises(ValueError, match="request does not match exact approval"):
        executor.execute(foreign_request)
    assert transport.apply_calls == credentials.calls == 1

    (
        fresh_executor,
        fresh_request,
        fresh_authority,
        _fresh_destination_guard,
        _fresh_repository,
        fresh_credentials,
        fresh_ledger,
        fresh_transport,
    ) = _executor(tmp_path / "fresh")
    fresh_alias = tmp_path / "fresh-worktree-alias"
    fresh_alias.symlink_to(fresh_request.destination.worktree, target_is_directory=True)
    fresh_approval = deepcopy(fresh_request.approval)
    fresh_approval["destination"]["worktree"] = str(fresh_alias)
    fresh_approval["destination"]["resolved_worktree"] = str(
        fresh_request.destination.worktree
    )
    fresh_authority.approval = deepcopy(fresh_approval)
    fresh_request = fresh_request.model_copy(update={"approval": fresh_approval})
    fresh_alias.unlink()
    fresh_alias.symlink_to(retarget, target_is_directory=True)

    with pytest.raises(ValueError, match="approval destination is invalid"):
        fresh_executor.execute(fresh_request)
    assert fresh_ledger.state == "missing"
    assert fresh_transport.apply_calls == fresh_credentials.calls == 0


def test_issue_delivery_ledger_reuses_outbox_with_bounded_scope() -> None:
    client = object()
    default_outbox = BuilderOpsOutboxExecutor(  # type: ignore[arg-type]
        client,
        repository=REPOSITORY,
        worker_id="verification-worker",
    )
    assert default_outbox.envelope["scope"] == "verification-executor"
    assert default_outbox.claim_ttl_seconds == 300

    ledger = BuilderOpsIssueDeliveryEffectLedger(  # type: ignore[arg-type]
        client,
        repository=REPOSITORY,
        run_id="run-5558",
        approval_id="approval-5558",
        worker_id="issue-delivery-host",
    )
    assert ledger.outbox.envelope["scope"] == "issue-delivery-executor"
    assert ledger.outbox.claim_ttl_seconds == ledger.claim_ttl_seconds


def test_issue_delivery_ledger_bootstraps_task_through_authenticated_service(
    tmp_path: Path,
) -> None:
    effect_slot_sha256 = "a" * 64

    class BootstrapStore:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.task: dict[str, Any] | None = None

        def readiness(self) -> dict[str, int]:
            return {"schema_version": 1, "authority_epoch": 1}

        def get_task(self, repository: str, task_id: str) -> Mapping[str, Any]:
            self.calls.append("get_task")
            if self.task is None:
                raise KeyError(task_id)
            return self.task

        def commit_transition(self, **values: Any) -> TransactionResult:
            key = str(values["idempotency_key"])
            self.calls.append(f"commit_transition:{key}")
            self.task = {
                "repository": values["envelope"].repository,
                "task_id": values["task_id"],
                "state": values["to_state"],
                "version": 1,
            }
            return TransactionResult(
                values["envelope"].repository,
                values["task_id"],
                values["to_state"],
                1,
                "0/1",
                None,
            )

        def claim_task(self, **values: Any) -> tuple[TransactionResult, Lease]:
            key = str(values["idempotency_key"])
            self.calls.append(f"claim_task:{key}")
            lease = Lease(
                repository=values["envelope"].repository,
                resource_id=values["task_id"],
                holder=values["holder"],
                fencing_token=1,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                lease_kind="task",
            )
            return (
                TransactionResult(
                    values["envelope"].repository,
                    values["task_id"],
                    "claimed",
                    2,
                    "0/2",
                    None,
                ),
                lease,
            )

    store = BootstrapStore()
    client = _production_client(
        store,  # type: ignore[arg-type]
        _production_registry(tmp_path),
        "executor-pg-token",
    )
    ledger = BuilderOpsIssueDeliveryEffectLedger(
        client,
        repository=REPOSITORY,
        run_id="run-bootstrap",
        approval_id="approval-bootstrap",
        worker_id="issue-delivery-host",
    )

    lease = ledger._ensure_task_claim(  # noqa: SLF001 - exact service boundary regression
        task_id=ledger._task_id(effect_slot_sha256),
        effect_slot_sha256=effect_slot_sha256,
    )

    assert lease["holder"] == "destination:shared"
    assert store.calls == [
        "get_task",
        f"commit_transition:delivery-effect-ingest:{effect_slot_sha256}",
        f"claim_task:delivery-effect-claim:{effect_slot_sha256}",
    ]


def test_issue_delivery_approval_binds_executor_and_worker_boundary() -> None:
    assert (
        "app/builderops/issue_delivery_effect_executor.py"
        in REQUIRED_WORKFLOW_ARTIFACTS
    )


def test_production_manifest_allocates_unique_approval_identity(tmp_path: Path) -> None:
    first = _production_manifest(
        checkout=tmp_path / "checkout-1",
        worktree=tmp_path / "worktree-1",
        base_sha="a" * 40,
        operation_key="operation-1",
    )
    second = _production_manifest(
        checkout=tmp_path / "checkout-2",
        worktree=tmp_path / "worktree-2",
        base_sha="b" * 40,
        operation_key="operation-2",
    )
    assert first["approval_id"] != second["approval_id"]
    assert first["operation_key"] != second["operation_key"]
    replay = _production_manifest(
        checkout=tmp_path / "checkout-1",
        worktree=tmp_path / "worktree-1",
        base_sha="a" * 40,
        operation_key="operation-1",
    )
    assert replay["approval_id"] == first["approval_id"]
    assert (
        "app/builderops/issue_delivery_worker_isolation.py"
        in REQUIRED_WORKFLOW_ARTIFACTS
    )


@pytest.mark.pg
@pytest.mark.parametrize("bifrost", [False, True])
def test_unknown_effect_requires_readback_before_retry(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    monkeypatch: pytest.MonkeyPatch,
    bifrost: bool,
) -> None:
    harness = issue_delivery_production_harness(bifrost=bifrost)
    if bifrost:
        request = harness.completed_request()
        harness.transport.raise_on_apply = True
        harness.transport.readbacks = ["unknown", "not_applied", "applied"]
        first = harness.executor.execute(request)
        assert first.outcome == "unknown"
        # Restart/re-entry of the actual executor uses the same persisted slot;
        # a later negative read cannot authorize redispatch of a committed call.
        assert harness.executor.execute(request).outcome == "unknown"
        assert harness.transport.apply_calls == 1
        credential_manifest = json.loads(harness.registry.manifest_path.read_text())
        for row in credential_manifest["credentials"]:
            if row["id"] in {"consumer-effect", "hub-effect"}:
                row["revoked"] = True
        harness.registry.manifest_path.write_text(json.dumps(credential_manifest))
        assert harness.executor.execute(request).outcome == "applied"
        assert harness.transport.apply_calls == 1
        status = harness.ledger.status(first.operation_key)
        assert status["payload"]["delivery_sources"]["repository"] == request.repository
        return
    issue_delivery_pg_store = harness.store
    registry = harness.registry
    host = harness.host
    destination = harness.destination
    frozen = harness.frozen
    request = harness.completed_request()
    ledger = harness.ledger
    credentials = harness.credentials
    transport = harness.transport
    transport.raise_on_apply = True
    transport.readbacks = ["unknown", "not_applied", "not_applied"]
    executor = harness.executor

    original_mark_unknown = host.mark_outbox_unknown
    lose_first_response = True

    def committed_unknown_with_lost_response(*args: Any, **kwargs: Any) -> Any:
        nonlocal lose_first_response
        result = original_mark_unknown(*args, **kwargs)
        if lose_first_response:
            lose_first_response = False
            raise TimeoutError("unknown transition response was lost")
        return result

    monkeypatch.setattr(
        host, "mark_outbox_unknown", committed_unknown_with_lost_response
    )
    first = executor.execute(request)
    assert first.outcome == "unknown"
    assert transport.apply_calls == credentials.calls == 1
    assert ledger.status(first.operation_key)["status"] == "unknown"

    def expire_current_fence() -> None:
        with psycopg.connect(issue_delivery_pg_store.dsn) as conn:
            conn.execute(
                "UPDATE builderops_outbox "
                "SET claim_expires_at = clock_timestamp() - interval '1 second' "
                "WHERE repository = %s AND operation_key = %s",
                (REPOSITORY, first.operation_key),
            )

    expire_current_fence()
    # The first process must discard its now-expired cached claim and obtain a
    # fresh readback-only recovery fence, never an effect-eligible claim.
    ledger.clock = lambda: datetime.max.replace(tzinfo=timezone.utc)
    cached_recovery = ledger.claim_for_readback(first.operation_key)
    assert cached_recovery["readback_only"] is True
    assert cached_recovery["effect_eligible"] is False
    assert cached_recovery["recovery_kind"] == "recovered_attempt"

    expire_current_fence()
    credential_manifest = json.loads(registry.manifest_path.read_text(encoding="utf-8"))
    credential_manifest["credentials"][0]["revoked"] = True
    registry.manifest_path.write_text(json.dumps(credential_manifest), encoding="utf-8")
    # A process without the frozen host receipt cannot reconstruct it from
    # worker output, even if it can obtain a separately scoped readback grant.
    fresh_ledger = BuilderOpsIssueDeliveryEffectLedger(
        host,
        repository=REPOSITORY,
        run_id=request.run_id,
        approval_id=request.approval_id,
        worker_id="issue-delivery-host",
    )
    fresh_executor = IssueDeliveryHostExecutor(
        authority=host,
        ledger=fresh_ledger,
        repository_authority=harness.repository_authority,
        credentials=credentials,
        destination=destination,
        frozen_destination=frozen,
        transport=transport,
    )
    with pytest.raises(ValueError, match="completed worker receipt is unavailable"):
        fresh_executor.execute(request)
    assert transport.apply_calls == credentials.calls == 1
    # A fresh process has no authority to reconstruct the launch receipt from
    # worker text; only the original bound executor may read back the slot.
    recovered = executor.execute(request)
    assert recovered.outcome == "unknown"
    assert (
        recovered.readback["retry_refused"]
        == "committed-dispatch-may-still-complete"
    )
    assert ledger.status(first.operation_key)["status"] == "unknown"
    assert transport.apply_calls == credentials.calls == 1

    # The forced max clock proves exactly one expired-fence recovery above.
    # Restore normal time before proving that its fresh token is reused.
    ledger.clock = lambda: datetime.now(timezone.utc)
    recovered_again = executor.execute(request)
    assert recovered_again.outcome == "unknown"
    assert (
        recovered_again.readback["retry_refused"]
        == "committed-dispatch-may-still-complete"
    )
    assert ledger.status(first.operation_key)["status"] == "unknown"
    assert transport.apply_calls == credentials.calls == 1

    with psycopg.connect(issue_delivery_pg_store.dsn) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count, MAX(claim_fencing_token) AS fence "
            "FROM builderops_outbox WHERE repository = %s AND operation_key = %s",
            (REPOSITORY, first.operation_key),
        ).fetchone()
        receipt_events = conn.execute(
            "SELECT event_type FROM builderops_receipts "
            "WHERE repository = %s AND task_id = %s ORDER BY receipt_sequence",
            (REPOSITORY, f"issue-delivery-effect:{request.effect_slot_sha256}"),
        ).fetchall()
    assert row == (1, 3)
    assert [event[0] for event in receipt_events].count("outbox.recovered") == 2
    assert not any(event[0] == "outbox.reconciled.pending" for event in receipt_events)

    # A second execute sharing the original ledger can read back while the
    # admitted transport is still in flight. Its negative observation must
    # not reopen pending or permit a second transport.
    concurrent = issue_delivery_production_harness()
    concurrent_request = concurrent.completed_request()
    transport_entered = Event()
    transport_release = Event()

    def block_transport() -> None:
        transport_entered.set()
        if not transport_release.wait(timeout=10):
            raise TimeoutError("test transport was not released")

    concurrent.transport.on_apply = block_transport
    concurrent.transport.readbacks = ["not_applied", "applied"]
    concurrent_result: list[object] = []

    def run_concurrent_executor() -> None:
        try:
            concurrent_result.append(concurrent.executor.execute(concurrent_request))
        except Exception as exc:
            concurrent_result.append(exc)

    concurrent_thread = Thread(target=run_concurrent_executor, daemon=True)
    concurrent_thread.start()
    assert transport_entered.wait(timeout=10)
    negative_while_inflight = concurrent.executor.execute(concurrent_request)
    assert negative_while_inflight.outcome == "unknown"
    assert (
        negative_while_inflight.readback["retry_refused"]
        == "committed-dispatch-may-still-complete"
    )
    assert concurrent.ledger.status(negative_while_inflight.operation_key)["status"] == "unknown"
    assert concurrent.transport.apply_calls == 1

    transport_release.set()
    concurrent_thread.join(timeout=10)
    assert not concurrent_thread.is_alive()
    assert len(concurrent_result) == 1
    assert isinstance(concurrent_result[0], IssueDeliveryEffectReceipt)
    assert concurrent_result[0].outcome == "applied"
    assert concurrent.transport.apply_calls == 1

    # Stall after the final eligibility read but before the durable dispatch
    # commit. Expiry/recovery must supersede that exact fence, and a recovered
    # negative readback must not reopen the slot while the old process could
    # still resume and issue the external effect.
    race = issue_delivery_production_harness()
    race_request = race.completed_request()

    class BlockingDispatchLedger(BuilderOpsIssueDeliveryEffectLedger):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.dispatch_entered = Event()
            self.dispatch_release = Event()

        def mark_unknown(
            self, claim: Mapping[str, Any], *, detail: str
        ) -> Mapping[str, Any]:
            self.dispatch_entered.set()
            if not self.dispatch_release.wait(timeout=10):
                raise TimeoutError("test dispatch fence was not released")
            return super().mark_unknown(claim, detail=detail)

    stalled_ledger = BlockingDispatchLedger(
        race.host,
        repository=REPOSITORY,
        run_id=race_request.run_id,
        approval_id=race_request.approval_id,
        worker_id="issue-delivery-host",
    )
    stale_transport = _Transport()
    stalled_executor = IssueDeliveryHostExecutor(
        authority=race.host,
        ledger=stalled_ledger,
        repository_authority=race.repository_authority,
        credentials=race.credentials,
        destination=race.destination,
        frozen_destination=race.frozen,
        transport=stale_transport,
        prepared_worker=race.prepared_worker,
        expected_isolation_profile_sha256=(
            race.prepared_worker.launcher.expected_profile_sha256
        ),
    )
    stalled_executor.bind_completed_worker()
    stalled_result: list[object] = []

    def run_stalled_executor() -> None:
        try:
            stalled_result.append(stalled_executor.execute(race_request))
        except Exception as exc:
            stalled_result.append(exc)

    thread = Thread(target=run_stalled_executor, daemon=True)
    thread.start()
    assert stalled_ledger.dispatch_entered.wait(timeout=10)
    race_operation_key = stalled_ledger.operation_key(
        effect_slot_sha256=race_request.effect_slot_sha256,
        effect_type="github.issue-delivery.claim.v1",
    )
    with psycopg.connect(race.store.dsn) as conn:
        conn.execute(
            "UPDATE builderops_outbox "
            "SET claim_expires_at = clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND operation_key = %s",
            (REPOSITORY, race_operation_key),
        )
    recovery_ledger = BuilderOpsIssueDeliveryEffectLedger(
        race.host,
        repository=REPOSITORY,
        run_id=race_request.run_id,
        approval_id=race_request.approval_id,
        worker_id="issue-delivery-host",
    )
    recovery_claim = recovery_ledger.claim_for_readback(race_operation_key)
    assert recovery_claim["effect_eligible"] is False
    recovery_result = recovery_ledger.reconcile(
        recovery_claim,
        observed_applied=False,
        evidence={
            "outcome": "not_applied",
            "request_sha256": race_request.content_sha256,
            "source": "github-authoritative-readback",
        },
    )
    assert recovery_result == {
        "status": "unknown",
        "retry_refused": "committed-dispatch-may-still-complete",
    }
    stalled_ledger.dispatch_release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(stalled_result) == 1
    assert isinstance(stalled_result[0], IssueDeliveryEffectReceipt)
    assert stalled_result[0].outcome == "unknown"
    assert stale_transport.apply_calls == 0

    with psycopg.connect(race.store.dsn) as conn:
        race_row = conn.execute(
            "SELECT status, claim_fencing_token FROM builderops_outbox "
            "WHERE repository = %s AND operation_key = %s",
            (REPOSITORY, race_operation_key),
        ).fetchone()
    assert race_row == ("unknown", 2)


def test_unit_revocation_and_target_drift_fail_closed(tmp_path: Path) -> None:
    (
        executor,
        request,
        authority,
        destination,
        repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path)
    authority.revoked = True
    with pytest.raises(ValueError, match="revoked"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    authority.revoked = False
    changed_target = request.target.model_dump(mode="json")
    changed_target["issue_number"] = 5559
    transport.target_override = {"target": changed_target}
    with pytest.raises(ValueError, match="target/source/profile"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0
    assert ledger.state == "pending"

    transport.target_override = None
    destination.drifted = True
    with pytest.raises(ValueError, match="destination"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    destination.drifted = False
    repository.drifted = True
    with pytest.raises(ValueError, match="protected repository manifest changed"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    (tmp_path / "issue_delivery_effect_executor.py").write_text(
        "replaced\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="artifact"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    workflow_executor, workflow_request, *_rest, workflow_transport = _executor(
        tmp_path / "workflow-artifact"
    )
    (
        tmp_path
        / "workflow-artifact"
        / "workflow-root"
        / ".codex/skills/publish-pr/SKILL.md"
    ).write_text("replaced\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact"):
        workflow_executor.execute(workflow_request)
    assert workflow_transport.apply_calls == 0

    epoch_executor, epoch_request, epoch_authority, *_ = _executor(tmp_path / "epoch")
    epoch_authority.epoch_drifted = True
    with pytest.raises(ValueError, match="authority changed"):
        epoch_executor.execute(epoch_request)

    source_executor, source_request, *_rest, source_transport = _executor(
        tmp_path / "source"
    )
    source_transport.target_override = {"source_revision": "b" * 40}
    with pytest.raises(ValueError, match="target/source/profile"):
        source_executor.execute(source_request)
    assert source_transport.apply_calls == 0

    profile_executor, profile_request, *_rest, profile_transport = _executor(
        tmp_path / "profile"
    )
    profile_transport.target_override = {"profile_hash": "e" * 64}
    with pytest.raises(ValueError, match="target/source/profile"):
        profile_executor.execute(profile_request)
    assert profile_transport.apply_calls == 0

    (
        parent_executor,
        parent_request,
        parent_authority,
        *_rest,
        parent_transport,
    ) = _executor(tmp_path / "parent", effect_kind="parent_evidence", parent=True)
    foreign_parent = parent_request.model_dump(mode="json")
    foreign_parent["target"]["issue_number"] = 5400
    with pytest.raises(ValueError, match="parent evidence"):
        parent_executor.execute(
            IssueDeliveryEffectRequest.model_validate(foreign_parent)
        )
    assert parent_transport.apply_calls == 0

    foreign_repository = parent_request.model_dump(mode="json")
    foreign_repository["approval"]["parent_evidence"]["repository"] = (
        "other/parent-repository"
    )
    foreign_repository["target"]["repository"] = "other/parent-repository"
    parent_authority.approval = deepcopy(foreign_repository["approval"])
    with pytest.raises(ValueError, match="parent evidence"):
        parent_executor.execute(
            IssueDeliveryEffectRequest.model_validate(foreign_repository)
        )
    assert parent_transport.apply_calls == 0

    readback_executor, readback_request, *_rest, readback_transport = _executor(
        tmp_path / "readback"
    )
    readback_transport.raise_on_apply = True
    readback_transport.readback_target_override = "f" * 64
    with pytest.raises(ValueError, match="readback target changed"):
        readback_executor.execute(readback_request)
    assert readback_transport.apply_calls == 1

    stale_executor, stale_request, *_rest, stale_ledger, stale_transport = _executor(
        tmp_path / "stale-fence"
    )
    stale_ledger.effect_revalidation_override = {"fencing_token": 2}
    with pytest.raises(ValueError, match="fence changed"):
        stale_executor.execute(stale_request)
    assert stale_transport.apply_calls == 0

    expired_executor, expired_request, *_ = _executor(tmp_path / "expired-fence")
    expired_claim = {
        "repository": REPOSITORY,
        "operation_key": "outbox-operation",
        "worker_id": "host-executor",
        "fencing_token": 1,
        "intent_lsn": "0/1",
        "claim_lsn": "0/2",
        "receipt_sequence": 1,
        "expires_at": "2000-01-01T00:00:00+00:00",
        "task_id": f"issue-delivery-effect:{expired_request.content_sha256}",
        "effect_type": "github.issue-delivery.claim.v1",
        "effect_eligible": True,
        "payload": {},
    }
    with pytest.raises(ValueError, match="not exact authority"):
        expired_executor._validate_effect_claim(
            expired_claim,
            "outbox-operation",
            "github.issue-delivery.claim.v1",
            {},
            repository=REPOSITORY,
        )


def test_unit_host_prepares_and_freezes_destination_before_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    worktree = tmp_path / "worktrees" / "issue-5558"
    checkout.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(checkout)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.name", "Issue Delivery Test"],
        check=True,
    )
    (checkout / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-m", "base"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "remote",
            "add",
            "origin",
            "https://github.com/RasmusTho/agentic-pkm-mvp.git",
        ],
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    approval = {
        "repository": REPOSITORY,
        "destination": DestinationBinding(
            identity="destination:shared",
            run_id="run-5558",
            host_identity="host:test",
            system_identity="system:builderops",
            channel="dev",
            repository=REPOSITORY,
            checkout=checkout,
            worktree=worktree,
            branch="codex/5558-host-prepared",
            base_ref="main",
            base_sha=base_sha,
        ).as_manifest(),
    }
    guard = GitIssueDeliveryDestination()
    with pytest.raises(ValueError, match="worktree is absent"):
        guard.prepare(approval)
    assert not worktree.parent.exists()
    worktree.parent.mkdir(parents=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "worktree",
            "add",
            "-b",
            "codex/5558-host-prepared",
            str(worktree),
            base_sha,
        ],
        check=True,
        capture_output=True,
    )
    approval["destination"]["resolved_checkout"] = str(checkout.resolve())
    approval["destination"]["resolved_worktree"] = str(worktree.resolve())
    frozen = guard.prepare(approval)
    tampered = deepcopy(approval)
    tampered["destination"]["resolved_worktree"] = str(
        (tmp_path / "retargeted-worktree").resolve()
    )
    with pytest.raises(ValueError, match="not approved"):
        guard.assert_frozen(frozen, tampered)
    calls: list[bool] = []

    launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)

    def fake_launch(self, context_pack, *, execution_routing=None):
        del self, context_pack, execution_routing
        calls.append(True)
        return {
            "session_id": "session",
            "worker_receipt": {},
            "isolation_receipt": _isolation_receipt(),
        }

    monkeypatch.setattr(ContentOnlyIssueDeliverySessionLauncher, "launch", fake_launch)

    worker = PreparedIssueDeliveryWorker.create(
        approval=approval,
        destination=guard,
        launcher_factory=lambda frozen: (
            launcher
            if frozen.binding.worktree.is_dir()
            else pytest.fail("worktree not prepared")
        ),
    )
    result = worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    assert result["isolation_receipt"]["git_metadata_write_denied"] is True
    assert calls == [True]

    # A symlink spelling is the portable equivalent of macOS /tmp ->
    # /private/tmp: the admitted raw plan may differ textually, but it must
    # resolve to exactly the frozen worktree identity and never retarget it.
    equivalent_spelling = tmp_path / "private-tmp-spelling"
    equivalent_spelling.symlink_to(worktree, target_is_directory=True)
    worker.launch({"branch_worktree_plan": {"worktree": str(equivalent_spelling)}})
    assert calls == [True, True]
    retargeted = tmp_path / "retargeted-worktree"
    retargeted.mkdir()
    with pytest.raises(ValueError, match="another worktree"):
        worker.launch({"branch_worktree_plan": {"worktree": str(retargeted)}})

    absent = worktree.with_name("issue-5558-absent")
    worktree.rename(absent)
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    absent.rename(worktree)

    original = worktree.with_name("issue-5558-original")
    worktree.rename(original)
    worktree.mkdir()
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    worktree.rmdir()
    original.rename(worktree)

    subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "remote",
            "set-url",
            "origin",
            "https://github.com/example/issue-delivery-mismatch.git",
        ],
        check=True,
    )
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "remote",
            "set-url",
            "origin",
            "https://github.com/RasmusTho/agentic-pkm-mvp.git",
        ],
        check=True,
    )

    subprocess.run(
        ["git", "-C", str(worktree), "switch", "-c", "foreign"],
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    assert calls == [True, True]
