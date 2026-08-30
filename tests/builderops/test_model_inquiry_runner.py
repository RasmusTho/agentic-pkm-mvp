from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.builderops.model_inquiry import (
    ModelInquiryService,
    _validate_adapter_failure_diagnostic,
)
from app.builderops.model_inquiry_adapters import (
    INQUIRY_INTENT_CONFIG_ENV,
    AdapterExecutionError,
    AdapterResult,
    CredentialUnavailableError,
    LocalCommandAdapter,
    ScriptedAdapter,
)
from app.builderops.model_inquiry_contract import (
    MODEL_TURN_SYSTEM_PROMPT,
    RESPONSE_SCHEMA_VERSION,
    canonical_hash,
    initial_context_packet,
    model_turn_request_hash,
    model_turn_system_prompt,
)
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from app.builderops.models import BuilderOpsValidationError
from tests.builderops.inquiry_intent import (
    DECLARED_TEST_CREDENTIALS,
    intent_config,
    intent_env,
    provisioned_env,
    resolver_for_targets,
)


def _downgrade_manifest_to_legacy(vault: Path, inquiry_id: str) -> None:
    manifest_path = vault / "model-inquiries" / inquiry_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = "builderops.model-inquiry.v1"
    for field in ("acceptance_mode", "perspectives", "independence", "artifact_hash"):
        manifest.pop(field, None)
    manifest["artifact_hash"] = canonical_hash(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _hybrid_manifest_to_legacy(vault: Path, inquiry_id: str) -> None:
    manifest_path = vault / "model-inquiries" / inquiry_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = "builderops.model-inquiry.v1"
    manifest.pop("artifact_hash", None)
    manifest["artifact_hash"] = canonical_hash(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _start(
    tmp_path: Path,
    inquiry_id: str,
    *,
    acceptance_mode: str | None = "single_target",
) -> tuple[ModelInquiryService, Path]:
    vault = tmp_path / inquiry_id
    vault.mkdir()
    service = ModelInquiryService(vault)
    service.start(
        question=f"Question for {inquiry_id}",
        workflow="fable-gpt-architecture",
        acceptance_mode="single_target",
        inquiry_id=inquiry_id,
        source_refs=[{"ref_type": "github_issue", "ref": "#3291"}],
    )
    if acceptance_mode is None:
        _downgrade_manifest_to_legacy(vault, inquiry_id)
    return service, vault


def _response(
    stance: str,
    *,
    reviewed: list[str] | None = None,
    accepted_hash: str | None = None,
) -> str:
    return json.dumps(
        {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "stance": stance,
            "content": f"{stance} content",
            "claims": ["bounded claim"],
            "risks": [],
            "blocking_questions": [],
            "reviewed_artifact_refs": reviewed or [],
            "accepted_artifact_hash": accepted_hash,
        }
    )


def _scripted(role: str, responses: list[str]) -> ScriptedAdapter:
    return ScriptedAdapter(
        adapter_id="configured-sol-adapter",
        provider="configured-provider",
        model="configured-sol-model",
        responses=responses,
        calls=[],
    )


def test_single_target_acceptance_is_truthful_and_receipted(tmp_path: Path) -> None:
    vault = tmp_path / "single-target"
    vault.mkdir()
    service = ModelInquiryService(vault)
    service.start(
        question="Choose the bounded implementation.",
        workflow="governed-model-inquiry",
        acceptance_mode="single_target",
        inquiry_id="inq_single_target",
        source_refs=[{"ref_type": "github_issue", "ref": "#5203"}],
    )
    reviewed = ["draft-synthesis", "draft-verification"]

    class SameTargetAdapter(ScriptedAdapter):
        pass

    adapters = {
        perspective: SameTargetAdapter(
            adapter_id="configured-sol-subscription",
            provider="configured-provider",
            model="configured-sol-model",
            responses=[
                _response("draft"),
                _response("accept", reviewed=reviewed, accepted_hash=None),
            ],
            calls=[],
        )
        for perspective in ("synthesis", "verification")
    }

    # Each accept response must bind one persisted draft hash. Scripted responses
    # are replaced after the drafts exist so the test follows the production graph.
    for perspective, adapter in adapters.items():
        original_execute = adapter.execute

        def execute(request: Mapping[str, Any], *, _original=original_execute) -> AdapterResult:
            if request["phase"] == "review":
                return AdapterResult(
                    _response(
                        "accept",
                        reviewed=list(request["reviewed_artifact_refs"]),
                        accepted_hash=str(request["input_artifacts"][0]["artifact_hash"]),
                    )
                )
            return _original(request)

        adapter.execute = execute  # type: ignore[method-assign]

    result = ModelInquiryRunner(service, adapters).run(
        "inq_single_target", max_rounds=1
    )

    assert result["outcome"] == "single_target_acceptance"
    trace = ModelInquiryService(vault).trace("inq_single_target")
    terminal = next(
        item
        for item in trace["receipts"]
        if item["event_type"] == "inquiry_run_terminal"
    )
    details = terminal["details"]
    assert details["acceptance_mode"] == "single_target"
    assert details["independence"] is False
    assert len(details["target_fingerprints"]) == 1
    assert details["effective_targets"] == [
        {
            "adapter_id": "configured-sol-subscription",
            "provider": "configured-provider",
            "model": "configured-sol-model",
        }
    ]
    assert details["context_hash"]
    assert details["synthesis_artifact_hash"] == trace["synthesis"]["artifact_hash"]
    assert all(turn["context_hash"] == details["context_hash"] for turn in trace["turns"])
    assert terminal["outcome"] != "consensus"


def test_single_target_acceptance_recovers_after_synthesis_before_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _start(tmp_path, "inq_single_target_terminal_gap", acceptance_mode="single_target")
    adapters = {
        perspective: ScriptedAdapter(
            adapter_id="configured-sol-subscription",
            provider="configured-provider",
            model="configured-sol-model",
            responses=[_response("draft"), _response("accept")],
            calls=[],
        )
        for perspective in ("synthesis", "verification")
    }
    for adapter in adapters.values():
        original_execute = adapter.execute

        def execute(request: Mapping[str, Any], *, _original=original_execute) -> AdapterResult:
            if request["phase"] == "review":
                return AdapterResult(
                    _response(
                        "accept",
                        reviewed=list(request["reviewed_artifact_refs"]),
                        accepted_hash=str(request["input_artifacts"][0]["artifact_hash"]),
                    )
                )
            return _original(request)

        adapter.execute = execute  # type: ignore[method-assign]

    original_terminal = service.commit_run_terminal_receipt

    def crash_before_terminal(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise KeyboardInterrupt("simulated crash after synthesis")

    monkeypatch.setattr(service, "commit_run_terminal_receipt", crash_before_terminal)
    with pytest.raises(KeyboardInterrupt, match="simulated crash"):
        ModelInquiryRunner(service, adapters).run("inq_single_target_terminal_gap", max_rounds=1)

    partial = service.trace("inq_single_target_terminal_gap")
    assert partial["synthesis"] is not None
    assert not any(item["event_type"] == "inquiry_run_terminal" for item in partial["receipts"])

    monkeypatch.setattr(service, "commit_run_terminal_receipt", original_terminal)
    result = ModelInquiryRunner(service, adapters).run(
        "inq_single_target_terminal_gap", max_rounds=1
    )
    assert result["outcome"] == "single_target_acceptance"
    recovered = service.trace("inq_single_target_terminal_gap")
    terminal = next(
        item for item in recovered["receipts"] if item["event_type"] == "inquiry_run_terminal"
    )
    assert terminal["details"]["synthesis_artifact_hash"] == recovered["synthesis"]["artifact_hash"]


def test_legacy_inquiry_is_readable_but_not_reactivated_by_sol_path(tmp_path: Path) -> None:
    rejected_vault = tmp_path / "rejected-legacy-start"
    rejected_vault.mkdir()
    rejected_service = ModelInquiryService(rejected_vault)
    with pytest.raises(BuilderOpsValidationError, match="must use single_target"):
        rejected_service.start(
            question="Do not mint a new v1 inquiry",
            workflow="governed-model-inquiry",
            acceptance_mode=None,  # type: ignore[arg-type]
            inquiry_id="inq_rejected_legacy_start",
            source_refs=[{"ref_type": "github_issue", "ref": "#5203"}],
        )
    assert not list(rejected_vault.rglob("*"))

    default_vault = tmp_path / "default-v2"
    default_vault.mkdir()
    default_service = ModelInquiryService(default_vault)
    default_service.start(
        question="New inquiries use the active contract",
        workflow="governed-model-inquiry",
        inquiry_id="inq_default_v2",
        source_refs=[{"ref_type": "github_issue", "ref": "#5203"}],
    )
    default_manifest = default_service.trace("inq_default_v2")["inquiry"]
    assert default_manifest["schema"] == "builderops.model-inquiry.v2"
    assert default_manifest["acceptance_mode"] == "single_target"

    hybrid_service, hybrid_vault = _start(tmp_path, "inq_hybrid_v1_read_only")
    _hybrid_manifest_to_legacy(hybrid_vault, "inq_hybrid_v1_read_only")
    hybrid_trace = hybrid_service.trace("inq_hybrid_v1_read_only")
    assert hybrid_trace["inquiry"]["acceptance_mode"] == "single_target"
    with pytest.raises(BuilderOpsValidationError, match="legacy.*read-only"):
        ModelInquiryRunner(hybrid_service, env={}).plan(
            "inq_hybrid_v1_read_only",
            max_rounds=1,
        )
    with pytest.raises(BuilderOpsValidationError, match="legacy.*read-only"):
        ModelInquiryRunner(hybrid_service, env={}).run(
            "inq_hybrid_v1_read_only",
            max_rounds=1,
            dry_run=True,
        )

    default_manifest_path = (
        default_vault / "model-inquiries" / "inq_default_v2" / "manifest.json"
    )
    corrupted_manifest = json.loads(
        default_manifest_path.read_text(encoding="utf-8")
    )
    corrupted_manifest["artifact_hash"] = "0" * 64
    default_manifest_path.write_text(
        json.dumps(corrupted_manifest),
        encoding="utf-8",
    )
    corrupt_before = {
        path.relative_to(default_vault): path.read_bytes()
        for path in default_vault.rglob("*")
        if path.is_file()
    }
    with pytest.raises(BuilderOpsValidationError, match="manifest artifact hash mismatch"):
        default_service.commit_readiness(
            "inq_default_v2",
            outcome="not_ready",
            rationale="Corrupt manifest must fail before writes.",
            input_artifact_refs=["question"],
            source_refs=[{"ref_type": "github_issue", "ref": "#5203"}],
        )
    with pytest.raises(BuilderOpsValidationError, match="manifest artifact hash mismatch"):
        with default_service.inquiry_runner_lock("inq_default_v2"):
            pytest.fail("corrupt-manifest lock unexpectedly acquired")
    assert {
        path.relative_to(default_vault): path.read_bytes()
        for path in default_vault.rglob("*")
        if path.is_file()
    } == corrupt_before

    service, vault = _start(
        tmp_path,
        "inq_legacy_read_only",
        acceptance_mode=None,
    )
    assert service.trace("inq_legacy_read_only")["inquiry"]["schema"] == (
        "builderops.model-inquiry.v1"
    )
    before = {
        path.relative_to(vault): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    }
    adapters = {
        "fable": _scripted("fable", [_response("draft")]),
        "gpt_codex": _scripted("gpt_codex", [_response("draft")]),
    }

    with pytest.raises(BuilderOpsValidationError, match="legacy.*read-only"):
        ModelInquiryRunner(service, adapters).run("inq_legacy_read_only", max_rounds=1)
    with pytest.raises(BuilderOpsValidationError, match="legacy.*read-only"):
        ModelInquiryRunner(service, env={}).run(
            "inq_legacy_read_only",
            max_rounds=1,
            dry_run=True,
        )

    source_refs = [{"ref_type": "github_issue", "ref": "#3291"}]
    mutations = (
        lambda: service.commit_turn(
            "inq_legacy_read_only",
            turn_id="legacy-turn",
            sequence=0,
            role="fable",
            content="No legacy write",
            input_artifact_refs=["question"],
            source_refs=source_refs,
        ),
        lambda: service.commit_synthesis(
            "inq_legacy_read_only",
            content="No legacy synthesis",
            input_artifact_refs=["question"],
            source_refs=source_refs,
        ),
        lambda: service.commit_readiness(
            "inq_legacy_read_only",
            outcome="not_ready",
            rationale="Legacy is trace-only.",
            input_artifact_refs=["question"],
            source_refs=source_refs,
        ),
        lambda: service.commit_readiness_receipt(
            "inq_legacy_read_only",
            source_refs=source_refs,
        ),
        lambda: service.commit_promotion_intent(
            "inq_legacy_read_only",
            repository="example/repo",
            marker=f"<!-- builderops-inquiry-promotion:inq_legacy_read_only:{'d' * 64} -->",
            title="No legacy promotion",
            issue_body="Legacy is trace-only.",
            source_refs=source_refs,
        ),
        lambda: service.commit_promotion_receipt(
            "inq_legacy_read_only",
            intent={},
            issue_number=1,
            issue_url="https://github.com/example/repo/issues/1",
            issue_created_at="2026-08-30T12:00:00Z",
            source_refs=source_refs,
        ),
        lambda: service.commit_delivery_reference(
            "inq_legacy_read_only",
            delivery_ref={
                "ref_type": "owner_doc",
                "ref": "docs/BUILDEROPS_MODEL_INQUIRY/README.md",
            },
            source_refs=source_refs,
        ),
        lambda: service.commit_terminal_turn_receipt(
            "inq_legacy_read_only",
            turn_id="legacy-turn",
            outcome="accepted",
            source_refs=source_refs,
        ),
        lambda: service.commit_provider_attempt_receipt(
            "inq_legacy_read_only",
            adapter_request_id="legacy-attempt",
            outcome="provider_error",
            details={"classification": "must not persist"},
            source_refs=source_refs,
        ),
        lambda: service.commit_run_terminal_receipt(
            "inq_legacy_read_only",
            outcome="provider_error",
            details={"classification": "must not persist"},
            source_refs=source_refs,
        ),
        lambda: service.write_human_readable_report("inq_legacy_read_only"),
    )
    for mutation in mutations:
        with pytest.raises(BuilderOpsValidationError, match="legacy.*read-only"):
            mutation()

    for lock in (service.inquiry_runner_lock, service.inquiry_promotion_lock):
        with pytest.raises(BuilderOpsValidationError, match="legacy.*read-only"):
            with lock("inq_legacy_read_only"):
                pytest.fail("legacy lock unexpectedly acquired")

    trace = service.trace("inq_legacy_read_only")
    assert trace["inquiry"]["schema"] == "builderops.model-inquiry.v1"
    assert trace["turns"] == []
    assert not adapters["fable"].calls
    assert not adapters["gpt_codex"].calls
    assert {
        path.relative_to(vault): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    } == before


def test_single_target_max_round_terminal_is_readable_and_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    service, _ = _start(
        tmp_path,
        "inq_single_target_max_rounds",
        acceptance_mode="single_target",
    )
    reviewed = ["draft-synthesis", "draft-verification"]
    adapters = {
        perspective: _scripted(
            perspective,
            [_response("draft"), _response("revise", reviewed=reviewed)],
        )
        for perspective in ("synthesis", "verification")
    }
    runner = ModelInquiryRunner(service, adapters)

    first = runner.run("inq_single_target_max_rounds", max_rounds=1)
    trace = service.trace("inq_single_target_max_rounds")
    calls_after_first_run = sum(len(adapter.calls) for adapter in adapters.values())
    second = runner.run("inq_single_target_max_rounds", max_rounds=1)

    assert first["outcome"] == "max_rounds_exhausted"
    assert second["terminal_receipt_id"] == first["terminal_receipt_id"]
    assert sum(len(adapter.calls) for adapter in adapters.values()) == calls_after_first_run
    assert trace["inquiry"]["acceptance_mode"] == "single_target"
    assert {turn["role"] for turn in trace["turns"]} == {
        "synthesis",
        "verification",
    }


def test_independent_drafts_share_context_hash(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_context")
    reviewed = ["draft-synthesis", "draft-verification"]
    fable = _scripted("synthesis", [_response("draft"), _response("revise", reviewed=reviewed)])
    gpt = _scripted("verification", [_response("draft"), _response("revise", reviewed=reviewed)])

    result = ModelInquiryRunner(service, {"synthesis": fable, "verification": gpt}).run(
        "inq_runner_context", max_rounds=1
    )

    assert result["outcome"] == "max_rounds_exhausted"
    assert fable.calls[0]["context_hash"] == gpt.calls[0]["context_hash"]
    assert fable.calls[0]["input_artifacts"][0]["artifact_id"] == "question"
    assert gpt.calls[0]["input_artifacts"][0]["artifact_id"] == "question"
    assert "draft-verification" not in json.dumps(fable.calls[0])
    assert "draft-synthesis" not in json.dumps(gpt.calls[0])


def test_review_turn_uses_persisted_inputs_and_validates_output(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_review")
    reviewed = ["draft-synthesis", "draft-verification"]
    fable = _scripted("synthesis", [_response("draft"), _response("revise", reviewed=reviewed)])
    gpt = _scripted("verification", [_response("draft"), "{\"stance\":\"revise\"}"])

    result = ModelInquiryRunner(service, {"synthesis": fable, "verification": gpt}).run(
        "inq_runner_review", max_rounds=1
    )

    assert result["outcome"] == "malformed_output"
    review_request = fable.calls[1]
    assert review_request["reviewed_artifact_refs"] == reviewed
    assert [item["artifact_id"] for item in review_request["input_artifacts"]] == reviewed
    assert all(item["artifact_hash"] for item in review_request["input_artifacts"])
    assert not any(turn["turn_id"] == "review-000-verification" for turn in service.trace("inq_runner_review")["turns"])


def test_dry_run_performs_no_adapter_call_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, vault = _start(tmp_path, "inq_runner_dry")
    before = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    posts = _forbid_provider_calls(monkeypatch)
    runner = ModelInquiryRunner(service, env={})

    first = runner.run("inq_runner_dry", max_rounds=2, dry_run=True)
    second = runner.run("inq_runner_dry", max_rounds=2, dry_run=True)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["unavailable_roles"] == ["synthesis", "verification"]
    assert {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()} == before

    # A fully provisioned, resolvable single-target configuration still performs
    # no call and writes nothing, and a mock identity is still refused.
    single_vault = tmp_path / "single-target-dry"
    single_vault.mkdir()
    single_service = ModelInquiryService(single_vault)
    single_service.start(
        question="Question for the single-target dry run",
        workflow="governed-model-inquiry",
        acceptance_mode="single_target",
        inquiry_id="inq_runner_single_dry",
        source_refs=[{"ref_type": "github_issue", "ref": "#5203"}],
    )
    unconfigured_single_target = ModelInquiryRunner(single_service, env={}).run(
        "inq_runner_single_dry", max_rounds=2, dry_run=True
    )
    assert unconfigured_single_target["unavailable_roles"] == [
        "synthesis",
        "verification",
    ]
    assert set(unconfigured_single_target["adapter_descriptors"]) == {
        "synthesis",
        "verification",
    }

    provisioned = ModelInquiryRunner(
        single_service, env=provisioned_env(tmp_path / "secrets")
    ).run("inq_runner_single_dry", max_rounds=2, dry_run=True)
    assert provisioned["unavailable_roles"] == []
    assert provisioned["adapter_descriptors"]["synthesis"]["available"] is True

    mocked = ModelInquiryRunner(
        single_service,
        env=provisioned_env(tmp_path / "secrets"),
        resolver=resolver_for_targets(
            tmp_path / "mock-census",
            {"synthesis": ("mock", "mock-chat"), "verification": ("mock", "mock-chat")},
        ),
    ).run("inq_runner_single_dry", max_rounds=2, dry_run=True)
    assert mocked["unavailable_roles"] == ["synthesis", "verification"]
    assert all(
        "mock" in descriptor["reason"]
        for descriptor in mocked["adapter_descriptors"].values()
    )
    assert not posts
    assert {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()} == before
    assert "credential" not in json.dumps(provisioned).replace(
        "credential_identity_ref", ""
    ).replace("anthropic.api-key", "").replace("openai.api-key", "")


def _forbid_provider_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail loudly if any code path reaches a provider transport."""
    calls: list[str] = []

    def refuse(url: str, **_kwargs: Any) -> None:
        calls.append(url)
        raise AssertionError(f"unexpected provider call: {url}")

    monkeypatch.setattr(
        "app.builderops.model_inquiry_adapters.requests.post",
        refuse,
    )
    return calls


@dataclass
class ConsensusAdapter:
    adapter_id: str
    provider: str
    model: str
    calls: list[dict[str, Any]]

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        if request["phase"] == "draft":
            return AdapterResult(_response("draft"), f"provider-{self.adapter_id}-draft")
        accepted = request["input_artifacts"][0]["artifact_hash"]
        return AdapterResult(
            _response(
                "accept",
                reviewed=list(request["reviewed_artifact_refs"]),
                accepted_hash=accepted,
            ),
            f"provider-{self.adapter_id}-review",
        )


@dataclass
class FailingAdapter:
    adapter_id: str = "configured-sol-adapter"
    provider: str = "configured-provider"
    model: str = "configured-sol-model"
    failure_class: str = "command_exit_nonzero"

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if self.failure_class == "credential_unavailable":
            raise CredentialUnavailableError(
                adapter_id=self.adapter_id,
                credential_identity_ref="anthropic.api-key",
            )
        raise AdapterExecutionError(
            "classified fixture failure",
            failure_class=self.failure_class,
            exit_code=17,
        )


@dataclass
class CountingFailureAdapter:
    adapter_id: str
    provider: str
    model: str
    calls: list[dict[str, Any]]
    failure_class: str = "command_exit_nonzero"

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        raise AdapterExecutionError(
            "classified fixture failure",
            failure_class=self.failure_class,
            exit_code=17,
        )


@dataclass
class CrashOnceConsensusAdapter(ConsensusAdapter):
    crash: bool = True

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if self.crash:
            self.crash = False
            raise KeyboardInterrupt("injected crash after durable primary failure")
        return super().execute(request)


@dataclass
class RecoveringConsensusAdapter(ConsensusAdapter):
    failures_remaining: int = 1

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if self.failures_remaining:
            self.failures_remaining -= 1
            self.calls.append(dict(request))
            raise AdapterExecutionError(
                "transient command failure",
                failure_class="command_exit_nonzero",
                exit_code=17,
            )
        return super().execute(request)


class LocalCommandFixtureAdapter(LocalCommandAdapter):
    """Exercise subscription fallback policy without spawning a subprocess."""

    def __init__(self, delegate: Any) -> None:
        super().__init__(
            adapter_id="configured-sol-adapter",
            provider="configured-provider",
            model="configured-sol-model",
            argv=("fixture-local-command",),
        )
        object.__setattr__(self, "delegate", delegate)

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        return self.delegate.execute(request)


def _subscription_adapters(first: Any, second: Any) -> dict[str, LocalCommandAdapter]:
    return {
        "synthesis": LocalCommandFixtureAdapter(first),
        "verification": LocalCommandFixtureAdapter(second),
    }


@dataclass
class UnexpectedSecretAdapter:
    provider_request_secret: bool = False
    adapter_id: str = "configured-sol-adapter"
    provider: str = "configured-provider"
    model: str = "configured-sol-model"

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if self.provider_request_secret:
            return AdapterResult(_response("draft"), "credential-sentinel")
        raise RuntimeError("credential-sentinel")


def test_runner_records_all_terminal_conditions(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_consensus")
    adapters = {
        role: ConsensusAdapter(
            "configured-sol-adapter",
            "configured-provider",
            "configured-sol-model",
            [],
        )
        for role in ("synthesis", "verification")
    }
    consensus = ModelInquiryRunner(service, adapters).run("inq_runner_consensus", max_rounds=1)
    assert consensus["outcome"] == "single_target_acceptance"

    cases = {
        "provider_refused": (_response("refuse"), _response("draft")),
        "malformed_output": ("not-json", _response("draft")),
    }
    for outcome, (fable_response, gpt_response) in cases.items():
        inquiry_id = f"inq_runner_{outcome}"
        case_service, _ = _start(tmp_path, inquiry_id)
        result = ModelInquiryRunner(
            case_service,
            {
                "synthesis": _scripted("synthesis", [fable_response]),
                "verification": _scripted("verification", [gpt_response]),
            },
        ).run(inquiry_id, max_rounds=1)
        assert result["outcome"] == outcome

    unavailable_service, _ = _start(tmp_path, "inq_runner_unavailable")
    unavailable = ModelInquiryRunner(unavailable_service, env={}).run(
        "inq_runner_unavailable", max_rounds=1
    )
    assert unavailable["outcome"] == "provider_unavailable"

    error_service, _ = _start(tmp_path, "inq_runner_error")
    gpt_after_fable_failure = _scripted("verification", [_response("draft")])
    provider_error = ModelInquiryRunner(
        error_service,
        {"synthesis": FailingAdapter(), "verification": gpt_after_fable_failure},
    ).run("inq_runner_error", max_rounds=1)
    assert provider_error["outcome"] == "provider_error"
    assert provider_error["details"]["diagnostic"] == {
        "adapter_id": "configured-sol-adapter",
        "adapter_failure_class": "command_exit_nonzero",
        "adapter_exit_code": 17,
    }
    provider_error_trace = error_service.trace("inq_runner_error")
    failure_receipts = [
        receipt
        for receipt in provider_error_trace["receipts"]
        if receipt["event_type"] in {"inquiry_provider_attempt_terminal", "inquiry_run_terminal"}
    ]
    assert len(failure_receipts) == 2
    assert failure_receipts[0]["details"]["diagnostic"] == failure_receipts[1]["details"][
        "diagnostic"
    ]
    assert not gpt_after_fable_failure.calls

    for inquiry_id in (
        "inq_runner_consensus",
        "inq_runner_provider_refused",
        "inq_runner_malformed_output",
        "inq_runner_unavailable",
        "inq_runner_error",
    ):
        trace = ModelInquiryService(tmp_path / inquiry_id).trace(inquiry_id)
        terminals = [r for r in trace["receipts"] if r.get("event_type") == "inquiry_run_terminal"]
        assert len(terminals) == 1


def test_single_available_adapter_completes_truthful_degraded_consensus(
    tmp_path: Path,
) -> None:
    service, vault = _start(tmp_path, "inq_runner_degraded")
    fable = CountingFailureAdapter("fable-adapter", "anthropic", "claude-fable-5", [])
    sol = ConsensusAdapter("sol-adapter", "openai", "gpt-5.6-sol", [])

    result = ModelInquiryRunner(
        service,
        _subscription_adapters(fable, sol),
        allow_operational_fallback=True,
    ).run("inq_runner_degraded", max_rounds=1)

    assert result["outcome"] == "provider_error"
    trace = ModelInquiryService(vault).trace("inq_runner_degraded")
    assert trace["turns"] == []
    attempts = [
        receipt
        for receipt in trace["receipts"]
        if receipt["event_type"] == "inquiry_provider_attempt_terminal"
    ]
    assert len(attempts) == 1
    assert {attempt["details"]["candidate_adapter_id"] for attempt in attempts} == {
        "configured-sol-adapter"
    }
    assert [call["phase"] for call in fable.calls] == ["draft"]
    assert sol.calls == []


def test_single_target_never_enters_operational_fallback(tmp_path: Path) -> None:
    service, vault = _start(
        tmp_path,
        "inq_runner_single_target_no_fallback",
        acceptance_mode="single_target",
    )
    failed = CountingFailureAdapter(
        "configured-sol-primary",
        "configured-provider",
        "configured-sol-model",
        [],
    )
    alternate = ConsensusAdapter(
        "forbidden-alternate",
        "other-provider",
        "other-model",
        [],
    )
    adapters = {
        "synthesis": LocalCommandFixtureAdapter(failed),
        "verification": LocalCommandFixtureAdapter(alternate),
    }

    result = ModelInquiryRunner(
        service,
        adapters,
        allow_operational_fallback=True,
    ).run("inq_runner_single_target_no_fallback", max_rounds=1)

    assert result["outcome"] == "provider_error"
    assert len(failed.calls) == 1
    assert alternate.calls == []
    trace = ModelInquiryService(vault).trace("inq_runner_single_target_no_fallback")
    assert trace["turns"] == []
    terminal = next(
        item
        for item in trace["receipts"]
        if item["event_type"] == "inquiry_run_terminal"
    )
    assert terminal["outcome"] == "provider_error"


def test_local_command_subscription_adapters_enable_fallback_automatically(
    tmp_path: Path,
) -> None:
    service, _ = _start(tmp_path, "inq_runner_local_command_fallback")
    response_program = """
import json
import sys

request = json.load(sys.stdin)
reviewed = request["reviewed_artifact_refs"]
is_draft = request["phase"] == "draft"
payload = {
    "schema_version": "builderops.model-turn-response.v1",
    "stance": "draft" if is_draft else "accept",
    "content": "bounded local-command response",
    "claims": [],
    "risks": [],
    "blocking_questions": [],
    "reviewed_artifact_refs": reviewed,
    "accepted_artifact_hash": None if is_draft else request["input_artifacts"][0]["artifact_hash"],
}
print(json.dumps(payload))
"""
    fable = LocalCommandAdapter(
        adapter_id="fable-local",
        provider="anthropic",
        model="claude-fable-5",
        argv=(sys.executable, "-c", "import sys; sys.exit(17)"),
        timeout_seconds=5,
    )
    sol = LocalCommandAdapter(
        adapter_id="sol-local",
        provider="openai",
        model="gpt-5.6-sol",
        argv=(sys.executable, "-c", response_program),
        timeout_seconds=5,
    )

    result = ModelInquiryRunner(
        service,
        {"synthesis": fable, "verification": sol},
    ).run("inq_runner_local_command_fallback", max_rounds=1)

    assert result["outcome"] == "provider_unavailable"
    assert service.trace(result["inquiry_id"])["turns"] == []


def test_explicit_fallback_flag_cannot_enable_non_subscription_adapters(
    tmp_path: Path,
) -> None:
    service, _ = _start(tmp_path, "inq_runner_non_subscription_boundary")
    primary = CountingFailureAdapter("api-primary", "openai", "gpt-api", [])
    alternate = ConsensusAdapter("api-alternate", "anthropic", "claude-api", [])

    result = ModelInquiryRunner(
        service,
        {"synthesis": primary, "verification": alternate},
        allow_operational_fallback=True,
    ).run("inq_runner_non_subscription_boundary", max_rounds=1)

    assert result["outcome"] == "provider_unavailable"
    assert primary.calls == []
    assert alternate.calls == []


def test_role_focused_prompts_are_distinct_and_hashed_per_candidate(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_role_prompts")
    reviewed = ["draft-synthesis", "draft-verification"]
    synthesis = _scripted(
        "synthesis", [_response("draft"), _response("revise", reviewed=reviewed)]
    )
    verification = _scripted(
        "verification", [_response("draft"), _response("revise", reviewed=reviewed)]
    )

    ModelInquiryRunner(
        service,
        {"synthesis": synthesis, "verification": verification},
        allow_operational_fallback=True,
    ).run("inq_runner_role_prompts", max_rounds=1)

    fable_lane = synthesis.calls[0]
    codex_lane = verification.calls[0]
    assert fable_lane["system_prompt"] == model_turn_system_prompt("synthesis")
    assert codex_lane["system_prompt"] == model_turn_system_prompt("verification")
    assert fable_lane["system_prompt"] != codex_lane["system_prompt"]
    assert "Build one coherent bounded option" in fable_lane["system_prompt"]
    assert "Challenge assumptions" in codex_lane["system_prompt"]
    assert fable_lane["request_hash"] != codex_lane["request_hash"]
    assert fable_lane["adapter_identity"] == codex_lane["adapter_identity"]


def test_candidate_fallback_is_durable_bounded_and_resume_safe(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_fallback_resume")
    primary = CountingFailureAdapter("fable-adapter", "anthropic", "claude-fable-5", [])
    alternate = CrashOnceConsensusAdapter("sol-adapter", "openai", "gpt-5.6-sol", [])
    runner = ModelInquiryRunner(
        service,
        _subscription_adapters(primary, alternate),
        allow_operational_fallback=True,
    )

    result = runner.run("inq_runner_fallback_resume", max_rounds=1)
    assert result["outcome"] == "provider_error"
    assert len(primary.calls) == 1
    assert alternate.calls == []

    bounded_service, _ = _start(tmp_path, "inq_runner_fallback_bounded")
    first = CountingFailureAdapter("first", "anthropic", "claude-fable-5", [])
    second = CountingFailureAdapter("second", "openai", "gpt-5.6-sol", [])
    bounded = ModelInquiryRunner(
        bounded_service,
        _subscription_adapters(first, second),
        allow_operational_fallback=True,
    ).run("inq_runner_fallback_bounded", max_rounds=1)
    assert bounded["outcome"] == "provider_error"
    assert len(first.calls) == 1
    assert second.calls == []


def test_refusal_and_persistence_failure_do_not_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusal_service, _ = _start(tmp_path, "inq_runner_no_refusal_fallback")
    refusal = _scripted("synthesis", [_response("refuse")])
    unused = ConsensusAdapter("sol-adapter", "openai", "gpt-5.6-sol", [])
    refused = ModelInquiryRunner(
        refusal_service,
        _subscription_adapters(refusal, unused),
        allow_operational_fallback=True,
    ).run("inq_runner_no_refusal_fallback", max_rounds=1)
    assert refused["outcome"] == "provider_refused"
    assert unused.calls == []

    persistence_service, _ = _start(tmp_path, "inq_runner_no_persistence_fallback")

    def fail_commit(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise BuilderOpsValidationError("injected persistence failure")

    monkeypatch.setattr(persistence_service, "commit_turn", fail_commit)
    first = ConsensusAdapter("fable-adapter", "anthropic", "claude-fable-5", [])
    second = ConsensusAdapter("sol-adapter", "openai", "gpt-5.6-sol", [])
    persisted = ModelInquiryRunner(
        persistence_service,
        _subscription_adapters(first, second),
        allow_operational_fallback=True,
    ).run("inq_runner_no_persistence_fallback", max_rounds=1)
    assert persisted["outcome"] == "persistence_failed"
    assert len(first.calls) == 1
    assert second.calls == []


def test_session_expiry_does_not_fallback(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_session_expired")
    expired = CountingFailureAdapter(
        "fable-adapter",
        "anthropic",
        "claude-fable-5",
        [],
        failure_class="session_expired",
    )
    alternate = ConsensusAdapter("sol-adapter", "openai", "gpt-5.6-sol", [])

    result = ModelInquiryRunner(
        service,
        _subscription_adapters(expired, alternate),
        allow_operational_fallback=True,
    ).run("inq_runner_session_expired", max_rounds=1)

    assert result["outcome"] == "provider_error"
    assert result["details"]["diagnostic"]["adapter_failure_class"] == "session_expired"
    assert len(expired.calls) == 1
    assert alternate.calls == []


def test_recovered_distinct_targets_remain_genuine_consensus(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_recovered_consensus")
    fable = RecoveringConsensusAdapter(
        "fable-adapter", "anthropic", "claude-fable-5", []
    )
    sol = ConsensusAdapter("sol-adapter", "openai", "gpt-5.6-sol", [])

    result = ModelInquiryRunner(
        service,
        _subscription_adapters(fable, sol),
        allow_operational_fallback=True,
    ).run("inq_runner_recovered_consensus", max_rounds=1)

    assert result["outcome"] == "provider_error"
    trace = service.trace("inq_runner_recovered_consensus")
    review_targets = {
        (turn["adapter_id"], turn["provider"], turn["model"])
        for turn in trace["turns"]
        if turn["phase"] == "review"
    }
    assert review_targets == set()
    assert sol.calls == []
    assert any(
        receipt["event_type"] == "inquiry_provider_attempt_terminal"
        for receipt in trace["receipts"]
    )


def test_distinct_adapter_ids_for_same_model_remain_degraded(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_same_model_ids")
    first = ConsensusAdapter("sol-fable-lane", "openai", "gpt-5.6-sol", [])
    second = ConsensusAdapter("sol-codex-lane", "openai", "gpt-5.6-sol", [])

    result = ModelInquiryRunner(
        service,
        {"synthesis": first, "verification": second},
        allow_operational_fallback=True,
    ).run("inq_runner_same_model_ids", max_rounds=1)

    assert result["outcome"] == "provider_unavailable"
    assert first.calls == []
    assert second.calls == []


def test_legacy_failed_attempt_is_not_retried_on_resume(tmp_path: Path) -> None:
    inquiry_id = "inq_runner_legacy_attempt_resume"
    service, _ = _start(tmp_path, inquiry_id)
    trace = service.trace(inquiry_id)
    source_refs = trace["source_refs"]
    context_hash = canonical_hash(
        initial_context_packet(
            inquiry_id=inquiry_id,
            workflow="fable-gpt-architecture",
            question_artifact_id="question",
            question_artifact_hash=trace["question"]["artifact_hash"],
            source_refs=source_refs,
        )
    )
    input_hash = canonical_hash(
        [
            {
                "artifact_id": "question",
                "artifact_hash": trace["question"]["artifact_hash"],
            }
        ]
    )
    legacy_hash = model_turn_request_hash(
        inquiry_id=inquiry_id,
        role="synthesis",
        phase="draft",
        round_index=0,
        context_hash=context_hash,
        input_hash=input_hash,
        input_artifact_refs=["question"],
        adapter_id="fable-adapter",
        provider="anthropic",
        model="claude-fable-5",
        system_prompt=MODEL_TURN_SYSTEM_PROMPT,
    )
    legacy_request_id = f"adapter_req_{legacy_hash[:32]}"
    service.commit_provider_attempt_receipt(
        inquiry_id,
        adapter_request_id=legacy_request_id,
        outcome="provider_error",
        details={
            "adapter_request_id": legacy_request_id,
            "candidate_adapter_id": "fable-adapter",
            "request_hash": legacy_hash,
            "context_hash": context_hash,
            "input_hash": input_hash,
            "output_hash": None,
            "classification": "provider adapter execution failed",
            "diagnostic": {
                "adapter_id": "fable-adapter",
                "adapter_failure_class": "command_exit_nonzero",
                "adapter_exit_code": 17,
            },
        },
        source_refs=source_refs,
    )
    primary = CountingFailureAdapter(
        "fable-adapter", "anthropic", "claude-fable-5", []
    )
    alternate = ConsensusAdapter("sol-adapter", "openai", "gpt-5.6-sol", [])

    result = ModelInquiryRunner(
        service,
        _subscription_adapters(primary, alternate),
        allow_operational_fallback=True,
    ).run(inquiry_id, max_rounds=1)

    assert result["outcome"] == "provider_error"
    assert [call["phase"] for call in primary.calls] == ["draft"]
    assert alternate.calls == []


def test_resume_and_persistence_failure_fail_closed(tmp_path: Path, monkeypatch) -> None:
    service, _ = _start(tmp_path, "inq_runner_resume")
    reviewed = ["draft-synthesis", "draft-verification"]
    adapters = {
        "synthesis": _scripted("synthesis", [_response("draft"), _response("revise", reviewed=reviewed)]),
        "verification": _scripted("verification", [_response("draft"), _response("revise", reviewed=reviewed)]),
    }
    runner = ModelInquiryRunner(service, adapters)
    first = runner.run("inq_runner_resume", max_rounds=1)
    call_count = sum(len(adapter.calls) for adapter in adapters.values())
    second = runner.run("inq_runner_resume", max_rounds=1)
    assert second["terminal_receipt_id"] == first["terminal_receipt_id"]
    assert sum(len(adapter.calls) for adapter in adapters.values()) == call_count

    failure_service, _ = _start(tmp_path, "inq_runner_persist_fail")
    original = failure_service.commit_turn
    call_number = 0

    def fail_first_commit(*args, **kwargs):
        nonlocal call_number
        call_number += 1
        if call_number == 1:
            raise BuilderOpsValidationError("injected persistence failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(failure_service, "commit_turn", fail_first_commit)
    fable = _scripted("synthesis", [_response("draft")])
    gpt = _scripted("verification", [_response("draft")])
    failed = ModelInquiryRunner(failure_service, {"synthesis": fable, "verification": gpt}).run(
        "inq_runner_persist_fail", max_rounds=1
    )
    assert failed["outcome"] == "persistence_failed"
    assert len(fable.calls) == 1
    assert len(gpt.calls) == 0
    assert failure_service.trace("inq_runner_persist_fail")["turns"] == []


def test_adapter_failures_and_bad_config_are_terminal_without_secret_leak(tmp_path: Path) -> None:
    for suffix, adapter in (
        ("unexpected", UnexpectedSecretAdapter()),
        ("request_id", UnexpectedSecretAdapter(provider_request_secret=True)),
    ):
        inquiry_id = f"inq_runner_secret_{suffix}"
        service, vault = _start(tmp_path, inquiry_id)
        result = ModelInquiryRunner(
            service,
            {"synthesis": adapter, "verification": _scripted("verification", [_response("draft")])},
        ).run(inquiry_id, max_rounds=1)
        assert result["outcome"] == "provider_error"
        assert "credential-sentinel" not in "".join(
            path.read_text(encoding="utf-8") for path in vault.rglob("*.json")
        )

    inquiry_id = "inq_runner_bad_config"
    service, _ = _start(tmp_path, inquiry_id)
    config = intent_config()
    config["target_intent"]["capability_tier"] = "economy"
    result = ModelInquiryRunner(
        service, env={INQUIRY_INTENT_CONFIG_ENV: json.dumps(config)}
    ).run(inquiry_id, max_rounds=1)
    assert result["outcome"] == "provider_unavailable"


class _FakeProviderResponse:
    """Minimal provider transport double; it never carries a credential back."""

    def __init__(self, provider: str, payload: dict[str, Any]) -> None:
        self.headers = {
            "request-id" if provider == "anthropic" else "x-request-id": (
                f"{'req' if provider == 'anthropic' else 'resp'}_{provider}_fixture"
            )
        }
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _provider_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    """Record provider calls and answer them with schema-valid role responses."""
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> _FakeProviderResponse:
        body = kwargs["json"]
        headers = kwargs["headers"]
        calls.append({"url": url, "model": body["model"], "headers": headers})
        request = json.loads(
            body["messages"][-1]["content"]
            if "messages" in body
            else body["messages"][0]["content"]
        )
        if request["phase"] == "draft":
            text = _response("draft")
        else:
            text = _response(
                "accept",
                reviewed=list(request["reviewed_artifact_refs"]),
                accepted_hash=request["input_artifacts"][0]["artifact_hash"],
            )
        if "x-api-key" in headers:
            return _FakeProviderResponse(
                "anthropic", {"content": [{"type": "text", "text": text}]}
            )
        return _FakeProviderResponse(
            "openai", {"choices": [{"message": {"content": text}}]}
        )

    monkeypatch.setattr("app.builderops.model_inquiry_adapters.requests.post", post)
    return calls


def test_production_inquiry_resolves_provider_free_intent_through_builder_census(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, vault = _start(
        tmp_path, "inq_runner_declared", acceptance_mode="single_target"
    )
    calls = _provider_transport(monkeypatch)
    env = provisioned_env(tmp_path / "secrets")

    # The caller submits provider-free intent only.
    submitted = json.dumps(json.loads(env[INQUIRY_INTENT_CONFIG_ENV])).lower()
    for forbidden in ("anthropic", "openai", "claude", "gpt-5", "api_key", "endpoint"):
        assert forbidden not in submitted

    result = ModelInquiryRunner(service, env=env).run("inq_runner_declared", max_rounds=1)

    assert result["outcome"] == "single_target_acceptance"
    turns = service.trace("inq_runner_declared")["turns"]
    assert {turn["provider"] for turn in turns} == {"openai"}
    assert {turn["model"] for turn in turns} == {"gpt-5.6-sol"}
    assert all(turn["provider_request_id"] for turn in turns)
    assert {call["url"] for call in calls} == {
        "https://api.openai.com/v1/chat/completions",
    }
    persisted = "".join(
        path.read_text(encoding="utf-8") for path in vault.rglob("*.json")
    )
    for value in DECLARED_TEST_CREDENTIALS.values():
        assert value not in persisted


def test_production_inquiry_resolves_distinct_effective_targets_for_role_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _start(
        tmp_path, "inq_runner_distinct", acceptance_mode="single_target"
    )
    _provider_transport(monkeypatch)

    ModelInquiryRunner(
        service, env=provisioned_env(tmp_path / "secrets")
    ).run("inq_runner_distinct", max_rounds=1)
    turns = service.trace("inq_runner_distinct")["turns"]
    targets = {(turn["provider"], turn["model"], turn["adapter_id"]) for turn in turns}
    assert len(targets) == 1
    assert len({turn["adapter_id"] for turn in turns}) == 1



def test_absent_credential_fails_closed_as_credential_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, vault = _start(
        tmp_path, "inq_runner_no_credential", acceptance_mode="single_target"
    )
    posts = _forbid_provider_calls(monkeypatch)
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        "app.builderops.model_inquiry_adapters.subprocess.Popen",
        lambda argv, **_kwargs: spawned.append(list(argv)),
    )

    result = ModelInquiryRunner(service, env=intent_env()).run(
        "inq_runner_no_credential", max_rounds=1
    )

    assert result["outcome"] == "provider_error"
    diagnostic = result["details"]["diagnostic"]
    assert diagnostic["adapter_failure_class"] == "credential_unavailable"
    assert diagnostic["credential_identity_ref"] == "openai.api-key"
    assert "adapter_exit_code" not in diagnostic
    # No fallback: no provider transport, no subscription CLI, no second provider.
    assert posts == []
    assert spawned == []
    assert service.trace("inq_runner_no_credential")["turns"] == []

    # The typed class survives the independent persistence-boundary validation.
    reloaded = ModelInquiryService(vault).trace("inq_runner_no_credential")
    attempt = next(
        receipt
        for receipt in reloaded["receipts"]
        if receipt["event_type"] == "inquiry_provider_attempt_terminal"
    )
    assert attempt["details"]["diagnostic"] == diagnostic

    # Ambient environment is not a credential source either.
    ambient_service, _ = _start(tmp_path, "inq_runner_ambient")
    ambient = ModelInquiryRunner(
        ambient_service, env={**intent_env(), **DECLARED_TEST_CREDENTIALS}
    ).run("inq_runner_ambient", max_rounds=1)
    assert ambient["details"]["diagnostic"]["adapter_failure_class"] == (
        "credential_unavailable"
    )
    assert posts == []


@pytest.mark.parametrize(
    ("failure_class", "expected_outcome"),
    [
        ("command_exit_nonzero", "provider_error"),
    ],
)
def test_single_target_typed_failure_is_readable_and_resume_is_idempotent(
    tmp_path: Path,
    failure_class: str,
    expected_outcome: str,
) -> None:
    inquiry_id = f"inq_single_target_{failure_class}"
    service, _ = _start(tmp_path, inquiry_id, acceptance_mode="single_target")
    adapters = {
        "synthesis": FailingAdapter(
            failure_class=failure_class,
        ),
        "verification": _scripted("verification", [_response("draft")]),
    }
    runner = ModelInquiryRunner(service, adapters)

    first = runner.run(inquiry_id, max_rounds=1)
    trace = service.trace(inquiry_id)
    second = runner.run(inquiry_id, max_rounds=1)

    assert first["outcome"] == expected_outcome
    assert second["terminal_receipt_id"] == first["terminal_receipt_id"]
    assert trace["inquiry"]["acceptance_mode"] == "single_target"
    assert any(
        receipt["event_type"] == "inquiry_provider_attempt_terminal"
        for receipt in trace["receipts"]
    )


def test_single_target_malformed_output_is_readable_and_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    inquiry_id = "inq_single_target_malformed_output"
    service, _ = _start(tmp_path, inquiry_id, acceptance_mode="single_target")
    runner = ModelInquiryRunner(
        service,
        {
            "synthesis": _scripted("synthesis", ["not-json"]),
            "verification": _scripted("verification", [_response("draft")]),
        },
    )

    first = runner.run(inquiry_id, max_rounds=1)
    trace = service.trace(inquiry_id)
    second = runner.run(inquiry_id, max_rounds=1)

    assert first["outcome"] == "malformed_output"
    assert second["terminal_receipt_id"] == first["terminal_receipt_id"]
    assert trace["inquiry"]["acceptance_mode"] == "single_target"


def test_single_target_provider_refusal_is_readable_and_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    inquiry_id = "inq_single_target_provider_refused"
    service, _ = _start(tmp_path, inquiry_id, acceptance_mode="single_target")
    runner = ModelInquiryRunner(
        service,
        {
            "synthesis": _scripted("synthesis", [_response("refuse")]),
            "verification": _scripted("verification", [_response("draft")]),
        },
    )

    first = runner.run(inquiry_id, max_rounds=1)
    trace = service.trace(inquiry_id)
    second = runner.run(inquiry_id, max_rounds=1)

    assert first["outcome"] == "provider_refused"
    assert second["terminal_receipt_id"] == first["terminal_receipt_id"]
    assert trace["inquiry"]["acceptance_mode"] == "single_target"


def test_single_target_configuration_failure_is_readable_and_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    inquiry_id = "inq_single_target_configuration_failure"
    service, _ = _start(tmp_path, inquiry_id, acceptance_mode="single_target")
    runner = ModelInquiryRunner(service, env={})

    first = runner.run(inquiry_id, max_rounds=1)
    trace = service.trace(inquiry_id)
    second = runner.run(inquiry_id, max_rounds=1)

    assert first["outcome"] == "provider_unavailable"
    assert second["terminal_receipt_id"] == first["terminal_receipt_id"]
    assert trace["inquiry"]["acceptance_mode"] == "single_target"


def test_auth_failure_class_survives_persistence_revalidation(tmp_path: Path) -> None:
    service, vault = _start(tmp_path, "inq_runner_auth_failure")
    result = ModelInquiryRunner(
        service,
        {
            "synthesis": FailingAdapter(failure_class="credential_unavailable"),
            "verification": _scripted("verification", [_response("draft")]),
        },
    ).run("inq_runner_auth_failure", max_rounds=1)

    assert result["outcome"] == "provider_error"
    assert result["details"]["diagnostic"]["adapter_failure_class"] == "credential_unavailable"

    reloaded_trace = ModelInquiryService(vault).trace("inq_runner_auth_failure")
    terminal = next(
        receipt
        for receipt in reloaded_trace["receipts"]
        if receipt["event_type"] == "inquiry_provider_attempt_terminal"
    )
    assert terminal["details"]["diagnostic"]["adapter_failure_class"] == "credential_unavailable"


def test_unknown_failure_class_is_rejected_at_both_validators() -> None:
    with pytest.raises(ValueError, match="unknown adapter failure class"):
        AdapterExecutionError(
            "unknown classification",
            failure_class="provider_magic_failure",
        )

    with pytest.raises(BuilderOpsValidationError, match="invalid adapter failure class"):
        _validate_adapter_failure_diagnostic(
            {
                "adapter_id": "fixture-adapter",
                "adapter_failure_class": "provider_magic_failure",
            }
        )


def test_credential_failure_identity_is_enforced_iff_at_persistence_boundary() -> None:
    with pytest.raises(BuilderOpsValidationError, match="must appear together"):
        _validate_adapter_failure_diagnostic(
            {
                "adapter_id": "fixture-adapter",
                "adapter_failure_class": "credential_unavailable",
            }
        )
    with pytest.raises(BuilderOpsValidationError, match="must appear together"):
        _validate_adapter_failure_diagnostic(
            {
                "adapter_id": "fixture-adapter",
                "adapter_failure_class": "command_timeout",
                "credential_identity_ref": "anthropic.api-key",
            }
        )
    _validate_adapter_failure_diagnostic(
        {
            "adapter_id": "fixture-adapter",
            "adapter_failure_class": "credential_unavailable",
            "credential_identity_ref": "anthropic.api-key",
        }
    )
    with pytest.raises(BuilderOpsValidationError, match="exact typed field set"):
        _validate_adapter_failure_diagnostic(
            {
                "adapter_id": "fixture-adapter",
                "adapter_failure_class": "credential_unavailable",
                "credential_identity_ref": "anthropic.api-key",
                "adapter_exit_code": 1,
            }
        )


@dataclass
class StaleConsensusAdapter:
    adapter_id: str
    provider: str
    model: str
    calls: list[dict[str, Any]]
    stale_hash: str | None = None

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        if request["phase"] == "draft":
            return AdapterResult(_response("draft"))
        if request["round_index"] == 0:
            if self.stale_hash is None:
                self.stale_hash = request["input_artifacts"][0]["artifact_hash"]
            return AdapterResult(
                _response("revise", reviewed=list(request["reviewed_artifact_refs"]))
            )
        return AdapterResult(
            _response(
                "accept",
                reviewed=list(request["reviewed_artifact_refs"]),
                accepted_hash=self.stale_hash,
            )
        )


def test_consensus_cannot_accept_stale_historical_artifact(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_stale_consensus")
    adapters = {
        role: StaleConsensusAdapter(
            "configured-sol-adapter",
            "configured-provider",
            "configured-sol-model",
            [],
        )
        for role in ("synthesis", "verification")
    }
    result = ModelInquiryRunner(service, adapters).run(
        "inq_runner_stale_consensus", max_rounds=2
    )
    assert result["outcome"] == "malformed_output"


def test_max_round_terminal_cannot_override_proven_consensus(tmp_path: Path) -> None:
    service, vault = _start(tmp_path, "inq_runner_false_max")
    adapters = {
        role: ConsensusAdapter(
            "configured-sol-adapter",
            "configured-provider",
            "configured-sol-model",
            [],
        )
        for role in ("synthesis", "verification")
    }
    result = ModelInquiryRunner(service, adapters).run("inq_runner_false_max", max_rounds=1)
    assert result["outcome"] == "single_target_acceptance"
    path = (
        vault
        / "model-inquiries"
        / "inq_runner_false_max"
        / "receipts"
        / "inquiry-run-terminal.json"
    )
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["outcome"] = "max_rounds_exhausted"
    receipt["action"] = "max_rounds_exhausted"
    receipt["details"] = {"max_rounds": 1}
    receipt["artifact_hash"] = canonical_hash(
        {key: value for key, value in receipt.items() if key != "artifact_hash"}
    )
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(BuilderOpsValidationError, match="incomplete review graph"):
        service.trace("inq_runner_false_max")
