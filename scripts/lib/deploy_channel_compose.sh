#!/usr/bin/env bash
set -euo pipefail

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

deploy_channel_compose() {
  local root="${1:?repo root required}"
  local channel="${2:?channel required}"
  local compose_overlay="${3:?channel compose overlay required}"
  local compose_project="${4:?compose project required}"
  local channel_env_file="${5:?channel env file required}"
  shift 5

  local runtime_env_ref runtime_env_file vault_host_root
  local -a compose_args
  compose_args=(-f "${root}/docker-compose.yaml" -f "${root}/${compose_overlay}")

  runtime_env_ref="$(_deploy_channel_env_value "${channel_env_file}" WATCHER_RUNTIME_ENV_FILE)"
  runtime_env_file=""
  if [ -n "${runtime_env_ref}" ]; then
    case "${runtime_env_ref}" in
      /*) runtime_env_file="${runtime_env_ref}" ;;
      ./*) runtime_env_file="${root}/${runtime_env_ref#./}" ;;
      *) runtime_env_file="${root}/${runtime_env_ref}" ;;
    esac
    if [ -f "${runtime_env_file}" ]; then
      env_args+=(--env-file "${runtime_env_file}")
    fi
  fi

  vault_host_root="$(_deploy_channel_env_value "${channel_env_file}" VAULT_HOST_ROOT)"
  if [ -z "${vault_host_root}" ] && [ -n "${runtime_env_file}" ] && [ -f "${runtime_env_file}" ]; then
    vault_host_root="$(_deploy_channel_env_value "${runtime_env_file}" VAULT_HOST_ROOT)"
  fi

  if [ -n "${vault_host_root}" ]; then
    compose_args+=(-f "${root}/docker-compose.legacy-vault.yml")
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
    else
      unset VAULT_HOST_ROOT
    fi

    docker compose \
      --env-file "${channel_env_file}" \
      "${compose_args[@]}" \
      -p "${compose_project}" \
      "$@"
  )
}
