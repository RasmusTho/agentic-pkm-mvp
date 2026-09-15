"""FCA-ID-B destination reservation, launch, and effect-gate proofs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.builderops.control_plane.client import (
    ControlPlaneAuthError,
    ControlPlaneNotFoundError,
    ControlPlaneUnavailableError,
)
from app.builderops.control_plane.issue_delivery import manifest_hash
from app.builderops.issue_delivery_operation import (
    IssueDeliveryOperationAdapter,
    IssueDeliveryOperationError,
    IssueDeliveryOperationRefused,
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
            for effect in (
                "repository_worktree",
                "issue_claim",
                "publication",
                "review_merge",
                "closure_reconciliation",
            ):
                effect_gate(effect)
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
        "checkout": str(Path(destination["checkout"]).resolve()),
        "worktree": str(Path(destination["worktree"]).resolve()),
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
    for effect in (
        "repository_worktree",
        "issue_claim",
        "publication",
        "review_merge",
        "closure_reconciliation",
    ):
        assert adapter.authorize_effect(effect)["effect"] == effect
    assert len(client.authority_calls) == 5

    client.revoked = True
    with pytest.raises(IssueDeliveryOperationRefused, match="unavailable"):
        adapter.authorize_effect("publication")

    with pytest.raises(IssueDeliveryOperationRefused, match="not permitted"):
        adapter.authorize_effect("deployment")


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
