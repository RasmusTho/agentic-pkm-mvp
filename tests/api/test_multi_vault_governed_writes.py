"""Production capture token and immutable selected-membership enforcement."""

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selections
from app.api.routes import capture
from app.governance.governed_write import GovernedWriteAdapter, InvalidDecisionTokenError
from app.instance.context_bound_write import require_selected_targets
from app.vault.active_context_v1 import WorkspaceState
from tests._mvr03_principal_harness import provisioned_instance, principal_store
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault


def setup_capture(tmp_path, monkeypatch):
    runtime, first, extra, _ = provisioned_instance(tmp_path, extra_roots=("other",))
    for registration in (first, *extra):
        initialize_test_vault(Path(registration.path))
        runtime.complete_initialization(
            registration.vault_binding_id,
            vault_id="vault-" + registration.vault_binding_id,
            local_instance_id=registration.local_instance_id,
        )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setattr(capture, "_offer_question_registration_proposal", lambda **_: None)
    selections.reset_selection_store_for_tests()
    client = TestClient(app)
    result = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [first.vault_binding_id]},
    )
    assert result.status_code == 201, result.text
    return (
        runtime,
        first,
        extra[0],
        client,
        {"X-Active-Context-Session": result.json()["context_selection_id"]},
    )


def test_capture_uses_explicit_authorized_target_and_receipt(tmp_path, monkeypatch):
    runtime, first, _, client, headers = setup_capture(tmp_path, monkeypatch)
    response = client.post(
        "/api/companion/capture/scoped",
        json={"text": "Keep me", "target_binding_id": first.vault_binding_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()["governed_write"]
    assert payload["decision_token"]["target_binding_id"] == first.vault_binding_id
    context = payload["authority_receipt"]["active_context"]
    assert context["instance_identity"] == runtime.registry.load().app_install_id
    assert [b["vault_binding_id"] for b in context["source_bindings"]] == [first.vault_binding_id]
    assert (
        context["selection_capability_digest"]
        and headers["X-Active-Context-Session"] not in response.text
    )
    assert "Keep me" in Path(first.path, "Inbox/inbox.md").read_text()
    assert payload["authority_receipt"]["receipt_id"] in (tmp_path / "outbox.jsonl").read_text()


def test_write_target_must_belong_to_active_context_set(tmp_path, monkeypatch):
    _, first, other, client, headers = setup_capture(tmp_path, monkeypatch)
    for target in (None, other.vault_binding_id):
        result = client.post(
            "/api/companion/capture/scoped",
            json={"text": "Forbidden", "target_binding_id": target},
            headers=headers,
        )
        assert result.status_code == 409, result.text
    assert not Path(first.path, "Inbox/inbox.md").exists()
    assert not Path(other.path, "Inbox/inbox.md").exists()


def test_authority_change_blocks_inflight_write_before_commit(tmp_path, monkeypatch):
    runtime, first, _, client, headers = setup_capture(tmp_path, monkeypatch)
    original = capture._GOVERNED_WRITE_ADAPTER.bind_context

    def change(grant, **kwargs):
        bound = original(grant, **kwargs)
        principal_store(runtime).rotate_credential(
            credential="rotated-for-test", _capability=STORAGE_MUTATION_CAPABILITY
        )
        return bound

    monkeypatch.setattr(capture._GOVERNED_WRITE_ADAPTER, "bind_context", change)
    result = client.post(
        "/api/companion/capture/scoped",
        json={"text": "Forbidden", "target_binding_id": first.vault_binding_id},
        headers=headers,
    )
    assert result.status_code == 409, result.text
    assert not Path(first.path, "Inbox/inbox.md").exists()


def test_capture_token_binds_exact_active_context_and_target_membership(tmp_path, monkeypatch):
    _, first, other, client, headers = setup_capture(tmp_path, monkeypatch)
    original = capture._GOVERNED_WRITE_ADAPTER.bind_context
    seen = []

    def collect(grant, **kwargs):
        bound = original(grant, **kwargs)
        seen.append(bound.decision_token)
        return bound

    monkeypatch.setattr(capture._GOVERNED_WRITE_ADAPTER, "bind_context", collect)
    result = client.post(
        "/api/companion/capture/scoped",
        json={"text": "Bound", "target_binding_id": first.vault_binding_id},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    token = seen[0]
    context = token.active_context
    changes = [
        dict(generation=context.generation + 1),
        dict(workspace=WorkspaceState.bound("foreign")),
        dict(sphere_memberships=("foreign",)),
        dict(situated_identity="foreign"),
        dict(selection_capability_digest="foreign"),
        dict(source_bindings=()),
    ]
    for change in changes:
        with pytest.raises(InvalidDecisionTokenError):
            GovernedWriteAdapter().validate_context(
                token, context=replace(context, **change), target_binding_id=first.vault_binding_id
            )
    with pytest.raises(InvalidDecisionTokenError):
        GovernedWriteAdapter().validate_context(
            replace(token, active_context=None),
            context=context,
            target_binding_id=first.vault_binding_id,
        )
    with pytest.raises(InvalidDecisionTokenError):
        require_selected_targets(context, (first.vault_binding_id, other.vault_binding_id))


def test_full_capture_proposal_stays_inside_authorized_effect_window(tmp_path, monkeypatch):
    from app.standing_questions.registration import propose_question_registration
    from app.components.llm.question_intent_classifier import (
        QuestionIntentClassifierCognition,
        QuestionIntentClassification,
        QuestionIntentClass,
    )
    from app.instance.binding_effect_lease import BindingEffectLeaseManager

    runtime, first, _, client, headers = setup_capture(tmp_path, monkeypatch)
    # Keep the real post-append proposal path. Only model classification is external.
    monkeypatch.setattr(
        capture,
        "_offer_question_registration_proposal",
        lambda **kwargs: propose_question_registration(
            capture_note_path=kwargs["vault_root"] / kwargs["note_rel"],
            vault_root=kwargs["vault_root"],
            trace_id=kwargs["trace_id"],
        ),
    )
    leases = BindingEffectLeaseManager.for_runtime(
        registry_store=runtime.registry,
        ownership_root=runtime.ledger.root,
        state_root=runtime.layout.root / "binding-effect-leases",
    )

    def classify(self, **kwargs):
        assert leases.observe(first.vault_binding_id).shared_count == 1
        return QuestionIntentClassification(
            intent_class=QuestionIntentClass.QUESTION_REGISTRATION,
            extracted_text="What should I learn?",
            classified=True,
        )

    monkeypatch.setattr(QuestionIntentClassifierCognition, "classify", classify)
    result = client.post(
        "/api/companion/capture/scoped",
        headers=headers,
        json={"text": "What should I learn?", "target_binding_id": first.vault_binding_id},
    )
    assert result.status_code == 200, result.text
    assert result.json()["registration_state"] == "proposal_pending"
    assert "Registrera stående fråga" in Path(first.path, "Inbox/inbox.md").read_text()


@pytest.mark.parametrize(
    "endpoint", ["/api/companion/capture", "/api/companion/capture/compatibility"]
)
def test_legacy_capture_revalidates_context_before_io(tmp_path, monkeypatch, endpoint):
    from app.api.compatibility_mutation import issue_compatibility_precondition
    from app.instance.settings_rebind import _install_dormant_settings_rebind
    from app.vault.manager import VaultManager
    from app.vault.app_local import AppLocalSettingsStore
    import app.api.routes.vault_resolution as resolution

    runtime, first, _, client, _ = setup_capture(tmp_path, monkeypatch)
    _install_dormant_settings_rebind(
        runtime.registry, binding_id=first.vault_binding_id, _capability=STORAGE_MUTATION_CAPABILITY
    )
    # Use the normal compatibility resolver's selected initialized root.
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "legacy-local.md"))
    monkeypatch.setattr(resolution, "get_vault_manager", lambda: manager)
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    manager.select_vault(Path(first.path), remember=False)
    headers = {}
    if endpoint.endswith("compatibility"):
        headers["X-Compatibility-Write-Precondition"] = issue_compatibility_precondition(
            binding_id=first.vault_binding_id,
            principal_id=principal_store(runtime).require().local_operator_role_id,
            registry=runtime.registry,
        )
    original = capture._GOVERNED_WRITE_ADAPTER.bind_context

    def revoke(grant, **kwargs):
        bound = original(grant, **kwargs)
        principal_store(runtime).rotate_credential(
            credential="changed-test-key", _capability=STORAGE_MUTATION_CAPABILITY
        )
        return bound

    monkeypatch.setattr(capture._GOVERNED_WRITE_ADAPTER, "bind_context", revoke)
    result = client.post(endpoint, headers=headers, json={"text": "Must be blocked"})
    assert result.status_code == 409, result.text
    assert not Path(first.path, "Inbox/inbox.md").exists()
