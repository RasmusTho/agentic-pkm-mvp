from pathlib import Path

from fastapi import Request

from app.api.operation_runtime import build_production_operation_runtime
from app.operations.contracts import CapabilitySupport
from app.operations.execution_kernel import JsonReceiptStore
from tests._production_operation_harness import production_operation_host


def _runtime(host):
    request = Request({"type": "http", "method": "GET", "headers": [],
                       "client": ("testclient", 5000)})
    return build_production_operation_runtime(request, api_key=None,
        session_bearer=host.selection["context_selection_id"], override_bearer=None)


def test_runtime_installs_only_authorized_delivered_handlers(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    runtime = _runtime(host)
    assert isinstance(runtime.kernel.receipt_store, JsonReceiptStore)
    assert runtime.kernel.receipt_store.path.parent == host.runtime.registry.path.parent
    assert set(runtime.kernel.handlers) == {
        "artifact.capture", "artifact.update", "artifact.move", "artifact.rename"}
    command = host.command()
    result = host.client.post("/api/operations", headers=host.headers, json=command)
    assert result.status_code == 200, result.text
    outcome = result.json()
    assert outcome["status"] == "convergence_pending", outcome
    assert host.note.read_text().endswith("Updated body.\n")
    authority = outcome["receipt"]["extensions"]["write"]["authority_receipt"]
    assert authority["active_context"]["principal_context"]["principal_id"] == runtime.actor
    assert authority["target_binding_id"] == host.binding_id
    assert Path(runtime.kernel.receipt_store.path).is_file()


def test_discovery_matches_installed_runtime_handlers(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    runtime = _runtime(host)
    capabilities = runtime.discovery()
    supported_effects = {entry.operation_id for entry in capabilities.capabilities
        if entry.support is CapabilitySupport.SUPPORTED
        and entry.extensions["authority_class"] == "governed_effect"}
    assert supported_effects == set(runtime.kernel.handlers)
    for operation in ("artifact.archive", "artifact.restore", "artifact.classify",
                      "artifact.tags.add", "collection.reorder", "artifact.create", "proposal.apply"):
        entry = capabilities.for_operation(operation)
        assert entry.support is CapabilitySupport.UNAVAILABLE and entry.reason
        response = host.client.post("/api/operations", headers=host.headers,
                                     json=host.command(operation, request_id=operation))
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "not_supported"
    discovered = host.client.get("/api/operations/capabilities", headers=host.headers)
    assert discovered.status_code == 200, discovered.text
    assert "unavailable" in discovered.text


def test_production_rename_preserves_identity_and_owner_receipt(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    from app.knowledge.placement import KnowledgePlacementOwner
    from app.api.routes.active_context_selection import build_selection_service, get_selection_store
    service = build_selection_service(get_selection_store())
    derived = service.derive("trusted_loopback")
    context = service.resolve_request_context(derived=derived,
        session_bearer=host.selection["context_selection_id"], override_bearer=None,
        action="operation.artifact.rename", write_class="vault_placement", required_permission="write").snapshot
    owner = KnowledgePlacementOwner(vault_root=host.root, context_ref=context.context_id,
        vault_generation=str(context.generation), actor=context.principal_context.principal_id,
        active_context=context, target_binding_id=host.binding_id, registry_store=host.runtime.registry,
        context_is_current=lambda: True, authority_is_current=lambda _: True, filesystem="local-posix-v1")
    command = host.command("artifact.rename", expected_version=owner.source_generation("Notes/human.md", host.artifact_id),
        arguments={"name": "renamed.md", "destination_generation": owner.destination_generation("Notes/renamed.md")})
    response = host.client.post("/api/operations", headers=host.headers, json=command)
    assert response.status_code == 200, response.text
    assert response.json()["status"] in {"succeeded", "convergence_pending"}, response.text
    assert not host.note.exists()
    assert host.artifact_id in (host.root / "Notes/renamed.md").read_text()
