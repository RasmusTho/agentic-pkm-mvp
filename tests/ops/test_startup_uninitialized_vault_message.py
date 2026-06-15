"""Watcher startup posture for an uninitialized vault — #1991 → #2005.

History: #1991 made the watcher fail-exit (raise) on a vault that predates the
vault-settings foundation (status ``uninitialized``), with an actionable remedy
in the message.

#2005 flips that hard precondition to *idle-until-opened* (the symmetric reverse
of an invariant, governed by the #1997 F4 rule). An ``uninitialized`` vault now
makes the validators return ``False`` (idle, no raise) instead of fail-exiting —
the watcher comes up disabled until the vault is initialized/opened. A genuinely
*invalid* vault (e.g. the settings path is a file, not a directory) still fails
loud, so a real misconfiguration is never papered over.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.watcher.config import _validate_watcher_vault
from app.watcher.registry import _validate_registry_vault


@pytest.mark.parametrize("validate", [_validate_watcher_vault, _validate_registry_vault])
def test_uninitialized_vault_idles_not_raises(tmp_path: Path, validate) -> None:
    """#2005: an uninitialized vault idles (returns False) instead of raising."""
    vault = tmp_path / "Midgård"  # exists, but has no settings files
    vault.mkdir()

    # No raise (the #1991 fail-exit is flipped); the watcher idles.
    assert validate(vault) is False


@pytest.mark.parametrize("validate", [_validate_watcher_vault, _validate_registry_vault])
def test_invalid_vault_still_fails_loud(tmp_path: Path, validate) -> None:
    """A genuinely invalid vault (path is a file, not a dir) still raises."""
    vault = tmp_path / "not-a-dir"
    vault.write_text("i am a file, not a vault directory\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        validate(vault)

    assert "selected vault" in str(excinfo.value)
