from __future__ import annotations

import json
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
    ScriptedAdapter,
)
from app.builderops.model_inquiry_contract import RESPONSE_SCHEMA_VERSION, canonical_hash
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from app.builderops.models import BuilderOpsValidationError
from tests.builderops.inquiry_intent import (
    DECLARED_TEST_CREDENTIALS,
    intent_config,
    intent_env,
    provisioned_env,
    resolver_for_targets,
)


def _start(tmp_path: Path, inquiry_id: str) -> tuple[ModelInquiryService, Path]:
    vault = tmp_path / inquiry_id
    vault.mkdir()
    service = ModelInquiryService(vault)
    service.start(
        question=f"Question for {inquiry_id}",
        workflow="fable-gpt-architecture",
        inquiry_id=inquiry_id,
        source_refs=[{"ref_type": "github_issue", "ref": "#3291"}],
    )
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
        adapter_id=f"{role}-adapter",
        provider=role,
        model=f"{role}-model",
        responses=responses,
        calls=[],
    )


def test_independent_drafts_share_context_hash(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_context")
    reviewed = ["draft-fable", "draft-gpt_codex"]
    fable = _scripted("fable", [_response("draft"), _response("revise", reviewed=reviewed)])
    gpt = _scripted("gpt_codex", [_response("draft"), _response("revise", reviewed=reviewed)])

    result = ModelInquiryRunner(service, {"fable": fable, "gpt_codex": gpt}).run(
        "inq_runner_context", max_rounds=1
    )

    assert result["outcome"] == "max_rounds_exhausted"
    assert fable.calls[0]["context_hash"] == gpt.calls[0]["context_hash"]
    assert fable.calls[0]["input_artifacts"][0]["artifact_id"] == "question"
    assert gpt.calls[0]["input_artifacts"][0]["artifact_id"] == "question"
    assert "draft-gpt_codex" not in json.dumps(fable.calls[0])
    assert "draft-fable" not in json.dumps(gpt.calls[0])


def test_review_turn_uses_persisted_inputs_and_validates_output(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_review")
    reviewed = ["draft-fable", "draft-gpt_codex"]
    fable = _scripted("fable", [_response("draft"), _response("revise", reviewed=reviewed)])
    gpt = _scripted("gpt_codex", [_response("draft"), "{\"stance\":\"revise\"}"])

    result = ModelInquiryRunner(service, {"fable": fable, "gpt_codex": gpt}).run(
        "inq_runner_review", max_rounds=1
    )

    assert result["outcome"] == "malformed_output"
    review_request = fable.calls[1]
    assert review_request["reviewed_artifact_refs"] == reviewed
    assert [item["artifact_id"] for item in review_request["input_artifacts"]] == reviewed
    assert all(item["artifact_hash"] for item in review_request["input_artifacts"])
    assert not any(turn["turn_id"] == "review-000-gpt_codex" for turn in service.trace("inq_runner_review")["turns"])


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
    assert first["unavailable_roles"] == ["fable", "gpt_codex"]
    assert {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()} == before

    # A fully provisioned, resolvable configuration still performs no call and
    # writes nothing, and a mock identity is still refused as a provider role.
    provisioned = ModelInquiryRunner(
        service, env=provisioned_env(tmp_path / "secrets")
    ).run("inq_runner_dry", max_rounds=2, dry_run=True)
    assert provisioned["unavailable_roles"] == []
    assert provisioned["adapter_descriptors"]["fable"]["available"] is True

    mocked = ModelInquiryRunner(
        service,
        env=provisioned_env(tmp_path / "secrets"),
        resolver=resolver_for_targets(
            tmp_path / "mock-census",
            {"fable": ("mock", "mock-chat"), "gpt_codex": ("mock", "mock-chat")},
        ),
    ).run("inq_runner_dry", max_rounds=2, dry_run=True)
    assert mocked["unavailable_roles"] == ["fable", "gpt_codex"]
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
    adapter_id: str = "failing"
    provider: str = "fixture"
    model: str = "fixture"
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
class UnexpectedSecretAdapter:
    provider_request_secret: bool = False
    adapter_id: str = "unexpected"
    provider: str = "fixture"
    model: str = "fixture"

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        if self.provider_request_secret:
            return AdapterResult(_response("draft"), "credential-sentinel")
        raise RuntimeError("credential-sentinel")


def test_runner_records_all_terminal_conditions(tmp_path: Path) -> None:
    service, _ = _start(tmp_path, "inq_runner_consensus")
    adapters = {
        role: ConsensusAdapter(role, role, f"{role}-model", []) for role in ("fable", "gpt_codex")
    }
    consensus = ModelInquiryRunner(service, adapters).run("inq_runner_consensus", max_rounds=1)
    assert consensus["outcome"] == "consensus"

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
                "fable": _scripted("fable", [fable_response]),
                "gpt_codex": _scripted("gpt_codex", [gpt_response]),
            },
        ).run(inquiry_id, max_rounds=1)
        assert result["outcome"] == outcome

    unavailable_service, _ = _start(tmp_path, "inq_runner_unavailable")
    unavailable = ModelInquiryRunner(unavailable_service, env={}).run(
        "inq_runner_unavailable", max_rounds=1
    )
    assert unavailable["outcome"] == "provider_unavailable"

    error_service, _ = _start(tmp_path, "inq_runner_error")
    gpt_after_fable_failure = _scripted("gpt_codex", [_response("draft")])
    provider_error = ModelInquiryRunner(
        error_service,
        {"fable": FailingAdapter(), "gpt_codex": gpt_after_fable_failure},
    ).run("inq_runner_error", max_rounds=1)
    assert provider_error["outcome"] == "provider_error"
    assert provider_error["details"]["diagnostic"] == {
        "adapter_id": "failing",
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


def test_resume_and_persistence_failure_fail_closed(tmp_path: Path, monkeypatch) -> None:
    service, _ = _start(tmp_path, "inq_runner_resume")
    reviewed = ["draft-fable", "draft-gpt_codex"]
    adapters = {
        "fable": _scripted("fable", [_response("draft"), _response("revise", reviewed=reviewed)]),
        "gpt_codex": _scripted("gpt_codex", [_response("draft"), _response("revise", reviewed=reviewed)]),
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
    fable = _scripted("fable", [_response("draft")])
    gpt = _scripted("gpt_codex", [_response("draft")])
    failed = ModelInquiryRunner(failure_service, {"fable": fable, "gpt_codex": gpt}).run(
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
            {"fable": adapter, "gpt_codex": _scripted("gpt_codex", [_response("draft")])},
        ).run(inquiry_id, max_rounds=1)
        assert result["outcome"] == "provider_error"
        assert "credential-sentinel" not in "".join(
            path.read_text(encoding="utf-8") for path in vault.rglob("*.json")
        )

    inquiry_id = "inq_runner_bad_config"
    service, _ = _start(tmp_path, inquiry_id)
    config = intent_config()
    config["roles"]["fable"]["capability_tier"] = "economy"
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
    service, vault = _start(tmp_path, "inq_runner_declared")
    calls = _provider_transport(monkeypatch)
    env = provisioned_env(tmp_path / "secrets")

    # The caller submits provider-free intent only.
    submitted = json.dumps(json.loads(env[INQUIRY_INTENT_CONFIG_ENV])).lower()
    for forbidden in ("anthropic", "openai", "claude", "gpt-5", "api_key", "endpoint"):
        assert forbidden not in submitted

    result = ModelInquiryRunner(service, env=env).run("inq_runner_declared", max_rounds=1)

    assert result["outcome"] == "consensus"
    turns = service.trace("inq_runner_declared")["turns"]
    assert {turn["provider"] for turn in turns} == {"anthropic", "openai"}
    assert {turn["model"] for turn in turns} == {"claude-fable-5", "gpt-5.6-sol"}
    assert all(turn["provider_request_id"] for turn in turns)
    assert {call["url"] for call in calls} == {
        "https://api.anthropic.com/v1/messages",
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
    service, _ = _start(tmp_path, "inq_runner_distinct")
    calls = _provider_transport(monkeypatch)

    ModelInquiryRunner(
        service, env=provisioned_env(tmp_path / "secrets")
    ).run("inq_runner_distinct", max_rounds=1)
    turns = service.trace("inq_runner_distinct")["turns"]
    targets = {(turn["provider"], turn["model"], turn["adapter_id"]) for turn in turns}
    assert len(targets) == 2
    assert len({turn["adapter_id"] for turn in turns}) == 2

    collided_service, collided_vault = _start(tmp_path, "inq_runner_collided")
    calls.clear()
    collided = ModelInquiryRunner(
        collided_service,
        env=provisioned_env(tmp_path / "secrets"),
        resolver=resolver_for_targets(
            tmp_path / "collided-census",
            {
                "fable": ("anthropic", "claude-fable-5"),
                "gpt_codex": ("anthropic", "claude-fable-5"),
            },
        ),
    ).run("inq_runner_collided", max_rounds=1)

    assert collided["outcome"] == "provider_unavailable"
    assert calls == []
    assert collided_service.trace("inq_runner_collided")["turns"] == []
    assert not list((collided_vault / "model-inquiries" / "inq_runner_collided" / "turns").glob("*"))


def test_absent_credential_fails_closed_as_credential_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, vault = _start(tmp_path, "inq_runner_no_credential")
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
    assert diagnostic["credential_identity_ref"] == "anthropic.api-key"
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


def test_auth_failure_class_survives_persistence_revalidation(tmp_path: Path) -> None:
    service, vault = _start(tmp_path, "inq_runner_auth_failure")
    result = ModelInquiryRunner(
        service,
        {
            "fable": FailingAdapter(failure_class="credential_unavailable"),
            "gpt_codex": _scripted("gpt_codex", [_response("draft")]),
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
        role: StaleConsensusAdapter(role, role, f"{role}-model", [])
        for role in ("fable", "gpt_codex")
    }
    result = ModelInquiryRunner(service, adapters).run(
        "inq_runner_stale_consensus", max_rounds=2
    )
    assert result["outcome"] == "malformed_output"


def test_max_round_terminal_cannot_override_proven_consensus(tmp_path: Path) -> None:
    service, vault = _start(tmp_path, "inq_runner_false_max")
    adapters = {
        role: ConsensusAdapter(role, role, f"{role}-model", [])
        for role in ("fable", "gpt_codex")
    }
    result = ModelInquiryRunner(service, adapters).run("inq_runner_false_max", max_rounds=1)
    assert result["outcome"] == "consensus"
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
