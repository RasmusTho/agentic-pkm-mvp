"""The watcher startup error on an uninitialized vault is actionable — #1991.

Reproduces the prod promotion failure: a real vault that predates the
vault-settings foundation validates as ``uninitialized`` and the watcher
fail-exits. The error must name the remedy, not just the missing files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.watcher.config import _validate_watcher_vault
from app.watcher.registry import _validate_registry_vault


@pytest.mark.parametrize("validate", [_validate_watcher_vault, _validate_registry_vault])
def test_actionable_error_on_uninitialized_vault(tmp_path: Path, validate) -> None:
    vault = tmp_path / "Midgård"  # exists, but has no settings files
    vault.mkdir()

    with pytest.raises(ValueError) as excinfo:
        validate(vault)

    message = str(excinfo.value)
    assert "uninitialized" in message
    assert "vault init" in message  # the actionable remedy
