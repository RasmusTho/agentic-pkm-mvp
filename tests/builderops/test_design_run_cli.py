from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import app.builderops.cli as cli_module
from app.builderops.cli import builderops
from app.builderops.ckm.overview_html import (
    CockpitRenderContext,
    render_overview_html,
)
from app.builderops.ckm.store import CkmStore
from app.builderops.design_agent_adapters import ResolvedDesignAgentAdapter
from app.builderops.design_run_contract import (
    CuratedDesignBrief,
    DesignAgentAvailabilityDescriptor,
    DesignAgentDescriptor,
)
from app.builderops.design_run_governance import DesignRunGovernance
from app.builderops.store import SqliteBuilderOpsStore
from llm_contract import AdapterResult

SHA_A = "a" * 64
SHA_B = "b" * 64
T0 = "2026-07-30T10:00:00Z"
T1 = "2026-07-30T10:01:00Z"
T2 = "2026-07-30T10:02:00Z"
T3 = "2026-07-30T10:03:00Z"
T4 = "2026-07-30T10:04:00Z"
T5 = "2026-07-30T10:05:00Z"
T6 = "2026-07-30T10:06:00Z"


@dataclass
class RecordingAdapter:
    calls: list[dict[str, Any]] = field(default_factory=list)
    fail_with_sensitive_detail: bool = False
    adapter_id: str = "test-codex"
    provider: str = "test-provider"
    model: str = "test-model"

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        if self.fail_with_sensitive_detail:
            raise RuntimeError("Bearer top-secret from /Users/operator/private")
        content = "bounded design output"
        handoff = {
            **dict(request["handoff_binding"]),
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        }
        return AdapterResult(
            response_text=json.dumps(
                {
                    "schema_version": request[
                        "handoff_output_schema_version"
                    ],
                    "artifact_content": content,
                    "handoff": handoff,
                },
                sort_keys=True,
            ),
            provider_request_id="provider-request-not-persisted",
        )


@dataclass
class RecordingRegistry:
    adapter: RecordingAdapter
    selections: list[tuple[str, str]] = field(default_factory=list)

    def contract_descriptor(
        self,
        design_agent_id: str,
    ) -> DesignAgentDescriptor:
        if design_agent_id != "codex":
            raise ValueError("unknown design agent")
        return DesignAgentDescriptor(
            descriptor_id="codex",
            display_name="Codex",
            role_profile_id="design.codex",
            supported_deliverables=(
                "content_review",
                "interaction_specification",
                "visual_handoff",
            ),
            descriptor_revision="v1",
        )

    def descriptors(
        self,
        *,
        run_id: str,
    ) -> tuple[DesignAgentAvailabilityDescriptor, ...]:
        return (
            DesignAgentAvailabilityDescriptor(
                design_agent_id="codex",
                display_name="Codex",
                role_profile_id="design.codex",
                supported_deliverables=(
                    "content_review",
                    "interaction_specification",
                    "visual_handoff",
                ),
                available=True,
                provider_identity="test-provider",
                model_identity="test-model",
                effective_identity="test-provider/test-model",
                capabilities=("structured_output",),
                resolution_group_id=f"design-run:{run_id}",
            ),
        )

    def select(
        self,
        design_agent_id: str,
        *,
        run_id: str,
    ) -> ResolvedDesignAgentAdapter:
        self.selections.append((design_agent_id, run_id))
        return ResolvedDesignAgentAdapter(
            design_agent_id=design_agent_id,
            descriptor=self.descriptors(run_id=run_id)[0],
            model_turn_adapter=self.adapter,
        )


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    policy_path = root / "config/builderops/design_run_policy.json"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(
            {
                "allowed_deliverables": [
                    "content_review",
                    "interaction_specification",
                    "visual_handoff",
                ],
                "approval_required": True,
                "contract_kind": "policy",
                "max_attachment_refs": 8,
                "max_source_refs": 16,
                "profile_id": "design.policy.local",
                "profile_version": "v1",
                "schema_version": "builderops.design-run-contract.v1",
                "visual_yggdrasil_receipt_required": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def store(tmp_path: Path) -> SqliteBuilderOpsStore:
    selected = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    selected.initialize()
    return selected


def _service(
    store: SqliteBuilderOpsStore,
    repo_root: Path,
    *,
    fail_with_sensitive_detail: bool = False,
) -> tuple[DesignRunGovernance, RecordingRegistry, RecordingAdapter]:
    adapter = RecordingAdapter(
        fail_with_sensitive_detail=fail_with_sensitive_detail
    )
    registry = RecordingRegistry(adapter)
    return (
        DesignRunGovernance(
            store=store,
            registry=registry,
            repo_root=repo_root,
            lease_ttl_seconds=30,
        ),
        registry,
        adapter,
    )


def _brief_payload() -> dict[str, Any]:
    return {
        "schema_version": "builderops.design-run-contract.v1",
        "contract_kind": "brief",
        "brief_id": "brief.cli.one",
        "projection_id": "projection.cli.one",
        "requested_deliverable": "interaction_specification",
        "source_refs": [
            {
                "source_type": "github_issue",
                "source_id": "github:RasmusTho/agentic-pkm-mvp#4311",
                "content_hash": SHA_A,
            }
        ],
        "attachment_refs": [
            {
                "attachment_id": "attachment.cli.one",
                "media_type": "text/markdown",
                "content_hash": SHA_B,
            }
        ],
        "constraints": ["Use explicit evidence only."],
        "yggdrasil_gate_receipt": None,
        "non_visual_exemption": True,
    }


def _request_payload() -> dict[str, Any]:
    return {
        "schema_version": "builderops.design-run-cli-request.v1",
        "run_id": "run.cli.one",
        "request_id": "request.cli.one",
        "adapter_id": "codex",
        "requested_at": T0,
        "evaluated_at": T1,
        "brief": _brief_payload(),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _bind_service(
    monkeypatch: pytest.MonkeyPatch,
    service: DesignRunGovernance,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "_design_run_governance",
        lambda _ctx, *, repo_root, store_mode="write": service,
    )


def _invoke(
    store: SqliteBuilderOpsStore,
    *args: str,
) -> Any:
    return CliRunner().invoke(
        builderops,
        ["--db-path", str(store.db_path), "design-run", *args],
        catch_exceptions=False,
    )


def _admit_and_approve(
    *,
    store: SqliteBuilderOpsStore,
    repo_root: Path,
    request_file: Path,
) -> dict[str, str]:
    admitted = _invoke(
        store,
        "admit",
        "--request-file",
        str(request_file),
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert admitted.exit_code == 0, admitted.output
    approved = _invoke(
        store,
        "approve",
        "run.cli.one",
        "--approval-id",
        "approval.cli.one",
        "--approved-at",
        T2,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert approved.exit_code == 0, approved.output
    admitted_payload = json.loads(admitted.output)
    approved_payload = json.loads(approved.output)
    return {
        "request_id": admitted_payload["request"]["request_id"],
        "request_hash": admitted_payload["request_hash"],
        "admission_id": admitted_payload["admission"]["admission_id"],
        "admission_hash": admitted_payload["admission_hash"],
        "approval_id": approved_payload["approval_id"],
        "approval_hash": approved_payload["content_hash"],
    }


def _exact_start_options(identities: Mapping[str, str]) -> list[str]:
    options = [
        "--request-id",
        identities["request_id"],
        "--request-hash",
        identities["request_hash"],
        "--admission-id",
        identities["admission_id"],
        "--admission-hash",
        identities["admission_hash"],
    ]
    if "approval_id" in identities or "approval_hash" in identities:
        options.extend(
            [
                "--approval-id",
                identities["approval_id"],
                "--approval-hash",
                identities["approval_hash"],
            ]
        )
    return options


def test_cli_builds_only_explicit_bounded_briefs(
    tmp_path: Path,
    store: SqliteBuilderOpsStore,
) -> None:
    request_file = _write_json(tmp_path / "request.json", _request_payload())
    first = _invoke(
        store,
        "brief-build",
        "--request-file",
        str(request_file),
        "--json",
    )
    second = _invoke(
        store,
        "brief-build",
        "--request-file",
        str(request_file),
        "--json",
    )
    assert first.exit_code == second.exit_code == 0
    assert first.output == second.output
    built = json.loads(first.output)
    assert built["brief"]["source_refs"][0]["content_hash"] == SHA_A
    assert built["brief"]["attachment_refs"][0]["content_hash"] == SHA_B

    brief_file = _write_json(tmp_path / "brief.json", built["brief"])
    inspected = _invoke(
        store,
        "brief-inspect",
        "--brief-file",
        str(brief_file),
        "--json",
    )
    assert inspected.exit_code == 0
    assert json.loads(inspected.output)["brief_hash"] == built["brief_hash"]

    unbounded = _request_payload()
    unbounded["brief"]["constraints"] = ["Use the whole repo."]
    rejected = _invoke(
        store,
        "brief-build",
        "--request-file",
        str(_write_json(tmp_path / "unbounded.json", unbounded)),
        "--json",
    )
    assert rejected.exit_code != 0
    assert "canonical design-run CLI request" in rejected.output

    missing_digest = _request_payload()
    del missing_digest["brief"]["attachment_refs"][0]["content_hash"]
    rejected_digest = _invoke(
        store,
        "brief-build",
        "--request-file",
        str(_write_json(tmp_path / "missing-digest.json", missing_digest)),
        "--json",
    )
    assert rejected_digest.exit_code != 0

    padded_cases = (
        ("request-id", lambda payload: payload.__setitem__(
            "request_id", " request.cli.one "
        )),
        ("brief-id", lambda payload: payload["brief"].__setitem__(
            "brief_id", " brief.cli.one "
        )),
        ("source-id", lambda payload: payload["brief"]["source_refs"][0].__setitem__(
            "source_id", " github:RasmusTho/agentic-pkm-mvp#4311 "
        )),
        ("constraint", lambda payload: payload["brief"].__setitem__(
            "constraints", [" Use explicit evidence only. "]
        )),
    )
    for name, mutate in padded_cases:
        padded = _request_payload()
        mutate(padded)
        result = _invoke(
            store,
            "brief-build",
            "--request-file",
            str(_write_json(tmp_path / f"padded-{name}.json", padded)),
            "--json",
        )
        assert result.exit_code != 0


def test_cli_preview_precedes_exact_governed_start(
    tmp_path: Path,
    repo_root: Path,
    store: SqliteBuilderOpsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry, adapter = _service(store, repo_root)
    _bind_service(monkeypatch, service)
    request_file = _write_json(tmp_path / "request.json", _request_payload())

    preview = _invoke(
        store,
        "preview",
        "--request-file",
        str(request_file),
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["persisted"] is False
    assert store.list_records("BuilderOpsReceipt") == []
    assert registry.selections == [] and adapter.calls == []

    before_admission = _invoke(
        store,
        "start",
        "run.cli.one",
        "--request-id",
        "request.cli.one",
        "--request-hash",
        "0" * 64,
        "--admission-id",
        "run.cli.one.admission",
        "--admission-hash",
        "0" * 64,
        "--approval-id",
        "approval.cli.one",
        "--approval-hash",
        "0" * 64,
        "--started-at",
        T3,
        "--completed-at",
        T4,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert before_admission.exit_code != 0
    assert registry.selections == [] and adapter.calls == []

    identities = _admit_and_approve(
        store=store,
        repo_root=repo_root,
        request_file=request_file,
    )
    mismatched = _invoke(
        store,
        "start",
        "run.cli.one",
        *_exact_start_options(
            {**identities, "admission_id": "foreign.admission"}
        ),
        "--started-at",
        T3,
        "--completed-at",
        T4,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert mismatched.exit_code != 0
    assert registry.selections == [] and adapter.calls == []

    started = _invoke(
        store,
        "start",
        "run.cli.one",
        *_exact_start_options(identities),
        "--started-at",
        T3,
        "--completed-at",
        T4,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert started.exit_code == 0, started.output
    assert json.loads(started.output)["result"]["final_status"] == "succeeded"
    assert registry.selections == [("codex", "run.cli.one")]
    assert len(adapter.calls) == 1
    receipt_count = len(store.list_records("BuilderOpsReceipt"))
    late_approval = _invoke(
        store,
        "approve",
        "run.cli.one",
        "--approval-id",
        "approval.late.one",
        "--approved-at",
        T5,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert late_approval.exit_code != 0
    assert len(store.list_records("BuilderOpsReceipt")) == receipt_count
    assert service.projection("run.cli.one").state == "succeeded"


def test_cli_starts_approval_free_allow_and_rejects_one_sided_pair(
    tmp_path: Path,
    repo_root: Path,
    store: SqliteBuilderOpsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = repo_root / "config/builderops/design_run_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["approval_required"] = False
    policy_path.write_text(json.dumps(policy, sort_keys=True), encoding="utf-8")
    service, registry, adapter = _service(store, repo_root)
    _bind_service(monkeypatch, service)
    request_file = _write_json(tmp_path / "request.json", _request_payload())

    admitted = _invoke(
        store,
        "admit",
        "--request-file",
        str(request_file),
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert admitted.exit_code == 0, admitted.output
    payload = json.loads(admitted.output)
    assert payload["admission"]["outcome"] == "allow"
    identities = {
        "request_id": payload["request"]["request_id"],
        "request_hash": payload["request_hash"],
        "admission_id": payload["admission"]["admission_id"],
        "admission_hash": payload["admission_hash"],
    }

    one_sided = _invoke(
        store,
        "start",
        "run.cli.one",
        *_exact_start_options(identities),
        "--approval-id",
        "approval.must.not.be.one-sided",
        "--started-at",
        T2,
        "--completed-at",
        T3,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert one_sided.exit_code != 0
    assert registry.selections == [] and adapter.calls == []

    started = _invoke(
        store,
        "start",
        "run.cli.one",
        *_exact_start_options(identities),
        "--started-at",
        T2,
        "--completed-at",
        T3,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert started.exit_code == 0, started.output
    assert json.loads(started.output)["result"]["final_status"] == "succeeded"
    assert registry.selections == [("codex", "run.cli.one")]
    assert len(adapter.calls) == 1


def test_execute_exact_requires_runtime_request_and_admission_evidence(
    repo_root: Path,
    store: SqliteBuilderOpsStore,
) -> None:
    service, registry, adapter = _service(store, repo_root)
    brief = CuratedDesignBrief.model_validate_json(
        json.dumps(_brief_payload(), sort_keys=True)
    )
    service.admit(
        run_id="run.cli.one",
        request_id="request.cli.one",
        brief=brief,
        adapter_id="codex",
        requested_at=T0,
        evaluated_at=T1,
    )
    service.approve(
        run_id="run.cli.one",
        approval_id="approval.cli.real",
        approved_at=T2,
    )

    with pytest.raises(
        ValueError,
        match="request identity mismatch",
    ):
        service.execute_exact(
            run_id="run.cli.one",
            started_at=T3,
            completed_at=T4,
            expected_request_id=None,  # type: ignore[arg-type]
            expected_request_hash=None,  # type: ignore[arg-type]
            expected_admission_id=None,  # type: ignore[arg-type]
            expected_admission_hash=None,  # type: ignore[arg-type]
            expected_approval_id="approval.foreign",
            expected_approval_hash="0" * 64,
        )
    assert registry.selections == [] and adapter.calls == []


def test_cli_approval_and_revocation_are_exact_and_actor_bound(
    tmp_path: Path,
    repo_root: Path,
    store: SqliteBuilderOpsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, registry, adapter = _service(store, repo_root)
    _bind_service(monkeypatch, service)
    monkeypatch.setattr(
        "app.builderops.design_run_governance._authenticated_local_principal",
        lambda: "local-operator",
    )
    request_file = _write_json(tmp_path / "request.json", _request_payload())
    admitted = _invoke(
        store,
        "admit",
        "--request-file",
        str(request_file),
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert admitted.exit_code == 0

    help_result = _invoke(store, "approve", "--help")
    assert "--actor" not in help_result.output
    approved = _invoke(
        store,
        "approve",
        "run.cli.one",
        "--approval-id",
        "approval.cli.one",
        "--approved-at",
        T2,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert approved.exit_code == 0, approved.output
    approved_payload = json.loads(approved.output)
    records = store.list_records("BuilderOpsReceipt")
    assert records[-1]["actor"] == {
        "actor_type": "human",
        "id": "local-operator",
    }

    revoked = _invoke(
        store,
        "revoke",
        "run.cli.one",
        "--revocation-id",
        "revocation.cli.one",
        "--revoked-at",
        T3,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert revoked.exit_code == 0
    reapproved = _invoke(
        store,
        "approve",
        "run.cli.one",
        "--approval-id",
        "approval.cli.one",
        "--approved-at",
        T4,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert reapproved.exit_code == 0, reapproved.output
    reapproved_payload = json.loads(reapproved.output)
    admitted_payload = json.loads(admitted.output)
    stale_identities = {
        "request_id": admitted_payload["request"]["request_id"],
        "request_hash": admitted_payload["request_hash"],
        "admission_id": admitted_payload["admission"]["admission_id"],
        "admission_hash": admitted_payload["admission_hash"],
        "approval_id": approved_payload["approval_id"],
        "approval_hash": approved_payload["content_hash"],
    }
    assert (
        reapproved_payload["content_hash"]
        != stale_identities["approval_hash"]
    )
    refused = _invoke(
        store,
        "start",
        "run.cli.one",
        *_exact_start_options(stale_identities),
        "--started-at",
        T5,
        "--completed-at",
        T6,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert refused.exit_code != 0
    assert registry.selections == [] and adapter.calls == []


def test_cli_status_and_result_are_receipt_derived_and_secret_safe(
    tmp_path: Path,
    repo_root: Path,
    store: SqliteBuilderOpsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, adapter = _service(
        store,
        repo_root,
        fail_with_sensitive_detail=True,
    )
    _bind_service(monkeypatch, service)
    request_file = _write_json(tmp_path / "request.json", _request_payload())
    identities = _admit_and_approve(
        store=store,
        repo_root=repo_root,
        request_file=request_file,
    )
    started = _invoke(
        store,
        "start",
        "run.cli.one",
        *_exact_start_options(identities),
        "--started-at",
        T3,
        "--completed-at",
        T4,
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert started.exit_code == 0, started.output
    assert len(adapter.calls) == 1

    for command in ("status", "result"):
        observed = _invoke(
            store,
            command,
            "run.cli.one",
            "--repo-root",
            str(repo_root),
            "--json",
        )
        assert observed.exit_code == 0, observed.output
        assert json.loads(observed.output)["state"] == "failed"
        lowered = observed.output.lower()
        assert "top-secret" not in lowered
        assert "bearer" not in lowered
        assert "/users/" not in lowered
        assert "provider-request-not-persisted" not in lowered

    latest = next(
        record
        for record in store.list_records("BuilderOpsReceipt")
        if record.get("action") == "run_failed"
        and record.get("event_type") == "design_run_event"
    )
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT payload FROM builderops_records WHERE id = ?",
            (latest["id"],),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        event = json.loads(payload["receipt_body"])
        event["artifact_hash"] = "0" * 64
        payload["receipt_body"] = json.dumps(event, sort_keys=True)
        conn.execute(
            "UPDATE builderops_records SET payload = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), latest["id"]),
        )
    tampered = _invoke(
        store,
        "status",
        "run.cli.one",
        "--repo-root",
        str(repo_root),
        "--json",
    )
    assert tampered.exit_code != 0, tampered.output
    assert '"state": "failed"' not in tampered.output


def test_read_only_commands_do_not_create_storage_or_leak_host_paths(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    request_file = _write_json(tmp_path / "request.json", _request_payload())
    absent_db = tmp_path / "absent" / "builderops.sqlite3"
    runner = CliRunner()

    preview = runner.invoke(
        builderops,
        [
            "--db-path",
            str(absent_db),
            "design-run",
            "preview",
            "--request-file",
            str(request_file),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["persisted"] is False
    assert not absent_db.exists()
    assert not absent_db.parent.exists()

    agents = runner.invoke(
        builderops,
        [
            "--db-path",
            str(absent_db),
            "design-run",
            "agents",
            "--run-id",
            "run.cli.one",
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert agents.exit_code == 0, agents.output
    assert not absent_db.exists()

    marker = "private-secret-marker"
    collision = tmp_path / marker
    collision.write_text("not a directory", encoding="utf-8")
    colliding_db = collision / "builderops.sqlite3"
    colliding_preview = runner.invoke(
        builderops,
        [
            "--db-path",
            str(colliding_db),
            "design-run",
            "preview",
            "--request-file",
            str(request_file),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert colliding_preview.exit_code == 0, colliding_preview.output
    assert marker not in colliding_preview.output
    status = runner.invoke(
        builderops,
        [
            "--db-path",
            str(colliding_db),
            "design-run",
            "status",
            "run.cli.one",
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert status.exit_code != 0
    assert marker not in status.output
    assert "design-run evidence store does not exist" in status.output


def test_status_and_result_use_sqlite_mode_ro_and_never_recreate(
    repo_root: Path,
    store: SqliteBuilderOpsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _registry, _adapter = _service(store, repo_root)
    brief = CuratedDesignBrief.model_validate_json(
        json.dumps(_brief_payload(), sort_keys=True)
    )
    service.admit(
        run_id="run.cli.one",
        request_id="request.cli.one",
        brief=brief,
        adapter_id="codex",
        requested_at=T0,
        evaluated_at=T1,
    )
    durable_bytes = store.db_path.read_bytes()

    real_store = cli_module.SqliteBuilderOpsStore
    read_only_flags: list[bool] = []

    def recording_store(
        path: Path,
        *,
        read_only: bool = False,
    ) -> SqliteBuilderOpsStore:
        read_only_flags.append(read_only)
        return real_store(path, read_only=read_only)

    monkeypatch.setattr(
        cli_module,
        "SqliteBuilderOpsStore",
        recording_store,
    )
    runner = CliRunner()
    status = runner.invoke(
        builderops,
        [
            "--db-path",
            str(store.db_path),
            "design-run",
            "status",
            "run.cli.one",
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert status.exit_code == 0, status.output
    assert read_only_flags == [True]

    def deleting_store(
        path: Path,
        *,
        read_only: bool = False,
    ) -> SqliteBuilderOpsStore:
        assert read_only is True
        Path(path).unlink()
        return real_store(path, read_only=read_only)

    monkeypatch.setattr(
        cli_module,
        "SqliteBuilderOpsStore",
        deleting_store,
    )
    result = runner.invoke(
        builderops,
        [
            "--db-path",
            str(store.db_path),
            "design-run",
            "result",
            "run.cli.one",
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "design-run storage is unavailable" in result.output
    assert not store.db_path.exists()

    store.db_path.write_bytes(durable_bytes)

    def deleting_write_store(
        path: Path,
        *,
        read_only: bool = False,
        create_if_missing: bool = True,
    ) -> SqliteBuilderOpsStore:
        assert read_only is False
        assert create_if_missing is False
        Path(path).unlink()
        return real_store(
            path,
            read_only=read_only,
            create_if_missing=create_if_missing,
        )

    monkeypatch.setattr(
        cli_module,
        "SqliteBuilderOpsStore",
        deleting_write_store,
    )
    approve = runner.invoke(
        builderops,
        [
            "--db-path",
            str(store.db_path),
            "design-run",
            "approve",
            "run.cli.one",
            "--approval-id",
            "approval.cli.race",
            "--approved-at",
            T2,
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert approve.exit_code != 0
    assert "design-run storage is unavailable" in approve.output
    assert not store.db_path.exists()


def test_control_surface_stays_outside_static_cockpit(tmp_path: Path) -> None:
    store = CkmStore(tmp_path / "ckm.sqlite3")
    store.ensure_schema()
    rendered = render_overview_html(
        store,
        generated_at=T0,
        cockpit=CockpitRenderContext(batch=store.load_projection_batch()),
    )
    lowered = rendered.lower()
    assert "<form" not in lowered
    assert "<button" not in lowered
    assert "<textarea" not in lowered
    assert "fetch(" not in lowered
    assert "design-run start" not in lowered
    assert "design-run approve" not in lowered
    assert "design-run admit" not in lowered
