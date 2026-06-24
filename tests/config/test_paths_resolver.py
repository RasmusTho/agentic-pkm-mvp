"""Fitness check: resolve_vault_root does not silently default to ./vault.

AC2 for #2476: ``resolve_vault_root`` no longer silently defaults to the
CWD-relative ``./vault`` path when ``VAULT_ROOT`` is unset.  An unset
``VAULT_ROOT`` must yield an explicit no-vault signal, not a fallback path.

Source: docs/VAULT_OPTIONAL_RUNTIME/RESOLVE_NO_VAULT_STATE.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.paths import (
    VaultRootMisconfiguredError,
    VaultRootNotBoundError,
    resolve_optional_vault_root,
    resolve_vault_root,
)


def test_resolve_vault_root_no_silent_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_vault_root raises VaultRootNotBoundError — does NOT return ./vault.

    The silent CWD-relative ``Path("vault")`` fallback is the
    ``provenance="fallback"`` footgun behind the 2026-06-09 "notes won't
    render" incident.  This test ensures the footgun is gone: callers that
    need no-vault tolerance must use ``resolve_optional_vault_root()`` instead.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

    # Must NOT silently return the CWD-relative ./vault default
    with pytest.raises(VaultRootNotBoundError):
        resolve_vault_root()

    # Double-check: the optional resolver still returns None gracefully
    result = resolve_optional_vault_root()
    assert result is None
    assert result != Path("vault")


def test_resolve_vault_root_set_but_missing_still_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Set-but-missing VAULT_ROOT still raises VaultRootMisconfiguredError.

    The no-silent-default hardening must not change set-but-missing semantics
    (#1757 regression guard).
    """
    missing = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing))

    with pytest.raises(VaultRootMisconfiguredError) as exc_info:
        resolve_vault_root()

    assert exc_info.value.env_var == "VAULT_ROOT"
    assert exc_info.value.configured_path == missing


def test_resolve_vault_root_bound_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A configured, existing VAULT_ROOT resolves normally."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    result = resolve_vault_root()
    assert result == vault
    assert result != Path("vault")  # not the CWD-relative fallback


def test_resolve_vault_root_not_bound_error_distinct_from_misconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VaultRootNotBoundError (unset) is distinct from VaultRootMisconfiguredError (set-missing)."""
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

    # Unset raises the "not bound" variant
    with pytest.raises(VaultRootNotBoundError):
        resolve_vault_root()

    # "not bound" is not a subclass of "misconfigured"
    assert not issubclass(VaultRootNotBoundError, VaultRootMisconfiguredError)
