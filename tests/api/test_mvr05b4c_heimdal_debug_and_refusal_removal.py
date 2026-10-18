"""MVR-05B4c6 (#6216): Heimdal reads classified and scoped; debug diagnostics; refusal removed.

The explicitly-global Heimdal ledgers (media receipts, meeting session/segment/projection) serve
a scoped read exactly like a carrier-free one; only the binding-scoped finalization receipt is
filtered to the request binding. The screen-control GET answers from the request binding's
settings, the debug panel's mapping diagnostics are a non-mutating per-request probe, and every
router that lost ``refuse_carrier_until_binding_aware`` still validates a presented carrier.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import heimdal_screen
from app.heimdal import meeting_finalization
from app.heimdal.consent_ledger import reset_memory_consent_ledger
from app.heimdal.media_receipts import all_media_receipts, reset_memory_media_receipts
from app.heimdal.raw_store import reset_memory_raw_store
from app.settings import panel_actions
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg

REPO = Path(__file__).resolve().parents[2]
SESSION = f"mtg-{uuid4()}"
BAD_CARRIERS = (
    ("X-Active-Context-Session", ""),
    ("X-Active-Context-Session", "unknown-session"),
    ("X-Active-Context-Override", "unknown-override"),
)


@pytest.fixture()
def two_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.vault.manager as vault_manager_module

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    for root in (Path(first.path), Path(second.path)):
        initialize_test_vault(root)
        (root / "panel.md").write_text("# Panel\n\n- [ ] promote it\n", encoding="utf-8")
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", "9f" * 32)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    for name in ("LEDGER", "PROJECTION", "BLOCKS", "FINALIZATION"):
        monkeypatch.setenv(
            f"HEIMDAL_MEETING_{name}_PATH", str(tmp_path / f"{name.lower()}.sqlite3")
        )
    meeting_vault = tmp_path / "meeting-vault"
    meeting_vault.mkdir()
    monkeypatch.setenv("HEIMDAL_MEETING_VAULT_ROOT", str(meeting_vault))
    reset_memory_raw_store()
    reset_memory_consent_ledger()
    reset_memory_media_receipts()
    return TestClient(app), first, second, tmp_path


def _headers(client: TestClient, binding_id: str) -> dict[str, str]:
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding_id]}
    )
    assert created.status_code == 201, created.text
    return {"X-Active-Context-Session": created.json()["context_selection_id"]}


def _without_trace(body: dict) -> dict:
    return {key: value for key, value in body.items() if key != "trace_id"}


def _receipts(client: TestClient, headers: dict[str, str] | None = None):
    return client.get(
        "/api/heimdal/capture/receipts",
        params=[("capture_id", "cap-1"), ("capture_id", "cap-2")],
        headers=headers or {},
    )


def _open_meeting(client: TestClient) -> None:
    opened = client.post(
        "/api/heimdal/meeting/session",
        json={"session_id": SESSION, "device_id": "ipad-1", "template_selection": {}},
    )
    assert opened.status_code == 200, opened.text


def _store_finalization(tmp_path: Path, binding: str) -> None:
    store = meeting_finalization._SqliteReceiptStore(str(tmp_path / "finalization.sqlite3"))
    assert store.insert(
        meeting_finalization.FinalizationReceipt(
            session_id=SESSION,
            state_sha256="same-state",
            complete=True,
            missing_seqs=[],
            artifact_refs={"binding": binding},
            supersedes=None,
            finalized_at=meeting_finalization._utcnow(),
            vault_binding_id=binding,
        )
    )


def test_scoped_heimdal_capture_receipts_are_served_from_the_explicitly_global_ledger(
    two_bindings,
) -> None:
    client, first, second, _tmp = two_bindings
    before = all_media_receipts()
    legacy = _receipts(client)
    scoped_a = _receipts(client, _headers(client, first.vault_binding_id))
    scoped_b = _receipts(client, _headers(client, second.vault_binding_id))

    for response in (legacy, scoped_a, scoped_b):
        assert response.status_code == 200, response.text
    assert _without_trace(scoped_a.json()) == _without_trace(legacy.json())
    assert _without_trace(scoped_b.json()) == _without_trace(legacy.json())
    # A read never stamps (or writes) the global ledger.
    assert all_media_receipts() == before


def test_scoped_heimdal_meeting_reads_serve_global_ledger_and_scope_only_finalization(
    two_bindings,
) -> None:
    client, first, second, tmp_path = two_bindings
    _open_meeting(client)
    _store_finalization(tmp_path, first.vault_binding_id)
    _store_finalization(tmp_path, second.vault_binding_id)
    headers_a = _headers(client, first.vault_binding_id)
    headers_b = _headers(client, second.vault_binding_id)

    legacy_segments = client.get(f"/api/heimdal/meeting/{SESSION}/segments")
    for headers in (headers_a, headers_b):
        segments = client.get(f"/api/heimdal/meeting/{SESSION}/segments", headers=headers)
        assert segments.status_code == 200, segments.text
        assert _without_trace(segments.json()) == _without_trace(legacy_segments.json())

    projection_a = client.get(f"/api/heimdal/meeting/{SESSION}/projection", headers=headers_a)
    projection_b = client.get(f"/api/heimdal/meeting/{SESSION}/projection", headers=headers_b)
    assert projection_a.status_code == 200, projection_a.text
    assert projection_b.status_code == 200, projection_b.text
    assert projection_a.json()["finalization"]["vault_binding_id"] == first.vault_binding_id
    assert projection_a.json()["finalization"]["artifact_refs"] == {
        "binding": first.vault_binding_id
    }
    assert projection_b.json()["finalization"]["vault_binding_id"] == second.vault_binding_id
    assert second.vault_binding_id not in projection_a.text
    # The global session/segment part of the projection is the same for both bindings.
    strip = {"finalization", "trace_id"}
    assert {k: v for k, v in projection_a.json().items() if k not in strip} == {
        k: v for k, v in projection_b.json().items() if k not in strip
    }


def test_heimdal_global_ledgers_stay_explicitly_global_and_unstamped() -> None:
    tables = json.loads(
        (REPO / "tests/architecture/durable_table_classification.json").read_text(encoding="utf-8")
    )["tables"]
    heimdal = {name: entry for name, entry in tables.items() if name.startswith("heimdal_")}
    binding_scoped = sorted(
        name for name, entry in heimdal.items() if entry["classification"] == "binding-scoped"
    )
    assert binding_scoped == ["heimdal_meeting_finalization_receipt"]
    for name in ("heimdal_media_receipt", "heimdal_meeting_session", "heimdal_meeting_segment"):
        entry = heimdal[name]
        assert entry["classification"] == "explicitly-global"
        for module in {writer["module"] for writer in entry.get("writers", [])}:
            source = (REPO / module).read_text(encoding="utf-8")
            for ddl in re.findall(
                rf"CREATE TABLE IF NOT EXISTS {name}\b[^;]*", source, flags=re.IGNORECASE
            ):
                assert "vault_binding_id" not in ddl, f"{name} gained a binding column in {module}"


def test_scoped_screen_control_read_answers_for_request_binding(
    two_bindings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, first, second, _tmp = two_bindings
    read_roots: list[Path] = []
    real_status = heimdal_screen.screen_control_status

    def spy(context, **kwargs):
        read_roots.append(Path(context.active_vault_path).resolve())
        return real_status(context, **kwargs)

    monkeypatch.setattr(heimdal_screen, "screen_control_status", spy)
    for binding, root in ((first, first.path), (second, second.path)):
        response = client.get(
            "/api/heimdal/screen/control",
            params={"app_id": "com.editor"},
            headers=_headers(client, binding.vault_binding_id),
        )
        assert response.status_code == 200, response.text
        assert "capability_not_ready" not in response.text
        assert read_roots[-1] == Path(root).resolve()


def test_scoped_debug_panel_restores_binding_scoped_panel_actions_diagnostics(
    two_bindings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, first, _second, _tmp = two_bindings
    missing_root = tmp_path / "no-panel-actions"
    monkeypatch.setenv("PANEL_ACTIONS_ROOT", str(missing_root))
    # Another caller's probe left an error in the process-wide slot.
    panel_actions._set_last_error("another caller's mapping error")

    response = client.get(
        "/api/debug/panel",
        params={"note_rel": "panel.md"},
        headers=_headers(client, first.vault_binding_id),
    )
    assert response.status_code == 200, response.text
    diagnostics = response.json()["panel_diagnostics"]
    assert diagnostics is not None
    assert diagnostics["resolved_panel_actions_root"] == str(missing_root.resolve())
    assert diagnostics["last_panel_mapping_load_error"] == f"missing: {missing_root}"
    # The scoped read neither reported nor rewrote the process-wide slot.
    assert panel_actions._LAST_PANEL_ACTIONS_ERROR == "another caller's mapping error"


def test_no_route_refuses_carrier_as_not_binding_aware() -> None:
    import app.api.request_active_context as request_active_context

    assert not hasattr(request_active_context, "refuse_carrier_until_binding_aware")
    offenders = [
        str(path.relative_to(REPO))
        for path in (REPO / "app").rglob("*.py")
        if "mvr05b4_binding_aware_read" in path.read_text(encoding="utf-8")
        or "refuse_carrier_until_binding_aware" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
    for route in app.routes:
        for dependency in getattr(getattr(route, "dependant", None), "dependencies", []):
            assert getattr(dependency.call, "__name__", "") != "refuse_carrier_until_binding_aware"


@pytest.mark.parametrize(("header", "value"), BAD_CARRIERS)
def test_global_heimdal_reads_still_validate_presented_carriers(
    two_bindings, header: str, value: str
) -> None:
    client, first, _second, _tmp = two_bindings
    _open_meeting(client)
    bad = {header: value}
    for path, params in (
        ("/api/heimdal/capture/receipts", [("capture_id", "cap-1")]),
        (f"/api/heimdal/meeting/{SESSION}/segments", []),
        (f"/api/heimdal/meeting/{SESSION}/projection", []),
        ("/api/heimdal/screen/control", [("app_id", "com.editor")]),
    ):
        refused = client.get(path, params=params, headers=bad)
        assert refused.status_code in (401, 403, 409), (path, refused.text)
        assert SESSION not in refused.text and "receipts" not in refused.json()
        valid = client.get(path, params=params, headers=_headers(client, first.vault_binding_id))
        assert valid.status_code == 200, (path, valid.text)
