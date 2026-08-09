"""Hostile contract tests for the BSC-01 governing-document projection."""

from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

from app.builderops.devui_builder_system_control import (
    GoverningDocumentContractError,
    compose_builder_system_control_view,
    compose_governing_document_inventory,
)


def _ref(source_id: str) -> dict[str, str]:
    return {
        "source_type": "repository_document",
        "source_id": source_id,
        "version": "git:315d8103",
        "locator": source_id,
    }


def _state(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "availability": "available",
        "freshness": "fresh",
        "coverage": "complete",
        "cardinality": "nonempty",
        "linkage": "linked",
        "captured_at": "2026-08-10T08:00:00+00:00",
        "fresh_until": "2026-08-11T08:00:00+00:00",
        "read_scope": "document:declared-governing-document",
        "read_watermark": "git:315d8103",
        "limitations": [],
    }
    value.update(overrides)
    return value


def _document(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source_ref": _ref("docs/architecture/SBS_OPERATING_MODEL.md"),
        "role": "Builder System operating model",
        "authority_class": "normative",
        "authority_scope": "Builder System boundary and work classification",
        "owner_ref": _ref("docs/architecture/SBS_OPERATING_MODEL.md#owner"),
        "lifecycle": {
            "phase": "accepted",
            "temporal_class": "strategic",
            "review_cadence": "event-driven",
            "supersedes_refs": [],
            "superseded_by_refs": [],
        },
        "source_state": _state(),
        "limitations": [],
    }
    value.update(overrides)
    return value


def _compose(*documents: dict[str, object]) -> dict[str, object]:
    return compose_governing_document_inventory(
        repository_ref="RasmusTho/agentic-pkm-mvp",
        governance_baseline_ref=_ref("docs/architecture/SBS_OPERATING_MODEL.md"),
        composed_at="2026-08-10T08:01:00+00:00",
        declarations=list(documents),
        limitations=[],
    )


def _adapter(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source_ref": _ref(".codex/skills/issue-to-code/SKILL.md"),
        "adapter_kind": "skill",
        "adapter_id": "issue-to-code",
        "version_or_digest": "git:315d8103",
        "owning_workflow_refs": [_ref("docs/development/DEV_WORKFLOW.md")],
        "owning_policy_refs": [_ref("AGENTS.md")],
        "trigger": "bounded GitHub implementation work",
        "input_contract_refs": [_ref(".codex/skills/_shared/ISSUE_CONTRACT.md")],
        "output_and_receipt_refs": [_ref("docs/development/PR_HOT_PATH.md")],
        "refusal_and_authority_limits": ["does not own policy or issue truth"],
        "source_state": _state(),
        "limitations": [],
    }
    value.update(overrides)
    return value


def _capability(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source_ref": _ref("scripts/issue_pickup_claim.sh"),
        "capability_kind": "script",
        "capability_id": "issue-pickup-claim",
        "version_or_digest": "git:315d8103",
        "owning_workflow_refs": [_ref("docs/development/DEV_WORKFLOW.md")],
        "available_operations": ["claim"],
        "side_effect_class": "governed_write",
        "admission_boundary_ref": _ref(".codex/skills/issue-to-code/SKILL.md"),
        "explicit_non_authority": ["does not grant approval or policy authority"],
        "source_state": _state(),
        "limitations": [],
    }
    value.update(overrides)
    return value


def _compose_control(
    *,
    adapters: list[dict[str, object]] | None = None,
    capabilities: list[dict[str, object]] | None = None,
    coverage: list[dict[str, object]] | None = None,
    deviations: list[dict[str, object]] | None = None,
    routes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return compose_builder_system_control_view(
        repository_ref="RasmusTho/agentic-pkm-mvp",
        governance_baseline_ref=_ref("docs/architecture/SBS_OPERATING_MODEL.md"),
        composed_at="2026-08-10T08:01:00+00:00",
        governing_document_declarations=[_document()],
        workflow_adapter_declarations=[] if adapters is None else adapters,
        capability_binding_declarations=[] if capabilities is None else capabilities,
        coverage_declarations=[] if coverage is None else coverage,
        route_deviation_declarations=[] if deviations is None else deviations,
        governed_route_declarations=[] if routes is None else routes,
        limitations=[],
    )


def _exception(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source_ref": _ref("evidence/exception-governing-document"),
        "permitting_authority_ref": _ref("docs/EXCEPTIONS.md#permit"),
        "lifecycle_ref": _ref("docs/EXCEPTIONS.md#expiry"),
        "expires_at": "2026-08-11T08:00:00+00:00",
        "limitations": [],
    }
    value.update(overrides)
    return value


def _coverage(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "claim_id": "coverage:governing-documents",
        "source_ref": _ref("evidence/governing-document-coverage"),
        "authority_scope": "declared Builder System governing documents",
        "governing_source_refs": [_ref("docs/architecture/SBS_OPERATING_MODEL.md")],
        "completeness_definition_ref": _ref("docs/architecture/SBS_OPERATING_MODEL.md#scope"),
        "assessed_scope": "declared Builder System governing documents at git:315d8103",
        "source_state": _state(read_scope="coverage:declared-governing-documents"),
        "drift_observations": [
            {
                "source_ref": _ref("evidence/governing-document-drift"),
                "observed_at": "2026-08-10T08:00:00+00:00",
                "difference": "no declared drift",
            }
        ],
        "exception_declarations": [],
        "unknowns": [],
        "limitations": [],
    }
    value.update(overrides)
    return value


def _route(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "route_id": "route:docs-governance",
        "source_ref": _ref(".codex/skills/docs-governance/SKILL.md"),
        "entrypoint": "docs-governance",
        "authority_or_admission_ref": _ref("docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md#routes"),
        "accepted_inputs": ["exact source refs", "bounded conflict context"],
        "expected_side_effects": ["none from the projection"],
        "expected_non_effects": ["does not execute the destination workflow"],
        "receipt_ref": _ref("docs/development/PR_HOT_PATH.md"),
        "source_state": _state(read_scope="route:docs-governance"),
        "limitations": [],
    }
    value.update(overrides)
    return value


def _deviation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "deviation_id": "deviation:declared-route",
        "source_ref": _ref("evidence/route-deviation"),
        "authority_scope": "declared Builder System delivery route",
        "intended_route_refs": [_ref("docs/development/DEV_WORKFLOW.md")],
        "observed_route_refs": [_ref("evidence/observed-delivery-route")],
        "correlation_ref": _ref("evidence/route-correlation"),
        "observed_at": "2026-08-10T08:00:00+00:00",
        "difference": "observed route omitted a declared handoff receipt",
        "source_state": _state(read_scope="route-deviation:declared-route"),
        "existing_repair_route_ref": _route(),
        "repair_route_linkage": "linked",
        "repair_route_correlation_ref": _ref("evidence/route-repair-applicability"),
        "limitations": [],
    }
    value.update(overrides)
    return value


def test_governing_document_inventory_is_projection_only_and_has_no_io_or_state_path() -> None:
    result = _compose(_document())

    assert result == {
        "contract_version": "builder-system-control-view.v1",
        "authority": "projection_only",
        "primary_identity": "builder_system",
        "scope": {
            "kind": "builder_system",
            "repository_ref": "RasmusTho/agentic-pkm-mvp",
            "governance_baseline_ref": _ref("docs/architecture/SBS_OPERATING_MODEL.md"),
        },
        "composed_at": "2026-08-10T08:01:00+00:00",
        "governing_documents": [_document()],
        "limitations": [],
    }
    source = inspect.getsource(compose_governing_document_inventory)
    assert "open(" not in source
    assert "Path(" not in source
    assert "requests" not in source


def test_governing_document_inventory_preserves_declared_authority_and_lifecycle() -> None:
    document = _document()
    result = _compose(document)

    rendered = result["governing_documents"][0]
    assert rendered["source_ref"] == document["source_ref"]
    assert rendered["role"] == document["role"]
    assert rendered["authority_class"] == "normative"
    assert rendered["authority_scope"] == document["authority_scope"]
    assert rendered["owner_ref"] == document["owner_ref"]
    assert rendered["lifecycle"] == document["lifecycle"]
    assert rendered["source_state"] == document["source_state"]
    assert rendered["limitations"] == []


def test_governing_document_inventory_rejects_provenance_and_noncanonical_hashes() -> None:
    provenance = _document(
        source_ref={
            "source_type": "provider_session",
            "source_id": "session:untrusted",
            "version": "run:1",
            "locator": "session:untrusted",
        }
    )
    with pytest.raises(GoverningDocumentContractError, match="provenance"):
        _compose(provenance)

    forged_hash = _document(
        source_ref={
            "source_type": "repository_document",
            "source_id": "docs/forged.md",
            "content_hash": "unknown",
            "locator": "docs/forged.md",
        }
    )
    with pytest.raises(GoverningDocumentContractError, match="SHA-256"):
        _compose(forged_hash)


def test_governing_document_inventory_never_infers_missing_authority_or_lifecycle() -> None:
    missing = _document(
        owner_ref=None,
        lifecycle=None,
        source_state=_state(
            coverage="missing",
            cardinality="not_measured",
            linkage="unlinked",
        ),
    )
    result = _compose(missing)
    rendered = result["governing_documents"][0]

    assert rendered["owner_ref"] is None
    assert rendered["lifecycle"] == {
        "phase": "unknown",
        "temporal_class": "unknown",
        "review_cadence": "unknown",
        "supersedes_refs": [],
        "superseded_by_refs": [],
    }
    assert rendered["source_state"]["coverage"] == "missing"
    assert rendered["source_state"]["linkage"] == "unlinked"

    conflicting = deepcopy(missing)
    conflicting["source_state"] = _state()
    with pytest.raises(GoverningDocumentContractError, match="missing owner"):
        _compose(conflicting)


def test_governing_document_inventory_preserves_independent_source_axes() -> None:
    unavailable = _document(
        source_state=_state(
            availability="unavailable",
            freshness="fresh",
            coverage="unread",
            cardinality="not_measured",
            linkage="not_assessed",
        )
    )
    unread = _document(
        source_ref=_ref("docs/DEVUI.md"),
        source_state=_state(
            availability="available",
            freshness="stale",
            coverage="unread",
            cardinality="not_measured",
            linkage="unlinked",
        ),
    )
    measured_empty = _document(
        source_ref=_ref("docs/empty.md"),
        source_state=_state(cardinality="measured_empty"),
    )
    result = _compose(unavailable, unread, measured_empty)

    rendered = result["governing_documents"]
    assert rendered[0]["source_state"] == unavailable["source_state"]
    assert rendered[1]["source_state"] == unread["source_state"]
    assert rendered[2]["source_state"] == measured_empty["source_state"]

    hostile_empty = deepcopy(measured_empty)
    hostile_empty["source_state"] = _state(
        availability="unavailable",
        cardinality="measured_empty",
    )
    with pytest.raises(GoverningDocumentContractError, match="measured_empty"):
        _compose(hostile_empty)


def test_governing_document_inventory_requires_time_basis_for_freshness() -> None:
    no_basis = _document(source_state=_state(fresh_until=None))
    with pytest.raises(GoverningDocumentContractError, match="freshness basis"):
        _compose(no_basis)

    expired = _document(source_state=_state(fresh_until="2026-08-10T08:00:00+00:00"))
    with pytest.raises(GoverningDocumentContractError, match="fresh_until"):
        _compose(expired)


def test_workflow_adapter_projection_preserves_explicit_ownership_and_contract_refs() -> None:
    adapter = _adapter()

    result = _compose_control(adapters=[adapter])

    assert result["workflow_adapters"] == [adapter]
    assert result["capability_bindings"] == []
    assert result["authority"] == "projection_only"
    assert result["primary_identity"] == "builder_system"


def test_workflow_adapter_projection_refuses_inferred_policy_or_ownership() -> None:
    incomplete = _adapter(
        version_or_digest=None,
        owning_workflow_refs=[],
        owning_policy_refs=[],
        source_state=_state(linkage="linked"),
    )

    result = _compose_control(adapters=[incomplete])

    rendered = result["workflow_adapters"][0]
    assert rendered["version_or_digest"] == "unknown"
    assert rendered["owning_workflow_refs"] == []
    assert rendered["owning_policy_refs"] == []
    assert rendered["source_state"]["coverage"] == "missing"
    assert rendered["source_state"]["cardinality"] == "not_measured"
    assert rendered["source_state"]["linkage"] == "unlinked"
    assert "inferred" not in str(rendered).lower()


def test_capability_binding_projection_preserves_operations_effects_and_admission_boundary() -> (
    None
):
    capability = _capability(
        capability_kind="connector",
        available_operations=["list", "describe"],
        side_effect_class="external_effect",
    )

    result = _compose_control(capabilities=[capability])

    assert result["capability_bindings"] == [capability]
    assert result["workflow_adapters"] == []


def test_capability_binding_projection_never_promotes_availability_to_authority() -> None:
    valid = _capability(
        capability_id="safe-read", side_effect_class="read_only", admission_boundary_ref=None
    )
    incomplete = _capability(
        capability_id="write-without-admission",
        owning_workflow_refs=[],
        admission_boundary_ref=None,
        source_state=_state(linkage="linked"),
    )

    result = _compose_control(capabilities=[valid, incomplete])

    assert result["capability_bindings"][0] == valid
    refused = result["capability_bindings"][1]
    assert refused["admission_boundary_ref"] is None
    assert refused["source_state"]["availability"] == "available"
    assert refused["source_state"]["coverage"] == "missing"
    assert refused["source_state"]["linkage"] == "unlinked"


def test_adapter_and_capability_projection_preserves_independent_axes_and_projection_boundary() -> (
    None
):
    adapter = _adapter(
        source_state=_state(
            availability="unavailable",
            freshness="stale",
            coverage="unread",
            cardinality="not_measured",
            linkage="not_assessed",
        )
    )
    capability = _capability(
        source_state=_state(
            availability="available",
            freshness="unknown",
            coverage="partial",
            cardinality="nonempty",
            linkage="unlinked",
        )
    )

    result = _compose_control(adapters=[adapter], capabilities=[capability])

    assert result["workflow_adapters"][0]["source_state"] == adapter["source_state"]
    assert result["capability_bindings"][0]["source_state"] == capability["source_state"]
    assert result["authority"] == "projection_only"
    assert result["primary_identity"] == "builder_system"
    source = inspect.getsource(compose_builder_system_control_view)
    assert "open(" not in source
    assert "Path(" not in source
    assert "requests" not in source


def test_coverage_projection_preserves_bounded_source_owned_evidence() -> None:
    coverage = _coverage(exception_declarations=[_exception()], unknowns=["unread legacy run"])

    result = _compose_control(coverage=[coverage])

    rendered = result["coverage"][0]
    assert rendered["claim_id"] == coverage["claim_id"]
    assert rendered["source_ref"] == coverage["source_ref"]
    assert rendered["governing_source_refs"] == coverage["governing_source_refs"]
    assert rendered["assessed_scope"] == coverage["assessed_scope"]
    assert rendered["source_state"] == coverage["source_state"]
    assert rendered["drift_observations"] == coverage["drift_observations"]
    assert rendered["exception_refs"] == [_exception()["source_ref"]]
    assert rendered["exceptions"] == [_exception()]
    assert rendered["unknowns"] == ["unread legacy run"]
    assert "score" not in rendered


def test_coverage_projection_requires_fresh_bounded_completeness_evidence() -> None:
    valid = _coverage(claim_id="coverage:valid")
    degraded = _coverage(
        claim_id="coverage:degraded",
        completeness_definition_ref=None,
        source_state=_state(
            availability="unavailable",
            freshness="stale",
            coverage="complete",
            cardinality="not_measured",
            linkage="unlinked",
        ),
    )
    measured_empty = _coverage(
        claim_id="coverage:measured-empty",
        source_state=_state(cardinality="measured_empty"),
    )

    result = _compose_control(coverage=[valid, degraded, measured_empty])

    assert result["coverage"][0]["source_state"]["coverage"] == "complete"
    assert result["coverage"][1]["source_state"]["coverage"] == "missing"
    assert result["coverage"][1]["source_state"]["cardinality"] == "not_measured"
    assert result["coverage"][1]["source_state"]["linkage"] == "unlinked"
    assert result["coverage"][2]["source_state"]["cardinality"] == "measured_empty"


def test_coverage_projection_refuses_unauthorized_or_unbounded_exceptions() -> None:
    valid = _exception()
    unauthorized = _exception(
        source_ref=_ref("evidence/unauthorized-exception"),
        permitting_authority_ref=None,
    )
    expired = _exception(
        source_ref=_ref("evidence/expired-exception"),
        expires_at="2026-08-10T08:00:00+00:00",
    )
    malformed = _exception(
        source_ref=_ref("evidence/malformed-exception"),
        lifecycle_ref={
            "source_type": "repository_document",
            "source_id": "docs/EXCEPTIONS.md#broken-expiry",
            "content_hash": "not-a-sha",
            "locator": "docs/EXCEPTIONS.md#broken-expiry",
        },
    )

    result = _compose_control(
        coverage=[_coverage(exception_declarations=[valid, unauthorized, expired, malformed])]
    )

    rendered = result["coverage"][0]
    assert rendered["exception_refs"] == [valid["source_ref"]]
    assert "exception:evidence/unauthorized-exception" in rendered["unknowns"]
    assert "exception:evidence/expired-exception" in rendered["unknowns"]
    assert "exception:evidence/malformed-exception" in rendered["unknowns"]

    future_drift = _coverage(
        drift_observations=[
            {
                "source_ref": _ref("evidence/future-drift"),
                "observed_at": "2026-08-10T08:02:00+00:00",
                "difference": "future evidence",
            }
        ]
    )
    with pytest.raises(GoverningDocumentContractError, match="cannot be after composition"):
        _compose_control(coverage=[future_drift])


def test_route_deviation_projection_requires_explicit_source_owned_correlation() -> None:
    valid = _deviation()

    result = _compose_control(deviations=[valid], routes=[_route()])

    assert result["deviations"] == [valid]
    with pytest.raises(GoverningDocumentContractError, match="correlation_ref"):
        _compose_control(
            deviations=[_deviation(correlation_ref=None)],
            routes=[_route()],
        )
    for source_state in (
        _state(linkage="unlinked"),
        _state(
            availability="unavailable",
            coverage="partial",
            cardinality="not_measured",
        ),
        _state(freshness="stale", coverage="partial"),
        _state(coverage="unread", cardinality="not_measured"),
    ):
        withdrawn = _compose_control(
            deviations=[_deviation(source_state=source_state)],
            routes=[_route()],
        )
        assert withdrawn["deviations"] == []
        assert "route deviation:deviation:declared-route withdrawn" in withdrawn["limitations"]


def test_route_deviation_projection_preserves_governed_repair_route_without_effect() -> None:
    route = _route()
    deviation = _deviation(existing_repair_route_ref=route)

    result = _compose_control(deviations=[deviation], routes=[route])

    assert result["governed_routes"] == [route]
    assert result["deviations"][0]["existing_repair_route_ref"] == route
    assert result["deviations"][0]["repair_route_correlation_ref"] == _ref(
        "evidence/route-repair-applicability"
    )
    source = inspect.getsource(compose_builder_system_control_view)
    assert "execute" not in source
    assert "mutate" not in source


def test_coverage_and_deviation_projection_preserves_bsc_boundary() -> None:
    result = _compose_control(coverage=[_coverage()], deviations=[_deviation()], routes=[_route()])

    assert result["authority"] == "projection_only"
    assert result["primary_identity"] == "builder_system"
    assert "focus" not in result
    assert "commands" not in result
    assert "persistence" not in result
    source = inspect.getsource(compose_builder_system_control_view)
    assert "open(" not in source
    assert "Path(" not in source
    assert "requests" not in source
