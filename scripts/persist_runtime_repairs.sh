#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

startup_status_path="${STARTUP_STATUS_PATH:-tmp/startup_status.json}"
env_path="${ENV_PATH:-.env}"

python3 - "$startup_status_path" "$env_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])

if not status_path.exists():
    raise SystemExit(f"startup status missing: {status_path}")

payload = json.loads(status_path.read_text(encoding="utf-8"))
effective = str(payload.get("ollama_effective_base_url") or "").strip()
drift = bool(payload.get("ollama_endpoint_drift"))

if not effective:
    raise SystemExit("startup status does not include an effective Ollama endpoint")
if not drift:
    print(f"No runtime repair drift to persist. Current effective endpoint: {effective}")
    raise SystemExit(0)

lines: list[str] = []
if env_path.exists():
    lines = env_path.read_text(encoding="utf-8").splitlines()

updates = {
    "OLLAMA_URL": effective,
    "OLLAMA_HOST": effective,
}

seen: set[str] = set()
for idx, line in enumerate(lines):
    key, sep, _ = line.partition("=")
    if sep and key in updates:
        lines[idx] = f"{key}={updates[key]}"
        seen.add(key)

for key, value in updates.items():
    if key not in seen:
        lines.append(f"{key}={value}")

env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Persisted Ollama runtime repair to {env_path}: {effective}")
PY
