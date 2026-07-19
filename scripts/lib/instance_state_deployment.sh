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

  # Probe every Compose domain and native launchers twice after the local
  # project stops.  A changed snapshot or any surviving writer is unsafe: the
  # finalizer must never infer host-wide quiescence from this caller's channel.
  local first_probe second_probe inventory_json native_pattern controller_pid
  # Match launcher scripts, rather than arbitrary command lines containing their
  # names (for example a pytest node path), and never count this controller.
  native_pattern='(^|/)(start_full_system|deploy_channel)\.sh([[:space:]]|$)|uvicorn|celery|watch'
  controller_pid="$$"
  first_probe="$(docker ps --format '{{.Label "com.docker.compose.project"}} {{.Names}}'; pgrep -af "${native_pattern}" | awk -v controller_pid="${controller_pid}" '$1 != controller_pid' || true)"
  second_probe="$(docker ps --format '{{.Label "com.docker.compose.project"}} {{.Names}}'; pgrep -af "${native_pattern}" | awk -v controller_pid="${controller_pid}" '$1 != controller_pid' || true)"
  inventory_json="$(python3 - "${first_probe}" "${second_probe}" <<'PY'
import json
import sys

def domains(snapshot):
    result = {name: [] for name in ("dev", "test", "prod", "native")}
    for line in snapshot.splitlines():
        lower = line.lower()
        if "pkm-dev" in lower:
            result["dev"].append(line)
        elif "pkm-test" in lower:
            result["test"].append(line)
        elif "pkm-prod" in lower:
            result["prod"].append(line)
        elif line.strip():
            result["native"].append(line)
    return result

first, second = domains(sys.argv[1]), domains(sys.argv[2])
if first != second or any(first.values()):
    raise SystemExit("host-wide writer inventory is live or racing")
print(json.dumps({
    "schema": "agentic-pkm.host-deployment-quiescence.v1",
    "inventory_complete": True,
    "probe_count": 2,
    "all_consumers_stopped": True,
    "domains": first,
}, sort_keys=True))
PY
)" || return $?
  printf '%s\n' "${inventory_json}" | "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    sh -c "umask 077; cat > '${quiescence_inventory_path}'" || return $?

  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-prove \
      --channel "${channel}" \
      --host-global-root /app/instance-ownership \
      --inventory-path "${quiescence_inventory_path}" || return $?

  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-finish \
      "${finish_args[@]}"
}
