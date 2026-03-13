from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.not_pg


def test_apply_start_full_system_vault_defaults_surfaces_inference_failures() -> None:
    proc = subprocess.run(
        [
            "bash",
            "-lc",
            "set -euo pipefail; "
            "vault_root=$(mktemp -d); "
            "mkdir -p \"$vault_root/System\"; "
            "tmpbin=$(mktemp -d); "
            "cat > \"$tmpbin/python\" <<'EOF'\n"
            "#!/usr/bin/env bash\n"
            "echo helper-crashed >&2\n"
            "exit 42\n"
            "EOF\n"
            "chmod +x \"$tmpbin/python\"; "
            "PATH=\"$tmpbin:$PATH\"; "
            "source scripts/lib/start_full_system_env.sh; "
            "apply_start_full_system_vault_defaults \"$vault_root\""
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 42
    assert "helper-crashed" in proc.stderr
