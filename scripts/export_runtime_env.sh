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

# SIGNBOARD_ROOT is resolved by the launcher (start_full_system.sh) and only
# forwarded here. This exporter deliberately runs no `app.*` import of its own:
# the settings-location import below is a fail-loud path, and an extra import
# in front of it would perturb that failure surface (#4198).

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

# #4519 — fail-loud test isolation guard. pytest exports marker variables that
# launcher subprocesses inherit; such a run must never write this repository's
# own tmp/runtime.env or tmp-test/runtime.env, because a leaked test value
# (e.g. VAULT_HOST_ROOT under a deleted pytest tmp_path) survives in operator
# state and blocks every later channel deploy. Refuse loudly instead of
# silently redirecting so the test author sees the missing RUNTIME_ENV_PATH.
# Real operator invocations carry no pytest markers and are unaffected.
if [ -n "${PYTEST_CURRENT_TEST:-}" ] || [ -n "${PYTEST_VERSION:-}" ]; then
  _pytest_guard_target="$runtime_env_path"
  case "$_pytest_guard_target" in
    ./*) _pytest_guard_target="${_pytest_guard_target#./}" ;;
  esac
  case "$_pytest_guard_target" in
    /*) ;;
    *) _pytest_guard_target="$ROOT/$_pytest_guard_target" ;;
  esac
  case "$_pytest_guard_target" in
    "$ROOT/tmp/runtime.env"|"$ROOT/tmp-test/runtime.env")
      echo "export_runtime_env.sh: refusing to write $_pytest_guard_target from a pytest run (#4519)." >&2
      echo "Set RUNTIME_ENV_PATH to a tmp_path-scoped file before invoking the launcher or this exporter from a test." >&2
      exit 3
      ;;
  esac
  unset _pytest_guard_target
fi

runtime_env_dir="$(dirname "$runtime_env_path")"
mkdir -p "$runtime_env_dir"
runtime_env_output_path="$(mktemp "${runtime_env_dir}/.runtime.env.XXXXXX")"
trap 'rm -f "$runtime_env_output_path"' EXIT

publish_runtime_env() {
  mv -f "$runtime_env_output_path" "$runtime_env_path"
  trap - EXIT
}

if [ "${NO_VAULT_MODE:-0}" -eq 1 ]; then
  # Preserve an explicit selector, while retaining the established no-vault
  # idle fallback. Persisting either value keeps a later pinned-image render
  # independent of its caller shell.
  no_vault_llm_provider="${LLM_PROVIDER:-mock}"
  watcher_runtime_env_file="$runtime_env_path"
  case "$watcher_runtime_env_file" in
    /*) ;;
    ./*) ;;
    *) watcher_runtime_env_file="./$watcher_runtime_env_file" ;;
  esac
  cat > "$runtime_env_output_path" <<ENV
WATCHER_RUNTIME_ENV_FILE=$watcher_runtime_env_file
LOCAL_UID=${LOCAL_UID:-$(id -u)}
LOCAL_GID=${LOCAL_GID:-$(id -g)}
LLM_PROVIDER=$no_vault_llm_provider
WATCHER_ENABLE=0
WATCHER_VAULT_PATH=
ENV
  if [ -n "${DATABASE_URL:-}" ]; then
    printf "DATABASE_URL=%s\n" "$DATABASE_URL" >> "$runtime_env_output_path"
    printf "DB_DSN=%s\n" "${DB_DSN:-$DATABASE_URL}" >> "$runtime_env_output_path"
  elif [ -n "${DB_DSN:-}" ]; then
    printf "DATABASE_URL=%s\n" "$DB_DSN" >> "$runtime_env_output_path"
    printf "DB_DSN=%s\n" "$DB_DSN" >> "$runtime_env_output_path"
  fi
  if [ -n "${TTS_ENABLED:-}" ]; then
    printf "TTS_ENABLED=%s\n" "$TTS_ENABLED" >> "$runtime_env_output_path"
  fi
  if [ -n "${TTS_HOST_ROOT:-}" ]; then
    printf "TTS_HOST_ROOT=%s\n" "$TTS_HOST_ROOT" >> "$runtime_env_output_path"
  fi
  if [ -n "${SIGNBOARD_ROOT:-}" ]; then
    printf "SIGNBOARD_ROOT=%s\n" "$SIGNBOARD_ROOT" >> "$runtime_env_output_path"
  fi
  # heimdal-capture-watch is not gated by no-vault/idle mode (#4362): forward
  # the operator's watch-dir/allowlist config here too, same rule as the
  # vault-bound branch below -- only when explicitly set, never defaulted.
  if [ -n "${HEIMDAL_CAPTURE_WATCH_DIR:-}" ]; then
    printf "%s\n" "HEIMDAL_CAPTURE_WATCH_DIR=${HEIMDAL_CAPTURE_WATCH_DIR}" >> "$runtime_env_output_path"
  fi
  if [ -n "${HEIMDAL_RAW_READ_ALLOWLIST:-}" ]; then
    printf "%s\n" "HEIMDAL_RAW_READ_ALLOWLIST=${HEIMDAL_RAW_READ_ALLOWLIST}" >> "$runtime_env_output_path"
  fi
  if [ -n "${HEIMDAL_CAPTURE_INTERVAL_SECONDS:-}" ]; then
    printf "%s\n" "HEIMDAL_CAPTURE_INTERVAL_SECONDS=${HEIMDAL_CAPTURE_INTERVAL_SECONDS}" >> "$runtime_env_output_path"
  fi
  publish_runtime_env
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

# This file is consumed by compose two ways, which need two *different* vault
# paths (issue #2141):
#   1. as the service `env_file:` — its values become the *container* environment
#      read by resolve_vault_root(); that must be the in-container mount path.
#   2. as the CLI `--env-file` (start_full_system.sh, cold_boot.sh,
#      verify_runtime_stack.sh) — used to interpolate the legacy compatibility
#      bind-mount *source* `${VAULT_HOST_ROOT:?...}:/app/vault` in the explicit
#      docker-compose.legacy-vault.yml overlay (#2386); that must be the *host*
#      path, or the wrappers bind a non-existent host dir.
# So emit both: VAULT_HOST_ROOT carries the host path for mount-source
# interpolation; VAULT_ROOT carries the container mount path for the app. The
# provider settings loader below still reads the host path from the shell
# `VAULT_ROOT`. Writing the host path into the container's VAULT_ROOT is what made
# resolve_vault_root() raise VaultRootMisconfiguredError and the API 503.
#
# The container path is the fixed compose mount target (/app/vault in the legacy
# overlay for all three services); it is intentionally not operator-overridable,
# because the app validates VAULT_ROOT exists and a value diverging from the
# fixed mount target would re-introduce the same 503. The base compose no longer
# carries a ./vault fallback, so a no-vault startup omits both vars (above) and
# start_full_system.sh does not include the legacy overlay.
vault_host_root="$VAULT_ROOT"
container_vault_root="/app/vault"

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

cat > "$runtime_env_output_path" <<ENV
WATCHER_RUNTIME_ENV_FILE=$watcher_runtime_env_file
DISPATCHER_HOST_STATE_DIR=${DISPATCHER_HOST_STATE_DIR:-$ROOT/runtime/dispatcher}
VAULT_HOST_ROOT=$vault_host_root
VAULT_ROOT=$container_vault_root
LOCAL_UID=$local_uid
LOCAL_GID=$local_gid
DATABASE_URL=$DATABASE_URL
DB_DSN=$DB_DSN
ENV

if [ -n "${SIGNBOARD_ROOT:-}" ]; then
  printf "SIGNBOARD_ROOT=%s\n" "$SIGNBOARD_ROOT" >> "$runtime_env_output_path"
fi

python3 - <<'PY' >> "$runtime_env_output_path"
from __future__ import annotations

import os
import re
from pathlib import Path

_operator_provider = os.environ.get("LLM_PROVIDER")
if not (_operator_provider or "").strip():
    # Importing app.* enforces the runtime provider contract. This short-lived
    # exporter process must inspect settings before it can derive that value.
    os.environ["LLM_PROVIDER"] = "mock"
from app.settings.locations import LEGACY_COMPILED_DIR, resolve_settings_file

try:
    from app.settings.compiler import compile_file, merge
    from app.settings.models import Providers
except Exception:
    compile_file = None
    merge = None
    Providers = None
finally:
    if _operator_provider is None:
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = _operator_provider


def _load_providers(vault_root: Path) -> object | None:
    path = resolve_settings_file(
        vault_root,
        "providers.md",
        legacy_paths=(LEGACY_COMPILED_DIR / "providers.md",),
    )
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
  printf "%s\n" "WATCHER_AUTO_EXEC=${WATCHER_AUTO_EXEC}" >> "$runtime_env_output_path"
fi

if [ -n "${VAULT_LAYOUT_NOTE_REL:-}" ]; then
  printf "%s\n" "VAULT_LAYOUT_NOTE_REL=${VAULT_LAYOUT_NOTE_REL}" >> "$runtime_env_output_path"
fi

if [ -n "${VAULT_SYSTEM_DIR_REL:-}" ]; then
  printf "%s\n" "VAULT_SYSTEM_DIR_REL=${VAULT_SYSTEM_DIR_REL}" >> "$runtime_env_output_path"
fi

if [ -n "${VAULT_INBOX_DIR_REL:-}" ]; then
  printf "%s\n" "VAULT_INBOX_DIR_REL=${VAULT_INBOX_DIR_REL}" >> "$runtime_env_output_path"
fi

if [ -n "${VAULT_DESK_DIR_REL:-}" ]; then
  printf "%s\n" "VAULT_DESK_DIR_REL=${VAULT_DESK_DIR_REL}" >> "$runtime_env_output_path"
fi

# Forward both machine-local TTS selectors so governed deploy preflight and
# Compose interpolation consume one generated snapshot rather than ambient
# caller-shell state. Loaded from .env / .env.prod.local above (#2189/#4656).
if [ -n "${TTS_ENABLED:-}" ]; then
  printf "%s\n" "TTS_ENABLED=${TTS_ENABLED}" >> "$runtime_env_output_path"
fi
if [ -n "${TTS_HOST_ROOT:-}" ]; then
  printf "%s\n" "TTS_HOST_ROOT=${TTS_HOST_ROOT}" >> "$runtime_env_output_path"
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
  printf "%s\n" "WATCHER_STATE_DIR=tmp-test" >> "$runtime_env_output_path"
  printf "%s\n" "WATCHER_STOP_FILE=/app/tmp-test/WATCHER_STOP" >> "$runtime_env_output_path"
  printf "%s\n" "INDEX_OUTBOX_PATH=/app/tmp-test/index-outbox.jsonl" >> "$runtime_env_output_path"
  printf "%s\n" "WATCHER_HEARTBEAT_PATH=/app/tmp-test/watcher_heartbeat.json" >> "$runtime_env_output_path"
  printf "%s\n" "WORKER_HEARTBEAT_PATH=/app/tmp-test/worker_heartbeat.json" >> "$runtime_env_output_path"
  printf "%s\n" "WATCHER_STATE_PATH=/app/tmp-test/watcher_state.json" >> "$runtime_env_output_path"
  # heimdal-capture-watch has no real capture client on the test channel, and
  # an absent/empty HEIMDAL_CAPTURE_WATCH_DIR is a fail-loud config error
  # (app.heimdal.capture_runtime.CaptureRuntimeConfig.from_env) -- exactly
  # what crash-looped pkm-test-heimdal-capture-watch-1 for 72h+ (#4362).
  # Hardcode a test-scoped folder under the same tmp-test artifact root the
  # other test-channel paths above use, unconditionally, so the service
  # always has somewhere valid to watch (it will simply stay empty).
  printf "%s\n" "HEIMDAL_CAPTURE_WATCH_DIR=/app/tmp-test/heimdal-capture-inbox" >> "$runtime_env_output_path"
else
  if [ -n "${WATCHER_STATE_DIR:-}" ]; then
    printf "%s\n" "WATCHER_STATE_DIR=${WATCHER_STATE_DIR}" >> "$runtime_env_output_path"
  fi

  if [ -n "${WATCHER_STOP_FILE:-}" ]; then
    printf "%s\n" "WATCHER_STOP_FILE=${WATCHER_STOP_FILE}" >> "$runtime_env_output_path"
  fi

  # heimdal-capture-watch's non-secret operator config (#4362): the watched
  # folder and read-allowlist differ per device/channel and have no safe
  # default outside the test channel (an empty/missing watch dir must fail
  # loud, never fall back to a guessed path) -- forward only when the
  # operator actually set them, mirroring WATCHER_STATE_DIR/STOP_FILE above,
  # so the generated runtime env is the one deterministic delivery path for
  # every non-test channel instead of requiring an ad-hoc shell export at
  # compose time. HEIMDAL_RAW_STORE_KEY is deliberately NOT handled here --
  # it is a Keychain-backed secret delivered through the host-secret
  # bootstrap env_file layer, never through this generated file.
  if [ -n "${HEIMDAL_CAPTURE_WATCH_DIR:-}" ]; then
    printf "%s\n" "HEIMDAL_CAPTURE_WATCH_DIR=${HEIMDAL_CAPTURE_WATCH_DIR}" >> "$runtime_env_output_path"
  fi
  if [ -n "${HEIMDAL_RAW_READ_ALLOWLIST:-}" ]; then
    printf "%s\n" "HEIMDAL_RAW_READ_ALLOWLIST=${HEIMDAL_RAW_READ_ALLOWLIST}" >> "$runtime_env_output_path"
  fi
  if [ -n "${HEIMDAL_CAPTURE_INTERVAL_SECONDS:-}" ]; then
    printf "%s\n" "HEIMDAL_CAPTURE_INTERVAL_SECONDS=${HEIMDAL_CAPTURE_INTERVAL_SECONDS}" >> "$runtime_env_output_path"
  fi
fi
unset _is_test_channel

# Only include WATCHER_SCOPE_GLOB if explicitly set by the operator.
# If unset or blank, the watcher computes a vault-wide default at runtime.
scope_glob_raw="${WATCHER_SCOPE_GLOB:-}"
scope_glob_raw="${scope_glob_raw#"${scope_glob_raw%%[![:space:]]*}"}"
scope_glob_raw="${scope_glob_raw%"${scope_glob_raw##*[![:space:]]}"}"
if [ -n "$scope_glob_raw" ]; then
  printf "%s\n" "WATCHER_SCOPE_GLOB=$scope_glob_raw" >> "$runtime_env_output_path"
fi

# OPENAI_BASE is the full chat-completions URL used directly by the adapter and health checks.
# See `.env.example` and `config/runtime.defaults.env` for canonical example values.
# If the operator set it explicitly, write it as-is.
# Otherwise, if OPENAI_BASE_URL is set (OpenAI-compatible base), derive the chat-completions
# URL by stripping a trailing slash and appending /chat/completions.
if [ -n "$operator_openai_base" ]; then
  printf "%s\n" "OPENAI_BASE=${OPENAI_BASE}" >> "$runtime_env_output_path"
else
  _resolved_openai_base_url="${OPENAI_BASE_URL:-}"
  if [ -z "$_resolved_openai_base_url" ]; then
    _resolved_openai_base_url="$(awk -F= '/^OPENAI_BASE_URL=/{print substr($0, index($0,$2)); exit}' "$runtime_env_output_path")"
  fi
  if [ -n "$_resolved_openai_base_url" ] && { [ -n "$operator_openai_base_url" ] || [ -z "${OPENAI_BASE:-}" ]; }; then
    _derived_openai_base="${_resolved_openai_base_url%/}/chat/completions"
    printf "%s\n" "OPENAI_BASE=${_derived_openai_base}" >> "$runtime_env_output_path"
  elif [ -n "${OPENAI_BASE:-}" ]; then
    printf "%s\n" "OPENAI_BASE=${OPENAI_BASE}" >> "$runtime_env_output_path"
  elif [ -n "$_resolved_openai_base_url" ]; then
    _derived_openai_base="${_resolved_openai_base_url%/}/chat/completions"
    printf "%s\n" "OPENAI_BASE=${_derived_openai_base}" >> "$runtime_env_output_path"
  fi
fi

# Propagate OPENAI_API_KEY if set; required by route health checks for the openai provider.
if [ -n "${OPENAI_API_KEY:-}" ]; then
  printf "%s\n" "OPENAI_API_KEY=${OPENAI_API_KEY}" >> "$runtime_env_output_path"
fi

if grep -q '^LLM_PROVIDER=ollama$' "$runtime_env_output_path"; then
  python3 - <<'PY' >> "$runtime_env_output_path"
from __future__ import annotations

import os
from pathlib import Path

_operator_provider = os.environ.get("LLM_PROVIDER")
if not (_operator_provider or "").strip():
    os.environ["LLM_PROVIDER"] = "mock"
from app.settings.locations import LEGACY_COMPILED_DIR, resolve_settings_file

try:
    from app.settings.compiler import compile_file, merge
    from app.settings.models import Providers
except Exception:
    compile_file = None
    merge = None
    Providers = None
finally:
    if _operator_provider is None:
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = _operator_provider


def _strip_v1(url: str) -> str:
    clean = url.rstrip("/")
    if clean.endswith("/v1"):
        return clean[:-3]
    return clean


def _load_providers(vault_root: Path) -> object | None:
    path = resolve_settings_file(
        vault_root,
        "providers.md",
        legacy_paths=(LEGACY_COMPILED_DIR / "providers.md",),
    )
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

publish_runtime_env
