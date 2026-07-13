from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_adapters import (
    ADAPTER_CONFIG_ENV,
    AdapterExecutionError,
    AdapterResult,
    ScriptedAdapter,
)
from app.builderops.model_inquiry_contract import RESPONSE_SCHEMA_VERSION, canonical_hash
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from app.builderops.models import BuilderOpsValidationError


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


def test_dry_run_is_deterministic_and_side_effect_free(tmp_path: Path) -> None:
    service, vault = _start(tmp_path, "inq_runner_dry")
    before = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    runner = ModelInquiryRunner(service, env={})

    first = runner.run("inq_runner_dry", max_rounds=2, dry_run=True)
    second = runner.run("inq_runner_dry", max_rounds=2, dry_run=True)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["unavailable_roles"] == ["fable", "gpt_codex"]
    assert {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()} == before


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

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        raise AdapterExecutionError(
            "classified fixture failure",
            failure_class="command_exit_nonzero",
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
    config = {
        "fable": {
            "kind": "command",
            "role_identity": "fable",
            "adapter_id": "fable-command",
            "provider": "fable",
            "model": "fable-model",
            "argv": ["/missing/fable"],
            "timeout_seconds": "not-a-number",
        },
        "gpt_codex": {
            "kind": "command",
            "role_identity": "gpt_codex",
            "adapter_id": "codex-command",
            "provider": "codex",
            "model": "codex-model",
            "argv": ["/missing/codex"],
        },
    }
    result = ModelInquiryRunner(
        service, env={ADAPTER_CONFIG_ENV: json.dumps(config)}
    ).run(inquiry_id, max_rounds=1)
    assert result["outcome"] == "provider_unavailable"


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
