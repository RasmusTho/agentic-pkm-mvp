from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
import yaml

import app.watcher.registry as registry
from app.vault.manager import VaultManager
from app.vault.markdown_settings import MarkdownSettingsStore
from app.vault.settings_service import RUNTIME_GATING_SETTINGS, SettingsService
from app.receipts.settings_receipts import query_settings_receipts
from app.watcher.settings_delta import (
    SETTINGS_LOCAL_REL,
    SETTINGS_YOUTUBE_REL,
    handle_settings_local_delta,
    handle_settings_sync_arrival,
)
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
    assert row.file == str(vault_root / SETTINGS_LOCAL_REL)
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
    initialize_test_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")

    youtube_md = _write_youtube_settings(vault_root, {"youtubeSync.enabled": True})
    youtube_md.unlink()

    result = handle_settings_local_delta(
        vault_root=vault_root,
        rel_path=SETTINGS_YOUTUBE_REL,
        previous_values={"youtubeSync.enabled": True},
    )

    assert result.errors == ()
    assert result.values == {"youtubeSync.enabled": False}
    assert [(receipt.key, receipt.old_value, receipt.new_value) for receipt in result.receipts] == [
        ("youtubeSync.enabled", True, None)
    ]
    assert SettingsService().resolve_accepted_runtime_gating(
        VaultManager().validate_vault(vault_root)
    )["youtubeSync.enabled"].value is False


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
