#!/usr/bin/env bash

# MVR-01B deploy/start producer. The caller supplies its channel-aware compose
# function so the same fenced sequence is used by pinned deploys and local
# full-system starts.
prepare_instance_state_deployment() {
  local compose_function="$1"
  local channel="$2"
  local legacy_path="${DESIGN_HANDOFF_APP_LOCAL_SETTINGS:-/app/tmp/agentic-pkm/app-local.md}"
  local inventory_path="${INSTANCE_LEGACY_OWNER_INVENTORY_PATH:-/app/instance-ownership/legacy-owner-inventory.json}"
  local quiescence_inventory_path="/app/instance-ownership/deployment-quiescence-inventory.json"
  local backup_root="${INSTANCE_STATE_BACKUP_PATH:-/app/instance-ownership/backups/${channel}/latest}"
  local restore_root="${INSTANCE_STATE_RESTORE_PATH:-}"
  local runtime_uid="${LOCAL_UID:-$(id -u)}"
  local runtime_gid="${LOCAL_GID:-$(id -g)}"
  local runtime_user="${runtime_uid}:${runtime_gid}"
  local repo_root inventory_helper controller_pid controller_start_token
  local inventory_host_path owner_inventory_host_path inventory_rc
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  inventory_helper="${repo_root}/scripts/instance_state_writer_inventory.py"
  controller_pid="$$"
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
  finish_args+=(--quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json)

  # Derive and twice-stabilize every canonical dev/test/prod/native owner and
  # stopped-service config source before the init producer, host lease, channel
  # fence, writer stop, or any other deployment mutation. The stopped-window
  # validation below must reproduce this exact private baseline.
  owner_inventory_host_path="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-owners.XXXXXX")"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    return "${inventory_rc}"
  fi
  python3 "${inventory_helper}" produce-legacy-owners \
    --repo-root "${repo_root}" \
    --active-channel "${channel}" \
    --output "${owner_inventory_host_path}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ] || [ ! -s "${owner_inventory_host_path}" ]; then
    rm -f -- "${owner_inventory_host_path}"
    [ "${inventory_rc}" -ne 0 ] && return "${inventory_rc}"
    return 1
  fi

  # The one-shot remains the sole mount-permission producer. It creates no
  # registry or ledger authority; it only makes both mounted roots private for
  # the same uid/gid used by every runtime consumer and the commands below.
  LOCAL_UID="${runtime_uid}" LOCAL_GID="${runtime_gid}" \
    "${compose_function}" run --rm --no-deps -T instance-state-init
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi

  # Resolve the OS start identity before claiming the durable host-global lease.
  controller_start_token="$(python3 "${inventory_helper}" controller-token --pid "${controller_pid}")"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi
  inventory_host_path="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-quiescence.XXXXXX")"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi

  # The fence is durable host-global state. If any later step fails it remains
  # installed and every upgraded consumer preflight refuses to restart.
  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-begin \
      --channel "${channel}" \
      --instance-state-root /app/instance-state \
      --host-global-root /app/instance-ownership \
      --legacy-path "${legacy_path}" \
      --controller-pid "${controller_pid}" \
      --controller-start-token "${controller_start_token}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${inventory_host_path}"
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi

  "${compose_function}" stop api worker watcher heimdal-capture-watch
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${inventory_host_path}"
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi

  # One foreground helper owns both structured Docker and native OS probes.
  # It writes no proof candidate unless two complete snapshots are identical
  # and empty; there is no shell pipeline for the helper to observe as a writer.
  python3 "${inventory_helper}" prove-quiescent \
    --controller-pid "${controller_pid}" \
    --controller-start-token "${controller_start_token}" \
    --output "${inventory_host_path}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${inventory_host_path}"
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi
  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    sh -c "umask 077; cat > '${quiescence_inventory_path}'" < "${inventory_host_path}"
  inventory_rc=$?
  rm -f -- "${inventory_host_path}"
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi

  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-prove \
      --channel "${channel}" \
      --host-global-root /app/instance-ownership \
      --inventory-path "${quiescence_inventory_path}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi

  # Re-read every owner/config producer after all writers are stopped and the
  # lease-bound quiescence proof is durable. Any missing or changed source
  # aborts while the durable fence remains installed; only an exact match may
  # become the drained inventory consumed by finish.
  python3 "${inventory_helper}" validate-legacy-owners \
    --repo-root "${repo_root}" \
    --active-channel "${channel}" \
    --inventory "${owner_inventory_host_path}" \
    --output "${owner_inventory_host_path}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${owner_inventory_host_path}"
    return "${inventory_rc}"
  fi
  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    sh -c "umask 077; cat > '${inventory_path}'" < "${owner_inventory_host_path}"
  inventory_rc=$?
  rm -f -- "${owner_inventory_host_path}"
  if [ "${inventory_rc}" -ne 0 ]; then
    return "${inventory_rc}"
  fi

  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-finish \
      "${finish_args[@]}"
}
