"""Tests for app.settings.health_settings.

Covers:
- Missing settings file returns defaults with status "missing"
- Malformed YAML / missing thresholds returns status "fail" with defaults
- Valid thresholds load correctly
- Env-var threshold overrides applied only when PKM_SETTINGS_PROFILE=lab
- Env-var threshold overrides suppressed in operator/prod profile
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.settings.health_settings import (
    HealthSettingsV1,
    load_health_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_FRONTMATTER = dedent("""\
    ---
    thresholds:
      outbox_degrade_oldest_age_s: 20.0
      outbox_recover_oldest_age_s: 8.0
      degrade_samples: 4
      recover_samples: 12
    ---
    # Health Settings
""")

_MISSING_THRESHOLD_FRONTMATTER = dedent("""\
    ---
    thresholds:
      outbox_degrade_oldest_age_s: 20.0
      outbox_recover_oldest_age_s: 8.0
      degrade_samples: 4
    ---
""")

_NO_THRESHOLD_BLOCK_FRONTMATTER = dedent("""\
    ---
    incident_capture:
      enabled: false
    ---
""")


def _write_health_file(vault_root: Path, content: str) -> None:
    """Write health.md at the expected vault path using VAULT_SYSTEM_DIR_REL=@System."""
    health_dir = vault_root / "@System" / "Settings"
    health_dir.mkdir(parents=True, exist_ok=True)
    (health_dir / "health.md").write_text(content, encoding="utf-8")


def _load(
    vault_root: Path,
    env_vars: dict[str, str] | None = None,
    profile: str = "operator",
) -> "HealthSettingsLoadResult":  # noqa: F821 – returned by load_health_settings
    """Thin wrapper that injects deterministic env and profile mappings."""
    env_map: dict[str, str] = {"PKM_SETTINGS_PROFILE": profile}
    if env_vars:
        env_map.update(env_vars)

    return load_health_settings(
        vault_root=vault_root,
        env_getter=env_map.get,
        profile_env=env_map,
    )


# ---------------------------------------------------------------------------
# Basic load behaviour
# ---------------------------------------------------------------------------


def test_missing_file_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    result = _load(vault)
    assert result.status == "missing"
    assert result.settings == HealthSettingsV1.defaults()
    assert result.errors == []


def test_canonical_health_load_does_not_require_legacy_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "health.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text(_VALID_FRONTMATTER, encoding="utf-8")
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "../invalid-legacy-layout")

    result = _load(vault)

    assert result.status == "ok"
    assert result.source.path == str(canonical)


def test_canonical_health_logs_shadowed_legacy_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    vault = tmp_path / "vault"
    canonical = vault / "settings" / "health.md"
    legacy = vault / "_system" / "Settings" / "health.md"
    canonical.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    canonical.write_text(_VALID_FRONTMATTER, encoding="utf-8")
    legacy.write_text(_MISSING_THRESHOLD_FRONTMATTER, encoding="utf-8")
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "_system")

    result = _load(vault)

    assert result.status == "ok"
    assert result.source.path == str(canonical)
    assert caplog.text.count("shadowed legacy settings") == 1
    assert str(legacy) in caplog.text


@pytest.mark.parametrize("escape_kind", ["parent", "absolute"])
def test_configured_legacy_health_path_must_remain_inside_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    escape_kind: str,
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside_health = outside / "Settings" / "health.md"
    outside_health.parent.mkdir(parents=True)
    outside_health.write_text(_VALID_FRONTMATTER, encoding="utf-8")
    configured_dir = "../outside" if escape_kind == "parent" else str(outside)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", configured_dir)

    with pytest.raises(ValueError, match="escapes vault root|symlink"):
        _load(vault)
    assert outside_health.read_text(encoding="utf-8") == _VALID_FRONTMATTER


def test_configured_legacy_health_symlink_must_remain_inside_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    outside_health = outside / "Settings" / "health.md"
    outside_health.parent.mkdir()
    outside_health.write_text(_VALID_FRONTMATTER, encoding="utf-8")
    (vault / "linked-system").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "linked-system")

    with pytest.raises(ValueError, match="escapes vault root|symlink"):
        _load(vault)
    assert outside_health.read_text(encoding="utf-8") == _VALID_FRONTMATTER


def test_configured_legacy_health_in_vault_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    actual = vault / "Actual"
    vault.mkdir()
    health = actual / "Settings" / "health.md"
    health.parent.mkdir(parents=True)
    health.write_text(_VALID_FRONTMATTER, encoding="utf-8")
    (vault / "Meta").symlink_to(actual, target_is_directory=True)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "Meta")

    with pytest.raises(ValueError, match="symlink"):
        _load(vault)


def test_valid_thresholds_load_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_health_file(vault, _VALID_FRONTMATTER)

    result = _load(vault)
    assert result.status == "ok"
    assert result.errors == []
    t = result.settings.thresholds
    assert t.outbox_degrade_oldest_age_s == 20.0
    assert t.outbox_recover_oldest_age_s == 8.0
    assert t.degrade_samples == 4
    assert t.recover_samples == 12


def test_default_legacy_health_path_warns_once_without_self_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    vault = tmp_path / "vault"
    legacy = vault / "_system" / "Settings" / "health.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(_VALID_FRONTMATTER, encoding="utf-8")
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "_system")

    result = _load(vault)

    assert result.status == "ok"
    assert caplog.text.count("deprecated settings location") == 1
    assert "shadowed legacy settings" not in caplog.text


def test_missing_threshold_key_returns_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_health_file(vault, _MISSING_THRESHOLD_FRONTMATTER)

    result = _load(vault)
    assert result.status == "fail"
    assert any("missing thresholds.recover_samples" in e for e in result.errors)
    assert result.settings == HealthSettingsV1.defaults()


def test_no_threshold_block_returns_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_health_file(vault, _NO_THRESHOLD_BLOCK_FRONTMATTER)

    result = _load(vault)
    assert result.status == "fail"
    assert any("missing thresholds block" in e for e in result.errors)
    assert result.settings == HealthSettingsV1.defaults()


# ---------------------------------------------------------------------------
# Env-var override policy
# ---------------------------------------------------------------------------


def test_env_overrides_applied_in_lab_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HEALTH_THRESHOLDS_* env vars MUST take effect under PKM_SETTINGS_PROFILE=lab."""
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_health_file(vault, _VALID_FRONTMATTER)

    env_overrides = {
        "HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S": "99.0",
        "HEALTH_THRESHOLDS_OUTBOX_RECOVER_OLDEST_AGE_S": "33.0",
        "HEALTH_THRESHOLDS_DEGRADE_SAMPLES": "7",
        "HEALTH_THRESHOLDS_RECOVER_SAMPLES": "20",
    }
    result = _load(vault, env_vars=env_overrides, profile="lab")

    assert result.status == "ok"
    assert result.errors == []
    t = result.settings.thresholds
    assert t.outbox_degrade_oldest_age_s == 99.0
    assert t.outbox_recover_oldest_age_s == 33.0
    assert t.degrade_samples == 7
    assert t.recover_samples == 20


def test_env_overrides_suppressed_in_operator_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HEALTH_THRESHOLDS_* env vars MUST NOT alter thresholds in operator profile."""
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_health_file(vault, _VALID_FRONTMATTER)

    env_overrides = {
        "HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S": "999.0",
        "HEALTH_THRESHOLDS_DEGRADE_SAMPLES": "99",
    }
    result = _load(vault, env_vars=env_overrides, profile="operator")

    assert result.status == "ok"
    assert result.errors == []
    # Thresholds must reflect the file values, NOT the env overrides.
    t = result.settings.thresholds
    assert t.outbox_degrade_oldest_age_s == 20.0
    assert t.degrade_samples == 4


def test_env_overrides_suppressed_when_profile_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no PKM_SETTINGS_PROFILE set, env overrides must be suppressed (defaults to operator)."""
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_health_file(vault, _VALID_FRONTMATTER)

    # Profile defaults to operator when not set; pass empty mapping.
    result = load_health_settings(
        vault_root=vault,
        env_getter={"HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S": "999.0"}.get,
        profile_env={},  # no PKM_SETTINGS_PROFILE → resolves to operator
    )

    assert result.status == "ok"
    t = result.settings.thresholds
    assert t.outbox_degrade_oldest_age_s == 20.0


def test_invalid_env_override_in_lab_returns_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad env-var value in lab mode must cause status='fail' and return defaults."""
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "@System")
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_health_file(vault, _VALID_FRONTMATTER)

    env_overrides = {
        "HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S": "not-a-float",
    }
    result = _load(vault, env_vars=env_overrides, profile="lab")

    assert result.status == "fail"
    assert any("HEALTH_THRESHOLDS_OUTBOX_DEGRADE_OLDEST_AGE_S" in e for e in result.errors)
    assert result.settings == HealthSettingsV1.defaults()
