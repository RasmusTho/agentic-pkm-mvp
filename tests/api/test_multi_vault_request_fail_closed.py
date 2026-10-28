"""Behavioural guards for the migrated backend read ingress."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import ask as ask_routes
from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.context_selection import ContextSelectionStore
from app.instance.vault_registry import KnownVaultRef, RegistryError
from app.vault.active_context_v1 import DimensionFilter
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

SELECTION_URL = "/api/companion/active-context/selection"
DIMENSIONS_URL = "/api/instance/dimensions"
NOTES_URL = "/api/companion/vault/notes/scoped"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, _extra, _record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    return runtime, first


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_global_vault_manager(monkeypatch):
    import app.vault.manager as vault_manager_module

    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    yield


def _create(client: TestClient, binding_id: str) -> dict:
    response = client.post(SELECTION_URL, json={"vault_binding_ids": [binding_id]})
    assert response.status_code == 201, response.text
    return response.json()


def test_migrated_scoped_read_rejects_stripped_carrier_without_default_downgrade(
    instance, client, monkeypatch
) -> None:
    """A scoped read whose carrier is stripped fails reselection-required, never downgrades.

    The separately identified scoped routes stay server-identifiable by route when an
    intermediary strips the carrier; their legacy twins refuse any carrier-bearing retry;
    and the routes MVR-05B3 migrated in place never answer a present (even emptied or
    stale) carrier from the instance default or the process-wide selection.
    """

    _runtime, first = instance
    import app.api.request_active_context as request_context_module
    import app.api.routes.search as search_routes
    import app.api.routes.vault_resolution as vault_resolution

    def _no_default(*_a, **_kw):
        pytest.fail("default/no-vault resolution was consulted")

    monkeypatch.setattr(ask_routes, "run_ask_graph", lambda *_a, **_kw: pytest.fail("ASK ran"))
    monkeypatch.setattr(search_routes, "retrieve", lambda *_a, **_kw: pytest.fail("search ran"))
    monkeypatch.setattr(vault_resolution, "get_vault_manager", _no_default)
    monkeypatch.setattr(vault_resolution, "resolve_optional_vault_root", _no_default)
    monkeypatch.setattr(
        request_context_module, "compatibility_vault_root_or_selection_required", _no_default
    )

    # 1. Stripped carrier on the separately identified scoped routes.
    response = client.post("/api/ask/scoped", json={"question": "which context?"})
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "reselection_required"
    for path in ("/search/scoped?q=context", "/api/companion/vault/notes/scoped"):
        stripped = client.get(path)
        assert stripped.status_code == 401, (path, stripped.text)
        assert stripped.json()["detail"] == "reselection_required"

    # 2. No retry/downgrade through the legacy twin while the carrier is present.
    session = _create(client, first.vault_binding_id)["context_selection_id"]
    for carrier in (
        {"X-Active-Context-Session": session},
        {"X-Active-Context-Override": session},
        {"X-Active-Context-Session": ""},
    ):
        legacy_ask = client.post("/api/ask", json={"question": "which context?"}, headers=carrier)
        assert legacy_ask.status_code == 409, legacy_ask.text
        assert legacy_ask.json()["detail"] == "active_context_scoped_route_required"
        legacy_search = client.get("/search?q=context", headers=carrier)
        assert legacy_search.status_code == 409, legacy_search.text
        assert legacy_search.json()["detail"] == "active_context_scoped_route_required"

    # 3. Routes migrated in place by MVR-05B3: an emptied or stale carrier is a
    #    scoped request and fails reselection-required before any default lookup.
    for path in (
        "/api/artifacts/note?note_path=note.md",
        "/api/debug/panel?note_rel=note.md",
        "/api/eval-drafts",
    ):
        for carrier in (
            {"X-Active-Context-Session": ""},
            {"X-Active-Context-Override": ""},
            {"X-Active-Context-Session": "stale-session"},
        ):
            scoped = client.get(path, headers=carrier)
            assert scoped.status_code == 401, (path, carrier, scoped.text)
            assert str(scoped.json()["detail"]).startswith("reselection_required"), scoped.text
            assert "stale-session" not in scoped.text


def test_invalid_override_fails_closed_without_falling_back_to_session(
    instance, client, monkeypatch
) -> None:
    _runtime, first = instance
    session = _create(client, first.vault_binding_id)
    monkeypatch.setattr(ask_routes, "run_ask_graph", lambda *_a, **_kw: pytest.fail("ASK ran"))

    response = client.post(
        "/api/ask/scoped",
        json={"question": "which context?"},
        headers={
            "X-Active-Context-Session": session["context_selection_id"],
            "X-Active-Context-Override": "stale-override",
        },
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"].startswith("reselection_required")
    assert "stale-override" not in response.text


def test_scoped_reads_preserve_lifecycle_and_transfer_admission_guards(instance, client, monkeypatch) -> None:
    """Scoped reads do not bypass dormant lifecycle or transfer participant guards."""

    runtime, first = instance
    session = _create(client, first.vault_binding_id)
    scoped = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["context_generation"] == 1

    search = client.get(
        "/search/scoped?q=backend",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert search.status_code == 200, search.text
    assert "results" in search.json()

    import app.agents.ask.graph as ask_graph

    monkeypatch.setattr(
        ask_graph,
        "get_vault_manager",
        lambda: pytest.fail("scoped ASK must not consult the global vault manager"),
    )
    ask = client.post(
        "/api/ask/scoped",
        json={"question": "backend"},
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert ask.status_code == 200, ask.text
    assert "answer" in ask.json()

    # The shipped legacy route still uses its existing global-selection adapter;
    # enabling the backend carrier never silently activates the picker or rewires
    # that producer into the scoped route.
    legacy = client.get("/api/companion/vault/notes")
    assert legacy.status_code == 200, legacy.text
    assert "context_generation" not in legacy.json()

    # The actual dormant producer methods remain fail-closed after scoped reads;
    # route inventory alone would not prove that the capability gate still holds.
    with pytest.raises(CapabilityNotReadyError, match="MVR-06B"):
        runtime.remove(first.vault_binding_id)
    with pytest.raises(CapabilityNotReadyError, match="MVR-06C"):
        runtime.relocate(first.vault_binding_id, runtime.layout.root / "relocated")
    before_registry, before_ledger = runtime.registry.load(), runtime.ledger.load()
    with pytest.raises(RegistryError, match="transfer requires distinct channels"):
        runtime.transfer_to(runtime, first.vault_binding_id)
    assert runtime.registry.load() == before_registry and runtime.ledger.load() == before_ledger
    assert not (runtime.layout.root / "channel-transfer.json").exists()

    # Removal, relocation and transfer have no ungoverned request route.
    assert not any(
        route.path.endswith("/remove") or route.path.endswith("/relocate") or route.path.endswith("/transfer")
        for route in client.app.routes
        if hasattr(route, "path")
    )


# ---------------------------------------------------------------------------
# MVR-05B0 (#6135): invalid selection and zero-binding dimension proofs
# ---------------------------------------------------------------------------


@pytest.fixture()
def multi_instance(tmp_path, monkeypatch):
    """Default `one`, three more registered vaults, each with one marker note."""

    runtime, first, extra, record = provisioned_instance(
        tmp_path, extra_roots=("two", "three", "four")
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    bindings = {"one": first, "two": extra[0], "three": extra[1], "four": extra[2]}
    registrations = runtime.registry.load().registrations
    for name, binding in bindings.items():
        root = Path(registrations[binding.vault_binding_id].path)
        (root / f"{name}-marker.md").write_text(f"# {name}\n", encoding="utf-8")
    return runtime, bindings, record


def _remember_last_active(runtime, binding_id: str) -> None:
    """Drive the registry's picker-history producer, not a direct field write."""

    registration = runtime.registry.load().registrations[binding_id]
    runtime.registry.remember_registration(
        binding_id,
        KnownVaultRef(
            ref=registration.ref,
            path=registration.path,
            vault_id=registration.vault_id,
            local_instance_id=registration.local_instance_id,
            vault_name=registration.vault_name,
            last_opened_at="2026-10-15T00:00:00Z",
        ),
        make_active=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )


def _markers(response) -> set[str]:
    return {
        note["path"].split("/")[-1]
        for note in response.json().get("notes", [])
        if note["path"].endswith("-marker.md")
    }


def test_invalid_selection_never_falls_back(multi_instance, client, monkeypatch) -> None:
    """Every invalid or unauthorized carrier fails closed with the reselection/deny contract.

    The process is deliberately primed with every tempting fallback: an explicit instance
    default (`one`), registry last-active history and the process CWD on `three`, and a
    second valid session on `two`. No invalid carrier may be served from any of them.
    """

    runtime, bindings, _record = multi_instance
    import app.agents.ask.graph as ask_graph
    import app.vault.manager as vault_manager_module

    one, two, three, four = (
        bindings[name].vault_binding_id for name in ("one", "two", "three", "four")
    )
    _remember_last_active(runtime, three)
    monkeypatch.chdir(runtime.registry.load().registrations[three].path)
    before = runtime.registry.load()
    assert before.default_vault_binding_id == one
    assert before.last_active_vault_ref == before.registrations[three].ref

    now = {"t": 1_000.0}
    store = ContextSelectionStore(ttl_seconds=60, clock=lambda: now["t"])
    monkeypatch.setattr(selection_routes, "_STORE", store)
    expired = _create(client, two)["context_selection_id"]
    now["t"] += 61
    valid_other = _create(client, two)["context_selection_id"]
    removed = _create(client, four)["context_selection_id"]

    # The unauthorized case: GOV no longer knows `four`, so the shipped policy denies it.
    runtime.registry.remove_registration(
        four,
        expected_revision=runtime.registry.load().revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    # Nothing downstream of the request dependency may run, and the global vault
    # manager (the legacy last-active/CWD carrier) is never consulted.
    monkeypatch.setattr(ask_routes, "run_ask_graph", lambda *_a, **_kw: pytest.fail("ASK ran"))
    for module in (vault_manager_module, ask_graph):
        monkeypatch.setattr(
            module,
            "get_vault_manager",
            lambda: pytest.fail("invalid selection consulted the global vault manager"),
        )

    invalid_carriers = (
        ("unknown session", {"X-Active-Context-Session": "never-issued"}, 401),
        ("expired session", {"X-Active-Context-Session": expired}, 401),
        (
            "stale override over a valid session",
            {"X-Active-Context-Session": valid_other, "X-Active-Context-Override": "never-issued"},
            401,
        ),
        (
            "expired override over a valid session",
            {"X-Active-Context-Session": valid_other, "X-Active-Context-Override": expired},
            401,
        ),
        ("unauthorized binding", {"X-Active-Context-Session": removed}, 403),
        # GOV's deny dropped the selection: it is never reissued, even unchanged.
        ("denied selection is not reissued", {"X-Active-Context-Session": removed}, 401),
    )
    for label, headers, expected_status in invalid_carriers:
        notes = client.get(NOTES_URL, headers=headers)
        assert notes.status_code == expected_status, (label, notes.text)
        detail = notes.json()["detail"]
        if expected_status == 401:
            assert detail.startswith("reselection_required"), (label, detail)
        else:
            assert detail == "active_context_binding_denied", (label, detail)
        assert "notes" not in notes.json(), label
        for secret in ("never-issued", expired, removed):
            assert secret not in notes.text, label

        ask = client.post("/api/ask/scoped", json={"question": "which vault?"}, headers=headers)
        assert ask.status_code in {401, 403}, (label, ask.text)

        search = client.get("/search/scoped?q=marker", headers=headers)
        assert search.status_code in {401, 403}, (label, search.text)

    # The valid sibling session is untouched: it still reads exactly its own binding, at its
    # own generation, and was neither invalidated nor redirected by the failures above.
    sibling = client.get(NOTES_URL, headers={"X-Active-Context-Session": valid_other})
    assert sibling.status_code == 200, sibling.text
    assert _markers(sibling) == {"two-marker.md"}
    assert {note["vault_binding_id"] for note in sibling.json()["notes"]} == {two}
    assert sibling.json()["context_generation"] == 1

    # Nothing the failures could have used as a fallback moved.
    after = runtime.registry.load()
    assert after.default_vault_binding_id == one
    assert after.last_active_vault_ref == before.last_active_vault_ref

    # A process restart turns even the formerly valid sibling into an explicit
    # reselection, never into the default, last-active, or CWD vault.
    selection_routes.reset_selection_store_for_tests()
    restarted = client.get(NOTES_URL, headers={"X-Active-Context-Session": valid_other})
    assert restarted.status_code == 401, restarted.text
    assert restarted.json()["detail"].startswith("reselection_required")


def test_empty_dimension_selection_fails_closed(multi_instance, client) -> None:
    """KD-0F9089B13719: a zero-binding dimension is an invalid selection, not no-vault."""

    runtime, bindings, _record = multi_instance
    two = bindings["two"].vault_binding_id
    three = bindings["three"].vault_binding_id

    for dimension_id, members in (("work", [two]), ("solo", [three])):
        created = client.post(
            DIMENSIONS_URL,
            json={
                "dimension_id": dimension_id,
                "display_name": dimension_id,
                "vault_binding_ids": members,
            },
        )
        assert created.status_code == 201, created.text

    # Control: a populated dimension resolves and drives a scoped read.
    session = client.post(SELECTION_URL, json={"dimension_id": "work"})
    assert session.status_code == 201, session.text
    bearer = session.json()["context_selection_id"]
    assert session.json()["context"]["vault_binding_ids"] == [two]

    # Two production routes to an empty membership: the operator empties it, and the
    # transactional membership repair strips a de-registered member.
    emptied = client.put(f"{DIMENSIONS_URL}/work/members", json={"vault_binding_ids": []})
    assert emptied.status_code == 200, emptied.text
    runtime.registry.remove_registration(
        three,
        expected_revision=runtime.registry.load().revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert client.get(f"{DIMENSIONS_URL}/solo").json()["vault_binding_ids"] == []

    for dimension_id in ("work", "solo"):
        resolved = client.get(f"{DIMENSIONS_URL}/{dimension_id}/resolve")
        assert resolved.status_code == 409, resolved.text
        assert resolved.json()["detail"].startswith("dimension_empty")

        create = client.post(SELECTION_URL, json={"dimension_id": dimension_id})
        assert create.status_code == 409, create.text
        assert create.json()["detail"].startswith("dimension_empty")
        assert "context_selection_id" not in create.json()

        replace = client.put(
            SELECTION_URL,
            json={"dimension_id": dimension_id},
            headers={"X-Active-Context-Session": bearer},
        )
        assert replace.status_code == 409, replace.text
        assert replace.json()["detail"].startswith("dimension_empty")

    # The failed replacements left the existing session exactly as it was.
    unchanged = client.get(SELECTION_URL, headers={"X-Active-Context-Session": bearer})
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["context"]["vault_binding_ids"] == [two]
    assert unchanged.json()["context"]["generation"] == 1
    scoped = client.get(NOTES_URL, headers={"X-Active-Context-Session": bearer})
    assert scoped.status_code == 200, scoped.text
    assert _markers(scoped) == {"two-marker.md"}

    # The request path refuses a zero-binding dimension selection on its own, even if one
    # reached the production store: it is reselection, never an empty or no-vault context.
    store = selection_routes.get_selection_store()
    derived = selection_routes.build_selection_service(store).derive("trusted_loopback")
    raw, _ = store.create(
        principal=derived.principal,
        instance_identity=derived.instance_identity,
        workspace=derived.workspace,
        scope=derived.scope,
        sphere_memberships=derived.sphere_memberships,
        situated_identity=derived.situated_identity,
        binding_ids=(),
        dimension_filter=DimensionFilter(dimension_id="work", dimension_revision=2),
    )
    empty = client.get(NOTES_URL, headers={"X-Active-Context-Session": raw})
    assert empty.status_code == 401, empty.text
    assert empty.json()["detail"].startswith("reselection_required")
    assert "notes" not in empty.json()

    # An explicit, non-dimension empty selection is still the healthy no-vault journey.
    explicit_empty = client.post(SELECTION_URL, json={"vault_binding_ids": []})
    assert explicit_empty.status_code == 201, explicit_empty.text
    assert explicit_empty.json()["context"]["dimension_id"] is None
