#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "VAULT_ROOT is required to export runtime env" >&2
  exit 2
fi

runtime_env_path="${RUNTIME_ENV_PATH:-tmp/runtime.env}"
runtime_env_dir="$(dirname "$runtime_env_path")"
mkdir -p "$runtime_env_dir"

local_uid="${LOCAL_UID:-$(id -u)}"
local_gid="${LOCAL_GID:-$(id -g)}"

default_db_url="postgresql+psycopg://app:app@db:5432/app"
DATABASE_URL="${DATABASE_URL:-$default_db_url}"
DB_DSN="${DB_DSN:-$DATABASE_URL}"
export DATABASE_URL DB_DSN

cat > "$runtime_env_path" <<ENV
VAULT_ROOT=$VAULT_ROOT
LOCAL_UID=$local_uid
LOCAL_GID=$local_gid
DATABASE_URL=$DATABASE_URL
DB_DSN=$DB_DSN
ENV

if [ -n "${LLM_PROVIDER:-}" ]; then
  printf "%s\n" "LLM_PROVIDER=$LLM_PROVIDER" >> "$runtime_env_path"
fi

if [ -n "${WATCHER_AUTO_EXEC+x}" ]; then
  printf "%s\n" "WATCHER_AUTO_EXEC=${WATCHER_AUTO_EXEC}" >> "$runtime_env_path"
fi

if [ -n "${VAULT_LAYOUT_NOTE_REL:-}" ]; then
  printf "%s\n" "VAULT_LAYOUT_NOTE_REL=${VAULT_LAYOUT_NOTE_REL}" >> "$runtime_env_path"
fi

if [ -n "${WATCHER_STATE_DIR:-}" ]; then
  printf "%s\n" "WATCHER_STATE_DIR=${WATCHER_STATE_DIR}" >> "$runtime_env_path"
fi

if [ -n "${WATCHER_STOP_FILE:-}" ]; then
  printf "%s\n" "WATCHER_STOP_FILE=${WATCHER_STOP_FILE}" >> "$runtime_env_path"
fi

# Only include WATCHER_SCOPE_GLOB if explicitly set by the operator.
# If unset or blank, the watcher computes a vault-wide default at runtime.
scope_glob_raw="${WATCHER_SCOPE_GLOB:-}"
scope_glob_raw="${scope_glob_raw#"${scope_glob_raw%%[![:space:]]*}"}"
scope_glob_raw="${scope_glob_raw%"${scope_glob_raw##*[![:space:]]}"}"
if [ -n "$scope_glob_raw" ]; then
  printf "%s\n" "WATCHER_SCOPE_GLOB=$scope_glob_raw" >> "$runtime_env_path"
fi

if [ "${LLM_PROVIDER:-}" = "ollama" ]; then
  python - <<'PY' >> "$runtime_env_path"
from __future__ import annotations

import os
from pathlib import Path

try:
    from app.settings.compiler import compile_file, merge
    from app.settings.models import Providers
except Exception:
    compile_file = None
    merge = None
    Providers = None


def _strip_v1(url: str) -> str:
    clean = url.rstrip("/")
    if clean.endswith("/v1"):
        return clean[:-3]
    return clean


def _load_providers(vault_root: Path) -> object | None:
    if compile_file is None or merge is None or Providers is None:
        return None
    path = vault_root / "@Settings" / "providers.md"
    if not path.exists():
        return None
    try:
        sections = compile_file(path)
        payload: dict[str, object] = {}
        for value in sections.values():
            if isinstance(value, dict):
                merge(payload, value)
        return Providers(**payload)
    except Exception:
        return None


vault_root = Path(os.environ.get("VAULT_ROOT", "vault"))
providers = _load_providers(vault_root)
llm_ref = providers.llm.get("default_chat") if providers else None
embed_ref = providers.embedding.get("default") if providers else None

base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OPENAI_BASE_URL")
if not base_url:
    base_url = getattr(llm_ref, "base_url", None) if llm_ref else None

model = os.getenv("OLLAMA_MODEL") or os.getenv("LLM_MODEL")
if not model:
    model = getattr(llm_ref, "model", None) if llm_ref else None

embed_model = os.getenv("OLLAMA_EMBED_MODEL") or os.getenv("EMBED_MODEL")
if not embed_model:
    embed_model = getattr(embed_ref, "model", None) if embed_ref else None

default_base = "http://host.docker.internal:11434/v1"
if not base_url:
    base_url = default_base
elif "127.0.0.1" in base_url or "localhost" in base_url:
    base_url = default_base

base_url = base_url.rstrip("/")
ollama_host = _strip_v1(base_url)

if ollama_host:
    print(f"OLLAMA_HOST={ollama_host}")
    print(f"OLLAMA_URL={ollama_host}")
if model:
    print(f"OLLAMA_MODEL={model}")
    print(f"LLM_MODEL={model}")
if embed_model:
    print(f"OLLAMA_EMBED_MODEL={embed_model}")
    print(f"EMBED_MODEL={embed_model}")
PY
fi
