"""Production-path proofs for FCA-ID-B destination operation state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Mapping
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root

from app.builderops.control_plane.client import (
    ControlPlaneAuthError,
    ControlPlaneNotFoundError,
    ControlPlaneUnavailableError,
)
from app.builderops.control_plane.issue_delivery import (
    canonical_hash,
    destination_resource_key,
    manifest_hash,
    strip_server_fields,
)
from app.builderops.epic_dispatch import dispatch_issue_sessions
from app.builderops.issue_delivery_operation import (
    IssueDeliveryOperationAdapter,
    IssueDeliveryOperationError,
    IssueDeliveryOperationRefused,
    _digest,
    observe_issue_delivery_operation,
    _default_live_binding_reader,
    _require_protected_host_executor,
)
from app.builderops.issue_delivery_effect_executor import (
    ContentOnlyIssueDeliverySessionLauncher,
    PreparedIssueDeliveryWorker,
    WorkerIsolationBinding,
)
from app.builderops.issue_delivery_worker_isolation import _run_streaming_process
from tests.builderops.test_control_plane_issue_delivery import _manifest
from tests.builderops.issue_delivery_production_harness import _ProductionHarness


def _binding(approval: Mapping[str, Any]) -> dict[str, Any]:
    destination = approval["destination"]
    return {
        "checkout": str(destination["checkout"]),
        "worktree": str(destination["worktree"]),
        "branch": str(destination["branch"]),
        "source_revision": str(approval["source"]["revision"]),
        "base_sha": str(destination["base_sha"]),
        "workflow_hash": str(approval["workflow"]["content_hash"]),
        "workflow_artifacts": sorted(
            [
                {"path": str(item["path"]), "sha256": str(item["sha256"])}
                for item in approval["workflow"]["artifacts"]
            ],
            key=lambda item: item["path"],
        ),
    }


class Client:
    def __init__(self, approval: Mapping[str, Any]) -> None:
        self.approval = deepcopy(dict(approval))
        self.records: dict[str, dict[str, Any]] = {}
        self.fail: set[str] = set()
        self.revoked = False
        self.read_only = False
        self.authority_calls: list[str] = []

    def issue_delivery_authority(
        self, *, manifest: Mapping[str, Any], purpose: str
    ) -> dict[str, Any]:
        self.authority_calls.append(purpose)
        if self.revoked:
            raise ControlPlaneAuthError("revoked")
        if self.read_only and purpose == "execute":
            raise ControlPlaneAuthError("read-only credential")
        return {
            "approval": self.approval,
            "purpose": purpose,
            "operation_key": self.approval["operation_key"],
            "authority_epoch": 1,
            "observed_at": "2026-09-16T00:00:00+00:00",
        }

    def issue_delivery_operation_record(self, **kwargs: Any) -> dict[str, Any]:
        kind = kwargs["record_id"].removeprefix("issue-delivery-").split(":", 1)[0]
        if kind in self.fail:
            raise ControlPlaneUnavailableError("receipt unavailable")
        record = {
            "record_type": "BuilderOpsReceipt",
            "state": kwargs["state"],
            "payload": deepcopy(kwargs["payload"]),
            "replayed": False,
        }
        previous = self.records.get(kwargs["record_id"])
        if previous is not None and previous != record:
            raise RuntimeError("receipt conflict")
        record["replayed"] = previous is not None
        self.records[kwargs["record_id"]] = record
        return {"replayed": record["replayed"]}

    def issue_delivery_operation_record_read(
        self, *, repository: str, record_id: str
    ) -> dict[str, Any]:
        del repository
        if record_id not in self.records:
            raise ControlPlaneNotFoundError("not found")
        return deepcopy(self.records[record_id])


class Launcher:
    def __init__(self, *, session_id: str = "session-1", fail: bool = False) -> None:
        self.session_id, self.fail, self.calls = session_id, fail, 0

    def launch(
        self, context: Mapping[str, Any], *, on_entry: Any = None, effect_gate: Any = None
    ) -> Mapping[str, Any]:
        self.calls += 1
        if effect_gate is not None:
            issue = context["issue_contract"]
            plan = context["branch_worktree_plan"]
            target = {
                "repository": issue["repository"],
                "issue_number": issue["number"],
                "checkout": "/workspaces/agentic-pkm-mvp",
                "worktree": plan["worktree"],
                "branch": plan["branch"],
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
                            "pr_head_ref": plan["branch"],
                            "pr_base_ref": "main",
                        }
                    )
                effect_gate(effect, target=effect_target)
        if on_entry is not None:
            on_entry(self.session_id)
        if self.fail:
            error = RuntimeError("response lost")
            error.session_id = self.session_id  # type: ignore[attr-defined]
            raise error
        return {"session_id": self.session_id, "worker_receipt": {"final_state": "handoff"}}


class TimeoutAfterEntryLauncher(Launcher):
    """Persist a streamed entry, then lose the launcher response."""

    def launch(
        self, context: Mapping[str, Any], *, on_entry: Any = None, effect_gate: Any = None
    ) -> Mapping[str, Any]:
        del context, effect_gate
        self.calls += 1
        assert on_entry is not None
        on_entry(self.session_id)
        raise TimeoutError("launcher response lost")


def _adapter(
    approval: Mapping[str, Any], client: Client, launcher: Launcher
) -> IssueDeliveryOperationAdapter:
    return IssueDeliveryOperationAdapter(
        approval, client=client, launcher=launcher, repo_root=None, live_binding_reader=_binding
    )


def test_authenticated_observation_replays_terminal_before_fresh_preparation() -> None:
    approval = _manifest(operation_key="operation-observe-terminal")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    adapter = _adapter(approval, client, Launcher())
    adapter.reserve()
    adapter.record_attempt()
    adapter.record_entry(session_id="session-observe-terminal")
    adapter.record_terminal(
        session_id="session-observe-terminal",
        worker_receipt={"final_state": "handoff"},
    )
    original_records = deepcopy(client.records)
    client.authority_calls.clear()

    observed = observe_issue_delivery_operation(
        approval,
        client=client,
        plan=approval["context"]["dispatch_plan"],
        expected_plan_hash=approval["context"]["expected_plan_hash"],
        repo_root=Path(str(approval["destination"]["worktree"])),
    )

    assert observed.state == "terminal"
    assert observed.session_id == "session-observe-terminal"
    assert observed.worker_receipt == {"final_state": "handoff"}
    assert observed.host_effect_refs == []
    assert client.records == original_records
    assert client.authority_calls == ["readback"]


def test_authenticated_observation_uses_durable_entry_for_launch_unknown_without_terminal_session() -> (
    None
):
    approval = _manifest(operation_key="operation-observe-launch-unknown-entry")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    launcher = TimeoutAfterEntryLauncher(session_id="session-observed-before-timeout")
    adapter = _adapter(approval, client, launcher)

    with pytest.raises(IssueDeliveryOperationError, match="replacement launch is forbidden"):
        adapter.launch(approval["context"]["dispatch_plan"]["context_packs"][0])

    original_records = deepcopy(client.records)
    client.authority_calls.clear()
    observed = observe_issue_delivery_operation(
        approval,
        client=client,
        plan=approval["context"]["dispatch_plan"],
        expected_plan_hash=approval["context"]["expected_plan_hash"],
        repo_root=Path(str(approval["destination"]["worktree"])),
    )

    assert observed.state == "launch_unknown"
    assert observed.session_id == "session-observed-before-timeout"
    assert client.records == original_records
    assert client.authority_calls == ["readback"]
    assert launcher.calls == 1

    terminal = client.records["issue-delivery-terminal:operation-observe-launch-unknown-entry"][
        "payload"
    ]
    terminal["session_id"] = "session-conflicts-with-entry"
    terminal["receipt_hash"] = _digest(
        {key: value for key, value in terminal.items() if key != "receipt_hash"}
    )
    with pytest.raises(IssueDeliveryOperationRefused, match="session id conflicts"):
        observe_issue_delivery_operation(
            approval,
            client=client,
            plan=approval["context"]["dispatch_plan"],
            expected_plan_hash=approval["context"]["expected_plan_hash"],
            repo_root=Path(str(approval["destination"]["worktree"])),
        )
    assert launcher.calls == 1


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("not_started", "not_started"),
        ("reserved", "reserved"),
        ("attempt", "reconciliation_required"),
        ("entry", "active"),
        ("launch_unknown", "launch_unknown"),
    ],
)
def test_authenticated_observation_classifies_preparation_free_recovery_states(
    stage: str, expected: str
) -> None:
    approval = _manifest(operation_key=f"operation-observe-{stage}")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    adapter = _adapter(approval, client, Launcher())
    if stage != "not_started":
        adapter.reserve()
    if stage in {"attempt", "entry", "launch_unknown"}:
        adapter.record_attempt()
    if stage == "entry":
        adapter.record_entry(session_id="session-observe-active")
    if stage == "launch_unknown":
        adapter.record_terminal(session_id=None, worker_receipt=None, state="launch_unknown")
    original_records = deepcopy(client.records)
    client.authority_calls.clear()

    observed = observe_issue_delivery_operation(
        approval,
        client=client,
        plan=approval["context"]["dispatch_plan"],
        expected_plan_hash=approval["context"]["expected_plan_hash"],
        repo_root=Path(str(approval["destination"]["worktree"])),
    )

    assert observed.state == expected
    assert client.records == original_records
    assert client.authority_calls == ["readback"]


def test_authenticated_observation_refuses_changed_contracts_and_read_only_fresh_attempt() -> None:
    approval = _manifest(operation_key="operation-observe-refusal")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    plan = deepcopy(approval["context"]["dispatch_plan"])
    with pytest.raises(IssueDeliveryOperationRefused, match="dispatch plan differs"):
        observe_issue_delivery_operation(
            approval,
            client=client,
            plan={**plan, "run_id": "other-run"},
            expected_plan_hash=approval["context"]["expected_plan_hash"],
            repo_root=Path(str(approval["destination"]["worktree"])),
        )
    changed = deepcopy(approval)
    changed["operation_key"] = "foreign-operation"
    with pytest.raises(IssueDeliveryOperationRefused, match="approval hash is corrupt"):
        observe_issue_delivery_operation(
            changed,
            client=client,
            plan=plan,
            expected_plan_hash=approval["context"]["expected_plan_hash"],
            repo_root=Path(str(approval["destination"]["worktree"])),
        )
    client.read_only = True
    observed = observe_issue_delivery_operation(
        approval,
        client=client,
        plan=plan,
        expected_plan_hash=approval["context"]["expected_plan_hash"],
        repo_root=Path(str(approval["destination"]["worktree"])),
    )
    assert observed.state == "not_started"
    with pytest.raises(IssueDeliveryOperationRefused, match="authority is unavailable"):
        _adapter(approval, client, Launcher()).reserve()


def test_observed_not_started_race_loses_attempt_ownership_before_child_entry() -> None:
    approval = _manifest(operation_key="operation-observe-race")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    plan = approval["context"]["dispatch_plan"]
    observed = observe_issue_delivery_operation(
        approval,
        client=client,
        plan=plan,
        expected_plan_hash=approval["context"]["expected_plan_hash"],
        repo_root=Path(str(approval["destination"]["worktree"])),
    )
    assert observed.state == "not_started"
    winner = _adapter(approval, client, Launcher())
    reservation = winner.reserve()
    attempt = winner.record_attempt()
    assert (
        attempt["payload"]["destination_resource_key"]
        == reservation["payload"]["destination_resource_key"]
    )

    _attempt, owns_attempt = _adapter(approval, client, Launcher())._record_attempt()

    assert owns_attempt is False


@pytest.mark.parametrize("profile_state", ["missing", "directory", "unreadable"])
def test_cli_recomposition_replays_terminal_before_worker_or_executor_construction(
    tmp_path: Path, profile_state: str
) -> None:
    """A restarted CLI must observe a completed descendant worktree first."""

    destination = tmp_path / "advanced-destination"

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(destination), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    subprocess.run(["git", "init", str(destination)], check=True, capture_output=True)
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (destination / "receipt.txt").write_text("base\n", encoding="utf-8")
    git("add", "receipt.txt")
    git("commit", "-m", "base")
    approved_base = git("rev-parse", "HEAD")
    (destination / "receipt.txt").write_text("publication\n", encoding="utf-8")
    git("add", "receipt.txt")
    git("commit", "-m", "approved-publication")
    assert git("rev-parse", "HEAD") != approved_base
    git("merge-base", "--is-ancestor", approved_base, "HEAD")

    approval = _manifest(operation_key="operation-cli-terminal-replay")
    plan = deepcopy(approval["context"]["dispatch_plan"])
    branch = git("branch", "--show-current")
    plan["context_packs"][0]["branch_worktree_plan"].update(
        {"worktree": str(destination), "branch": branch}
    )
    approval["destination"].update(
        {
            "checkout": str(destination),
            "worktree": str(destination),
            "resolved_checkout": str(destination),
            "resolved_worktree": str(destination),
            "branch": branch,
            "base_sha": approved_base,
            "run_id": plan["run_id"],
        }
    )
    approval["context"]["dispatch_plan"] = plan
    approval["context"]["expected_plan_hash"] = canonical_hash(plan)
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    adapter = _adapter(approval, client, Launcher())
    adapter.reserve()
    adapter.record_attempt()
    adapter.record_entry(session_id="session-cli-terminal-replay")
    adapter.record_terminal(
        session_id="session-cli-terminal-replay",
        worker_receipt={"final_state": "handoff", "diagnostics": {"summary": "done"}},
    )
    approval_file = tmp_path / "approval.json"
    plan_file = tmp_path / "plan.json"
    profile_file = tmp_path / "profile.json"
    if profile_state == "directory":
        profile_file.mkdir()
    elif profile_state == "unreadable":
        profile_file.write_text("{}", encoding="utf-8")
        profile_file.chmod(0)
    approval_file.write_text(json.dumps({"approval": approval}), encoding="utf-8")
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    original_records = deepcopy(client.records)
    client.authority_calls.clear()
    client.close = lambda: None  # type: ignore[attr-defined]

    with (
        patch("app.builderops.cli.ClientConfig.from_env", return_value=object()),
        patch("app.builderops.cli.BuilderOpsControlPlaneClient", return_value=client),
        patch("app.builderops.cli.PreparedIssueDeliveryWorker.create") as prepared,
        patch("app.builderops.cli.build_host_issue_delivery_executor") as executor,
        patch("app.builderops.cli.dispatch_issue_sessions") as dispatch,
    ):
        result = CliRunner().invoke(
            builderops_standalone_root,
            [
                "builderops",
                "epic-run-state",
                "dispatch-sessions",
                "--plan-file",
                str(plan_file),
                "--repo-root",
                str(destination),
                "--approval-file",
                str(approval_file),
                "--expected-plan-hash",
                approval["context"]["expected_plan_hash"],
                "--worker-isolation-profile-file",
                str(profile_file),
                "--json",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sessions"][0]["fresh_session"] is False
    assert payload["sessions"][0]["worker_receipt"]["diagnostics"] == {"summary": "done"}
    assert payload["sessions"][0]["host_effect_refs"] == []
    prepared.assert_not_called()
    executor.assert_not_called()
    dispatch.assert_not_called()
    assert client.records == original_records
    assert client.authority_calls == ["readback"]


def test_cli_recomposition_replays_terminal_with_type_drifted_repo_root(tmp_path: Path) -> None:
    """Recovery binds the textual root before requiring a live directory."""

    repo_root = tmp_path / "replaced-worktree"
    repo_root.write_text("not a directory", encoding="utf-8")
    approval = _manifest(operation_key="operation-cli-file-root-replay")
    plan = deepcopy(approval["context"]["dispatch_plan"])
    plan["context_packs"][0]["branch_worktree_plan"]["worktree"] = str(repo_root)
    approval["destination"].update(
        {
            "checkout": str(repo_root),
            "worktree": str(repo_root),
            "resolved_checkout": str(repo_root),
            "resolved_worktree": str(repo_root),
        }
    )
    approval["context"]["dispatch_plan"] = plan
    approval["context"]["expected_plan_hash"] = canonical_hash(plan)
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    adapter = _adapter(approval, client, Launcher())
    adapter.reserve()
    adapter.record_attempt()
    adapter.record_entry(session_id="session-cli-file-root-replay")
    adapter.record_terminal(
        session_id="session-cli-file-root-replay",
        worker_receipt={"final_state": "handoff"},
    )
    approval_file = tmp_path / "approval.json"
    plan_file = tmp_path / "plan.json"
    approval_file.write_text(json.dumps({"approval": approval}), encoding="utf-8")
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    original_records = deepcopy(client.records)
    client.authority_calls.clear()
    client.close = lambda: None  # type: ignore[attr-defined]

    with (
        patch("app.builderops.cli.ClientConfig.from_env", return_value=object()),
        patch("app.builderops.cli.BuilderOpsControlPlaneClient", return_value=client),
        patch("app.builderops.cli.PreparedIssueDeliveryWorker.create") as prepared,
        patch("app.builderops.cli.build_host_issue_delivery_executor") as executor,
        patch("app.builderops.cli.dispatch_issue_sessions") as dispatch,
    ):
        result = CliRunner().invoke(
            builderops_standalone_root,
            [
                "builderops",
                "epic-run-state",
                "dispatch-sessions",
                "--plan-file",
                str(plan_file),
                "--repo-root",
                str(repo_root),
                "--approval-file",
                str(approval_file),
                "--expected-plan-hash",
                approval["context"]["expected_plan_hash"],
                "--json",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["sessions"][0]["fresh_session"] is False
    prepared.assert_not_called()
    executor.assert_not_called()
    dispatch.assert_not_called()
    assert client.records == original_records
    assert client.authority_calls == ["readback"]


def _production_binding(approval: Mapping[str, Any]) -> dict[str, Any]:
    """Return live facts from the production fixture's external read seams."""

    # Destination/source artifact identity is read from the fixture's real
    # pinned checkout.  Only the external Issue/profile source facts below
    # are substituted for this closed PostgreSQL composition test.
    binding = dict(_default_live_binding_reader(approval))
    issue = approval["issue"]
    source = approval["source"]
    binding.update(
        {
            "current_issue": {
                "number": issue["number"],
                "node_id": issue["node_id"],
                "state": "open",
                "body_hash": issue["body_hash"],
                "acceptance_criteria_hash": issue["acceptance_criteria_hash"],
            },
            "current_source": {
                "revision": source["revision"],
                "refs": list(source.get("refs", [])),
            },
            "current_profile": dict(approval["profile"]),
        }
    )
    return binding


def _production_adapter(
    harness: _ProductionHarness,
    approval: Mapping[str, Any] | None = None,
) -> IssueDeliveryOperationAdapter:
    # The fixture uses real create_app/PostgresStore/authenticated client,
    # PreparedIssueDeliveryWorker, ContentOnly launcher and protected host
    # executor.  Only the external GitHub/credential transports are replaced.
    approved = harness.approval if approval is None else approval
    setattr(harness.executor, "_live_binding_reader", _production_binding)
    return IssueDeliveryOperationAdapter(
        approved,
        client=harness.client,
        launcher=harness.prepared_worker,
        repo_root=harness.worktree,
        # The adapter's reservation/attempt and child-effect gates call the
        # protected host reader, which in turn reads the real fixture checkout
        # and receives only the explicitly substituted external facts.
        live_binding_reader=harness.executor.live_binding,
        protected_executor=harness.executor,
        require_protected_composition=True,
    )


def _cross_issue_approval(
    harness: _ProductionHarness, *, issue_number: int, suffix: str
) -> Mapping[str, Any]:
    """Admit another Issue identity against the harness's same destination."""

    manifest = deepcopy(strip_server_fields(harness.approval))
    manifest["approval_id"] = f"approval-pg-cross-{suffix}"
    manifest["operation_key"] = f"operation-pg-cross-{suffix}"
    manifest["expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    manifest["issue"] = {
        **manifest["issue"],
        "number": issue_number,
        "node_id": f"I_kwDOQEip6s8AAAACdXiy{issue_number}",
        "url": f"https://github.com/RasmusTho/agentic-pkm-mvp/issues/{issue_number}",
    }
    manifest["source"] = {
        **manifest["source"],
        "refs": [
            f"github:issue:{issue_number}",
            *[
                ref
                for ref in manifest["source"]["refs"]
                if not str(ref).startswith("github:issue:")
            ],
        ],
    }
    plan = manifest["context"]["dispatch_plan"]
    decision = plan["decisions"][0]
    context = plan["context_packs"][0]
    decision["issue_number"] = issue_number
    context["issue_contract"] = {
        **context["issue_contract"],
        "number": issue_number,
        "url": f"https://github.com/RasmusTho/agentic-pkm-mvp/issues/{issue_number}",
    }
    plan["epic_run_state_update"]["dispatch_decisions"][0]["issue_number"] = issue_number
    plan["scope"] = {**plan["scope"], "issue_numbers": [issue_number]}
    manifest["context"]["content_hash"] = canonical_hash(context)
    manifest["context"]["expected_plan_hash"] = canonical_hash(plan)
    preview = harness.owner.issue_delivery_preview(manifest=manifest)
    return harness.owner.issue_delivery_start(decision="start", manifest=preview["manifest"])[
        "approval"
    ]


@pytest.mark.pg
def test_production_dispatch_reservation_and_crash_matrix(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Before an authenticated attempt, the real operation route rejects a
    # fabricated entry and has no durable receipt to read back.
    before_attempt = issue_delivery_production_harness()
    before_adapter = _production_adapter(before_attempt)
    with pytest.raises(IssueDeliveryOperationRefused, match="attempt receipt"):
        before_adapter.record_entry(session_id="session-before-attempt")
    with pytest.raises(ControlPlaneNotFoundError):
        before_attempt.owner.issue_delivery_operation_record_read(
            repository=str(before_attempt.approval["repository"]),
            record_id=f"issue-delivery-entry:{before_attempt.approval['operation_key']}",
        )

    # Revoking the host credential at the pre-spawn hook refuses the claim
    # after reservation/attempt but before the content-only runner is entered.
    pre_entry_revoked = issue_delivery_production_harness()
    original_bind = pre_entry_revoked.executor.bind_completed_worker

    def revoke_then_bind() -> None:
        pre_entry_revoked.worker_transport._revoke_destination()
        original_bind()

    monkeypatch.setattr(pre_entry_revoked.executor, "bind_completed_worker", revoke_then_bind)
    refused_pre_entry = dispatch_issue_sessions(
        pre_entry_revoked.approval["context"]["dispatch_plan"],
        _production_adapter(pre_entry_revoked),
        expected_plan_hash=pre_entry_revoked.approval["context"]["expected_plan_hash"],
    )
    assert refused_pre_entry["stopped_reason"] == "session-launch-failed"
    assert pre_entry_revoked.worker_transport.calls == 0
    assert pre_entry_revoked.transport.apply_calls == 0
    for kind, state in (("reservation", "reserved"), ("attempt", "attempted")):
        assert (
            pre_entry_revoked.owner.issue_delivery_operation_record_read(
                repository=str(pre_entry_revoked.approval["repository"]),
                record_id=f"issue-delivery-{kind}:{pre_entry_revoked.approval['operation_key']}",
            )["state"]
            == state
        )

    harness = issue_delivery_production_harness()
    competing_approval = _cross_issue_approval(harness, issue_number=5552, suffix="unresolved")
    assert harness.approval["issue"]["number"] != competing_approval["issue"]["number"]
    assert harness.approval["context"]["dispatch_plan"]["scope"]["issue_numbers"] == [
        harness.approval["issue"]["number"]
    ]

    def assert_host_claim_precedes_content_worker() -> None:
        assert harness.transport.apply_calls == 1

    harness.worker_transport.pre_entry_check = assert_host_claim_precedes_content_worker
    adapter = _production_adapter(harness)
    adapter.reserve()
    with pytest.raises(IssueDeliveryOperationRefused, match="durably committed"):
        _production_adapter(harness, approval=competing_approval).reserve()
    plan = harness.approval["context"]["dispatch_plan"]
    result = dispatch_issue_sessions(
        plan,
        adapter,
        expected_plan_hash=harness.approval["context"]["expected_plan_hash"],
    )
    assert result["stopped_reason"] == "worker-handoff"
    assert result["sessions"][0]["fresh_session"] is True
    assert "effect_receipts" not in result["sessions"][0]["worker_receipt"]
    assert len(result["sessions"][0]["host_effect_refs"]) == 1
    assert harness.worker_transport.calls == 1
    assert harness.transport.apply_calls == 1
    assert harness.executor.worker_isolation == WorkerIsolationBinding.from_receipt(
        harness.prepared_worker.launcher.completed_isolation_receipt()
    )

    replay = dispatch_issue_sessions(
        plan,
        adapter,
        expected_plan_hash=harness.approval["context"]["expected_plan_hash"],
    )
    assert replay["sessions"][0]["fresh_session"] is False
    assert replay["sessions"][0]["host_effect_refs"] == result["sessions"][0]["host_effect_refs"]
    assert harness.worker_transport.calls == 1
    assert harness.transport.apply_calls == 1

    # A streamed thread.started event followed by a lost runner response is a
    # real create_app/PostgresStore crash path: entry and launch_unknown are
    # independently committed and read back through the authenticated owner.
    lost = issue_delivery_production_harness(lose_response_after_entry=True)
    lost_result = dispatch_issue_sessions(
        lost.approval["context"]["dispatch_plan"],
        _production_adapter(lost),
        expected_plan_hash=lost.approval["context"]["expected_plan_hash"],
    )
    assert lost_result["stopped_reason"] == "session-launch-failed"
    for kind, state in (("entry", "active"), ("terminal", "launch_unknown")):
        readback = lost.owner.issue_delivery_operation_record_read(
            repository=str(lost.approval["repository"]),
            record_id=f"issue-delivery-{kind}:{lost.approval['operation_key']}",
        )
        assert readback["state"] == state
    with pytest.raises(IssueDeliveryOperationRefused, match="durably committed"):
        _production_adapter(
            lost,
            approval=_cross_issue_approval(lost, issue_number=5553, suffix="launch-unknown"),
        ).reserve()

    attempt_only = issue_delivery_production_harness()
    attempt_only_adapter = _production_adapter(attempt_only)
    attempt_only_adapter.reserve()
    attempt_only_adapter.record_attempt()
    with pytest.raises(IssueDeliveryOperationRefused, match="durably committed"):
        _production_adapter(
            attempt_only,
            approval=_cross_issue_approval(attempt_only, issue_number=5554, suffix="attempt-only"),
        ).reserve()

    expired = issue_delivery_production_harness(approval_ttl_seconds=5.0)
    stale_prepared_attempt = _production_adapter(expired)
    stale_prepared_attempt.reserve()
    expires_at = datetime.fromisoformat(str(expired.approval["expires_at"]))
    time.sleep(max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds()) + 0.05)
    expired_reuse = _production_adapter(
        expired,
        approval=_cross_issue_approval(expired, issue_number=5555, suffix="expired"),
    ).reserve()
    assert expired_reuse["state"] == "reserved"
    with pytest.raises(IssueDeliveryOperationRefused, match="durably committed"):
        stale_prepared_attempt.record_attempt()

    # Once reservation and attempt are durable, observations deliberately do
    # not resolve mutable paths. This exercises the authenticated service
    # route and store readback, not an in-memory adapter receipt.
    observation = issue_delivery_production_harness()
    observation_adapter = _production_adapter(observation)
    observation_adapter.reserve()
    observation_adapter.record_attempt()
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("entry/terminal must not re-resolve destination paths")
        ),
    )
    entry = observation_adapter.record_entry(session_id="session-observed-pg")
    terminal = observation_adapter.record_terminal(
        session_id="session-observed-pg", worker_receipt={"final_state": "handoff"}
    )
    assert entry["state"] == "active"
    assert terminal["state"] == "terminal"
    assert (
        observation.owner.issue_delivery_operation_record_read(
            repository=str(observation.approval["repository"]),
            record_id=f"issue-delivery-terminal:{observation.approval['operation_key']}",
        )["payload"]["session_id"]
        == "session-observed-pg"
    )
    monkeypatch.undo()

    # The terminal first operation releases the physical destination.
    reused = _production_adapter(harness, approval=competing_approval).reserve()
    assert reused["state"] == "reserved"

    crashed_harness = issue_delivery_production_harness(
        effect_kind="publication", revoke_before_effect=True
    )
    crashed_result = dispatch_issue_sessions(
        crashed_harness.approval["context"]["dispatch_plan"],
        _production_adapter(crashed_harness),
        expected_plan_hash=crashed_harness.approval["context"]["expected_plan_hash"],
    )
    assert crashed_result["stopped_reason"] == "session-launch-failed"
    assert crashed_harness.worker_transport.calls == 1
    assert crashed_harness.transport.apply_calls == 1
    # The pre-entry claim was applied before worker entry. The host grant was
    # revoked only after the live entry callback, so the later publication is
    # refused while the injected operation client persists ambiguity.
    assert (
        crashed_harness.owner.issue_delivery_operation_record_read(
            repository=str(crashed_harness.approval["repository"]),
            record_id=f"issue-delivery-entry:{crashed_harness.approval['operation_key']}",
        )["state"]
        == "active"
    )
    assert (
        crashed_harness.owner.issue_delivery_operation_record_read(
            repository=str(crashed_harness.approval["repository"]),
            record_id=f"issue-delivery-terminal:{crashed_harness.approval['operation_key']}",
        )["state"]
        == "launch_unknown"
    )
    crashed_replay = dispatch_issue_sessions(
        crashed_harness.approval["context"]["dispatch_plan"],
        _production_adapter(crashed_harness),
        expected_plan_hash=crashed_harness.approval["context"]["expected_plan_hash"],
    )
    assert crashed_replay["stopped_reason"] == "session-launch-failed"
    assert crashed_harness.worker_transport.calls == 1


@pytest.mark.pg
def test_claim_readback_authority_drift_refuses_worker_spawn(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow claim cannot carry stale admission across the final spawn gate."""

    harness = issue_delivery_production_harness()
    current_readiness = harness.store.readiness()

    def invalidate_approval_after_claim_readback() -> None:
        monkeypatch.setattr(
            harness.store,
            "readiness",
            lambda: {
                **current_readiness,
                "authority_epoch": current_readiness["authority_epoch"] + 1,
            },
        )

    harness.transport.on_readback = invalidate_approval_after_claim_readback
    result = dispatch_issue_sessions(
        harness.approval["context"]["dispatch_plan"],
        _production_adapter(harness),
        expected_plan_hash=harness.approval["context"]["expected_plan_hash"],
    )

    assert result["stopped_reason"] == "session-launch-failed"
    assert harness.transport.apply_calls == 1
    assert harness.worker_transport.calls == 0
    for kind, state in (
        ("reservation", "reserved"),
        ("attempt", "attempted"),
        ("terminal", "launch_unknown"),
    ):
        assert (
            harness.owner.issue_delivery_operation_record_read(
                repository=str(harness.approval["repository"]),
                record_id=f"issue-delivery-{kind}:{harness.approval['operation_key']}",
            )["state"]
            == state
        )


@pytest.mark.pg
@pytest.mark.parametrize("observation_kind", ["entry", "terminal"])
def test_destination_takeover_race_is_serialized_before_observation_write(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    observation_kind: str,
) -> None:
    """A successor reservation and old observation use one lock order."""

    harness = issue_delivery_production_harness()
    old = _production_adapter(harness)
    old.reserve()
    old.record_attempt()
    if observation_kind == "terminal":
        old.record_entry(session_id="session-race-terminal")
    successor = _production_adapter(
        harness,
        approval=_cross_issue_approval(
            harness,
            issue_number=5561 if observation_kind == "entry" else 5562,
            suffix=f"race-{observation_kind}",
        ),
    )
    barrier = threading.Barrier(2)

    def record_observation() -> Mapping[str, Any]:
        barrier.wait(timeout=10)
        if observation_kind == "entry":
            return old.record_entry(session_id="session-race-entry")
        return old.record_terminal(
            session_id="session-race-terminal",
            worker_receipt={"final_state": "handoff"},
        )

    def reserve_successor() -> str:
        barrier.wait(timeout=10)
        try:
            successor.reserve()
        except IssueDeliveryOperationRefused:
            return "refused"
        return "reserved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        observation_future = pool.submit(record_observation)
        successor_future = pool.submit(reserve_successor)
        observation = observation_future.result(timeout=10)
        successor_state = successor_future.result(timeout=10)

    assert observation["state"] == ("active" if observation_kind == "entry" else "terminal")
    if observation_kind == "entry":
        assert successor_state == "refused"
    else:
        assert successor_state in {"refused", "reserved"}


@pytest.mark.pg
def test_terminal_unknown_effect_blocks_cross_issue_destination_reuse(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    harness = issue_delivery_production_harness(effect_kind="publication")
    harness.transport.readbacks = ["applied", "unknown"]
    result = dispatch_issue_sessions(
        harness.approval["context"]["dispatch_plan"],
        _production_adapter(harness),
        expected_plan_hash=harness.approval["context"]["expected_plan_hash"],
    )
    assert result["stopped_reason"] == "worker-handoff"
    assert harness.transport.apply_calls == 2
    with pytest.raises(IssueDeliveryOperationRefused, match="durably committed"):
        _production_adapter(
            harness,
            approval=_cross_issue_approval(harness, issue_number=5560, suffix="unknown-effect"),
        ).reserve()


@pytest.mark.pg
@pytest.mark.parametrize("effect_kind", ["claim", "publication", "merge", "closure"])
def test_delivery_effect_boundaries_recheck_authority(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    effect_kind: str,
) -> None:
    harness = issue_delivery_production_harness(effect_kind=effect_kind)
    result = dispatch_issue_sessions(
        harness.approval["context"]["dispatch_plan"],
        _production_adapter(harness),
        expected_plan_hash=harness.approval["context"]["expected_plan_hash"],
    )
    assert result["stopped_reason"] == "worker-handoff"
    assert "effect_receipts" not in result["sessions"][0]["worker_receipt"]
    expected_effects = 1 if effect_kind == "claim" else 2
    assert len(result["sessions"][0]["host_effect_refs"]) == expected_effects
    assert harness.transport.apply_calls == expected_effects
    for ref in result["sessions"][0]["host_effect_refs"]:
        status = harness.ledger.status(ref["operation_key"])
        assert status["status"] == "succeeded"
        assert status["payload"]["request_sha256"] == ref["request_sha256"]
        assert status["payload"]["effect_slot_sha256"] == ref["effect_slot_sha256"]
    replay = dispatch_issue_sessions(
        harness.approval["context"]["dispatch_plan"],
        _production_adapter(harness),
        expected_plan_hash=harness.approval["context"]["expected_plan_hash"],
    )
    assert replay["sessions"][0]["fresh_session"] is False
    assert replay["sessions"][0]["host_effect_refs"] == result["sessions"][0]["host_effect_refs"]
    assert harness.worker_transport.calls == 1
    assert harness.transport.apply_calls == expected_effects
    for ref in replay["sessions"][0]["host_effect_refs"]:
        status = harness.ledger.status(ref["operation_key"])
        assert status["status"] == "succeeded"
        assert status["payload"]["request_sha256"] == ref["request_sha256"]
        assert status["payload"]["effect_slot_sha256"] == ref["effect_slot_sha256"]

    if effect_kind == "claim":
        return
    revoked = issue_delivery_production_harness(effect_kind=effect_kind, revoke_before_effect=True)
    refused = dispatch_issue_sessions(
        revoked.approval["context"]["dispatch_plan"],
        _production_adapter(revoked),
        expected_plan_hash=revoked.approval["context"]["expected_plan_hash"],
    )
    assert refused["stopped_reason"] == "session-launch-failed"
    assert revoked.worker_transport.calls == 1
    assert revoked.transport.apply_calls == 1


@pytest.mark.pg
def test_production_composition_requires_protected_worker_and_live_facts(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    harness = issue_delivery_production_harness()
    adapter = _production_adapter(harness)
    assert isinstance(adapter.launcher, PreparedIssueDeliveryWorker)
    assert isinstance(adapter.launcher.launcher, ContentOnlyIssueDeliverySessionLauncher)
    assert getattr(adapter.launcher.launcher.runner, "supports_streaming", False) is True
    assert harness.worker_transport.supports_streaming is True
    assert harness.executor.repository_authority is harness.repository_authority
    assert harness.executor.credentials is harness.credentials
    assert callable(getattr(harness.executor, "live_binding"))


def test_unit_dispatch_reservation_and_crash_matrix() -> None:
    approval = _manifest(operation_key="operation-b-matrix")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    launcher = Launcher()
    adapter = _adapter(approval, client, launcher)
    context = approval["context"]["dispatch_plan"]["context_packs"][0]
    result = adapter.launch(context)
    assert result["operation_state"] == "terminal"
    assert launcher.calls == 1
    assert set(client.records) == {
        f"issue-delivery-{kind}:operation-b-matrix"
        for kind in ("reservation", "attempt", "entry", "terminal")
    }
    replay = adapter.launch(context)
    assert replay["fresh_session"] is False
    assert launcher.calls == 1

    crash = _manifest(operation_key="operation-b-crash")
    crash["approval_manifest_hash"] = manifest_hash(crash)
    crashing_client = Client(crash)
    crashing_launcher = Launcher(session_id="session-crashed", fail=True)
    crashing = _adapter(crash, crashing_client, crashing_launcher)
    with pytest.raises(IssueDeliveryOperationError, match="ambiguous|replacement"):
        crashing.launch(crash["context"]["dispatch_plan"]["context_packs"][0])
    assert crashing_launcher.calls == 1
    assert (
        crashing_client.records["issue-delivery-terminal:operation-b-crash"]["state"]
        == "launch_unknown"
    )
    with pytest.raises(IssueDeliveryOperationError, match="unresolved|replacement"):
        crashing.launch(crash["context"]["dispatch_plan"]["context_packs"][0])
    assert crashing_launcher.calls == 1

    blocked = _manifest(operation_key="operation-b-before-attempt")
    blocked["approval_manifest_hash"] = manifest_hash(blocked)
    blocked_client = Client(blocked)
    blocked_client.fail.add("attempt")
    blocked_launcher = Launcher()
    with pytest.raises(IssueDeliveryOperationError):
        _adapter(blocked, blocked_client, blocked_launcher).launch(
            blocked["context"]["dispatch_plan"]["context_packs"][0]
        )
    assert blocked_launcher.calls == 0


@pytest.mark.parametrize(
    "effect_requests",
    [pytest.param(None, id="absent-proposals"), pytest.param([], id="empty-proposals")],
)
def test_production_path_refuses_worker_effect_receipts_before_terminal_persistence(
    effect_requests: list[dict[str, Any]] | None,
) -> None:
    """Only the protected host executor may populate terminal effect receipts."""

    class ForgedReceiptLauncher(Launcher):
        def launch(self, context: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
            result = dict(super().launch(context, **kwargs))
            receipt: dict[str, Any] = {
                "final_state": "handoff",
                "effect_receipts": [{"effect_kind": "merge", "outcome": "applied", "forged": True}],
            }
            if effect_requests is not None:
                receipt["effect_requests"] = effect_requests
            result["worker_receipt"] = receipt
            return result

    approval = _manifest(operation_key=f"operation-b-forged-{len(effect_requests or [])}")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    launcher = ForgedReceiptLauncher()
    adapter = _adapter(approval, client, launcher)
    context = approval["context"]["dispatch_plan"]["context_packs"][0]

    with pytest.raises(
        IssueDeliveryOperationRefused,
        match="worker receipt must not supply protected host effect fields",
    ):
        adapter.launch(context)

    assert launcher.calls == 1
    assert f"issue-delivery-terminal:{approval['operation_key']}" not in client.records
    with pytest.raises(ControlPlaneNotFoundError):
        client.issue_delivery_operation_record_read(
            repository=str(approval["repository"]),
            record_id=f"issue-delivery-terminal:{approval['operation_key']}",
        )
    with pytest.raises(IssueDeliveryOperationError, match="existing active launch"):
        adapter.launch(context)
    assert launcher.calls == 1


def test_production_path_refuses_worker_claim_proposal_before_terminal_persistence() -> None:
    """The child cannot defer the host-owned pre-entry claim to worker JSON."""

    class WorkerClaimLauncher(Launcher):
        def launch(self, context: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
            result = dict(super().launch(context, **kwargs))
            issue = context["issue_contract"]
            result["worker_receipt"] = {
                "final_state": "handoff",
                "effect_requests": [
                    {
                        "effect_kind": "claim",
                        "target": {
                            "kind": "claim",
                            "issue_number": issue["number"],
                            "issue_node_id": "I_issue5550",
                            "expected_state": "open",
                            "expected_label": "agent:ready",
                        },
                    }
                ],
            }
            return result

    approval = _manifest(operation_key="operation-b-worker-claim")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    launcher = WorkerClaimLauncher()
    adapter = _adapter(approval, client, launcher)
    context = approval["context"]["dispatch_plan"]["context_packs"][0]

    with pytest.raises(IssueDeliveryOperationRefused, match="host-owned Issue claim"):
        adapter.launch(context)

    assert launcher.calls == 1
    assert f"issue-delivery-terminal:{approval['operation_key']}" not in client.records


def test_worker_post_entry_proposals_reserve_the_pre_entry_host_ref_slot() -> None:
    approval = _manifest(operation_key="operation-b-post-worker-effect-bound")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    adapter = _adapter(approval, Client(approval), Launcher())

    with pytest.raises(IssueDeliveryOperationRefused, match="bounded list"):
        adapter._execute_proposed_effects({"effect_requests": [{}] * 5})


def test_production_path_refuses_nested_worker_host_effect_fields_before_terminal_persistence() -> (
    None
):
    """Worker diagnostics cannot smuggle host-owned fields below their root."""

    class NestedForgedReceiptLauncher(Launcher):
        def launch(self, context: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
            result = dict(super().launch(context, **kwargs))
            result["worker_receipt"] = {
                "final_state": "handoff",
                "diagnostics": {"host_effect_refs": [{"operation_key": "forged"}]},
            }
            return result

    approval = _manifest(operation_key="operation-b-nested-forged-host-field")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    launcher = NestedForgedReceiptLauncher()
    adapter = _adapter(approval, client, launcher)
    context = approval["context"]["dispatch_plan"]["context_packs"][0]

    with pytest.raises(
        IssueDeliveryOperationRefused,
        match="worker receipt must not supply protected host effect fields",
    ):
        adapter.launch(context)

    assert launcher.calls == 1
    assert f"issue-delivery-terminal:{approval['operation_key']}" not in client.records


def test_unit_delivery_effect_boundaries_recheck_authority() -> None:
    approval = _manifest(operation_key="operation-b-gates")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    adapter = _adapter(approval, client, Launcher())
    target = adapter._default_target()
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
                    "pr_repository": approval["repository"],
                    "pr_issue_number": approval["issue"]["number"],
                    "pr_head_ref": approval["destination"]["branch"],
                    "pr_base_ref": approval["destination"]["base_ref"],
                }
            )
        assert adapter.authorize_effect(effect, target=effect_target)["effect"] == effect
    assert len(client.authority_calls) == 5
    with pytest.raises(IssueDeliveryOperationRefused, match="targetless"):
        adapter.authorize_effect("publication")
    with pytest.raises(IssueDeliveryOperationRefused, match="not permitted"):
        adapter.authorize_effect("deployment", target=target)
    client.revoked = True
    with pytest.raises(IssueDeliveryOperationRefused, match="unavailable"):
        adapter.authorize_effect("publication", target=target)


def test_selected_launcher_reports_stop_unsupported() -> None:
    approval = _manifest(operation_key="operation-b-stop")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    assert _adapter(approval, Client(approval), Launcher()).stop() == {
        "stop_support": "unsupported",
        "stop_status": "unsupported",
    }


def test_observation_receipts_do_not_require_live_execute_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = _manifest(operation_key="operation-b-observation")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    client = Client(approval)
    adapter = _adapter(approval, client, Launcher(session_id="session-observed"))
    adapter.reserve()
    adapter.record_attempt()
    execute_calls = len(client.authority_calls)
    client.revoked = True
    adapter.live_binding_reader = lambda _approval: (_ for _ in ()).throw(
        AssertionError("observation must not re-read mutable live source facts")
    )
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("observation must not resolve mutable paths")
        ),
    )
    entry = adapter.record_entry(session_id="session-observed")
    terminal = adapter.record_terminal(
        session_id="session-observed", worker_receipt={"state": "handoff"}
    )
    assert entry["state"] == "active"
    assert terminal["state"] == "terminal"
    # These are the authoritative operation-route readbacks, not merely the
    # adapter's proposed payload.  They prove post-launch observations remain
    # durably writable after filesystem resolution has become unavailable.
    assert client.records["issue-delivery-entry:operation-b-observation"] == entry
    assert client.records["issue-delivery-terminal:operation-b-observation"] == terminal
    assert len(client.authority_calls) == execute_calls


def test_admitted_observation_adapter_does_not_reresolve_frozen_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval = _manifest(operation_key="operation-b-frozen-observation")
    checkout = tmp_path / "checkout"
    worktree = tmp_path / "worktree"
    checkout.mkdir()
    worktree.mkdir()
    checkout_link = tmp_path / "checkout-link"
    worktree_link = tmp_path / "worktree-link"
    checkout_link.symlink_to(checkout, target_is_directory=True)
    worktree_link.symlink_to(worktree, target_is_directory=True)
    destination = approval["destination"]
    destination["checkout"] = str(checkout_link)
    destination["worktree"] = str(worktree_link)
    destination["resolved_checkout"] = str(checkout.resolve())
    destination["resolved_worktree"] = str(worktree.resolve())
    approval["context"]["dispatch_plan"]["context_packs"][0]["branch_worktree_plan"]["worktree"] = (
        str(worktree_link)
    )
    approval["approval_manifest_hash"] = manifest_hash(approval)

    def fail_resolve(_self: Path, *args: Any, **kwargs: Any) -> Path:
        del args, kwargs
        raise AssertionError("admitted observation must not resolve mutable paths")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    adapter = IssueDeliveryOperationAdapter(
        approval,
        client=Client(approval),
        launcher=Launcher(),
        repo_root=worktree_link,
        live_binding_reader=_binding,
    )
    assert adapter.repo_root == worktree_link


def test_destination_resource_lock_is_physical_across_issue_and_approval_identity() -> None:
    first = _manifest(operation_key="operation-b-resource-1")
    second = deepcopy(first)
    second["approval_id"] = "approval-resource-2"
    second["operation_key"] = "operation-b-resource-2"
    second["issue"]["number"] = 5551
    second["issue"]["node_id"] = "I_kwDOQEip6s8AAAACdXiyQQ"
    second["issue"]["url"] = "https://github.com/RasmusTho/agentic-pkm-mvp/issues/5551"
    second["destination"]["base_sha"] = "b" * 40
    second["destination"]["base_ref"] = "release"
    second["source"]["revision"] = "b" * 40
    assert destination_resource_key(
        first["repository"], first["issue"]["number"], first["destination"]
    ) == destination_resource_key(
        second["repository"], second["issue"]["number"], second["destination"]
    )


def test_unit_production_composition_refuses_unprepared_launcher() -> None:
    approval = _manifest(operation_key="operation-b-composition")
    approval["approval_manifest_hash"] = manifest_hash(approval)
    with pytest.raises(IssueDeliveryOperationRefused, match="prepared content-only launcher"):
        IssueDeliveryOperationAdapter(
            approval,
            client=Client(approval),
            launcher=Launcher(),
            repo_root=None,
            require_protected_composition=True,
        )


def test_protected_effect_boundary_refuses_callable_substitute_executor() -> None:
    class SubstituteExecutor:
        def execute(self, _request: Any) -> dict[str, str]:
            return {"outcome": "applied"}

        def live_binding(self, _approval: Mapping[str, Any]) -> dict[str, Any]:
            return {}

    with pytest.raises(IssueDeliveryOperationRefused, match="exact protected host executor"):
        _require_protected_host_executor(SubstituteExecutor())


def test_protected_runner_streams_entry_before_process_exit() -> None:
    observed: list[str] = []
    result = _run_streaming_process(
        [
            sys.executable,
            "-c",
            "import json,time; print(json.dumps({'type':'thread.started','thread_id':'streamed'}), flush=True); time.sleep(.2)",
        ],
        cwd=Path.cwd(),
        input="",
        env={"PATH": "/usr/bin:/bin"},
        timeout=5,
        on_stdout_line=observed.append,
    )
    assert result.returncode == 0
    assert observed and '"thread_id": "streamed"' in observed[0]
