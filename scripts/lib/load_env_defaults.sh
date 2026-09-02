#!/usr/bin/env bash
set -euo pipefail

load_env_defaults_file() {
  local env_file="${1:-}"
  local parser_path
  [ -n "$env_file" ] || return 0
  [ -f "$env_file" ] || return 0
  parser_path="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/compose_env.py"

  eval "$(
    python3 - "$env_file" "$parser_path" <<'PY'
from __future__ import annotations

import importlib.util
import os
import re
import shlex
from pathlib import Path
import sys

parser_path = Path(sys.argv[2])
if parser_path.is_file():
    spec = importlib.util.spec_from_file_location("compose_env", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Compose parser helper could not be loaded")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    compose_env_value = parser.compose_env_value
else:
    # Synthetic launcher fixtures may copy this standalone library without the
    # sibling helper; keep the bounded parser entrypoint-safe and equivalent.
    def _decode_double_quoted(value: str) -> str:
        decoded: list[str] = []
        escaped = False
        for character in value:
            if escaped:
                if character in {'"', "\\"}:
                    decoded.append(character)
                else:
                    decoded.extend(("\\", character))
                escaped = False
            elif character == "\\":
                escaped = True
            else:
                decoded.append(character)
        if escaped:
            decoded.append("\\")
        return "".join(decoded)

    def compose_env_value(raw_value: str) -> str:
        value = raw_value.strip()
        if value[:1] in {"'", '"'}:
            quote = value[0]
            escaped = False
            for index in range(1, len(value)):
                character = value[index]
                if quote == '"' and escaped:
                    escaped = False
                    continue
                if quote == '"' and character == "\\":
                    escaped = True
                    continue
                if character != quote:
                    continue
                suffix = value[index + 1 :].lstrip()
                if not suffix or suffix.startswith("#"):
                    quoted = value[1:index]
                    return _decode_double_quoted(quoted) if quote == '"' else quoted
                break
            return value
        comment = re.search(r"[ \t]+#", value)
        if comment:
            value = value[: comment.start()].rstrip()
        return value

pattern = re.compile(r"^(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=(.*)$")


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
    value = compose_env_value(value)
    print(f"export {key}={shlex.quote(value)}")
PY
  )"
}
