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


def handoff_through_cli(
    runtime, *, legacy_bootstrap_root: Path | None = None, other_runtimes=()
) -> dict:
    """The shipped handoff command inside a proved stopped window, then finish it."""

    legacy_path = runtime.layout.root / "missing-legacy.md"
    proof, inventory_path = deployment_authority(
        runtime, legacy_path, other_runtimes=other_runtimes
    )
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


def configure_watcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runtime, root: Path
) -> Path:
    """The production registry watcher env for one running compatibility root."""

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.briefing.compose import briefing_note_path
    from app.briefing.config import BRIEFING_TIMEZONE
    from app.vault.manager import VaultContext

    config_path = tmp_path / "watchers.yaml"
    config_path.write_text(
        "watchers:\n"
        "  - name: ingest\n"
        "    scope_glob: '*.md,**/*.md'\n"
        "    debounce_ms: 0\n"
        "    rate_limit_per_min: 1000\n"
        "    backoff_seconds: 0\n"
        "    emit_event: ingest.vault.changed\n",
        encoding="utf-8",
    )
    for registration in runtime.registry.load().registrations.values():
        # Keep the unrelated scheduled briefing hook out of the watcher fixture.
        context = VaultContext(status="selected", active_vault_path=registration.path)
        note = briefing_note_path(
            vault_context=context, for_date=datetime.now(ZoneInfo(BRIEFING_TIMEZONE)).date()
        )
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("fixture sentinel\n", encoding="utf-8")
    env = {
        "PKM_SETTINGS_PROFILE": "lab",
        "WATCHER_ENABLE": "1",
        "WATCHER_VAULT_PATH": str(root),
        "WATCHER_DEBOUNCE_MS": "0",
        "WATCHER_RATE_LIMIT_PER_MIN": "1000",
        "WATCHER_STATE_DIR": str(tmp_path / "watcher-state"),
        "WATCHER_HEARTBEAT_PATH": str(tmp_path / "watcher-heartbeat.json"),
        "WATCHER_STOP_FILE": str(tmp_path / "watcher.stop"),
        "WATCHER_TICK_LOG_PATH": str(tmp_path / "watcher-ticks.jsonl"),
        "WATCHER_RUN_LOG_PATH": str(tmp_path / "watcher-runs.jsonl"),
        "WATCHER_TICK_SLEEP_SECONDS": "0",
        "WATCHER_SUMMARY_INTERVAL": "0",
        "INDEX_OUTBOX_PATH": str(tmp_path / "index-outbox.jsonl"),
        "SETTINGS_REBIND_WAIT_TIMEOUT_SECONDS": "1",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return config_path


def drive_watcher_during_waits(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    *,
    after_acknowledged=None,
) -> None:
    """Run the separately running production watcher from inside each stage wait.

    ``after_acknowledged`` runs once the watcher has published its quiescent pre-commit
    acknowledgement, i.e. after the old-root final scan and before the commit.
    """

    from app.watcher import registry as watcher_registry

    original = SettingsRebindActivation._wait_for_stage

    def wait_for_stage(activation, record, *, required_stage):
        for _ in range(3):
            watcher_registry.run_registry_once(config_path)
        original(activation, record, required_stage=required_stage)
        if required_stage == "acknowledged" and after_acknowledged is not None:
            after_acknowledged(record)

    monkeypatch.setattr(SettingsRebindActivation, "_wait_for_stage", wait_for_stage)


def watcher_receipt(tmp_path: Path, revision: int):
    from app.watcher.settings_rebind import (
        load_settings_rebind_watcher_receipt,
        settings_rebind_watcher_receipt_path,
    )

    return load_settings_rebind_watcher_receipt(
        settings_rebind_watcher_receipt_path(tmp_path / "watcher-state", revision)
    )


def outbox_paths(tmp_path: Path) -> list[str]:
    import json

    path = tmp_path / "index-outbox.jsonl"
    if not path.exists():
        return []
    return [
        str((json.loads(line).get("payload") or {}).get("vault_path") or "")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def background_ids(runtime) -> tuple[str, ...]:
    state = durable_background_state(runtime.registry.load())
    assert state is not None
    return state.binding_ids


__all__ = [
    "configure_watcher",
    "drive_watcher_during_waits",
    "outbox_paths",
    "watcher_receipt",
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
