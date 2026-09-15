"""FCA-ID-B destination reservation, launch, and effect-gate proofs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
from typing import Any, Mapping

import pytest

from app.builderops.control_plane.client import (
    ControlPlaneAuthError,
    ControlPlaneNotFoundError,
    ControlPlaneUnavailableError,
)
from app.builderops.control_plane.issue_delivery import (
    IssueDeliveryContractError,
    manifest_hash,
    normalize_manifest,
)
from app.builderops.issue_delivery_operation import (
    IssueDeliveryOperationAdapter,
    IssueDeliveryOperationError,
    IssueDeliveryOperationRefused,
    _default_live_binding_reader,
)
from tests.builderops.test_control_plane_issue_delivery import _manifest
from tests.builderops.test_control_plane_issue_delivery import (
    _client as _control_plane_client,
    registry as pg_registry_fixture,  # noqa: F401
    store as pg_store_fixture,  # noqa: F401
)


class _Client:
    def __init__(self, approval: Mapping[str, Any]) -> None:
        self.approval = dict(approval)
        self.records: dict[str, dict[str, Any]] = {}
        self.authority_calls: list[str] = []
        self.revoked = False
        self.fail_record_kinds: set[str] = set()

    def issue_delivery_authority(
        self, *, manifest: Mapping[str, Any], purpose: str
    ) -> dict[str, Any]:
        self.authority_calls.append(purpose)
        if self.revoked:
            raise ControlPlaneAuthError("revoked")
        return {
            "approval": self.approval,
            "purpose": purpose,
            "operation_key": self.approval["operation_key"],
            "authority_epoch": 1,
            "observed_at": "2026-09-15T08:00:00+00:00",
        }

    def issue_delivery_operation_record(self, **kwargs: Any) -> dict[str, Any]:
        kind = kwargs["record_id"].removeprefix("issue-delivery-").split(":", 1)[0]
        if kind in self.fail_record_kinds:
            raise ControlPlaneUnavailableError("synthetic receipt transport loss")
        record = {
            "record_type": "BuilderOpsReceipt",
            "state": kwargs["state"],
            "payload": deepcopy(kwargs["payload"]),
        }
        existing = self.records.get(kwargs["record_id"])
        if existing is not None and existing != record:
            raise RuntimeError("record conflict")
        replayed = existing is not None
        self.records[kwargs["record_id"]] = record
        return {"state": kwargs["state"], "replayed": replayed}

    def get_receipt(self, **kwargs: Any) -> dict[str, Any]:
        record = self.records.get(kwargs["object_id"])
        if record is None:
            raise ControlPlaneNotFoundError("not found")
        return deepcopy(record)

    def issue_delivery_operation_record_read(
        self, *, repository: str, record_id: str
    ) -> dict[str, Any]:
        return self.get_receipt(object_id=record_id)


class _Launcher:
    def __init__(self, *, fail: bool = False, session_id: str | None = "session-1") -> None:
        self.calls = 0
        self.fail = fail
        self.session_id = session_id

    def launch(
        self,
        _context_pack: Mapping[str, Any],
        *,
        on_entry: Any = None,
        effect_gate: Any = None,
    ) -> Mapping[str, Any]:
        self.calls += 1
        if effect_gate is not None:
            issue = _context_pack["issue_contract"]
            destination = _context_pack["branch_worktree_plan"]
            target = {
                "repository": issue["repository"],
                "issue_number": issue["number"],
                "worktree": destination["worktree"],
                "branch": destination["branch"],
            }
            for effect in (
                "repository_worktree",
                "issue_claim",
                "publication",
                "review_merge",
                "closure_reconciliation",
            ):
                effect_target = dict(target)
                if effect in {"review_merge", "closure_reconciliation"}:
                    effect_target.update(
                        {
                            "pr_number": 1,
                            "pr_repository": issue["repository"],
                            "pr_issue_number": issue["number"],
                            "pr_head_ref": destination["branch"],
                            "pr_base_ref": "main",
                        }
                    )
                effect_gate(effect, target=effect_target)
        if on_entry is not None and self.session_id is not None:
            on_entry(self.session_id)
        if self.fail:
            error = RuntimeError("response lost")
            error.session_id = self.session_id  # type: ignore[attr-defined]
            raise error
        return {
            "session_id": self.session_id,
            "worker_receipt": {
                "role": "slice_implementer",
                "final_state": "handoff",
            },
        }


def _approved_live_binding(approval: Mapping[str, Any]) -> Mapping[str, Any]:
    destination = approval["destination"]
    workflow = approval["workflow"]
    return {
        "checkout": str(destination["resolved_checkout"]),
        "worktree": str(destination["resolved_worktree"]),
        "branch": destination["branch"],
        "source_revision": approval["source"]["revision"],
        "base_sha": destination["base_sha"],
        "workflow_hash": workflow["content_hash"],
        "workflow_artifacts": sorted(
            [
                {"path": artifact["path"], "sha256": artifact["sha256"]}
                for artifact in workflow["artifacts"]
            ],
            key=lambda item: item["path"],
        ),
    }


def _adapter(*, client: _Client, launcher: _Launcher) -> IssueDeliveryOperationAdapter:
    approval = client.approval
    return IssueDeliveryOperationAdapter(
        approval,
        client=client,
        launcher=launcher,
        repo_root=Path(approval["destination"]["checkout"]),
        live_binding_reader=_approved_live_binding,
    )


def test_production_dispatch_reservation_and_crash_matrix() -> None:
    approval = _manifest(operation_key="operation-b-matrix")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = _Client(approval)
    launcher = _Launcher()
    adapter = _adapter(client=client, launcher=launcher)
    context = approval["context"]["dispatch_plan"]["context_packs"][0]

    result = adapter.launch(context)
    assert result["operation_state"] == "terminal"
    assert launcher.calls == 1
    assert set(client.records) == {
        "issue-delivery-reservation:operation-b-matrix",
        "issue-delivery-attempt:operation-b-matrix",
        "issue-delivery-entry:operation-b-matrix",
        "issue-delivery-terminal:operation-b-matrix",
    }

    replay = adapter.launch(context)
    assert replay["session_id"] == "session-1"
    assert launcher.calls == 1

    crashing_approval = _manifest(operation_key="operation-b-crash")
    crashing_approval["approval_manifest_hash"] = manifest_hash(crashing_approval)
    crashing_client = _Client(crashing_approval)
    crashing_launcher = _Launcher(fail=True, session_id="session-crashed")
    crashing = _adapter(client=crashing_client, launcher=crashing_launcher)
    crashing_context = crashing_approval["context"]["dispatch_plan"]["context_packs"][0]
    with pytest.raises(IssueDeliveryOperationError, match="ambiguous|replacement"):
        crashing.launch(crashing_context)
    assert crashing_launcher.calls == 1
    assert crashing_client.records["issue-delivery-terminal:operation-b-crash"]["state"] == "launch_unknown"
    assert (
        crashing_client.records["issue-delivery-terminal:operation-b-crash"]["payload"][
            "entry_receipt_hash"
        ]
        is None
    )
    with pytest.raises(IssueDeliveryOperationError, match="unresolved"):
        crashing.launch(crashing_context)
    assert crashing_launcher.calls == 1

    competing = deepcopy(approval)
    competing["approval_id"] = "approval-b-other"
    competing["approval_manifest_hash"] = manifest_hash(competing)
    competing_client = _Client(competing)
    competing_client.records = client.records
    with pytest.raises(IssueDeliveryOperationError, match="different operation"):
        _adapter(client=competing_client, launcher=_Launcher()).launch(context)

    pre_attempt_approval = _manifest(operation_key="operation-b-before-attempt")
    pre_attempt_approval["approval_manifest_hash"] = manifest_hash(pre_attempt_approval)
    pre_attempt_client = _Client(pre_attempt_approval)
    pre_attempt_client.fail_record_kinds.add("attempt")
    pre_attempt_launcher = _Launcher()
    pre_attempt = _adapter(client=pre_attempt_client, launcher=pre_attempt_launcher)
    pre_attempt_context = pre_attempt_approval["context"]["dispatch_plan"]["context_packs"][0]
    with pytest.raises(IssueDeliveryOperationError, match="durably committed|unavailable"):
        pre_attempt.launch(pre_attempt_context)
    assert pre_attempt_launcher.calls == 0
    pre_attempt_client.fail_record_kinds.clear()
    pre_attempt.launch(pre_attempt_context)
    assert pre_attempt_launcher.calls == 1

    lost_entry_approval = _manifest(operation_key="operation-b-lost-entry")
    lost_entry_approval["approval_manifest_hash"] = manifest_hash(lost_entry_approval)
    lost_entry_client = _Client(lost_entry_approval)
    lost_entry_client.fail_record_kinds.add("entry")
    lost_entry_launcher = _Launcher(session_id="session-lost-entry")
    lost_entry = _adapter(client=lost_entry_client, launcher=lost_entry_launcher)
    lost_entry_context = lost_entry_approval["context"]["dispatch_plan"]["context_packs"][0]
    with pytest.raises(IssueDeliveryOperationError, match="durably committed|unavailable"):
        lost_entry.launch(lost_entry_context)
    assert lost_entry_launcher.calls == 1
    lost_entry_client.fail_record_kinds.clear()
    with pytest.raises(IssueDeliveryOperationError, match="attempt|replacement"):
        lost_entry.launch(lost_entry_context)
    assert lost_entry_launcher.calls == 1


def test_delivery_effect_boundaries_recheck_authority() -> None:
    approval = _manifest(operation_key="operation-b-gates")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = _Client(approval)
    adapter = _adapter(client=client, launcher=_Launcher())
    target = {
        "repository": "RasmusTho/agentic-pkm-mvp",
        "issue_number": 5550,
        "worktree": "/worktrees/issue-5550",
        "branch": "codex/5550-issue-delivery-approval",
    }
    for effect in (
        "repository_worktree",
        "issue_claim",
        "publication",
        "review_merge",
        "closure_reconciliation",
    ):
        effect_target = dict(target)
        if effect in {"review_merge", "closure_reconciliation"}:
            effect_target.update(
                {
                    "pr_number": 1,
                    "pr_repository": "RasmusTho/agentic-pkm-mvp",
                    "pr_issue_number": 5550,
                    "pr_head_ref": "codex/5550-issue-delivery-approval",
                    "pr_base_ref": "main",
                }
            )
        assert adapter.authorize_effect(effect, target=effect_target)["effect"] == effect
    assert len(client.authority_calls) == 5

    assert adapter.authorize_effect("publication", target=target)["target"] == target
    with pytest.raises(IssueDeliveryOperationRefused, match="target is required"):
        adapter.authorize_effect("publication")
    with pytest.raises(IssueDeliveryOperationRefused, match="Issue differs"):
        adapter.authorize_effect(
            "publication", target={**target, "issue_number": 5551}
        )
    with pytest.raises(IssueDeliveryOperationRefused, match="PR binding is incomplete"):
        adapter.authorize_effect("review_merge", target=target)

    client.revoked = True
    with pytest.raises(IssueDeliveryOperationRefused, match="unavailable"):
        adapter.authorize_effect("publication", target=target)

    with pytest.raises(IssueDeliveryOperationRefused, match="not permitted"):
        adapter.authorize_effect("deployment", target=target)


def test_closure_effect_binds_an_approved_parent_target() -> None:
    approval = _manifest(operation_key="operation-b-parent-gate")
    approval["parent_evidence"] = {
        "kind": "issue",
        "repository": "RasmusTho/agentic-pkm-mvp",
        "number": 5399,
    }
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = _Client(approval)
    adapter = _adapter(client=client, launcher=_Launcher())

    target = {
        "repository": "RasmusTho/agentic-pkm-mvp",
        "issue_number": 5550,
        "worktree": "/worktrees/issue-5550",
        "branch": "codex/5550-issue-delivery-approval",
        "pr_number": 1,
        "pr_repository": "RasmusTho/agentic-pkm-mvp",
        "pr_issue_number": 5550,
        "pr_head_ref": "codex/5550-issue-delivery-approval",
        "pr_base_ref": "main",
    }
    authorized = adapter.authorize_effect("closure_reconciliation", target=target)
    assert authorized["target"]["parent_repository"] == "RasmusTho/agentic-pkm-mvp"
    assert authorized["target"]["parent_issue_number"] == 5399
    with pytest.raises(IssueDeliveryOperationRefused, match="parent Issue differs"):
        adapter.authorize_effect(
            "closure_reconciliation",
            target={
                **authorized["target"],
                "parent_issue_number": 5400,
            },
        )
    with pytest.raises(IssueDeliveryOperationRefused, match="target Issue is required"):
        adapter.authorize_effect(
            "closure_reconciliation",
            target={"repository": "RasmusTho/agentic-pkm-mvp"},
        )
    with pytest.raises(IssueDeliveryOperationRefused, match="existing Issue"):
        adapter.authorize_effect(
            "closure_reconciliation",
            target={
                "repository": "RasmusTho/agentic-pkm-mvp",
                "issue_number": None,
            },
        )


def test_live_binding_rejects_a_retargeted_approved_checkout(tmp_path: Path) -> None:
    actual_checkout = tmp_path / "actual-checkout"
    actual_checkout.mkdir()
    (actual_checkout / "tracked.txt").write_text("approved\n", encoding="utf-8")
    link = tmp_path / "checkout-link"
    link.symlink_to(actual_checkout, target_is_directory=True)
    other_checkout = tmp_path / "other-checkout"
    other_checkout.mkdir()
    (other_checkout / "tracked.txt").write_text("retargeted\n", encoding="utf-8")

    approval = {
        "destination": {
            "checkout": str(link),
            "resolved_checkout": str(actual_checkout),
            "worktree": str(tmp_path / "worktree"),
            "resolved_worktree": str(tmp_path / "worktree"),
            "base_sha": "a" * 40,
            "branch": "codex/test",
        },
        "workflow": {
            "artifacts": [{"path": "tracked.txt", "sha256": ""}],
            "content_hash": "workflow",
        },
        "source": {"revision": "source"},
    }
    # The reader checks identity before the Git/artifact assertions, so this
    # focused fixture does not need to pretend that the temporary directory is
    # a complete approved checkout.
    link.unlink()
    link.symlink_to(other_checkout, target_is_directory=True)
    with pytest.raises(IssueDeliveryOperationRefused, match="identity changed"):
        _default_live_binding_reader(approval)


@pytest.mark.parametrize("drift", ["common-dir", "repository", "branch"])
def test_live_binding_rechecks_git_identity_and_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    checkout = tmp_path / "checkout"
    worktree = tmp_path / "worktree"
    checkout.mkdir()
    worktree.mkdir()
    artifact = checkout / "tracked.txt"
    artifact.write_text("approved\n", encoding="utf-8")
    common_dir = checkout / ".git"
    other_common_dir = tmp_path / "other.git"
    approved_branch = "codex/approved"

    approval = {
        "repository": "RasmusTho/agentic-pkm-mvp",
        "destination": {
            "checkout": str(checkout),
            "resolved_checkout": str(checkout),
            "worktree": str(worktree),
            "resolved_worktree": str(worktree),
            "base_sha": "a" * 40,
            "branch": approved_branch,
        },
        "workflow": {
            "artifacts": [
                {
                    "path": "tracked.txt",
                    "sha256": hashlib.sha256(b"approved\n").hexdigest(),
                }
            ],
            "content_hash": "workflow",
        },
        "source": {"revision": "source"},
    }

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        path = Path(argv[2])
        args = argv[3:]
        if args == ["rev-parse", "HEAD"]:
            output = "a" * 40
        elif args == ["rev-parse", "--show-toplevel"]:
            output = str(path)
        elif args == ["rev-parse", "--git-common-dir"]:
            output = str(
                other_common_dir
                if drift == "common-dir" and path == checkout
                else common_dir
            )
        elif args == ["symbolic-ref", "--short", "HEAD"]:
            output = "codex/drifted" if drift == "branch" else approved_branch
        elif args == ["remote", "get-url", "origin"]:
            output = (
                "https://github.com/other-owner/other-repo.git"
                if drift == "repository"
                else "https://github.com/RasmusTho/agentic-pkm-mvp.git"
            )
        else:
            raise AssertionError(f"unexpected git probe: {argv}")
        return subprocess.CompletedProcess(argv, 0, stdout=output + "\n", stderr="")

    monkeypatch.setattr("app.builderops.issue_delivery_operation.subprocess.run", fake_run)
    with pytest.raises(IssueDeliveryOperationRefused, match=drift):
        _default_live_binding_reader(approval)


def test_admission_freezes_resolved_destination_identity() -> None:
    raw = _manifest(operation_key="operation-b-frozen-path")
    raw["destination"].pop("resolved_checkout")  # type: ignore[union-attr]
    raw["destination"].pop("resolved_worktree")  # type: ignore[union-attr]
    normalized = normalize_manifest(raw)
    assert normalized["destination"]["resolved_checkout"] == "/workspaces/agentic-pkm-mvp"
    assert normalized["destination"]["resolved_worktree"] == "/worktrees/issue-5550"

    conflicting = _manifest(operation_key="operation-b-conflicting-path")
    conflicting["destination"]["resolved_checkout"] = "/other-checkout"  # type: ignore[union-attr]
    with pytest.raises(IssueDeliveryContractError, match="approved path"):
        normalize_manifest(conflicting)


def test_selected_launcher_reports_stop_unsupported() -> None:
    approval = _manifest(operation_key="operation-b-stop")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    adapter = _adapter(client=_Client(approval), launcher=_Launcher())
    assert adapter.stop() == {
        "stop_support": "unsupported",
        "stop_status": "unsupported",
    }


@pytest.mark.pg
def test_production_control_plane_operation_records(store, registry) -> None:
    """Exercise the adapter against the real authenticated service and store."""

    owner = _control_plane_client(store, registry, "owner-token")
    executor = _control_plane_client(store, registry, "executor-high-token")
    preview = owner.issue_delivery_preview(
        manifest=_manifest(operation_key="operation-b-service")
    )
    started = owner.issue_delivery_start(
        decision="start", manifest=preview["manifest"]
    )
    approval = started["approval"]
    context = approval["context"]["dispatch_plan"]["context_packs"][0]
    launcher = _Launcher(session_id="session-service")
    adapter = IssueDeliveryOperationAdapter(
        approval,
        client=executor,
        launcher=launcher,
        repo_root=Path(approval["destination"]["checkout"]),
        live_binding_reader=_approved_live_binding,
    )

    adapter.bind_dispatch_plan(approval["context"]["dispatch_plan"])
    first = adapter.launch(context)
    assert first["operation_state"] == "terminal"
    assert launcher.calls == 1
    replay = adapter.launch(context)
    assert replay["session_id"] == "session-service"
    assert launcher.calls == 1
    receipt = executor.issue_delivery_operation_record_read(
        repository=approval["repository"],
        record_id="issue-delivery-entry:operation-b-service",
    )
    assert receipt["payload"]["session_id"] == "session-service"
