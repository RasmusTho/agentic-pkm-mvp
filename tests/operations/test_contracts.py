from app.operations.contracts import CapabilityAvailability, CapabilityDiscovery, CapabilitySupport, OperationContext, OperationOutcome, OperationRequest, OperationStatus


def test_operation_contract_round_trip_and_forward_compatible_extensions() -> None:
    context = OperationContext("context-1", "vault-7", {"future_context": True})
    request = OperationRequest("artifact.move", "request-1", context, targets=({"artifact_id": "a-1"},), arguments={"destination": "inbox"}, expected_version=7, extensions={"future_request": {"x": 1}})
    assert OperationRequest.from_dict(request.to_dict()) == request
    for status in OperationStatus:
        outcome = OperationOutcome("request-1", status, "artifact.move", context, extensions={"future_outcome": status.value})
        assert OperationOutcome.from_dict(outcome.to_dict()) == outcome


def test_capability_discovery_reports_support_policy_and_availability() -> None:
    discovery = CapabilityDiscovery((CapabilityAvailability("artifact.read", CapabilitySupport.SUPPORTED), CapabilityAvailability("artifact.move", CapabilitySupport.POLICY_DISABLED, "policy denies this context"), CapabilityAvailability("artifact.archive", CapabilitySupport.UNAVAILABLE, "owner seam unavailable")))
    assert discovery.for_operation("artifact.read").support is CapabilitySupport.SUPPORTED
    assert discovery.for_operation("artifact.move").support is CapabilitySupport.POLICY_DISABLED
    assert discovery.for_operation("artifact.archive").support is CapabilitySupport.UNAVAILABLE
