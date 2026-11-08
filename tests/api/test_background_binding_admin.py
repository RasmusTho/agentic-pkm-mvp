"""MVR-06 (#2143) governed background-binding administration (API + headless CLI).

Contract: docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md. MVR-06A (#3863) ships the
staged surface: list/inspect read durable intent without writing, and every intent-changing
command fails ``capability_not_ready`` until the MVR-06B supervisor handoff. Later children
add their activation tests here.

Every test drives the production producers (shipped cutover CLI, API router, CLI) rather
than seeding the registry.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.active_context_selection as selection_routes
from app.api.app import app
from app.instance.background_intent import (
    BACKGROUND_INTENT_KEY,
    HANDOFF_PENDING,
    INTENT_MODE_COMPATIBILITY,
)
from tests._mvr06_background_harness import cli, mvr06_instance


def _files_digest(runtime) -> dict[str, str]:
    """Every durable byte the admin surface could touch: registry generation + role."""

    directory = runtime.layout.registry_path.parent
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file() and not path.name.endswith(".lock")
    }


@pytest.fixture()
def staged(tmp_path: Path, monkeypatch):
    runtime, first, extra, _operator, _receipt = mvr06_instance(
        tmp_path, extra_roots=("two",)
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    selection_routes.reset_selection_store_for_tests()
    return runtime, first.vault_binding_id, extra[0].vault_binding_id, TestClient(app)


def test_mvr06a_selection_cannot_mutate_staged_intent(staged, tmp_path: Path) -> None:
    runtime, binding_a, binding_b, client = staged
    snapshot = runtime.registry.load()
    intent_before = snapshot.extensions[BACKGROUND_INTENT_KEY]
    # The staged MVR-06A intent: compatibility mode, nothing materialized, because the
    # legacy picker bridge still owns the single watcher binding.
    assert intent_before["mode"] == INTENT_MODE_COMPATIBILITY
    assert intent_before["compatibilityHandoff"] == HANDOFF_PENDING
    assert intent_before["compatibilityBindingId"] is None
    assert intent_before["backgroundVaultBindingIds"] == []
    role_digest_before = _files_digest(runtime)["background-runtime-role.json"]

    # -- request/session selection, through the production selection API -----------------
    for bindings in ([binding_a], [binding_b], [binding_a, binding_b]):
        created = client.post(
            "/api/companion/active-context/selection",
            json={"vault_binding_ids": bindings},
        )
        assert created.status_code == 201, created.text
        bearer = created.json()["context_selection_id"]
        reread = client.get(
            "/api/companion/active-context/selection",
            headers={"X-Active-Context-Session": bearer},
        )
        assert reread.status_code == 200, reread.text
        # A per-request override carrier is selection too; it never enrols a binding.
        scoped = client.get(
            "/api/companion/vault/notes/scoped",
            headers={"X-Active-Context-Override": bearer},
        )
        assert scoped.status_code in {200, 409}, scoped.text

    # Selection may maintain its own foreground state, but never background intent or
    # the delegated background role.
    after = runtime.registry.load()
    assert after.extensions[BACKGROUND_INTENT_KEY] == intent_before
    assert _files_digest(runtime)["background-runtime-role.json"] == role_digest_before
    assert binding_b not in after.extensions[BACKGROUND_INTENT_KEY]["backgroundVaultBindingIds"]

    # -- list/inspect are read-only on both production surfaces ---------------------------
    digest_after_selection = _files_digest(runtime)
    registry_revision = after.revision

    listed = client.get("/api/instance/background-bindings")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["initialized"] is True
    assert body["mode"] == INTENT_MODE_COMPATIBILITY
    assert body["compatibility_handoff"] == HANDOFF_PENDING
    assert body["compatibility_binding_id"] is None
    assert body["background_vault_binding_ids"] == []
    assert body["explicit_empty"] is False
    assert body["legacy_bridge"]["binding_id"] == binding_a
    assert body["intent_mutations"] == "capability_not_ready"
    assert body["registry_revision"] == registry_revision

    bridge = client.get(f"/api/instance/background-bindings/{binding_a}").json()
    assert bridge["background_status"] == "legacy_bridge_binding"
    other = client.get(f"/api/instance/background-bindings/{binding_b}").json()
    assert other["background_status"] == "not_enrolled" and other["registered"] is True

    registry_path = str(runtime.layout.registry_path)
    cli_list = cli("background-binding-list", "--registry-path", registry_path)
    assert cli_list["_exit_code"] == 0
    assert {key: cli_list[key] for key in body} == body
    cli_inspect = cli(
        "background-binding-inspect",
        "--registry-path",
        registry_path,
        "--vault-binding-id",
        binding_b,
    )
    assert cli_inspect["background_status"] == "not_enrolled"

    # Redaction: binding ids and revisions only, never a content root.
    for text in (listed.text, str(cli_list), str(cli_inspect)):
        assert str(tmp_path) not in text

    # Read-only: not a byte of the registry generation or role record moved.
    assert runtime.registry.load().revision == registry_revision
    assert _files_digest(runtime) == digest_after_selection


def test_mvr06a_rejects_all_intent_mutations_until_supervisor_handoff(staged) -> None:
    runtime, binding_a, binding_b, client = staged
    registry_path = str(runtime.layout.registry_path)
    before = runtime.registry.load()
    bridge_before = before.settings_rebind
    digest_before = _files_digest(runtime)

    # Every intent-changing API command, including add-current, remove-current, adding a
    # second binding, and removing a nonmember, is sealed before it reads or writes.
    api_attempts = [
        client.post("/api/instance/background-bindings", json={"vault_binding_id": binding_a}),
        client.post("/api/instance/background-bindings", json={"vault_binding_id": binding_b}),
        client.delete(f"/api/instance/background-bindings/{binding_a}"),
        client.delete(f"/api/instance/background-bindings/{binding_b}"),
        client.delete("/api/instance/background-bindings/binding-never-registered"),
    ]
    for response in api_attempts:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["error"] == "capability_not_ready"

    for command in ("background-binding-add", "background-binding-remove"):
        for binding in (binding_a, binding_b, "binding-never-registered"):
            receipt = cli(command, "--registry-path", registry_path, "--vault-binding-id", binding)
            assert receipt["_exit_code"] == 2, receipt
            assert receipt["ok"] is False
            assert receipt["error"] == "capability_not_ready"

    # Durable intent cannot diverge from the still-authoritative legacy watcher: neither
    # the intent nor the bridge record nor any other durable byte changed.
    after = runtime.registry.load()
    assert after.revision == before.revision
    assert after.extensions[BACKGROUND_INTENT_KEY] == before.extensions[BACKGROUND_INTENT_KEY]
    assert after.settings_rebind == bridge_before
    assert _files_digest(runtime) == digest_before
    listed = client.get("/api/instance/background-bindings").json()
    assert listed["mode"] == INTENT_MODE_COMPATIBILITY
    assert listed["legacy_bridge"]["binding_id"] == binding_a

    # The mutating routes stay behind the Companion state-change authentication boundary.
    from app.settings import settings

    previous = settings.api_key
    settings.api_key = "background-admin-test-key"
    try:
        remote = TestClient(app, base_url="http://remote.example")
        denied = remote.post(
            "/api/instance/background-bindings",
            json={"vault_binding_id": binding_a},
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
    finally:
        settings.api_key = previous
    assert denied.status_code in {401, 403}, denied.text
    assert _files_digest(runtime) == digest_before


# -- MVR-06B (#3864): governed singleton/explicit-empty producers ------------------------


@pytest.fixture()
def handed_off(tmp_path: Path, monkeypatch):
    from tests._mvr06b_handoff_harness import mvr06b_instance, stub_settings_reload

    runtime, first, extra = mvr06b_instance(tmp_path, monkeypatch)
    stub_settings_reload(monkeypatch)
    selection_routes.reset_selection_store_for_tests()
    return runtime, first.vault_binding_id, extra[0].vault_binding_id, TestClient(app)


def _deny_content_authority(monkeypatch, denied: str) -> None:
    from app.governance.binding_authority import RegistryBindingAuthorizer
    from tests.helpers.revoked_binding_authorizer import RevokedBindingAuthorizer

    original = RegistryBindingAuthorizer.authorize

    def authorize(self, request):
        if request.vault_binding_id != denied:
            return original(self, request)
        revoked = RevokedBindingAuthorizer(self)
        revoked.revoke_for_test(denied)
        return revoked.authorize(request)

    monkeypatch.setattr(RegistryBindingAuthorizer, "authorize", authorize)


def _intent(runtime):
    from app.instance.background_supervisor import stored_intent

    return stored_intent(runtime.registry.load())


def test_mvr06b_commands_allow_only_singleton_or_empty_intent(
    handed_off, monkeypatch
) -> None:
    from app.events.topic_schema_registry import is_registered_topic, validate_topic_payload
    from app.events.types import INSTANCE_BACKGROUND_INTENT_CHANGED

    runtime, binding_a, binding_b, client = handed_off
    registry_path = str(runtime.layout.registry_path)
    listing = client.get("/api/instance/background-bindings").json()
    assert listing["intent_mutations"] == "singleton_or_empty"

    # Unknown binding: refused before any write.
    before = _intent(runtime)
    unknown = client.post("/api/instance/background-bindings", json={"vault_binding_id": "nope"})
    assert unknown.status_code == 404
    assert _intent(runtime) == before

    # Unauthorized binding: refused before any write (CLI and API share the service).
    _deny_content_authority(monkeypatch, binding_b)
    response = client.post(
        "/api/instance/background-bindings", json={"vault_binding_id": binding_b}
    )
    assert response.status_code == 403
    cli_refusal = cli(
        "background-binding-add", "--registry-path", registry_path,
        "--vault-binding-id", binding_b, "--consumer", "cli",
    )
    assert cli_refusal["_exit_code"] != 0
    assert _intent(runtime) == before
    monkeypatch.undo()

    # A singleton add through the API commits exactly one durable revision + one hint.
    from tests._mvr06b_handoff_harness import bind_runtime_env, stub_settings_reload

    bind_runtime_env(monkeypatch, runtime)
    stub_settings_reload(monkeypatch)
    captured: list = []
    from app.services import outbox as outbox_module

    monkeypatch.setattr(
        outbox_module, "write_outbox_event",
        lambda event, conn=None, **kw: captured.append((event, kw["idempotency_key"])) or "k",
    )
    added = client.post("/api/instance/background-bindings", json={"vault_binding_id": binding_a})
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["mode"] == "explicit" and body["background_vault_binding_ids"] == [binding_a]
    assert body["intent_revision"] == before.revision + 1
    assert len(captured) == 1
    event, key = captured[0]
    assert event.event_type == INSTANCE_BACKGROUND_INTENT_CHANGED
    assert is_registered_topic(INSTANCE_BACKGROUND_INTENT_CHANGED)
    validate_topic_payload(INSTANCE_BACKGROUND_INTENT_CHANGED, event.payload)
    assert event.payload["intent_revision"] == body["intent_revision"]

    # Idempotent re-add: no new revision, no second hint.
    again = client.post("/api/instance/background-bindings", json={"vault_binding_id": binding_a})
    assert again.status_code == 200 and again.json()["changed"] is False
    assert len(captured) == 1

    # A second binding is gated: capability_not_ready, nothing changes.
    second = client.post("/api/instance/background-bindings", json={"vault_binding_id": binding_b})
    assert second.status_code == 409
    assert second.json()["detail"]["error"] == "capability_not_ready"
    assert _intent(runtime).background_vault_binding_ids == (binding_a,)

    # The headless CLI removes to explicit-empty through the same service.
    removed = cli(
        "background-binding-remove", "--registry-path", registry_path,
        "--vault-binding-id", binding_a, "--consumer", "cli",
    )
    assert removed["_exit_code"] == 0, removed
    assert removed["explicit_empty"] is True
    listed = cli("background-binding-list", "--registry-path", registry_path, "--consumer", "cli")
    assert listed["explicit_empty"] is True and listed["background_vault_binding_ids"] == []


def test_first_explicit_mutation_snapshots_compatibility_singleton_before_apply(
    tmp_path: Path, monkeypatch
) -> None:
    from tests._mvr06b_handoff_harness import (
        admin,
        background_ids,
        mvr06b_instance,
        stub_settings_reload,
        supervisor,
    )

    cases = {
        "remove-current": ("remove", "a", "explicit", ()),
        "add-current": ("add", "a", "explicit", ("a",)),
        "remove-nonmember": ("remove", "b", "explicit", ("a",)),
    }
    for index, (name, (command, which, mode, expected)) in enumerate(cases.items()):
        runtime, first, (second,) = mvr06b_instance(tmp_path / str(index), monkeypatch)
        stub_settings_reload(monkeypatch)
        ids = {"a": first.vault_binding_id, "b": second.vault_binding_id}
        assert background_ids(runtime) == (ids["a"],), name
        getattr(admin(runtime), command)(ids[which])
        intent = _intent(runtime)
        assert intent.mode == mode, name
        assert intent.background_vault_binding_ids == tuple(ids[item] for item in expected), name

    # add-different against the non-empty compatibility snapshot would yield two members:
    # rejected as a gated second enrollment, mode and lifecycle untouched.
    runtime, first, (second,) = mvr06b_instance(tmp_path / "different", monkeypatch)
    stub_settings_reload(monkeypatch)
    lifecycle = supervisor(runtime).start()
    before = _intent(runtime)
    from app.instance.background_authority import BackgroundIntentNotReadyError

    with pytest.raises(BackgroundIntentNotReadyError, match="second background binding"):
        admin(runtime).add(second.vault_binding_id)
    assert _intent(runtime) == before
    assert before.mode == "compatibility"
    assert supervisor(runtime).start().binding_id == lifecycle.binding_id == first.vault_binding_id

    # Truthful no-vault compatibility snapshots as the empty set: add yields a singleton.
    runtime, first, (second,) = mvr06b_instance(tmp_path / "novault", monkeypatch)
    stub_settings_reload(monkeypatch)
    from app.instance.runtime import open_default_vault_service

    open_default_vault_service(runtime.layout.registry_path).clear()
    assert background_ids(runtime) == ()
    admin(runtime).add(second.vault_binding_id)
    assert _intent(runtime).background_vault_binding_ids == (second.vault_binding_id,)


def test_stale_binding_intent_can_be_removed_without_content_authority(
    handed_off, monkeypatch
) -> None:
    runtime, binding_a, binding_b, client = handed_off
    from tests._mvr06b_handoff_harness import admin

    admin(runtime).add(binding_a)
    # Content authority is lost: add is refused, but instance-authorized remove clears it.
    _deny_content_authority(monkeypatch, binding_a)
    from app.instance.background_supervisor import BackgroundLifecycleError

    with pytest.raises(BackgroundLifecycleError):
        admin(runtime).add(binding_a)
    response = client.delete(f"/api/instance/background-bindings/{binding_a}")
    assert response.status_code == 200, response.text
    assert response.json()["explicit_empty"] is True
    # Idempotent, even for a binding with no registry entry at all.
    again = client.delete("/api/instance/background-bindings/binding-never-registered")
    assert again.status_code == 200 and again.json()["changed"] is False
    monkeypatch.undo()

    # A member whose registration disappears stays as stale intent; remove still clears.
    from tests._mvr06b_handoff_harness import bind_runtime_env, stub_settings_reload

    bind_runtime_env(monkeypatch, runtime)
    stub_settings_reload(monkeypatch)
    admin(runtime).add(binding_b)
    runtime.remove(binding_b)
    assert binding_b not in runtime.registry.load().registrations
    assert _intent(runtime).background_vault_binding_ids == (binding_b,)
    removed = admin(runtime).remove(binding_b)
    assert removed["explicit_empty"] is True and removed["changed"] is True
    with pytest.raises(Exception, match="unknown vault_binding_id"):
        admin(runtime).add(binding_b)


def test_mvr06c_rejects_many_until_mvr06d_dispatch_gate(handed_off) -> None:
    """MVR-06C generalizes the supervisor but production many-binding stays sealed.

    Enrollment through the API and the headless CLI, the registry's intent commit, the
    supervisor record's binding capacity, and the process supervisor all keep refusing a
    second binding until MVR-06D atomically enables its matching queue-dispatch contract;
    only the private harness capability can construct a many-binding supervisor.
    """

    from dataclasses import replace

    from app.instance.background_intent import (
        BACKGROUND_SUPERVISOR_KEY,
        BackgroundSupervisorRecord,
    )
    from app.instance.background_supervisor import (
        BackgroundLifecycleSupervisor,
        process_background_supervisor,
    )
    from app.instance.vault_registry import CapabilityNotReadyError, RegistryError

    runtime, binding_a, binding_b, client = handed_off
    registry_path = str(runtime.layout.registry_path)
    added = client.post("/api/instance/background-bindings", json={"vault_binding_id": binding_a})
    assert added.status_code == 200, added.text
    enrolled = _intent(runtime)
    assert enrolled.background_vault_binding_ids == (binding_a,)
    files_before = _files_digest(runtime)

    refused = client.post("/api/instance/background-bindings", json={"vault_binding_id": binding_b})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["error"] == "capability_not_ready"
    assert "MVR-06D" in detail["message"] and "queue-dispatch" in detail["message"]
    cli_refusal = cli(
        "background-binding-add", "--registry-path", registry_path,
        "--vault-binding-id", binding_b, "--consumer", "cli",
    )
    assert cli_refusal["_exit_code"] != 0 and cli_refusal["error"] == "capability_not_ready"
    assert _files_digest(runtime) == files_before
    assert client.get("/api/instance/background-bindings").json()["intent_mutations"] == (
        "singleton_or_empty"
    )

    # The durable store itself refuses many-binding intent, whatever the producer: the
    # snapshot validator every registry read and write runs rejects it.
    from app.instance.vault_registry import _validate_background_supervisor_state

    many = replace(
        enrolled,
        revision=enrolled.revision + 1,
        background_vault_binding_ids=tuple(sorted((binding_a, binding_b))),
    )
    with pytest.raises(RegistryError, match="sealed until MVR-06D"):
        _validate_background_supervisor_state(many, runtime.registry.load().extensions)
    record = BackgroundSupervisorRecord.from_payload(
        runtime.registry.load().extensions[BACKGROUND_SUPERVISOR_KEY]
    )
    assert record.max_bindings == 1
    assert _files_digest(runtime) == files_before

    # The generalized supervisor is dormant: production supervises the singleton only,
    # and constructing a many-binding supervisor needs the private harness capability.
    production = process_background_supervisor("worker")
    assert production is not None
    assert production.reconcile().binding_id == binding_a
    health = production.health()
    assert health["many_binding"] == "dormant" and health["binding_capacity"] == 1
    for capability in (None, object()):
        with pytest.raises(CapabilityNotReadyError, match="dormant until MVR-06D"):
            BackgroundLifecycleSupervisor.for_runtime(
                registry_path=runtime.layout.registry_path,
                ownership_root=runtime.ledger.root,
                channel_id=runtime.layout.channel_id,
                consumer="worker",
                internal_binding_ids=(binding_a, binding_b),
                _harness_capability=capability,
            )
