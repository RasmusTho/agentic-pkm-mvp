from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from app.builderops.design_run_contract import (
    ContractIdentityRef,
    CuratedDesignBrief,
    DesignAgentHandoffOutput,
    DesignAgentDescriptor,
    DesignHandoffRef,
    DesignRunAdmission,
    DesignRunApprovalEvidence,
    DesignRunPolicyProfile,
    DesignRunRefusalDetail,
    DesignRunRequest,
    DesignRunResult,
    DesignRunStatus,
    DesignSourceRef,
    DigestBoundAttachmentRef,
    YggdrasilGateReceipt,
    contract_ref,
    parse_design_agent_handoff_output,
    validate_admission_bindings,
    validate_approval_bindings,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
TS = "2026-07-29T10:00:00Z"


def _source(source_id: str = "ckm:observation:one") -> DesignSourceRef:
    return DesignSourceRef(source_type="ckm_observation", source_id=source_id, content_hash=SHA_A)


def _attachment(attachment_id: str = "attachment.one") -> DigestBoundAttachmentRef:
    return DigestBoundAttachmentRef(attachment_id=attachment_id, media_type="image/png", content_hash=SHA_B)


def _receipt() -> YggdrasilGateReceipt:
    return YggdrasilGateReceipt(
        receipt_id="receipt.yggdrasil.one",
        system_name="Yggdrasil",
        system_id="yggdrasil.design.system",
        selection_mechanism="explicit_attachment",
        repo_token_source="companion-ui/design_tokens.css",
        live_token_hash=SHA_C,
        repo_token_hash=SHA_C,
        parity_passed=True,
        verified_at=TS,
        expires_at="2026-07-29T11:00:00Z",
        preview_refs=(_attachment(),),
    )


def _brief(*, visual: bool = True) -> CuratedDesignBrief:
    return CuratedDesignBrief(
        brief_id="brief.design.one",
        projection_id="ckm.projection.one",
        requested_deliverable="visual_handoff" if visual else "interaction_specification",
        source_refs=(_source(),),
        attachment_refs=(_attachment(),),
        constraints=("Use explicit evidence only.",),
        yggdrasil_gate_receipt=_receipt() if visual else None,
        non_visual_exemption=None if visual else True,
    )


def _adapter() -> DesignAgentDescriptor:
    return DesignAgentDescriptor(
        descriptor_id="adapter.claude.design",
        display_name="Claude Design",
        role_profile_id="design.claude",
        supported_deliverables=("interaction_specification", "visual_handoff"),
        descriptor_revision="v1",
    )


def _policy() -> DesignRunPolicyProfile:
    return DesignRunPolicyProfile(
        profile_id="design.policy.local",
        profile_version="v1",
        allowed_deliverables=("interaction_specification", "visual_handoff"),
        max_source_refs=4,
        max_attachment_refs=2,
        approval_required=True,
        visual_yggdrasil_receipt_required=True,
    )


def _request(brief: CuratedDesignBrief, adapter: DesignAgentDescriptor, policy: DesignRunPolicyProfile) -> DesignRunRequest:
    return DesignRunRequest(
        request_id="request.design.one",
        brief_ref=contract_ref(brief, brief.brief_id),
        adapter_ref=contract_ref(adapter, adapter.descriptor_id),
        policy_ref=contract_ref(policy, policy.profile_id),
        requested_at=TS,
    )


def test_curated_brief_is_bounded_provenanced_and_deterministic() -> None:
    first = _brief()
    assert first.content_hash == _brief().content_hash
    with pytest.raises(ValidationError, match="canonical sorted"):
        CuratedDesignBrief(**(_brief().model_dump() | {"source_refs": (_source("ckm:observation:z"), _source())}))
    with pytest.raises(ValidationError, match="explicit exemption"):
        CuratedDesignBrief(**(_brief(visual=False).model_dump() | {"non_visual_exemption": None}))
    with pytest.raises(ValidationError, match="Yggdrasil gate receipt"):
        CuratedDesignBrief(**(_brief().model_dump() | {"yggdrasil_gate_receipt": None}))
    with pytest.raises(ValidationError, match="ambient"):
        DesignSourceRef(source_type="repo_document", source_id="whole-repo", content_hash=SHA_A)


def test_design_agent_handoff_output_requires_structured_digest_bound_ref() -> None:
    content = "bounded design artifact"
    handoff = DesignHandoffRef(
        handoff_id="run.design.one.handoff",
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source_refs=(_source(),),
        adapter_ref=contract_ref(_adapter(), "adapter.claude.design"),
        run_id="run.design.one",
        receipt_ref=ContractIdentityRef(
            schema_version="builderops.design-run-receipt-event.v1",
            contract_id="receipt.design.one",
            content_hash=SHA_B,
        ),
        limitations=(
            "Unaccepted Builder material; governed promotion is required.",
        ),
        produced_at=TS,
    )
    output = DesignAgentHandoffOutput(
        artifact_content=content,
        handoff=handoff,
    )

    assert (
        parse_design_agent_handoff_output(
            json.dumps(output.model_dump(mode="json"))
        )
        == output
    )
    with pytest.raises(ValidationError, match="content digest"):
        DesignAgentHandoffOutput(
            artifact_content=f"{content} changed",
            handoff=handoff,
        )
    with pytest.raises(ValidationError, match="content digest"):
        DesignAgentHandoffOutput(
            artifact_content=f" {content} ",
            handoff=handoff,
        )
    padded_binding = output.model_dump(mode="json")
    padded_binding["handoff"]["handoff_id"] = (
        f" {handoff.handoff_id} "
    )
    with pytest.raises(ValueError, match="exact canonical bindings"):
        parse_design_agent_handoff_output(
            json.dumps(padded_binding)
        )
    with pytest.raises(ValueError, match="one JSON object"):
        parse_design_agent_handoff_output("provider prose")


def test_admission_and_approval_bind_the_exact_request() -> None:
    brief, adapter, policy = _brief(), _adapter(), _policy()
    request = _request(brief, adapter, policy)
    admission = DesignRunAdmission(
        admission_id="admission.design.one", request_ref=contract_ref(request, request.request_id),
        brief_ref=contract_ref(brief, brief.brief_id), adapter_ref=contract_ref(adapter, adapter.descriptor_id),
        policy_ref=contract_ref(policy, policy.profile_id), evaluated_at=TS, outcome="approval_required",
        repo_token_hash_observed=SHA_C,
        refusal=DesignRunRefusalDetail(code="approval_pending", public_message="Operator approval is required.", retryable=False),
    )
    validate_admission_bindings(admission, request=request, brief=brief, adapter=adapter, policy=policy, current_repo_token_hash=SHA_C)
    approval = DesignRunApprovalEvidence(
        approval_id="approval.design.one", request_ref=contract_ref(request, request.request_id),
        admission_ref=contract_ref(admission, admission.admission_id), brief_ref=contract_ref(brief, brief.brief_id),
        adapter_ref=contract_ref(adapter, adapter.descriptor_id), policy_ref=contract_ref(policy, policy.profile_id),
        approved_at=TS, state="approved",
    )
    validate_approval_bindings(approval, request=request, admission=admission, brief=brief, adapter=adapter, policy=policy)
    with pytest.raises(ValueError, match="exact contract"):
        validate_admission_bindings(admission, request=request, brief=_brief(visual=False), adapter=adapter, policy=policy)


def test_visual_deliverables_bind_current_yggdrasil_gate_receipt() -> None:
    brief, adapter, policy = _brief(), _adapter(), _policy()
    request = _request(brief, adapter, policy)
    admission = DesignRunAdmission(
        admission_id="admission.visual.one", request_ref=contract_ref(request, request.request_id),
        brief_ref=contract_ref(brief, brief.brief_id), adapter_ref=contract_ref(adapter, adapter.descriptor_id),
        policy_ref=contract_ref(policy, policy.profile_id), evaluated_at=TS, outcome="allow",
        repo_token_hash_observed=SHA_C,
    )
    validate_admission_bindings(admission, request=request, brief=brief, adapter=adapter, policy=policy, current_repo_token_hash=SHA_C)
    with pytest.raises(ValueError, match="token hash drifted"):
        validate_admission_bindings(admission, request=request, brief=brief, adapter=adapter, policy=policy, current_repo_token_hash=SHA_A)
    with pytest.raises(ValueError, match="observed repo token hash"):
        validate_admission_bindings(
            admission.model_copy(
                update={"repo_token_hash_observed": SHA_A}
            ),
            request=request,
            brief=brief,
            adapter=adapter,
            policy=policy,
            current_repo_token_hash=SHA_C,
        )
    non_visual = _brief(visual=False)
    non_visual_request = _request(non_visual, adapter, policy)
    non_visual_admission = admission.model_copy(
        update={
            "admission_id": "admission.nonvisual.one",
            "request_ref": contract_ref(
                non_visual_request,
                non_visual_request.request_id,
            ),
            "brief_ref": contract_ref(
                non_visual,
                non_visual.brief_id,
            ),
            "repo_token_hash_observed": SHA_C,
        }
    )
    with pytest.raises(ValueError, match="must not bind"):
        validate_admission_bindings(
            non_visual_admission,
            request=non_visual_request,
            brief=non_visual,
            adapter=adapter,
            policy=policy,
        )
    assert _brief(visual=False).non_visual_exemption is True


def test_result_and_refusal_contracts_are_closed_and_secret_safe() -> None:
    with pytest.raises(ValidationError, match="secret"):
        DesignRunRefusalDetail(code="execution_failed", public_message="api_key leaked", retryable=False)
    with pytest.raises(ValidationError, match="invalid design-run status transition"):
        DesignRunStatus(run_id="run.design.one", previous_state="succeeded", state="running", observed_at=TS)
    with pytest.raises(ValidationError, match="requires refusal"):
        DesignRunResult(result_id="result.design.one", run_id="run.design.one", request_ref=contract_ref(_brief(), "brief.design.one"), final_status="failed", completed_at=TS)
    with pytest.raises(ValidationError, match="Extra inputs"):
        DesignRunStatus(run_id="run.design.one", state="unknown", observed_at=TS, raw_stderr="no")
    assert DesignRunStatus(run_id="run.design.one", state="unknown", observed_at=TS).state == "unknown"
