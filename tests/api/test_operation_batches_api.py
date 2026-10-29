from copy import deepcopy

import pytest

from tests._production_batch_harness import (
    batch_action, batch_command, batch_inspect, preview_batch, production_batch_host,
)


def test_batch_preview_execution_enforce_frozen_host_authority(tmp_path, monkeypatch):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources)
    before = [note.read_bytes() for _, note in sources]
    preview = preview_batch(host, command)
    assert preview["cardinality"] == 2 and preview["partial_success_policy"] == "independent"
    assert [note.read_bytes() for _, note in sources] == before
    assert "decision_token" not in str(preview) and "host_admission" not in str(preview)
    executed = batch_action(host, preview)
    assert executed.status_code == 200, executed.text
    result = executed.json()
    assert result["status"] == "convergence_pending", result
    assert result["counts"]["completed"] == result["counts"]["convergence_pending"] == 2
    for index, (_, note) in enumerate(sources):
        assert note.read_text().endswith(f"HTTP batch body {index}.\n")
        authority = result["items"][index]["outcome"]["receipt"]["extensions"]["write"]["authority_receipt"]
        assert authority["target_binding_id"] == host.binding_id and authority["receipt_id"]
    assert batch_inspect(host, preview).json()["items"] == result["items"]
    assert batch_action(host, preview).json() == result


@pytest.mark.parametrize("kind", ["artifact.capture", "artifact.create", "proposal.apply", "artifact.read",
    "artifact.archive", "artifact.restore", "artifact.classify", "artifact.tags.add", "artifact.tags.remove",
    "collection.reorder", "unknown"])
def test_unqualified_batch_kind_refuses_before_effect(tmp_path, monkeypatch, kind):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = {**batch_command(host, sources), "operation_id": kind}
    before = [note.read_bytes() for _, note in sources]
    response = host.client.post("/api/operations/batches/preview", headers=host.headers, json=command)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_supported"
    assert [note.read_bytes() for _, note in sources] == before
    assert not (host.runtime.registry.path.parent / "operation-receipts.json").exists()


@pytest.mark.parametrize("field", ["path", "key", "reader", "service_reader", "policy", "policy_decision",
                                  "decision_token", "receipt", "receipt_store", "delegation", "active_context"])
def test_batch_client_cannot_inject_host_authority(tmp_path, monkeypatch, field):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources)
    for payload in ({**command, field: "forged"}, deepcopy(command)):
        if field not in payload:
            payload["items"][0]["arguments"][field] = {"allowed": True}
        response = host.client.post("/api/operations/batches/preview", headers=host.headers, json=payload)
        assert response.status_code == 422, response.text
    assert all("Original" in note.read_text() for _, note in sources)


@pytest.mark.parametrize("kind", ["artifact.move", "artifact.rename"])
def test_public_preconditions_freeze_qualified_placement_batch(tmp_path, monkeypatch, kind):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources, kind=kind)
    preview = preview_batch(host, command)
    result = batch_action(host, preview)
    assert result.status_code == 200, result.text
    assert result.json()["counts"]["completed"] == 2, result.text
    assert all(not note.exists() for _, note in sources)
    for index, (identity, _) in enumerate(sources):
        name = f"renamed-{index}.md" if kind == "artifact.rename" else f"moved-{index}.md"
        assert identity in (host.root / "Notes" / name).read_text()
    assert batch_action(host, preview).json()["items"] == result.json()["items"]



def test_preview_retry_retains_original_tokens_deadline_and_all_digests(tmp_path, monkeypatch):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources)
    first = preview_batch(host, command)
    from app.governance.governed_write import GovernedWriteAdapter

    def no_new_grant(*args, **kwargs):
        pytest.fail("retry cannot refresh original host admission")

    monkeypatch.setattr(GovernedWriteAdapter, "issue_decision_token", no_new_grant)
    assert preview_batch(host, command) == first
    changed = deepcopy(command)
    changed["items"][0]["arguments"]["body"] = "Changed after preview"
    assert host.client.post("/api/operations/batches/preview", headers=host.headers, json=changed).status_code == 409
    assert batch_inspect(host, first).json() == first


@pytest.mark.parametrize("timing", ["before_admission", "during_resolution", "during_item_binding", "after_preview"])
def test_real_selection_replacement_cannot_rebind_batch(tmp_path, monkeypatch, timing):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources)
    before = [note.read_bytes() for _, note in sources]
    from app.instance.active_context_service import ActiveContextSelectionService
    import app.api.batch_operation_runtime as batches
    observed = {}

    def replace_selection(service, derived):
        original = service.inspect(host.selection["context_selection_id"], derived=derived)
        replacement = service.selection_store.replace_bindings(host.selection["context_selection_id"],
            principal=original.principal, instance_identity=original.instance_identity,
            binding_ids=list(original.binding_ids))
        observed.update(original=original, replacement=replacement)

    if timing == "after_preview":
        preview = preview_batch(host, command)
        response = host.client.put("/api/companion/active-context/selection", headers=host.headers,
                                  json={"vault_binding_ids": [host.binding_id]})
        assert response.status_code == 200
        from app.governance.governed_write import GovernedWriteAdapter
        monkeypatch.setattr(GovernedWriteAdapter, "issue_decision_token",
            lambda *a, **k: pytest.fail("replacement cannot mint new authority for the frozen batch"))
        result = batch_action(host, preview)
        assert result.status_code == 200, result.text
        assert result.json()["current_admission"] == "refused"
        assert result.json()["counts"]["refused"] == 2
        assert batch_inspect(host, preview).json()["current_admission"] == "refused"
    else:
        if timing == "before_admission":
            response = host.client.put("/api/companion/active-context/selection", headers=host.headers,
                                      json={"vault_binding_ids": [host.binding_id]})
            assert response.status_code == 200
        elif timing == "during_resolution":
            resolve = ActiveContextSelectionService.resolve_request_context

            def replacing(service, **kwargs):
                if not observed:
                    replace_selection(service, kwargs["derived"])
                    # Ask for the newer generation deliberately. Capturing a
                    # newer record after resolution must still fail the old window.
                    command["vault_generation"] = str(observed["replacement"].generation)
                return resolve(service, **kwargs)

            monkeypatch.setattr(ActiveContextSelectionService, "resolve_request_context", replacing)
            # Input is already deserialized when the server resolves; use the
            # expected next generation to prove old-record/new-context confusion.
            command["vault_generation"] = str(host.selection["context"]["generation"] + 1)
        else:
            factory = batches.build_production_operation_runtime

            def replacing(*args, **kwargs):
                runtime = factory(*args, **kwargs)
                if kwargs.get("operation") is not None and not observed:
                    replace_selection(runtime.carrier.service, runtime.carrier.derived)
                return runtime

            monkeypatch.setattr(batches, "build_production_operation_runtime", replacing)
        result = host.client.post("/api/operations/batches/preview", headers=host.headers, json=command)
        assert result.status_code in {403, 409}, result.text
        assert not (host.runtime.registry.path.parent / "operation-receipts.json").exists()
        if observed:
            assert observed["replacement"].generation == observed["original"].generation + 1
            assert observed["replacement"] is not observed["original"]
    assert [note.read_bytes() for _, note in sources] == before


def test_batch_current_gov_and_native_final_selection_checks(tmp_path, monkeypatch):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    preview = preview_batch(host, batch_command(host, sources))
    from app.governance.governed_write import GovernedWriteAdapter, InvalidDecisionTokenError
    validate = GovernedWriteAdapter.validate_decision_token

    def denied(self, **kwargs):
        raise InvalidDecisionTokenError("current GOV veto")

    monkeypatch.setattr(GovernedWriteAdapter, "validate_decision_token", denied)
    response = batch_action(host, preview)
    assert response.status_code == 403, response.text
    assert batch_inspect(host, preview).status_code == 200
    assert all("Original" in note.read_text() for _, note in sources)
    monkeypatch.setattr(GovernedWriteAdapter, "validate_decision_token", validate)
    import app.operations.write_operations as writes
    write = writes.write_note_from_absolute

    def replaced_at_native(*args, **kwargs):
        host.clear_selection()
        return write(*args, **kwargs)

    monkeypatch.setattr(writes, "write_note_from_absolute", replaced_at_native)
    response = batch_action(host, preview)
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["completed"] == 0
    assert all("Original" in note.read_text() for _, note in sources)


def test_batch_versions_and_confirmation_cannot_expand_original_targets(tmp_path, monkeypatch):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources)
    preview = preview_batch(host, command)
    changed = deepcopy(command)
    changed["items"][0]["artifact_id"] = sources[1][0]
    assert host.client.post("/api/operations/batches/preview", headers=host.headers, json=changed).status_code == 409
    assert host.client.post(f"/api/operations/batches/{preview['batch_id']}/execute", headers=host.headers,
        json={"expected_digest": "0" * 64}).status_code == 409
    assert host.client.post(f"/api/operations/batches/{preview['batch_id']}/execute", headers=host.headers,
        json={"expected_digest": preview["digest"], "items": changed["items"]}).status_code == 422
    sources[0][1].write_text(sources[0][1].read_text() + "Human changed the original.\n")
    result = batch_action(host, preview)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "partial"
    assert result.json()["counts"]["conflicted"] == result.json()["counts"]["completed"] == 1
    assert sources[0][1].read_text().endswith("Human changed the original.\n")
    assert sources[1][1].read_text().endswith("HTTP batch body 1.\n")


@pytest.mark.parametrize("change", ["duplicate_target", "duplicate_request", "too_many", "zero", "limit", "atomic"])
def test_batch_finite_original_set_is_enforced(tmp_path, monkeypatch, change):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    command = batch_command(host, sources)
    if change == "duplicate_target":
        command["items"][1]["artifact_id"] = command["items"][0]["artifact_id"]
    elif change == "duplicate_request":
        command["items"][1]["request_id"] = command["items"][0]["request_id"]
    elif change == "too_many":
        command["items"] *= 51
    elif change == "zero":
        command["items"] = []
    elif change == "limit":
        command["limit"] = 1
    else:
        command["partial_success_policy"] = "atomic"
    result = host.client.post("/api/operations/batches/preview", headers=host.headers, json=command)
    assert result.status_code in {409, 422}, result.text
    assert all("Original" in note.read_text() for _, note in sources)
    assert not (host.runtime.registry.path.parent / "operation-receipts.json").exists()


def test_batch_authentication_and_selected_vault_isolation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api.app import app
    from uuid import uuid4
    from pathlib import Path
    host, sources = production_batch_host(tmp_path, monkeypatch, extra_roots=("two",))
    command = batch_command(host, sources)
    assert host.client.post("/api/operations/batches/preview", json=command).status_code == 401
    remote = TestClient(app, client=("203.0.113.9", 5000))
    assert remote.post("/api/operations/batches/preview", headers=host.headers, json=command).status_code == 401
    preview = preview_batch(host, command)
    foreign_binding = next(binding for binding in host.runtime.registry.load().registrations if binding != host.binding_id)
    other = Path(host.runtime.registry.load().registrations[foreign_binding].path) / "foreign.md"
    identity = str(uuid4())
    other.write_text(f"---\nuuid: {identity}\nartifact_class: human_knowledge\ntrust: human\n---\nForeign.\n")
    selected = host.client.put("/api/companion/active-context/selection", headers=host.headers,
                              json={"vault_binding_ids": [foreign_binding]})
    assert selected.status_code == 200
    assert batch_inspect(host, preview).status_code == 404
    assert batch_action(host, preview, "cancel").status_code == 404
    assert batch_action(host, preview).status_code == 404
    assert other.read_text().endswith("Foreign.\n")
    assert all("Original" in note.read_text() for _, note in sources)



@pytest.mark.parametrize("kind", ["artifact.update", "artifact.rename"])
def test_original_deadline_is_rechecked_at_real_native_frontier(tmp_path, monkeypatch, kind):
    host, sources = production_batch_host(tmp_path, monkeypatch)
    preview = preview_batch(host, batch_command(host, sources, kind=kind))
    before = [note.read_bytes() for _, note in sources]
    deadline = preview["policy_ceiling"]["expires_at"]
    import app.api.operation_runtime as runtime
    import app.governance.governed_write as governed

    def expire():
        monkeypatch.setattr(runtime, "time", lambda: deadline + 1)
        monkeypatch.setattr(governed, "time", lambda: deadline + 1)

    if kind == "artifact.update":
        import app.operations.write_operations as writes
        write = writes.write_note_from_absolute

        def waited(*args, **kwargs):
            expire()
            return write(*args, **kwargs)

        monkeypatch.setattr(writes, "write_note_from_absolute", waited)
    else:
        from app.knowledge.placement import KnowledgePlacementOwner
        store = KnowledgePlacementOwner._store

        def waited(owner, root, state, name, value):
            store(owner, root, state, name, value)
            if value["phase"] == "prepared":
                expire()

        monkeypatch.setattr(KnowledgePlacementOwner, "_store", waited)
    response = batch_action(host, preview)
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["completed"] == 0
    assert response.json()["policy_ceiling"]["expires_at"] == deadline
    assert [note.read_bytes() for _, note in sources] == before
    assert not any((host.root / "Notes" / f"renamed-{index}.md").exists() for index in range(len(sources)))


@pytest.mark.parametrize("fault", ["missing", "corrupt", "not_host_admitted"])
def test_retained_batch_requires_complete_authentic_host_composition(tmp_path, monkeypatch, fault):
    import hashlib
    import json
    host, sources = production_batch_host(tmp_path, monkeypatch)
    preview = preview_batch(host, batch_command(host, sources))
    path = host.runtime.registry.path.parent / "operation-receipts.json"
    if fault == "missing":
        preview["batch_id"] = "absent"
    elif fault == "corrupt":
        path.write_text("{corrupt")
    else:
        records = json.loads(path.read_text())
        # Produce an internally digest-consistent direct-coordinator record
        # lacking this production host's admission. Its digest is no authority.
        record = records["ygg.batch:batch-1"]
        frozen = record["outcome"]["extensions"]["batch"]["frozen"]
        frozen["selector"].pop("producer")
        digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        record["intent_digest"] = digest
        path.write_text(json.dumps(records))
        preview["digest"] = digest
    response = batch_action(host, preview)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "batch_state_unavailable"
    assert all("Original" in note.read_text() for _, note in sources)
