from __future__ import annotations

import inspect
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from app.builderops.cli import builderops
from app.builderops.design_agent_adapters import ResolvedDesignAgentAdapter
from app.builderops.design_run_contract import (
    CuratedDesignBrief,
    DESIGN_RUN_CONTRACT_VERSION,
    DesignAgentAvailabilityDescriptor,
    DesignAgentDescriptor,
    DesignRunPolicyProfile,
    DesignSourceRef,
    DigestBoundAttachmentRef,
    YggdrasilGateReceipt,
    canonical_json,
)
from app.builderops.design_run_governance import (
    DESIGN_RUN_EVENT_VERSION,
    DesignRunApprovalRequiredError,
    DesignRunEvidenceError,
    DesignRunGovernance,
    DesignRunGovernanceError,
    DesignRunIncompleteError,
    DesignRunPersistenceError,
    DesignRunUnavailableError,
)
from app.builderops.models import BuilderOpsValidationError
from app.builderops.store import SqliteBuilderOpsStore
from llm_contract import AdapterResult

SHA_A = "a" * 64
SHA_B = "b" * 64
TOKEN_BYTES = b"repo design tokens\n"
SHA_C = hashlib.sha256(TOKEN_BYTES).hexdigest()
T0 = "2026-07-30T10:00:00Z"
T1 = "2026-07-30T10:01:00Z"
T2 = "2026-07-30T10:02:00Z"
T3 = "2026-07-30T10:03:00Z"
T4 = "2026-07-30T10:04:00Z"


@dataclass
class RecordingAdapter:
    calls: list[dict[str, Any]] = field(default_factory=list)
    artifact_content: str = "bounded design output"
    response_text: str | None = None
    content_hash_override: str | None = None
    handoff_overrides: dict[str, Any] = field(default_factory=dict)
    adapter_id: str = "test-codex"
    provider: str = "test-provider"
    model: str = "test-model"

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        response_text = self.response_text
        if response_text is None:
            response_text = json.dumps(
                {
                    "schema_version": request[
                        "handoff_output_schema_version"
                    ],
                    "artifact_content": self.artifact_content,
                    "handoff": {
                        **dict(request["handoff_binding"]),
                        **self.handoff_overrides,
                        "content_hash": (
                            self.content_hash_override
                            or hashlib.sha256(
                                self.artifact_content.encode("utf-8")
                            ).hexdigest()
                        ),
                    },
                },
                sort_keys=True,
            )
        return AdapterResult(
            response_text=response_text,
            provider_request_id="provider-request-not-persisted",
        )


@dataclass
class RecordingRegistry:
    adapter: RecordingAdapter
    calls: list[tuple[str, str]] = field(default_factory=list)
    resolution_group_id: str | None = None

    def select(
        self,
        design_agent_id: str,
        *,
        run_id: str,
    ) -> ResolvedDesignAgentAdapter:
        self.calls.append((design_agent_id, run_id))
        return ResolvedDesignAgentAdapter(
            design_agent_id=design_agent_id,
            descriptor=DesignAgentAvailabilityDescriptor(
                design_agent_id=design_agent_id,
                display_name="Test Codex",
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
                resolution_group_id=(
                    self.resolution_group_id
                    or f"design-run:{run_id}"
                ),
            ),
            model_turn_adapter=self.adapter,
        )


class StoreProxy:
    def __init__(self, wrapped: SqliteBuilderOpsStore) -> None:
        self.wrapped = wrapped

    def append_receipt(self, **fields: Any) -> dict[str, Any]:
        return self.wrapped.append_receipt(**fields)

    def list_records(
        self,
        object_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.wrapped.list_records(object_type)

    def acquire_lease(
        self,
        resource_id: str,
        *,
        actor: Mapping[str, Any] | str,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]:
        return self.wrapped.acquire_lease(
            resource_id,
            actor=actor,
            ttl_seconds=ttl_seconds,
        )

    def release_lease(
        self,
        lease_id: str,
        *,
        actor: Mapping[str, Any] | str,
    ) -> dict[str, Any]:
        return self.wrapped.release_lease(lease_id, actor=actor)


class FailingStore(StoreProxy):
    def __init__(
        self,
        wrapped: SqliteBuilderOpsStore,
        *,
        fail_actions: set[str],
    ) -> None:
        super().__init__(wrapped)
        self.fail_actions = fail_actions

    def append_receipt(self, **fields: Any) -> dict[str, Any]:
        if fields.get("action") in self.fail_actions:
            raise BuilderOpsValidationError("injected persistence failure")
        return super().append_receipt(**fields)


class TamperingStore(StoreProxy):
    def __init__(
        self,
        wrapped: SqliteBuilderOpsStore,
        transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    ) -> None:
        super().__init__(wrapped)
        self.transform = transform

    def list_records(
        self,
        object_type: str | None = None,
    ) -> list[dict[str, Any]]:
        records = super().list_records(object_type)
        if object_type == "BuilderOpsReceipt":
            return self.transform(records)
        return records


class SecondAcquireCallbackStore(StoreProxy):
    def __init__(
        self,
        wrapped: SqliteBuilderOpsStore,
        callback: Callable[[], None],
    ) -> None:
        super().__init__(wrapped)
        self.callback = callback
        self.acquire_count = 0
        self.first_lease: dict[str, Any] | None = None
        self.first_actor: Mapping[str, Any] | str | None = None

    def acquire_lease(
        self,
        resource_id: str,
        *,
        actor: Mapping[str, Any] | str,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]:
        self.acquire_count += 1
        if self.acquire_count == 2:
            assert self.first_lease is not None
            assert self.first_actor is not None
            self.wrapped.release_lease(
                self.first_lease["lease_id"],
                actor=self.first_actor,
            )
            self.callback()
        lease = super().acquire_lease(
            resource_id,
            actor=actor,
            ttl_seconds=ttl_seconds,
        )
        if self.acquire_count == 1:
            self.first_lease = lease
            self.first_actor = actor
        return lease


class RootBarrierStore(StoreProxy):
    def __init__(
        self,
        wrapped: SqliteBuilderOpsStore,
        barrier: threading.Barrier,
    ) -> None:
        super().__init__(wrapped)
        self.barrier = barrier

    def append_receipt(self, **fields: Any) -> dict[str, Any]:
        if fields.get("action") == "request_persisted":
            self.barrier.wait(timeout=5)
        return super().append_receipt(**fields)


class TerminalAppendRecoveryStore(StoreProxy):
    def __init__(
        self,
        wrapped: SqliteBuilderOpsStore,
        callback: Callable[[], None],
    ) -> None:
        super().__init__(wrapped)
        self.callback = callback
        self.latest_lease: dict[str, Any] | None = None
        self.latest_actor: Mapping[str, Any] | str | None = None
        self.fired = False

    def acquire_lease(
        self,
        resource_id: str,
        *,
        actor: Mapping[str, Any] | str,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]:
        lease = super().acquire_lease(
            resource_id,
            actor=actor,
            ttl_seconds=ttl_seconds,
        )
        self.latest_lease = lease
        self.latest_actor = actor
        return lease

    def append_receipt(self, **fields: Any) -> dict[str, Any]:
        if fields.get("action") == "run_succeeded" and not self.fired:
            self.fired = True
            assert self.latest_lease is not None
            assert self.latest_actor is not None
            self.wrapped.release_lease(
                self.latest_lease["lease_id"],
                actor=self.latest_actor,
            )
            self.callback()
        return super().append_receipt(**fields)


class StartAppendCompetitorStore(StoreProxy):
    def __init__(
        self,
        wrapped: SqliteBuilderOpsStore,
        callback: Callable[[], None],
    ) -> None:
        super().__init__(wrapped)
        self.callback = callback
        self.latest_lease: dict[str, Any] | None = None
        self.latest_actor: Mapping[str, Any] | str | None = None
        self.fired = False

    def acquire_lease(
        self,
        resource_id: str,
        *,
        actor: Mapping[str, Any] | str,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]:
        lease = super().acquire_lease(
            resource_id,
            actor=actor,
            ttl_seconds=ttl_seconds,
        )
        self.latest_lease = lease
        self.latest_actor = actor
        return lease

    def append_receipt(self, **fields: Any) -> dict[str, Any]:
        if fields.get("action") == "start_accepted" and not self.fired:
            self.fired = True
            assert self.latest_lease is not None
            assert self.latest_actor is not None
            self.wrapped.release_lease(
                self.latest_lease["lease_id"],
                actor=self.latest_actor,
            )
            self.callback()
        return super().append_receipt(**fields)


@pytest.fixture
def store(tmp_path: Path) -> SqliteBuilderOpsStore:
    value = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    value.initialize()
    return value


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    policy_path = root / "config/builderops/design_run_policy.json"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(
        json.dumps(_policy().model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    token_path = root / "companion-ui/companion-app/colors_and_type.css"
    token_path.parent.mkdir(parents=True)
    token_path.write_bytes(TOKEN_BYTES)
    return root


def _policy(
    *,
    approval_required: bool = True,
    allowed_deliverables: tuple[
        str, ...
    ] = (
        "content_review",
        "interaction_specification",
        "visual_handoff",
    ),
) -> DesignRunPolicyProfile:
    return DesignRunPolicyProfile(
        profile_id="design.policy.local",
        profile_version="v1",
        allowed_deliverables=allowed_deliverables,
        max_source_refs=16,
        max_attachment_refs=8,
        approval_required=approval_required,
        visual_yggdrasil_receipt_required=True,
    )


def _source() -> DesignSourceRef:
    return DesignSourceRef(
        source_type="ckm_observation",
        source_id="ckm:observation:one",
        content_hash=SHA_A,
    )


def _attachment() -> DigestBoundAttachmentRef:
    return DigestBoundAttachmentRef(
        attachment_id="preview.one",
        media_type="image/png",
        content_hash=SHA_B,
    )


def _brief(
    *,
    visual: bool = False,
    verified_at: str = "2026-07-30T09:00:00Z",
    expires_at: str = "2026-07-30T11:00:00Z",
    token_hash: str = SHA_C,
    repo_token_source: str = (
        "companion-ui/companion-app/colors_and_type.css"
    ),
) -> CuratedDesignBrief:
    receipt = (
        YggdrasilGateReceipt(
            receipt_id="receipt.yggdrasil.one",
            system_name="Yggdrasil",
            system_id="yggdrasil.design.system",
            selection_mechanism="explicit_attachment",
            repo_token_source=repo_token_source,
            live_token_hash=token_hash,
            repo_token_hash=token_hash,
            parity_passed=True,
            verified_at=verified_at,
            expires_at=expires_at,
            preview_refs=(_attachment(),),
        )
        if visual
        else None
    )
    return CuratedDesignBrief(
        brief_id="brief.design.one",
        projection_id="ckm.projection.one",
        requested_deliverable=(
            "visual_handoff" if visual else "interaction_specification"
        ),
        source_refs=(_source(),),
        attachment_refs=(_attachment(),),
        constraints=("Use explicit evidence only.",),
        yggdrasil_gate_receipt=receipt,
        non_visual_exemption=None if visual else True,
    )


def _descriptor() -> DesignAgentDescriptor:
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


def _service(
    store: Any,
    repo_root: Path,
    *,
    adapter: RecordingAdapter | None = None,
) -> tuple[DesignRunGovernance, RecordingRegistry, RecordingAdapter]:
    selected_adapter = adapter or RecordingAdapter()
    registry = RecordingRegistry(selected_adapter)
    return (
        DesignRunGovernance(
            store=store,
            registry=registry,
            repo_root=repo_root,
            lease_ttl_seconds=30,
        ),
        registry,
        selected_adapter,
    )


def _submit(
    service: DesignRunGovernance,
    *,
    run_id: str = "run.design.one",
    brief: CuratedDesignBrief | None = None,
    evaluated_at: str = T1,
) -> None:
    selected_brief = brief or _brief()
    adapter = _descriptor()
    request = service.build_request(
        request_id=f"{run_id}.request",
        brief=selected_brief,
        adapter=adapter,
        requested_at=T0,
    )
    service.submit(
        run_id=run_id,
        request=request,
        brief=selected_brief,
        adapter=adapter,
        evaluated_at=evaluated_at,
    )


def _approve_and_execute(
    service: DesignRunGovernance,
    *,
    run_id: str = "run.design.one",
) -> None:
    service.approve(
        run_id=run_id,
        approval_id=f"{run_id}.approval",
        approved_at=T2,
    )
    service.execute(
        run_id=run_id,
        started_at=T3,
        completed_at=T4,
    )


def _event(record: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(record["receipt_body"])


def test_policy_and_approval_gate_provider_execution(
    store: SqliteBuilderOpsStore,
    repo_root: Path,
) -> None:
    service, registry, adapter = _service(store, repo_root)
    _submit(service)

    assert service.projection("run.design.one").state == "approval_pending"
    with pytest.raises(
        DesignRunApprovalRequiredError,
        match="exact current",
    ):
        service.execute(
            run_id="run.design.one",
            started_at=T3,
            completed_at=T4,
        )
    assert registry.calls == []
    assert adapter.calls == []

    service.approve(
        run_id="run.design.one",
        approval_id="run.design.one.approval",
        approved_at=T2,
    )
    result = service.execute(
        run_id="run.design.one",
        started_at=T3,
        completed_at=T4,
    )
    assert result.final_status == "succeeded"
    assert registry.calls == [("codex", "run.design.one")]
    assert len(adapter.calls) == 1
    assert service.projection("run.design.one").refusal is None

    denied_root = repo_root.parent / "denied-repo"
    denied_path = denied_root / "config/builderops/design_run_policy.json"
    denied_path.parent.mkdir(parents=True)
    denied_path.write_text(
        json.dumps(
            _policy(
                allowed_deliverables=("content_review",)
            ).model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    denied_service, denied_registry, denied_adapter = _service(
        SqliteBuilderOpsStore(repo_root.parent / "denied.sqlite3"),
        denied_root,
    )
    denied_service.store.initialize()
    _submit(denied_service, run_id="run.denied.one")
    assert denied_service.projection("run.denied.one").state == "denied"
    with pytest.raises(DesignRunGovernanceError, match="terminally refused"):
        denied_service.execute(
            run_id="run.denied.one",
            started_at=T3,
            completed_at=T4,
        )
    assert denied_registry.calls == []
    assert denied_adapter.calls == []

    foreign_store = SqliteBuilderOpsStore(
        repo_root.parent / "foreign-resolution.sqlite3"
    )
    foreign_store.initialize()
    foreign_adapter = RecordingAdapter()
    foreign_registry = RecordingRegistry(
        foreign_adapter,
        resolution_group_id="design-run:foreign.run",
    )
    foreign_service = DesignRunGovernance(
        store=foreign_store,
        registry=foreign_registry,
        repo_root=repo_root,
    )
    _submit(foreign_service, run_id="run.foreign.resolution")
    foreign_service.approve(
        run_id="run.foreign.resolution",
        approval_id="approval.foreign.resolution",
        approved_at=T2,
    )
    with pytest.raises(
        DesignRunUnavailableError,
        match="unavailable",
    ):
        foreign_service.execute(
            run_id="run.foreign.resolution",
            started_at=T3,
            completed_at=T4,
        )
    assert foreign_registry.calls == [
        ("codex", "run.foreign.resolution")
    ]
    assert foreign_adapter.calls == []
    assert foreign_service.projection(
        "run.foreign.resolution"
    ).state == "unavailable"

    time_store = SqliteBuilderOpsStore(
        repo_root.parent / "invalid-time.sqlite3"
    )
    time_store.initialize()
    time_service, time_registry, time_adapter = _service(
        time_store,
        repo_root,
    )
    _submit(time_service, run_id="run.invalid.time")
    time_service.approve(
        run_id="run.invalid.time",
        approval_id="approval.invalid.time",
        approved_at=T2,
    )
    receipt_count = len(
        time_store.list_records("BuilderOpsReceipt")
    )
    with pytest.raises(
        DesignRunGovernanceError,
        match="completion precedes",
    ):
        time_service.execute(
            run_id="run.invalid.time",
            started_at=T4,
            completed_at=T3,
        )
    assert len(
        time_store.list_records("BuilderOpsReceipt")
    ) == receipt_count
    assert time_registry.calls == []
    assert time_adapter.calls == []


def test_repo_governed_policy_is_the_only_admission_source(
    store: SqliteBuilderOpsStore,
    repo_root: Path,
) -> None:
    service, registry, adapter = _service(store, repo_root)
    _submit(service)
    admission = service.projection("run.design.one").admission
    assert admission is not None
    assert (
        admission.policy_ref.content_hash
        == _policy().content_hash
    )

    policy_path = repo_root / "config/builderops/design_run_policy.json"
    policy_path.write_text(
        json.dumps(
            _policy(approval_required=False).model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    service.approve(
        run_id="run.design.one",
        approval_id="run.design.one.approval",
        approved_at=T2,
    )
    with pytest.raises(
        DesignRunGovernanceError,
        match="policy changed",
    ):
        service.execute(
            run_id="run.design.one",
            started_at=T3,
            completed_at=T4,
        )
    assert registry.calls == []
    assert adapter.calls == []
    assert service.projection("run.design.one").state == "denied"
    assert service.projection(
        "run.design.one"
    ).refusal.code == "admission_denied"
    with pytest.raises(
        DesignRunGovernanceError,
        match="terminally refused",
    ):
        service.execute(
            run_id="run.design.one",
            started_at=T3,
            completed_at=T4,
        )
    assert [
        _event(record)["event_type"]
        for record in store.list_records("BuilderOpsReceipt")
    ].count("run_refused") == 1

    policy_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DesignRunGovernanceError, match="malformed"):
        service.build_request(
            request_id="request.malformed.one",
            brief=_brief(),
            adapter=_descriptor(),
            requested_at=T0,
        )
    policy_path.unlink()
    with pytest.raises(DesignRunGovernanceError, match="unavailable"):
        service.build_request(
            request_id="request.missing.one",
            brief=_brief(),
            adapter=_descriptor(),
            requested_at=T0,
        )


def test_authenticated_approval_and_revocation_bind_exact_admission(
    store: SqliteBuilderOpsStore,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.builderops.design_run_governance._authenticated_local_principal",
        lambda: "local-operator",
    )
    service, registry, adapter = _service(store, repo_root)
    _submit(service)

    with pytest.raises(
        DesignRunApprovalRequiredError,
        match="stale",
    ):
        service.approve(
            run_id="run.design.one",
            approval_id="approval.stale.one",
            approved_at=T0,
        )
    approval_result = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(store.db_path),
            "design-run",
            "approve",
            "run.design.one",
            "--approval-id",
            "approval.exact.one",
            "--approved-at",
            T2,
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert approval_result.exit_code == 0, approval_result.output
    approval = json.loads(approval_result.output)
    admission = service.projection("run.design.one").admission
    assert admission is not None
    assert approval["request_ref"] == admission.request_ref.model_dump(
        mode="json"
    )
    approval_record = store.list_records("BuilderOpsReceipt")[-1]
    assert approval_record["actor"] == {
        "actor_type": "human",
        "id": "local-operator",
    }
    assert "actor" not in inspect.signature(service.approve).parameters

    revoke_result = CliRunner().invoke(
        builderops,
        [
            "--db-path",
            str(store.db_path),
            "design-run",
            "revoke",
            "run.design.one",
            "--revocation-id",
            "approval.revoke.one",
            "--revoked-at",
            T3,
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert revoke_result.exit_code == 0, revoke_result.output
    assert json.loads(revoke_result.output)["state"] == "revoked"
    with pytest.raises(
        DesignRunApprovalRequiredError,
        match="exact current",
    ):
        service.execute(
            run_id="run.design.one",
            started_at=T4,
            completed_at="2026-07-30T10:05:00Z",
        )
    assert registry.calls == []
    assert adapter.calls == []


def test_visual_admission_requires_current_yggdrasil_parity(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    cases = (
        (
            "run.visual.missing",
            _brief(
                visual=True,
                repo_token_source="untrusted/design_tokens.css",
            ),
            T1,
        ),
        (
            "run.visual.drift",
            _brief(visual=True, token_hash=SHA_A),
            T1,
        ),
        (
            "run.visual.stale",
            _brief(
                visual=True,
                verified_at="2026-07-30T08:00:00Z",
                expires_at="2026-07-30T09:00:00Z",
            ),
            T1,
        ),
    )
    for run_id, brief, evaluated_at in cases:
        case_store = SqliteBuilderOpsStore(
            tmp_path / f"{run_id}.sqlite3"
        )
        case_store.initialize()
        service, registry, adapter = _service(case_store, repo_root)
        _submit(
            service,
            run_id=run_id,
            brief=brief,
            evaluated_at=evaluated_at,
        )
        assert service.projection(run_id).state == "denied"
        with pytest.raises(
            DesignRunGovernanceError,
            match="terminally refused",
        ):
            service.execute(
                run_id=run_id,
                started_at=T3,
                completed_at=T4,
            )
        assert registry.calls == []
        assert adapter.calls == []
        if run_id == "run.visual.missing":
            def rewrite_untrusted_observation(
                records: list[dict[str, Any]],
            ) -> list[dict[str, Any]]:
                copied = [dict(record) for record in records]
                for record in copied:
                    event = _event(record)
                    if event["event_type"] != "admission_recorded":
                        continue
                    event["artifact"][
                        "repo_token_hash_observed"
                    ] = SHA_A
                    event["artifact"]["refusal"] = {
                        "code": "yggdrasil_token_drift",
                        "public_message": (
                            "Yggdrasil token parity is not current."
                        ),
                        "retryable": False,
                    }
                    event["artifact_hash"] = hashlib.sha256(
                        canonical_json(event["artifact"]).encode(
                            "utf-8"
                        )
                    ).hexdigest()
                    record["receipt_body"] = canonical_json(event)
                    record["idempotency_key"] = (
                        "design-run:run.visual.missing:"
                        f"admission_recorded:{event['artifact_hash']}:"
                        f"{event['previous_receipt_hash']}"
                    )
                return copied

            untrusted_tamper, _, _ = _service(
                TamperingStore(
                    case_store,
                    rewrite_untrusted_observation,
                ),
                repo_root,
            )
            with pytest.raises(
                DesignRunEvidenceError,
                match="admission semantics",
            ):
                untrusted_tamper.projection(run_id)

    with pytest.raises(ValidationError, match="Yggdrasil gate receipt"):
        CuratedDesignBrief(
            **(
                _brief(visual=True).model_dump()
                | {"yggdrasil_gate_receipt": None}
            )
        )

    accepted_store = SqliteBuilderOpsStore(
        tmp_path / "run.visual.execute-drift.sqlite3"
    )
    accepted_store.initialize()
    accepted_service, accepted_registry, accepted_adapter = _service(
        accepted_store,
        repo_root,
    )
    _submit(
        accepted_service,
        run_id="run.visual.execute.drift",
        brief=_brief(visual=True),
    )
    accepted_admission = accepted_service.projection(
        "run.visual.execute.drift"
    ).admission
    assert accepted_admission is not None
    assert accepted_admission.repo_token_hash_observed == SHA_C
    accepted_service.approve(
        run_id="run.visual.execute.drift",
        approval_id="approval.visual.execute.drift",
        approved_at=T2,
    )
    (
        repo_root
        / "companion-ui/companion-app/colors_and_type.css"
    ).write_bytes(b"changed repo design tokens\n")
    with pytest.raises(
        DesignRunGovernanceError,
        match="no longer current",
    ):
        accepted_service.execute(
            run_id="run.visual.execute.drift",
            started_at=T3,
            completed_at=T4,
        )
    assert accepted_registry.calls == []
    assert accepted_adapter.calls == []
    drift_projection = accepted_service.projection(
        "run.visual.execute.drift"
    )
    assert drift_projection.state == "denied"
    assert drift_projection.refusal is not None
    assert drift_projection.refusal.code == "yggdrasil_token_drift"


def test_design_run_transitions_are_append_only_and_receipted(
    store: SqliteBuilderOpsStore,
    repo_root: Path,
) -> None:
    service, _, adapter = _service(store, repo_root)
    _submit(service)
    _submit(service)
    _approve_and_execute(service)
    first_result = service.projection("run.design.one").result
    replay = service.execute(
        run_id="run.design.one",
        started_at=T3,
        completed_at=T4,
    )

    records = store.list_records("BuilderOpsReceipt")
    events = [_event(record) for record in records]
    assert [event["event_type"] for event in events] == [
        "request_persisted",
        "admission_recorded",
        "approval_recorded",
        "start_accepted",
        "run_succeeded",
    ]
    assert len(adapter.calls) == 1
    assert replay == first_result
    assert all(record["object_type"] == "BuilderOpsReceipt" for record in records)
    for previous, current in zip(records, records[1:]):
        current_event = _event(current)
        assert current_event["previous_receipt_id"] == previous["id"]
        assert current_event["previous_receipt_hash"] == service._node(
            previous,
            expected_run_id="run.design.one",
        ).event_hash

    lease = store.acquire_lease(
        records[0]["id"],
        actor={"actor_type": "agent", "id": "test"},
    )
    with pytest.raises(BuilderOpsValidationError, match="append-only"):
        store.transition_record_state(
            records[0]["id"],
            actor={"actor_type": "agent", "id": "test"},
            lease_id=lease["lease_id"],
            idempotency_key="transition:design-run-root",
            source_refs=[
                {
                    "ref_type": "repo_doc",
                    "ref": (
                        "docs/CKM_DESIGN_AGENT_INTEGRATION/"
                        "GOVERN_DESIGN_RUN_LIFECYCLE.md"
                    ),
                }
            ],
            summary="Bad transition",
            action="archive",
            receipt_body="Receipts must remain append-only.",
            lifecycle_state="archived",
        )

    concurrent_store = SqliteBuilderOpsStore(
        repo_root.parent / "concurrent.sqlite3"
    )
    concurrent_store.initialize()
    barrier_store = RootBarrierStore(
        concurrent_store,
        threading.Barrier(2),
    )
    first_service, _, _ = _service(barrier_store, repo_root)
    second_service, _, _ = _service(barrier_store, repo_root)
    second_brief = _brief().model_copy(
        update={
            "brief_id": "brief.design.two",
            "projection_id": "ckm.projection.two",
        }
    )

    def concurrent_submit(
        candidate: DesignRunGovernance,
        brief: CuratedDesignBrief,
    ) -> object:
        try:
            _submit(
                candidate,
                run_id="run.concurrent.one",
                brief=brief,
            )
            return "accepted"
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(
            future.result()
            for future in (
                pool.submit(concurrent_submit, first_service, _brief()),
                pool.submit(
                    concurrent_submit,
                    second_service,
                    second_brief,
                ),
            )
        )
    assert outcomes.count("accepted") == 1
    assert sum(isinstance(item, DesignRunPersistenceError) for item in outcomes) == 1
    concurrent_projection = first_service.projection(
        "run.concurrent.one"
    )
    assert concurrent_projection.state == "approval_pending"
    assert len(
        [
            record
            for record in concurrent_store.list_records(
                "BuilderOpsReceipt"
            )
            if _event(record)["run_id"] == "run.concurrent.one"
            and _event(record)["event_type"] == "request_persisted"
        ]
    ) == 1


def test_tampered_or_incomplete_receipt_chain_refuses_the_run(
    store: SqliteBuilderOpsStore,
    repo_root: Path,
) -> None:
    service, _, _ = _service(store, repo_root)
    _submit(service)
    _approve_and_execute(service)

    def mutate_event(
        records: list[dict[str, Any]],
        index: int,
        **changes: Any,
    ) -> list[dict[str, Any]]:
        copied = [dict(record) for record in records]
        event = _event(copied[index])
        event.update(changes)
        copied[index]["receipt_body"] = json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
        )
        return copied

    transforms = (
        lambda records: mutate_event(
            records,
            -1,
            run_id="run.foreign",
        ),
        lambda records: mutate_event(
            records,
            -1,
            previous_receipt_id="receipt_missing",
        ),
        lambda records: mutate_event(
            records,
            -1,
            previous_receipt_hash=SHA_A,
        ),
        lambda records: mutate_event(
            records,
            1,
            previous_receipt_id=records[-1]["id"],
        ),
        lambda records: [
            *records,
            {
                **records[-1],
                "id": "receipt_branching_copy",
            },
        ],
        lambda records: [
            *records[:-1],
            {**records[-1], "authority_class": "raw"},
        ],
        lambda records: [
            *records[:-1],
            {**records[-1], "lifecycle_state": "archived"},
        ],
        lambda records: [
            *records[:-1],
            {**records[-1], "promotion_status": "candidate"},
        ],
        lambda records: [
            *records[:-1],
            {
                **records[-1],
                "updated_at": "2099-01-01T00:00:00Z",
            },
        ],
        lambda records: [
            *records[:-1],
            {**records[-1], "promotion_intent": "forged"},
        ],
        lambda records: records[:-1],
    )
    for transform in transforms:
        tampered, _, _ = _service(
            TamperingStore(store, transform),
            repo_root,
        )
        if transform is transforms[-1]:
            projection = tampered.projection("run.design.one")
            assert projection.state == "running"
            assert projection.result is None
        else:
            with pytest.raises(DesignRunEvidenceError):
                tampered.projection("run.design.one")

    _submit(service, run_id="run.semantic.tamper")

    def rewrite_admission(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        copied = [dict(record) for record in records]
        for record in copied:
            event = _event(record)
            if (
                event["run_id"] != "run.semantic.tamper"
                or event["event_type"] != "admission_recorded"
            ):
                continue
            event["artifact"]["outcome"] = "allow"
            event["artifact"]["refusal"] = None
            event["artifact_hash"] = hashlib.sha256(
                canonical_json(event["artifact"]).encode("utf-8")
            ).hexdigest()
            record["receipt_body"] = canonical_json(event)
            record["idempotency_key"] = (
                f"design-run:run.semantic.tamper:"
                f"admission_recorded:{event['artifact_hash']}:"
                f"{event['previous_receipt_hash']}"
            )
        return copied

    semantic_tamper, _, _ = _service(
        TamperingStore(store, rewrite_admission),
        repo_root,
    )
    with pytest.raises(
        DesignRunEvidenceError,
        match="admission semantics",
    ):
        semantic_tamper.projection("run.semantic.tamper")

    def rewrite_observed_hash(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        copied = [dict(record) for record in records]
        for record in copied:
            event = _event(record)
            if (
                event["run_id"] != "run.semantic.tamper"
                or event["event_type"] != "admission_recorded"
            ):
                continue
            event["artifact"]["repo_token_hash_observed"] = SHA_A
            event["artifact_hash"] = hashlib.sha256(
                canonical_json(event["artifact"]).encode("utf-8")
            ).hexdigest()
            record["receipt_body"] = canonical_json(event)
            record["idempotency_key"] = (
                f"design-run:run.semantic.tamper:"
                f"admission_recorded:{event['artifact_hash']}:"
                f"{event['previous_receipt_hash']}"
            )
        return copied

    observed_hash_tamper, _, _ = _service(
        TamperingStore(store, rewrite_observed_hash),
        repo_root,
    )
    with pytest.raises(
        DesignRunEvidenceError,
        match="admission semantics",
    ):
        observed_hash_tamper.projection("run.semantic.tamper")

    denied_root = repo_root.parent / "semantic-denied-repo"
    denied_policy_path = (
        denied_root / "config/builderops/design_run_policy.json"
    )
    denied_policy_path.parent.mkdir(parents=True)
    denied_policy_path.write_text(
        json.dumps(
            _policy(
                allowed_deliverables=("content_review",)
            ).model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    denied_store = SqliteBuilderOpsStore(
        repo_root.parent / "semantic-denied.sqlite3"
    )
    denied_store.initialize()
    denied_service, _, _ = _service(denied_store, denied_root)
    _submit(denied_service, run_id="run.denied.observation")

    def rewrite_denied_observation(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        copied = [dict(record) for record in records]
        for record in copied:
            event = _event(record)
            if event["event_type"] != "admission_recorded":
                continue
            event["artifact"]["repo_token_hash_observed"] = SHA_A
            event["artifact_hash"] = hashlib.sha256(
                canonical_json(event["artifact"]).encode("utf-8")
            ).hexdigest()
            record["receipt_body"] = canonical_json(event)
            record["idempotency_key"] = (
                "design-run:run.denied.observation:"
                f"admission_recorded:{event['artifact_hash']}:"
                f"{event['previous_receipt_hash']}"
            )
        return copied

    denied_observation_tamper, _, _ = _service(
        TamperingStore(denied_store, rewrite_denied_observation),
        denied_root,
    )
    with pytest.raises(
        DesignRunEvidenceError,
        match="admission semantics",
    ):
        denied_observation_tamper.projection(
            "run.denied.observation"
        )

    _submit(service, run_id="run.event.approval")
    service.approve(
        run_id="run.event.approval",
        approval_id="approval.event.pairing",
        approved_at=T2,
    )

    def rewrite_event_state(
        run_id: str,
        event_type: str,
        state: str,
        previous_state: str,
    ) -> Callable[
        [list[dict[str, Any]]],
        list[dict[str, Any]],
    ]:
        def transform(
            records: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            copied = [dict(record) for record in records]
            for record in copied:
                event = _event(record)
                if (
                    event["run_id"] == run_id
                    and event["event_type"] == event_type
                ):
                    event["state"] = state
                    event["previous_state"] = previous_state
                    record["receipt_body"] = canonical_json(event)
            return copied

        return transform

    forged_approval_state, _, _ = _service(
        TamperingStore(
            store,
            rewrite_event_state(
                "run.event.approval",
                "approval_recorded",
                "running",
                "approval_pending",
            ),
        ),
        repo_root,
    )
    with pytest.raises(
        DesignRunEvidenceError,
        match="approval receipt",
    ):
        forged_approval_state.projection("run.event.approval")

    incomplete_service, _, _ = _service(
        FailingStore(store, fail_actions={"run_succeeded"}),
        repo_root,
    )
    _submit(incomplete_service, run_id="run.event.start")
    incomplete_service.approve(
        run_id="run.event.start",
        approval_id="approval.event.start",
        approved_at=T2,
    )
    with pytest.raises(DesignRunPersistenceError):
        incomplete_service.execute(
            run_id="run.event.start",
            started_at=T3,
            completed_at=T4,
        )
    forged_start_state, _, _ = _service(
        TamperingStore(
            store,
            rewrite_event_state(
                "run.event.start",
                "start_accepted",
                "denied",
                "approval_pending",
            ),
        ),
        repo_root,
    )
    with pytest.raises(
        DesignRunEvidenceError,
        match="resolution does not bind",
    ):
        forged_start_state.projection("run.event.start")

    def rewrite_resolution_group(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        copied = [dict(record) for record in records]
        for record in copied:
            event = _event(record)
            if (
                event["run_id"] != "run.event.start"
                or event["event_type"] != "start_accepted"
            ):
                continue
            event["artifact"]["resolution_group_id"] = (
                "design-run:foreign.run"
            )
            event["artifact_hash"] = hashlib.sha256(
                canonical_json(event["artifact"]).encode("utf-8")
            ).hexdigest()
            record["receipt_body"] = canonical_json(event)
            record["idempotency_key"] = (
                f"design-run:run.event.start:start_accepted:"
                f"{event['artifact_hash']}:"
                f"{event['previous_receipt_hash']}"
            )
        return copied

    foreign_resolution, _, _ = _service(
        TamperingStore(store, rewrite_resolution_group),
        repo_root,
    )
    with pytest.raises(
        DesignRunEvidenceError,
        match="resolution does not bind",
    ):
        foreign_resolution.projection("run.event.start")


def test_design_outputs_have_no_direct_authority_or_writeback(
    store: SqliteBuilderOpsStore,
    repo_root: Path,
) -> None:
    adapter = RecordingAdapter(
        artifact_content="unaccepted design proposal; do not publish"
    )
    service, registry, _ = _service(store, repo_root, adapter=adapter)
    _submit(service)
    _approve_and_execute(service)

    projection = service.projection("run.design.one")
    assert projection.result is not None
    assert projection.result.handoff is not None
    assert (
        projection.result.handoff.acceptance_state
        == "unaccepted_builder_material"
    )
    assert projection.result.handoff.source_refs == (_source(),)
    assert len(registry.calls) == 1
    assert set(inspect.signature(DesignRunGovernance).parameters) == {
        "store",
        "registry",
        "repo_root",
        "lease_ttl_seconds",
    }
    assert set(inspect.signature(service.execute).parameters) == {
        "run_id",
        "started_at",
        "completed_at",
    }
    records = store.list_records()
    assert {record["object_type"] for record in records} == {
        "BuilderOpsReceipt"
    }
    serialized = json.dumps(records, sort_keys=True)
    assert adapter.artifact_content not in serialized
    assert "provider-request-not-persisted" not in serialized
    assert "PromotionIntent" not in serialized
    assert not any(
        key in serialized
        for key in (
            "github_issue_mutation",
            "github_pr_mutation",
            "owner_doc_writeback",
            "product_runtime_writeback",
        )
    )


@pytest.mark.parametrize(
    "adapter",
    (
        pytest.param(
            RecordingAdapter(response_text="unstructured provider prose"),
            id="unstructured-prose",
        ),
        pytest.param(
            RecordingAdapter(content_hash_override="0" * 64),
            id="content-digest",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "acceptance_state": "accepted",
                }
            ),
            id="acceptance-state",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "adapter_ref": {
                        "schema_version": DESIGN_RUN_CONTRACT_VERSION,
                        "contract_id": "adapter.foreign",
                        "content_hash": SHA_A,
                    },
                }
            ),
            id="adapter-ref",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "handoff_id": "run.foreign.handoff",
                }
            ),
            id="handoff-id",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "limitations": ["Different unaccepted limitation."],
                }
            ),
            id="limitations",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "produced_at": T3,
                }
            ),
            id="produced-at",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "receipt_ref": {
                        "schema_version": DESIGN_RUN_EVENT_VERSION,
                        "contract_id": "receipt.foreign",
                        "content_hash": SHA_A,
                    },
                }
            ),
            id="receipt-ref",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "run_id": "run.foreign",
                }
            ),
            id="run-id",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "source_refs": [
                        {
                            "source_type": "ckm_observation",
                            "source_id": "ckm:observation:foreign",
                            "content_hash": SHA_A,
                        }
                    ],
                }
            ),
            id="source-refs",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "handoff_id": " run.foreign.handoff ",
                }
            ),
            id="padded-identifier",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "limitations": [
                        " Unaccepted Builder material; governed promotion is required. "
                    ]
                }
            ),
            id="padded-non-empty",
        ),
        pytest.param(
            RecordingAdapter(
                handoff_overrides={
                    "source_refs": [],
                }
            ),
            id="missing-sources",
        ),
    ),
)
def test_unverifiable_adapter_handoff_never_records_success(
    tmp_path: Path,
    repo_root: Path,
    adapter: RecordingAdapter,
) -> None:
    store = SqliteBuilderOpsStore(
        tmp_path / f"{len(adapter.response_text or '')}.sqlite3"
    )
    store.initialize()
    service, _, _ = _service(store, repo_root, adapter=adapter)
    run_id = (
        "run.invalid.handoff.prose"
        if adapter.response_text is not None
        else "run.invalid.handoff.digest"
    )
    _submit(service, run_id=run_id)
    service.approve(
        run_id=run_id,
        approval_id=f"{run_id}.approval",
        approved_at=T2,
    )

    result = service.execute(
        run_id=run_id,
        started_at=T3,
        completed_at=T4,
    )

    assert result.final_status == "failed"
    assert result.handoff is None
    assert result.refusal is not None
    assert result.refusal.code == "execution_failed"
    assert service.projection(run_id).state == "failed"
    serialized = json.dumps(store.list_records(), sort_keys=True)
    assert adapter.artifact_content not in serialized
    if adapter.response_text:
        assert adapter.response_text not in serialized
    assert "provider-request-not-persisted" not in serialized


def test_persistence_failures_remain_fail_closed(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    admission_store = SqliteBuilderOpsStore(tmp_path / "admission.sqlite3")
    admission_store.initialize()
    failing_admission = FailingStore(
        admission_store,
        fail_actions={"admission_recorded"},
    )
    admission_service, admission_registry, admission_adapter = _service(
        failing_admission,
        repo_root,
    )
    with pytest.raises(DesignRunPersistenceError, match="not durable"):
        _submit(
            admission_service,
            run_id="run.persistence.admission",
        )
    assert admission_registry.calls == []
    assert admission_adapter.calls == []
    with pytest.raises(DesignRunEvidenceError, match="admission"):
        admission_service.projection("run.persistence.admission")
    failing_admission.fail_actions.clear()
    _submit(
        admission_service,
        run_id="run.persistence.admission",
    )
    assert (
        admission_service.projection(
            "run.persistence.admission"
        ).state
        == "approval_pending"
    )

    pre_store = SqliteBuilderOpsStore(tmp_path / "pre.sqlite3")
    pre_store.initialize()
    pre_service, pre_registry, pre_adapter = _service(
        FailingStore(pre_store, fail_actions={"start_accepted"}),
        repo_root,
    )
    _submit(pre_service, run_id="run.persistence.pre")
    pre_service.approve(
        run_id="run.persistence.pre",
        approval_id="approval.persistence.pre",
        approved_at=T2,
    )
    with pytest.raises(DesignRunPersistenceError, match="not durable"):
        pre_service.execute(
            run_id="run.persistence.pre",
            started_at=T3,
            completed_at=T4,
        )
    assert pre_registry.calls == [("codex", "run.persistence.pre")]
    assert pre_adapter.calls == []
    assert (
        pre_service.projection("run.persistence.pre").state
        == "approval_pending"
    )

    terminal_store = SqliteBuilderOpsStore(tmp_path / "terminal.sqlite3")
    terminal_store.initialize()
    failing_terminal = FailingStore(
        terminal_store,
        fail_actions={"run_succeeded"},
    )
    terminal_service, terminal_registry, terminal_adapter = _service(
        failing_terminal,
        repo_root,
    )
    _submit(terminal_service, run_id="run.persistence.terminal")
    terminal_service.approve(
        run_id="run.persistence.terminal",
        approval_id="approval.persistence.terminal",
        approved_at=T2,
    )
    with pytest.raises(DesignRunPersistenceError, match="not durable"):
        terminal_service.execute(
            run_id="run.persistence.terminal",
            started_at=T3,
            completed_at=T4,
        )
    projection = terminal_service.projection(
        "run.persistence.terminal"
    )
    assert projection.state == "running"
    assert projection.result is None
    assert projection.refusal is None
    with pytest.raises(DesignRunIncompleteError, match="incomplete"):
        terminal_service.execute(
            run_id="run.persistence.terminal",
            started_at=T3,
            completed_at=T4,
        )
    assert terminal_registry.calls == [
        ("codex", "run.persistence.terminal")
    ]
    assert len(terminal_adapter.calls) == 1
    recovery = terminal_service.recover_incomplete(
        run_id="run.persistence.terminal",
        recovered_at="2026-07-30T10:05:00Z",
    )
    assert recovery.final_status == "failed"
    assert terminal_service.projection(
        "run.persistence.terminal"
    ).state == "failed"

    def rewrite_terminal(
        records: list[dict[str, Any]],
        *,
        run_id: str,
        update: Callable[[dict[str, Any]], None],
    ) -> list[dict[str, Any]]:
        copied = [dict(record) for record in records]
        for record in copied:
            event = _event(record)
            if (
                event["run_id"] != run_id
                or event["event_type"]
                not in {"run_failed", "recovery_failed"}
            ):
                continue
            update(event)
            event["artifact_hash"] = hashlib.sha256(
                canonical_json(event["artifact"]).encode("utf-8")
            ).hexdigest()
            record["receipt_body"] = canonical_json(event)
            record["idempotency_key"] = (
                f"design-run:{run_id}:{event['event_type']}:"
                f"{event['artifact_hash']}:"
                f"{event['previous_receipt_hash']}"
            )
        return copied

    for update in (
        lambda event: event["artifact"].__setitem__(
            "result_id",
            "run.persistence.terminal.forged",
        ),
        lambda event: (
            event["artifact"].__setitem__(
                "final_status",
                "timed_out",
            ),
            event["artifact"].__setitem__(
                "refusal",
                {
                    "code": "timed_out",
                    "public_message": (
                        "The selected design agent timed out."
                    ),
                    "retryable": False,
                },
            ),
            event.__setitem__("state", "timed_out"),
        ),
        lambda event: event["artifact"].__setitem__(
            "refusal",
            {
                "code": "timed_out",
                "public_message": (
                    "The selected design agent timed out."
                ),
                "retryable": False,
            },
        ),
    ):
        tampered_recovery, _, _ = _service(
            TamperingStore(
                terminal_store,
                lambda records, update=update: rewrite_terminal(
                    records,
                    run_id="run.persistence.terminal",
                    update=update,
                ),
            ),
            repo_root,
        )
        with pytest.raises(DesignRunEvidenceError):
            tampered_recovery.projection(
                "run.persistence.terminal"
            )

    failed_store = SqliteBuilderOpsStore(tmp_path / "failed.sqlite3")
    failed_store.initialize()
    failed_service, _, _ = _service(
        failed_store,
        repo_root,
        adapter=RecordingAdapter(response_text=""),
    )
    _submit(failed_service, run_id="run.persistence.failed")
    failed_service.approve(
        run_id="run.persistence.failed",
        approval_id="approval.persistence.failed",
        approved_at=T2,
    )
    assert failed_service.execute(
        run_id="run.persistence.failed",
        started_at=T3,
        completed_at=T4,
    ).final_status == "failed"
    tampered_failure, _, _ = _service(
        TamperingStore(
            failed_store,
            lambda records: rewrite_terminal(
                records,
                run_id="run.persistence.failed",
                update=lambda event: event["artifact"].__setitem__(
                    "result_id",
                    "run.persistence.failed.forged",
                ),
            ),
        ),
        repo_root,
    )
    with pytest.raises(
        DesignRunEvidenceError,
        match="result bindings",
    ):
        tampered_failure.projection("run.persistence.failed")

    race_store = SqliteBuilderOpsStore(tmp_path / "race.sqlite3")
    race_store.initialize()
    race_service, race_registry, race_adapter = _service(
        race_store,
        repo_root,
    )
    _submit(race_service, run_id="run.persistence.race")
    race_service.approve(
        run_id="run.persistence.race",
        approval_id="approval.persistence.race",
        approved_at=T2,
    )
    recovery_service, _, _ = _service(race_store, repo_root)
    race_proxy = SecondAcquireCallbackStore(
        race_store,
        lambda: recovery_service.recover_incomplete(
            run_id="run.persistence.race",
            recovered_at=T4,
        ),
    )
    race_service.store = race_proxy
    with pytest.raises(
        DesignRunIncompleteError,
        match="changed before terminal",
    ):
        race_service.execute(
            run_id="run.persistence.race",
            started_at=T3,
            completed_at="2026-07-30T10:05:00Z",
        )
    assert race_registry.calls == [("codex", "run.persistence.race")]
    assert len(race_adapter.calls) == 1
    race_projection = race_service.projection(
        "run.persistence.race"
    )
    assert race_projection.state == "failed"
    assert race_projection.result is not None
    assert race_projection.result.final_status == "failed"

    terminal_race_store = SqliteBuilderOpsStore(
        tmp_path / "terminal-race.sqlite3"
    )
    terminal_race_store.initialize()
    terminal_race_service, _, terminal_race_adapter = _service(
        terminal_race_store,
        repo_root,
    )
    _submit(
        terminal_race_service,
        run_id="run.persistence.terminal.race",
    )
    terminal_race_service.approve(
        run_id="run.persistence.terminal.race",
        approval_id="approval.persistence.terminal.race",
        approved_at=T2,
    )
    terminal_recovery_service, _, _ = _service(
        terminal_race_store,
        repo_root,
    )
    terminal_race_service.store = TerminalAppendRecoveryStore(
        terminal_race_store,
        lambda: terminal_recovery_service.recover_incomplete(
            run_id="run.persistence.terminal.race",
            recovered_at=T4,
        ),
    )
    with pytest.raises(DesignRunPersistenceError):
        terminal_race_service.execute(
            run_id="run.persistence.terminal.race",
            started_at=T3,
            completed_at="2026-07-30T10:05:00Z",
        )
    assert len(terminal_race_adapter.calls) == 1
    terminal_race_projection = terminal_race_service.projection(
        "run.persistence.terminal.race"
    )
    assert terminal_race_projection.state == "failed"
    assert terminal_race_projection.result is not None
    assert (
        terminal_race_projection.result.final_status
        == "failed"
    )

    start_race_store = SqliteBuilderOpsStore(
        tmp_path / "start-race.sqlite3"
    )
    start_race_store.initialize()
    first_start_service, _, first_start_adapter = _service(
        start_race_store,
        repo_root,
    )
    second_start_service, _, second_start_adapter = _service(
        start_race_store,
        repo_root,
    )
    _submit(
        first_start_service,
        run_id="run.persistence.start.race",
    )
    first_start_service.approve(
        run_id="run.persistence.start.race",
        approval_id="approval.persistence.start.race",
        approved_at=T2,
    )
    first_start_service.store = StartAppendCompetitorStore(
        start_race_store,
        lambda: second_start_service.execute(
            run_id="run.persistence.start.race",
            started_at=T3,
            completed_at=T4,
        ),
    )
    with pytest.raises(DesignRunPersistenceError):
        first_start_service.execute(
            run_id="run.persistence.start.race",
            started_at=T3,
            completed_at=T4,
        )
    assert first_start_adapter.calls == []
    assert len(second_start_adapter.calls) == 1
    start_race_projection = first_start_service.projection(
        "run.persistence.start.race"
    )
    assert start_race_projection.state == "succeeded"
    assert start_race_projection.result is not None
    assert start_race_projection.refusal is None
