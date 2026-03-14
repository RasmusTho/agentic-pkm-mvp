#!/usr/bin/env bash
set -euo pipefail

load_env_defaults_file() {
  local env_file="${1:-}"
  [ -n "$env_file" ] || return 0
  [ -f "$env_file" ] || return 0

  eval "$(
    python3 - "$env_file" <<'PY'
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
for raw_line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    match = pattern.match(line)
    if not match:
        continue
    key, value = match.groups()
    if key in os.environ:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    print(f"export {key}={shlex.quote(value)}")
PY
  )"
}
