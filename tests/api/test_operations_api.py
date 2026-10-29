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


def test_http_read_version_drives_native_update_and_stale_conflict(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    read = dict(operation_id="artifact.read", request_id="public-read",
        active_context_ref=host.selection["context"]["context_id"],
        vault_generation=str(host.selection["context"]["generation"]),
        target_binding_id=host.binding_id, targets=[{"artifact_id": host.artifact_id}], arguments={})
    observed = host.client.post("/api/operations", headers=host.headers, json=read)
    assert observed.status_code == 200 and observed.json()["status"] == "succeeded"
    version = observed.json()["items"][0]["resulting_version"]
    update = {**read, "operation_id": "artifact.update", "request_id": "public-update",
        "expected_version": version, "arguments": {"body": "Updated using only HTTP.\n"}}
    result = host.client.post("/api/operations", headers=host.headers, json=update)
    assert result.status_code == 200 and result.json()["status"] == "convergence_pending"
    stale = host.client.post("/api/operations", headers=host.headers,
        json={**update, "request_id": "public-stale-update"})
    assert stale.status_code == 200 and stale.json()["status"] == "conflicted"
    after = host.client.post("/api/operations", headers=host.headers,
        json={**read, "request_id": "public-read-after"})
    assert after.json()["items"][0]["payload"]["body"].endswith("Updated using only HTTP.\n")


@pytest.mark.parametrize(("operation", "arguments", "destination"), [
    ("artifact.rename", {"name": "renamed.md"}, "Notes/renamed.md"),
    ("artifact.move", {"destination": "Projects/moved.md"}, "Projects/moved.md"),
])
def test_http_placement_preconditions_are_native_and_non_authoritative(
    tmp_path, monkeypatch, operation, arguments, destination,
):
    host = production_operation_host(tmp_path, monkeypatch)
    (host.root / "Projects").mkdir()
    command = dict(operation_id=operation, request_id="public-placement",
        active_context_ref=host.selection["context"]["context_id"],
        vault_generation=str(host.selection["context"]["generation"]),
        target_binding_id=host.binding_id, targets=[{"artifact_id": host.artifact_id}],
        arguments=arguments)
    preflight = host.client.post("/api/operations/preconditions", headers=host.headers, json=command)
    assert preflight.status_code == 200, preflight.text
    snapshot = preflight.json()
    assert snapshot["status"] == "observed"
    assert isinstance(snapshot["expected_version"], str) and snapshot["expected_version"]
    assert snapshot["arguments"]["destination_generation"]
    assert not {"decision_token", "delegation", "receipt", "policy", "root", "path"}.intersection(snapshot)
    assert host.note.exists() and not (host.root / destination).exists()
    assert not (host.root / ".pkm-placement").exists()
    effect = host.client.post("/api/operations", headers=host.headers,
        json={**command, "expected_version": snapshot["expected_version"],
              "arguments": snapshot["arguments"]})
    assert effect.status_code == 200 and effect.json()["status"] in {"succeeded", "convergence_pending"}
    assert effect.json()["convergence"]["source_effect"] == "committed"
    read = host.client.post("/api/operations", headers=host.headers,
        json={**command, "operation_id": "artifact.read", "request_id": "public-read-placed",
              "arguments": {}})
    assert read.status_code == 200 and read.json()["status"] == "succeeded"
    assert read.json()["items"][0]["payload"]["body"].endswith("Original.\n")


@pytest.mark.parametrize("change", ["source", "destination"])
def test_http_placement_observation_does_not_refresh_execute_versions(tmp_path, monkeypatch, change):
    host = production_operation_host(tmp_path, monkeypatch)
    command = dict(operation_id="artifact.rename", request_id="placement-observed",
        active_context_ref=host.selection["context"]["context_id"],
        vault_generation=str(host.selection["context"]["generation"]),
        target_binding_id=host.binding_id, targets=[{"artifact_id": host.artifact_id}],
        arguments={"name": "occupied.md"})
    observed = host.client.post("/api/operations/preconditions", headers=host.headers, json=command)
    assert observed.status_code == 200, observed.text
    snapshot = observed.json()
    if change == "source":
        read = host.client.post("/api/operations", headers=host.headers,
            json={**command, "operation_id": "artifact.read", "request_id": "before-concurrent-edit", "arguments": {}})
        changed = host.client.post("/api/operations", headers=host.headers,
            json={**command, "operation_id": "artifact.update", "request_id": "concurrent-edit",
                  "arguments": {"body": "Newer source must remain.\n"},
                  "expected_version": read.json()["items"][0]["resulting_version"]})
        assert changed.json()["status"] == "convergence_pending"
    else:
        (host.root / "Notes/occupied.md").write_text("Independent destination must remain.\n")
    original = host.note.read_bytes()
    refused = host.client.post("/api/operations", headers=host.headers,
        json={**command, "expected_version": snapshot["expected_version"], "arguments": snapshot["arguments"]})
    assert refused.status_code == 200 and refused.json()["status"] == "conflicted", refused.text
    assert host.note.read_bytes() == original
    if change == "destination":
        assert (host.root / "Notes/occupied.md").read_text() == "Independent destination must remain.\n"


@pytest.mark.parametrize("boundary", ["after_factory_clear", "after_factory_replace", "after_native_observation"])
def test_preconditions_keep_original_selection_guard(tmp_path, monkeypatch, boundary):
    host = production_operation_host(tmp_path, monkeypatch, extra_roots=("two",))
    from app.api.routes import operations
    from app.knowledge.placement import KnowledgePlacementOwner
    command = dict(operation_id="artifact.rename", request_id="precondition-revoked",
        active_context_ref=host.selection["context"]["context_id"],
        vault_generation=str(host.selection["context"]["generation"]),
        target_binding_id=host.binding_id, targets=[{"artifact_id": host.artifact_id}],
        arguments={"name": "refused.md"})
    if boundary.startswith("after_factory"):
        factory = operations.build_production_operation_runtime

        def changed(*args, **kwargs):
            runtime = factory(*args, **kwargs)
            if boundary == "after_factory_clear":
                host.clear_selection()
            else:
                service = runtime.carrier.service
                service.selection_store.replace_bindings(host.selection["context_selection_id"],
                    principal=runtime.carrier.derived.principal,
                    instance_identity=runtime.carrier.derived.instance_identity,
                    binding_ids=[next(binding for binding in host.runtime.registry.load().registrations
                                     if binding != host.binding_id)])
            return runtime

        monkeypatch.setattr(operations, "build_production_operation_runtime", changed)
    else:
        native = KnowledgePlacementOwner.destination_generation

        def revoked(owner, destination):
            generation = native(owner, destination)
            host.clear_selection()
            return generation

        monkeypatch.setattr(KnowledgePlacementOwner, "destination_generation", revoked)
    refused = host.client.post("/api/operations/preconditions", headers=host.headers, json=command)
    assert refused.status_code == 403, refused.text
    assert host.note.exists() and not (host.root / "Notes/refused.md").exists()
    assert not (host.root / ".pkm-placement").exists()
    assert not (host.runtime.registry.path.parent / "operation-receipts.json").exists()


def test_preconditions_reject_client_authority_and_do_not_reserve_receipts(tmp_path, monkeypatch):
    host = production_operation_host(tmp_path, monkeypatch)
    command = dict(operation_id="artifact.update", request_id="observe-only",
        active_context_ref=host.selection["context"]["context_id"],
        vault_generation=str(host.selection["context"]["generation"]),
        target_binding_id=host.binding_id, targets=[{"artifact_id": host.artifact_id}],
        arguments={"body": "Not an effect.\n"})
    assert host.client.post("/api/operations/preconditions", json=command).status_code == 401
    for key in ("delegation", "decision_token", "path", "receipt", "reader", "policy_decision"):
        assert host.client.post("/api/operations/preconditions", headers=host.headers,
            json={**command, key: "forged"}).status_code == 422
    assert host.client.post("/api/operations/preconditions", headers=host.headers,
        json={**command, "expected_version": "silently-refresh-this"}).status_code == 422
    observed = host.client.post("/api/operations/preconditions", headers=host.headers, json=command)
    assert observed.status_code == 200 and observed.json()["status"] == "observed"
    assert host.note.read_text().endswith("Original.\n")
    assert not (host.runtime.registry.path.parent / "operation-receipts.json").exists()


@pytest.mark.parametrize(("operation", "arguments"), [
    ("artifact.rename", {"name": "../escape.md"}),
    ("artifact.rename", {"name": "back\\slash.md"}),
    ("artifact.move", {"destination": "/tmp/escape.md"}),
    ("artifact.move", {"destination": "../escape.md"}),
    ("artifact.move", {"destination": ".system/escape.md"}),
    ("artifact.move", {"destination": "Notes/human.md"}),
])
def test_preconditions_keep_native_destination_boundaries(tmp_path, monkeypatch, operation, arguments):
    host = production_operation_host(tmp_path, monkeypatch)
    command = dict(operation_id=operation, request_id="invalid-destination",
        active_context_ref=host.selection["context"]["context_id"],
        vault_generation=str(host.selection["context"]["generation"]),
        target_binding_id=host.binding_id, targets=[{"artifact_id": host.artifact_id}],
        arguments=arguments)
    refused = host.client.post("/api/operations/preconditions", headers=host.headers, json=command)
    assert refused.status_code in {409, 422}, refused.text
    assert "expected_version" not in refused.json()
    assert host.note.read_text().endswith("Original.\n")
    assert not (host.root / ".pkm-placement").exists()
    assert not (host.runtime.registry.path.parent / "operation-receipts.json").exists()
