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

cat > "$runtime_env_path" <<ENV
VAULT_ROOT=$VAULT_ROOT
LOCAL_UID=$local_uid
LOCAL_GID=$local_gid
ENV
