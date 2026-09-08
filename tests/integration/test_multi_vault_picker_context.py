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
    # The scoped selection is the immediate read authority; the registry's
    # interaction-history field is deliberately not consulted or materialized.
    assert runtime.registry.load().last_active_vault_ref is None
