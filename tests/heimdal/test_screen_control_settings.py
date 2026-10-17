import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.heimdal.screen_control import screen_control_status
from app.heimdal.consent_ledger import grant_consent, resolve_active_grant
from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE
from app.heimdal.retention import RetentionWindowMissingError, resolve_screen_frame_retention_minutes
from app.settings.models import SCREEN_CONTROL_KEYS, ScreenControlSettings
from app.vault.manager import VaultManager, no_vault_context
from app.vault.settings_service import SettingsRegistry
from app.watcher.settings_delta import handle_settings_detected_delta
from tests.heimdal._screen_control_fixtures import edit_controls, screen_rows, set_control

pytestmark = pytest.mark.not_pg


def ingest_edit(env):
    return handle_settings_detected_delta(
        vault_root=env.root, rel_path=Path("settings/screen_control.md"), previous_values=None,
    )


def test_control_settings_ingested_live(screen_env):
    edit_controls(screen_env, screen_paused=False, screen_excluded_apps=["com.bank"])
    pending = screen_env.client.get("/api/heimdal/screen/control", params={"app_id": "com.editor"}).json()
    assert pending["paused"] and pending["errors"]
    result = ingest_edit(screen_env)
    assert not result.errors
    assert len(result.receipts) == 2
    assert all(row.actor == "human" and row.surface == "file" for row in screen_rows(screen_env))
    status = screen_env.client.get("/api/heimdal/screen/control", params={"app_id": "com.editor"}).json()
    assert status["settings_state"] == "ok"
    assert status["capture_permitted"] and not status["paused"]
    assert status["controls"]["screen_excluded_apps"] == ["com.bank"]


def test_registry_tick_reloads_screen_controls_once(screen_env, tmp_path, monkeypatch):
    import app.watcher.registry as registry

    config = tmp_path / "watchers.yaml"
    config.write_text("version: 1\nwatchers:\n  - name: screen-controls\n    scope_glob: ''\n    debounce_ms: 0\n    rate_limit_per_min: 30\n    emit_event: panel.scan.requested\n")
    for key, value in {
        "WATCHER_ENABLE": "1", "WATCHER_VAULT_PATH": str(screen_env.root),
        "WATCHER_STATE_DIR": str(tmp_path / "watcher-state"),
        "WATCHER_SCOPE_GLOB": "settings/*.md", "WATCHER_SUMMARY_INTERVAL": "0",
        "WATCHER_DEBOUNCE_MS": "0", "PKM_SETTINGS_PROFILE": "lab",
    }.items():
        monkeypatch.setenv(key, value)
    registry.run_registry_once(config)
    edit_controls(screen_env, screen_paused=False)
    registry.run_registry_once(config)
    assert screen_control_status(screen_env.context, app_id="com.editor")["capture_permitted"]
    assert len(screen_rows(screen_env)) == 1
    registry.run_registry_once(config)
    assert len(screen_rows(screen_env)) == 1


def test_visible_state_matches_governed_controls(screen_env):
    # This is the host permission contract the external client's loop must read.
    # The API explicitly does not claim to have observed an external process.
    def status(app_id="com.editor"):
        return screen_env.client.get("/api/heimdal/screen/control", params={"app_id": app_id}).json()

    assert status()["paused"] and not status()["capture_permitted"]
    set_control(screen_env, "screen_paused", False)
    assert status()["state"] == "ready" and status()["capture_permitted"]
    assert status()["requested_state"] == "resume_requested"
    assert status()["capture_state"] == "unknown_external_client"
    set_control(screen_env, "screen_excluded_apps", ["com.bank"])
    assert not status("com.bank")["capture_permitted"]
    set_control(screen_env, "screen_scope_app_mapping", {"private": ["com.private"]})
    set_control(screen_env, "screen_excluded_scopes", ["private"])
    assert not status("com.private")["capture_permitted"]
    assert status("com.private")["scopes"] == ["private"]
    set_control(screen_env, "screen_paused", True)
    assert status()["paused"] and not status()["consent_active"]
    assert resolve_active_grant(scope=SCREEN_CAPTURE_SCOPE) is None
    set_control(screen_env, "screen_paused", False)
    assert status()["paused"] and not status()["capture_permitted"]
    grant_consent(grant_ref="controls-explicit-regrant", scope=SCREEN_CAPTURE_SCOPE, basis="screen_always_on", granted_by="operator")
    assert status()["capture_permitted"]
    assert status()["capture_state"] == "unknown_external_client"


@pytest.mark.parametrize("key,bad", [
    ("screen_frame_retention_minutes", 0),
    ("screen_capture_cadence_seconds", -1),
    ("screen_client_buffer_max", True),
    ("screen_coalesce_similarity_threshold", 1.1),
    ("screen_excluded_apps", [1]),
    ("screen_scope_app_mapping", {"private": "com.bank"}),
])
def test_invalid_tunable_degrades_loud_not_silent(screen_env, key, bad):
    set_control(screen_env, "screen_frame_retention_minutes", 7)
    set_control(screen_env, "screen_capture_cadence_seconds", 1.5)
    before = screen_control_status(screen_env.context)["controls"]
    edit_controls(screen_env, **{key: bad})
    result = ingest_edit(screen_env)
    assert result.errors
    status = screen_control_status(screen_env.context, app_id="com.editor")
    assert status["settings_state"] == "degraded_last_valid"
    assert status["controls"] == before
    assert status["errors"] and not status["capture_permitted"]
    assert resolve_screen_frame_retention_minutes(screen_env.root) == 7


def test_screen_tunables_are_single_sourced(screen_env):
    defaults = ScreenControlSettings().model_dump()
    registry = SettingsRegistry()
    assert {key: registry.get(key).default_value for key in SCREEN_CONTROL_KEYS} == defaults
    assert screen_control_status(screen_env.context)["controls"] == defaults
    # Consumers may read a registered key but cannot inline another default.
    app_root = Path(__file__).resolve().parents[2] / "app"
    violations = []
    for path in app_root.rglob("*.py"):
        if path == app_root / "settings" / "models.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"get", "getenv"} and len(node.args) > 1:
                    if isinstance(node.args[0], ast.Constant) and node.args[0].value in SCREEN_CONTROL_KEYS:
                        if isinstance(node.args[1], (ast.Constant, ast.List, ast.Dict)):
                            violations.append((str(path), node.lineno))
    assert not violations


def test_restart_and_vault_rebind_do_not_resume_paused_capture(screen_env, tmp_path):
    set_control(screen_env, "screen_paused", False)
    set_control(screen_env, "screen_paused", True)
    restored = VaultManager().validate_vault(screen_env.root)
    assert screen_control_status(restored)["controls"]["screen_paused"]
    other = VaultManager().initialize_vault(tmp_path / "other", machine_role="testNode", remember=False).context
    set_control(screen_env, "screen_paused", False)
    assert screen_control_status(other)["paused"]
    assert screen_control_status(no_vault_context())["paused"]
    screen_env.path.unlink()
    assert screen_control_status(restored)["paused"]
    assert screen_control_status(restored)["errors"]


def test_invalid_cold_source_never_claims_last_valid_or_cleans_up_with_defaults(screen_env):
    edit_controls(screen_env, screen_frame_retention_minutes="invalid")
    assert ingest_edit(screen_env).errors
    assert screen_control_status(screen_env.context)["settings_state"] == "invalid_sources"
    with pytest.raises(RetentionWindowMissingError, match="no last-valid"):
        resolve_screen_frame_retention_minutes(screen_env.root)


@pytest.mark.parametrize("malformation", ["numeric-key", "invalid-utf8"])
def test_malformed_control_source_degrades_without_losing_last_valid(screen_env, malformation):
    set_control(screen_env, "screen_frame_retention_minutes", 7)
    if malformation == "invalid-utf8":
        screen_env.path.write_bytes(b"\xff")
    else:
        screen_env.path.write_text(screen_env.path.read_text().replace("---\n", "---\n42: invalid\n", 1))
    response = screen_env.client.get("/api/heimdal/screen/control")
    assert response.status_code == 200
    status = response.json()
    assert status["settings_state"] == "degraded_last_valid"
    assert status["paused"] and status["errors"]
    assert resolve_screen_frame_retention_minutes(screen_env.root) == 7


def test_unreadable_receipt_history_refuses_capture_and_retention(screen_env):
    set_control(screen_env, "screen_paused", False)
    set_control(screen_env, "screen_frame_retention_minutes", 7)
    screen_env.outbox.write_text(screen_env.outbox.read_text() + "malformed receipt\n")
    response = screen_env.client.get("/api/heimdal/screen/control", params={"app_id": "com.editor"})
    assert response.status_code == 200
    status = response.json()
    assert status["settings_state"] == "invalid_sources"
    assert status["paused"] and not status["capture_permitted"]
    assert status["errors"]
    assert screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": True}).status_code == 409
    with pytest.raises(RetentionWindowMissingError, match="no last-valid"):
        resolve_screen_frame_retention_minutes(screen_env.root)


def test_bad_screen_source_does_not_block_healthy_settings_ingestion(screen_env):
    from app.vault.markdown_settings import MarkdownSettingsStore

    set_control(screen_env, "screen_frame_retention_minutes", 7)
    screen_env.path.write_bytes(b"\xff")
    store = MarkdownSettingsStore()
    youtube_path = screen_env.root / "settings" / "youtube.md"
    document = store.read(youtube_path)
    store.write_frontmatter(
        youtube_path, {**document.frontmatter, "youtubeSync.enabled": True}, body=document.body,
    )
    result = handle_settings_detected_delta(
        vault_root=screen_env.root, rel_path=Path("settings/youtube.md"), previous_values=None,
    )
    assert not result.errors and len(result.receipts) == 1
    resolution = screen_env.service.resolve(screen_env.context)
    assert resolution.settings["youtubeSync.enabled"].value is True
    assert any(error.source_file == str(screen_env.path) for error in resolution.validation_errors)
    status = screen_control_status(screen_env.context)
    assert status["settings_state"] == "degraded_last_valid"
    assert status["paused"] and status["controls"]["screen_frame_retention_minutes"] == 7


def test_authentication_and_actor_are_server_derived(screen_env, monkeypatch):
    from app.auth import settings

    monkeypatch.setattr(settings, "api_key", None)
    with TestClient(screen_env.client.app, client=("198.51.100.2", 4321)) as client:
        assert client.get("/api/heimdal/screen/control").status_code == 401
        assert client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": False}).status_code == 401
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": False, "actor": "forged"})
    assert response.status_code == 422
    assert not screen_rows(screen_env)


def test_companion_remote_screen_write_requires_server_derived_authentication(screen_env, monkeypatch):
    from app.auth import SUBJECT_API_KEY_CREDENTIAL, settings

    monkeypatch.setattr(settings, "api_key", "screen-test-key")
    with TestClient(screen_env.client.app, client=("198.51.100.2", 4321)) as client:
        response = client.post("/api/companion/vault/settings", json={"key": "screen_paused", "value": False})
        assert response.status_code == 401
        assert not screen_rows(screen_env)
        assert screen_control_status(screen_env.context)["controls"]["screen_paused"]
        response = client.post(
            "/api/companion/vault/settings", headers={"X-API-Key": "screen-test-key"},
            json={"key": "screen_paused", "value": False, "actor": "forged"},
        )
        assert response.status_code == 200
        assert screen_rows(screen_env)[-1].actor == SUBJECT_API_KEY_CREDENTIAL


def test_read_only_role_cannot_change_screen_controls(screen_env):
    from app.vault.markdown_settings import MarkdownSettingsStore

    store = MarkdownSettingsStore()
    path = screen_env.root / "settings" / "local.md"
    document = store.read(path)
    store.write_frontmatter(path, {**document.frontmatter, "machineRole": "readOnlySatellite"}, body=document.body)
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": False})
    assert response.status_code == 403
    assert not screen_rows(screen_env)


@pytest.mark.parametrize("header", ["X-Active-Context-Session", "X-Active-Context-Override"])
def test_scoped_bearer_cannot_mutate_compatibility_screen_controls(screen_env, header):
    response = screen_env.client.put(
        "/api/heimdal/screen/control", headers={header: "scoped-context"},
        json={"key": "screen_paused", "value": False},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "capability_not_ready"
    assert not screen_rows(screen_env)


def test_deleted_control_key_is_receipted_reset_and_unknown_key_is_visible(screen_env):
    from app.vault.markdown_settings import MarkdownSettingsStore

    set_control(screen_env, "screen_paused", False)
    store = MarkdownSettingsStore()
    document = store.read(screen_env.path)
    frontmatter = dict(document.frontmatter)
    del frontmatter["screen_paused"]
    store.write_frontmatter(screen_env.path, frontmatter, body=document.body)
    assert not ingest_edit(screen_env).errors
    assert screen_control_status(screen_env.context)["controls"]["screen_paused"]
    assert len(screen_rows(screen_env)) == 2
    edit_controls(screen_env, screen_unknown_tunable=3)
    assert screen_control_status(screen_env.context)["errors"]


def test_legacy_retention_requires_explicit_canonical_acceptance(screen_env):
    from app.heimdal.settings_notes import SETTINGS, SettingsNote, write_settings_note

    write_settings_note(screen_env.root, SettingsNote(spec=SETTINGS, values={"screen_frame_retention_minutes": 45}))
    status = screen_control_status(screen_env.context)
    assert status["errors"] and status["paused"]
    with pytest.raises(RetentionWindowMissingError, match="no last-valid"):
        resolve_screen_frame_retention_minutes(screen_env.root)
    # Even explicitly choosing the registry default must leave a migration
    # receipt, rather than silently replacing the historical operator value.
    selected = ScreenControlSettings().screen_frame_retention_minutes
    response = set_control(screen_env, "screen_frame_retention_minutes", selected)
    assert response["receipt"]["old_value"] == 45
    assert response["receipt"]["new_value"] == selected
    assert not response["errors"]
    assert resolve_screen_frame_retention_minutes(screen_env.root) == selected
