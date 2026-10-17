import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.auth import SUBJECT_TRUSTED_LOOPBACK
from app.vault.settings_service import SettingsService, SettingsWriteError
from app.vault.markdown_settings import MarkdownSettingsStore
from app.watcher.settings_delta import handle_settings_detected_delta
from tests.heimdal._screen_control_fixtures import edit_controls, screen_rows, set_control

pytestmark = pytest.mark.not_pg


@pytest.mark.parametrize("writer", ["screen-api", "companion-api", "service", "watcher"])
@pytest.mark.parametrize("key,values", [
    ("screen_paused", [False, True]),
    ("screen_excluded_apps", [["com.bank.app"], []]),
    ("screen_excluded_scopes", [["private"], []]),
    ("screen_scope_app_mapping", [{"private": ["com.bank.app"]}, {}]),
    ("screen_frame_retention_minutes", [7, 8]),
    ("screen_capture_cadence_seconds", [0.5, 1.5]),
    ("screen_client_buffer_max", [4, 8]),
    ("screen_coalesce_max_gap_seconds", [12.0, 15.0]),
    ("screen_coalesce_similarity_threshold", [0.99, 1.0]),
])
def test_every_control_change_receipted(screen_env, writer, key, values):
    for count, value in enumerate(values, start=1):
        actor = "human"
        if writer == "screen-api":
            result = set_control(screen_env, key, value)
            assert result["receipt"]["receipt_type"] == "heimdal_screen_control_receipt"
            actor = SUBJECT_TRUSTED_LOOPBACK
        elif writer == "companion-api":
            response = screen_env.client.post("/api/companion/vault/settings", json={"key": key, "value": value})
            assert response.status_code == 200, response.text
            actor = SUBJECT_TRUSTED_LOOPBACK
        elif writer == "service":
            screen_env.service.update_setting(screen_env.context, key, value, surface="agent", actor="operator-authorized-agent")
            actor = "operator-authorized-agent"
        else:
            edit_controls(screen_env, **{key: value})
            delta = handle_settings_detected_delta(vault_root=screen_env.root, rel_path=Path("settings/screen_control.md"), previous_values=None)
            assert not delta.errors
            assert len(delta.receipts) == 1
        rows = screen_rows(screen_env)
        assert len(rows) == count
        assert rows[-1].key == key and rows[-1].new_value == value
        assert rows[-1].actor == actor
        assert rows[-1].vault_id == screen_env.context.active_vault_id
        assert rows[-1].local_instance_id == screen_env.context.local_instance_id
    durable = [json.loads(line) for line in screen_env.outbox.read_text().splitlines()]
    assert len([r for r in durable if r.get("payload", {}).get("receipt_type") == "heimdal_screen_control_receipt"]) == 2


def test_api_write_then_watcher_replay_does_not_duplicate_receipt(screen_env):
    set_control(screen_env, "screen_paused", False)
    for previous in ({"screen_paused": True}, None):
        result = handle_settings_detected_delta(
            vault_root=screen_env.root, rel_path=Path("settings/screen_control.md"), previous_values=previous,
        )
        assert not result.errors
        assert not result.receipts
    assert set_control(screen_env, "screen_paused", False)["receipt"] is None
    assert len(screen_rows(screen_env)) == 1


def test_receipt_failure_retains_last_valid_and_retry_accepts_once(screen_env, monkeypatch):
    import app.services.outbox as outbox

    append = outbox.append_jsonl_record
    monkeypatch.setattr(outbox, "append_jsonl_record", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": False})
    assert response.status_code == 409
    status = screen_env.client.get("/api/heimdal/screen/control", params={"app_id": "com.editor"}).json()
    assert status["paused"] and not status["capture_permitted"]
    assert status["errors"] and not screen_rows(screen_env)
    monkeypatch.setattr(outbox, "append_jsonl_record", append)
    assert set_control(screen_env, "screen_paused", False)["receipt"]
    assert len(screen_rows(screen_env)) == 1


def test_concurrent_control_writers_preserve_both_changes(screen_env):
    def write(item):
        key, value = item
        return SettingsService().update_setting(screen_env.context, key, value, surface="cli", actor="operator")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(write, [("screen_excluded_apps", ["com.bank"]), ("screen_excluded_scopes", ["private"])]))
    status = screen_env.client.get("/api/heimdal/screen/control").json()
    assert status["controls"]["screen_excluded_apps"] == ["com.bank"]
    assert status["controls"]["screen_excluded_scopes"] == ["private"]
    assert len(screen_rows(screen_env)) == 2


def test_changed_source_before_receipt_is_refused(screen_env, monkeypatch):
    import app.vault.settings_service as settings_service

    emit = settings_service.emit_durable_settings_write_receipt_once

    def race(receipt, **kwargs):
        screen_env.path.write_text(screen_env.path.read_text() + "\nExternal edit\n")
        return emit(receipt, **kwargs)

    monkeypatch.setattr(settings_service, "emit_durable_settings_write_receipt_once", race)
    with pytest.raises(SettingsWriteError, match="not durably accepted"):
        screen_env.service.update_setting(screen_env.context, "screen_paused", False)
    assert not screen_rows(screen_env)
    assert screen_env.client.get("/api/heimdal/screen/control").json()["paused"]


def test_api_stale_document_preserves_concurrent_human_exclusion(screen_env, monkeypatch):
    from app.api.routes import heimdal_screen

    class RacingStore(MarkdownSettingsStore):
        def read(self, path):
            document = super().read(path)
            if path == screen_env.path:
                edit_controls(screen_env, screen_excluded_apps=["com.bank"])
            return document

    service = SettingsService(markdown_store=RacingStore())
    monkeypatch.setattr(heimdal_screen, "SettingsService", lambda: service)
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": False})
    assert response.status_code == 409
    source = MarkdownSettingsStore().read(screen_env.path).frontmatter
    assert source["screen_paused"] and source["screen_excluded_apps"] == ["com.bank"]
    assert not screen_rows(screen_env)


def test_human_pause_after_source_write_cannot_receipt_stale_resume(screen_env, monkeypatch):
    import app.vault.settings_service as settings_service

    confirm = settings_service._confirm_file_and_parent_durable

    def confirm_then_pause(path):
        confirm(path)
        edit_controls(screen_env, screen_paused=True)

    monkeypatch.setattr(settings_service, "_confirm_file_and_parent_durable", confirm_then_pause)
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": False})
    assert response.status_code == 409
    assert MarkdownSettingsStore().read(screen_env.path).frontmatter["screen_paused"]
    assert not screen_rows(screen_env)


def capture_control_frame(env, frame):
    from app.heimdal.capture_adapter import register_sensor

    register_sensor("screen-control-test", "v1")
    return env.client.post("/api/heimdal/screen/capture", json={
        "bundle_shape": "raw_capture_bundle",
        "sensor": {"adapter": "screen-control-test", "version": "v1", "machine": "test-mac"},
        "raw": {"frame": frame},
    })


@pytest.mark.parametrize("writer", ["screen-api", "companion-api", "service", "watcher"])
def test_pause_revokes_screen_grant_and_resume_requires_explicit_grant(screen_env, writer):
    from app.heimdal import consent_ledger, raw_store
    from app.heimdal.raw_liveness import all_deletion_receipts
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE

    set_control(screen_env, "screen_paused", False)
    assert capture_control_frame(screen_env, "before pause").status_code == 200
    actor = SUBJECT_TRUSTED_LOOPBACK
    if writer == "screen-api":
        set_control(screen_env, "screen_paused", True)
    elif writer == "companion-api":
        response = screen_env.client.post("/api/companion/vault/settings", json={"key": "screen_paused", "value": True})
        assert response.status_code == 200, response.text
    elif writer == "service":
        actor = "authorized-operator"
        screen_env.service.update_setting(screen_env.context, "screen_paused", True, actor=actor)
    else:
        actor = "human"
        edit_controls(screen_env, screen_paused=True)
        result = handle_settings_detected_delta(vault_root=screen_env.root, rel_path=Path("settings/screen_control.md"), previous_values=None)
        assert not result.errors and len(result.receipts) == 1
    assert consent_ledger.resolve_active_grant(scope=SCREEN_CAPTURE_SCOPE) is None
    revocations = [row for row in consent_ledger._backend().all_rows() if row.revokes_grant_ref == "controls-test"]
    assert len(revocations) == 1 and revocations[0].granted_by == actor
    assert not raw_store.all_raw_records()
    assert len(all_deletion_receipts()) == 1
    assert all_deletion_receipts()[0].reason == "consent_revoked"
    assert capture_control_frame(screen_env, "paused").status_code == 400
    result = set_control(screen_env, "screen_paused", False)
    assert result["paused"] and not result["consent_active"]
    assert not result["capture_permitted"] and result["requested_state"] == "resume_requested"
    assert capture_control_frame(screen_env, "resume without grant").status_code == 400
    assert [row.new_value for row in screen_rows(screen_env)] == [False, True, False]
    assert screen_rows(screen_env)[1].actor == actor
    consent_ledger.grant_consent(grant_ref="controls-explicit-regrant", scope=SCREEN_CAPTURE_SCOPE, basis="screen_always_on", granted_by="operator")
    assert capture_control_frame(screen_env, "after separate explicit grant").status_code == 200


def test_pause_revocation_failure_never_accepts_setting(screen_env, monkeypatch):
    from app.heimdal import consent_ledger

    set_control(screen_env, "screen_paused", False)
    monkeypatch.setattr(consent_ledger, "revoke_consent", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("ledger unavailable")))
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": True})
    assert response.status_code == 409
    assert [row.new_value for row in screen_rows(screen_env)] == [False]
    status = screen_env.client.get("/api/heimdal/screen/control", params={"app_id": "com.editor"}).json()
    assert status["paused"] and status["errors"] and not status["capture_permitted"]


def test_pause_erasure_failure_remains_revoked_and_retry_reconciles(screen_env, monkeypatch):
    from app.heimdal import consent_ledger, raw_store, retention
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE

    set_control(screen_env, "screen_paused", False)
    assert capture_control_frame(screen_env, "must be erased").status_code == 200
    enforce = retention.enforce_consent_revocation
    monkeypatch.setattr(retention, "enforce_consent_revocation", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("cold cleanup unavailable")))
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": True})
    assert response.status_code == 409
    assert consent_ledger.resolve_active_grant(scope=SCREEN_CAPTURE_SCOPE) is None
    assert capture_control_frame(screen_env, "after failed cleanup").status_code == 400
    assert [row.new_value for row in screen_rows(screen_env)] == [False]
    assert len(raw_store.all_raw_records()) == 1
    monkeypatch.setattr(retention, "enforce_consent_revocation", enforce)
    assert set_control(screen_env, "screen_paused", True)["receipt"]
    assert not raw_store.all_raw_records()
    assert [row.new_value for row in screen_rows(screen_env)] == [False, True]
    assert set_control(screen_env, "screen_paused", True)["receipt"] is None
    assert len(screen_rows(screen_env)) == 2
    assert len([row for row in consent_ledger._backend().all_rows() if row.revokes_grant_ref == "controls-test"]) == 1


def test_pause_receipt_failure_keeps_revocation_and_retry_exactly_once(screen_env, monkeypatch):
    from app.heimdal import consent_ledger
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE
    import app.vault.settings_service as settings_service

    set_control(screen_env, "screen_paused", False)
    emit = settings_service.emit_durable_settings_write_receipt_once
    monkeypatch.setattr(settings_service, "emit_durable_settings_write_receipt_once", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("receipt unavailable")))
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": True})
    assert response.status_code == 409
    assert consent_ledger.resolve_active_grant(scope=SCREEN_CAPTURE_SCOPE) is None
    assert capture_control_frame(screen_env, "after failed receipt").status_code == 400
    assert [row.new_value for row in screen_rows(screen_env)] == [False]
    monkeypatch.setattr(settings_service, "emit_durable_settings_write_receipt_once", emit)
    assert set_control(screen_env, "screen_paused", True)["receipt"]
    assert set_control(screen_env, "screen_paused", True)["receipt"] is None
    assert [row.new_value for row in screen_rows(screen_env)] == [False, True]


def test_pause_revokes_all_screen_grants_and_reconciles_only_screen_erasure(screen_env, monkeypatch):
    from app.heimdal import consent_ledger, retention
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE

    consent_ledger.revoke_consent(grant_ref=consent_ledger.SELF_RECORD_GRANT_REF, revoked_by="operator")
    consent_ledger.grant_consent(grant_ref="second-screen-grant", scope=SCREEN_CAPTURE_SCOPE, basis="screen_always_on", granted_by="operator")
    enforce = retention.enforce_consent_revocation
    reconciled = []

    def enforce_screen_only(**kwargs):
        reconciled.append(kwargs["grant_ref"])
        assert kwargs["grant_ref"] != consent_ledger.SELF_RECORD_GRANT_REF
        return enforce(**kwargs)

    monkeypatch.setattr(retention, "enforce_consent_revocation", enforce_screen_only)
    # An explicit pause still revokes a grant when the setting is already at
    # its safe default; there is no duplicate settings change to receipt.
    assert set_control(screen_env, "screen_paused", True)["receipt"] is None
    assert consent_ledger.list_active_grants(scope=SCREEN_CAPTURE_SCOPE) == []
    assert set(reconciled) == {"controls-test", "second-screen-grant"}
    assert consent_ledger.resolve_active_grant(scope=consent_ledger.MEDIA_CAPTURE_SCOPE) is not None
    assert set(consent_ledger.list_revoked_grant_refs(scope=SCREEN_CAPTURE_SCOPE)) == set(reconciled)
    assert consent_ledger.SELF_RECORD_GRANT_REF in consent_ledger.list_revoked_grant_refs()
    assert capture_control_frame(screen_env, "no older grant fallback").status_code == 400
    assert not screen_rows(screen_env)


def test_source_edit_during_revocation_cannot_accept_stale_pause_or_regrant(screen_env, monkeypatch):
    from app.heimdal import consent_ledger
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE

    set_control(screen_env, "screen_paused", False)
    revoke = consent_ledger.revoke_consent

    def revoke_then_edit(**kwargs):
        result = revoke(**kwargs)
        edit_controls(screen_env, screen_paused=False, screen_excluded_apps=["com.bank"])
        return result

    monkeypatch.setattr(consent_ledger, "revoke_consent", revoke_then_edit)
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": True})
    assert response.status_code == 409
    assert consent_ledger.resolve_active_grant(scope=SCREEN_CAPTURE_SCOPE) is None
    assert [row.new_value for row in screen_rows(screen_env)] == [False]
    source = MarkdownSettingsStore().read(screen_env.path).frontmatter
    assert source["screen_paused"] is False and source["screen_excluded_apps"] == ["com.bank"]
    assert capture_control_frame(screen_env, "no compensating regrant").status_code == 400


def test_first_grant_erasure_failure_still_revokes_every_screen_grant(screen_env, monkeypatch):
    from app.heimdal import consent_ledger, raw_store, retention
    from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE

    set_control(screen_env, "screen_paused", False)
    assert capture_control_frame(screen_env, "first grant raw").status_code == 200
    consent_ledger.grant_consent(grant_ref="later-screen-grant", scope=SCREEN_CAPTURE_SCOPE, basis="screen_always_on", granted_by="operator")
    assert capture_control_frame(screen_env, "later grant raw").status_code == 200
    enforce = retention.enforce_consent_revocation
    attempted = []

    def fail_first_erasure(**kwargs):
        attempted.append(kwargs["grant_ref"])
        if kwargs["grant_ref"] == "controls-test":
            raise RuntimeError("first grant cold erasure unavailable")
        return enforce(**kwargs)

    monkeypatch.setattr(retention, "enforce_consent_revocation", fail_first_erasure)
    response = screen_env.client.put("/api/heimdal/screen/control", json={"key": "screen_paused", "value": True})
    assert response.status_code == 409
    assert consent_ledger.list_active_grants(scope=SCREEN_CAPTURE_SCOPE) == []
    assert set(attempted) == {"controls-test", "later-screen-grant"}
    assert capture_control_frame(screen_env, "after partial erasure").status_code == 400
    assert [row.new_value for row in screen_rows(screen_env)] == [False]
    assert [row.consent["grant_ref"] for row in raw_store.all_raw_records()] == ["controls-test"]
    monkeypatch.setattr(retention, "enforce_consent_revocation", enforce)
    assert set_control(screen_env, "screen_paused", True)["receipt"]
    assert not raw_store.all_raw_records()
    assert [row.new_value for row in screen_rows(screen_env)] == [False, True]
    revocations = [row.revokes_grant_ref for row in consent_ledger._backend().all_rows() if row.is_revocation]
    assert revocations == ["controls-test", "later-screen-grant"]
    set_control(screen_env, "screen_paused", False)
    assert capture_control_frame(screen_env, "resume cannot restore either grant").status_code == 400
