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
host_home="${HOME:?Host home is required}"
command -v uv >/dev/null
command -v npm >/dev/null
command -v codex >/dev/null
/usr/bin/python3 - "$factory_dir" "$host_home" "$source_dir" <<'PY'
from pathlib import Path
import sys
install, home, source = (Path(value).resolve() for value in sys.argv[1:])
if (install == home or install in home.parents or install == source
        or install in source.parents or source in install.parents):
    raise SystemExit("OpenHands installation overlaps the host home or source repository")
PY
mkdir -p "$factory_dir/acp" "$factory_dir/canvas" "$factory_dir/bin" "$worktree_dir"
mkdir -m 700 -p "$factory_dir/runs"
mkdir -m 700 -p "$factory_dir/setup-home"
[[ ! -L "$factory_dir/setup-home" && -d "$factory_dir/setup-home" ]] || {
  printf 'OpenHands setup home must be a directory, not a link\n' >&2
  exit 1
}
chmod 700 "$factory_dir/setup-home"
clean_env=(env -i "PATH=$PATH" "HOME=$factory_dir/setup-home" "TMPDIR=$factory_dir/setup-home" LANG=C)

# The Canvas launcher belongs to the separately reviewed #6602 candidate.
# Pin its exact contents until that candidate is integrated into this checkout.
canvas_commit=aa521a9d7301d7033a04b4285ff5821a4e791f90
canvas_hash=56a1c913082ea680046979f9828ae376ba4879ecfc36ec28ce95854e0749ab7e
canvas_launcher="$factory_dir/bin/openhands_canvas.py"
if [[ ! -e "$canvas_launcher" ]]; then
  canvas_tmp="$(mktemp "$factory_dir/bin/.canvas.XXXXXXXX")"
  trap 'rm -f -- "$canvas_tmp"' EXIT
  if git -C "$source_dir" cat-file -e "$canvas_commit:scripts/openhands_canvas.py" 2>/dev/null; then
    git -C "$source_dir" show "$canvas_commit:scripts/openhands_canvas.py" > "$canvas_tmp"
  else
    env -i PATH=/usr/bin:/bin HOME="$factory_dir/runs" /usr/bin/curl --fail --silent --show-error \
      --location --proto '=https' --tlsv1.2 \
      "https://raw.githubusercontent.com/RasmusTho/agentic-pkm-mvp/$canvas_commit/scripts/openhands_canvas.py" > "$canvas_tmp"
  fi
  [[ "$(shasum -a 256 "$canvas_tmp" | cut -d ' ' -f 1)" == "$canvas_hash" ]] || {
    printf 'Canvas launcher hash does not match the reviewed candidate\n' >&2
    exit 1
  }
  chmod 700 "$canvas_tmp"
  mv -n "$canvas_tmp" "$canvas_launcher"
  rm -f -- "$canvas_tmp"
  trap - EXIT
fi
[[ -f "$canvas_launcher" && ! -L "$canvas_launcher" && "$(shasum -a 256 "$canvas_launcher" | cut -d ' ' -f 1)" == "$canvas_hash" ]] || {
  printf 'Installed Canvas launcher differs from the reviewed candidate\n' >&2
  exit 1
}

if [[ ! -x "$factory_dir/venv/bin/python" ]]; then
  (cd "$factory_dir" && "${clean_env[@]}" uv venv --no-config --python 3.12 "$factory_dir/venv")
fi
"${clean_env[@]}" /usr/bin/curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  'https://files.pythonhosted.org/packages/b3/0d/bf0567477f7281d9a3926c582bfef21bff7498fc0ffd3e9de21811896a0b/func_timeout-4.3.5.tar.gz' \
  > "$factory_dir/setup-home/func_timeout-4.3.5.tar.gz"
"${clean_env[@]}" "$factory_dir/venv/bin/python" -I -S "$source_dir/scripts/openhands_build_func_timeout.py" \
  "$factory_dir" "$host_home" "$source_dir"
(cd "$factory_dir" && "${clean_env[@]}" npm install --prefix "$factory_dir/acp" --save-exact --ignore-scripts \
  --no-audit --no-fund --registry=https://registry.npmjs.org/ '@agentclientprotocol/codex-acp@2.2.2')
(cd "$factory_dir" && "${clean_env[@]}" npm install --prefix "$factory_dir/canvas" --save-exact --ignore-scripts \
  --no-audit --no-fund --registry=https://registry.npmjs.org/ '@openhands/agent-canvas@1.37.0')
PYTHONPATH="$source_dir" "$factory_dir/venv/bin/python" -m app.builderops.openhands_test_environment "$factory_dir"
"$factory_dir/venv/bin/python" - "$factory_dir" "$source_dir" "$worktree_dir" <<'PY'
from pathlib import Path
import shlex
import sys

install, source, worktrees = map(Path, sys.argv[1:])
bootstrap = ("import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); "
             "runpy.run_module('app.builderops.openhands_factory', run_name='__main__')")
args = ["env", f"PYTHONPATH={source}", str(install / "venv/bin/python"),
        "-c", bootstrap, str(source), "--install-root", str(install),
        "--state-root", str(install / "runs"), "--worktree-root", str(worktrees)]
entry = install / "bin/openhands"
entry.write_text("#!/bin/sh\nexec " + " ".join(map(shlex.quote, args)) + ' "$@"\n')
entry.chmod(0o755)
PY
printf 'Installed OpenHands components in %s\n' "$factory_dir"
printf 'Owner entry point: %s/bin/openhands\n' "$factory_dir"
printf 'Native Codex: %s\n' "$(codex --version)"
