"""MVR-05B compatibility handoff behavior at the production seams."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.routes.active_context_selection as selection_routes
import app.api.routes.companion as companion_module
from app.api.app import app
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.first_vault_bootstrap import FirstVaultPreconditionStore
from app.instance.default_vault import InstanceDefaultVaultService
from app.instance.settings_rebind import (
    SettingsRebindActivation,
    SettingsRebindRecord,
)
from app.instance.vault_registry import KnownVaultRef
from app.vault.manager import VaultManager
from app.vault.app_local import AppLocalSettingsStore
from app.workers import outbox_worker
from app.watcher import registry as watcher_registry
from app.watcher.settings_rebind import (
    load_settings_rebind_watcher_receipt,
)
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests._mvr05b_bootstrap_harness import fresh_no_vault_instance
from tests.integration.test_watcher_cross_process_rebind import (
    _event_paths,
    _fixture,
    _record_reload,
    _revision_receipt_path,
)


pytestmark = pytest.mark.not_pg


class _EffectLease:
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self.entered = entered
        self.release = release

    @contextmanager
    def shared_effect(self, *_args: object, **_kwargs: object):
        self.entered.set()
        assert self.release.wait(timeout=5)
        yield


def _known_ref(runtime, binding_id: str) -> KnownVaultRef:
    registration = runtime.registry.load().registrations[binding_id]
    return KnownVaultRef(
        ref=registration.ref,
        path=registration.path,
        vault_id=registration.vault_id,
        local_instance_id=registration.local_instance_id,
        vault_name=registration.vault_name,
        last_opened_at="2026-09-08T00:00:00Z",
    )


def _compatibility_message(root: Path) -> dict[str, object]:
    return {
        "id": "compatibility-row-1",
        "topic": "ingest.vault.changed",
        "payload": {},
        "vault_binding_id": COMPATIBILITY_BINDING_ID,
        "event": SimpleNamespace(meta={}),
    }


def test_interim_default_mutation_rebinds_before_foreground_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default SET and CLEAR use one handoff and preserve interaction history."""

    runtime, _vault_a, _vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    events: list[object] = []
    service = InstanceDefaultVaultService(
        runtime.registry,
        capability=STORAGE_MUTATION_CAPABILITY,
        emit_event=events.append,
    )

    set_receipt = service.set("binding-b")
    after_set = runtime.registry.load()
    assert set_receipt.vault_binding_id == "binding-b"
    assert after_set.default_vault_binding_id == "binding-b"
    assert after_set.last_active_vault_ref is None
    assert runtime.open_settings_rebind_store().read().phase == "no_lifecycle"

    clear_receipt = service.clear()
    after_clear = runtime.registry.load()
    cleared = runtime.open_settings_rebind_store().read()
    assert clear_receipt.vault_binding_id is None
    assert after_clear.default_vault_binding_id is None
    assert after_clear.default_vault_provenance is None
    assert after_clear.last_active_vault_ref is None
    assert cleared.candidate_binding_id is None
    assert cleared.reload_revision == cleared.desired_revision
    assert len(events) == 2


def test_picker_rebind_drains_scalar_worker_before_binding_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admitted compatibility effect finishes before B can be prepared."""

    runtime, _vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.workers.outbox_binding_gate.validate_frozen_binding_runtime",
        lambda value: value,
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    entered = threading.Event()
    release = threading.Event()
    lease = _EffectLease(entered, release)
    worker_runtime = SimpleNamespace(
        vault_binding_id="binding-a",
        binding_revision=1,
        authority="allow",
        authorization_epoch="epoch-a",
        channel_id="test",
        root=Path(runtime.registry.load().registrations["binding-a"].path),
        registry_store=runtime.registry,
        effect_leases=lease,
    )
    activation = SettingsRebindActivation.from_environment(runtime.registry)
    results: list[SettingsRebindRecord] = []
    errors: list[BaseException] = []

    message = _compatibility_message(worker_runtime.root)
    dispatched: list[object] = []
    acknowledged: list[str] = []
    monkeypatch.setattr(
        outbox_worker,
        "resolve_scalar_binding_runtime",
        lambda *, vault_root: worker_runtime,
    )
    monkeypatch.setattr(
        outbox_worker,
        "poll_outbox_one",
        lambda **_kwargs: message,
    )
    monkeypatch.setattr(
        outbox_worker,
        "_dispatch_topic",
        lambda *args, **kwargs: dispatched.append((args, kwargs)),
    )
    monkeypatch.setattr(
        outbox_worker,
        "ack_outbox",
        lambda message_id: acknowledged.append(str(message_id)),
    )

    def admit_a() -> None:
        try:
            result = outbox_worker.run_once(vault_root=worker_runtime.root)
            assert result.state == "processed"
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=admit_a)
    worker.start()
    assert entered.wait(timeout=5)

    def activate_b() -> None:
        try:
            results.append(
                activation.activate(
                    selection=_known_ref(runtime, "binding-b"),
                    candidate_binding_id="binding-b",
                    candidate_root=vault_b,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    picker = threading.Thread(target=activate_b)
    picker.start()
    time.sleep(0.05)
    assert runtime.open_settings_rebind_store().read().candidate_binding_id == "binding-a"
    assert not results

    release.set()
    worker.join(timeout=5)
    picker.join(timeout=5)
    assert not worker.is_alive()
    assert not picker.is_alive()
    assert not errors
    assert len(results) == 1
    assert len(dispatched) == 1
    assert acknowledged == ["compatibility-row-1"]
    final = runtime.open_settings_rebind_store().read()
    assert final.candidate_binding_id == "binding-b"
    assert final.scalar_drain_revision == final.desired_revision
    assert final.phase == "no_lifecycle"


def test_direct_filesystem_write_between_scan_and_commit_is_receipted_under_old_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watcher brackets a direct A write even when no event hint survives."""

    runtime, vault_a, vault_b, config_path = _fixture(tmp_path, monkeypatch)
    watcher_registry.run_registry_forever(config_path, max_ticks=1)
    between = vault_a / "direct-between-scan-and-commit.md"
    between.write_text("old root remains authoritative\n", encoding="utf-8")
    activation = SettingsRebindActivation.from_environment(runtime.registry)
    commit_started = threading.Event()
    commit_release = threading.Event()
    commit_done = threading.Event()
    activation_result: list[SettingsRebindRecord] = []
    activation_errors: list[BaseException] = []
    watcher_errors: list[BaseException] = []
    original_commit = activation.store.commit_selection

    def pause_before_commit(**kwargs: object) -> SettingsRebindRecord:
        commit_started.set()
        assert commit_release.wait(timeout=5)
        result = original_commit(**kwargs)
        commit_done.set()
        return result

    monkeypatch.setattr(activation.store, "commit_selection", pause_before_commit)

    def activate_b() -> None:
        try:
            activation_result.append(
                activation.activate(
                    selection=_known_ref(runtime, "binding-b"),
                    candidate_binding_id="binding-b",
                    candidate_root=vault_b,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            activation_errors.append(exc)

    picker = threading.Thread(target=activate_b)
    picker.start()
    assert commit_started.wait(timeout=5)
    (vault_b / "must-not-be-seen.md").write_text("candidate\n", encoding="utf-8")

    def reconcile_after_commit() -> None:
        try:
            assert commit_done.wait(timeout=5)
            watcher_registry.run_registry_forever(config_path, max_ticks=2)
        except BaseException as exc:  # pragma: no cover - asserted below
            watcher_errors.append(exc)

    watcher = threading.Thread(target=reconcile_after_commit)
    watcher.start()
    commit_release.set()
    picker.join(timeout=5)
    watcher.join(timeout=5)
    assert not picker.is_alive()
    assert not watcher.is_alive()
    assert not activation_errors
    assert not watcher_errors
    assert len(activation_result) == 1

    receipt = load_settings_rebind_watcher_receipt(_revision_receipt_path(tmp_path, 1))
    assert receipt.stage == "completed"
    assert any(item.relative_path == between.name for item in receipt.buffer)
    assert all(path.startswith(str(vault_a)) for path in _event_paths(tmp_path))
    assert not any(path.startswith(str(vault_b)) for path in _event_paths(tmp_path))


def test_picker_and_watcher_rebind_is_failure_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-commit cancellation and post-commit retry both converge durably."""

    runtime, _vault_a, vault_b, config_path = _fixture(
        tmp_path, monkeypatch, enabled=True, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    registration = runtime.registry.load().registrations["binding-b"]
    activation = SettingsRebindActivation.from_environment(runtime.registry)
    tripped = False
    post_commit_fault = False
    commit_done = threading.Event()
    watcher_errors: list[BaseException] = []
    watcher_thread: threading.Thread | None = None
    original_commit = activation.store.commit_selection

    def mark_commit_done(**kwargs: object) -> SettingsRebindRecord:
        result = original_commit(**kwargs)
        commit_done.set()
        return result

    monkeypatch.setattr(activation.store, "commit_selection", mark_commit_done)

    def reconcile_retry() -> None:
        try:
            watcher_registry.run_registry_once(config_path)
            assert commit_done.wait(timeout=5)
            watcher_registry.run_registry_once(config_path)
            watcher_registry.run_registry_once(config_path)
        except BaseException as exc:  # pragma: no cover - asserted below
            watcher_errors.append(exc)

    def fail_before_ack(stage: str) -> None:
        nonlocal post_commit_fault, tripped, watcher_thread
        if stage == "acknowledge" and not tripped:
            tripped = True
            raise RuntimeError("injected pre-commit fault")
        if stage == "acknowledge" and watcher_thread is None:
            watcher_thread = threading.Thread(target=reconcile_retry)
            watcher_thread.start()
        if stage == "commit" and not post_commit_fault:
            post_commit_fault = True
            raise RuntimeError("injected post-commit fault")

    monkeypatch.setattr("app.instance.settings_rebind._activation_fault_point", fail_before_ack)
    with pytest.raises(RuntimeError, match="pre-commit fault"):
        activation.activate(
            selection=_known_ref(runtime, "binding-b"),
            candidate_binding_id="binding-b",
            candidate_root=vault_b,
        )
    cancelled = runtime.open_settings_rebind_store().read()
    assert cancelled.phase == "cancelled"
    assert cancelled.candidate_binding_id == "binding-a"
    assert runtime.registry.load().last_active_vault_ref is None

    with pytest.raises(RuntimeError, match="injected post-commit fault"):
        activation.activate(
            selection=KnownVaultRef(
                ref=registration.ref,
                path=registration.path,
                vault_id=registration.vault_id,
                local_instance_id=registration.local_instance_id,
                vault_name=registration.vault_name,
                last_opened_at=registration.last_opened_at,
            ),
            candidate_binding_id="binding-b",
            candidate_root=vault_b,
        )
    assert watcher_thread is not None
    watcher_thread.join(timeout=5)
    assert not watcher_thread.is_alive()
    assert not watcher_errors
    committed = runtime.open_settings_rebind_store().read()
    assert committed.phase == "committed"
    assert committed.candidate_binding_id == "binding-b"
    assert committed.reload_revision != committed.desired_revision

    activation.activate(
        selection=KnownVaultRef(
            ref=registration.ref,
            path=registration.path,
            vault_id=registration.vault_id,
            local_instance_id=registration.local_instance_id,
            vault_name=registration.vault_name,
            last_opened_at=registration.last_opened_at,
        ),
        candidate_binding_id="binding-b",
        candidate_root=vault_b,
    )
    recovered = runtime.open_settings_rebind_store().read()
    assert recovered.phase == "committed"
    assert recovered.candidate_binding_id == "binding-b"
    assert recovered.reload_revision == recovered.desired_revision


def test_session_selection_reuses_bindings_with_per_request_server_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One bearer drives a read and, later, a separately authorized governed write.

    The selection stores bindings and server-derived cognitive context only. Action, write
    class, and permission are derived from each endpoint's own contract per call; the
    bearer gains nothing from a successful read, and a denied operation stays denied.
    """

    import app.instance.active_context_service as service_module
    from app.api.compatibility_mutation import HEADER_COMPATIBILITY_PRECONDITION
    from app.instance.active_context_service import (
        ACTION_SELECTION_INSPECT,
        PERMISSION_SELECTION_READ,
        WRITE_CLASS_READ,
    )
    from app.instance.context_selection import ContextSelectionRecord
    from tests._mvr03_principal_harness import provisioned_instance
    from tests.helpers.vault_settings import initialize_test_vault

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    binding_a = first.vault_binding_id
    binding_b = extra[0].vault_binding_id
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    root_a = Path(runtime.registry.load().registrations[binding_a].path)
    initialize_test_vault(root_a)
    (root_a / "shared.md").write_text("before\n", encoding="utf-8")
    _install_dormant_settings_rebind_for_test(runtime, binding_a)
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    manager.select_vault(root_a)
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app)

    seen: list[object] = []
    live_authorize = service_module._LiveRegistryAuthorizer.authorize

    def recording_authorize(self, request):  # type: ignore[no-untyped-def]
        seen.append(request)
        return live_authorize(self, request)

    monkeypatch.setattr(service_module._LiveRegistryAuthorizer, "authorize", recording_authorize)

    created = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [binding_a]},
    )
    assert created.status_code == 201, created.text
    bearer = created.json()["context_selection_id"]
    stored_context = created.json()["context"]
    # The selection is not an authority record: it has no field that could carry one.
    authority_fields = {"action", "write_class", "required_permission", "permission"}
    assert not authority_fields & set(ContextSelectionRecord.__dataclass_fields__)
    assert not authority_fields & set(stored_context)

    # -- 1. an authorized production read, with the read contract's own GOV inputs ----
    read = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": bearer},
    )
    assert read.status_code == 200, read.text
    assert {note["vault_binding_id"] for note in read.json()["notes"]} == {binding_a}
    assert [(item.vault_binding_id, item.action, item.write_class, item.required_permission) for item in seen] == [
        (binding_a, ACTION_SELECTION_INSPECT, WRITE_CLASS_READ, PERMISSION_SELECTION_READ)
    ]
    precondition = read.headers[HEADER_COMPATIBILITY_PRECONDITION]

    # -- 2. a denied operation: the bearer cannot itself carry a write before MVR-05C ----
    seen.clear()
    for path, headers in (
        ("/api/companion/note/save", {"X-Active-Context-Session": bearer}),
        (
            "/api/companion/note/save/compatibility",
            {
                "X-Active-Context-Session": bearer,
                HEADER_COMPATIBILITY_PRECONDITION: precondition,
            },
        ),
    ):
        denied = client.post(
            path,
            headers=headers,
            json={"note_path": "shared.md", "new_body": "must not write\n"},
        )
        assert denied.status_code == 409, (path, denied.text)
        assert denied.json()["detail"]["error"] == "capability_not_ready"
    assert (root_a / "shared.md").read_text(encoding="utf-8") == "before\n"
    # The refusal happened before any binding authorization: nothing was widened to try.
    assert seen == []

    # -- 3. later, an independently authorized governed write on the same binding ------
    written = client.post(
        "/api/companion/note/save/compatibility",
        headers={HEADER_COMPATIBILITY_PRECONDITION: precondition},
        json={"note_path": "shared.md", "new_body": "after\n"},
    )
    assert written.status_code == 200, written.text
    assert written.json()["status"] == "ok"
    assert (root_a / "shared.md").read_text(encoding="utf-8").strip().endswith("after")
    # The write authorized itself against the principal and the durable compatibility
    # binding; it consulted no selection-held authority and resolved no scoped context.
    assert seen == []

    # -- 4. the bearer is exactly what it was: same bindings, same cognitive context --
    reread = client.get(
        "/api/companion/active-context/selection",
        headers={"X-Active-Context-Session": bearer},
    )
    assert reread.status_code == 200, reread.text
    assert reread.json()["context"] == stored_context
    assert reread.json()["context"]["vault_binding_ids"] == [binding_a]
    assert binding_b not in reread.json()["context"]["vault_binding_ids"]
    for field in ("scope", "sphere_memberships", "situated_identity", "workspace", "generation"):
        assert reread.json()["context"][field] == stored_context[field]

    # The denied operation stays denied after the successful write, too.
    still_denied = client.post(
        "/api/companion/note/save",
        headers={"X-Active-Context-Session": bearer},
        json={"note_path": "shared.md", "new_body": "still must not write\n"},
    )
    assert still_denied.status_code == 409
    assert (root_a / "shared.md").read_text(encoding="utf-8").strip().endswith("after")

    # And the same bearer still drives the read, with fresh per-call read inputs.
    seen.clear()
    again = client.get(
        "/api/companion/vault/notes/scoped",
        headers={"X-Active-Context-Session": bearer},
    )
    assert again.status_code == 200, again.text
    assert again.json()["context_generation"] == read.json()["context_generation"]
    assert [(item.action, item.write_class, item.required_permission) for item in seen] == [
        (ACTION_SELECTION_INSPECT, WRITE_CLASS_READ, PERMISSION_SELECTION_READ)
    ]


@contextmanager
def _running_watcher(config_path: Path, *, long_lived: bool = False):
    """Run the production watcher reconciler as an independent, separately ticking loop.

    The picker never calls it: it only observes the durable receipts this loop publishes,
    exactly as it would observe a separately deployed watcher container. By default every
    tick reloads its configuration from the environment, so each tick is also a watcher
    *restart*: the loop converges only from durable state. ``long_lived`` instead keeps one
    in-memory configuration across ticks, like the deployed ``watcher run`` loop.
    """

    stop = threading.Event()
    errors: list[BaseException] = []
    loaded = watcher_registry.load_registry_config(config_path) if long_lived else None

    def loop() -> None:
        while not stop.is_set():
            try:
                if loaded is None:
                    watcher_registry.run_registry_once(config_path)
                else:
                    # The entrypoint decorator reloads config per call; keep the one
                    # in-memory config under the same single-writer lock instead.
                    with watcher_registry._registry_writer_lock(loaded.state_dir):
                        watcher_registry.run_registry_once.__wrapped__(
                            config_path, _loaded_config=loaded
                        )
            except BaseException as exc:  # pragma: no cover - asserted by caller
                errors.append(exc)
                return
            time.sleep(0.01)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        yield errors
    finally:
        stop.set()
        thread.join(timeout=10)
        assert not thread.is_alive()


def _heartbeat_root(tmp_path: Path) -> str:
    import json

    return str(
        json.loads((tmp_path / "watcher-heartbeat.json").read_text(encoding="utf-8"))[
            "vault_path"
        ]
    )


def _wait_until(predicate, *, timeout: float = 10.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_legacy_picker_bridge_preserves_single_watcher_until_mvr06(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy picker and default SET/CLEAR share one durable single-watcher handoff."""

    import json

    from app.instance._storage_boundary import CapabilityNotReadyError, RegistryError
    from app.instance.active_context_service import (
        ACTION_SELECTION_INSPECT,
        PERMISSION_SELECTION_READ,
        WRITE_CLASS_READ,
        binding_facts,
        build_authorizer,
    )
    from app.instance.context_selection import (
        ActiveContextSelectionResolver,
        ContextSelectionStore,
    )
    from app.instance.runtime import _require_runtime_floor
    from app.instance.settings_rebind import (
        MINIMUM_SETTINGS_REBIND_RUNTIME,
        MINIMUM_SETTINGS_REBIND_RUNTIME_KEY,
        SETTINGS_REBIND_SCHEMA,
    )
    from app.vault.active_context_v1 import PrincipalContext, WorkspaceState

    runtime, vault_a, vault_b, config_path = _fixture(
        tmp_path, monkeypatch, enabled=True, prepare=False
    )
    monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "10")
    reloads: list[Path] = []
    monkeypatch.setattr("app.settings.ingestion.ingest_settings", _record_reload(reloads))
    assert _heartbeat_root(tmp_path) == str(vault_a)

    # The in-process VaultChangedEvent is only a wake-up hint: suppress it entirely and
    # the separately ticking watcher must still converge from durable state alone.
    monkeypatch.setattr(VaultManager, "_emit_changed", lambda *_args, **_kwargs: None)
    hints: list[object] = []

    def record_hint(receipt: object) -> None:
        # The default-mutation event is published only after the durable handoff has
        # committed and the watcher has completed it.
        record = runtime.open_settings_rebind_store().read()
        assert record.phase == "committed"
        assert record.reload_revision == record.desired_revision
        hints.append(receipt)

    defaults = InstanceDefaultVaultService(
        runtime.registry,
        capability=STORAGE_MUTATION_CAPABILITY,
        emit_event=record_hint,
    )

    with _running_watcher(config_path) as watcher_errors:
        # -- 1. legacy choose/open picker: A -> B -----------------------------------
        selected = VaultManager().select_vault(vault_b)
        assert selected.active_vault_path == str(vault_b)
        picked = runtime.open_settings_rebind_store().read()
        assert (picked.phase, picked.prior_binding_id, picked.candidate_binding_id) == (
            "committed",
            "binding-a",
            "binding-b",
        )
        assert picked.desired_revision == picked.reload_revision == 1
        assert load_settings_rebind_watcher_receipt(_revision_receipt_path(tmp_path, 1)).stage == "completed"
        _wait_until(lambda: _heartbeat_root(tmp_path) == str(vault_b))

        # -- 2. MVR-02 default SET drives the same transaction: B -> A ---------------
        set_receipt = defaults.set("binding-a")
        after_set = runtime.registry.load()
        rebound = runtime.open_settings_rebind_store().read()
        assert set_receipt.vault_binding_id == after_set.default_vault_binding_id == "binding-a"
        assert (rebound.phase, rebound.prior_binding_id, rebound.candidate_binding_id) == (
            "committed",
            "binding-b",
            "binding-a",
        )
        assert rebound.desired_revision == rebound.reload_revision == 2
        assert load_settings_rebind_watcher_receipt(_revision_receipt_path(tmp_path, 2)).stage == "completed"
        _wait_until(lambda: _heartbeat_root(tmp_path) == str(vault_a))

        # -- 3. a default mutation that cannot hand off fails before changing it ------
        monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "0")
        with _paused_watcher(monkeypatch):
            with pytest.raises(RegistryError, match="did not reach acknowledged"):
                defaults.set("binding-b")
        monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "10")
        unchanged = runtime.registry.load()
        cancelled = runtime.open_settings_rebind_store().read()
        assert unchanged.default_vault_binding_id == "binding-a"
        assert (cancelled.phase, cancelled.candidate_binding_id) == ("cancelled", "binding-a")
        assert len(hints) == 1

        # -- 4. default CLEAR also hands the single watcher off ----------------------
        clear_receipt = defaults.clear()
        cleared = runtime.open_settings_rebind_store().read()
        assert clear_receipt.vault_binding_id is None
        assert runtime.registry.load().default_vault_binding_id is None
        assert cleared.candidate_binding_id is None
        assert cleared.reload_revision == cleared.desired_revision
        assert len(hints) == 2

    assert not watcher_errors
    # The deployed long-lived watcher entrypoint (startup reconciliation plus its in-memory
    # loop) treats the completed no-target handoff as stable idle state, not a crash.
    reloads_before_restart = len(reloads)
    watcher_registry.run_registry_forever(config_path, max_ticks=3)
    assert runtime.open_settings_rebind_store().read() == cleared
    # ...and its startup does not recompile the cleared vault's settings.
    assert reloads[reloads_before_restart:] == []
    # Default mutations never wrote picker history; only the picker did.
    assert runtime.registry.load().last_active_vault_ref == picked_ref(runtime, "binding-b")

    # -- 5. generic scoped session/request selection never touches the bridge --------
    before = runtime.registry.load()
    principal = PrincipalContext(
        principal_id="operator", principal_kind="delegated_operator_role", subject="trusted_loopback"
    )
    store = ContextSelectionStore()
    raw, _ = store.create(
        principal=principal,
        instance_identity=before.app_install_id,
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        binding_ids=("binding-a",),
    )
    store.replace_bindings(
        raw,
        principal=principal,
        instance_identity=before.app_install_id,
        binding_ids=("binding-b",),
    )
    resolver = ActiveContextSelectionResolver(
        binding_facts=lambda: binding_facts(runtime.registry.load()),
        registry_revision=lambda: runtime.registry.load().revision,
        authorizer=build_authorizer(runtime.registry.load()),
        instance_identity=before.app_install_id,
    )
    scoped = resolver.resolve(
        selection=store.inspect(raw, principal=principal, instance_identity=before.app_install_id),
        principal=principal,
        action=ACTION_SELECTION_INSPECT,
        write_class=WRITE_CLASS_READ,
        required_permission=PERMISSION_SELECTION_READ,
    ).snapshot
    assert scoped.binding_ids == ("binding-b",)
    after = runtime.registry.load()
    assert after.settings_rebind == before.settings_rebind
    assert after.default_vault_binding_id == before.default_vault_binding_id
    assert after.last_active_vault_ref == before.last_active_vault_ref
    assert after.revision == before.revision

    # -- 6. the bridge is one named, floor-guarded record that MVR-06 retires atomically --
    attestation = json.loads(
        (Path(__file__).resolve().parents[2] / "app/instance/settings_rebind_runtime_capability.json").read_text(
            encoding="utf-8"
        )
    )
    assert attestation["capability"] == "settings-rebind-runtime-floor"
    assert attestation["rollbackPosture"] == "reject-incompatible-writer"
    assert set(attestation["preserves"]) == {
        SETTINGS_REBIND_SCHEMA,
        f"{MINIMUM_SETTINGS_REBIND_RUNTIME_KEY}={MINIMUM_SETTINGS_REBIND_RUNTIME}",
    }
    assert after.settings_rebind["schema"] == SETTINGS_REBIND_SCHEMA
    floors = after.extensions["runtimeFloors"]
    assert floors[MINIMUM_SETTINGS_REBIND_RUNTIME_KEY] == MINIMUM_SETTINGS_REBIND_RUNTIME
    # A legacy scalar writer cannot boot alongside the bridge, and neither can a runtime
    # built for a different bridge revision: there is never "both or neither".
    with pytest.raises(CapabilityNotReadyError, match="legacy scalar writer"):
        _require_runtime_floor(after, scalar_runtime=True)
    incompatible = replace_extensions(
        after,
        runtimeFloors={**floors, MINIMUM_SETTINGS_REBIND_RUNTIME_KEY: "2"},
    )
    with pytest.raises(CapabilityNotReadyError, match="settings rebind runtime floor"):
        _require_runtime_floor(incompatible, scalar_runtime=False)
    _require_runtime_floor(after, scalar_runtime=False)
    # Only the sealed storage capability can write it, and never backwards.
    with pytest.raises(CapabilityNotReadyError):
        runtime.registry.set_settings_rebind_state(after.settings_rebind)
    regressed = SettingsRebindRecord.dormant(binding_id="binding-a").as_payload()
    with pytest.raises(RegistryError, match="monotonic"):
        runtime.registry.set_settings_rebind_state(
            regressed, _capability=STORAGE_MUTATION_CAPABILITY
        )
    # The foreground SETTINGS-01 reload ran for each new compatibility root.
    assert {vault_a, vault_b} <= set(reloads)

    # -- 7. after a completed CLEAR, a long-lived watcher re-arms only for its own root --
    # Activation and reconciliation must agree: the configured watcher acknowledges the
    # next first selection of its own root instead of silently answering no_lifecycle,
    # and refuses (staying idle, scanning nothing) a selection of any other root.
    with _running_watcher(config_path, long_lived=True) as long_lived_errors:
        before_refusal = runtime.open_settings_rebind_store().read()
        events_before = len(_event_paths(tmp_path))
        (vault_a / "cleared-root-edit.md").write_text("must not be scanned\n", encoding="utf-8")
        monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "0.5")
        with pytest.raises(RegistryError, match="did not reach acknowledged"):
            VaultManager().select_vault(vault_b)
        monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "10")
        refused = runtime.open_settings_rebind_store().read()
        assert refused.phase == "cancelled"
        assert refused.candidate_binding_id is None
        assert refused.desired_revision == before_refusal.desired_revision + 1
        assert not _revision_receipt_path(tmp_path, refused.desired_revision).exists()
        assert _event_paths(tmp_path)[events_before:] == []

        reselected = VaultManager().select_vault(vault_a)
        assert reselected.active_vault_path == str(vault_a)
        readopted = runtime.open_settings_rebind_store().read()
        assert (readopted.phase, readopted.prior_binding_id, readopted.candidate_binding_id) == (
            "committed",
            None,
            "binding-a",
        )
        assert readopted.reload_revision == readopted.desired_revision
        assert (
            load_settings_rebind_watcher_receipt(
                _revision_receipt_path(tmp_path, readopted.desired_revision)
            ).stage
            == "completed"
        )
        _wait_until(lambda: _heartbeat_root(tmp_path) == str(vault_a))
    assert not long_lived_errors


def picked_ref(runtime, binding_id: str) -> str:  # type: ignore[no-untyped-def]
    return runtime.registry.load().registrations[binding_id].ref


def replace_extensions(snapshot, **extensions):  # type: ignore[no-untyped-def]
    from dataclasses import replace as dataclass_replace

    return dataclass_replace(snapshot, extensions={**snapshot.extensions, **extensions})


@contextmanager
def _paused_watcher(monkeypatch: pytest.MonkeyPatch):
    """Make the separately running watcher publish nothing, as if it were stalled."""

    with monkeypatch.context() as patch:
        patch.setattr(watcher_registry, "run_registry_once", lambda *_a, **_kw: None)
        yield


def test_prepare_drains_old_binding_writes_before_quiescent_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admitted A mutations drain before prepare; the watcher acks a quiescent A scan."""

    from app.instance._storage_boundary import RegistryError
    from app.instance.settings_rebind import compatibility_ingress_window

    runtime, vault_a, vault_b, config_path = _fixture(
        tmp_path, monkeypatch, enabled=True, prepare=False
    )
    monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "10")
    monkeypatch.setattr("app.settings.ingestion.ingest_settings", _record_reload([]))
    store = runtime.open_settings_rebind_store()
    activation = SettingsRebindActivation.from_environment(runtime.registry)

    # A carrier-free compatibility mutation has been admitted on A and is mid-effect: it
    # holds the production ingress window exactly as `require_compatibility_mutation` does.
    admitted = threading.Event()
    finish_admitted = threading.Event()
    mutation_errors: list[BaseException] = []

    def admitted_a_mutation() -> None:
        try:
            with compatibility_ingress_window(runtime.registry):
                assert store.compatibility_binding_id() == "binding-a"
                admitted.set()
                assert finish_admitted.wait(timeout=10)
                (vault_a / "admitted-before-prepare.md").write_text("A\n", encoding="utf-8")
        except BaseException as exc:  # pragma: no cover - asserted below
            mutation_errors.append(exc)

    mutation = threading.Thread(target=admitted_a_mutation)
    mutation.start()
    assert admitted.wait(timeout=5)

    commit_reached = threading.Event()
    release_commit = threading.Event()
    original_commit = activation.store.commit_selection

    def hold_commit(**kwargs: object) -> SettingsRebindRecord:
        commit_reached.set()
        assert release_commit.wait(timeout=10)
        return original_commit(**kwargs)

    monkeypatch.setattr(activation.store, "commit_selection", hold_commit)
    results: list[SettingsRebindRecord] = []
    picker_errors: list[BaseException] = []

    def pick_b() -> None:
        try:
            results.append(
                activation.activate(
                    selection=_known_ref(runtime, "binding-b"),
                    candidate_binding_id="binding-b",
                    candidate_root=vault_b,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            picker_errors.append(exc)

    with _running_watcher(config_path) as watcher_errors:
        picker = threading.Thread(target=pick_b)
        picker.start()
        # Prepare is gated behind the admitted A mutation: no revision is published.
        time.sleep(0.2)
        gated = store.read()
        assert (gated.phase, gated.candidate_binding_id, gated.desired_revision) == (
            "dormant",
            "binding-a",
            0,
        )

        finish_admitted.set()
        mutation.join(timeout=5)
        assert not mutation.is_alive()
        assert not mutation_errors

        # The watcher acknowledges the prepared revision only from a complete A scan
        # that already contains the drained write; B has produced nothing.
        (vault_b / "candidate-before-commit.md").write_text("B\n", encoding="utf-8")
        assert commit_reached.wait(timeout=10)
        prepared = store.read()
        assert (prepared.phase, prepared.prior_binding_id, prepared.candidate_binding_id) == (
            "prepared",
            "binding-a",
            "binding-b",
        )
        ack = load_settings_rebind_watcher_receipt(_revision_receipt_path(tmp_path, 1))
        assert ack.stage == "acknowledged"
        assert ack.acknowledgement is not None
        assert ack.acknowledgement.scan_kind == "pre_commit"
        # The drained write settled under A before the acknowledgement: either an ordinary
        # A effect before prepare, or buffered by the pre-commit A scan.
        admitted_write = vault_a / "admitted-before-prepare.md"
        assert str(admitted_write) in _event_paths(tmp_path) or any(
            item.relative_path == admitted_write.name for item in ack.buffer
        )
        assert not any(path.startswith(str(vault_b)) for path in _event_paths(tmp_path))
        assert _heartbeat_root(tmp_path) == str(vault_a)

        # New carrier-free compatibility ingress is closed while the revision is prepared.
        with pytest.raises(RegistryError, match="awaiting commit"):
            store.compatibility_binding_id()

        # Old-root observation continues past the acknowledgement up to the commit.
        (vault_a / "after-ack-before-commit.md").write_text("A\n", encoding="utf-8")
        time.sleep(0.1)
        assert store.read().phase == "prepared"
        release_commit.set()
        picker.join(timeout=20)
        assert not picker.is_alive()

    assert not watcher_errors
    assert not picker_errors
    assert len(results) == 1
    final = store.read()
    assert (final.phase, final.candidate_binding_id) == ("committed", "binding-b")
    assert final.reload_revision == final.desired_revision == 1
    completed = load_settings_rebind_watcher_receipt(_revision_receipt_path(tmp_path, 1))
    assert completed.stage == "completed"
    buffered = {item.relative_path for item in completed.buffer}
    # A write after the acknowledgement but before commit stays an A observation.
    assert "after-ack-before-commit.md" in buffered
    assert "candidate-before-commit.md" not in buffered
    assert store.compatibility_binding_id() == "binding-b"


def test_picker_commit_succeeds_with_durable_no_lifecycle_watcher_posture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An intentionally disabled or absent watcher is a durable no_lifecycle commit."""

    from app.instance.vault_registry import VaultRegistryStore

    runtime, vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    reloads: list[Path] = []
    monkeypatch.setattr("app.settings.ingestion.ingest_settings", _record_reload(reloads))
    # No watcher process exists and none will ever acknowledge: any wait would fail now.
    monkeypatch.setenv("SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS", "0")
    waits: list[str] = []
    original_wait = SettingsRebindActivation._wait_for_stage

    def record_wait(self, record, *, required_stage):  # type: ignore[no-untyped-def]
        waits.append(required_stage)
        return original_wait(self, record, required_stage=required_stage)

    monkeypatch.setattr(SettingsRebindActivation, "_wait_for_stage", record_wait)
    receipts = tmp_path / "watcher-state"
    before_receipts = set(receipts.glob("settings-rebind-watcher-r*.json")) if receipts.exists() else set()

    # Intentionally disabled watcher (WATCHER_ENABLE=0): the legacy picker commits B.
    selected = VaultManager().select_vault(vault_b)
    assert selected.active_vault_path == str(vault_b)
    disabled = VaultRegistryStore(runtime.registry.path).load()
    record = SettingsRebindRecord.from_payload(disabled.settings_rebind)
    assert (record.phase, record.lifecycle_posture) == ("no_lifecycle", "no_lifecycle")
    assert record.candidate_binding_id == "binding-b"
    assert record.desired_revision == record.applied_revision == record.reload_revision == 1

    # Absent watcher (requested, but no watcher root configured): the candidate's watcher
    # policy is still validated, then the same durable no_lifecycle commit applies.
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.delenv("WATCHER_VAULT_PATH")
    back = VaultManager().select_vault(vault_a)
    assert back.active_vault_path == str(vault_a)
    absent = runtime.open_settings_rebind_store().read()
    assert (absent.phase, absent.lifecycle_posture) == ("no_lifecycle", "no_lifecycle")
    assert (absent.prior_binding_id, absent.candidate_binding_id) == ("binding-b", "binding-a")
    assert absent.desired_revision == absent.applied_revision == absent.reload_revision == 2

    # No process acknowledgement was awaited or produced, and the durable outcome is stable
    # across a fresh reader and an idempotent no-watcher reconcile.
    assert waits == []
    after_receipts = set(receipts.glob("settings-rebind-watcher-r*.json")) if receipts.exists() else set()
    assert after_receipts == before_receipts
    assert runtime.open_settings_rebind_store().reconcile_no_lifecycle() == absent
    assert reloads == [vault_b, vault_a]
    assert runtime.open_settings_rebind_store().compatibility_binding_id() == "binding-a"


def _install_dormant_settings_rebind_for_test(runtime, binding_id: str) -> None:
    from app.instance.settings_rebind import _install_dormant_settings_rebind

    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id=binding_id,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )


def test_compatibility_bridge_enables_legacy_without_scoped_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped one-binding picker still selects a vault through the bridge."""

    runtime, _vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    selected = VaultManager().select_vault(vault_b)
    record = runtime.open_settings_rebind_store().read()
    assert selected.status == "selected"
    assert selected.active_vault_path == str(vault_b)
    assert record.candidate_binding_id == "binding-b"
    assert record.phase == "no_lifecycle"


def test_first_vault_initialize_bootstrap_is_single_use_and_failure_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-effect fault leaves no registry/default/compatibility or owner lease."""

    runtime, _principal = fresh_no_vault_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", "prod")
    manager = VaultManager(
        app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md")
    )
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app, raise_server_exceptions=False)
    target = tmp_path / "atomic-failure"
    issued = client.post(
        "/api/companion/vault/initialize/bootstrap",
        json={"path": str(target), "confirm": True},
    )
    assert issued.status_code == 200, issued.text

    def fail_before_effect(*_args, **_kwargs):
        raise RuntimeError("injected pre-effect failure")

    monkeypatch.setattr(manager, "initialize_vault", fail_before_effect)
    failed = client.post(
        "/api/companion/vault/initialize",
        json={
            "path": str(target),
            "confirm": True,
            "bootstrap_token": issued.json()["bootstrap_token"],
        },
    )
    assert failed.status_code == 500
    snapshot = runtime.registry.load()
    assert snapshot.registrations == {}
    assert snapshot.default_vault_binding_id is None
    assert snapshot.settings_rebind is None
    assert runtime.ledger.load().leases == {}
    assert not target.exists()
    assert FirstVaultPreconditionStore(runtime.registry.path).load().state == "failed"


def test_fresh_vault_initialize_returns_usable_scoped_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first production read uses the returned scoped selection, not last-active."""

    runtime, _principal = fresh_no_vault_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", "prod")
    manager = VaultManager(
        app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md")
    )
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app)
    target = tmp_path / "fresh-scoped"
    bootstrap = client.post(
        "/api/companion/vault/initialize/bootstrap",
        json={"path": str(target), "confirm": True},
    )
    assert bootstrap.status_code == 200, bootstrap.text
    initialized = client.post(
        "/api/companion/vault/initialize",
        json={
            "path": str(target),
            "confirm": True,
            "bootstrap_token": bootstrap.json()["bootstrap_token"],
        },
    )
    assert initialized.status_code == 200, initialized.text
    selection_id = initialized.json()["context_selection_id"]
    assert selection_id
    binding_id = runtime.registry.load().default_vault_binding_id
    scoped = client.get(
        "/api/companion/active-context/selection",
        headers={"X-Active-Context-Session": selection_id},
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["context"]["vault_binding_ids"] == [binding_id]
    assert scoped.json()["context"]["principal_id"]
    runtime.ledger.require_scalar_rollback_ready(
        channel_id=runtime.layout.channel_id,
        registrations={binding_id: target},
    )
    # The scoped selection is the immediate read authority; the registry's
    # interaction-history field is deliberately not consulted or materialized.
    assert runtime.registry.load().last_active_vault_ref is None
