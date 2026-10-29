"""Production registry, principal, selection and native-note operation harness."""
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection, capture
from app.knowledge.write_ops import read_note_text_with_version
from tests._mvr03_principal_harness import provisioned_instance
from tests.api._vault_test_helpers import bind_initialized_vault


@dataclass
class OperationHost:
    runtime: object
    binding_id: str
    root: Path
    note: Path
    artifact_id: str
    client: TestClient
    selection: dict
    headers: dict

    def clear_selection(self):
        from app.api.routes.active_context_selection import build_selection_service, get_selection_store
        service = build_selection_service(get_selection_store())
        derived = service.derive("trusted_loopback")
        service.selection_store.clear(self.selection["context_selection_id"],
            principal=derived.principal, instance_identity=derived.instance_identity)

    def command(self, operation_id="artifact.update", request_id="update-1", **updates):
        data = dict(operation_id=operation_id, request_id=request_id,
            active_context_ref=self.selection["context"]["context_id"],
            vault_generation=str(self.selection["context"]["generation"]),
            target_binding_id=self.binding_id,
            targets=[{"artifact_id": self.artifact_id}],
            arguments={"body": "Updated body.\n"},
            expected_version=read_note_text_with_version(self.note)[1])
        data.update(updates)
        return data


def production_operation_host(tmp_path, monkeypatch, *, extra_roots=()):
    runtime, registration, extra, principal = provisioned_instance(tmp_path, extra_roots=extra_roots)
    root = Path(registration.path)
    for selected in (registration, *extra):
        bind_initialized_vault(monkeypatch, Path(selected.path), store_dir=tmp_path,
                               channel=runtime.layout.channel_id)
        runtime.complete_initialization(selected.vault_binding_id,
            vault_id="vault-" + selected.vault_binding_id,
            local_instance_id=selected.local_instance_id)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.delenv("PKM_CONFIG_ROOT", raising=False)
    monkeypatch.setattr(capture, "_offer_question_registration_proposal", lambda **_: None)
    active_context_selection.reset_selection_store_for_tests()
    note = root / "Notes" / "human.md"
    note.parent.mkdir(exist_ok=True)
    artifact_id = str(uuid4())
    note.write_text(f"---\nuuid: {artifact_id}\nartifact_class: human_knowledge\ntrust: human\n---\nOriginal.\n")
    client = TestClient(app)
    selected = client.post("/api/companion/active-context/selection",
        json={"vault_binding_ids": [registration.vault_binding_id]})
    assert selected.status_code == 201, selected.text
    selection = selected.json()
    return OperationHost(runtime, registration.vault_binding_id, root, note,
                         artifact_id, client, selection,
                         {"X-Active-Context-Session": selection["context_selection_id"]})
