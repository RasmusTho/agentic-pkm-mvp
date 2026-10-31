"""Production request isolation and authority-change fencing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.instance.local_operator_principal import SUBJECT_LOOPBACK
from tests._mvr03_principal_harness import principal_store, provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

SELECTION_URL = "/api/companion/active-context/selection"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    return runtime, first, extra[0]


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


def test_screen_control_refuses_authorized_scoped_session_before_legacy_read(
    instance, client, monkeypatch
) -> None:
    """A valid vault-B carrier cannot fall back to the process-selected vault A."""
    from pathlib import Path

    import app.vault.manager as vault_manager_module
    from app.api.routes import heimdal_screen
    from app.vault.manager import VaultManager

    _runtime, first, second = instance
    manager = VaultManager()
    manager.select_vault(Path(first.path), remember=False)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", manager)
    read_roots: list[Path] = []

    def binding_controls(context, **_kwargs):
        # MVR-05B4c6: the scoped read answers from the request binding's settings.
        read_roots.append(Path(context.active_vault_path).resolve())
        return {"state": "paused"}

    monkeypatch.setattr(heimdal_screen, "screen_control_status", binding_controls)
    session = _create(client, second.vault_binding_id)

    response = client.get(
        "/api/heimdal/screen/control",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
        params={"app_id": "com.editor"},
    )
    assert response.status_code == 200, response.text
    assert read_roots == [Path(second.path).resolve()]


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("X-Active-Context-Session", ""),
        ("X-Active-Context-Session", "unknown-session"),
        ("X-Active-Context-Override", "unknown-override"),
    ],
)
def test_screen_control_refuses_unresolved_scoped_carrier_before_legacy_read(
    instance, client, monkeypatch, header, value
) -> None:
    """Blank or unresolved carriers cannot downgrade to the process-selected vault."""
    from pathlib import Path

    import app.vault.manager as vault_manager_module
    from app.api.routes import heimdal_screen
    from app.vault.manager import VaultManager

    _runtime, first, _second = instance
    manager = VaultManager()
    manager.select_vault(Path(first.path), remember=False)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", manager)
    monkeypatch.setattr(
        heimdal_screen,
        "screen_control_status",
        lambda *_args, **_kwargs: pytest.fail("unresolved scoped request read process-selected controls"),
    )

    response = client.get("/api/heimdal/screen/control", headers={header: value})
    # The presented carrier is validated fail-closed before any read (MVR-05B4c6).
    assert response.status_code in (401, 403, 409), response.text


def test_two_sessions_use_distinct_vaults_without_cross_talk(instance, client, monkeypatch) -> None:
    """Two real scoped API reads hold shared fences concurrently and stay isolated."""

    runtime, first, second = instance
    first_root = runtime.registry.lookup(first.vault_binding_id)
    second_root = runtime.registry.lookup(second.vault_binding_id)
    assert first_root is not None and second_root is not None
    from pathlib import Path

    Path(first_root.path, "only-first.md").write_text("# First", encoding="utf-8")
    Path(second_root.path, "only-second.md").write_text("# Second", encoding="utf-8")
    first_session = _create(client, first.vault_binding_id)
    second_session = _create(client, second.vault_binding_id)

    entered = Barrier(2)
    from app.api.routes import companion as companion_routes

    original = companion_routes._list_vault_notes

    def paused(root, q=""):
        entered.wait(timeout=5)
        return original(root, q=q)

    # Synchronize inside the actual scoped route after it has acquired its
    # binding effect lease. This proves API-session isolation, not only a
    # helper-level filesystem projection.
    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused)

    def read(session: dict):
        response = client.get(
            "/api/companion/vault/notes/scoped",
            headers={"X-Active-Context-Session": session["context_selection_id"]},
        )
        assert response.status_code == 200, response.text
        return [
            (note["vault_binding_id"], note["path"])
            for note in response.json()["notes"]
            if note["path"].startswith("only-")
        ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(read, first_session),
            pool.submit(read, second_session),
        ]
        responses = [future.result(timeout=5) for future in futures]

    assert responses == [
        [(first.vault_binding_id, "only-first.md")],
        [(second.vault_binding_id, "only-second.md")],
    ]

    # MVR-05B2: the migrated companion read routes (the same URLs the legacy
    # carrier-free journey uses) bind to each request's own context while both
    # requests hold their shared binding leases concurrently.
    migrated_entered = Barrier(2)

    def paused_migrated(root, q=""):
        migrated_entered.wait(timeout=5)
        return original(root, q=q)

    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused_migrated)

    def read_migrated(session: dict):
        headers = {"X-Active-Context-Session": session["context_selection_id"]}
        response = client.get("/api/companion/vault/notes", headers=headers)
        assert response.status_code == 200, response.text
        context = client.get("/api/companion/vault/context", headers=headers)
        assert context.status_code == 200, context.text
        return (
            sorted(
                note["path"] for note in response.json()["notes"] if note["path"].startswith("only-")
            ),
            context.json()["active_vault_path"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(read_migrated, first_session),
            pool.submit(read_migrated, second_session),
        ]
        migrated = [future.result(timeout=5) for future in futures]

    assert migrated == [
        (["only-first.md"], str(Path(first_root.path).resolve())),
        (["only-second.md"], str(Path(second_root.path).resolve())),
    ]
    # Neither scoped read consulted or created the process-wide selector.
    import app.vault.manager as vault_manager_module

    assert vault_manager_module._GLOBAL_MANAGER is None
    assert runtime.registry.load().default_vault_binding_id == first.vault_binding_id


def test_authority_change_cannot_cross_read_effect_window(instance, client, monkeypatch) -> None:
    """Rotation waits for real scoped reads, then invalidates their stale session.

    Both the dedicated scoped route and a migrated companion read route (MVR-05B2)
    hold the shared binding lease from final revalidation through response
    publication, so the exclusive authority mutation cannot cross either.
    """

    runtime, first, _second = instance
    session = _create(client, first.vault_binding_id)
    headers = {"X-Active-Context-Session": session["context_selection_id"]}
    read_routes = ("/api/companion/vault/notes/scoped", "/api/companion/vault/notes")
    entered = Barrier(len(read_routes) + 1)
    release = Event()
    from app.api.routes import companion as companion_routes

    original = companion_routes._list_vault_notes

    def paused(root, q=""):
        entered.wait(timeout=5)
        assert release.wait(timeout=5)
        return original(root, q=q)

    monkeypatch.setattr(companion_routes, "_list_vault_notes", paused)

    with ThreadPoolExecutor(max_workers=len(read_routes) + 1) as pool:
        read_futures = [pool.submit(client.get, route, headers=headers) for route in read_routes]
        entered.wait(timeout=5)
        rotation_future = pool.submit(
            principal_store(runtime).rotate_credential,
            credential="rotated-for-test",
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
        with pytest.raises(TimeoutError):
            rotation_future.result(timeout=0.1)
        # Releasing the reads lets the exclusive authority mutation acquire the
        # principal lock. Every future must complete: no lock-order deadlock.
        release.set()
        read_responses = [future.result(timeout=5) for future in read_futures]
        rotated = rotation_future.result(timeout=5)

    for read_response in read_responses:
        assert read_response.status_code == 200, read_response.text
    assert rotated.revision == session["context"]["generation"] + 1
    for route in read_routes:
        stale = client.get(route, headers=headers)
        assert stale.status_code == 401, stale.text
        assert (
            stale.json()["detail"]
            == "reselection_required: selection is not resolvable for this caller"
        )


def test_subject_revocation_rejects_a_previously_issued_session(instance, client) -> None:
    runtime, first, _second = instance
    session = _create(client, first.vault_binding_id)
    store = principal_store(runtime)
    store.rotate_credential(
        credential="credential-to-keep-loopback-revocable",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    revoked = store.revoke_subject(
        SUBJECT_LOOPBACK,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert SUBJECT_LOOPBACK not in revoked.subjects

    stale = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": session["context_selection_id"]},
    )
    assert stale.status_code == 401, stale.text
    assert stale.json()["detail"] == "reselection_required"


def test_explicit_empty_selection_renders_no_vault_state_without_legacy_lookup(
    instance, client, monkeypatch
) -> None:
    """#6156 review: a healthy zero-binding selection is the scoped no-vault journey."""

    from app.api.routes import companion as companion_routes

    def legacy_forbidden(*_args, **_kwargs):
        raise AssertionError("scoped no-vault read consulted the legacy process-wide selection")

    monkeypatch.setattr(companion_routes, "_legacy_companion_vault_manager", legacy_forbidden)
    monkeypatch.setattr(companion_routes, "_legacy_configured_vault_root", legacy_forbidden)
    response = client.post(SELECTION_URL, json={"vault_binding_ids": []})
    assert response.status_code == 201, response.text
    headers = {"X-Active-Context-Session": response.json()["context_selection_id"]}

    notes = client.get("/api/companion/vault/notes", headers=headers)
    context = client.get("/api/companion/vault/context", headers=headers)

    for result in (notes, context):
        assert result.status_code == 200, result.text
        assert "active_context_single_binding_required" not in result.text
    assert "no_vault_bound" in notes.text
    assert context.json().get("active_vault_path") in (None, "")


def test_explicit_empty_selection_reads_inside_the_principal_effect_window(
    instance, client, monkeypatch
) -> None:
    """#6156 review: the zero-binding journey keeps the read-to-publication fence."""

    from contextlib import contextmanager

    from app.api.routes import companion as companion_routes

    original = companion_routes.context_bound_read_window
    entered: list[int] = []

    @contextmanager
    def recording(context, **kwargs):
        with original(context, **kwargs) as roots:
            entered.append(len(roots))
            yield roots

    monkeypatch.setattr(companion_routes, "context_bound_read_window", recording)
    response = client.post(SELECTION_URL, json={"vault_binding_ids": []})
    assert response.status_code == 201, response.text
    headers = {"X-Active-Context-Session": response.json()["context_selection_id"]}

    browse = client.get("/api/companion/vault/browse", headers=headers)

    assert browse.status_code == 200, browse.text
    assert entered == [0]


def test_scoped_reads_do_not_adopt_unstamped_artifact_projections(instance, client, monkeypatch) -> None:
    """#6156 review: a scoped read never shows unstamped process-global artifact state.

    Agent-memory posture (MVR-05B4c1) and panel state / receipts (MVR-05B4c2) are
    binding-aware and covered by ``tests/api/test_mvr05b4c_*_binding.py``; here the
    process stores hold only unstamped state, which a scoped read must not see.
    """

    from pathlib import Path

    import app.panel.confirmation as confirm_module

    monkeypatch.setattr(confirm_module._proposal_store, "_proposals", {})
    monkeypatch.setattr(confirm_module._idempotency_store, "_cache", {})
    runtime, first, _second = instance
    first_root = runtime.registry.lookup(first.vault_binding_id)
    assert first_root is not None
    Path(first_root.path, "shared.md").write_text("# Shared\n", encoding="utf-8")
    session = _create(client, first.vault_binding_id)
    headers = {"X-Active-Context-Session": session["context_selection_id"]}

    browser = client.get("/api/companion/vault-browser", headers=headers)
    workspace = client.get(
        "/api/companion/workspace", params={"note_path": "shared.md"}, headers=headers
    )

    assert browser.status_code == 200, browser.text
    assert all(note.get("receipts") in ([], None) for note in browser.json()["notes"])
    assert workspace.status_code == 200, workspace.text
    panel = workspace.json()["panel"]
    assert panel["proposal_count"] == 0
    assert panel["receipt_count"] == 0


def test_scoped_now_orientation_and_browse_stay_inside_the_bound_vault(
    instance, client, monkeypatch
) -> None:
    """#6156 review: /now nudges, orientation stores and browse base are binding-confined."""

    from pathlib import Path

    from app.api.routes import companion as companion_routes
    from app.relevance import now_surface

    runtime, first, _second = instance

    def forbidden(*_args, **_kwargs):
        raise AssertionError("scoped read consulted a process-global source")

    monkeypatch.setattr(now_surface, "query_reachout_receipts", forbidden)
    monkeypatch.setattr(companion_routes, "_orientation_memory_review_queue", forbidden)
    monkeypatch.setattr(companion_routes, "_append_orientation_memory_intent_trace", forbidden)
    # MVR-05B4c4: runtime signals and the leave point are read for the request binding only.
    real_signals = companion_routes.get_orientation_signals
    real_leave_point = companion_routes._orientation_leave_point

    def binding_signals(vault_binding_id=None):
        assert vault_binding_id == first.vault_binding_id, "scoped read used process-wide signals"
        return real_signals(vault_binding_id)

    def binding_leave_point(*args, **kwargs):
        assert kwargs.get("vault_binding_id") == first.vault_binding_id
        return real_leave_point(*args, **kwargs)

    monkeypatch.setattr(companion_routes, "get_orientation_signals", binding_signals)
    monkeypatch.setattr(companion_routes, "_orientation_leave_point", binding_leave_point)
    # A global browse override must not widen a scoped browse beyond its root.
    monkeypatch.setenv("VAULT_BROWSE_ROOT", str(Path(runtime.registry.lookup(first.vault_binding_id).path).parent))
    first_root = runtime.registry.lookup(first.vault_binding_id)
    assert first_root is not None
    from tests.helpers.vault_settings import initialize_test_vault

    initialize_test_vault(Path(first_root.path))
    session = _create(client, first.vault_binding_id)
    headers = {"X-Active-Context-Session": session["context_selection_id"]}

    Path(first_root.path, "focus.md").write_text("# Focus\n", encoding="utf-8")
    workspace = client.get(
        "/api/companion/workspace", params={"note_path": "focus.md"}, headers=headers
    )
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["runtime"]["resurface"]["candidates"] == []
    # The process-wide watcher heartbeat may name another vault: not reported.
    assert workspace.json()["runtime"]["ingest"]["state"] in {"unbound", "unavailable"}
    assert workspace.json()["runtime"]["ingest"]["watcher_vault_path"] is None
    now = client.get("/api/companion/now", headers=headers)
    orientation = client.get("/api/companion/orientation", headers=headers)
    browse = client.get("/api/companion/vault/browse", headers=headers)

    assert now.status_code == 200, now.text
    assert orientation.status_code == 200, orientation.text
    body = orientation.json()
    assert body["memory"]["pending_candidate_count"] == 0
    assert body["governance"]["pending_proposal_count"] == 0
    assert browse.status_code == 200, browse.text
    assert browse.json()["base"] == str(Path(first_root.path).resolve())


def test_scoped_identity_is_stable_and_review_queue_serves_request_binding_only(instance, client) -> None:
    """#6156 review: binding-snapshot identity; MVR-05B4c1: the queue answers per binding."""

    runtime, first, _second = instance
    registration = runtime.registry.lookup(first.vault_binding_id)
    assert registration is not None
    session = _create(client, first.vault_binding_id)
    headers = {"X-Active-Context-Session": session["context_selection_id"]}

    contexts = [client.get("/api/companion/vault/context", headers=headers) for _ in range(2)]
    queue = client.get("/api/companion/memory/review-queue", headers=headers)

    for response in contexts:
        assert response.status_code == 200, response.text
    ids = {response.json().get("active_vault_id") for response in contexts}
    assert len(ids) == 1
    if registration.vault_id:
        assert ids == {registration.vault_id}
    assert queue.status_code == 200, queue.text
    assert queue.json()["candidates"] == []


@pytest.mark.parametrize("header", ["X-Active-Context-Session", "X-Active-Context-Override"])
def test_blank_carrier_fails_closed_instead_of_legacy_fallback(instance, client, header) -> None:
    """#6156 review: a present-but-blank carrier is scoped and invalid, never legacy."""

    blank = {header: ""}
    notes = client.get("/api/companion/vault/notes", headers=blank)
    queue = client.get("/api/companion/memory/review-queue", headers=blank)

    assert notes.status_code in (400, 401, 409), notes.text
    assert "notes" not in notes.json()
    assert queue.status_code in (400, 401, 409), queue.text
    assert "candidates" not in queue.json()


def test_parent_request_context_acceptance(tmp_path, monkeypatch) -> None:
    """MVR-05D aggregate: the parent #2143 request contract on the production seam.

    One provisioned two-binding instance composes, through real API requests:
    two-session isolation, override-over-session resolution precedence,
    projection separation for a duplicate artifact identity, retrieval
    provenance, governed writes with a binding/context outbox envelope, and
    fail-closed stale selection after a restart.
    """
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from app.api.routes import ask as ask_routes
    from app.api.routes import capture as capture_routes
    from app.instance.runtime import open_default_vault_service
    from app.retrieval import hybrid
    from app.retrieval.capability import RetrievalRequest, retrieve
    from app.services import outbox as outbox_service
    from app.services.outbox_producers import OUTBOX_ENVELOPE_VERSION
    from tests.helpers.vault_settings import initialize_test_vault
    from tests.retrieval.test_retrieval_capability import _patch_embeddings

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    for registration in (first, second):
        initialize_test_vault(Path(registration.path))
        runtime.complete_initialization(
            registration.vault_binding_id,
            vault_id="vault-" + registration.vault_binding_id,
            local_instance_id=registration.local_instance_id,
        )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app)
    first_root = Path(first.path).resolve()
    second_root = Path(second.path).resolve()

    # 1. Two-session isolation: concurrent scoped reads stay in their own vault.
    (first_root / "only-first.md").write_text("# First\n", encoding="utf-8")
    (second_root / "only-second.md").write_text("# Second\n", encoding="utf-8")
    session_a = _create(client, first.vault_binding_id)
    session_b = _create(client, second.vault_binding_id)
    headers_a = {"X-Active-Context-Session": session_a["context_selection_id"]}
    headers_b = {"X-Active-Context-Session": session_b["context_selection_id"]}

    def scoped_notes(headers: dict) -> list[tuple[str, str]]:
        response = client.get("/api/companion/vault/notes/scoped", headers=headers)
        assert response.status_code == 200, response.text
        return sorted(
            (note["vault_binding_id"], note["path"])
            for note in response.json()["notes"]
            if note["path"].startswith("only-")
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        isolated = list(pool.map(scoped_notes, (headers_a, headers_b)))
    assert isolated == [
        [(first.vault_binding_id, "only-first.md")],
        [(second.vault_binding_id, "only-second.md")],
    ]

    # 2. Resolution precedence: a one-request override outranks the retained
    #    session without mutating it; the session alone resolves its own vault.
    overridden = client.get(
        "/api/companion/vault/context",
        headers={**headers_a, "X-Active-Context-Override": session_b["context_selection_id"]},
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["active_vault_path"] == str(second_root)
    plain = client.get("/api/companion/vault/context", headers=headers_a)
    assert plain.status_code == 200, plain.text
    assert plain.json()["active_vault_path"] == str(first_root)
    retained = client.get(SELECTION_URL, headers=headers_a)
    assert retained.status_code == 200, retained.text
    assert retained.json()["context"]["vault_binding_ids"] == [first.vault_binding_id]
    assert retained.json()["context"]["generation"] == session_a["context"]["generation"]

    # 3. Projection separation: one artifact identity in both vaults stays
    #    namespaced by binding in a many-binding request.
    shared_identity = "---\nuuid: 00000000-0000-4000-8000-000000000d05\n---\n"
    (first_root / "only-shared.md").write_text(shared_identity + "# Alpha\n", encoding="utf-8")
    (second_root / "only-shared.md").write_text(shared_identity + "# Beta\n", encoding="utf-8")
    both = client.post(
        SELECTION_URL, json={"vault_binding_ids": [first.vault_binding_id, second.vault_binding_id]}
    )
    assert both.status_code == 201, both.text
    many_headers = {"X-Active-Context-Session": both.json()["context_selection_id"]}
    response = client.get("/api/companion/vault/notes/scoped", headers=many_headers)
    assert response.status_code == 200, response.text
    shared_rows = sorted(
        (note["vault_binding_id"], note["title"], note["context_generation"])
        for note in response.json()["notes"]
        if note["path"] == "only-shared.md"
    )
    many_generation = both.json()["context"]["generation"]
    assert shared_rows == sorted(
        [
            (first.vault_binding_id, "Alpha", many_generation),
            (second.vault_binding_id, "Beta", many_generation),
        ]
    )

    # 4. Retrieval provenance: the context the production request resolved is
    #    the one retrieval filters and stamps on every hit.
    seen: list = []
    monkeypatch.setattr(
        ask_routes,
        "run_ask_graph",
        lambda *_a, **kwargs: seen.append(kwargs["active_context"])
        or SimpleNamespace(answer="ok", hits=[]),
    )
    monkeypatch.setattr(ask_routes, "_ensure_hybrid_store_loaded", lambda: None)
    ask_routes._HYBRID_WARMED = True
    try:
        asked = client.post("/api/ask/scoped", json={"question": "needle?"}, headers=headers_a)
    finally:
        ask_routes._HYBRID_WARMED = False
    assert asked.status_code == 200, asked.text
    request_context = seen[-1]
    assert request_context.binding_ids == (first.vault_binding_id,)
    _patch_embeddings(monkeypatch)

    class DurableIndex:
        def generation_for_bindings(self, _binding_ids=None):
            return "durable-generation-1"

        def all_rows_for_bindings(self, _binding_ids=None):
            return [
                {
                    "object_id": object_id,
                    "text": "needle",
                    "payload": {"domain": "core", "text": "needle"},
                    "vault_binding_id": binding,
                    "embedding": [0.1, 0.1, 0.1],
                }
                for object_id, binding in (
                    ("in-a", first.vault_binding_id),
                    ("in-b", second.vault_binding_id),
                )
            ]

    monkeypatch.setattr("app.stores.get_vector_index", lambda: DurableIndex())
    hybrid.reset_durable_rebuild_state()
    hybrid.rebuild_from_durable_index(force=True)
    try:
        retrieved = retrieve(
            RetrievalRequest(query="needle", k=5, scope="core", active_context=request_context)
        )
    finally:
        hybrid.reset_durable_rebuild_state()
    assert [hit.doc_id for hit in retrieved.hits] == ["in-a"]
    assert retrieved.hits[0].payload["vault_binding_id"] == first.vault_binding_id
    assert retrieved.hits[0].payload["context_generation"] == request_context.generation

    # 5. Governed writes: one explicit authorized target inside the selected
    #    set; its durable outbox row carries the binding/context envelope.
    recorded: list[tuple] = []

    class _Recorder:
        def execute(self, sql, params=()):
            recorded.append((sql, tuple(params)))
            return SimpleNamespace(fetchone=lambda: (params[0],))

        def close(self):
            return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://recorder.invalid:5432/mvr05d")
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: _Recorder())
    monkeypatch.setattr(outbox_service, "_self_owned_outbox_write_policy", lambda **_: "connect")
    monkeypatch.setattr(capture_routes, "_offer_question_registration_proposal", lambda **_: None)
    written = client.post(
        "/api/companion/capture/scoped",
        json={"text": "Parent acceptance", "target_binding_id": first.vault_binding_id},
        headers=headers_a,
    )
    assert written.status_code == 200, written.text
    receipt = written.json()["governed_write"]
    assert receipt["decision_token"]["target_binding_id"] == first.vault_binding_id
    assert "Parent acceptance" in (first_root / "Inbox/inbox.md").read_text(encoding="utf-8")
    assert not (second_root / "Inbox/inbox.md").exists()
    (insert,) = [params for sql, params in recorded if sql.lower().startswith("insert into outbox")]
    meta = json.loads(insert[2])["meta"]
    assert insert[6] == first.vault_binding_id
    assert meta["outbox_envelope"] == OUTBOX_ENVELOPE_VERSION
    assert meta["routing_class"] == "vault_bound"
    assert meta["outbox_producer"] == "capture.appended"
    assert meta["producer_context"] == {
        "kind": "active_context",
        "context_id": session_a["context"]["context_id"],
        "context_generation": session_a["context"]["generation"],
    }
    refused = client.post(
        "/api/companion/capture/scoped",
        json={"text": "Forbidden", "target_binding_id": second.vault_binding_id},
        headers=headers_a,
    )
    assert refused.status_code == 409, refused.text
    assert not (second_root / "Inbox/inbox.md").exists()

    # 6. Fail-closed stale selection: after a restart the old bearer requires
    #    visible reselection and never falls back to the instance default.
    open_default_vault_service(runtime.layout.registry_path).set(first.vault_binding_id)
    selection_routes.reset_selection_store_for_tests()
    stale_read = client.get("/api/companion/vault/notes/scoped", headers=headers_a)
    assert stale_read.status_code == 401, stale_read.text
    assert str(stale_read.json()["detail"]).startswith("reselection_required")
    stale_write = client.post(
        "/api/companion/capture/scoped",
        json={"text": "Stale", "target_binding_id": first.vault_binding_id},
        headers=headers_a,
    )
    assert stale_write.status_code in (401, 409), stale_write.text
    assert "Stale" not in (first_root / "Inbox/inbox.md").read_text(encoding="utf-8")
