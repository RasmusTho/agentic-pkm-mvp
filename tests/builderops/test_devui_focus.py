"""Contract tests for the subject-centred devUI Focus projection (#4694)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.builderops.devui_focus import FocusContractError, compose_focus_view


NOW = datetime(2026, 8, 9, 13, 0, tzinfo=timezone.utc)
ISSUE_REF = {
    "kind": "issue",
    "stable_id": "github:RasmusTho/agentic-pkm-mvp#4694",
    "authority_ref": {
        "source_type": "github_issue",
        "source_id": "RasmusTho/agentic-pkm-mvp#4694",
        "version": "updated-at:2026-08-09T12:57:38Z",
        "locator": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4694",
    },
    "title": "Compose subject-centred Focus",
}
CAPABILITY_REF = {
    "kind": "capability",
    "stable_id": "ckm_capability_devui_focus",
    "authority_ref": {
        "source_type": "owner_document",
        "source_id": "docs/DEVUI.md#DEVUI-FCP-BOUNDARY",
        "content_hash": "a" * 64,
        "locator": "docs/DEVUI.md#devui-fcp-boundary--focus-and-conversation-port",
    },
    "title": "devUI Focus",
}


def _source_ref(source_id: str, *, source_type: str = "owner_document") -> dict:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "content_hash": "b" * 64,
        "locator": source_id,
    }


def _claim(
    claim_id: str,
    *,
    claim: str | None = "Supported subject claim",
    availability: str = "available",
    freshness: str = "fresh",
    coverage: str = "complete",
    cardinality: str = "nonempty",
    linkage: str = "linked",
    read_watermark: str | None = None,
) -> dict:
    result = {
        "claim_id": claim_id,
        "claim": claim,
        "source_ref": _source_ref(f"docs/example.md#{claim_id}"),
        "availability": availability,
        "freshness": freshness,
        "coverage": coverage,
        "cardinality": cardinality,
        "linkage": linkage,
        "captured_at": "2026-08-09T12:59:00+00:00",
        "limitation": None if claim is not None else f"{claim_id} is not claim-supporting",
    }
    if read_watermark is not None:
        result["read_watermark"] = read_watermark
    return result


def _observation(*, status: str = "linked", method: str = "explicit_receipt") -> dict:
    return {
        "observation_ref": "builderops:receipt:receipt-4694",
        "observed_at": "2026-08-09T12:58:00+00:00",
        "provider": "codex",
        "summary": "Session text mentions #4694 on the same branch and minute.",
        "source_ref": _source_ref(
            "builderops:receipt:receipt-4694", source_type="builderops_receipt"
        ),
        "correlation": {
            "status": status,
            "method": method,
            "authority_ref": (
                deepcopy(ISSUE_REF["authority_ref"])
                if status == "linked"
                else None
            ),
        },
    }


def _receipt() -> dict:
    return {
        "receipt_ref": "builderops:receipt:receipt-4694",
        "source_ref": _source_ref(
            "builderops:receipt:receipt-4694", source_type="builderops_receipt"
        ),
        "correlation": {
            "status": "linked",
            "method": "explicit_receipt",
            "authority_ref": deepcopy(ISSUE_REF["authority_ref"]),
        },
    }


def _compose(**overrides: object) -> dict:
    values: dict[str, object] = {
        "subject": ISSUE_REF,
        "owner_intent": {
            "summary": "Deliver the bounded read-only Focus contract.",
            "source_ref": _source_ref(
                "docs/DEVUI_FOCUS_CONVERSATION_PORT/COMPOSE_SUBJECT_CENTRED_FOCUS.md"
            ),
        },
        "governing_sources": [_claim("governing")],
        "evidence": [_claim("evidence")],
        "receipts": [],
        "risks": [],
        "next_legal_step": {
            "workflow_ref": "issue-to-code",
            "actor_class": "agent",
            "legality": "legal",
            "reason": "The strictly validated Issue is claimed.",
        },
        "execution_observations": [_observation()],
        "conversation_port": {
            "availability": "unsupported",
            "reason": "Not part of FCP-01",
        },
        "limitations": [],
        "now": lambda: NOW,
    }
    values.update(overrides)
    if "execution_observations" not in overrides:
        observation = _observation()
        selected_subject = values["subject"]
        assert isinstance(selected_subject, dict)
        observation["correlation"]["authority_ref"] = deepcopy(
            selected_subject["authority_ref"]
        )
        values["execution_observations"] = [observation]
    return compose_focus_view(**values)  # type: ignore[arg-type]


def test_focus_accepts_only_governed_issue_or_capability_subjects() -> None:
    issue = _compose(subject=ISSUE_REF)
    capability = _compose(subject=CAPABILITY_REF)

    assert issue["subject"]["stable_id"] == ISSUE_REF["stable_id"]
    assert capability["subject"]["stable_id"] == CAPABILITY_REF["stable_id"]

    for kind in ("provider_session", "transcript", "pull_request", "worker", "free_form"):
        invalid = {**ISSUE_REF, "kind": kind}
        with pytest.raises(FocusContractError, match="governed Issue or capability"):
            _compose(subject=invalid)


def test_linked_evidence_must_match_selected_subject() -> None:
    matching_observation = _observation()
    matching_receipt = _receipt()

    result = _compose(
        execution_observations=[matching_observation], receipts=[matching_receipt]
    )

    assert result["execution_observations"] == [matching_observation]
    assert result["receipts"] == [matching_receipt]

    mismatched_issue = deepcopy(ISSUE_REF["authority_ref"])
    mismatched_issue["source_id"] = "RasmusTho/agentic-pkm-mvp#9999"
    mismatched_issue["locator"] = (
        "https://github.com/RasmusTho/agentic-pkm-mvp/issues/9999"
    )
    mismatched_observation = _observation()
    mismatched_observation["correlation"]["authority_ref"] = mismatched_issue
    mismatched_observation_result = _compose(
        execution_observations=[mismatched_observation]
    )
    assert mismatched_observation_result["execution_observations"] == []
    assert any(
        item["kind"] == "unlinked_execution_observation"
        and item["observation_ref"] == mismatched_observation["observation_ref"]
        for item in mismatched_observation_result["limitations"]
    )

    mismatched_receipt = _receipt()
    mismatched_receipt["correlation"]["authority_ref"] = mismatched_issue
    mismatched_receipt_result = _compose(receipts=[mismatched_receipt])
    assert mismatched_receipt_result["receipts"] == []
    assert any(
        item["kind"] == "unlinked_receipt"
        and item["receipt_ref"] == mismatched_receipt["receipt_ref"]
        for item in mismatched_receipt_result["limitations"]
    )

    provider_authority = _source_ref(
        "codex:transcript:unrelated", source_type="provider_transcript"
    )
    provider_observation = _observation()
    provider_observation["correlation"]["authority_ref"] = provider_authority
    provider_result = _compose(execution_observations=[provider_observation])
    assert provider_result["execution_observations"] == []
    assert provider_result["state"] == "focus_partial"

    unrelated_authority = _source_ref(
        "docs/UNRELATED.md#other-subject", source_type="owner_document"
    )
    unrelated_receipt = _receipt()
    unrelated_receipt["correlation"]["authority_ref"] = unrelated_authority
    unrelated_result = _compose(receipts=[unrelated_receipt])
    assert unrelated_result["receipts"] == []
    assert unrelated_result["limitations"][0]["kind"] == "unlinked_receipt"

    missing_authority = _observation()
    missing_authority["correlation"]["authority_ref"] = None
    with pytest.raises(FocusContractError, match="linked observation requires"):
        _compose(execution_observations=[missing_authority])


def test_capability_subject_requires_owner_document_authority() -> None:
    result = _compose(subject=CAPABILITY_REF)
    assert result["subject"]["authority_ref"]["source_type"] == "owner_document"

    ckm_only = deepcopy(CAPABILITY_REF)
    ckm_only["authority_ref"] = _source_ref(
        "ckm:capability:devui-focus", source_type="ckm_capability"
    )
    with pytest.raises(
        FocusContractError, match="capability subject requires owner-document authority"
    ):
        _compose(subject=ckm_only)


def test_focus_preserves_independent_evidence_axes() -> None:
    claims = [
        _claim("fresh-complete"),
        _claim(
            "measured-empty",
            claim="No receipts exist in the measured subject scope.",
            cardinality="measured_empty",
            read_watermark="receipt-seq:42",
        ),
        _claim(
            "stale-partial",
            claim=None,
            freshness="stale",
            coverage="partial",
            cardinality="not_measured",
            linkage="not_assessed",
        ),
    ]

    result = _compose(evidence=claims)

    assert [
        {
            key: claim[key]
            for key in (
                "availability",
                "freshness",
                "coverage",
                "cardinality",
                "linkage",
            )
        }
        for claim in result["evidence"]
    ] == [
        {
            key: claim[key]
            for key in (
                "availability",
                "freshness",
                "coverage",
                "cardinality",
                "linkage",
            )
        }
        for claim in claims
    ]
    assert result["evidence"][1]["read_watermark"] == "receipt-seq:42"
    assert result["evidence"][0]["captured_at"] == claims[0]["captured_at"]
    assert result["evidence"][0]["source_ref"] == claims[0]["source_ref"]


def test_focus_never_infers_execution_correlation() -> None:
    linked = _observation(status="linked", method="explicit_receipt")
    unlinked = _observation(status="unlinked", method="none")
    unlinked["source_ref"] = _source_ref(
        "codex:session:unlinked-4694", source_type="provider_session"
    )

    result = _compose(execution_observations=[linked, unlinked])

    assert result["execution_observations"] == [linked]
    limitation = next(
        item
        for item in result["limitations"]
        if item["kind"] == "unlinked_execution_observation"
    )
    assert limitation["observation_ref"] == unlinked["observation_ref"]
    assert limitation["linkage"] == "unlinked"
    assert result["next_legal_step"]["workflow_ref"] == "issue-to-code"


def test_focus_distinguishes_required_source_states() -> None:
    claims = [
        _claim(
            "unavailable",
            claim=None,
            availability="unavailable",
            freshness="unknown",
            coverage="missing",
            cardinality="not_measured",
            linkage="not_assessed",
        ),
        _claim(
            "unread",
            claim=None,
            coverage="unread",
            cardinality="not_measured",
            linkage="not_assessed",
        ),
        _claim(
            "unsupported",
            claim=None,
            availability="unsupported",
            freshness="unknown",
            coverage="not_applicable",
            cardinality="not_countable",
            linkage="not_applicable",
        ),
        _claim(
            "unlinked",
            claim=None,
            cardinality="not_measured",
            linkage="unlinked",
        ),
        _claim(
            "missing",
            claim=None,
            coverage="missing",
            cardinality="not_measured",
            linkage="not_assessed",
        ),
        _claim(
            "measured-empty",
            claim="No matching evidence exists in the measured scope.",
            cardinality="measured_empty",
            read_watermark="evidence-seq:0",
        ),
    ]

    result = _compose(evidence=claims)

    assert [claim["owner_state"] for claim in result["evidence"]] == [
        "unavailable",
        "unread",
        "unsupported",
        "unlinked",
        "missing",
        "measured_empty",
    ]


def test_focus_composition_adds_no_store_or_effect() -> None:
    subject = deepcopy(ISSUE_REF)
    evidence = [_claim("evidence")]
    original_subject = deepcopy(subject)
    original_evidence = deepcopy(evidence)

    first = _compose(subject=subject, evidence=evidence)
    second = _compose(subject=CAPABILITY_REF, evidence=[])

    assert subject == original_subject
    assert evidence == original_evidence
    assert first["contract_version"] == "focus-view.v1"
    assert first["authority"] == "projection_only"
    assert first["composed_at"] == NOW.isoformat()
    assert second["subject"]["stable_id"] == CAPABILITY_REF["stable_id"]
    assert first["subject"]["stable_id"] != second["subject"]["stable_id"]
    assert "store" not in first
    assert "effects" not in first

    hostile = _claim("hostile")
    hostile["effects"] = [{"type": "github_mutation"}]
    with pytest.raises(FocusContractError, match="unknown field"):
        _compose(evidence=[hostile])

    non_string_key = _claim("non-string-key")
    non_string_key[7] = "silently coerced by permissive JSON"  # type: ignore[index]
    with pytest.raises(FocusContractError, match="string keys"):
        _compose(evidence=[non_string_key])


def test_focus_rejects_semantically_inconsistent_claims() -> None:
    unlinked_support = _claim("bad-link", linkage="unlinked")
    with pytest.raises(FocusContractError, match="unlinked evidence cannot support"):
        _compose(evidence=[unlinked_support])

    empty_without_watermark = _claim(
        "bad-empty",
        cardinality="measured_empty",
    )
    with pytest.raises(FocusContractError, match="measured_empty requires"):
        _compose(evidence=[empty_without_watermark])

    with pytest.raises(FocusContractError, match="legal next step requires"):
        _compose(
            next_legal_step={
                "workflow_ref": None,
                "actor_class": "agent",
                "legality": "legal",
                "reason": "Missing workflow",
            }
        )

    provider_claim = _claim("provider-authority")
    provider_claim["source_ref"] = _source_ref(
        "claude:transcript:4694", source_type="provider_transcript"
    )
    with pytest.raises(FocusContractError, match="provenance only"):
        _compose(evidence=[provider_claim])

    provider_governance = _claim("provider-governance", claim=None)
    provider_governance["source_ref"] = _source_ref(
        "codex:session:4694", source_type="provider_session"
    )
    with pytest.raises(FocusContractError, match="cannot use.*as authority"):
        _compose(governing_sources=[provider_governance])

    with pytest.raises(FocusContractError, match="linked observation requires"):
        _compose(execution_observations=[_observation(status="linked", method="none")])
