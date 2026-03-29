#!/usr/bin/env bash
set -euo pipefail

normalize_ollama_base_url() {
  local raw="${1:-}"
  python3 - "$raw" <<'PY'
from __future__ import annotations

import sys

raw = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
if not raw:
    print("")
    raise SystemExit(0)
clean = raw.rstrip("/")
if clean.endswith("/v1"):
    clean = clean[:-3]
print(clean)
PY
}

upsert_runtime_env_value() {
  local file_path="${1:?file path required}"
  local key="${2:?key required}"
  local value="${3:-}"
  python3 - "$file_path" "$key" "$value" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]

lines: list[str] = []
if path.exists():
    lines = path.read_text(encoding="utf-8").splitlines()

needle = f"{key}="
updated = False
for idx, line in enumerate(lines):
    if line.startswith(needle):
        lines[idx] = f"{key}={value}"
        updated = True
        break

if not updated:
    lines.append(f"{key}={value}")

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

probe_ollama_candidates_in_api_container() {
  local container_id="${1:?container id required}"
  local model="${2:?model required}"
  shift 2
  local candidates_raw
  candidates_raw=$(printf '%s\n' "$@")
  docker exec -i "$container_id" env OLLAMA_CANDIDATES="$candidates_raw" OLLAMA_PROBE_MODEL="$model" python - <<'PY'
from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx


def normalize(url: str) -> str:
    clean = (url or "").strip().rstrip("/")
    if clean.endswith("/v1"):
        clean = clean[:-3]
    return clean


def extract_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or err.get("error")
        else:
            detail = err or payload.get("message")
    else:
        detail = None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    text = response.text.strip()
    return text or None


def extract_embedding(payload: dict[str, Any]) -> list[float] | None:
    value = payload.get("embeddings") or payload.get("embedding")
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, list):
            return first
        if isinstance(first, (int, float)):
            return value
    return None


seen: set[str] = set()
candidates: list[str] = []
for raw in os.environ.get("OLLAMA_CANDIDATES", "").splitlines():
    candidate = normalize(raw)
    if candidate and candidate not in seen:
        seen.add(candidate)
        candidates.append(candidate)

model = (os.environ.get("OLLAMA_PROBE_MODEL") or "").strip() or "nomic-embed-text:latest"
results: list[dict[str, Any]] = []

with httpx.Client(timeout=10.0) as client:
    for candidate in candidates:
        result: dict[str, Any] = {"candidate": candidate, "ok": False}
        try:
            tags = client.get(f"{candidate}/api/tags")
            if tags.is_error:
                result["error"] = f"/api/tags http {tags.status_code}"
                detail = extract_error_detail(tags)
                if detail:
                    result["error"] = f"{result['error']}: {detail}"
                results.append(result)
                continue

            embed = client.post(
                f"{candidate}/api/embeddings",
                json={"model": model, "prompt": "startup-check"},
            )
            if embed.is_error:
                result["error"] = f"/api/embeddings http {embed.status_code}"
                detail = extract_error_detail(embed)
                if detail:
                    result["error"] = f"{result['error']}: {detail}"
                results.append(result)
                continue

            payload = embed.json() if embed.headers.get("Content-Type", "").startswith("application/json") else {}
            embedding = extract_embedding(payload) if isinstance(payload, dict) else None
            if not embedding:
                result["error"] = "embeddings payload missing vectors"
                results.append(result)
                continue

            result["ok"] = True
            result["embed_dim"] = len(embedding)
            results.append(result)
            print(json.dumps({"ok": True, "chosen_base": candidate, "results": results}, ensure_ascii=False))
            raise SystemExit(0)
        except httpx.HTTPError as exc:
            result["error"] = str(exc)
            results.append(result)

print(json.dumps({"ok": False, "results": results}, ensure_ascii=False))
sys.exit(1)
PY
}

auto_resolve_ollama_runtime_endpoint() {
  local runtime_env_path="${1:?runtime env path required}"
  local api_container_id="${2:?api container id required}"
  local model="${OLLAMA_EMBED_MODEL:-${EMBED_MODEL:-nomic-embed-text:latest}}"
  local configured_candidate="${OLLAMA_BASE_URL:-${OLLAMA_URL:-${OLLAMA_HOST:-${OPENAI_BASE_URL:-}}}}"
  local current_base=""
  local probe_json=""
  local chosen_base=""
  local changed="0"
  local -a candidates=()

  if [ -n "$configured_candidate" ]; then
    candidates+=("$configured_candidate")
  fi
  if [ -n "${DOCKER_OLLAMA_BASE_URL:-}" ]; then
    candidates+=("${DOCKER_OLLAMA_BASE_URL}")
  fi
  candidates+=("http://host.docker.internal:11434" "http://ollama:11434")

  probe_json=$(probe_ollama_candidates_in_api_container "$api_container_id" "$model" "${candidates[@]}")
  chosen_base=$(OLLAMA_PROBE_JSON="$probe_json" python3 - <<'PY'
from __future__ import annotations

import json
import os

payload = json.loads(os.environ.get("OLLAMA_PROBE_JSON", "{}"))
print(payload.get("chosen_base") or "")
PY
)
  if [ -z "$chosen_base" ]; then
    echo "ERROR: could not find a reachable Ollama endpoint from inside the api container" >&2
    echo "$probe_json" >&2
    return 1
  fi

  current_base=$(normalize_ollama_base_url "$configured_candidate")
  if [ "$chosen_base" != "$current_base" ]; then
    upsert_runtime_env_value "$runtime_env_path" "OLLAMA_URL" "$chosen_base"
    upsert_runtime_env_value "$runtime_env_path" "OLLAMA_HOST" "$chosen_base"
    changed="1"
  fi

  echo "$probe_json"
  return 0
}
