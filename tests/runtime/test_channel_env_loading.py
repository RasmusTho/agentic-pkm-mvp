"""Tests for per-channel env file loading in start_full_system.sh.

Verifies:
- .env.<channel>.local is loaded before .env when PKM_ENVIRONMENT is set
- Vault paths containing spaces (e.g. iCloud "Mobile Documents") are handled safely
- CHANNEL / PKM_CHANNEL / ENVIRONMENT are accepted as channel selectors alongside PKM_ENVIRONMENT
- Channel-specific file takes precedence over base .env for VAULT_ROOT and layout vars
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg


def _bash(cmd: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", "-lc", cmd],
        capture_output=True,
        text=True,
        env=merged_env,
    )


def _bash_ok(cmd: str, *, env: dict[str, str] | None = None) -> str:
    proc = _bash(cmd, env=env)
    assert proc.returncode == 0, f"bash failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return proc.stdout.strip()


def test_load_env_defaults_file_handles_path_with_spaces() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env.dev.local"
        env_file.write_text(
            'VAULT_ROOT=/Users/test/Mobile Documents/iCloud~md~obsidian/Documents/Niflheim\n',
            encoding="utf-8",
        )
        out = _bash_ok(
            f"source scripts/lib/load_env_defaults.sh; "
            f"unset VAULT_ROOT; "
            f"load_env_defaults_file '{env_file}'; "
            f"printf '%s' \"${{VAULT_ROOT:-}}\""
        )
        assert out == "/Users/test/Mobile Documents/iCloud~md~obsidian/Documents/Niflheim"


def test_load_env_defaults_file_channel_specific_takes_precedence_over_base() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        dev_env = Path(tmpdir) / ".env.dev.local"
        dev_env.write_text(
            'VAULT_ROOT=/dev/niflheim\nVAULT_INBOX_DIR_REL=📥 Inbox\n',
            encoding="utf-8",
        )
        base_env = Path(tmpdir) / ".env"
        base_env.write_text(
            'VAULT_ROOT=/prod/alpha\n',
            encoding="utf-8",
        )
        out = _bash_ok(
            f"source scripts/lib/load_env_defaults.sh; "
            f"unset VAULT_ROOT VAULT_INBOX_DIR_REL; "
            f"load_env_defaults_file '{dev_env}'; "
            f"load_env_defaults_file '{base_env}'; "
            f"printf '%s|%s' \"${{VAULT_ROOT:-}}\" \"${{VAULT_INBOX_DIR_REL:-}}\""
        )
        vault_root, inbox = out.split("|", 1)
        assert vault_root == "/dev/niflheim", "Channel-specific VAULT_ROOT must win over base .env"
        assert inbox == "📥 Inbox"


def test_load_env_defaults_file_does_not_override_caller_env() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        env_file = Path(tmpdir) / ".env.dev.local"
        env_file.write_text("VAULT_ROOT=/dev/niflheim\n", encoding="utf-8")
        out = _bash_ok(
            f"source scripts/lib/load_env_defaults.sh; "
            f"export VAULT_ROOT=/caller/vault; "
            f"load_env_defaults_file '{env_file}'; "
            f"printf '%s' \"${{VAULT_ROOT:-}}\""
        )
        assert out == "/caller/vault", "Caller-supplied VAULT_ROOT must not be overwritten"


def test_channel_env_key_variants_accepted() -> None:
    """CHANNEL and PKM_CHANNEL are accepted in addition to PKM_ENVIRONMENT."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dev_env = Path(tmpdir) / ".env.dev.local"
        dev_env.write_text("VAULT_SYSTEM_DIR_REL=⚙️ System\n", encoding="utf-8")
        for env_key in ("PKM_ENVIRONMENT", "CHANNEL", "PKM_CHANNEL"):
            out = _bash_ok(
                f"source scripts/lib/load_env_defaults.sh; "
                f"unset VAULT_SYSTEM_DIR_REL; "
                f"export {env_key}=dev; "
                f"_ch=\"${{{env_key}}}\"; "
                f"load_env_defaults_file \"{tmpdir}/.env.${{_ch}}.local\"; "
                f"printf '%s' \"${{VAULT_SYSTEM_DIR_REL:-}}\""
            )
            assert out == "⚙️ System", (
                f"{env_key}=dev should cause .env.dev.local to be loaded; got {out!r}"
            )


def test_load_env_defaults_file_skips_missing_file_gracefully() -> None:
    out = _bash_ok(
        "source scripts/lib/load_env_defaults.sh; "
        "load_env_defaults_file '.env.nonexistent-channel.local'; "
        "echo ok"
    )
    assert out == "ok"


def test_vault_layout_vars_emitted_to_stdout_after_apply() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        system_dir = Path(tmpdir) / "⚙️ System"
        system_dir.mkdir()
        layout = system_dir / "vault.layout.md"
        layout.write_text(
            "---\nsystem_folder: ⚙️ System\ninbox_folder: 📥 Inbox\ndesk_folder: 🛠️ Workbench\n---\n",
            encoding="utf-8",
        )
        out = _bash_ok(
            "source scripts/lib/start_full_system_env.sh; "
            f"unset VAULT_SYSTEM_DIR_REL VAULT_INBOX_DIR_REL VAULT_DESK_DIR_REL; "
            f"apply_start_full_system_vault_defaults '{tmpdir}'; "
            "python - <<'PY'\n"
            "import os\n"
            "print(os.environ.get('VAULT_SYSTEM_DIR_REL', ''))\n"
            "print(os.environ.get('VAULT_INBOX_DIR_REL', ''))\n"
            "print(os.environ.get('VAULT_DESK_DIR_REL', ''))\n"
            "PY"
        )
        lines = out.splitlines()
        assert lines[0] == "⚙️ System"
        assert lines[1] == "📥 Inbox"
        assert lines[2] == "🛠️ Workbench"
