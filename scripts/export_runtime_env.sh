#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

operator_openai_base="${OPENAI_BASE:-}"
operator_openai_base_url="${OPENAI_BASE_URL:-}"
export PKM_EXPORT_OPERATOR_OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-}"
export PKM_EXPORT_OPERATOR_OLLAMA_URL="${OLLAMA_URL:-}"
export PKM_EXPORT_OPERATOR_OLLAMA_HOST="${OLLAMA_HOST:-}"
export PKM_EXPORT_OPERATOR_OPENAI_BASE_URL="${OPENAI_BASE_URL:-}"

source "scripts/lib/load_env_defaults.sh"
load_env_defaults_file ".env"
load_env_defaults_file "config/runtime.defaults.env"

# #2005 — no-vault idle posture: when the runtime boots with no vault bound,
# there is no vault to derive provider/path settings from. Write a minimal
# runtime env (no VAULT_ROOT, watcher disabled) so the stack can come up idle
# and the API serves the picker state. A *set-but-missing* VAULT_ROOT never
# reaches here — start_full_system.sh fails loud at the bind step first.
runtime_env_path="${RUNTIME_ENV_PATH:-}"
if [ -z "$runtime_env_path" ]; then
  case "${COMPOSE_PROJECT_NAME:-}" in
    pkm-test) runtime_env_path="tmp-test/runtime.env" ;;
    *) runtime_env_path="tmp/runtime.env" ;;
  esac
fi
runtime_env_dir="$(dirname "$runtime_env_path")"
mkdir -p "$runtime_env_dir"

if [ "${NO_VAULT_MODE:-0}" -eq 1 ]; then
  watcher_runtime_env_file="$runtime_env_path"
  case "$watcher_runtime_env_file" in
    /*) ;;
    ./*) ;;
    *) watcher_runtime_env_file="./$watcher_runtime_env_file" ;;
  esac
  cat > "$runtime_env_path" <<ENV
WATCHER_RUNTIME_ENV_FILE=$watcher_runtime_env_file
LOCAL_UID=${LOCAL_UID:-$(id -u)}
LOCAL_GID=${LOCAL_GID:-$(id -g)}
WATCHER_ENABLE=0
WATCHER_VAULT_PATH=
ENV
  if [ -n "${DATABASE_URL:-}" ]; then
    printf "DATABASE_URL=%s\n" "$DATABASE_URL" >> "$runtime_env_path"
    printf "DB_DSN=%s\n" "${DB_DSN:-$DATABASE_URL}" >> "$runtime_env_path"
  elif [ -n "${DB_DSN:-}" ]; then
    printf "DATABASE_URL=%s\n" "$DB_DSN" >> "$runtime_env_path"
    printf "DB_DSN=%s\n" "$DB_DSN" >> "$runtime_env_path"
  fi
  echo "Exported no-vault idle runtime env -> $runtime_env_path"
  exit 0
fi

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "VAULT_ROOT is required to export runtime env" >&2
  exit 2
fi

watcher_runtime_env_file="$runtime_env_path"
case "$watcher_runtime_env_file" in
  /*) ;;
  ./*) ;;
  *) watcher_runtime_env_file="./$watcher_runtime_env_file" ;;
esac

local_uid="${LOCAL_UID:-$(id -u)}"
local_gid="${LOCAL_GID:-$(id -g)}"

# Container-facing vault path. This file is consumed by the compose services via
# `env_file:`, so its values become the *container* environment. The host vault
# path (the shell `VAULT_ROOT` exported by start_full_system.sh) is needed only
# for compose to interpolate the bind-mount *source* `${VAULT_ROOT:-./vault}` —
# compose reads that from the shell, never from this file. Writing the host path
# here is what made in-container `resolve_vault_root()` raise
# VaultRootMisconfiguredError and the API 503 (issue #2141). Emit the in-container
# mount path instead; it aligns with WATCHER_VAULT_PATH=/app/vault. The provider
# settings loader below still reads the host `VAULT_ROOT` from the shell env.
container_vault_root="${CONTAINER_VAULT_ROOT:-/app/vault}"

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
VAULT_ROOT=$container_vault_root
LOCAL_UID=$local_uid
LOCAL_GID=$local_gid
DATABASE_URL=$DATABASE_URL
DB_DSN=$DB_DSN
ENV

python3 - <<'PY' >> "$runtime_env_path"
from __future__ import annotations

import os
import re
from pathlib import Path

try:
    from app.settings.compiler import compile_file, merge
    from app.settings.models import Providers
except Exception:
    compile_file = None
    merge = None
    Providers = None


def _load_providers(vault_root: Path) -> object | None:
    path = vault_root / "@Settings" / "providers.md"
    if not path.exists():
        return None
    if compile_file is not None and merge is not None and Providers is not None:
        try:
            sections = compile_file(path)
            payload: dict[str, object] = {}
            for value in sections.values():
                if isinstance(value, dict):
                    merge(payload, value)
            return Providers(**payload)
        except Exception:
            pass
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    m = re.search(r"```yaml settings\s*(.*?)```", text, re.S)
    if not m:
        return None
    block = m.group(1)
    kind = model = base_url = None
    in_default_chat = False
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("default_chat:"):
            in_default_chat = True
            continue
        if not in_default_chat:
            continue
        key, _, value = line.partition(":")
        if not _:
            continue
        value = value.strip().strip('"').strip("'")
        key = key.strip()
        if key == "kind":
            kind = value
        elif key == "model":
            model = value
        elif key == "base_url":
            base_url = value
    if not kind:
        return None
    class _Ref:
        pass
    class _Providers:
        pass
    ref = _Ref()
    ref.kind = kind
    ref.model = model
    ref.base_url = base_url
    p = _Providers()
    p.llm = {"default_chat": ref}
    p.embedding = {}
    return p


providers = _load_providers(Path(os.environ.get("VAULT_ROOT", "vault")))
llm_ref = providers.llm.get("default_chat") if providers else None

env = os.environ

provider = (env.get("LLM_PROVIDER") or "").strip()
if not provider:
    kind = (getattr(llm_ref, "kind", "") or "").strip().lower()
    provider = "openai" if kind in {"openai", "openai_compat"} else kind
if provider:
    print(f"LLM_PROVIDER={provider}")

model = (env.get("LLM_MODEL") or "").strip() or (getattr(llm_ref, "model", None) or "").strip()
if model:
    print(f"LLM_MODEL={model}")

base_url = (env.get("OPENAI_BASE_URL") or "").strip() or (getattr(llm_ref, "base_url", None) or "").strip()
if base_url:
    print(f"OPENAI_BASE_URL={base_url}")
PY

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

# Determine whether we are generating a test-channel env file.
# True when COMPOSE_PROJECT_NAME=pkm-test or the resolved runtime_env_path
# lives under a tmp-test/ directory.
_is_test_channel=0
case "${COMPOSE_PROJECT_NAME:-}" in
  pkm-test) _is_test_channel=1 ;;
esac
if [ "$_is_test_channel" -eq 0 ]; then
  case "$runtime_env_path" in
    *tmp-test/*|*/tmp-test/runtime.env|tmp-test/runtime.env) _is_test_channel=1 ;;
  esac
fi

if [ "$_is_test_channel" -eq 1 ]; then
  # Emit test-channel-scoped artifact path overrides.
  # These unconditionally override the /app/tmp defaults loaded from
  # config/runtime.defaults.env so containers started under pkm-test write
  # to /app/tmp-test/ without any manual post-processing of the generated
  # env file.  The values are hardcoded to the canonical test-channel paths
  # rather than using ${VAR:-fallback} so that defaults already loaded from
  # config/runtime.defaults.env do not shadow the test-scoped values.
  printf "%s\n" "WATCHER_STATE_DIR=tmp-test" >> "$runtime_env_path"
  printf "%s\n" "WATCHER_STOP_FILE=/app/tmp-test/WATCHER_STOP" >> "$runtime_env_path"
  printf "%s\n" "INDEX_OUTBOX_PATH=/app/tmp-test/index-outbox.jsonl" >> "$runtime_env_path"
  printf "%s\n" "WATCHER_HEARTBEAT_PATH=/app/tmp-test/watcher_heartbeat.json" >> "$runtime_env_path"
  printf "%s\n" "WORKER_HEARTBEAT_PATH=/app/tmp-test/worker_heartbeat.json" >> "$runtime_env_path"
  printf "%s\n" "WATCHER_STATE_PATH=/app/tmp-test/watcher_state.json" >> "$runtime_env_path"
else
  if [ -n "${WATCHER_STATE_DIR:-}" ]; then
    printf "%s\n" "WATCHER_STATE_DIR=${WATCHER_STATE_DIR}" >> "$runtime_env_path"
  fi

  if [ -n "${WATCHER_STOP_FILE:-}" ]; then
    printf "%s\n" "WATCHER_STOP_FILE=${WATCHER_STOP_FILE}" >> "$runtime_env_path"
  fi
fi
unset _is_test_channel

# Only include WATCHER_SCOPE_GLOB if explicitly set by the operator.
# If unset or blank, the watcher computes a vault-wide default at runtime.
scope_glob_raw="${WATCHER_SCOPE_GLOB:-}"
scope_glob_raw="${scope_glob_raw#"${scope_glob_raw%%[![:space:]]*}"}"
scope_glob_raw="${scope_glob_raw%"${scope_glob_raw##*[![:space:]]}"}"
if [ -n "$scope_glob_raw" ]; then
  printf "%s\n" "WATCHER_SCOPE_GLOB=$scope_glob_raw" >> "$runtime_env_path"
fi

# OPENAI_BASE is the full chat-completions URL used directly by the adapter and health checks.
# See `.env.example` and `config/runtime.defaults.env` for canonical example values.
# If the operator set it explicitly, write it as-is.
# Otherwise, if OPENAI_BASE_URL is set (OpenAI-compatible base), derive the chat-completions
# URL by stripping a trailing slash and appending /chat/completions.
if [ -n "$operator_openai_base" ]; then
  printf "%s\n" "OPENAI_BASE=${OPENAI_BASE}" >> "$runtime_env_path"
else
  _resolved_openai_base_url="${OPENAI_BASE_URL:-}"
  if [ -z "$_resolved_openai_base_url" ]; then
    _resolved_openai_base_url="$(awk -F= '/^OPENAI_BASE_URL=/{print substr($0, index($0,$2)); exit}' "$runtime_env_path")"
  fi
  if [ -n "$_resolved_openai_base_url" ] && { [ -n "$operator_openai_base_url" ] || [ -z "${OPENAI_BASE:-}" ]; }; then
    _derived_openai_base="${_resolved_openai_base_url%/}/chat/completions"
    printf "%s\n" "OPENAI_BASE=${_derived_openai_base}" >> "$runtime_env_path"
  elif [ -n "${OPENAI_BASE:-}" ]; then
    printf "%s\n" "OPENAI_BASE=${OPENAI_BASE}" >> "$runtime_env_path"
  elif [ -n "$_resolved_openai_base_url" ]; then
    _derived_openai_base="${_resolved_openai_base_url%/}/chat/completions"
    printf "%s\n" "OPENAI_BASE=${_derived_openai_base}" >> "$runtime_env_path"
  fi
fi

# Propagate OPENAI_API_KEY if set; required by route health checks for the openai provider.
if [ -n "${OPENAI_API_KEY:-}" ]; then
  printf "%s\n" "OPENAI_API_KEY=${OPENAI_API_KEY}" >> "$runtime_env_path"
fi

if grep -q '^LLM_PROVIDER=ollama$' "$runtime_env_path"; then
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
    path = vault_root / "@Settings" / "providers.md"
    if not path.exists():
        return None
    if compile_file is not None and merge is not None and Providers is not None:
        try:
            sections = compile_file(path)
            payload: dict[str, object] = {}
            for value in sections.values():
                if isinstance(value, dict):
                    merge(payload, value)
            return Providers(**payload)
        except Exception:
            return None
    return None


vault_root = Path(os.environ.get("VAULT_ROOT", "vault"))
providers = _load_providers(vault_root)
llm_ref = providers.llm.get("default_chat") if providers else None
embed_ref = providers.embedding.get("default") if providers else None

def _operator_env(name: str) -> str | None:
    value = (os.getenv(f"PKM_EXPORT_OPERATOR_{name}") or "").strip()
    return value or None


base_url = (
    _operator_env("OLLAMA_BASE_URL")
    or _operator_env("OLLAMA_URL")
    or _operator_env("OLLAMA_HOST")
    or _operator_env("OPENAI_BASE_URL")
    or os.getenv("OLLAMA_BASE_URL")
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
