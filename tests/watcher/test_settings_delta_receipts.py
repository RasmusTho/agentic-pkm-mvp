from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
import yaml

import app.watcher.registry as registry
import app.watcher.settings_delta as settings_delta_module
import app.watcher.watcher as legacy_watcher
from app.vault.manager import VaultManager
from app.vault.markdown_settings import MarkdownSettingsStore
from app.vault.settings_service import RUNTIME_GATING_SETTINGS, SettingsService
from app.receipts.settings_receipts import query_settings_receipts
from app.watcher.config import WatcherConfig
from app.watcher.settings_delta import (
    SETTINGS_LOCAL_REL,
    SETTINGS_YOUTUBE_REL,
    handle_settings_detected_delta,
    handle_settings_local_delta,
    handle_settings_sync_arrival,
    settings_delta_state_values,
    settings_delta_is_sync_arrival,
)
from app.watcher.state import WatcherState
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def test_delta_apply_receipted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    previous_values = {
        key: value
        for key, value in _read_frontmatter(vault_root / SETTINGS_LOCAL_REL).items()
        if key in RUNTIME_GATING_SETTINGS
    }
    _write_local_settings(vault_root, {"enableAutoIndexing": False})

    result = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_LOCAL_REL,
        previous_values=previous_values,
    )

    assert result.errors == ()
    rows = query_settings_receipts(outbox_path=outbox_path).rows
    row = next(row for row in rows if row.key == "enableAutoIndexing")
    assert row.surface == "file"
    assert row.file == SETTINGS_LOCAL_REL.name
    assert row.old_value is True
    assert row.new_value is False


def _write_watchers_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: panel
                scope_glob: ""
                debounce_ms: 0
                rate_limit_per_min: 30
                emit_event: "panel.scan.requested"
              - name: ingest
                scope_glob: ""
                debounce_ms: 0
                rate_limit_per_min: 30
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def _touch(path: Path, timestamp: float) -> None:
    os.utime(path, (timestamp, timestamp))


def _read_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    data = yaml.safe_load(frontmatter)
    assert isinstance(data, dict)
    return data


def _write_local_settings(vault_root: Path, updates: dict[str, object]) -> Path:
    store = MarkdownSettingsStore()
    local_md = vault_root / "settings" / "local.md"
    document = store.read(local_md)
    frontmatter = dict(document.frontmatter)
    frontmatter.update(updates)
    store.write_frontmatter(local_md, frontmatter, body=document.body)
    return local_md


def _write_youtube_settings(vault_root: Path, updates: dict[str, object]) -> Path:
    store = MarkdownSettingsStore()
    youtube_md = vault_root / SETTINGS_YOUTUBE_REL
    document = store.read(youtube_md)
    frontmatter = dict(document.frontmatter)
    frontmatter.update(updates)
    store.write_frontmatter(youtube_md, frontmatter, body=document.body)
    return youtube_md


def test_youtube_master_switch_file_delta_is_guarded_and_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A direct youtube.md edit cannot activate without WriteGuard + receipt."""
    import app.write_guard as _wg_module

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    previous_values = {"youtubeSync.enabled": False}

    _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "safe_mode", "reason": "maintenance window"},
    ):
        blocked = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_YOUTUBE_REL,
            previous_values=previous_values,
        )

    assert blocked.values == previous_values
    assert blocked.receipts == ()
    assert blocked.errors and "blocked" in blocked.errors[0]
    assert not [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]

    # Keep-on-disk deny semantics: the human's edit REMAINS in the git-shared
    # owner file — this seam never rewrites it, because a denial on one
    # machine must not clobber a value another machine legitimately accepted
    # and receipted (youtube.md syncs with 'commit' policy). The ACCEPTED
    # values stay at the last guarded state, so runtime-gating consumers must
    # consume the seam's accepted values, never raw resolution.
    store = MarkdownSettingsStore()
    youtube_md = vault_root / SETTINGS_YOUTUBE_REL
    assert store.read(youtube_md).frontmatter["youtubeSync.enabled"] is True

    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "healthy", "reason": None},
    ):
        allowed = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_YOUTUBE_REL,
            previous_values=previous_values,
        )

    assert allowed.errors == ()
    assert allowed.values == {"youtubeSync.enabled": True}
    assert len(allowed.receipts) == 1
    receipt = allowed.receipts[0]
    assert receipt.key == "youtubeSync.enabled"
    assert receipt.surface == "file"
    assert receipt.is_runtime_gating is True
    row = next(
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    )
    assert row.old_value is False
    assert row.new_value is True

    # Reverse direction: deleting the enabling key while blocked is denied the
    # same way — the accepted True stays in the seam's values, no receipt is
    # emitted, and the file keeps the human's edit (key absent, not restored).
    document = store.read(youtube_md)
    frontmatter = dict(document.frontmatter)
    del frontmatter["youtubeSync.enabled"]
    store.write_frontmatter(youtube_md, frontmatter, body=document.body)
    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "safe_mode", "reason": "maintenance window"},
    ):
        removal_blocked = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_YOUTUBE_REL,
            previous_values={"youtubeSync.enabled": True},
        )
    assert removal_blocked.values == {"youtubeSync.enabled": True}
    assert removal_blocked.receipts == ()
    assert removal_blocked.errors
    assert "youtubeSync.enabled" not in store.read(youtube_md).frontmatter


def test_gating_delta_on_unselected_vault_is_deferred_not_marked_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gating-file delta on a not-selected vault defers instead of routing.

    The result carries ``deferred=True`` so callers skip recording the file
    as seen and the edit re-processes once the vault validates — otherwise
    the unrouted on-disk value would silently become effective through
    resolution when the vault recovers (round-B review finding).
    """
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    # Invalidate the vault: the committed marker file is required for
    # validate_vault to return 'selected'.
    (vault_root / "settings" / "vault.md").unlink()

    result = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": False},
    )

    assert result.deferred is True
    assert result.values == {"youtubeSync.enabled": False}
    assert result.receipts == ()
    assert result.errors and "requires selected vault" in result.errors[0]

    # A routable delta is not deferred (control case).
    (vault_root / "settings" / "vault.md").write_text(
        "---\nschema: design-handoff.vault.v1\nscope: vault-shared\nvaultId: v1\nvaultName: V\n---\n",
        encoding="utf-8",
    )
    import app.write_guard as _wg_module

    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "healthy", "reason": None},
    ):
        routable = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_YOUTUBE_REL,
            previous_values={"youtubeSync.enabled": False},
        )
    assert routable.deferred is False


def test_local_file_cannot_override_youtube_master_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cross-file gate is ignored loudly and produces no success receipt."""
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")

    _write_local_settings(vault_root, {"youtubeSync.enabled": True})
    result = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_LOCAL_REL,
        previous_values=None,
    )

    assert result.values is not None
    assert "youtubeSync.enabled" not in result.values
    assert result.receipts == ()
    assert result.errors and "owned by youtube.md" in result.errors[0]
    resolution = SettingsService().resolve(VaultManager().validate_vault(vault_root))
    assert resolution.settings["youtubeSync.enabled"].value is False
    assert not [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]


def test_first_seen_youtube_activation_is_guarded_and_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing watcher state cannot turn an on-disk true into trusted state."""
    import app.write_guard as _wg_module

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})

    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "safe_mode", "reason": "maintenance window"},
    ):
        blocked = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_YOUTUBE_REL,
            previous_values=None,
        )

    assert blocked.values == {"youtubeSync.enabled": False}
    assert blocked.receipts == ()
    assert blocked.errors and "blocked" in blocked.errors[0]
    assert not [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]

    # Keep-on-disk deny: the untrusted on-disk true stays as human-authored
    # input (never rewritten by this seam — the file may have arrived via git
    # from a machine where it WAS legitimately accepted); only the seam's
    # accepted values guard what the runtime trusts.
    store = MarkdownSettingsStore()
    youtube_md = vault_root / SETTINGS_YOUTUBE_REL
    assert store.read(youtube_md).frontmatter["youtubeSync.enabled"] is True

    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "healthy", "reason": None},
    ):
        allowed = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_YOUTUBE_REL,
            previous_values=None,
        )

    assert allowed.errors == ()
    assert allowed.values == {"youtubeSync.enabled": True}
    assert len(allowed.receipts) == 1
    assert allowed.receipts[0].old_value is False
    assert allowed.receipts[0].new_value is True


def test_multiple_watcher_specs_emit_one_settings_receipt_per_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    VaultManager().initialize_vault(vault_root, machine_role="primary", remember=False)

    config_path = tmp_path / "watchers.yaml"
    _write_watchers_config(config_path)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "settings/*.md")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")

    registry.run_registry_once(config_path)

    local_md = _write_local_settings(vault_root, {"enableAutoIndexing": False})
    _touch(local_md, 1_700_000_050.0)

    summaries = registry.run_registry_once(config_path)
    total_receipts = sum(int(summary.get("settings_receipts_in_tick", 0)) for summary in summaries.values())

    assert total_receipts == 1
    assert summaries["panel"]["changed_in_tick"] >= 1
    assert summaries["ingest"]["changed_in_tick"] >= 1
    assert summaries["panel"]["emitted_in_tick"] == 0
    assert summaries["ingest"]["emitted_in_tick"] == 0


def test_runtime_gating_key_removal_routes_settings_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)

    local_md = vault_root / "settings" / "local.md"
    previous_values = {
        key: value
        for key, value in _read_frontmatter(local_md).items()
        if key in RUNTIME_GATING_SETTINGS
    }
    assert "enableAutoIndexing" in previous_values
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")

    store = MarkdownSettingsStore()
    document = store.read(local_md)
    frontmatter = dict(document.frontmatter)
    frontmatter.pop("enableAutoIndexing", None)
    store.write_frontmatter(local_md, frontmatter, body=document.body)
    _touch(local_md, 1_700_000_090.0)

    captured_calls: list[tuple[str, object, str, str, bool]] = []
    original_update = SettingsService.update_setting

    def _spy_update(
        self: SettingsService,
        context,
        key,
        value,
        *,
        surface="api",
        actor="human",
        persist=True,
    ):
        captured_calls.append((key, value, surface, actor, persist))
        return original_update(
            self,
            context,
            key,
            value,
            surface=surface,
            actor=actor,
            persist=persist,
        )

    with patch.object(SettingsService, "update_setting", _spy_update):
        result = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_LOCAL_REL,
            previous_values=previous_values,
        )

    assert result.errors == ()
    assert result.values is not None
    assert "enableAutoIndexing" not in result.values
    assert len(result.receipts) == 1
    receipt = result.receipts[0]
    assert receipt.key == "enableAutoIndexing"
    assert receipt.surface == "file"
    assert receipt.actor == "human"
    assert receipt.is_runtime_gating is True
    assert receipt.value is None
    assert receipt.old_value is True
    assert receipt.new_value is None
    assert captured_calls == [("enableAutoIndexing", True, "file", "human", False)]
    assert "enableAutoIndexing" not in _read_frontmatter(local_md)

    row = next(
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "enableAutoIndexing"
    )
    assert row.value is None
    assert row.old_value is True
    assert row.new_value is None


def test_owner_file_deletion_routes_runtime_gating_reset_through_governed_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    VaultManager().initialize_vault(vault_root, machine_role="primary", remember=False)
    outbox_path = tmp_path / "outbox.jsonl"
    config_path = tmp_path / "watchers.yaml"
    _write_watchers_config(config_path)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "settings/*.md")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")

    registry.run_registry_once(config_path)

    youtube_md = _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    _touch(youtube_md, 1_700_000_100.0)
    registry.run_registry_once(config_path)

    youtube_md.unlink()
    # Exercise the production race window: a compiler-source delta in the
    # same tick must not suppress the authority-bearing owner-file reset.
    source_md = vault_root / "settings" / "runtime-source.md"
    source_md.write_text("---\n{}\n---\n", encoding="utf-8")
    _touch(source_md, 1_700_000_101.0)

    summaries = registry.run_registry_once(config_path)
    total_deletions = sum(
        int(summary.get("runtime_gating_owner_file_deletions_in_tick", 0))
        for summary in summaries.values()
    )
    total_receipts = sum(
        int(summary.get("settings_receipts_in_tick", 0))
        for summary in summaries.values()
    )

    assert total_deletions == 1
    assert total_receipts == 1
    rows = [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]
    assert [(row.old_value, row.new_value) for row in rows] == [
        (False, True),
        (True, None),
    ]
    assert SettingsService().resolve_accepted_runtime_gating(
        VaultManager().validate_vault(vault_root)
    )["youtubeSync.enabled"].value is False


def test_local_owner_file_deletion_uses_retained_identity_for_governed_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _write_local_settings(vault_root, {"youtubeSync.runnerEnabled": True})

    accepted = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_LOCAL_REL,
        previous_values={"youtubeSync.runnerEnabled": False},
    )
    assert accepted.errors == ()
    retained_state = settings_delta_state_values(accepted)

    (vault_root / SETTINGS_LOCAL_REL).unlink()
    reset = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_LOCAL_REL,
        previous_values=retained_state,
    )

    assert reset.deferred is False
    assert reset.errors == ()
    runner_receipts = [
        receipt
        for receipt in reset.receipts
        if receipt.key == "youtubeSync.runnerEnabled"
    ]
    assert [(receipt.old_value, receipt.new_value) for receipt in runner_receipts] == [
        (True, None)
    ]
    assert runner_receipts[0].vault_id == accepted.vault_id
    assert runner_receipts[0].local_instance_id == accepted.local_instance_id


def test_registry_retries_blocked_owner_file_deletion_until_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.write_guard as write_guard_module

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    config_path = tmp_path / "watchers.yaml"
    _write_watchers_config(config_path)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "settings/*.md")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    registry.run_registry_once(config_path)

    youtube_md = _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    _touch(youtube_md, 1_700_000_300.0)
    registry.run_registry_once(config_path)
    youtube_md.unlink()

    with patch.object(
        write_guard_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "safe_mode", "reason": "maintenance"},
    ):
        blocked = registry.run_registry_once(config_path)
    assert sum(
        int(summary.get("settings_write_errors_in_tick", 0))
        for summary in blocked.values()
    ) >= 1

    with patch.object(
        write_guard_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "healthy", "reason": None},
    ):
        recovered = registry.run_registry_once(config_path)
    assert sum(
        int(summary.get("settings_receipts_in_tick", 0))
        for summary in recovered.values()
    ) == 1
    rows = [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]
    assert [(row.old_value, row.new_value) for row in rows] == [
        (False, True),
        (True, None),
    ]


def test_legacy_watcher_retries_blocked_owner_file_deletion_until_receipted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.write_guard as write_guard_module

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    cfg = WatcherConfig(
        enable=True,
        vault_path=vault_root,
        scope_glob="settings/*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        state_path=tmp_path / "legacy-state.json",
        stop_file=tmp_path / "WATCHER_STOP",
        outbox_path=outbox_path,
        summary_interval=0,
        tick_sleep_seconds=0.0,
        tick_log_path=tmp_path / "legacy-tick.jsonl",
    )
    state = WatcherState()
    legacy_watcher.run_tick(cfg, state, now=1_700_000_400.0)
    youtube_md = _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    _touch(youtube_md, 1_700_000_401.0)
    legacy_watcher.run_tick(cfg, state, now=1_700_000_401.0)
    youtube_md.unlink()

    with patch.object(
        write_guard_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "safe_mode", "reason": "maintenance"},
    ):
        blocked = legacy_watcher.run_tick(cfg, state, now=1_700_000_402.0)
    assert int(blocked.get("settings_write_errors_in_tick", 0)) >= 1

    with patch.object(
        write_guard_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "healthy", "reason": None},
    ):
        recovered = legacy_watcher.run_tick(cfg, state, now=1_700_000_403.0)
    assert int(recovered.get("settings_receipts_in_tick", 0)) == 1
    rows = [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]
    assert [(row.old_value, row.new_value) for row in rows] == [
        (False, True),
        (True, None),
    ]


def test_sync_arrival_replay_does_not_emit_human_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})

    result = handle_settings_sync_arrival(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": False},
    )

    assert result.errors == ()
    assert [receipt.actor for receipt in result.receipts] == ["sync"]
    assert [receipt.surface for receipt in result.receipts] == ["sync"]
    rows = query_settings_receipts(outbox_path=outbox_path).rows
    assert [row.actor for row in rows if row.key == "youtubeSync.enabled"] == ["sync"]


def test_runtime_gating_sync_arrival_unwired_uses_production_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    VaultManager().initialize_vault(vault_root, machine_role="primary", remember=False)
    config_path = tmp_path / "watchers.yaml"
    outbox_path = tmp_path / "outbox.jsonl"
    _write_watchers_config(config_path)
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    subprocess.run(["git", "config", "user.name", "Sync Test"], cwd=vault_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sync-test@example.invalid"],
        cwd=vault_root,
        check=True,
    )
    subprocess.run(["git", "add", "settings"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=vault_root, check=True)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "settings/*.md")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    registry.run_registry_once(config_path)

    youtube_md = _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    _touch(youtube_md, 1_700_000_200.0)
    subprocess.run(["git", "add", "settings/youtube.md"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "sync arrival"], cwd=vault_root, check=True)

    registry.run_registry_once(config_path)

    rows = [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]
    assert [(row.surface, row.actor, row.new_value) for row in rows] == [
        ("sync", "sync", True)
    ]


def test_sync_arrival_revalidates_exact_bytes_after_git_provenance_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    subprocess.run(["git", "config", "user.name", "Sync Test"], cwd=vault_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sync-test@example.invalid"],
        cwd=vault_root,
        check=True,
    )
    subprocess.run(["git", "add", "settings"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=vault_root, check=True)
    _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    subprocess.run(["git", "add", "settings/youtube.md"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "sync arrival"], cwd=vault_root, check=True)

    real_run = subprocess.run
    raced = False

    def _run_with_race(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal raced
        result = real_run(*args, **kwargs)
        command = args[0] if args else kwargs.get("args")
        if not raced and isinstance(command, list) and "status" in command:
            raced = True
            _write_youtube_settings(vault_root, {"youtubeSync.enabled": False})
        return result

    monkeypatch.setattr("app.watcher.settings_delta.subprocess.run", _run_with_race)
    result = handle_settings_detected_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": False},
    )

    assert result.deferred is True
    assert result.receipts == ()
    assert result.errors and "changed during provenance inspection" in result.errors[0]
    assert not query_settings_receipts(outbox_path=outbox_path).rows


def test_sync_arrival_defers_edit_after_final_provenance_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    subprocess.run(["git", "config", "user.name", "Sync Test"], cwd=vault_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sync-test@example.invalid"],
        cwd=vault_root,
        check=True,
    )
    subprocess.run(["git", "add", "settings"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=vault_root, check=True)
    youtube_md = _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    subprocess.run(["git", "add", "settings/youtube.md"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "sync arrival"], cwd=vault_root, check=True)

    real_capture = settings_delta_module._capture_settings_snapshot
    captures = 0

    def _capture_then_edit(path: Path):  # type: ignore[no-untyped-def]
        nonlocal captures
        snapshot = real_capture(path)
        captures += 1
        if captures == 2:
            path.write_text(
                f"{path.read_text(encoding='utf-8')}local edit after provenance\n",
                encoding="utf-8",
            )
        return snapshot

    monkeypatch.setattr(
        settings_delta_module,
        "_capture_settings_snapshot",
        _capture_then_edit,
    )
    result = handle_settings_detected_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": False},
    )

    assert result.deferred is True
    assert result.receipts == ()
    assert result.errors and "changed before governed processing" in result.errors[0]
    assert not query_settings_receipts(outbox_path=outbox_path).rows
    assert youtube_md.read_text(encoding="utf-8").endswith(
        "local edit after provenance\n"
    )


def test_sync_deletion_defers_recreation_after_final_provenance_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    youtube_md = _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    subprocess.run(["git", "config", "user.name", "Sync Test"], cwd=vault_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sync-test@example.invalid"],
        cwd=vault_root,
        check=True,
    )
    subprocess.run(["git", "add", "settings"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=vault_root, check=True)
    deleted_payload = youtube_md.read_bytes()
    youtube_md.unlink()
    subprocess.run(["git", "add", "-u", "settings/youtube.md"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "sync deletion"], cwd=vault_root, check=True)

    real_capture = settings_delta_module._capture_settings_snapshot
    captures = 0

    def _capture_then_recreate(path: Path):  # type: ignore[no-untyped-def]
        nonlocal captures
        snapshot = real_capture(path)
        captures += 1
        if captures == 2:
            path.write_bytes(deleted_payload)
        return snapshot

    monkeypatch.setattr(
        settings_delta_module,
        "_capture_settings_snapshot",
        _capture_then_recreate,
    )
    result = handle_settings_detected_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": True},
    )

    assert result.deferred is True
    assert result.receipts == ()
    assert result.errors and "changed before governed processing" in result.errors[0]
    assert not query_settings_receipts(outbox_path=outbox_path).rows
    assert youtube_md.read_bytes() == deleted_payload


def test_sync_arrival_defers_mutation_after_processing_capture_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture three is not acceptance when the live generation changes next."""

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Sync Test"], cwd=vault_root, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "sync-test@example.invalid"],
        cwd=vault_root,
        check=True,
    )
    subprocess.run(["git", "add", "settings"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=vault_root, check=True)
    _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    subprocess.run(["git", "add", "settings/youtube.md"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "sync arrival"], cwd=vault_root, check=True)

    real_capture = settings_delta_module._capture_settings_snapshot
    captures = 0

    def _capture_then_mutate(path: Path):  # type: ignore[no-untyped-def]
        nonlocal captures
        snapshot = real_capture(path)
        captures += 1
        if captures == 3:
            path.write_text(
                f"{path.read_text(encoding='utf-8')}generation after capture three\n",
                encoding="utf-8",
            )
        return snapshot

    monkeypatch.setattr(
        settings_delta_module,
        "_capture_settings_snapshot",
        _capture_then_mutate,
    )
    result = handle_settings_detected_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": False},
    )

    assert captures >= 4
    assert result.deferred is True
    assert result.receipts == ()
    assert not query_settings_receipts(outbox_path=outbox_path).rows
    assert (
        SettingsService().resolve_accepted_runtime_gating(
            VaultManager().validate_vault(vault_root)
        )["youtubeSync.enabled"].value
        is False
    )


def test_registry_generation_race_after_processing_snapshot_is_not_stranded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance and watcher state advance must name the same file generation."""

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    config_path = tmp_path / "watchers.yaml"
    outbox_path = tmp_path / "outbox.jsonl"
    config_path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: panel
                scope_glob: ""
                debounce_ms: 0
                rate_limit_per_min: 30
                emit_event: "panel.scan.requested"
            """
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Sync Test"], cwd=vault_root, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "sync-test@example.invalid"],
        cwd=vault_root,
        check=True,
    )
    subprocess.run(["git", "add", "settings"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=vault_root, check=True)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "settings/*.md")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    registry.run_registry_once(config_path)

    youtube_md = _write_youtube_settings(
        vault_root, {"youtubeSync.enabled": True}
    )
    _touch(youtube_md, 1_700_000_500.0)
    subprocess.run(["git", "add", "settings/youtube.md"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "sync arrival"], cwd=vault_root, check=True)

    original_update = SettingsService.update_setting
    raced = False

    def _update_after_processing_snapshot(
        self: SettingsService,
        context,
        key,
        value,
        **kwargs,
    ):
        nonlocal raced
        if not raced and key == "youtubeSync.enabled":
            raced = True
            youtube_md.write_text(
                f"{youtube_md.read_text(encoding='utf-8')}post-snapshot generation\n",
                encoding="utf-8",
            )
        return original_update(self, context, key, value, **kwargs)

    with patch.object(
        SettingsService,
        "update_setting",
        _update_after_processing_snapshot,
    ):
        raced_summaries = registry.run_registry_once(config_path)

    assert raced is True
    assert sum(
        int(summary.get("settings_receipts_in_tick", 0))
        for summary in raced_summaries.values()
    ) == 0
    assert not query_settings_receipts(outbox_path=outbox_path).rows
    context = VaultManager().validate_vault(vault_root)
    assert (
        SettingsService().resolve_accepted_runtime_gating(context)[
            "youtubeSync.enabled"
        ].value
        is False
    )

    newer_digest = hashlib.sha256(youtube_md.read_bytes()).hexdigest()
    panel_state = WatcherState.load(
        tmp_path / "state" / "watcher_state_panel.json"
    )
    assert panel_state.last_hash(str(SETTINGS_YOUTUBE_REL)) != newer_digest

    recovered_summaries = registry.run_registry_once(config_path)
    assert sum(
        int(summary.get("settings_receipts_in_tick", 0))
        for summary in recovered_summaries.values()
    ) == 1
    rows = query_settings_receipts(outbox_path=outbox_path).rows
    assert [
        (row.surface, row.actor, row.new_value)
        for row in rows
        if row.key == "youtubeSync.enabled"
    ] == [("file", "human", True)]
    assert (
        SettingsService().resolve_accepted_runtime_gating(context)[
            "youtubeSync.enabled"
        ].value
        is True
    )
    recovered_state = WatcherState.load(
        tmp_path / "state" / "watcher_state_panel.json"
    )
    assert recovered_state.last_hash(str(SETTINGS_YOUTUBE_REL)) == newer_digest


def test_registry_retries_non_deletion_receipt_failure_without_marking_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient durable-receipt failure leaves an owner delta pending."""

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    config_path = tmp_path / "watchers.yaml"
    outbox_path = tmp_path / "outbox.jsonl"
    _write_watchers_config(config_path)
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_root))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "settings/*.md")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.05")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    registry.run_registry_once(config_path)

    youtube_md = _write_youtube_settings(
        vault_root, {"youtubeSync.enabled": True}
    )
    _touch(youtube_md, 1_700_000_510.0)
    with patch(
        "app.vault.settings_service.emit_durable_settings_write_receipt_once",
        side_effect=RuntimeError("synthetic durable sink failure"),
    ):
        failed_summaries = registry.run_registry_once(config_path)

    assert sum(
        int(summary.get("settings_write_errors_in_tick", 0))
        for summary in failed_summaries.values()
    ) >= 1
    assert not query_settings_receipts(outbox_path=outbox_path).rows

    recovered_summaries = registry.run_registry_once(config_path)
    assert sum(
        int(summary.get("settings_receipts_in_tick", 0))
        for summary in recovered_summaries.values()
    ) == 1
    rows = query_settings_receipts(outbox_path=outbox_path).rows
    assert [
        (row.old_value, row.new_value)
        for row in rows
        if row.key == "youtubeSync.enabled"
    ] == [(False, True)]


def test_gitignored_local_settings_edit_is_not_misattributed_as_sync(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    VaultManager().initialize_vault(vault_root, machine_role="primary", remember=False)
    subprocess.run(["git", "init", "-q"], cwd=vault_root, check=True)
    subprocess.run(["git", "config", "user.name", "Sync Test"], cwd=vault_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sync-test@example.invalid"],
        cwd=vault_root,
        check=True,
    )
    subprocess.run(["git", "add", "settings"], cwd=vault_root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=vault_root, check=True)

    _write_local_settings(vault_root, {"youtubeSync.runnerEnabled": True})

    assert settings_delta_is_sync_arrival(
        vault_root=vault_root,
        rel_path=SETTINGS_LOCAL_REL,
    ) is False


def test_runtime_gating_replay_ignores_durable_accepted_baseline_is_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.write_guard as _wg_module

    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    accepted = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": False},
    )
    assert len(accepted.receipts) == 1

    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "safe_mode", "reason": "maintenance window"},
    ):
        replay = handle_settings_local_delta(
            vault_root=vault_root,
            rel_path=SETTINGS_YOUTUBE_REL,
            previous_values=None,
        )

    assert replay.errors == ()
    assert replay.receipts == ()
    assert replay.values == {"youtubeSync.enabled": True}
    rows = [
        row
        for row in query_settings_receipts(outbox_path=outbox_path).rows
        if row.key == "youtubeSync.enabled"
    ]
    assert len(rows) == 1


def test_cross_file_runtime_gating_residue_is_reported_and_unaccepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _write_local_settings(vault_root, {"youtubeSync.enabled": True})

    result = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_LOCAL_REL,
        previous_values=None,
    )

    assert result.values == {"enableAutoIndexing": True, "enableVaultWatcher": True, "youtubeSync.runnerEnabled": False}
    assert result.receipts == ()
    assert any("owned by youtube.md" in error for error in result.errors)
    assert SettingsService().resolve_accepted_runtime_gating(
        VaultManager().validate_vault(vault_root)
    )["youtubeSync.enabled"].value is False
    assert not [row for row in query_settings_receipts(outbox_path=outbox_path).rows if row.key == "youtubeSync.enabled"]
