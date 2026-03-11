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
