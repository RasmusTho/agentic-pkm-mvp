"""Behavioral compatibility-mutation seals after MVR-05C capture activation.

Every test drives the production API routes. The sealed population is derived
from the live application, not re-typed: every mutation route either carries the
compatibility seal, carries the finite governed-context admission, or is named
in ``NOT_VAULT_BOUND_MUTATIONS`` with the reason it writes no vault.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.api.batch_operation_runtime as batch_runtime_module
import app.api.routes.capture as capture_routes
import app.api.routes.operations as operations_routes
import app.vault.manager as vault_manager_module
from app.api.app import app
from app.api.compatibility_mutation import (
    HEADER_COMPATIBILITY_PRECONDITION,
    is_compatibility_selector_bridge,
    require_compatibility_mutation,
)
from app.api.routes import active_context_selection as selection_routes
from app.api.request_governed_write import require_capture_context
from app.instance.active_context_service import ActiveContextSelectionService
from app.instance.context_selection import ReselectionRequiredError
from app.instance.settings_rebind import SettingsRebindStore, _install_dormant_settings_rebind
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault
from tests.integration.test_watcher_cross_process_rebind import _record_reload

pytestmark = pytest.mark.not_pg

_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CAPABILITY_NOT_READY = {"error": "capability_not_ready", "capability": "mvr05c_scoped_write"}
# Every graduated governed-context mutation route and the real selection
# admission seam it resolves through: the scoped capture dependency, or the
# production operation runtime (directly, or via the batch runtime, which
# delegates to it and rebinds each effect item through it).
_CAPTURE_ADMISSION = "require_capture_context"
_OPERATION_ADMISSION = "build_production_operation_runtime"
_BATCH_ADMISSION = "build_production_batch_runtime"
GOVERNED_CONTEXT_MUTATIONS: dict[tuple[str, str], str] = {
    ("POST", "/api/companion/capture/scoped"): _CAPTURE_ADMISSION,
    ("POST", "/api/operations"): _OPERATION_ADMISSION,
    ("POST", "/api/operations/batches/preview"): _BATCH_ADMISSION,
    ("POST", "/api/operations/batches/{batch_id}/execute"): _BATCH_ADMISSION,
    ("POST", "/api/operations/batches/{batch_id}/cancel"): _BATCH_ADMISSION,
}

# Mutation routes that write no vault-bound state, by endpoint module. A new
# mutation route fails ``test_scoped_write_is_sealed_until_mvr05c`` until it is
# either sealed or classified here with its reason.
NOT_VAULT_BOUND_MUTATIONS: dict[str, str] = {
    "app.api.routes.ask": (
        "POST /api/ask and /api/ask/scoped are reads over POST: the legacy twin refuses any "
        "carrier, the scoped route requires one; /api/ask/voice is sealed"
    ),
    "app.api.routes.active_context_selection": "the selection bearer store, not a vault write",
    "app.api.routes.instance_default_vault": (
        "the instance registry's explicit default, governed by its own MVR-02 authority"
    ),
    "app.api.routes.vault_dimensions": "the instance dimension registry, not a vault write",
    "app.api.routes.builderops": "the BuilderOps record store, not a product vault",
    "app.api.routes.signboard": "the BuilderOps signboard, not a product vault",
    "app.api.routes.devui": "devUI overview synthesis over BuilderOps records",
    "app.api.routes.source_understanding": "pure P0 packet computation; persists nothing",
}

# Exact unsealed routes, by route rather than module so a new sibling route
# still fails closed.
NOT_VAULT_BOUND_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/api/operations/preconditions"): (
        "observes native versions without executing or reserving an operation; admitted "
        "through the production operation runtime"
    ),
    ("POST", "/api/operations/acceptance/admission"): (
        "derives and freezes private instance-local acceptance context through production "
        "selection admission and native preconditions; no vault write or operation reservation"
    ),
}


def _dependency_calls(route: APIRoute) -> set[Any]:
    calls: set[Any] = set()

    def walk(dependant: Any) -> None:
        for dependency in dependant.dependencies:
            calls.add(dependency.call)
            walk(dependency)

    walk(route.dependant)
    return calls


def _is_sealed(route: APIRoute) -> bool:
    if getattr(route.endpoint, "__governed_context_write__", False):
        return False
    return any(
        getattr(call, "__name__", "") == "seal_vault_mutation"
        or call is require_compatibility_mutation
        for call in _dependency_calls(route)
    )


def _mutation_routes() -> list[tuple[str, str, APIRoute]]:
    found = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods & _MUTATION_METHODS):
                found.append((method, route.path, route))
    return found


def _sealed_routes() -> list[tuple[str, str, APIRoute]]:
    return [entry for entry in _mutation_routes() if _is_sealed(entry[2])]


def _is_compatibility_route(route: APIRoute) -> bool:
    return require_compatibility_mutation in _dependency_calls(route)


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def _send(client: TestClient, method: str, path: str, headers: dict[str, str]):
    return client.request(method, _url(path), headers=headers, json={})


def _tree(*roots: Path) -> dict[str, bytes]:
    return {
        str(path): path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two registered vaults; the compatibility picker and this process select A."""

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    root_a, root_b = Path(first.path), Path(second.path)
    initialize_test_vault(root_a)
    initialize_test_vault(root_b)
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=first.vault_binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "0")
    monkeypatch.setattr("app.settings.ingestion.ingest_settings", _record_reload([]))
    # The post-append standing-question proposal pass needs a model executor;
    # it is not part of the write seal under test.
    monkeypatch.setattr(capture_routes, "_offer_question_registration_proposal", lambda **_: None)
    # This API process's own single-binding selector.
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", manager)
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app, client=("127.0.0.1", 50000))
    selected = client.post("/api/companion/vault/select", json={"path": str(root_a), "remember": False})
    assert selected.status_code == 200, selected.text
    return client, runtime, first, second


def _session(client: TestClient, binding_id: str) -> str:
    response = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [binding_id]},
    )
    assert response.status_code == 201, response.text
    return response.json()["context_selection_id"]


def _precondition(client: TestClient, session: str) -> str:
    read = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": session},
    )
    assert read.status_code == 200, read.text
    return read.headers[HEADER_COMPATIBILITY_PRECONDITION]


def _inbox_text(root: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in sorted(root.rglob("inbox.md")))


def _other_process_moves_compatibility_picker(tmp_path: Path, root: Path) -> None:
    """Another API process's picker commits the compatibility binding to ``root``.

    This process's own selector is untouched, exactly as for a second process.
    """

    other = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "other-app-local.md"))
    assert other.select_vault(root, remember=False).status == "selected"


def _governed_probe_body(path: str, binding_id: str) -> dict[str, Any]:
    if path == "/api/companion/capture/scoped":
        return {"text": "must not land"}
    if path == "/api/operations":
        return {
            "operation_id": "artifact.update", "request_id": "probe-request",
            "active_context_ref": "probe", "vault_generation": "1",
        }
    if path == "/api/operations/batches/preview":
        return {
            "batch_id": "probe-batch", "operation_id": "artifact.update",
            "active_context_ref": "probe", "vault_generation": "1",
            "target_binding_id": binding_id,
            "items": [{"request_id": "probe-item", "artifact_id": "probe", "expected_version": "1"}],
        }
    return {"expected_digest": "0" * 64}


def _assert_governed_routes_resolve_selection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session: str,
    binding_id: str,
    roots: tuple[Path, ...],
) -> None:
    """Each governed route reaches the real selection admission through its seam.

    Selection resolution is made to refuse; every governed route must have
    reached it through its declared seam and refuse with 401 before any effect.
    """

    seams: list[str] = []
    resolutions: list[str] = []

    def refuse(self: Any, **kwargs: Any) -> Any:
        resolutions.append(kwargs["required_permission"])
        raise ReselectionRequiredError("probe refusal")

    def recording(name: str, factory: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            seams.append(name)
            return factory(*args, **kwargs)

        return wrapper

    original_operation = operations_routes.build_production_operation_runtime
    with monkeypatch.context() as scoped:
        scoped.setattr(ActiveContextSelectionService, "resolve_request_context", refuse)
        scoped.setattr(
            operations_routes, _OPERATION_ADMISSION, recording(_OPERATION_ADMISSION, original_operation)
        )
        scoped.setattr(
            operations_routes,
            _BATCH_ADMISSION,
            recording(_BATCH_ADMISSION, operations_routes.build_production_batch_runtime),
        )
        # The batch runtime admits by delegating to the production operation runtime.
        scoped.setattr(
            batch_runtime_module,
            _OPERATION_ADMISSION,
            recording(_OPERATION_ADMISSION, original_operation),
        )
        _probe_governed_routes(client, session, binding_id, roots, seams, resolutions)


def _probe_governed_routes(
    client: TestClient,
    session: str,
    binding_id: str,
    roots: tuple[Path, ...],
    seams: list[str],
    resolutions: list[str],
) -> None:
    before = _tree(*roots)
    for (method, path), seam in GOVERNED_CONTEXT_MUTATIONS.items():
        seams.clear()
        resolutions.clear()
        response = client.request(
            method,
            _url(path),
            headers={"X-Active-Context-Session": session},
            json=_governed_probe_body(path, binding_id),
        )
        assert response.status_code == 401, (method, path, response.text)
        assert resolutions, (method, path, "selection admission was not reached")
        if seam == _CAPTURE_ADMISSION:
            assert seams == [], (method, path, seams)
        elif seam == _OPERATION_ADMISSION:
            assert seams == [_OPERATION_ADMISSION], (method, path, seams)
        else:
            assert seams == [_BATCH_ADMISSION, _OPERATION_ADMISSION], (method, path, seams)
    assert _tree(*roots) == before


def test_scoped_write_is_sealed_until_mvr05c(tmp_path, monkeypatch) -> None:
    client, runtime, first, second = _setup(tmp_path, monkeypatch)
    root_a, root_b = Path(first.path), Path(second.path)
    session = _session(client, first.vault_binding_id)

    # The live mutation population stays closed. The sole graduated endpoint
    # must retain its real selection admission; a marker on a new route fails.
    governed = {
        (method, path)
        for method, path, route in _mutation_routes()
        if getattr(route.endpoint, "__governed_context_write__", False)
    }
    assert governed == set(GOVERNED_CONTEXT_MUTATIONS)
    for method, path, route in _mutation_routes():
        if GOVERNED_CONTEXT_MUTATIONS.get((method, path)) == _CAPTURE_ADMISSION:
            assert require_capture_context in _dependency_calls(route)
    _assert_governed_routes_resolve_selection(
        client, monkeypatch, session, first.vault_binding_id, (root_a, root_b)
    )
    unclassified = sorted(
        f"{method} {path} ({route.endpoint.__module__})"
        for method, path, route in _mutation_routes()
        if not _is_sealed(route)
        and (method, path) not in governed
        and (method, path) not in NOT_VAULT_BOUND_ROUTES
        and route.endpoint.__module__ not in NOT_VAULT_BOUND_MUTATIONS
    )
    assert not unclassified, "unsealed vault-bound mutation route:\n" + "\n".join(unclassified)
    sealed = _sealed_routes()
    sealed_paths = {path for _method, path, _route in sealed}
    for expected in (
        "/api/companion/capture",
        "/api/companion/capture/compatibility",
        "/api/companion/note/save",
        "/api/companion/note/save/compatibility",
        "/api/companion/memory/provisional",
        "/api/eval-drafts/{draft_id}/decision",
        "/api/canvas/sessions",
        "/api/canvas/sessions/{session_id}/edits",
        "/api/panel/confirm",
        "/api/ask/voice",
        "/api/heimdal/meeting/{session_id}/user-note",
        "/ingest",
    ):
        assert expected in sealed_paths, expected
    stale = sorted(
        module
        for module in NOT_VAULT_BOUND_MUTATIONS
        if not any(route.endpoint.__module__ == module for _m, _p, route in _mutation_routes())
    )
    assert not stale, stale
    live_routes = {(method, path) for method, path, _route in _mutation_routes()}
    assert set(NOT_VAULT_BOUND_ROUTES) <= live_routes

    before = _tree(root_a, root_b)
    carriers = (
        {"X-Active-Context-Session": session},
        {"X-Active-Context-Override": session},
        {"X-Active-Context-Session": session, "X-Active-Context-Override": session},
        # A present-but-blank (intermediary-emptied) carrier is still scoped.
        {"X-Active-Context-Session": ""},
        {"X-Active-Context-Override": ""},
    )
    for method, path, _route in sealed:
        for carrier in carriers:
            response = _send(client, method, path, carrier)
            assert response.status_code == 409, (method, path, carrier, response.text)
            assert response.json()["detail"] == _CAPABILITY_NOT_READY, (method, path)
    # Refused before the translator and before any filesystem/store/outbox effect.
    assert _tree(root_a, root_b) == before
    assert not (tmp_path / "index-outbox.jsonl").exists()

    # A carrier/precondition-free legacy write that would resolve to anything
    # other than the sole freshly revalidated compatibility binding is sealed
    # too: another process moved the compatibility picker to B while this
    # process's selector still names A.
    _other_process_moves_compatibility_picker(tmp_path, root_b)
    assert SettingsRebindStore(runtime.registry).compatibility_binding_id() == second.vault_binding_id
    assert vault_manager_module.get_vault_manager().context.active_vault_path == str(root_a)
    before = _tree(root_a, root_b)
    for method, path, route in sealed:
        if _is_compatibility_route(route) or is_compatibility_selector_bridge(route.endpoint):
            continue
        response = _send(client, method, path, {})
        assert response.status_code == 409, (method, path, response.text)
        assert response.json()["detail"] == _CAPABILITY_NOT_READY, (method, path)
    capture = client.post("/api/companion/capture", json={"text": "must not land in A"})
    assert capture.status_code == 409, capture.text
    assert _tree(root_a, root_b) == before
    assert not (tmp_path / "index-outbox.jsonl").exists()

    # Once this process's selection is the compatibility binding again, the truly
    # legacy single-binding journey on the old route is available unchanged.
    reselected = client.post(
        "/api/companion/vault/select", json={"path": str(root_b), "remember": False}
    )
    assert reselected.status_code == 200, reselected.text
    legacy = client.post("/api/companion/capture", json={"text": "legacy write to B"})
    assert legacy.status_code == 200, legacy.text
    assert "legacy write to B" in _inbox_text(root_b)
    assert "legacy write to B" not in _inbox_text(root_a)


def test_canvas_session_pinned_to_a_previous_binding_is_sealed(tmp_path, monkeypatch) -> None:
    """A canvas session writes the root it was opened on, so that root is sealed too."""

    import app.api.routes.canvas as canvas_module

    client, _runtime, first, second = _setup(tmp_path, monkeypatch)
    root_a, root_b = Path(first.path), Path(second.path)
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_capture_leave_point_for_session", lambda *_a, **_kw: None)
    (root_a / "note.md").write_text("# Note\n\nA body.\n", encoding="utf-8")
    opened = client.post("/api/canvas/sessions", json={"note_path": "note.md"})
    assert opened.status_code == 200, opened.text
    session_id = opened.json()["session_id"]

    # The compatibility picker (and this process) move to B; the session is still A's.
    moved = client.post("/api/companion/vault/select", json={"path": str(root_b), "remember": False})
    assert moved.status_code == 200, moved.text
    before = _tree(root_a, root_b)
    for method, path, payload in (
        ("POST", f"/api/canvas/sessions/{session_id}/edits", {"new_body": "x\n", "change_summary": "x"}),
        ("DELETE", f"/api/canvas/sessions/{session_id}/edits/last", None),
        ("DELETE", f"/api/canvas/sessions/{session_id}", None),
    ):
        response = client.request(method, path, json=payload)
        assert response.status_code == 409, (method, path, response.text)
        assert response.json()["detail"] == _CAPABILITY_NOT_READY
    assert _tree(root_a, root_b) == before
    canvas_module._sessions.pop(session_id, None)


def test_migrated_client_write_precondition_prevents_cross_client_compatibility_redirect(
    tmp_path, monkeypatch
) -> None:
    client, runtime, first, second = _setup(tmp_path, monkeypatch)
    root_a, root_b = Path(first.path), Path(second.path)
    (root_a / "shared.md").write_text("A before\n", encoding="utf-8")
    (root_b / "shared.md").write_text("B before\n", encoding="utf-8")

    # S1 retains A: its scoped read mints the opaque expected-binding/revision
    # precondition, which authorizes exactly one compatibility write journey.
    s1 = _session(client, first.vault_binding_id)
    s1_precondition = _precondition(client, s1)
    control = client.post(
        "/api/companion/capture/compatibility",
        headers={HEADER_COMPATIBILITY_PRECONDITION: s1_precondition},
        json={"text": "S1 control write"},
    )
    assert control.status_code == 200, control.text
    assert "S1 control write" in _inbox_text(root_a)

    # S2 moves the compatibility picker to B through the production picker route.
    moved = client.post("/api/companion/vault/select", json={"path": str(root_b), "remember": False})
    assert moved.status_code == 200, moved.text
    assert SettingsRebindStore(runtime.registry).compatibility_binding_id() == second.vault_binding_id

    before = _tree(root_a, root_b)
    for path, payload in (
        ("/api/companion/capture/compatibility", {"text": "S1 meant A"}),
        ("/api/companion/note/save/compatibility", {"note_path": "shared.md", "new_body": "S1 meant A\n"}),
    ):
        redirected = client.post(
            path, headers={HEADER_COMPATIBILITY_PRECONDITION: s1_precondition}, json=payload
        )
        assert redirected.status_code == 409, (path, redirected.text)
        assert redirected.json()["detail"] == _CAPABILITY_NOT_READY
    # Nor can S1 retry the same write as a legacy write on the old routes.
    for path, payload in (
        ("/api/companion/capture", {"text": "S1 meant A"}),
        ("/api/companion/note/save", {"note_path": "shared.md", "new_body": "S1 meant A\n"}),
    ):
        downgraded = client.post(
            path, headers={HEADER_COMPATIBILITY_PRECONDITION: s1_precondition}, json=payload
        )
        assert downgraded.status_code == 409, (path, downgraded.text)
    # S1's mutation failed; it did not become a legacy B write (nor an A write).
    assert _tree(root_a, root_b) == before
    assert "S1 meant A" not in _inbox_text(root_b)

    # The precondition never selects a target or grants authority: a fresh,
    # valid precondition for the durable compatibility binding still cannot
    # write while this process's own selection names another binding.
    _other_process_moves_compatibility_picker(tmp_path, root_a)
    fresh_a = _precondition(client, s1)
    assert vault_manager_module.get_vault_manager().context.active_vault_path == str(root_b)
    stale_process = client.post(
        "/api/companion/capture/compatibility",
        headers={HEADER_COMPATIBILITY_PRECONDITION: fresh_a},
        json={"text": "would land in B"},
    )
    assert stale_process.status_code == 409, stale_process.text
    assert stale_process.json()["detail"] == _CAPABILITY_NOT_READY
    assert _tree(root_a, root_b) == before


def test_migrated_write_route_rejects_stripped_precondition_without_legacy_downgrade(
    tmp_path, monkeypatch
) -> None:
    client, _runtime, first, _second = _setup(tmp_path, monkeypatch)
    root_a = Path(first.path)
    (root_a / "shared.md").write_text("before\n", encoding="utf-8")
    session = _session(client, first.vault_binding_id)
    precondition = _precondition(client, session)
    capture = ("/api/companion/capture/compatibility", {"text": "must not write"})
    save = (
        "/api/companion/note/save/compatibility",
        {"note_path": "shared.md", "new_body": "must not write\n"},
    )

    before = _tree(root_a)
    for path, payload in (capture, save):
        for headers in (
            {},  # stripped precondition
            {HEADER_COMPATIBILITY_PRECONDITION: ""},  # emptied by an intermediary
            {HEADER_COMPATIBILITY_PRECONDITION: precondition + "tampered"},
            # A precondition never rides together with a scoped carrier.
            {HEADER_COMPATIBILITY_PRECONDITION: precondition, "X-Active-Context-Session": session},
        ):
            response = client.post(path, headers=headers, json=payload)
            assert response.status_code == 409, (path, headers.keys(), response.text)
            assert response.json()["detail"] == _CAPABILITY_NOT_READY

    # The migrated route cannot downgrade through the old route: any request that
    # carries a migrated precondition (even emptied) is refused on every other
    # sealed mutation route, before effect.
    for method, path, route in _sealed_routes():
        if _is_compatibility_route(route):
            continue
        for value in (precondition, ""):
            response = _send(client, method, path, {HEADER_COMPATIBILITY_PRECONDITION: value})
            assert response.status_code == 409, (method, path, response.text)
            assert response.json()["detail"] == _CAPABILITY_NOT_READY
    # The graduated endpoint requires its own scoped admission. A compatibility
    # precondition cannot become a bearer or fall through to a legacy write.
    for value in (precondition, ""):
        response = client.post(
            "/api/companion/capture/scoped",
            headers={HEADER_COMPATIBILITY_PRECONDITION: value},
            json={"text": "must not write", "target_binding_id": first.vault_binding_id},
        )
        assert response.status_code == 401, response.text
        assert response.json()["detail"] == "reselection_required"
    assert _tree(root_a) == before
    assert not (tmp_path / "index-outbox.jsonl").exists()

    # The intact precondition on the compatibility route still works...
    migrated = client.post(
        save[0], headers={HEADER_COMPATIBILITY_PRECONDITION: precondition}, json={
            "note_path": "shared.md",
            "new_body": "migrated write\n",
        },
    )
    assert migrated.status_code == 200, migrated.text
    # ...and a truly legacy carrier/precondition-free write keeps its old route.
    legacy = client.post("/api/companion/capture", json={"text": "truly legacy"})
    assert legacy.status_code == 200, legacy.text
    assert "truly legacy" in _inbox_text(root_a)


def test_settings_update_is_sealed_when_another_process_moved_the_binding(tmp_path, monkeypatch) -> None:
    """#6159 review: /vault/settings writes A before any rebind, so it must prove A first."""

    client, runtime, first, second = _setup(tmp_path, monkeypatch)
    root_a, root_b = Path(first.path), Path(second.path)
    _other_process_moves_compatibility_picker(tmp_path, root_b)
    assert SettingsRebindStore(runtime.registry).compatibility_binding_id() == second.vault_binding_id
    assert vault_manager_module.get_vault_manager().context.active_vault_path == str(root_a)
    before = _tree(root_a, root_b)

    response = client.post(
        "/api/companion/vault/settings",
        json={"key": "enableAutoIndexing", "value": False},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == _CAPABILITY_NOT_READY
    assert _tree(root_a, root_b) == before
