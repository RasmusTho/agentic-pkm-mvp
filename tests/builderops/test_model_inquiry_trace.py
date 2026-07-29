from __future__ import annotations

from pathlib import Path
import json

import pytest

from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.models import BuilderOpsValidationError, normalize_record
from app.builderops.model_inquiry_adapters import ScriptedAdapter
from app.builderops.model_inquiry_contract import RESPONSE_SCHEMA_VERSION, canonical_hash
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from tests.builderops.inquiry_intent import (
    DECLARED_TEST_CREDENTIALS,
    intent_env,
    provisioned_env,
)


def test_trace_links_question_turns_and_synthesis(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    service = ModelInquiryService(vault)
    source_refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Trace this inquiry",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_trace",
        source_refs=source_refs,
    )
    second = service.commit_turn(
        "inq_test_trace",
        turn_id="turn-b",
        sequence=1,
        role="gpt",
        content="Second turn",
        input_artifact_refs=["turn-a"],
        source_refs=source_refs,
    )
    first = service.commit_turn(
        "inq_test_trace",
        turn_id="turn-a",
        sequence=0,
        role="fable",
        content="First turn",
        input_artifact_refs=["question"],
        source_refs=source_refs,
    )
    synthesis = service.commit_synthesis(
        "inq_test_trace",
        content="Shared synthesis",
        input_artifact_refs=["turn-a", "turn-b"],
        source_refs=source_refs,
    )
    readiness = service.commit_readiness(
        "inq_test_trace",
        outcome="needs_input",
        rationale="One contract question remains.",
        input_artifact_refs=["synthesis"],
        source_refs=source_refs,
    )

    trace = ModelInquiryService(vault).trace("inq_test_trace")

    assert trace["question"]["inquiry_id"] == "inq_test_trace"
    assert trace["turns"] == [first, second]
    assert trace["synthesis"] == synthesis
    assert trace["readiness"] == readiness
    assert trace["source_refs"] == source_refs
    assert trace["completeness"] == {
        "ok": True,
        "question": True,
        "turn_count": 2,
        "synthesis": True,
        "readiness": True,
    }
    assert all(item["content_hash"] for item in [trace["question"], *trace["turns"], synthesis])

    receipt_path = (
        vault
        / "model-inquiries"
        / "inq_test_trace"
        / "receipts"
        / "inquiry-started.json"
    )
    receipt_path.unlink()
    with pytest.raises(BuilderOpsValidationError, match="start receipt is missing"):
        ModelInquiryService(vault).trace("inq_test_trace")


def test_trace_includes_delivery_refs(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault-delivery"
    vault.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3293"}]
    service.start(
        question="Trace delivery references",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_delivery",
        source_refs=refs,
    )
    synthesis = service.commit_synthesis(
        "inq_test_delivery",
        content="Issue proposal",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    readiness = service.commit_readiness(
        "inq_test_delivery",
        outcome="issue_ready",
        rationale="Canonical issue evidence is complete.",
        input_artifact_refs=["synthesis"],
        source_refs=refs,
    )
    service.commit_readiness_receipt("inq_test_delivery", source_refs=refs)
    marker = f"<!-- builderops-inquiry-promotion:inq_test_delivery:{'a' * 64} -->"
    intent = service.commit_promotion_intent(
        "inq_test_delivery",
        repository="example/repo",
        marker=marker,
        title="Trace delivery",
        issue_body=f"Canonical body\n{marker}",
        source_refs=refs,
    )
    service.commit_promotion_receipt(
        "inq_test_delivery",
        intent=intent,
        issue_number=700,
        issue_url="https://github.com/example/repo/issues/700",
        issue_created_at="2026-07-10T12:00:00Z",
        source_refs=refs,
    )
    for delivery_ref in (
        {
            "ref_type": "github_pull_request",
            "ref": "example/repo#701",
            "authority_surface": "github",
        },
        {"ref_type": "verification_receipt", "ref": "receipt-701"},
        {"ref_type": "owner_doc", "ref": "docs/STATUS.md"},
    ):
        service.commit_delivery_reference(
            "inq_test_delivery",
            delivery_ref=delivery_ref,
            source_refs=refs,
        )

    trace = service.trace("inq_test_delivery", include_delivery=True)

    assert trace["readiness"] == readiness
    assert trace["synthesis"] == synthesis
    assert trace["promotion_intent"] == intent
    assert trace["delivery_refs"] == [
        {
            "ref_type": "github_issue",
            "ref": "example/repo#700",
            "authority_surface": "github",
        },
        {
            "ref_type": "github_pull_request",
            "ref": "example/repo#701",
            "authority_surface": "github",
        },
        {"ref_type": "owner_doc", "ref": "docs/STATUS.md"},
        {"ref_type": "verification_receipt", "ref": "receipt-701"},
    ]

    promotion_path = (
        vault
        / "model-inquiries"
        / "inq_test_delivery"
        / "receipts"
        / "promotion-github-issue.json"
    )
    forged = json.loads(promotion_path.read_text(encoding="utf-8"))
    forged["github_issue_url"] = "https://attacker.example/issues/700"
    forged.pop("artifact_hash")
    forged["artifact_hash"] = canonical_hash(forged)
    promotion_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(BuilderOpsValidationError, match="promotion terminal receipt"):
        service.trace("inq_test_delivery", include_delivery=True)


def test_trace_rejects_tampered_derived_artifact(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Validate derived artifacts",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_tamper",
        source_refs=refs,
    )
    service.commit_synthesis(
        "inq_test_tamper",
        content="Original",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    path = vault / "model-inquiries" / "inq_test_tamper" / "synthesis.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content"] = "Tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BuilderOpsValidationError, match="synthesis content hash mismatch"):
        service.trace("inq_test_tamper")
    payload["content"] = "Original"
    path.write_text(json.dumps(payload), encoding="utf-8")

    turn = service.commit_turn(
        "inq_test_tamper",
        turn_id="turn-a",
        sequence=0,
        role="reviewer",
        content="Original turn",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    turn_path = vault / "model-inquiries" / "inq_test_tamper" / "turns" / "000000.json"
    turn["role"] = "tampered-role"
    turn_path.write_text(json.dumps(turn), encoding="utf-8")
    with pytest.raises(BuilderOpsValidationError, match="artifact hash mismatch"):
        service.trace("inq_test_tamper")


def test_receipt_parent_symlink_cannot_escape_vault(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3290"}]
    service.start(
        question="Stay confined",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_symlink",
        source_refs=refs,
    )
    service.commit_turn(
        "inq_test_symlink",
        turn_id="turn-a",
        sequence=0,
        role="reviewer",
        content="Committed",
        input_artifact_refs=["question"],
        source_refs=refs,
    )
    receipts = vault / "model-inquiries" / "inq_test_symlink" / "receipts"
    (receipts / "inquiry-started.json").unlink()
    receipts.rmdir()
    receipts.symlink_to(outside, target_is_directory=True)

    with pytest.raises(BuilderOpsValidationError, match="parent must not be a symlink"):
        service.commit_terminal_turn_receipt(
            "inq_test_symlink",
            turn_id="turn-a",
            outcome="accepted",
            source_refs=refs,
        )
    assert list(outside.iterdir()) == []


def test_trace_includes_provider_request_id_and_output_hash(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault-provider"
    vault.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3291"}]
    service.start(
        question="Trace provider provenance",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_provider_trace",
        source_refs=refs,
    )

    def response(stance: str, reviewed: list[str]) -> str:
        return json.dumps(
            {
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "stance": stance,
                "content": f"{stance} output",
                "claims": [],
                "risks": [],
                "blocking_questions": [],
                "reviewed_artifact_refs": reviewed,
                "accepted_artifact_hash": None,
            }
        )

    reviewed = ["draft-fable", "draft-gpt_codex"]
    adapters = {
        role: ScriptedAdapter(
            adapter_id=f"{role}-adapter",
            provider=role,
            model=f"{role}-model",
            responses=[response("draft", []), response("revise", reviewed)],
            calls=[],
        )
        for role in ("fable", "gpt_codex")
    }
    ModelInquiryRunner(service, adapters).run("inq_test_provider_trace", max_rounds=1)

    trace = ModelInquiryService(vault).trace("inq_test_provider_trace")
    provider_turns = [turn for turn in trace["turns"] if "adapter_request_id" in turn]
    assert len(provider_turns) == 4
    for turn in provider_turns:
        assert turn["adapter_request_id"].startswith("adapter_req_")
        assert turn["provider_request_id"].startswith("scripted-")
        assert len(turn["request_hash"]) == 64
        assert len(turn["context_hash"]) == 64
        assert len(turn["input_hash"]) == 64
        assert len(turn["output_hash"]) == 64
        assert turn["adapter_id"]
        assert turn["provider"]
        assert turn["model"]
        assert turn["source_refs"] == refs


def test_trace_recomputes_provider_context_and_request_hashes(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault-forged-provider"
    vault.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3291"}]
    trace = service.start(
        question="Reject forged provider lineage",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_forged_provider",
        source_refs=refs,
    )
    response = {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "stance": "draft",
        "content": "forged lineage",
        "claims": [],
        "risks": [],
        "blocking_questions": [],
        "reviewed_artifact_refs": [],
        "accepted_artifact_hash": None,
    }
    content = json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    input_hash = canonical_hash(
        [
            {
                "artifact_id": "question",
                "artifact_hash": trace["question"]["artifact_hash"],
            }
        ]
    )
    service.commit_turn(
        "inq_test_forged_provider",
        turn_id="draft-fable",
        sequence=0,
        role="fable",
        content=content,
        input_artifact_refs=["question"],
        source_refs=refs,
        provider_metadata={
            "adapter_request_id": f"adapter_req_{'1' * 32}",
            "provider_request_id": "request-safe",
            "adapter_id": "fable-adapter",
            "provider": "fable",
            "model": "fable-model",
            "context_hash": "0" * 64,
            "request_hash": "1" * 64,
            "input_hash": input_hash,
            "output_hash": canonical_hash(response),
            "phase": "draft",
            "round_index": 0,
            "stance": "draft",
            "accepted_artifact_hash": None,
        },
    )

    with pytest.raises(BuilderOpsValidationError, match="context hash mismatch"):
        service.trace("inq_test_forged_provider")


def test_trace_rejects_forged_canonical_run_terminal_receipt(tmp_path: Path) -> None:
    vault = tmp_path / "shared-vault-forged-terminal"
    vault.mkdir()
    service = ModelInquiryService(vault)
    refs = [{"ref_type": "github_issue", "ref": "#3291"}]
    service.start(
        question="Reject forged terminal receipt",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_forged_terminal",
        source_refs=refs,
    )
    occurred_at = "2026-07-10T12:00:00+00:00"
    receipt = normalize_record(
        {
            "id": "receipt_wrong",
            "object_type": "BuilderOpsReceipt",
            "summary": "Forged terminal",
            "event_type": "inquiry_run_terminal",
            "actor": {"actor_type": "agent", "id": "forger"},
            "occurred_at": occurred_at,
            "target_refs": [
                {
                    "ref_type": "builderops_inquiry",
                    "ref": "wrong-inquiry",
                    "authority_surface": "builderops",
                }
            ],
            "action": "issue_ready",
            "receipt_body": "Forged outcome.",
            "idempotency_key": "wrong-key",
            "source_refs": refs,
            "created_by": {"actor_type": "agent", "id": "forger"},
            "outcome": "issue_ready",
            "details": {},
            "created_at": occurred_at,
            "updated_at": occurred_at,
        }
    )
    receipt["artifact_hash"] = canonical_hash(receipt)
    path = (
        vault
        / "model-inquiries"
        / "inq_test_forged_terminal"
        / "receipts"
        / "aaa.json"
    )
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(BuilderOpsValidationError, match="invalid inquiry run terminal receipt"):
        service.trace("inq_test_forged_terminal")

    exact_vault = tmp_path / "shared-vault-false-consensus"
    exact_vault.mkdir()
    exact_service = ModelInquiryService(exact_vault)
    exact_service.start(
        question="Reject false consensus",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_false_consensus",
        source_refs=refs,
    )
    exact = normalize_record(
        {
            "id": "receipt_inq_test_false_consensus_run_terminal",
            "object_type": "BuilderOpsReceipt",
            "summary": "False consensus",
            "event_type": "inquiry_run_terminal",
            "actor": {"actor_type": "agent", "id": "forger"},
            "occurred_at": occurred_at,
            "target_refs": [
                {
                    "ref_type": "builderops_inquiry",
                    "ref": "inq_test_false_consensus",
                    "authority_surface": "builderops",
                }
            ],
            "action": "consensus",
            "receipt_body": "Structurally exact but false consensus.",
            "idempotency_key": "inquiry:inq_test_false_consensus:run:terminal",
            "source_refs": refs,
            "created_by": {"actor_type": "agent", "id": "forger"},
            "outcome": "consensus",
            "details": {},
            "created_at": occurred_at,
            "updated_at": occurred_at,
        }
    )
    exact["artifact_hash"] = canonical_hash(exact)
    exact_path = (
        exact_vault
        / "model-inquiries"
        / "inq_test_false_consensus"
        / "receipts"
        / "inquiry-run-terminal.json"
    )
    exact_path.write_text(json.dumps(exact), encoding="utf-8")
    with pytest.raises(BuilderOpsValidationError, match="invalid round_index"):
        exact_service.trace("inq_test_false_consensus")

    failure_vault = tmp_path / "shared-vault-false-failure"
    failure_vault.mkdir()
    failure_service = ModelInquiryService(failure_vault)
    failure_service.start(
        question="Reject false provider failure",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_false_failure",
        source_refs=refs,
    )
    details = {
        "adapter_request_id": "adapter_req_forged",
        "classification": "provider adapter execution failed",
    }
    target = [
        {
            "ref_type": "builderops_inquiry",
            "ref": "inq_test_false_failure",
            "authority_surface": "builderops",
        }
    ]
    attempt = normalize_record(
        {
            "id": "receipt_inq_test_false_failure_adapter_req_forged",
            "object_type": "BuilderOpsReceipt",
            "summary": "False provider attempt",
            "event_type": "inquiry_provider_attempt_terminal",
            "actor": {"actor_type": "agent", "id": "forger"},
            "occurred_at": occurred_at,
            "target_refs": target,
            "action": "provider_error",
            "receipt_body": "False attempt.",
            "idempotency_key": "inquiry:inq_test_false_failure:attempt:adapter_req_forged",
            "source_refs": refs,
            "created_by": {"actor_type": "agent", "id": "forger"},
            "adapter_request_id": "adapter_req_forged",
            "outcome": "provider_error",
            "details": details,
            "created_at": occurred_at,
            "updated_at": occurred_at,
        }
    )
    attempt["artifact_hash"] = canonical_hash(attempt)
    terminal = normalize_record(
        {
            "id": "receipt_inq_test_false_failure_run_terminal",
            "object_type": "BuilderOpsReceipt",
            "summary": "False run failure",
            "event_type": "inquiry_run_terminal",
            "actor": {"actor_type": "agent", "id": "forger"},
            "occurred_at": occurred_at,
            "target_refs": target,
            "action": "provider_error",
            "receipt_body": "False run failure.",
            "idempotency_key": "inquiry:inq_test_false_failure:run:terminal",
            "source_refs": refs,
            "created_by": {"actor_type": "agent", "id": "forger"},
            "outcome": "provider_error",
            "details": details,
            "created_at": occurred_at,
            "updated_at": occurred_at,
        }
    )
    terminal["artifact_hash"] = canonical_hash(terminal)
    receipts_dir = (
        failure_vault / "model-inquiries" / "inq_test_false_failure" / "receipts"
    )
    (receipts_dir / "attempt-adapter_req_forged.json").write_text(
        json.dumps(attempt), encoding="utf-8"
    )
    (receipts_dir / "inquiry-run-terminal.json").write_text(
        json.dumps(terminal), encoding="utf-8"
    )
    with pytest.raises(BuilderOpsValidationError, match="details do not match"):
        failure_service.trace("inq_test_false_failure")


def test_trace_never_contains_credential_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolved credential never reaches a durable turn, receipt, or report."""
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    source_refs = [{"ref_type": "github_issue", "ref": "#4291"}]
    service = ModelInquiryService(vault)
    service.start(
        question="Prove credential material stays out of durable state",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_credential_trace",
        source_refs=source_refs,
    )

    def post(url: str, **kwargs: object) -> object:
        headers = kwargs["headers"]
        assert isinstance(headers, dict)
        # The credential reaches the transport and nothing else.
        assert any(
            value in DECLARED_TEST_CREDENTIALS.values()
            for value in headers.values()
            if isinstance(value, str)
        ) or any(
            credential in str(value)
            for credential in DECLARED_TEST_CREDENTIALS.values()
            for value in headers.values()
        )
        body = kwargs["json"]
        assert isinstance(body, dict)
        request = json.loads(body["messages"][-1]["content"])
        if request["phase"] == "draft":
            text = _credential_trace_response("draft")
        else:
            text = _credential_trace_response(
                "accept",
                reviewed=list(request["reviewed_artifact_refs"]),
                accepted_hash=request["input_artifacts"][0]["artifact_hash"],
            )
        if "x-api-key" in headers:
            return _CredentialTraceResponse(
                {"content": [{"type": "text", "text": text}]},
                {"request-id": "req_anthropic_fixture"},
            )
        return _CredentialTraceResponse(
            {"choices": [{"message": {"content": text}}]},
            {"x-request-id": "resp_openai_fixture"},
        )

    monkeypatch.setattr("app.builderops.model_inquiry_adapters.requests.post", post)
    result = ModelInquiryRunner(
        service, env=provisioned_env(tmp_path / "secrets")
    ).run("inq_test_credential_trace", max_rounds=1)
    assert result["outcome"] == "consensus"

    trace = ModelInquiryService(vault).trace("inq_test_credential_trace")
    serialized = json.dumps(trace, sort_keys=True)
    durable = "".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in vault.rglob("*")
        if path.is_file()
    )
    for credential in DECLARED_TEST_CREDENTIALS.values():
        assert credential not in serialized
        assert credential not in durable
    for binding in DECLARED_TEST_CREDENTIALS:
        assert binding not in serialized
    assert all(turn["provider_request_id"] for turn in trace["turns"])

    # The credential-unavailable diagnostic keeps the logical identifier only.
    (tmp_path / "absent-vault").mkdir()
    absent_service = ModelInquiryService(tmp_path / "absent-vault")
    absent_service.start(
        question="Fail closed without a declared value",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_test_credential_absent",
        source_refs=source_refs,
    )
    absent = ModelInquiryRunner(absent_service, env=intent_env()).run(
        "inq_test_credential_absent", max_rounds=1
    )
    absent_trace = ModelInquiryService(tmp_path / "absent-vault").trace(
        "inq_test_credential_absent"
    )
    assert absent["details"]["diagnostic"]["credential_identity_ref"] == (
        "anthropic.api-key"
    )
    absent_serialized = json.dumps(absent_trace, sort_keys=True)
    for credential in DECLARED_TEST_CREDENTIALS.values():
        assert credential not in absent_serialized
    assert "ANTHROPIC_API_KEY" not in absent_serialized


class _CredentialTraceResponse:
    def __init__(self, payload: dict[str, object], headers: dict[str, str]) -> None:
        self._payload = payload
        self.headers = headers

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


def _credential_trace_response(
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
