"""MVR-02 (#3856): authenticated API + headless CLI default-vault administration.

Contract: docs/MULTI_VAULT_RUNTIME/RESOLVE_INSTANCE_DEFAULT_VAULT.md

These tests drive the two *production* producers rather than seeding the registry
or calling an internal setter, and assert that both converge on one locked
registry state, one redacted receipt, and one versioned mutation event.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.events.topic_schema_registry import (
    current_schema_ref,
    is_registered_topic,
    validate_topic_payload,
)
from app.events.types import INSTANCE_DEFAULT_VAULT_CHANGED
from app.instance.runtime import main as instance_runtime_main
from app.instance.vault_registry import (
    DEFAULT_PROVENANCE_EXPLICIT,
    RegistryDefaultConflict,
    VaultRegistryStore,
)
from tests._mvr_default_vault_harness import active_runtime, reopen_runtime


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def bound_instance(tmp_path, monkeypatch):
    runtime, first, extra = active_runtime(tmp_path, extra_roots=("two",))
    monkeypatch.setenv(
        "INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path)
    )
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    return runtime, first, extra[0]


@pytest.fixture()
def captured_events(monkeypatch) -> list[tuple[object, str]]:
    from app.services import outbox as outbox_module

    emitted: list[tuple[object, str]] = []

    def _capture(event, conn=None, *, idempotency_key: str, required_db: bool = False):
        emitted.append((event, idempotency_key))
        return idempotency_key

    monkeypatch.setattr(outbox_module, "write_outbox_event", _capture)
    return emitted


def _cli(*args: str) -> dict[str, object]:
    from contextlib import redirect_stdout
    from io import StringIO

    buffer = StringIO()
    with redirect_stdout(buffer):
        code = instance_runtime_main(list(args))
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    payload["_exit_code"] = code
    return payload


def test_production_default_commands_share_one_service(
    client, bound_instance, tmp_path, captured_events
) -> None:
    runtime, first, second = bound_instance
    registry_path = str(runtime.layout.registry_path)

    # The API sets the default...
    response = client.put(
        "/api/instance/default-vault",
        json={"vault_binding_id": first.vault_binding_id},
    )
    assert response.status_code == 200, response.text
    api_receipt = response.json()
    assert api_receipt["vault_binding_id"] == first.vault_binding_id
    assert api_receipt["provenance"] == DEFAULT_PROVENANCE_EXPLICIT

    # ...and the headless CLI observes exactly the same locked registry state.
    cli_get = _cli("default-vault-get", "--registry-path", registry_path)
    assert cli_get["_exit_code"] == 0
    assert cli_get["vault_binding_id"] == first.vault_binding_id
    assert cli_get["registry_revision"] == api_receipt["registry_revision"]

    # The CLI replaces it, and the API observes that.
    cli_set = _cli(
        "default-vault-set",
        "--registry-path",
        registry_path,
        "--vault-binding-id",
        second.vault_binding_id,
    )
    assert cli_set["_exit_code"] == 0
    assert cli_set["previous_vault_binding_id"] == first.vault_binding_id
    assert client.get("/api/instance/default-vault").json()["vault_binding_id"] == (
        second.vault_binding_id
    )

    # Neither producer emits a content-root path or any other raw binding payload.
    for receipt in (api_receipt, cli_get, cli_set):
        rendered = json.dumps(receipt)
        assert str(tmp_path) not in rendered
        assert first.path not in rendered

    # Both reject an unknown/unauthorized binding without changing state.
    rejected = client.put(
        "/api/instance/default-vault", json={"vault_binding_id": "binding-nope"}
    )
    assert rejected.status_code == 404
    cli_rejected = _cli(
        "default-vault-set",
        "--registry-path",
        registry_path,
        "--vault-binding-id",
        "binding-nope",
    )
    assert cli_rejected["_exit_code"] == 1
    assert cli_rejected["ok"] is False
    assert runtime.registry.load().default_vault_binding_id == second.vault_binding_id

    # Clear converges too, and survives restart as an explicit absence.
    assert client.delete("/api/instance/default-vault").status_code == 200
    assert reopen_runtime(runtime, tmp_path).registry.load().default_vault_binding_id is None
    assert (
        _cli("default-vault-get", "--registry-path", registry_path)["vault_binding_id"]
        is None
    )


def test_default_mutation_publishes_versioned_rebind_event(
    client, bound_instance, captured_events
) -> None:
    runtime, first, second = bound_instance

    response = client.put(
        "/api/instance/default-vault",
        json={"vault_binding_id": first.vault_binding_id},
    )
    assert response.status_code == 200, response.text

    assert len(captured_events) == 1
    event, idempotency_key = captured_events[0]
    assert event.event_type == INSTANCE_DEFAULT_VAULT_CHANGED
    assert idempotency_key
    payload = event.payload
    assert payload["event_version"] == 1
    assert payload["registry_revision"] == runtime.registry.load().revision
    assert payload["vault_binding_id"] == first.vault_binding_id
    assert payload["previous_vault_binding_id"] is None
    assert payload["provenance"] == DEFAULT_PROVENANCE_EXPLICIT

    # The topic is a registered KERNEL-08 schema and the payload validates.
    assert is_registered_topic(INSTANCE_DEFAULT_VAULT_CHANGED)
    assert current_schema_ref(INSTANCE_DEFAULT_VAULT_CHANGED) == (
        f"{INSTANCE_DEFAULT_VAULT_CHANGED}.v1"
    )
    validate_topic_payload(INSTANCE_DEFAULT_VAULT_CHANGED, payload)

    # No raw binding payload: no path, ref, name, or filesystem identity.
    assert set(payload) == {
        "event_version",
        "registry_revision",
        "vault_binding_id",
        "previous_vault_binding_id",
        "provenance",
    }

    # Clearing publishes exactly one further event carrying the new revision.
    assert client.delete("/api/instance/default-vault").status_code == 200
    assert len(captured_events) == 2
    cleared_payload = captured_events[1][0].payload
    assert cleared_payload["vault_binding_id"] is None
    assert cleared_payload["previous_vault_binding_id"] == first.vault_binding_id
    assert cleared_payload["registry_revision"] == runtime.registry.load().revision
    validate_topic_payload(INSTANCE_DEFAULT_VAULT_CHANGED, cleared_payload)

    # A read never publishes.
    assert client.get("/api/instance/default-vault").status_code == 200
    assert len(captured_events) == 2


def test_removing_current_default_requires_atomic_clear_or_replacement(
    client, bound_instance, captured_events
) -> None:
    runtime, first, second = bound_instance
    third_root = runtime.layout.root.parent.parent / "three"
    third_root.mkdir()
    third = runtime.production_register(third_root, producer="api")
    service = runtime.default_vault_service()
    # `first` is the MVR-01C scalar rollback floor target, so the default under
    # test is a binding this transaction is actually allowed to remove.
    client.put(
        "/api/instance/default-vault",
        json={"vault_binding_id": second.vault_binding_id},
    )
    before = runtime.registry.load()

    # Removing the current default without saying what happens to it is a conflict,
    # and the locked transaction leaves the registry untouched.
    with pytest.raises(RegistryDefaultConflict):
        service.remove_registration(second.vault_binding_id)
    after_conflict = runtime.registry.load()
    assert after_conflict.revision == before.revision
    assert after_conflict.default_vault_binding_id == second.vault_binding_id
    assert set(after_conflict.registrations) == set(before.registrations)

    # A replacement must be another current registration, never an invented one,
    # and clear/replace are mutually exclusive rather than quietly ordered.
    with pytest.raises(RegistryDefaultConflict):
        service.remove_registration(
            second.vault_binding_id, replacement_default_binding_id="binding-nope"
        )
    with pytest.raises(RegistryDefaultConflict):
        service.remove_registration(
            second.vault_binding_id,
            clear_default=True,
            replacement_default_binding_id=third.vault_binding_id,
        )
    assert runtime.registry.load().revision == before.revision

    # One explicit authorized replacement in the same locked transaction succeeds,
    # and nothing dangles or is silently substituted.
    receipt = service.remove_registration(
        second.vault_binding_id,
        replacement_default_binding_id=third.vault_binding_id,
    )
    merged = runtime.registry.load()
    assert receipt.vault_binding_id == third.vault_binding_id
    assert merged.default_vault_binding_id == third.vault_binding_id
    assert second.vault_binding_id not in merged.registrations
    assert merged.revision == before.revision + 1

    # Removing a non-default registration must not carry a default gesture at all.
    fourth_root = runtime.layout.root.parent.parent / "four"
    fourth_root.mkdir()
    fourth = runtime.production_register(fourth_root, producer="api")
    with pytest.raises(RegistryDefaultConflict):
        service.remove_registration(fourth.vault_binding_id, clear_default=True)

    # The explicit-clear arm is equally atomic.
    cleared = service.remove_registration(
        third.vault_binding_id, clear_default=True
    )
    final = VaultRegistryStore(runtime.layout.registry_path).load()
    assert cleared.vault_binding_id is None
    assert final.default_vault_binding_id is None
    assert final.default_vault_provenance is None
    assert set(final.registrations) == {
        first.vault_binding_id,
        fourth.vault_binding_id,
    }

    # The MVR-01C rollback floor target is protected by the same reference safety.
    with pytest.raises(RegistryDefaultConflict):
        service.remove_registration(first.vault_binding_id, clear_default=True)
