"""#2992 — the watcher CLI must not crash-loop when `enable` is flipped off by
the #2005 vault-idle contract; it must idle (stay up) instead, and error
messages must name the actual cause.

Before this fix, `app/cli/watcher.py` treated any `cfg.enable is False` as
"WATCHER_ENABLE=1 is not set" and raised `click.ClickException`. But `enable`
is also force-flipped to False by the registry/config vault validators when
the bound vault is absent or uninitialized (`_IDLE_VAULT_STATUSES`, #2005).
That collapsed two distinct causes into one exit path and one misleading
message, crash-looping any container whose vault mount is not yet
initialized (e.g. `pkm-test-watcher-1` against an empty Bifrost mount).

Two legs:
  * WATCHER_ENABLE genuinely falsy (unset/0)  -> exit, message names WATCHER_ENABLE.
  * WATCHER_ENABLE=1 but vault idle/uninit    -> idle (no exit), message names vault status.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from app.cli.watcher import watcher_group

pytestmark = pytest.mark.not_pg


def _write_registry_config(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "watchers": [
                    {
                        "name": "ingest",
                        "scope_glob": "",
                        "debounce_ms": 1000,
                        "rate_limit_per_min": 60,
                        "emit_event": "ingest.vault.changed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    return {
        "PKM_SETTINGS_PROFILE": "lab",
        "STORE_BACKEND": "memory",
        "WATCHER_STATE_DIR": str(tmp_path / "state"),
        "WATCHER_HEARTBEAT_PATH": str(tmp_path / "watcher_heartbeat.json"),
        "WATCHER_STOP_FILE": str(tmp_path / "watcher.stop"),
        "WATCHER_RUN_LOG_PATH": str(tmp_path / "watcher_run.jsonl"),
        "INDEX_OUTBOX_PATH": str(tmp_path / "index-outbox.jsonl"),
        "WATCHER_TICK_SLEEP_SECONDS": "0",
    }


def test_uninitialized_vault_idles_not_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#2005 idle contract at the CLI layer: an uninitialized bound vault with
    WATCHER_ENABLE=1 must idle the `watcher run` process (exit code 0, at least
    one tick executed, no ClickException) instead of crash-exiting."""
    vault = tmp_path / "uninitialized-vault"
    vault.mkdir()
    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)

    for key, value in _base_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))

    runner = CliRunner()
    result = runner.invoke(
        watcher_group,
        ["run", "--config", str(config_path), "--max-ticks", "1"],
    )

    assert result.exit_code == 0, result.output
    assert "idle" in result.output.lower()
    assert "uninitialized" in result.output.lower()


def test_error_messages_name_actual_cause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WATCHER_ENABLE=0 -> exit, message names the env var. Vault-idle case ->
    no exit, message names the vault status, not the env var."""
    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)

    # Leg 1: WATCHER_ENABLE genuinely disabled -> exit, message names env var.
    for key, value in _base_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WATCHER_ENABLE", "0")
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        watcher_group,
        ["run", "--config", str(config_path), "--max-ticks", "1"],
    )
    assert result.exit_code != 0
    assert "WATCHER_ENABLE" in str(result.output) or "WATCHER_ENABLE" in str(result.exception)

    # Leg 2: vault idle -> not an exit, message names vault status not env var.
    vault = tmp_path / "uninitialized-vault-2"
    vault.mkdir()
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))

    result2 = runner.invoke(
        watcher_group,
        ["run", "--config", str(config_path), "--max-ticks", "1"],
    )
    assert result2.exit_code == 0, result2.output
    assert "uninitialized" in result2.output.lower()
    assert "WATCHER_ENABLE=1 required" not in result2.output
