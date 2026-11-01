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
