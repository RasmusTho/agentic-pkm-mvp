"""Shared MVR-06B harness: production handoff, supervisor, and watcher drive.

Every state transition is produced by a shipped producer: the MVR-06A cutover CLI, the
``background-supervisor-handoff`` CLI inside a proved stopped window, the legacy picker
two-phase activation, the MVR-02 default service, the governed background-intent admin
service, and the production removal/reactivation coordinators. Nothing here writes the
registry, intent, journal, or ledger directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.instance.background_authority import BackgroundIntentAdminService
from app.instance.background_supervisor import (
    BackgroundLifecycleSupervisor,
    durable_background_state,
)
from app.instance.runtime import _finish_instance_state_deployment
from app.instance.settings_rebind import SettingsRebindActivation, SettingsRebindRecord
from app.instance.vault_registry import KnownVaultRef
from app.settings.ingestion import SettingsIngestionState
from tests._mvr06_background_harness import (
    cli,
    mvr05_instance,
    run_background_cutover_through_cli,
)
from tests._mvr_default_vault_harness import deployment_authority
from tests.helpers.vault_settings import initialize_test_vault


def bind_runtime_env(monkeypatch: pytest.MonkeyPatch, runtime, *, watcher: bool = False) -> None:
    """The production compose env a background process sees (no ambient vault root)."""

    for name in ("VAULT_ROOT", "VAULT_ROOT_PROD", "WATCHER_VAULT_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("WATCHER_ENABLE", "1" if watcher else "0")
    monkeypatch.setenv("STORE_BACKEND", "memory")


def stub_settings_reload(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record SETTINGS-01 reloads at the production call site."""

    reloads: list[Path] = []

    def ingest(**kwargs: object) -> SettingsIngestionState:
        reloads.append(Path(str(kwargs["vault_root"])))
        return SettingsIngestionState(state="ok", source="vault")

    monkeypatch.setattr("app.settings.ingestion.ingest_settings", ingest)
    return reloads


def handoff_through_cli(runtime, *, legacy_bootstrap_root: Path | None = None) -> dict:
    """The shipped handoff command inside a proved stopped window, then finish it."""

    legacy_path = runtime.layout.root / "missing-legacy.md"
    proof, inventory_path = deployment_authority(runtime, legacy_path)
    args = [
        "background-supervisor-handoff",
        "--channel",
        runtime.layout.channel_id,
        "--registry-path",
        str(runtime.layout.registry_path),
        "--host-global-root",
        str(runtime.ledger.root),
        "--quiescence-proof-path",
        str(runtime.ledger.root / "deployment-quiescence-proof.json"),
        "--consumer",
        "bootstrap-init",
    ]
    if legacy_bootstrap_root is not None:
        args += ["--legacy-bootstrap-root", str(legacy_bootstrap_root)]
    try:
        receipt = cli(*args)
    finally:
        _finish_instance_state_deployment(
            channel=runtime.layout.channel_id,
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=legacy_path,
            inventory_path=inventory_path,
            backup_root=runtime.layout.root / "handoff-backup",
            restore_root=None,
            quiescence_proof=proof,
        )
    return receipt


def mvr06a_instance(tmp_path: Path, *, extra_roots: tuple[str, ...] = ("two",), vaults: bool = True):
    """MVR-05 + #3163 bridge + MVR-06A cutover; the bridge is still authoritative."""

    runtime, first, extra, _principal = mvr05_instance(tmp_path, extra_roots=extra_roots)
    if vaults:
        for registration in (first, *extra):
            initialize_test_vault(Path(registration.path))
    receipt = run_background_cutover_through_cli(runtime)
    assert receipt["_exit_code"] == 0, receipt
    return runtime, first, extra


def mvr06b_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    extra_roots: tuple[str, ...] = ("two",),
    watcher: bool = False,
):
    """An instance carried through the MVR-06B handoff by the production CLI."""

    runtime, first, extra = mvr06a_instance(tmp_path, extra_roots=extra_roots)
    bind_runtime_env(monkeypatch, runtime, watcher=watcher)
    receipt = handoff_through_cli(runtime)
    assert receipt["_exit_code"] == 0, receipt
    return runtime, first, extra


def supervisor(runtime, consumer: str = "watcher") -> BackgroundLifecycleSupervisor:
    return BackgroundLifecycleSupervisor.for_runtime(
        registry_path=runtime.layout.registry_path,
        ownership_root=runtime.ledger.root,
        channel_id=runtime.layout.channel_id,
        consumer=consumer,
    )


def admin(runtime) -> BackgroundIntentAdminService:
    from app.instance.runtime import open_background_intent_admin_service

    return open_background_intent_admin_service(runtime.layout.registry_path)


def selection_for(runtime, binding_id: str) -> KnownVaultRef:
    registration = runtime.registry.load().registrations[binding_id]
    return KnownVaultRef(
        ref=registration.ref,
        path=registration.path,
        vault_id=registration.vault_id,
        vault_name=registration.vault_name,
        local_instance_id=registration.local_instance_id,
        last_opened_at="2026-11-01T00:00:00Z",
    )


def pick(runtime, binding_id: str, **activation_kwargs) -> SettingsRebindRecord:
    """The production legacy choose/open two-phase activation."""

    activation = (
        SettingsRebindActivation(runtime.registry, **activation_kwargs)
        if activation_kwargs
        else SettingsRebindActivation.from_environment(runtime.registry)
    )
    registration = runtime.registry.load().registrations[binding_id]
    return activation.activate(
        selection=selection_for(runtime, binding_id),
        candidate_binding_id=binding_id,
        candidate_root=Path(registration.path),
    )


def background_ids(runtime) -> tuple[str, ...]:
    state = durable_background_state(runtime.registry.load())
    assert state is not None
    return state.binding_ids


__all__ = [
    "admin",
    "background_ids",
    "bind_runtime_env",
    "handoff_through_cli",
    "mvr06a_instance",
    "mvr06b_instance",
    "pick",
    "selection_for",
    "stub_settings_reload",
    "supervisor",
]
