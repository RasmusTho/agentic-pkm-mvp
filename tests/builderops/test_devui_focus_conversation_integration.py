"""Explicit contract composition, not a shipped UI journey or live acceptance.

The existing runtime serves Focus and the control plane builds inquiry proposals
independently; this test joins their real contracts without launching a workflow.
"""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.builderops import devui_sources
from app.builderops.devui_conversation_port import (
    ConversationPortContractError,
    canonical_context_pack_bytes,
    open_external_conversation,
    validate_context_pack_bytes,
    validate_conversation_disposition,
)
from app.builderops.devui_model_inquiry_command import (
    CommandContractError,
    build_command_proposal,
    validate_command_proposal,
)
from tests.builderops.inquiry_operation_fixture import InquiryGraph, REPOSITORY
from tests.builderops.test_devui_focus import _claim, _compose


@pytest.mark.parametrize("provider_state", ["unavailable", "unsupported", "refused"])
def test_correlated_partial_failure_boundary(provider_state: str, tmp_path, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    issue = {
        "number": 4696,
        "html_url": f"https://github.com/{REPOSITORY}/issues/4696",
        "title": "Exact inquiry subject",
        "state": "open",
        "body": "## Acceptance Criteria\n- [ ] Exact result. Verify: tests/example.py\n",
        "updated_at": now.isoformat(),
    }
    graph = InquiryGraph(tmp_path, monkeypatch)
    monkeypatch.setenv("DEVUI_GITHUB_ENABLED", "true")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(devui_sources.cockpit_github_plane, "_run_gh", lambda _: deepcopy(issue))
    preview = graph.preview(issue=issue)
    now = datetime.now(timezone.utc)
    material = preview["material"]
    pack = material["context_pack"]
    subject = deepcopy(pack["subject_ref"])
    source = _claim(
        "unavailable",
        claim=None,
        availability="unavailable",
        freshness="unknown",
        coverage="missing",
        cardinality="not_measured",
        linkage="not_assessed",
    )
    focus = _compose(subject=subject, evidence=[source])
    focus_before = deepcopy(focus)
    exact = canonical_context_pack_bytes(pack)
    digest = pack["content_hash"]
    calls = []

    def opener(payload, content_hash):
        calls.append((payload, content_hash))
        return {"provider_request_id": "unexpected"}

    result = open_external_conversation(
        pack_bytes=exact,
        expected_hash=digest,
        provider="fixture",
        availability=provider_state,
        reason="Fixture refusal",
        opener=opener,
        now=now,
    )
    assert result["state"] == provider_state and result["durable_effect"] is False
    assert calls == []
    assert focus == focus_before and focus["subject"] == subject
    assert focus["evidence"][0]["owner_state"] == "unavailable"
    assert pack["subject_ref"] == focus["subject"]
    assert canonical_context_pack_bytes(pack) == exact
    assert validate_context_pack_bytes(exact, now=now)["content_hash"] == digest

    with pytest.raises(ConversationPortContractError):
        open_external_conversation(
            pack_bytes=exact,
            expected_hash="0" * 64,
            provider="fixture",
            availability="available",
            reason="Wrong hash",
            opener=opener,
            now=now,
        )
    changed_pack = deepcopy(pack)
    changed_pack["subject_ref"]["stable_id"] = "github:other/repository#1"
    with pytest.raises(ConversationPortContractError):
        validate_context_pack_bytes(canonical_context_pack_bytes(changed_pack), now=now)

    disposition = {
        "contract_version": "conversation-disposition.v1",
        "context_hash": digest,
        "outcome": "plan",
        "rationale": "Reason only",
        "source_refs": pack["source_refs"],
        "limitations": pack["limitations"],
        "provenance": {"provider": "fixture"},
        "proposed_command": None,
    }
    accepted = validate_conversation_disposition(disposition, expected_context_hash=digest)
    assert accepted["authority"] == "provenance_only" and accepted["durable_effect"] is False
    for invalid in ({**disposition, "context_hash": "0" * 64}, {**disposition, "execute": True}):
        with pytest.raises(ConversationPortContractError):
            validate_conversation_disposition(invalid, expected_context_hash=digest)

    proposal = preview["proposal"]
    rule = proposal["approval_rule"]
    identity = dict(
        owner_principal=rule["authenticated_principal_ref"],
        permission_ref=rule["permission_ref"],
        permission_version=rule["permission_version"],
        authority_epoch=rule["authority_epoch"],
    )
    assert (
        build_command_proposal(
            approval_id=proposal["proposal_id"],
            material=material,
            now=datetime.fromisoformat(proposal["freshness"]["created_at"]),
            expires_at=datetime.fromisoformat(proposal["freshness"]["expires_at"]),
            **identity,
        )
        == proposal
    )
    assert proposal["subject_ref"] == subject
    assert proposal["context_pack_ref"]["content_hash"] == digest
    assert (
        validate_command_proposal(proposal, current_material=material, now=now, **identity)
        == proposal
    )
    changed = deepcopy(material)
    changed["question"] += "Changed after preview."
    with pytest.raises(CommandContractError):
        validate_command_proposal(proposal, current_material=changed, now=now, **identity)
    wrong_subject = deepcopy(material)
    wrong_subject["issue_number"] = 1
    with pytest.raises(CommandContractError):
        validate_command_proposal(proposal, current_material=wrong_subject, now=now, **identity)
    changed_preview = deepcopy(preview)
    changed_preview["material"] = changed
    assert graph.start(changed_preview).status_code == 400
    assert graph.reserves == 0 and graph.launches == 0 and not graph.provider.calls
    assert calls == [] and focus == focus_before
