#!/usr/bin/env bash

# MVR-01B deploy/start producer. The caller supplies its channel-aware compose
# function so the same fenced sequence is used by pinned deploys and local
# full-system starts.
prepare_instance_state_deployment() {
  local compose_function="$1"
  local channel="$2"
  local legacy_path="${DESIGN_HANDOFF_APP_LOCAL_SETTINGS:-/app/tmp/agentic-pkm/app-local.md}"
  local inventory_path="${INSTANCE_LEGACY_OWNER_INVENTORY_PATH:-/app/instance-ownership/legacy-owner-inventory.json}"
  local backup_root="${INSTANCE_STATE_BACKUP_PATH:-/app/instance-ownership/backups/${channel}/latest}"
  local restore_root="${INSTANCE_STATE_RESTORE_PATH:-}"
  local runtime_uid="${LOCAL_UID:-$(id -u)}"
  local runtime_gid="${LOCAL_GID:-$(id -g)}"
  local runtime_user="${runtime_uid}:${runtime_gid}"
  local -a finish_args=(
    --channel "${channel}"
    --instance-state-root /app/instance-state
    --host-global-root /app/instance-ownership
    --legacy-path "${legacy_path}"
    --inventory-path "${inventory_path}"
    --backup-root "${backup_root}"
  )
  if [ -n "${restore_root}" ]; then
    finish_args+=(--restore-root "${restore_root}")
  fi
  finish_args+=(--writers-drained --old-api-stopped)

  # The one-shot remains the sole mount-permission producer. It creates no
  # registry or ledger authority; it only makes both mounted roots private for
  # the same uid/gid used by every runtime consumer and the commands below.
  LOCAL_UID="${runtime_uid}" LOCAL_GID="${runtime_gid}" \
    "${compose_function}" run --rm --no-deps -T instance-state-init || return $?

  # The fence is durable host-global state. If any later step fails it remains
  # installed and every upgraded consumer preflight refuses to restart.
  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-begin \
      --channel "${channel}" \
      --instance-state-root /app/instance-state \
      --host-global-root /app/instance-ownership \
      --legacy-path "${legacy_path}" || return $?

  "${compose_function}" stop api worker watcher heimdal-capture-watch || return $?

  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-finish \
      "${finish_args[@]}"
}
