from app.operations.contracts import (
    CapabilityAvailability,
    CapabilityDiscovery,
    CapabilitySupport,
    ConvergenceState,
    OperationConflict,
    OperationContext,
    OperationConvergence,
    OperationItemOutcome,
    OperationOutcome,
    OperationProvenance,
    OperationReceipt,
    OperationRecovery,
    OperationRequest,
    OperationStatus,
    ReceiptStatus,
    SourceEffectStatus,
)


def test_operation_contract_round_trip_and_forward_compatible_extensions() -> None:
    context = OperationContext("context-1", "vault-7", {"future_context": True})
    request = OperationRequest(
        "artifact.move",
        "request-1",
        context,
        targets=({"artifact_id": "a-1"},),
        arguments={"destination": "inbox"},
        expected_version=7,
        extensions={"future_request": {"x": 1}},
    )
    assert OperationRequest.from_dict(request.to_dict()) == request
    for status in OperationStatus:
        outcome = OperationOutcome(
            "request-1",
            status,
            "artifact.move",
            context,
            extensions={"future_outcome": status.value},
        )
        assert OperationOutcome.from_dict(outcome.to_dict()) == outcome


def test_outcome_preserves_source_success_and_convergence_state_separately() -> None:
    outcome = OperationOutcome(
        "request-1",
        OperationStatus.SUCCEEDED,
        "artifact.move",
        OperationContext("context-1"),
        convergence=OperationConvergence(
            source_effect=SourceEffectStatus.COMMITTED,
            store=ConvergenceState.PENDING,
            index=ConvergenceState.PENDING,
        ),
    )

    assert outcome.status is OperationStatus.SUCCEEDED
    assert outcome.convergence is not None
    assert outcome.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert outcome.convergence.store is ConvergenceState.PENDING
    assert outcome.convergence.index is ConvergenceState.PENDING
    assert OperationOutcome.from_dict(outcome.to_dict()) == outcome


def test_operation_envelope_preserves_typed_metadata_and_provenance() -> None:
    context = OperationContext("context-1", "vault-7")
    provenance = OperationProvenance(actor="user-1", client="companion", surface="gui")
    request = OperationRequest(
        "artifact.move",
        "request-1",
        context,
        provenance=provenance,
        targets=({"artifact_id": "a-1", "domain_only": {"keep": "opaque"}},),
        arguments={"destination": "inbox", "domain_only": ["keep", "opaque"]},
    )
    outcome = OperationOutcome(
        "request-1",
        OperationStatus.CONFLICTED,
        "artifact.move",
        context,
        provenance=provenance,
        items=(
            OperationItemOutcome(
                resource_id="a-1",
                status=OperationStatus.SUCCEEDED,
                input_version="7",
                resulting_version="8",
                payload={"domain_only": {"keep": "opaque"}},
            ),
        ),
        conflict=OperationConflict(
            resource_id="a-2",
            expected_version="7",
            observed_version="9",
            payload={"domain_only": "opaque"},
        ),
        receipt=OperationReceipt(
            receipt_id="receipt-1",
            status=ReceiptStatus.COMMITTED,
            payload={"domain_only": "opaque"},
        ),
        recovery=OperationRecovery(
            action="reconcile",
            instructions="Re-read the target before retrying.",
            payload={"domain_only": "opaque"},
        ),
    )

    assert OperationRequest.from_dict(request.to_dict()) == request
    assert OperationOutcome.from_dict(outcome.to_dict()) == outcome

    legacy = OperationOutcome.from_dict(
        {
            "request_id": "request-legacy",
            "status": "conflicted",
            "operation_id": "artifact.move",
            "context": {"active_context_ref": "context-1"},
            "items": [{"domain_only": "item"}],
            "conflict": {"domain_only": "conflict"},
            "receipt": {"domain_only": "receipt"},
        }
    )
    assert legacy.items[0].payload == {"domain_only": "item"}
    assert legacy.conflict is not None and legacy.conflict.payload == {"domain_only": "conflict"}
    assert legacy.receipt is not None and legacy.receipt.payload == {"domain_only": "receipt"}


def test_capability_discovery_reports_support_policy_and_availability() -> None:
    discovery = CapabilityDiscovery(
        (
            CapabilityAvailability("artifact.read", CapabilitySupport.SUPPORTED),
            CapabilityAvailability(
                "artifact.move", CapabilitySupport.POLICY_DISABLED, "policy denies this context"
            ),
            CapabilityAvailability(
                "artifact.archive", CapabilitySupport.UNAVAILABLE, "owner seam unavailable"
            ),
        )
    )
    assert discovery.for_operation("artifact.read").support is CapabilitySupport.SUPPORTED
    assert discovery.for_operation("artifact.move").support is CapabilitySupport.POLICY_DISABLED
    assert discovery.for_operation("artifact.archive").support is CapabilitySupport.UNAVAILABLE
