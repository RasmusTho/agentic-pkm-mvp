from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import ask as ask_routes
from app.api.routes import search as search_routes
from app.instance import context_settings as context_settings_module
from app.instance.active_context_service import binding_revision_for
from app.instance.context_settings import (
    BINDING_LOCAL,
    CONTEXT_SETTING_CLASSIFICATION,
    PROCESS_PATH_OVERRIDES,
    REQUEST_WIDE_MUST_MATCH,
    BindingLocalPathEscapeError,
    IncompatibleBindingSettingsError,
    UnclassifiedContextSettingError,
    resolve_context_settings,
)
from app.vault.active_context_v1 import (
    ActiveContextBinding,
    ActiveContextSetV1,
    PrincipalContext,
    WorkspaceState,
)
from app.vault.manager import VaultManager
from tests._mvr03_principal_harness import provisioned_instance
from tests._mvr_default_vault_harness import activate, new_runtime

SELECTION_URL = "/api/companion/active-context/selection"


def _two_binding_context(runtime) -> ActiveContextSetV1:
    snapshot = runtime.registry.load()
    return ActiveContextSetV1(
        context_id="settings-conflict",
        generation=1,
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        principal_context=PrincipalContext(
            "operator",
            "human",
            "trusted_loopback",
        ),
        instance_identity=snapshot.app_install_id,
        source_bindings=tuple(
            ActiveContextBinding(
                registration.vault_binding_id,
                binding_revision_for(snapshot, registration.vault_binding_id),
                "settings-test",
            )
            for registration in snapshot.registrations.values()
        ),
        registry_revision=snapshot.revision,
        authorization_epoch="settings-test",
        selection_provenance="integration-test",
    )


def _runtime_with_roles(tmp_path: Path, first_role: str, second_role: str):
    runtime = new_runtime(tmp_path)
    first_root = tmp_path / "vault-a"
    second_root = tmp_path / "vault-b"
    VaultManager().initialize_vault(first_root, machine_role=first_role, remember=False)
    first = runtime.bootstrap_env_binding(vault_root=first_root, watcher_vault_path=first_root)
    activate(runtime, first, tmp_path)
    VaultManager().initialize_vault(second_root, machine_role=second_role, remember=False)
    runtime.production_register(second_root, producer="api")
    return runtime, first_root, second_root


def test_many_binding_request_fails_before_effect_when_request_wide_settings_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production resolver and both scoped routes reject incompatible binding settings."""

    runtime, _first_root, _second_root = _runtime_with_roles(
        tmp_path, "testNode", "readOnlySatellite"
    )
    context = _two_binding_context(runtime)

    # Both bindings are resolved completely; neither binding order selects a winner.
    with pytest.raises(IncompatibleBindingSettingsError, match="incompatible_binding_settings"):
        resolve_context_settings(context, registry_store=runtime.registry)
    reversed_context = ActiveContextSetV1(
        **{**context.__dict__, "source_bindings": tuple(reversed(context.source_bindings))}
    )
    with pytest.raises(IncompatibleBindingSettingsError, match="incompatible_binding_settings"):
        resolve_context_settings(reversed_context, registry_store=runtime.registry)

    # Production requests over the same two bindings fail before any effect.
    p_runtime, first, extra, _record = provisioned_instance(tmp_path / "http", extra_roots=("two",))
    second = extra[0]
    VaultManager().initialize_vault(Path(first.path), machine_role="testNode", remember=False)
    VaultManager().initialize_vault(Path(second.path), machine_role="readOnlySatellite", remember=False)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(p_runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(p_runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    import app.vault.manager as vault_manager_module

    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    effects: list[str] = []
    monkeypatch.setattr(ask_routes, "run_ask_graph", lambda *_a, **_k: effects.append("graph"))
    monkeypatch.setattr(
        ask_routes, "_ensure_hybrid_store_loaded", lambda: effects.append("cache_fill")
    )
    monkeypatch.setattr(search_routes, "retrieve", lambda *_a, **_k: effects.append("retrieve"))

    client = TestClient(app)
    created = client.post(
        SELECTION_URL, json={"vault_binding_ids": [first.vault_binding_id, second.vault_binding_id]}
    )
    assert created.status_code == 201, created.text
    headers = {"X-Active-Context-Session": created.json()["context_selection_id"]}

    ask = client.post("/api/ask/scoped", json={"question": "both vaults?"}, headers=headers)
    assert ask.status_code == 409, ask.text
    assert ask.json()["detail"] == "incompatible_binding_settings"
    search = client.get("/search/scoped", params={"q": "both"}, headers=headers)
    assert search.status_code == 409, search.text
    assert search.json()["detail"] == "incompatible_binding_settings"
    assert effects == []


def test_process_wide_path_overrides_have_registry_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VAULT_SYSTEM_DIR_REL / VAULT_LAYOUT_NOTE_REL are classified binding-local and confined."""

    # Explicit registry classification for the two process-wide path overrides.
    assert PROCESS_PATH_OVERRIDES == ("VAULT_SYSTEM_DIR_REL", "VAULT_LAYOUT_NOTE_REL")
    for key in PROCESS_PATH_OVERRIDES:
        assert CONTEXT_SETTING_CLASSIFICATION[key] == BINDING_LOCAL

    runtime, first_root, second_root = _runtime_with_roles(tmp_path, "testNode", "testNode")
    context = _two_binding_context(runtime)

    # Every request-wide value the production resolver compares is classified as such.
    resolution = resolve_context_settings(context, registry_store=runtime.registry)
    assert resolution.request_wide_values
    for key in resolution.request_wide_values:
        assert CONTEXT_SETTING_CLASSIFICATION[key] == REQUEST_WIDE_MUST_MATCH

    # A uniformly applied process-wide override resolves inside each binding's own root
    # and stays binding-local: it is recorded per binding, never compared or merged.
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "Ops/System")
    monkeypatch.setenv("VAULT_LAYOUT_NOTE_REL", "Ops/System/vault.layout.md")
    resolution = resolve_context_settings(context, registry_store=runtime.registry)
    roots = {binding_id: Path(values["VAULT_SYSTEM_DIR_REL"]) for binding_id, values in resolution.binding_local_values.items()}
    assert sorted(path.parent.parent for path in roots.values()) == sorted(
        [first_root.resolve(), second_root.resolve()]
    )
    for values in resolution.binding_local_values.values():
        assert Path(values["VAULT_LAYOUT_NOTE_REL"]).parent == Path(values["VAULT_SYSTEM_DIR_REL"])
    assert "VAULT_SYSTEM_DIR_REL" not in resolution.request_wide_values

    # An override that escapes a binding's root fails the whole request before effect.
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "../outside")
    with pytest.raises(BindingLocalPathEscapeError):
        resolve_context_settings(context, registry_store=runtime.registry)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL")
    monkeypatch.setenv("VAULT_LAYOUT_NOTE_REL", "../../elsewhere/vault.layout.md")
    with pytest.raises(BindingLocalPathEscapeError):
        resolve_context_settings(context, registry_store=runtime.registry)
    monkeypatch.delenv("VAULT_LAYOUT_NOTE_REL")

    # Bindings that disagree on a request-wide override fail the request.
    def _diverging(bundle, effective):  # type: ignore[no-untyped-def]
        values = original(bundle, effective)
        values["ask"] = {"seen": len(seen)}
        seen.append(1)
        return values

    seen: list[int] = []
    original = context_settings_module._request_wide_values
    monkeypatch.setattr(context_settings_module, "_request_wide_values", _diverging)
    with pytest.raises(IncompatibleBindingSettingsError, match="incompatible_binding_settings"):
        resolve_context_settings(context, registry_store=runtime.registry)

    # A value with no registry classification never defaults to either class.
    monkeypatch.setattr(
        context_settings_module,
        "_request_wide_values",
        lambda bundle, effective: {**original(bundle, effective), "unclassified_knob": 1},
    )
    with pytest.raises(UnclassifiedContextSettingError):
        resolve_context_settings(context, registry_store=runtime.registry)
