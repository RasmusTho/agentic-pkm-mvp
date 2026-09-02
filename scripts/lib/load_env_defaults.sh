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

pattern = re.compile(r"^(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=(.*)$")


def compose_env_value(raw_value: str) -> str:
    """Parse the bounded dotenv value forms used by the launcher.

    Compose treats a ``#`` preceded by whitespace as an inline comment in an
    unquoted value. For a quoted value, the quote closes the value first and a
    following ``#`` comment is ignored; ``#`` inside the quotes remains data.
    Existing unquoted values containing spaces are preserved.
    """

    value = raw_value.strip()
    if value[:1] in {"'", '"'}:
        quote = value[0]
        for index in range(1, len(value)):
            if value[index] != quote:
                continue
            suffix = value[index + 1 :].lstrip()
            if not suffix or suffix.startswith("#"):
                return value[1:index]
            break
        return value
    comment = re.search(r"[ \t]+#", value)
    if comment:
        value = value[: comment.start()].rstrip()
    return value


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
