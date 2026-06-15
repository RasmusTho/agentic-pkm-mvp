"""#2005 — `scripts/start_full_system.sh` boots idle with no VAULT_ROOT.

The #1991 fail-exit (`exit 2: VAULT_ROOT is required`) is flipped to a no-vault
idle posture: an *unset* VAULT_ROOT must not exit 2 and must announce the idle
bring-up. A *set-but-missing* VAULT_ROOT still fails loud (covered by
tests/uat/test_negative_safety_integrated_runtime.py::test_missing_vault_fails_loud
and tests/watcher/test_watcher_idle_without_vault.py).

Hermetic: a fake `docker` that fails loudly proves the script reaches the
no-vault idle posture before any real Docker interaction — the same fake-docker
pattern used by the negative-safety UAT.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg


def test_boots_idle_without_vault_root(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    fallback_vault = repo_root / "vault"
    before_fallback_exists = fallback_vault.exists()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\necho fake docker should not run >&2\nexit 99\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = {
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "HOME": str(Path.home()),
        # VAULT_ROOT intentionally absent -> no-vault idle posture.
    }
    result = subprocess.run(
        ["bash", "scripts/start_full_system.sh"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    combined = result.stdout + result.stderr

    # The #1991 fail-exit is gone: unset VAULT_ROOT must not exit 2, and the
    # exit-2 "VAULT_ROOT is required" message must not appear.
    assert result.returncode != 2, (
        f"Unset VAULT_ROOT must not exit 2 (no-vault idle flip); "
        f"rc={result.returncode}: {combined[:800]}"
    )
    assert "VAULT_ROOT is required" not in combined, (
        f"The exit-2 'VAULT_ROOT is required' gate must be gone: {combined[:800]}"
    )

    # The script announces the no-vault idle bring-up.
    assert "no-vault idle posture" in combined, (
        f"Expected the no-vault idle banner; got: {combined[:800]}"
    )

    # The legacy ./vault fallback is NOT silently created.
    assert fallback_vault.exists() is before_fallback_exists
