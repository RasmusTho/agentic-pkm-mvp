from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.instance._storage_boundary import RegistryError
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.settings_rebind import (
    SettingsRebindRecord,
    _install_dormant_settings_rebind,
)
from app.instance.vault_registry import VaultRegistration
from app.watcher import registry
from app.watcher.settings_rebind import (
    _write_receipt,
    SettingsRebindWatcherReceipt,
    load_settings_rebind_watcher_receipt,
    settings_rebind_watcher_receipt_path,
)
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _runtime(root: Path) -> InstanceRegistryRuntime:
    return InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(root / "instance-state", "test"),
        root / "ownership",
    )


def _register(
    runtime: InstanceRegistryRuntime,
    *,
    binding_id: str,
    vault_root: Path,
) -> None:
    runtime.registry.register(
        VaultRegistration(
            vault_binding_id=binding_id,
            ref=f"path:{vault_root}",
            path=str(vault_root),
        ),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )


def _prepare(
    runtime: InstanceRegistryRuntime,
    *,
    desired_revision: int = 1,
    applied_revision: int = 0,
    prior_binding_id: str | None = "binding-a",
    candidate_binding_id: str | None = "binding-b",
) -> SettingsRebindRecord:
    prepared = SettingsRebindRecord(
        desired_revision=desired_revision,
        applied_revision=applied_revision,
        phase="prepared",
        lifecycle_posture="watcher",
        prior_binding_id=prior_binding_id,
        candidate_binding_id=candidate_binding_id,
    )
    runtime.registry.set_settings_rebind_state(
        prepared.as_payload(),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return prepared


def _commit(
    runtime: InstanceRegistryRuntime,
    *,
    desired_revision: int = 1,
    prior_binding_id: str | None = "binding-a",
    candidate_binding_id: str | None = "binding-b",
) -> SettingsRebindRecord:
    committed = SettingsRebindRecord(
        desired_revision=desired_revision,
        applied_revision=desired_revision,
        phase="committed",
        lifecycle_posture="watcher",
        prior_binding_id=prior_binding_id,
        candidate_binding_id=candidate_binding_id,
    )
    runtime.registry.set_settings_rebind_state(
        committed.as_payload(),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return committed


def _write_registry_config(path: Path) -> None:
    path.write_text(
        "watchers:\n"
        "  - name: ingest\n"
        "    scope_glob: '*.md,**/*.md'\n"
        "    debounce_ms: 0\n"
        "    rate_limit_per_min: 1000\n"
        "    backoff_seconds: 0\n"
        "    emit_event: ingest.vault.changed\n",
        encoding="utf-8",
    )


def _configure_watcher(
    monkeypatch: pytest.MonkeyPatch,
    *,
    root: Path,
    runtime: InstanceRegistryRuntime,
    vault_a: Path,
    enabled: bool = True,
) -> Path:
    config_path = root / "watchers.yaml"
    _write_registry_config(config_path)
    env = {
        "PKM_ENVIRONMENT": "test",
        "PKM_SETTINGS_PROFILE": "lab",
        "STORE_BACKEND": "memory",
        "WATCHER_ENABLE": "1" if enabled else "0",
        "WATCHER_VAULT_PATH": str(vault_a),
        "WATCHER_STATE_DIR": str(root / "watcher-state"),
        "WATCHER_HEARTBEAT_PATH": str(root / "watcher-heartbeat.json"),
        "WATCHER_STOP_FILE": str(root / "watcher.stop"),
        "WATCHER_TICK_LOG_PATH": str(root / "watcher-ticks.jsonl"),
        "WATCHER_RUN_LOG_PATH": str(root / "watcher-runs.jsonl"),
        "WATCHER_TICK_SLEEP_SECONDS": "0",
        "WATCHER_SUMMARY_INTERVAL": "0",
        "INDEX_OUTBOX_PATH": str(root / "index-outbox.jsonl"),
        "INSTANCE_VAULT_REGISTRY_PATH": str(runtime.registry.path),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return config_path


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
) -> tuple[InstanceRegistryRuntime, Path, Path, Path]:
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    initialize_test_vault(vault_a)
    initialize_test_vault(vault_b)
    runtime = _runtime(tmp_path)
    _register(runtime, binding_id="binding-a", vault_root=vault_a)
    _register(runtime, binding_id="binding-b", vault_root=vault_b)
    _install_dormant_settings_rebind(
        runtime.registry,
        binding_id="binding-a",
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    config_path = _configure_watcher(
        monkeypatch,
        root=tmp_path,
        runtime=runtime,
        vault_a=vault_a,
        enabled=enabled,
    )
    # Capture the ordinary A watcher state before an external producer prepares
    # the dormant revision. The reconciliation tick must finish from this
    # already-running production cursor rather than treating startup as a
    # candidate-root activation.
    registry.run_registry_once(config_path)
    outbox_path = tmp_path / "index-outbox.jsonl"
    if outbox_path.exists():
        outbox_path.unlink()
    _prepare(runtime)
    return runtime, vault_a, vault_b, config_path


def _outbox_payloads(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _event_paths(root: Path) -> list[str]:
    return [
        str((item.get("payload") or {}).get("vault_path") or "")
        for item in _outbox_payloads(root / "index-outbox.jsonl")
    ]


def _revision_receipt_path(root: Path, revision: int) -> Path:
    return settings_rebind_watcher_receipt_path(root / "watcher-state", revision)


def test_production_watcher_reconciler_quiesces_old_binding_without_picker_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, vault_a, vault_b, config_path = _fixture(tmp_path, monkeypatch)
    old_note = vault_a / "old-root.md"
    old_note.write_text("old-root observation\n", encoding="utf-8")
    candidate_note = vault_b / "candidate-root.md"
    candidate_note.write_text("candidate must stay unseen\n", encoding="utf-8")

    process_env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    existing_pythonpath = process_env.get("PYTHONPATH")
    process_env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(repo_root), existing_pythonpath)
        if part
    )
    process_env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "watcher",
            "run",
            "--config",
            str(config_path),
            "--max-ticks",
            "1",
        ],
        cwd=repo_root,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr

    receipt = load_settings_rebind_watcher_receipt(
        _revision_receipt_path(tmp_path, 1)
    )
    assert receipt.stage == "acknowledged"
    assert receipt.desired_revision == 1
    assert receipt.prior_binding_id == "binding-a"
    assert receipt.candidate_binding_id == "binding-b"
    assert receipt.acknowledgement is not None
    assert receipt.acknowledgement.scan_kind == "pre_commit"
    assert any(item.relative_path == "old-root.md" for item in receipt.buffer)
    assert runtime.open_settings_rebind_store().read().phase == "prepared"

    event_paths = _event_paths(tmp_path)
    assert str(old_note) in event_paths
    assert str(candidate_note) not in event_paths
    assert all(path.startswith(str(vault_a)) for path in event_paths)


@pytest.mark.parametrize("fault_stage", ["acknowledge", "commit", "drain", "resume"])
def test_dormant_reconciler_failure_matrix_preserves_old_root_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_stage: str,
) -> None:
    runtime, vault_a, vault_b, config_path = _fixture(tmp_path, monkeypatch)
    before = vault_a / "before-ack.md"
    between = vault_a / "between-ack-and-commit.md"
    candidate = vault_b / "candidate.md"
    before.write_text("before\n", encoding="utf-8")
    candidate.write_text("candidate\n", encoding="utf-8")

    tripped = False

    def fail_once(stage: str) -> None:
        nonlocal tripped
        if stage == fault_stage and not tripped:
            tripped = True
            raise RuntimeError(f"injected {stage} fault")

    monkeypatch.setattr("app.watcher.settings_rebind._rebind_fault_point", fail_once)

    if fault_stage == "acknowledge":
        with pytest.raises(RuntimeError, match="injected acknowledge fault"):
            registry.run_registry_forever(config_path, max_ticks=1)
    registry.run_registry_forever(config_path, max_ticks=1)
    acknowledged = load_settings_rebind_watcher_receipt(
        _revision_receipt_path(tmp_path, 1)
    )
    assert acknowledged.stage == "acknowledged"

    between.write_text("between\n", encoding="utf-8")
    _commit(runtime)
    if fault_stage != "acknowledge":
        with pytest.raises(RuntimeError, match=f"injected {fault_stage} fault"):
            registry.run_registry_forever(config_path, max_ticks=1)

    resumed = vault_a / "after-drain-before-resume.md"
    if fault_stage == "resume":
        resumed.write_text("resume scan\n", encoding="utf-8")

    registry.run_registry_forever(config_path, max_ticks=1)
    completed = load_settings_rebind_watcher_receipt(
        _revision_receipt_path(tmp_path, 1)
    )
    assert completed.stage == "completed"
    assert completed.drain_receipt is not None
    assert completed.drain_receipt.scan_kind == "post_commit"
    buffered = {item.relative_path for item in completed.buffer}
    assert {"before-ack.md", "between-ack-and-commit.md"}.issubset(buffered)
    if fault_stage == "resume":
        assert resumed.name in buffered

    event_paths = _event_paths(tmp_path)
    assert str(before) in event_paths
    assert str(between) in event_paths
    assert str(candidate) not in event_paths
    assert all(path.startswith(str(vault_a)) for path in event_paths)


@pytest.mark.parametrize("scan_blocker", ["kill_switch", "missing_scope"])
def test_prepare_ack_requires_complete_successful_old_root_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scan_blocker: str,
) -> None:
    runtime, _vault_a, _vault_b, config_path = _fixture(tmp_path, monkeypatch)
    if scan_blocker == "kill_switch":
        (tmp_path / "watcher.stop").touch()
    else:
        monkeypatch.setenv("WATCHER_SCOPE_GLOB", "missing-scope/**/*.md")

    with pytest.raises(RegistryError, match="settings rebind watcher scan"):
        registry.run_registry_once(config_path)

    assert runtime.open_settings_rebind_store().read().phase == "prepared"
    assert not _revision_receipt_path(tmp_path, 1).exists()


def test_reconciler_uses_revision_bound_receipts_for_monotonic_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _vault_a, vault_b, config_path = _fixture(tmp_path, monkeypatch)

    registry.run_registry_once(config_path)
    _commit(runtime)
    registry.run_registry_once(config_path)

    _prepare(runtime, desired_revision=2, applied_revision=1)
    registry.run_registry_once(config_path)

    revision_one = load_settings_rebind_watcher_receipt(
        _revision_receipt_path(tmp_path, 1)
    )
    revision_two = load_settings_rebind_watcher_receipt(
        _revision_receipt_path(tmp_path, 2)
    )
    assert revision_one.desired_revision == 1
    assert revision_one.stage == "completed"
    assert revision_two.desired_revision == 2
    assert revision_two.stage == "acknowledged"
    assert not any(path.startswith(str(vault_b)) for path in _event_paths(tmp_path))

    _write_receipt(
        _revision_receipt_path(tmp_path, 2),
        SettingsRebindWatcherReceipt(
            desired_revision=revision_two.desired_revision,
            prior_binding_id=revision_two.prior_binding_id,
            candidate_binding_id="binding-c",
            stage=revision_two.stage,
            buffer=revision_two.buffer,
            acknowledgement=revision_two.acknowledgement,
            drain_receipt=revision_two.drain_receipt,
            resume_ready_at=revision_two.resume_ready_at,
        ),
    )
    with pytest.raises(
        RegistryError,
        match="receipt does not match durable authority",
    ):
        registry.run_registry_once(config_path)


def test_dormant_no_lifecycle_reconciles_without_unsealing_picker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, vault_a, _vault_b, config_path = _fixture(
        tmp_path,
        monkeypatch,
        enabled=False,
    )

    registry.run_registry_once(config_path)

    no_lifecycle = runtime.open_settings_rebind_store().read()
    assert no_lifecycle.phase == "no_lifecycle"
    assert no_lifecycle.lifecycle_posture == "no_lifecycle"
    assert no_lifecycle.desired_revision == no_lifecycle.applied_revision == 1

    missing_root = tmp_path / "missing-record"
    missing_runtime = _runtime(missing_root)
    _register(missing_runtime, binding_id="binding-a", vault_root=vault_a)
    missing_config = _configure_watcher(
        monkeypatch,
        root=missing_root,
        runtime=missing_runtime,
        vault_a=vault_a,
        enabled=False,
    )
    with pytest.raises(RegistryError, match="settings rebind record is not installed"):
        registry.run_registry_once(missing_config)

    no_vault_root = tmp_path / "no-vault"
    no_vault_runtime = _runtime(no_vault_root)
    _register(no_vault_runtime, binding_id="binding-b", vault_root=_vault_b)
    _install_dormant_settings_rebind(
        no_vault_runtime.registry,
        binding_id=None,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    _prepare(
        no_vault_runtime,
        prior_binding_id=None,
        candidate_binding_id="binding-b",
    )
    no_vault_config = _configure_watcher(
        monkeypatch,
        root=no_vault_root,
        runtime=no_vault_runtime,
        vault_a=vault_a,
        enabled=True,
    )
    monkeypatch.delenv("WATCHER_VAULT_PATH")

    registry.run_registry_once(no_vault_config)

    no_vault = no_vault_runtime.open_settings_rebind_store().read()
    assert no_vault.phase == "no_lifecycle"
    assert no_vault.prior_binding_id is None
    assert no_vault.candidate_binding_id == "binding-b"

    picker_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (Path("app/api"), Path("app/vault"))
        for path in root.rglob("*.py")
    )
    assert "settings-rebind-initiate" not in picker_sources
    assert "set_settings_rebind_state(" not in picker_sources
