"""Contract tests for the pure devUI Overview projection (#4715)."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.builderops.devui_overview import (
    CONTRACT_VERSION,
    OverviewContractError,
    compose_overview_view,
)


def _source(name: str) -> dict[str, str]:
    return {
        "source_type": "github_issue",
        "source_id": name,
        "version": "updated-at:2026-08-09T21:00:00+00:00",
        "locator": f"https://example.test/{name}",
    }


def _composition() -> dict:
    return {
        "contract_version": "devui.composition.v1",
        "authority": "projection_only",
        "captured_at": "2026-08-09T21:00:00+00:00",
        "providers": {
            "work": {
                "provider": "builderops_cockpit",
                "status": "available",
                "authority": "read_time_join",
                "captured_at": "2026-08-09T21:00:00+00:00",
                "snapshot": {"watermark": "work:42"},
                "completeness": {"claim": {"kind": "counted"}},
                "refusal": None,
            },
            "capabilities": {
                "provider": "ckm",
                "status": "refused",
                "authority": "projection_marker",
                "captured_at": None,
                "snapshot": None,
                "completeness": None,
                "refusal": {"code": "unavailable"},
            },
        },
    }


def _evidence(
    evidence_id: str,
    *,
    claim: str | None = "The source supports this claim.",
    availability: str = "available",
    freshness: str = "fresh",
    completeness: str = "complete",
    cardinality: str = "nonempty",
    linkage: str = "linked",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "claim": claim,
        "source_ref": _source(f"source-{evidence_id}"),
        "availability": availability,
        "freshness": freshness,
        "completeness": completeness,
        "cardinality": cardinality,
        "linkage": linkage,
        "captured_at": "2026-08-09T21:00:00+00:00",
        "read_watermark": None,
        "limitation": None if claim is not None else "The source cannot support this claim.",
    }


def _candidate(*, evidence: list[dict] | None = None) -> dict:
    return {
        "subject_ref": _source("RasmusTho/agentic-pkm-mvp#4715"),
        "reason": "The server-declared reason for this placement.",
        "evidence": evidence or [_evidence("authority"), _evidence("ready")],
        "owner_authority": {
            "category": "contradictory_source_authority",
            "governing_source": _source("RasmusTho/agentic-pkm-mvp#4715"),
            "evidence_id": "authority",
        },
        "delivery_facts": {
            "merged": {"state": "evidenced", "source_ref": _source("merge"), "evidence_id": "ready"},
            "delivery": {"state": "evidenced", "source_ref": _source("delivery"), "evidence_id": "ready"},
            "availability": {"state": "evidenced", "source_ref": _source("availability"), "evidence_id": "ready"},
            "issue_closure": {"state": "evidenced", "source_ref": _source("closure"), "evidence_id": "ready"},
            "ready_to_try": {
                "state": "evidenced",
                "source_ref": _source("ready"),
                "receipt_ref": _source("receipt-ready"),
                "evidence_id": "ready",
            },
            "owner_trial": {"state": "unknown", "source_ref": _source("trial"), "evidence_id": "ready"},
            "owner_acceptance": {"state": "unknown", "source_ref": _source("acceptance"), "evidence_id": "ready"},
        },
        "navigation_refs": [],
        "limitations": [],
    }


def test_overview_production_composer_is_projection_only_and_has_no_io_or_state_path() -> None:
    composition = _composition()
    candidates = {"now": [_candidate()]}

    result = compose_overview_view(composition=composition, candidates=candidates)

    assert result["contract_version"] == CONTRACT_VERSION
    assert result["authority"] == "projection_only"
    assert result["composed_at"] == composition["captured_at"]
    assert result["trust_frame"]["provider_states"][0]["role"] == "work"
    assert result["trust_frame"]["provider_states"][0]["provider"] == "builderops_cockpit"
    assert result["trust_frame"]["provider_states"][0]["authority"] == "read_time_join"
    assert result["trust_frame"]["provider_states"][0]["snapshot"] == {"watermark": "work:42"}
    assert result["now"][0]["subject_ref"] == candidates["now"][0]["subject_ref"]
    assert "cache" not in result
    assert "store" not in result
    assert "effects" not in result
    assert composition == _composition()

    missing_identity = _composition()
    del missing_identity["providers"]["work"]["authority"]
    with pytest.raises(OverviewContractError, match="missing fields"):
        compose_overview_view(composition=missing_identity)


def test_overview_without_producer_candidates_withdraws_owner_and_ready_classifications() -> None:
    result = compose_overview_view(composition=_composition())

    assert result["now"] == []
    assert result["needs_you"] == []
    assert result["ready_to_try"] == []
    assert {(item["zone"], item["reason"]) for item in result["limitations"]} == {
        ("needs_you", "the producer supplied no actionable classification evidence"),
        ("ready_to_try", "the producer supplied no actionable classification evidence"),
    }

    empty = compose_overview_view(
        composition=_composition(), candidates={"needs_you": [], "ready_to_try": []}
    )
    assert {(item["zone"], item["reason"]) for item in empty["limitations"]} == {
        ("needs_you", "the producer supplied no actionable classification evidence"),
        ("ready_to_try", "the producer supplied no actionable classification evidence"),
    }


def test_needs_you_requires_named_owner_authority_and_withdraws_on_degraded_evidence() -> None:
    good = _candidate()
    missing = _candidate()
    missing.pop("owner_authority")
    unknown = _candidate()
    unknown["owner_authority"]["category"] = "ci_failure"
    stale = _candidate()
    stale["evidence"][0]["freshness"] = "stale"
    stale["evidence"][0]["claim"] = None
    stale["evidence"][0]["limitation"] = "authority source is stale"

    result = compose_overview_view(
        composition=_composition(), candidates={"needs_you": [good, missing, unknown, stale]}
    )

    assert result["needs_you"] == [good]
    withdrawals = [item for item in result["limitations"] if item["zone"] == "needs_you"]
    assert len(withdrawals) == 3
    assert all(item["kind"] == "classification_withdrawn" for item in withdrawals)


@pytest.mark.parametrize(
    "category",
    (
        "irreversible_external_effect",
        "security_privacy_cost_commitment",
        "production_release_operator_action",
        "contradictory_source_authority",
    ),
)
def test_needs_you_accepts_each_canonical_owner_authority_category(category: str) -> None:
    candidate = _candidate()
    candidate["owner_authority"]["category"] = category

    result = compose_overview_view(
        composition=_composition(), candidates={"needs_you": [candidate]}
    )

    assert result["needs_you"] == [candidate]


def test_ready_to_try_requires_receipt_backed_fact_and_preserves_delivery_axes() -> None:
    ready = _candidate()
    merged_only = _candidate()
    merged_only["delivery_facts"]["ready_to_try"] = {
        "state": "unknown",
        "source_ref": _source("ready"),
        "evidence_id": "ready",
    }

    result = compose_overview_view(
        composition=_composition(), candidates={"ready_to_try": [ready, merged_only]}
    )

    assert result["ready_to_try"] == [ready]
    facts = result["ready_to_try"][0]["delivery_facts"]
    assert set(facts) == {
        "merged",
        "delivery",
        "availability",
        "issue_closure",
        "ready_to_try",
        "owner_trial",
        "owner_acceptance",
    }
    assert facts["merged"]["state"] == "evidenced"
    assert facts["delivery"]["state"] == "evidenced"
    assert facts["availability"]["state"] == "evidenced"
    assert facts["issue_closure"]["state"] == "evidenced"
    assert facts["ready_to_try"]["receipt_ref"] == _source("receipt-ready")
    assert facts["owner_trial"]["state"] == "unknown"
    assert facts["owner_acceptance"]["state"] == "unknown"
    assert any(item["zone"] == "ready_to_try" for item in result["limitations"])


def test_evidenced_delivery_fact_requires_resolving_evidence() -> None:
    candidate = _candidate()
    candidate["delivery_facts"]["merged"]["evidence_id"] = "missing"

    with pytest.raises(OverviewContractError, match="evidenced fact requires source evidence"):
        compose_overview_view(
            composition=_composition(), candidates={"now": [candidate]}
        )

    unsupported = _candidate()
    unsupported["evidence"].append(
        _evidence(
            "unsupported",
            claim=None,
            availability="refused",
            freshness="unknown",
            completeness="unread",
            cardinality="not_measured",
            linkage="unlinked",
        )
    )
    unsupported["delivery_facts"]["merged"]["evidence_id"] = "unsupported"
    with pytest.raises(OverviewContractError, match="evidenced fact requires actionable"):
        compose_overview_view(
            composition=_composition(), candidates={"now": [unsupported]}
        )


def test_overview_preserves_exact_withdrawals_and_independent_evidence_axes() -> None:
    candidate = _candidate(
        evidence=[
            _evidence("authority"),
            _evidence("ready"),
            _evidence(
                "withdrawn",
                claim=None,
                availability="refused",
                freshness="unknown",
                completeness="unread",
                cardinality="not_measured",
                linkage="unlinked",
            ),
            {
                **_evidence("empty", claim="Measured no items.", cardinality="measured_empty"),
                "read_watermark": "receipt-seq:0",
            },
        ]
    )

    result = compose_overview_view(composition=_composition(), candidates={"now": [candidate]})

    evidence = result["now"][0]["evidence"]
    assert evidence[2]["availability"] == "refused"
    assert evidence[2]["completeness"] == "unread"
    assert evidence[2]["cardinality"] == "not_measured"
    assert evidence[2]["linkage"] == "unlinked"
    assert evidence[3]["cardinality"] == "measured_empty"
    assert evidence[3]["read_watermark"] == "receipt-seq:0"
    inferred = deepcopy(candidate)
    inferred["evidence"][2]["claim"] = "guessed relation"
    with pytest.raises(OverviewContractError, match="unlinked evidence"):
        compose_overview_view(composition=_composition(), candidates={"now": [inferred]})


def test_measured_empty_requires_fresh_source_evidence() -> None:
    for freshness in ("stale", "unknown"):
        candidate = _candidate(
            evidence=[
                {
                    **_evidence(
                        "empty",
                        claim="Measured no items.",
                        freshness=freshness,
                        cardinality="measured_empty",
                    ),
                    "read_watermark": "receipt-seq:0",
                }
            ]
        )

        with pytest.raises(OverviewContractError, match="measured_empty requires fresh"):
            compose_overview_view(
                composition=_composition(), candidates={"now": [candidate]}
            )


@pytest.mark.parametrize("zone", ("needs_you", "ready_to_try"))
@pytest.mark.parametrize(
    "captured_at",
    (
        "not-rfc3339",
        "2026-08-09 21:00:00+00:00",
        "20260809T210000+00:00",
        "2026-08-09T21:00:00",
    ),
)
def test_malformed_timestamps_cannot_support_classification(
    zone: str, captured_at: str
) -> None:
    candidate = _candidate()
    candidate["evidence"][0 if zone == "needs_you" else 1]["captured_at"] = captured_at

    with pytest.raises(OverviewContractError, match="RFC3339"):
        compose_overview_view(
            composition=_composition(), candidates={zone: [candidate]}
        )


def test_composition_and_provider_timestamps_must_be_rfc3339() -> None:
    malformed_composition = _composition()
    malformed_composition["captured_at"] = "not-rfc3339"
    with pytest.raises(OverviewContractError, match="RFC3339"):
        compose_overview_view(composition=malformed_composition)

    malformed_provider = _composition()
    malformed_provider["providers"]["work"]["captured_at"] = "not-rfc3339"
    with pytest.raises(OverviewContractError, match="RFC3339"):
        compose_overview_view(composition=malformed_provider)


@pytest.mark.parametrize(
    "field",
    ("authority", "completeness"),
)
def test_available_provider_requires_coherent_trust_fields(field: str) -> None:
    composition = _composition()
    composition["providers"]["work"][field] = None

    with pytest.raises(OverviewContractError, match="available provider"):
        compose_overview_view(composition=composition)

    missing_identity = _composition()
    missing_identity["providers"]["work"]["snapshot"] = None
    missing_identity["providers"]["work"]["captured_at"] = None
    with pytest.raises(OverviewContractError, match="snapshot or captured_at"):
        compose_overview_view(composition=missing_identity)


def test_refused_provider_requires_refusal_evidence() -> None:
    composition = _composition()
    composition["providers"]["capabilities"]["refusal"] = None

    with pytest.raises(OverviewContractError, match="refused provider"):
        compose_overview_view(composition=composition)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("captured_at", "2026-08-09T21:00:00+00:00"),
        ("snapshot", {"watermark": "forged:1"}),
        ("completeness", {"claim": {"kind": "counted"}}),
        ("payload", {"resources": []}),
    ),
)
def test_refused_provider_rejects_available_evidence(field: str, value: object) -> None:
    composition = _composition()
    composition["providers"]["capabilities"][field] = value

    with pytest.raises(OverviewContractError, match="cannot carry available evidence"):
        compose_overview_view(composition=composition)


def test_withdrawal_preserves_producer_limitations() -> None:
    candidate = _candidate()
    candidate["owner_authority"]["category"] = "ci_failure"
    candidate["limitations"] = [
        "The producer could not prove that this is an owner-authority decision."
    ]

    result = compose_overview_view(
        composition=_composition(), candidates={"needs_you": [candidate]}
    )

    withdrawal = next(
        item
        for item in result["limitations"]
        if item.get("subject_ref") == candidate["subject_ref"]
    )
    assert withdrawal["limitations"] == candidate["limitations"]


def test_overview_keeps_roots_separate_and_survives_degraded_references() -> None:
    roots = [
        {
            "kind": "focus",
            "navigation_ref": _source("focus:4715"),
            "status": "available",
            "limitation": None,
        },
        {
            "kind": "soi_evidence",
            "navigation_ref": _source("soi:mimer"),
            "status": "degraded",
            "limitation": "The explicit denominator source is stale.",
        },
        {
            "kind": "delivery_execution",
            "navigation_ref": _source("delivery:4715"),
            "status": "unsupported",
            "limitation": "No delivery control is admitted.",
        },
        {
            "kind": "builder_system_control",
            "navigation_ref": _source("bsc:main"),
            "status": "unlinked",
            "limitation": "Control has no selected Focus relation.",
        },
    ]

    result = compose_overview_view(
        composition=_composition(), candidates={"now": [_candidate()]}, root_references=roots
    )

    assert result["now"]
    assert result["root_references"] == roots
    assert result["soi_evidence_lens"] == roots[1]
    assert all(set(ref) == {"kind", "navigation_ref", "status", "limitation"} for ref in roots)
