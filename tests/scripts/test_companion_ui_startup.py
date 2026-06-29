from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "lib" / "companion_ui_startup.sh"
START_SCRIPTS = (
    REPO_ROOT / "scripts" / "dev" / "start_niflheim_ui.sh",
    REPO_ROOT / "scripts" / "test" / "start_bifrost_ui.sh",
    REPO_ROOT / "scripts" / "prod" / "start_midgard_ui.sh",
)

_START_UI_HARNESS = r"""
set -euo pipefail
FAKE_ROOT="$1"
BIND_LAN="$2"

mkdir -p "$FAKE_ROOT/companion-ui/companion-app"

source "$LIB"
cui_repo_root() { printf '%s' "$FAKE_ROOT"; }
cui_python_bin() { printf '/bin/echo'; }
cui_free_ui_port() { return 0; }
curl() { return 0; }

export CUI_CHANNEL=test
export CUI_API_PORT=18002
export CUI_UI_PORT=8112
export CUI_COMPOSE_PROJECT=pkm-test
export CUI_SERVE_MODULE=companion_ui.workspace.serve_dev_page
if [ "$BIND_LAN" = "__unset__" ]; then
  unset CUI_BIND_LAN
else
  export CUI_BIND_LAN="$BIND_LAN"
fi

cui_start_ui >/tmp/cui-start-ui.out 2>&1
printf 'HOST=%s\n' "$CUI_UI_HOST"
cui_lan_ip() { printf '192.0.2.10'; }
cui_tailscale_ip() { printf '100.64.0.10'; }
cui_print_summary
"""


def _run_start_ui(tmp_path: Path, *, bind_lan: str | None) -> str:
    env = dict(os.environ)
    env["LIB"] = str(LIB)
    result = subprocess.run(
        ["bash", "-c", _START_UI_HARNESS, "harness", str(tmp_path), bind_lan or "__unset__"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_default_bind_is_loopback_when_flag_not_set(tmp_path: Path) -> None:
    output = _run_start_ui(tmp_path, bind_lan=None)

    assert "HOST=127.0.0.1" in output
    assert "UI bind     : 127.0.0.1 only" in output
    assert "UI (LAN)" not in output
    assert "UI (Tailscale)" not in output

    for script in START_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert 'CUI_BIND_LAN="${CUI_BIND_LAN:-1}"' not in text
        assert "CUI_BIND_LAN:-1" not in text


def test_bind_lan_flag_exposes_lan_urls(tmp_path: Path) -> None:
    output = _run_start_ui(tmp_path, bind_lan="1")

    assert "HOST=0.0.0.0" in output
    assert "UI (LAN)    : http://192.0.2.10:8112/" in output
    assert "UI (Tailscale): http://100.64.0.10:8112/" in output
