from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.not_pg


def _bash(cmd: str) -> str:
    proc = subprocess.run(
        ["bash", "-lc", cmd],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def test_apply_start_full_system_defaults_sets_watcher_auto_exec_when_unset() -> None:
    out = _bash(
        "set -euo pipefail; "
        "source scripts/lib/start_full_system_env.sh; "
        "unset WATCHER_AUTO_EXEC; "
        "apply_start_full_system_defaults; "
        "printf '%s' \"${WATCHER_AUTO_EXEC-}\""
    )
    assert out == "1"


def test_apply_start_full_system_defaults_does_not_override_explicit_value() -> None:
    out = _bash(
        "set -euo pipefail; "
        "source scripts/lib/start_full_system_env.sh; "
        "export WATCHER_AUTO_EXEC=0; "
        "apply_start_full_system_defaults; "
        "printf '%s' \"$WATCHER_AUTO_EXEC\""
    )
    assert out == "0"


def test_apply_start_full_system_defaults_does_not_override_empty_string() -> None:
    out = _bash(
        "set -euo pipefail; "
        "source scripts/lib/start_full_system_env.sh; "
        "export WATCHER_AUTO_EXEC=''; "
        "apply_start_full_system_defaults; "
        "python - <<'PY'\n"
        "import os\n"
        "print('set' if 'WATCHER_AUTO_EXEC' in os.environ else 'unset')\n"
        "print(repr(os.environ.get('WATCHER_AUTO_EXEC')))\n"
        "PY"
    )
    lines = out.splitlines()
    assert lines[0] == "set"
    assert lines[1] == "''"


def test_apply_start_full_system_defaults_sets_startup_check_obsidian_when_unset() -> None:
    out = _bash(
        "set -euo pipefail; "
        "source scripts/lib/start_full_system_env.sh; "
        "unset STARTUP_CHECK_OBSIDIAN; "
        "apply_start_full_system_defaults; "
        "printf '%s' \"${STARTUP_CHECK_OBSIDIAN-}\""
    )
    assert out == "1"


def test_apply_start_full_system_defaults_does_not_override_explicit_startup_check_obsidian() -> None:
    out = _bash(
        "set -euo pipefail; "
        "source scripts/lib/start_full_system_env.sh; "
        "export STARTUP_CHECK_OBSIDIAN=0; "
        "apply_start_full_system_defaults; "
        "printf '%s' \"$STARTUP_CHECK_OBSIDIAN\""
    )
    assert out == "0"


def test_apply_start_full_system_vault_defaults_infers_dirs_from_layout_note_frontmatter() -> None:
    out = _bash(
        "set -euo pipefail; "
        "vault_root=$(mktemp -d); "
        "mkdir -p \"$vault_root/config\"; "
        "cat > \"$vault_root/config/vault.layout.md\" <<'EOF'\n"
        "---\n"
        "system_folder: config\n"
        "inbox_folder: intake\n"
        "desk_folder: workbench\n"
        "---\n"
        "EOF\n"
        "source scripts/lib/start_full_system_env.sh; "
        "unset VAULT_SYSTEM_DIR_REL VAULT_INBOX_DIR_REL VAULT_DESK_DIR_REL; "
        "apply_start_full_system_vault_defaults \"$vault_root\"; "
        "python - <<'PY'\n"
        "import os\n"
        "print(os.environ.get('VAULT_SYSTEM_DIR_REL', ''))\n"
        "print(os.environ.get('VAULT_INBOX_DIR_REL', ''))\n"
        "print(os.environ.get('VAULT_DESK_DIR_REL', ''))\n"
        "PY"
    )
    lines = out.splitlines()
    assert lines == ["config", "intake", "workbench"]


def test_apply_start_full_system_vault_defaults_does_not_guess_legacy_dirs_from_empty_layout_note() -> None:
    out = _bash(
        "set -euo pipefail; "
        "vault_root=$(mktemp -d); "
        "mkdir -p \"$vault_root/⚙️ System\" \"$vault_root/📥 Inbox\" \"$vault_root/🛠️ Workbench\"; "
        ": > \"$vault_root/⚙️ System/vault.layout.md\"; "
        "source scripts/lib/start_full_system_env.sh; "
        "unset VAULT_SYSTEM_DIR_REL VAULT_INBOX_DIR_REL VAULT_DESK_DIR_REL; "
        "apply_start_full_system_vault_defaults \"$vault_root\"; "
        "python - <<'PY'\n"
        "import os\n"
        "print(os.environ.get('VAULT_SYSTEM_DIR_REL', ''))\n"
        "print(os.environ.get('VAULT_INBOX_DIR_REL', ''))\n"
        "print(os.environ.get('VAULT_DESK_DIR_REL', ''))\n"
        "PY"
    )
    assert out == ""


def test_apply_start_full_system_vault_defaults_does_not_override_explicit_values() -> None:
    out = _bash(
        "set -euo pipefail; "
        "vault_root=$(mktemp -d); "
        "mkdir -p \"$vault_root/⚙️ System\" \"$vault_root/📥 Inbox\" \"$vault_root/🛠️ Workbench\"; "
        ": > \"$vault_root/⚙️ System/vault.layout.md\"; "
        "source scripts/lib/start_full_system_env.sh; "
        "export VAULT_SYSTEM_DIR_REL=CustomSystem; "
        "export VAULT_INBOX_DIR_REL=CustomInbox; "
        "export VAULT_DESK_DIR_REL=CustomDesk; "
        "apply_start_full_system_vault_defaults \"$vault_root\"; "
        "python - <<'PY'\n"
        "import os\n"
        "print(os.environ.get('VAULT_SYSTEM_DIR_REL', ''))\n"
        "print(os.environ.get('VAULT_INBOX_DIR_REL', ''))\n"
        "print(os.environ.get('VAULT_DESK_DIR_REL', ''))\n"
        "PY"
    )
    lines = out.splitlines()
    assert lines == ["CustomSystem", "CustomInbox", "CustomDesk"]
