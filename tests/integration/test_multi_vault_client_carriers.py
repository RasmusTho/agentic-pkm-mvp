"""Behavioral single-origin carrier forwarding for MVR-05B."""

from __future__ import annotations

import io
from pathlib import Path
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.compatibility_mutation as compatibility_mutation
import app.api.routes.capture as capture_routes
from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes.active_context_selection import build_selection_service, get_selection_store
from app.instance.settings_rebind import compatibility_ingress_window
from app.instance.settings_rebind import _install_dormant_settings_rebind
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault
from companion_ui.workspace.serve_dev_page import make_handler


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post(self, url: str, *, json: dict[str, Any], headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        return {"ok": True}


def test_proxy_backend_carrier_matrix_and_activation_boundary() -> None:
    client = _Client()
    handler_cls = make_handler(client=client, api_base_url="http://runtime")  # type: ignore[arg-type]
    handler = handler_cls.__new__(handler_cls)
    handler.path = "/api/companion/capture/compatibility"
    handler.headers = {
        "Content-Length": "2",
        "X-API-Key": "api-key",
        "X-Active-Context-Session": "session-bearer",
        "X-Active-Context-Override": "override-bearer",
        "X-Compatibility-Write-Precondition": "opaque-precondition",
    }
    handler.rfile = io.BytesIO(b"{}")
    handler.wfile = io.BytesIO()
    handler._send_json = lambda status_code, payload: None  # type: ignore[method-assign]
    handler.do_POST()

    assert client.calls == [
        (
            "/api/companion/capture/compatibility",
            {
                "X-API-Key": "api-key",
                "X-Active-Context-Session": "session-bearer",
                "X-Active-Context-Override": "override-bearer",
                "X-Compatibility-Write-Precondition": "opaque-precondition",
            },
        )
    ]
    assert handler_cls.route_allowed("POST", "/api/companion/capture/compatibility")
    # No page/picker activation is introduced by the callable carrier route.
    assert not handler_cls.route_allowed("POST", "/api/companion/capture/scoped")


def _compatibility_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=first.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    selection_routes.reset_selection_store_for_tests()
    initialize_test_vault(Path(first.path))
    client = TestClient(app, client=("127.0.0.1", 50000))
    selected = client.post(
        "/api/companion/vault/select",
        json={"path": first.path, "remember": False},
    )
    assert selected.status_code == 200, selected.text
    return client, runtime, first, extra[0]


def test_compatibility_mutation_holds_ingress_window_through_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime, first, _second = _compatibility_runtime(tmp_path, monkeypatch)
    principal_id = build_selection_service(get_selection_store()).derive(
        "trusted_loopback", presented_credential=None
    ).principal.principal_id
    precondition = compatibility_mutation.issue_compatibility_precondition(
        binding_id=first.vault_binding_id,
        principal_id=principal_id,
        registry=runtime.registry,
    )
    effect_entered = threading.Event()
    release_effect = threading.Event()
    rebind_entered = threading.Event()

    original_emit = capture_routes._emit_capture_event

    def blocked_emit(payload: dict[str, Any], trace_id: str) -> list[str]:
        effect_entered.set()
        assert release_effect.wait(timeout=5)
        return original_emit(payload, trace_id)

    monkeypatch.setattr(capture_routes, "_emit_capture_event", blocked_emit)
    response_box: list[Any] = []

    def run_compatibility_effect() -> None:
        response_box.append(
            client.post(
                "/api/companion/capture/compatibility",
                headers={
                    compatibility_mutation.HEADER_COMPATIBILITY_PRECONDITION: precondition
                },
                json={"text": "effect"},
            )
        )

    effect_thread = threading.Thread(target=run_compatibility_effect)
    effect_thread.start()
    if not effect_entered.wait(timeout=5):
        effect_thread.join(timeout=1)
        detail = response_box[0].json() if response_box else "no response"
        pytest.fail(f"compatibility effect did not start: {detail}")

    def attempt_rebind() -> None:
        with compatibility_ingress_window(runtime.registry, transition=True):
            rebind_entered.set()

    rebind_thread = threading.Thread(target=attempt_rebind)
    rebind_thread.start()
    assert not rebind_entered.wait(timeout=0.1)

    release_effect.set()
    effect_thread.join(timeout=5)
    rebind_thread.join(timeout=5)
    assert rebind_entered.is_set()
    assert response_box and response_box[0].status_code == 200, response_box


def test_independently_mounted_vault_writers_fail_closed_for_scoped_carrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _runtime, first, _second = _compatibility_runtime(tmp_path, monkeypatch)
    selection = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [first.vault_binding_id]},
    )
    assert selection.status_code == 201, selection.text
    headers = {"X-Active-Context-Session": selection.json()["context_selection_id"]}
    cases = (
        (
            "/api/companion/memory/provisional",
            {
                "scope_id": "scope",
                "principal_id": "principal",
                "memory_type": "fact",
                "sensitivity": "normal",
                "content": "must not write",
                "provenance_event_ids": ["event-1"],
            },
        ),
        ("/api/companion/capture", {"text": "must not write"}),
        (
            "/api/companion/note/save",
            {"note_path": "missing.md", "new_body": "must not write"},
        ),
        ("/api/canvas/sessions", {"note_path": "missing.md"}),
        (
            "/api/panel/checkbox-projection",
            {
                "artifact_id": "artifact",
                "note_path": "missing.md",
                "panel_id": "panel",
                "option_id": "option",
                "expected_content_hash": "content-hash",
                "expected_source_hash": "source-hash",
                "idempotency_key": "idempotency-key",
            },
        ),
    )
    carriers = (
        {"X-Active-Context-Session": headers["X-Active-Context-Session"]},
        {"X-Active-Context-Override": headers["X-Active-Context-Session"]},
        {
            "X-Active-Context-Session": headers["X-Active-Context-Session"],
            "X-Active-Context-Override": headers["X-Active-Context-Session"],
        },
    )
    for carrier in carriers:
        for path, payload in cases:
            response = client.post(path, headers=carrier, json=payload)
            assert response.status_code == 409, (path, response.text)
            assert response.json()["detail"] == {
                "error": "capability_not_ready",
                "capability": "mvr05c_scoped_write",
            }


def test_compatibility_mutation_requires_current_binding_and_principal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime, first, second = _compatibility_runtime(tmp_path, monkeypatch)
    principal_id = build_selection_service(get_selection_store()).derive(
        "trusted_loopback", presented_credential=None
    ).principal.principal_id
    wrong_principal = compatibility_mutation.issue_compatibility_precondition(
        binding_id=first.vault_binding_id,
        principal_id="not-the-request-principal",
        registry=runtime.registry,
    )
    wrong_binding = compatibility_mutation.issue_compatibility_precondition(
        binding_id=second.vault_binding_id,
        principal_id=principal_id,
        registry=runtime.registry,
    )
    for precondition in (wrong_principal, wrong_binding):
        response = client.post(
            "/api/companion/capture/compatibility",
            headers={compatibility_mutation.HEADER_COMPATIBILITY_PRECONDITION: precondition},
            json={"text": "must not write"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {
            "error": "capability_not_ready",
            "capability": "mvr05c_scoped_write",
        }
