#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "scripts/lib/load_env_defaults.sh"
load_env_defaults_file ".env"
load_env_defaults_file "config/runtime.defaults.env"

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "VAULT_ROOT is required to export runtime env" >&2
  exit 2
fi

runtime_env_path="${RUNTIME_ENV_PATH:-}"
if [ -z "$runtime_env_path" ]; then
  case "${COMPOSE_PROJECT_NAME:-}" in
    pkm-test) runtime_env_path="tmp-test/runtime.env" ;;
    *) runtime_env_path="tmp/runtime.env" ;;
  esac
fi
runtime_env_dir="$(dirname "$runtime_env_path")"
mkdir -p "$runtime_env_dir"

watcher_runtime_env_file="$runtime_env_path"
case "$watcher_runtime_env_file" in
  /*) ;;
  ./*) ;;
  *) watcher_runtime_env_file="./$watcher_runtime_env_file" ;;
esac

local_uid="${LOCAL_UID:-$(id -u)}"
local_gid="${LOCAL_GID:-$(id -g)}"

if [ -z "${DATABASE_URL:-}" ] && [ -z "${DB_DSN:-}" ]; then
  echo "DATABASE_URL or DB_DSN is required to export runtime env" >&2
  exit 2
fi
if [ -n "${DATABASE_URL:-}" ] && [ -z "${DB_DSN:-}" ]; then
  DB_DSN="$DATABASE_URL"
fi
if [ -n "${DB_DSN:-}" ] && [ -z "${DATABASE_URL:-}" ]; then
  DATABASE_URL="$DB_DSN"
fi
export DATABASE_URL DB_DSN

cat > "$runtime_env_path" <<ENV
WATCHER_RUNTIME_ENV_FILE=$watcher_runtime_env_file
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

if [ -n "${VAULT_SYSTEM_DIR_REL:-}" ]; then
  printf "%s\n" "VAULT_SYSTEM_DIR_REL=${VAULT_SYSTEM_DIR_REL}" >> "$runtime_env_path"
fi

if [ -n "${VAULT_INBOX_DIR_REL:-}" ]; then
  printf "%s\n" "VAULT_INBOX_DIR_REL=${VAULT_INBOX_DIR_REL}" >> "$runtime_env_path"
fi

if [ -n "${VAULT_DESK_DIR_REL:-}" ]; then
  printf "%s\n" "VAULT_DESK_DIR_REL=${VAULT_DESK_DIR_REL}" >> "$runtime_env_path"
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

# Compatibility shim: when OPENAI_BASE_URL is set for OpenAI-compatible local routing
# and OPENAI_BASE is not explicitly set, derive OPENAI_BASE so that route health checks
# and the adapter (which read OPENAI_BASE) can find the endpoint.
# This is a one-way derivation — it does not override an explicitly set OPENAI_BASE.
if [ -n "${OPENAI_BASE_URL:-}" ] && [ -z "${OPENAI_BASE:-}" ]; then
  printf "%s\n" "OPENAI_BASE=${OPENAI_BASE_URL}" >> "$runtime_env_path"
fi

# Propagate OPENAI_API_KEY if set; required by route health checks for the openai provider.
if [ -n "${OPENAI_API_KEY:-}" ]; then
  printf "%s\n" "OPENAI_API_KEY=${OPENAI_API_KEY}" >> "$runtime_env_path"
fi

if [ "${LLM_PROVIDER:-}" = "ollama" ]; then
  python3 - <<'PY' >> "$runtime_env_path"
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

base_url = (
    os.getenv("OLLAMA_BASE_URL")
    or os.getenv("OLLAMA_URL")
    or os.getenv("OLLAMA_HOST")
    or os.getenv("OPENAI_BASE_URL")
)
if not base_url:
    base_url = getattr(llm_ref, "base_url", None) if llm_ref else None

model = os.getenv("OLLAMA_MODEL") or os.getenv("LLM_MODEL")
if not model:
    model = getattr(llm_ref, "model", None) if llm_ref else None

embed_model = os.getenv("OLLAMA_EMBED_MODEL") or os.getenv("EMBED_MODEL")
if not embed_model:
    embed_model = getattr(embed_ref, "model", None) if embed_ref else None

docker_default_base = os.getenv("DOCKER_OLLAMA_BASE_URL", "").strip()
if not base_url:
    raise SystemExit(
        "OLLAMA_BASE_URL, OLLAMA_URL, OLLAMA_HOST, or OPENAI_BASE_URL is required when LLM_PROVIDER=ollama"
    )
if ("127.0.0.1" in base_url or "localhost" in base_url) and docker_default_base:
    base_url = docker_default_base

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
