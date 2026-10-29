import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from tests._production_operation_harness import production_operation_host


def test_effect_route_requires_mvr05c_and_rejects_client_authority(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    original = host.note.read_bytes()
    command = host.command()
    assert host.client.post("/api/operations", json=command).status_code == 401
    assert host.client.post("/api/operations", headers={"X-Active-Context-Session": "unknown"}, json=command).status_code == 401
    remote = TestClient(app, client=("203.0.113.9", 5000))
    assert remote.post("/api/operations", headers=host.headers, json=command).status_code == 401
    for field in ("path", "key", "reader", "policy_decision", "decision_token", "receipt", "delegation"):
        forged = {**command, field: {"allowed": True}}
        assert host.client.post("/api/operations", headers=host.headers, json=forged).status_code == 422
        forged = {**command, "arguments": {**command["arguments"], field: "forged"}}
        assert host.client.post("/api/operations", headers=host.headers, json=forged).status_code == 422
    readonly = {**command, "delegation": {"authority_class": "read_only"}}
    assert host.client.post("/api/operations", headers=host.headers, json=readonly).status_code == 422
    stale = {**command, "vault_generation": "0"}
    result = host.client.post("/api/operations", headers=host.headers, json=stale)
    assert result.status_code == 200 and result.json()["status"] == "conflicted"
    assert host.note.read_bytes() == original
    host.client.delete("/api/companion/active-context/selection", headers=host.headers)
    assert host.client.post("/api/operations", headers=host.headers, json=command).status_code == 401
    assert host.note.read_bytes() == original


@pytest.mark.parametrize("kind", ["path", "unknown"])
def test_target_identity_cannot_be_a_client_locator(tmp_path, monkeypatch, kind):
    host = production_operation_host(tmp_path, monkeypatch)
    identity = "Notes/human.md" if kind == "path" else "unknown"
    result = host.client.post("/api/operations", headers=host.headers,
        json=host.command(targets=[{"artifact_id": identity}]))
    assert result.status_code in {409, 422}
    assert host.note.read_text().endswith("Original.\n")


def test_expired_or_replaced_selection_cannot_borrow_old_intent(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    command = host.command()
    replacement = host.client.put("/api/companion/active-context/selection",
        headers=host.headers, json={"vault_binding_ids": [host.binding_id]})
    assert replacement.status_code == 200
    refused = host.client.post("/api/operations", headers=host.headers, json=command)
    assert refused.status_code == 200 and refused.json()["status"] == "conflicted"
    from app.api.routes.active_context_selection import get_selection_store
    store = get_selection_store()
    monkeypatch.setattr(store, "_clock", lambda: 4102444800)
    assert host.client.post("/api/operations", headers=host.headers, json=command).status_code == 401
    assert host.note.read_text().endswith("Original.\n")


@pytest.mark.parametrize("replacement", ["same_binding", "other_binding"])
def test_factory_selection_replacement_cannot_authorize_old_capture(tmp_path, monkeypatch, replacement):
    host = production_operation_host(tmp_path, monkeypatch, extra_roots=("two",))
    from pathlib import Path
    from app.api.routes import operations

    bindings = host.runtime.registry.load().registrations
    other_binding = next(binding for binding in bindings if binding != host.binding_id)
    target = host.binding_id if replacement == "same_binding" else other_binding
    command = host.command("artifact.capture", request_id="factory-selection-race",
        targets=[], expected_version=None, arguments={"text": "stale factory must not append"})
    real_factory = operations.build_production_operation_runtime
    observed = {}

    def replace_after_factory(*args, **kwargs):
        runtime = real_factory(*args, **kwargs)
        service = runtime.carrier.service
        bearer = host.selection["context_selection_id"]
        before = service.inspect(bearer, derived=runtime.carrier.derived)
        after = service.selection_store.replace_bindings(bearer,
            principal=before.principal, instance_identity=before.instance_identity,
            binding_ids=[target])
        observed.update(runtime=runtime, before=before, after=after)
        return runtime

    monkeypatch.setattr(operations, "build_production_operation_runtime", replace_after_factory)
    result = host.client.post("/api/operations", headers=host.headers, json=command)
    assert observed["before"].binding_ids == (host.binding_id,)
    assert observed["after"].binding_ids == (target,)
    assert observed["after"].generation == observed["before"].generation + 1
    assert observed["runtime"].context.active_context_ref == command["active_context_ref"]
    assert observed["runtime"].context.vault_generation == command["vault_generation"]
    assert observed["runtime"].context.extensions["target_binding_id"] == host.binding_id
    assert result.status_code == 403, result.text
    assert result.json()["detail"] == "operation_authority_unavailable"
    assert observed["runtime"].kernel.receipt_store.lookup(command["request_id"]) is None
    for registration in bindings.values():
        assert all("stale factory must not append" not in note.read_text()
                   for note in Path(registration.path).rglob("*.md"))


def test_replacement_during_factory_resolution_cannot_borrow_new_record(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch, extra_roots=("two",))
    from pathlib import Path
    from app.instance.active_context_service import ActiveContextSelectionService

    bindings = host.runtime.registry.load().registrations
    other_binding = next(binding for binding in bindings if binding != host.binding_id)
    command = host.command("artifact.capture", request_id="factory-resolution-race",
        targets=[], expected_version=None, arguments={"text": "unfenced resolved context"},
        target_binding_id=other_binding,
        vault_generation=str(host.selection["context"]["generation"] + 1))
    real_resolve = ActiveContextSelectionService.resolve_request_context
    observed = {}

    def replace_before_resolve(service, **kwargs):
        bearer = host.selection["context_selection_id"]
        before = service.inspect(bearer, derived=kwargs["derived"])
        after = service.selection_store.replace_bindings(bearer,
            principal=before.principal, instance_identity=before.instance_identity,
            binding_ids=[other_binding])
        resolved = real_resolve(service, **kwargs)
        observed.update(before=before, after=after, context=resolved.snapshot)
        return resolved

    monkeypatch.setattr(ActiveContextSelectionService, "resolve_request_context", replace_before_resolve)
    result = host.client.post("/api/operations", headers=host.headers, json=command)
    assert observed["before"].binding_ids == (host.binding_id,)
    assert observed["after"].binding_ids == observed["context"].binding_ids == (other_binding,)
    assert observed["after"].generation == observed["context"].generation == observed["before"].generation + 1
    assert str(observed["context"].generation) == command["vault_generation"]
    assert result.status_code == 403, result.text
    assert result.json()["detail"] == "operation_authority_unavailable"
    for registration in bindings.values():
        assert all("unfenced resolved context" not in note.read_text()
                   for note in Path(registration.path).rglob("*.md"))


def test_current_gov_token_is_required_even_for_valid_selection(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    from app.governance.governed_write import GovernedWriteAdapter, InvalidDecisionTokenError

    def invalid(self, **kwargs):
        raise InvalidDecisionTokenError("revoked at current GOV boundary")

    monkeypatch.setattr(GovernedWriteAdapter, "validate_decision_token", invalid)
    result = host.client.post("/api/operations", headers=host.headers, json=host.command())
    assert result.status_code == 200 and result.json()["status"] == "rejected", result.text
    assert host.note.read_text().endswith("Original.\n")


def test_reentrant_selection_change_at_source_seam_refuses_effect(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    import app.knowledge.write_ops as writes
    from app.api.routes.active_context_selection import build_selection_service, get_selection_store
    real_write = writes.write_note_from_absolute
    service = build_selection_service(get_selection_store())
    derived = service.derive("trusted_loopback")

    def changed(*args, **kwargs):
        service.selection_store.clear(host.selection["context_selection_id"],
            principal=derived.principal, instance_identity=derived.instance_identity)
        return real_write(*args, **kwargs)

    monkeypatch.setattr("app.operations.write_operations.write_note_from_absolute", changed)
    result = host.client.post("/api/operations", headers=host.headers, json=host.command())
    assert result.status_code in {200, 403}
    if result.status_code == 200:
        assert result.json()["status"] != "succeeded"
    assert host.note.read_text().endswith("Original.\n")


def test_capture_reuses_real_scoped_owner_and_preserves_v1(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    command = host.command("artifact.capture", targets=[], expected_version=None,
                           arguments={"text": "Remember the approved outcome"})
    result = host.client.post("/api/operations", headers=host.headers, json=command)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "convergence_pending", result.text
    assert "Remember the approved outcome" in "".join(
        note.read_text() for note in host.root.rglob("*.md"))
    assert result.json()["receipt"]["extensions"]["write"]["authority_receipt"]["target_binding_id"] == host.binding_id


def test_capture_keeps_selection_guard_at_native_append(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    from app.api.routes import capture
    from app.api.routes.active_context_selection import build_selection_service, get_selection_store
    service = build_selection_service(get_selection_store())
    derived = service.derive("trusted_loopback")
    append = capture.append_note_relative

    def clear_then_append(*args, **kwargs):
        service.selection_store.clear(host.selection["context_selection_id"],
            principal=derived.principal, instance_identity=derived.instance_identity)
        return append(*args, **kwargs)

    monkeypatch.setattr(capture, "append_note_relative", clear_then_append)
    result = host.client.post("/api/operations", headers=host.headers,
        json=host.command("artifact.capture", targets=[], expected_version=None,
                          arguments={"text": "must not cross cleared selection"}))
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "rejected", result.text
    assert all("must not cross cleared selection" not in note.read_text()
               for note in host.root.rglob("*.md"))


def test_capture_secondary_refusal_preserves_committed_main_receipt(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    from app.api.routes import capture
    from app.api.routes.active_context_selection import build_selection_service, get_selection_store
    from app.instance.context_bound_write import require_effect_locator
    service = build_selection_service(get_selection_store())
    derived = service.derive("trusted_loopback")

    def secondary(**kwargs):
        service.selection_store.clear(host.selection["context_selection_id"],
            principal=derived.principal, instance_identity=derived.instance_identity)
        require_effect_locator(kwargs["vault_root"], kwargs["note_rel"])
        pytest.fail("secondary effect must not run")

    monkeypatch.setattr(capture, "_offer_question_registration_proposal", secondary)
    result = host.client.post("/api/operations", headers=host.headers,
        json=host.command("artifact.capture", targets=[], expected_version=None,
                          arguments={"text": "main source remains acknowledged"}))
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "convergence_pending", result.text
    assert result.json()["convergence"]["source_effect"] == "committed"
    assert result.json()["receipt"]["extensions"]["write"]["authority_receipt"]["receipt_id"]


def test_capture_request_id_cannot_rebind_selected_target(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch, extra_roots=("two",))
    bindings = list(host.runtime.registry.load().registrations)
    assert len(bindings) == 2
    selection = host.client.put("/api/companion/active-context/selection", headers=host.headers,
                                json={"vault_binding_ids": bindings})
    assert selection.status_code == 200
    host.selection["context"] = selection.json()["context"]
    command = host.command("artifact.capture", targets=[], expected_version=None,
        arguments={"text": "one exact selected target"}, target_binding_id=bindings[0])
    first = host.client.post("/api/operations", headers=host.headers, json=command)
    assert first.status_code == 200 and first.json()["status"] == "convergence_pending", first.text
    second = host.client.post("/api/operations", headers=host.headers,
        json={**command, "target_binding_id": bindings[1]})
    assert second.status_code == 200 and second.json()["status"] == "conflicted", second.text
    from pathlib import Path
    other = Path(host.runtime.registry.load().registrations[bindings[1]].path)
    assert all("one exact selected target" not in note.read_text() for note in other.rglob("*.md"))
