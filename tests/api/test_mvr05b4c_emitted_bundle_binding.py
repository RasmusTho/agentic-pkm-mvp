"""MVR-05B4c5 (#6215): emitted context bundles keyed by binding; orientation frames per binding.

The emitted-bundle registry is keyed by (emitting binding, bundle id): a scoped read sees only
its own binding's emission and a foreign, unstamped or unknown id gets one indistinguishable
not-found. ``/api/orientation`` answers a scoped request with a frame computed from its own
binding's signals instead of the 05B3 ``capability_not_ready`` refusal, and the query-backed
``/api/context-bundles/{id}?query=`` producer retrieves only from the request's bindings.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.retrieval.capability as capability_module
from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.context_bundles.runtime_registry import clear_emitted_bundles
from app.observability import ingest_meta
from app.observability.ingest_meta import record_ingest_run
from app.retrieval.hybrid import ScopedRetrieval
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg

BUNDLE_ID = "cb-shared-id"


class _EmptyStore:
    def all(self) -> list:
        return []


@pytest.fixture()
def two_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.vault.manager as vault_manager_module

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    for root in (Path(first.path), Path(second.path)):
        initialize_test_vault(root)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    monkeypatch.setenv("INGEST_STATUS_PATH", str(tmp_path / "ingest_status.json"))
    monkeypatch.setattr(ingest_meta, "_last_ingest_run_at", None)
    monkeypatch.setattr(ingest_meta, "_last_ingest_run_ok", None)
    monkeypatch.setattr(ingest_meta, "_last_ingest_error_message", None)
    monkeypatch.setattr(ingest_meta, "_last_runs", {})
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    # Retrieval backend: one matching note per vault, returned WITHOUT honoring the
    # allowed bindings, so only the production post-filter keeps a scoped read honest.
    searched: list[set[str] | None] = []

    def search(query, **kwargs):
        searched.append(kwargs.get("allowed_binding_ids"))
        return ScopedRetrieval(
            results=[
                _hit("note-a", first.vault_binding_id, "vault-a/plan.md", 0.9),
                _hit("note-b", second.vault_binding_id, "vault-b/plan.md", 0.95),
            ]
        )

    monkeypatch.setattr(capability_module, "scoped_hybrid_search", search)
    monkeypatch.setattr(capability_module, "get_store", lambda: _EmptyStore())
    clear_emitted_bundles()
    yield TestClient(app), first, second, searched
    clear_emitted_bundles()


def _hit(object_id: str, binding: str, source_ref: str, score: float) -> dict:
    return {
        "object_id": object_id,
        "doc_id": object_id,
        "text": f"{object_id} plan body",
        "score": score,
        "snippet": None,
        "source_ref": source_ref,
        "payload": {"vault_binding_id": binding},
    }


def _headers(client: TestClient, binding_id: str) -> dict[str, str]:
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding_id]}
    )
    assert created.status_code == 201, created.text
    return {"X-Active-Context-Session": created.json()["context_selection_id"]}


def _emit(client: TestClient, headers: dict[str, str] | None, *uses: str) -> dict:
    response = client.get(
        f"/api/context-bundles/{BUNDLE_ID}",
        params={"query": "plan", "intended_use": list(uses) or ["orient", "resurface"]},
        headers=headers or {},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _sources(bundle: dict) -> set[str]:
    return {item["artifact_id"] for item in bundle["included"]}


def test_scoped_orientation_frame_and_bundle_are_binding_aware(two_bindings) -> None:
    client, first, second, _searched = two_bindings
    a, b = first.vault_binding_id, second.vault_binding_id
    record_ingest_run("vault", scanned=3, ingested=3, errors=0, vault_binding_id=a)
    record_ingest_run("vault", scanned=11, ingested=11, errors=0, vault_binding_id=b)
    headers_a, headers_b = _headers(client, a), _headers(client, b)

    frame_a = client.get("/api/orientation", headers=headers_a)
    frame_b = client.get("/api/orientation", headers=headers_b)
    assert frame_a.status_code == 200, frame_a.text
    assert frame_b.status_code == 200, frame_b.text
    assert "ingest_total=3" in frame_a.json()["explanation"]["notable_change"]
    assert "ingest_total=11" in frame_b.json()["explanation"]["notable_change"]

    _emit(client, headers_a, "orient")
    own = client.get(f"/api/orientation/bundle/{BUNDLE_ID}", headers=headers_a)
    assert own.status_code == 200, own.text
    foreign = client.get(f"/api/orientation/bundle/{BUNDLE_ID}", headers=headers_b)
    unknown = client.get("/api/orientation/bundle/cb-never-emitted", headers=headers_b)
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json()["detail"].replace(BUNDLE_ID, "X") == unknown.json()["detail"].replace(
        "cb-never-emitted", "X"
    )


def test_emitted_bundle_registry_is_keyed_by_binding(two_bindings) -> None:
    client, first, second, _searched = two_bindings
    headers_a, headers_b = (
        _headers(client, first.vault_binding_id),
        _headers(client, second.vault_binding_id),
    )

    # A carrier-free emission (no registry rebind: the legacy sentinel) is legacy-only.
    _emit(client, None)
    for path in (f"/api/context-bundles/{BUNDLE_ID}", f"/api/resurfacing/bundle/{BUNDLE_ID}"):
        unstamped = client.get(path, headers=headers_a)
        assert unstamped.status_code == 404, unstamped.text

    _emit(client, headers_a)
    for path, unknown_path in (
        (f"/api/context-bundles/{BUNDLE_ID}", "/api/context-bundles/cb-unknown"),
        (f"/api/resurfacing/bundle/{BUNDLE_ID}", "/api/resurfacing/bundle/cb-unknown"),
    ):
        assert client.get(path, headers=headers_a).status_code == 200
        foreign = client.get(path, headers=headers_b)
        unknown = client.get(unknown_path, headers=headers_b)
        assert foreign.status_code == unknown.status_code == 404
        assert foreign.json()["detail"].replace(BUNDLE_ID, "X") == unknown.json()["detail"].replace(
            "cb-unknown", "X"
        )

    # A blank carrier is still scoped: it never falls back to the legacy view.
    blank = client.get(
        f"/api/context-bundles/{BUNDLE_ID}", headers={"X-Active-Context-Session": ""}
    )
    assert blank.status_code != 200


def test_same_bundle_id_in_two_bindings_stays_independent(two_bindings) -> None:
    client, first, second, _searched = two_bindings
    headers_a, headers_b = (
        _headers(client, first.vault_binding_id),
        _headers(client, second.vault_binding_id),
    )

    emitted_a = _emit(client, headers_a)
    emitted_b = _emit(client, headers_b)
    assert emitted_a["id"] == emitted_b["id"] == BUNDLE_ID

    read_a = client.get(f"/api/context-bundles/{BUNDLE_ID}", headers=headers_a).json()
    read_b = client.get(f"/api/context-bundles/{BUNDLE_ID}", headers=headers_b).json()
    assert _sources(read_a) == {"note-a"}
    assert _sources(read_b) == {"note-b"}
    # Re-emitting under A never overwrote B's registration (and vice versa).
    _emit(client, headers_a)
    assert _sources(client.get(f"/api/context-bundles/{BUNDLE_ID}", headers=headers_b).json()) == {
        "note-b"
    }


def test_query_backed_bundle_retrieves_only_request_bindings(two_bindings) -> None:
    client, first, second, searched = two_bindings
    headers_a = _headers(client, first.vault_binding_id)

    bundle = _emit(client, headers_a)
    assert searched[-1] == {first.vault_binding_id}
    assert _sources(bundle) == {"note-a"}
    stored = client.get(f"/api/context-bundles/{BUNDLE_ID}", headers=headers_a).json()
    assert "note-b" not in str(stored)
    assert second.vault_binding_id not in str(stored)


def test_carrier_free_emission_is_never_visible_to_the_live_binding(two_bindings) -> None:
    """#6253 review: an unfiltered carrier-free emission is never stamped as any binding."""

    from app.instance.settings_rebind import _install_dormant_settings_rebind
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    client, first, _second, _searched = two_bindings
    import os

    from app.instance.vault_registry import VaultRegistryStore

    registry = VaultRegistryStore(Path(os.environ["INSTANCE_VAULT_REGISTRY_PATH"]))
    _install_dormant_settings_rebind(
        registry, binding_id=first.vault_binding_id, _capability=STORAGE_MUTATION_CAPABILITY
    )
    # The carrier-free query retrieves without a binding filter (both vaults' notes).
    legacy = _emit(client, None)
    assert _sources(legacy) == {"note-a", "note-b"}
    headers_a = _headers(client, first.vault_binding_id)
    for path in (f"/api/context-bundles/{BUNDLE_ID}", f"/api/resurfacing/bundle/{BUNDLE_ID}"):
        assert client.get(path, headers=headers_a).status_code == 404
    # The carrier-free legacy view still sees its own emission.
    assert client.get(f"/api/resurfacing/bundle/{BUNDLE_ID}").status_code == 200
