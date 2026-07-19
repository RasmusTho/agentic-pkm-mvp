#!/usr/bin/env bash
set -euo pipefail

_deploy_channel_compose_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_deploy_channel_compose_lib_dir}/instance_ownership_host_state.sh"
unset _deploy_channel_compose_lib_dir

_deploy_channel_env_value() {
  local file_path="${1:?env file required}"
  local key="${2:?env key required}"
  [ -f "${file_path}" ] || return 0
  awk -v key="${key}" '
    index($0, key "=") == 1 {
      print substr($0, length(key) + 2)
      exit
    }
  ' "${file_path}"
}

_deploy_channel_uses_full_host_vault_path() {
  local vault_path="${1:?vault path required}"
  python3 - "${vault_path}" <<'PY'
import os
import sys

selector = sys.argv[1]
roots = ("/Users", "/Volumes")


def under_full_host_root(path: str) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in roots)


# The container receives the selector string, not its host-side realpath. Both
# views must stay under a same-path mount: this rejects relative selectors,
# outside symlinks into /Users, and /Users symlinks that escape the mounts.
lexical_path = os.path.normpath(selector) if os.path.isabs(selector) else ""
resolved_path = os.path.realpath(selector)
raise SystemExit(
    0
    if under_full_host_root(lexical_path) and under_full_host_root(resolved_path)
    else 1
)
PY
}

deploy_channel_compose() {
  local root="${1:?repo root required}"
  local channel="${2:?channel required}"
  local compose_overlay="${3:?channel compose overlay required}"
  local compose_project="${4:?compose project required}"
  local channel_env_file="${5:?channel env file required}"
  shift 5

  resolve_instance_ownership_host_state_dir || return $?

  local runtime_env_ref runtime_env_file vault_host_root vault_container_root
  local -a compose_args
  compose_args=(-f "${root}/docker-compose.yaml" -f "${root}/${compose_overlay}")

  # Resolve the governed runtime env file path. It is used below ONLY to read
  # VAULT_HOST_ROOT for the overlay decision and to pin WATCHER_RUNTIME_ENV_FILE
  # for the service `env_file:` layer. It is NEVER passed to Compose as a CLI
  # `--env-file`: that would expose its DSNs and other values to Compose
  # interpolation (#3875 — a previous dead `env_args` block here looked like it
  # did exactly that; do not reintroduce it).
  runtime_env_ref="$(_deploy_channel_env_value "${channel_env_file}" WATCHER_RUNTIME_ENV_FILE)"
  runtime_env_file=""
  if [ -n "${runtime_env_ref}" ]; then
    case "${runtime_env_ref}" in
      /*) runtime_env_file="${runtime_env_ref}" ;;
      ./*) runtime_env_file="${root}/${runtime_env_ref#./}" ;;
      *) runtime_env_file="${root}/${runtime_env_ref}" ;;
    esac
  fi

  vault_host_root="$(_deploy_channel_env_value "${channel_env_file}" VAULT_HOST_ROOT)"
  if [ -z "${vault_host_root}" ] && [ -n "${runtime_env_file}" ] && [ -f "${runtime_env_file}" ]; then
    vault_host_root="$(_deploy_channel_env_value "${runtime_env_file}" VAULT_HOST_ROOT)"
  fi

  vault_container_root=""
  if [ -n "${vault_host_root}" ]; then
    if _deploy_channel_uses_full_host_vault_path "${vault_host_root}"; then
      vault_container_root="${vault_host_root}"
      compose_args+=(-f "${root}/docker-compose.full-host-vault.yml")
    else
      vault_container_root="/app/vault"
      compose_args+=(-f "${root}/docker-compose.legacy-vault.yml")
    fi
    if [ "${channel}" = "test" ]; then
      compose_args+=(-f "${root}/docker-compose.test-vault.yml")
    fi
  fi

  (
    cd "${root}" || exit 1

    # Compose gives the caller shell precedence over --env-file values. Pin the
    # two governed selectors here so a stale parent shell cannot swap the
    # selected runtime env or vault after the overlay decision above. The
    # runtime env itself stays a service env_file; passing it as a CLI
    # --env-file would expose its DSNs and other values to Compose interpolation.
    if [ -n "${runtime_env_ref}" ]; then
      export WATCHER_RUNTIME_ENV_FILE="${runtime_env_ref}"
    else
      unset WATCHER_RUNTIME_ENV_FILE
    fi
    if [ -n "${vault_host_root}" ]; then
      export VAULT_HOST_ROOT="${vault_host_root}"
      export DEPLOY_VAULT_CONTAINER_ROOT="${vault_container_root}"
    else
      unset VAULT_HOST_ROOT
      unset DEPLOY_VAULT_CONTAINER_ROOT
    fi

    docker compose \
      --env-file "${channel_env_file}" \
      "${compose_args[@]}" \
      -p "${compose_project}" \
      "$@"
  )
}
