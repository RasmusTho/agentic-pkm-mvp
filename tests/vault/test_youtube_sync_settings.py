"""YSS-01 (#3916): youtubeSync.* settings model.

Single comprehensive Verify: target, matching the issue's AC text exactly:
"youtubeSync.* settings resolve with defaults, scopes, and provenance;
invalid values degrade to defaults with a validation error; the two gating
keys are WriteGuard-gated on write from the production call site."

Pattern borrowed from `tests/vault/test_settings_service.py` (hand-built
`VaultContext` + raw frontmatter files, no `VaultManager` needed) and
`tests/companion_ui/test_runtime_control_settings_authority.py` (WriteGuard
blocked-write pattern: patch `DEFAULT_WRITE_GUARD.snapshot_fn` directly,
because the singleton is imported fresh inside `SettingsService.update_setting`
at call time).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.knowledge_acquisition.source_registry import VALID_ACQUISITION_MODES
from app.vault.manager import VaultContext
from app.vault.markdown_settings import MarkdownSettingsStore
from app.vault.settings_service import (
    ACCEPTED_RUNTIME_GATING_SETTINGS,
    RUNTIME_GATING_SETTINGS,
    SettingsService,
    SettingsWriteError,
)

pytestmark = pytest.mark.not_pg


def _write(path: Path, frontmatter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter, encoding="utf-8")


def _init_minimal_vault(vault_root: Path) -> Path:
    """A minimal valid vault-shared/vault-local settings set, deliberately
    WITHOUT settings/youtube.md -- proves the built-in default path holds even
    when the capability's own settings file has never been scaffolded (e.g. a
    vault created before this capability shipped)."""
    settings_dir = vault_root / "settings"
    files = {
        "vault.md": (
            "---\nschema: design-handoff.vault.v1\nscope: vault-shared\n"
            "vaultId: vault-test\nvaultName: Test\n---\n"
        ),
        "local.md": (
            "---\nschema: design-handoff.local.v1\nscope: vault-local\n"
            "localInstanceId: l1\nmachineRole: primary\n---\n"
        ),
    }
    for name, content in files.items():
        _write(settings_dir / name, content)
    return settings_dir


_EXPECTED_DEFAULTS: dict[str, object] = {
    "youtubeSync.enabled": False,
    "youtubeSync.inboxPollSeconds": 180,
    "youtubeSync.playlistPollSeconds": 3600,
    "youtubeSync.subscriptionsPollSeconds": 21600,
    "youtubeSync.reconcileIntervalDays": 7,
    "youtubeSync.maxConcurrentAcquisitions": 2,
    "youtubeSync.subscriptionDefaultPolicy": "discover_only",
    "youtubeSync.captionsEnabled": True,
    "youtubeSync.mediaDownloadEnabled": False,
    "youtubeSync.runnerEnabled": False,
}


def test_subscription_default_policy_matches_registry_contract() -> None:
    """Settings and registry share one pinned acquisition-mode vocabulary."""
    definition = SettingsService().registry.get("youtubeSync.subscriptionDefaultPolicy")
    assert definition is not None
    assert frozenset(definition.allowed_values) == VALID_ACQUISITION_MODES


def test_runtime_gating_accessor_rejects_unaccepted_disk_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raw owner-file input is not runtime-trusted until the governed seam accepts it."""
    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
    )
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    _write(settings_dir / "youtube.md", "---\nscope: vault-shared\nyoutubeSync.enabled: true\n---\n")
    service = SettingsService()

    # ``resolve`` remains the operator/provenance view; runtime callers use
    # the accepted accessor and must not trust a first-seen disk value.
    assert service.resolve(context).settings["youtubeSync.enabled"].value is True
    assert service.resolve_accepted_runtime_gating(context)["youtubeSync.enabled"].value is False

    service.update_setting(context, "youtubeSync.enabled", True, surface="api", actor="human")
    assert service.resolve_accepted_runtime_gating(context)["youtubeSync.enabled"].value is True


def test_runtime_gating_receipt_identity_path_only_does_not_cross_vault_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    _write(settings_dir / "youtube.md", "---\nscope: vault-shared\nyoutubeSync.enabled: true\n---\n")

    first = VaultContext(
        status="selected",
        active_vault_id="vault-first",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="local-first",
    )
    second_generation_same_path = VaultContext(
        status="selected",
        active_vault_id="vault-second",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="local-second",
    )
    service = SettingsService()

    service.update_setting(first, "youtubeSync.enabled", True, surface="api", actor="human")

    assert service.resolve_accepted_runtime_gating(first)["youtubeSync.enabled"].value is True
    assert (
        service.resolve_accepted_runtime_gating(second_generation_same_path)[
            "youtubeSync.enabled"
        ].value
        is False
    )


def test_runtime_gating_current_consumers_bypass_accessor_scope_is_yss_only(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
    )

    assert set(SettingsService().resolve_accepted_runtime_gating(context)) == set(
        ACCEPTED_RUNTIME_GATING_SETTINGS
    )
    assert ACCEPTED_RUNTIME_GATING_SETTINGS == frozenset(
        {"youtubeSync.enabled", "youtubeSync.runnerEnabled"}
    )


def test_accepted_runtime_receipt_best_effort_after_write_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
    )
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    _write(settings_dir / "youtube.md", "---\nscope: vault-shared\nyoutubeSync.enabled: false\n---\n")

    def _fail_receipt(_receipt: object) -> None:
        raise RuntimeError("synthetic durable sink failure")

    monkeypatch.setattr(
        "app.vault.settings_service.emit_durable_settings_write_receipt_once",
        _fail_receipt,
    )
    service = SettingsService()

    with pytest.raises(SettingsWriteError, match="not durably accepted"):
        service.update_setting(
            context,
            "youtubeSync.enabled",
            True,
            surface="api",
            actor="human",
        )

    # The raw file may have been written, but success was not reported and the
    # runtime projection remains fail-closed because no durable acceptance
    # receipt exists.
    assert service.resolve(context).settings["youtubeSync.enabled"].value is True
    assert service.resolve_accepted_runtime_gating(context)["youtubeSync.enabled"].value is False


def test_defaults_scopes_provenance_and_gated_writes(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
    )
    service = SettingsService()

    # --- 1. Defaults resolve built-in when youtube.md/local.md carry no override ---
    resolution = service.resolve(context)
    for key, expected in _EXPECTED_DEFAULTS.items():
        effective = resolution.settings[key]
        assert effective.value == expected, key
        assert effective.scope == "built-in", key
        assert effective.source == "built-in", key

    # --- 2. RUNTIME_GATING_SETTINGS names exactly the two authority-bearing keys ---
    assert "youtubeSync.enabled" in RUNTIME_GATING_SETTINGS
    assert "youtubeSync.runnerEnabled" in RUNTIME_GATING_SETTINGS

    # --- 3. Vault-shared override + provenance (settings/youtube.md) ---
    youtube_md = settings_dir / "youtube.md"
    _write(
        youtube_md,
        "---\nscope: vault-shared\nyoutubeSync.enabled: true\nyoutubeSync.inboxPollSeconds: 90\n---\n",
    )
    resolution = service.resolve(context)
    enabled_setting = resolution.settings["youtubeSync.enabled"]
    assert enabled_setting.value is True
    assert enabled_setting.scope == "vault-shared"
    assert enabled_setting.source_file == str(youtube_md)
    inbox_setting = resolution.settings["youtubeSync.inboxPollSeconds"]
    assert inbox_setting.value == 90
    assert inbox_setting.scope == "vault-shared"
    assert inbox_setting.source_file == str(youtube_md)
    # An untouched key in the same file still resolves to its default.
    assert resolution.settings["youtubeSync.captionsEnabled"].value is True

    # --- 4. Vault-local override + provenance (settings/local.md) for runnerEnabled ---
    local_md = settings_dir / "local.md"
    _write(
        local_md,
        (
            "---\nschema: design-handoff.local.v1\nscope: vault-local\n"
            "localInstanceId: l1\nmachineRole: primary\nyoutubeSync.runnerEnabled: true\n---\n"
        ),
    )
    resolution = service.resolve(context)
    runner_setting = resolution.settings["youtubeSync.runnerEnabled"]
    assert runner_setting.value is True
    assert runner_setting.scope == "vault-local"
    assert runner_setting.source_file == str(local_md)

    # --- 5. Invalid values degrade to defaults with a surfaced validation error ---
    _write(
        youtube_md,
        (
            "---\nscope: vault-shared\nyoutubeSync.inboxPollSeconds: -5\n"
            "youtubeSync.subscriptionDefaultPolicy: not_a_real_mode\n---\n"
        ),
    )
    resolution = service.resolve(context)
    degraded_inbox = resolution.settings["youtubeSync.inboxPollSeconds"]
    assert degraded_inbox.value == 180  # default, not -5 -- never a silent apply
    assert degraded_inbox.scope == "built-in"
    assert any(
        err.key == "youtubeSync.inboxPollSeconds" and err.source_file == str(youtube_md)
        for err in resolution.validation_errors
    )
    degraded_policy = resolution.settings["youtubeSync.subscriptionDefaultPolicy"]
    assert degraded_policy.value == "discover_only"
    assert any(
        err.key == "youtubeSync.subscriptionDefaultPolicy" and err.source_file == str(youtube_md)
        for err in resolution.validation_errors
    )

    # Restore a valid youtube.md for the write-gating section below.
    _write(youtube_md, "---\nscope: vault-shared\n---\n")

    # --- 6. WriteGuard gates the two runtime-gating keys at the production call site ---
    import app.write_guard as _wg_module

    healthy_snapshot = {"state": "healthy", "reason": None}
    blocked_snapshot = {"state": "safe_mode", "reason": "maintenance window"}

    # Positive control: a healthy snapshot lets the governed write through and
    # emits a receipt tagged is_runtime_gating -- proves the gate is genuinely
    # exercised, not merely present-but-vacuous.
    with patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=healthy_snapshot):
        effective, receipt = service.update_setting(
            context, "youtubeSync.enabled", True, surface="cli", actor="human"
        )
        assert effective.value is True
        assert receipt.is_runtime_gating is True
        assert receipt.key == "youtubeSync.enabled"

    for gated_key, value in (("youtubeSync.enabled", False), ("youtubeSync.runnerEnabled", True)):
        with (
            patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=blocked_snapshot),
            pytest.raises(SettingsWriteError) as excinfo,
        ):
            service.update_setting(context, gated_key, value, surface="cli", actor="human")
        message = str(excinfo.value).lower()
        assert "blocked" in message or "health gate" in message

    # A non-gating youtubeSync.* key is NOT WriteGuard-gated (mirrors the
    # existing enableVaultWatcher/enableAutoIndexing precedent).
    with patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=blocked_snapshot):
        effective, receipt = service.update_setting(
            context, "youtubeSync.captionsEnabled", False, surface="cli", actor="human"
        )
        assert effective.value is False
        assert receipt.is_runtime_gating is False


@pytest.mark.parametrize(
    ("key", "default", "invalid_literals"),
    (
        ("youtubeSync.inboxPollSeconds", 180, ("180.5", ".nan", ".inf", "-.inf", "true")),
        ("youtubeSync.playlistPollSeconds", 3600, ("3600.5", ".nan", ".inf", "-.inf", "true")),
        ("youtubeSync.subscriptionsPollSeconds", 21600, ("21600.5", ".nan", ".inf", "-.inf", "true")),
        ("youtubeSync.reconcileIntervalDays", 7, ("7.5", ".nan", ".inf", "-.inf", "true")),
        ("youtubeSync.maxConcurrentAcquisitions", 2, ("2.5", ".nan", ".inf", "-.inf", "true")),
    ),
)
def test_bounded_youtube_numeric_settings_reject_non_finite_non_integer_values(
    tmp_path: Path, key: str, default: int, invalid_literals: tuple[str, ...]
) -> None:
    """Resolution and the production write seam share finite-int validation."""
    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
    )
    service = SettingsService()
    youtube_md = settings_dir / "youtube.md"

    for literal in invalid_literals:
        _write(youtube_md, f"---\nscope: vault-shared\n{key}: {literal}\n---\n")
        resolution = service.resolve(context)
        effective = resolution.settings[key]
        assert effective.value == default
        assert effective.scope == "built-in"
        assert any(error.key == key and error.source_file == str(youtube_md) for error in resolution.validation_errors)

    for invalid_value in (default + 0.5, float("nan"), float("inf"), float("-inf"), True):
        with pytest.raises(SettingsWriteError, match="finite"):
            service.update_setting(context, key, invalid_value, surface="cli", actor="human")


def test_update_setting_scaffolds_missing_youtube_settings_file(tmp_path: Path) -> None:
    """An existing vault becomes writable only after a healthy guard permits it."""
    import app.write_guard as _wg_module

    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
    )
    service = SettingsService()
    youtube_md = settings_dir / "youtube.md"
    assert not youtube_md.exists()

    healthy_snapshot = {"state": "healthy", "reason": None}
    blocked_snapshot = {"state": "safe_mode", "reason": "maintenance window"}

    with patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=healthy_snapshot):
        effective, receipt = service.update_setting(
            context, "youtubeSync.enabled", True, surface="cli", actor="human"
        )
    assert youtube_md.exists()
    assert effective.value is True
    assert receipt.is_runtime_gating is True
    resolution = service.resolve(context)
    assert resolution.settings["youtubeSync.captionsEnabled"].value is True
    assert resolution.settings["youtubeSync.captionsEnabled"].source_file == str(youtube_md)

    youtube_md.unlink()
    # Every youtubeSync.* scaffold is WriteGuard-gated, including a normally
    # non-runtime-gated key. Safe mode must leave the missing file absent.
    for key, value in (("youtubeSync.enabled", True), ("youtubeSync.captionsEnabled", False)):
        with (
            patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=blocked_snapshot),
            pytest.raises(SettingsWriteError, match="blocked"),
        ):
            service.update_setting(context, key, value, surface="cli", actor="human")
        assert not youtube_md.exists()

    # A healthy guard permits a non-gating youtubeSync.* write to scaffold.
    with patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=healthy_snapshot):
        effective, receipt = service.update_setting(
            context, "youtubeSync.captionsEnabled", False, surface="cli", actor="human"
        )
    assert youtube_md.exists()
    assert effective.value is False
    assert receipt.is_runtime_gating is False

    # Existing-file semantics remain unchanged: safe mode does not turn a
    # normal non-gating setting update into a guarded write.
    with patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=blocked_snapshot):
        effective, receipt = service.update_setting(
            context, "youtubeSync.captionsEnabled", True, surface="cli", actor="human"
        )
    assert effective.value is True
    assert receipt.is_runtime_gating is False

    local_md = settings_dir / "local.md"
    local_md.unlink()
    with (
        patch.object(_wg_module.DEFAULT_WRITE_GUARD, "snapshot_fn", return_value=healthy_snapshot),
        pytest.raises(SettingsWriteError, match="does not exist"),
    ):
        service.update_setting(context, "youtubeSync.runnerEnabled", True, surface="cli", actor="human")
    assert not local_md.exists()


def test_settings_scaffold_toctou_overwrite_preserves_concurrent_owner_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RacingStore(MarkdownSettingsStore):
        def write_missing(self, path: Path, frontmatter: object, body: str) -> bool:
            del frontmatter, body
            path.write_text(
                "---\nscope: vault-shared\nyoutubeSync.captionsEnabled: false\n"
                "ownerSentinel: preserve-me\n---\n# Concurrent owner\n",
                encoding="utf-8",
            )
            return False

    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
        local_instance_id="l1",
    )
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    service = SettingsService(markdown_store=RacingStore())

    service.update_setting(
        context,
        "youtubeSync.captionsEnabled",
        True,
        surface="api",
        actor="human",
    )

    document = MarkdownSettingsStore().read(settings_dir / "youtube.md")
    assert document.frontmatter["ownerSentinel"] == "preserve-me"
    assert document.frontmatter["youtubeSync.captionsEnabled"] is True
    assert document.body.strip() == "# Concurrent owner"


def test_static_shared_settings_scaffold_is_guarded_for_legacy_paths_file(tmp_path: Path) -> None:
    """Every static shared seed is guarded before a legacy-vault file is created."""
    import app.write_guard as _wg_module

    vault_root = tmp_path / "vault"
    settings_dir = _init_minimal_vault(vault_root)
    context = VaultContext(
        status="selected",
        active_vault_path=str(vault_root),
        settings_path=str(settings_dir),
    )
    service = SettingsService()
    paths_md = settings_dir / "paths.md"

    with (
        patch.object(
            _wg_module.DEFAULT_WRITE_GUARD,
            "snapshot_fn",
            return_value={"state": "safe_mode", "reason": "maintenance window"},
        ),
        pytest.raises(SettingsWriteError, match="settings scaffold blocked"),
    ):
        service.update_setting(
            context,
            "handoffFolder",
            "Changed Handoff",
            surface="cli",
            actor="human",
        )
    assert not paths_md.exists()

    with patch.object(
        _wg_module.DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        return_value={"state": "healthy", "reason": None},
    ):
        effective, receipt = service.update_setting(
            context,
            "handoffFolder",
            "Changed Handoff",
            surface="cli",
            actor="human",
        )

    assert paths_md.exists()
    assert effective.value == "Changed Handoff"
    assert receipt.is_runtime_gating is False
