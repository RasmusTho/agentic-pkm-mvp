from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts/lib/companion_ui_startup.sh"

# Source the startup lib, then override cui_repo_root to a fake repo whose
# scripts/start_full_system.sh stub records that it ran. curl is stubbed to
# simulate the runtime API being healthy or not. We then call cui_start_runtime
# and report whether the full-system start was invoked.
_HARNESS = r"""
set -euo pipefail
FAKE_ROOT="$1"
CURL_RC="$2"
export CUI_API_PORT=18001
export CUI_CHANNEL=dev
export CUI_COMPOSE_PROJECT=pkm-dev
export CUI_COMPOSE_FILES=docker-compose.yaml

mkdir -p "$FAKE_ROOT/scripts"
cat > "$FAKE_ROOT/scripts/start_full_system.sh" <<'EOS'
#!/usr/bin/env bash
# cui_start_runtime cd's to the repo root before invoking us.
touch "$(pwd)/.full_system_ran"
EOS
chmod +x "$FAKE_ROOT/scripts/start_full_system.sh"

source "$LIB"
cui_repo_root() { printf '%s' "$FAKE_ROOT"; }
curl() { return "$CURL_RC"; }

cui_start_runtime >/dev/null 2>&1 || true

if [ -f "$FAKE_ROOT/.full_system_ran" ]; then
  echo RECREATED
else
  echo SKIPPED
fi
"""


def _run(tmp_path: Path, *, curl_rc: int, force_recreate: str | None = None) -> str:
    env = {"LIB": str(LIB)}
    cmd = ["bash", "-c", _HARNESS, "harness", str(tmp_path), str(curl_rc)]
    full_env = {**_base_env(), **env}
    if force_recreate is not None:
        full_env["CUI_FORCE_RECREATE"] = force_recreate
    result = subprocess.run(
        cmd, env=full_env, cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip().splitlines()[-1]


def _base_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def test_healthy_stack_skips_compose_recreate(tmp_path: Path) -> None:
    # curl_rc=0 → API healthy → recreate skipped.
    assert _run(tmp_path, curl_rc=0) == "SKIPPED"


def test_cold_start_runs_full_system(tmp_path: Path) -> None:
    # curl_rc=7 → API unreachable → full start_full_system.sh runs.
    assert _run(tmp_path, curl_rc=7) == "RECREATED"


def test_warm_restart_no_health_race(tmp_path: Path) -> None:
    # Healthy stack must not be recreated, so the watcher/worker health race
    # never opens on the warm-restart path.
    assert _run(tmp_path, curl_rc=0) == "SKIPPED"


def test_force_recreate_overrides_healthy_skip(tmp_path: Path) -> None:
    # Operator can force a rebuild even when the stack is healthy.
    assert _run(tmp_path, curl_rc=0, force_recreate="1") == "RECREATED"
