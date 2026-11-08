#!/usr/bin/env bash
# Install the Builder's pinned local OpenHands components in a dedicated directory.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 || "$1" != /* || ( $# -eq 2 && "$2" != /* ) ]]; then
  printf 'Usage: %s /absolute/install/root [/absolute/worktree/root]\n' "$0" >&2
  exit 2
fi

factory_dir="$1"
worktree_dir="${2:-$factory_dir/worktrees}"
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
command -v uv >/dev/null
command -v npm >/dev/null
command -v codex >/dev/null
mkdir -p "$factory_dir/acp" "$factory_dir/canvas" "$factory_dir/bin" "$worktree_dir"
mkdir -m 700 -p "$factory_dir/runs"

if [[ ! -x "$factory_dir/venv/bin/python" ]]; then
  uv venv --python 3.12 "$factory_dir/venv"
fi
uv pip install --python "$factory_dir/venv/bin/python" \
  'openhands-agent-server==1.60.1' 'openhands-sdk==1.60.1' \
  'openhands-tools==1.60.1' 'agent-client-protocol==0.12.1' \
  'psycopg[binary]==3.2.10'
npm install --prefix "$factory_dir/acp" --save-exact --ignore-scripts \
  '@agentclientprotocol/codex-acp@2.2.2'
npm install --prefix "$factory_dir/canvas" --save-exact --ignore-scripts \
  '@openhands/agent-canvas@1.37.0'
"$factory_dir/venv/bin/python" - "$factory_dir" "$source_dir" "$worktree_dir" <<'PY'
from pathlib import Path
import shlex
import sys

install, source, worktrees = map(Path, sys.argv[1:])
args = ["env", f"PYTHONPATH={source}", str(install / "venv/bin/python"),
        "-m", "app.builderops.openhands_factory", "--install-root", str(install),
        "--state-root", str(install / "runs"), "--worktree-root", str(worktrees)]
entry = install / "bin/openhands"
entry.write_text("#!/bin/sh\nexec " + " ".join(map(shlex.quote, args)) + ' "$@"\n')
entry.chmod(0o755)
PY
printf 'Installed OpenHands components in %s\n' "$factory_dir"
printf 'Owner entry point: %s/bin/openhands\n' "$factory_dir"
printf 'Native Codex: %s\n' "$(codex --version)"
