"""MVR-05B compatibility handoff behavior at the production seams."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.default_vault import InstanceDefaultVaultService
from app.instance.settings_rebind import (
    SettingsRebindActivation,
    SettingsRebindRecord,
)
from app.instance.vault_registry import KnownVaultRef
from app.vault.manager import VaultManager
from app.workers.outbox_binding_gate import worker_effect_window
from app.watcher import registry as watcher_registry
from app.watcher.settings_rebind import (
    load_settings_rebind_watcher_receipt,
)
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.integration.test_watcher_cross_process_rebind import (
    _commit,
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

    def admit_a() -> None:
        try:
            with worker_effect_window(
                _compatibility_message(worker_runtime.root), runtime=worker_runtime
            ):
                assert runtime.open_settings_rebind_store().read().candidate_binding_id == "binding-a"
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
    _commit(runtime)
    (vault_b / "must-not-be-seen.md").write_text("candidate\n", encoding="utf-8")

    watcher_registry.run_registry_forever(config_path, max_ticks=1)
    watcher_registry.run_registry_forever(config_path, max_ticks=1)

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

    runtime, _vault_a, vault_b, _config_path = _fixture(
        tmp_path, monkeypatch, enabled=False, prepare=False
    )
    monkeypatch.setattr(
        "app.settings.ingestion.ingest_settings",
        _record_reload([]),
    )
    registration = runtime.registry.load().registrations["binding-b"]
    activation = SettingsRebindActivation.from_environment(runtime.registry)
    tripped = False

    def fail_before_ack(stage: str) -> None:
        nonlocal tripped
        if stage == "acknowledge" and not tripped:
            tripped = True
            raise RuntimeError("injected pre-commit fault")

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

    monkeypatch.setattr("app.instance.settings_rebind._activation_fault_point", lambda _stage: None)
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
    assert recovered.phase == "no_lifecycle"
    assert recovered.candidate_binding_id == "binding-b"


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
