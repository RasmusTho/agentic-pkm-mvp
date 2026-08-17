#!/usr/bin/env bash

_instance_state_deployment_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_instance_state_deployment_lib_dir}/instance_ownership_host_state.sh"
unset _instance_state_deployment_lib_dir

# Best-effort self-release of the host-global deployment lease this producer
# claimed when it began. Called only on a failure path after that successful
# claim and before a successful finalization, so an abandoned deployment does
# not strand the lease, the public lease copy, and the channel restart fence
# that block every later runtime consumer and deploy attempt. The release is
# self-scoped: it only ever clears a lease whose recorded channel and
# controller identity match the ones passed here, so it can never disturb a
# lease still owned by another deployment. Its own failure is logged and
# swallowed; the caller's original failure is always the reported outcome.
_release_abandoned_instance_state_deployment_lease() {
  local compose_function="$1"
  local channel="$2"
  local runtime_user="$3"
  local controller_pid="$4"
  local controller_start_token="$5"
  if [ -z "${controller_start_token}" ]; then
    return 0
  fi
  if ! "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-release \
      --channel "${channel}" \
      --host-global-root /app/instance-ownership \
      --controller-pid "${controller_pid}" \
      --controller-start-token "${controller_start_token}"; then
    echo "warning: failed to release the abandoned host-global deployment lease" >&2
  fi
}

# Deliver a privately-owned copy of a locally-produced JSON inventory directly
# onto the host-global directory that is bind-mounted at /app/instance-ownership
# inside every instance-ownership consumer, instead of round-tripping the
# content through a `docker compose run ... < file` pipe (#4536). That pipe's
# stdin is the same command-invocation stdin `deploy_channel_compose` used for
# its own SIGNBOARD_ROOT override document, so both a caller-supplied pipe and
# the wrapper's own override document needed sole ownership of it at once and
# the pipe always lost. Writing straight to the bind-mounted host path removes
# that shared dependency for these two producer deliveries entirely.
_instance_state_deployment_deliver_private_inventory() {
  local source_path="${1:?source path required}"
  local host_target_path="${2:?host target path required}"
  local uid="${3:?uid required}"
  local gid="${4:?gid required}"
  if [ ! -s "${source_path}" ]; then
    echo "instance state deployment: refusing to deliver an empty or missing inventory (${source_path})" >&2
    return 1
  fi
  ( umask 077 && cat -- "${source_path}" > "${host_target_path}" ) || return $?
  chmod 0600 "${host_target_path}" || return $?
  chown "${uid}:${gid}" "${host_target_path}" || return $?
  if [ ! -s "${host_target_path}" ]; then
    echo "instance state deployment: delivered inventory is empty (${host_target_path})" >&2
    return 1
  fi
}

# Map a /app/instance-ownership/... container path to its host-side bind-mount
# equivalent under INSTANCE_OWNERSHIP_HOST_STATE_DIR. Only container paths
# under that mount can be delivered directly; anything else is a
# misconfiguration this producer does not support.
_instance_state_deployment_host_ownership_path() {
  local container_path="${1:?container path required}"
  case "${container_path}" in
    /app/instance-ownership/*)
      printf '%s/%s\n' "${INSTANCE_OWNERSHIP_HOST_STATE_DIR}" "${container_path#/app/instance-ownership/}"
      ;;
    *)
      return 1
      ;;
  esac
}

# The SETTINGS runtime floor crosses two durable stores.  The host receipt is
# therefore authority, not telemetry: each replacement fsyncs its content and
# then the containing directory before either protected-store commit can rely
# on it.  A failed installed replacement deliberately leaves a durable pending
# receipt, which fences an old image until an idempotent deployment reconciles.
_write_settings_rebind_floor_receipt() {
  local channel="${1:?channel required}"
  local phase="${2:?phase required}"
  python3 - "${INSTANCE_OWNERSHIP_HOST_STATE_DIR}" "${channel}" "${phase}" <<'PY'
import json
import os
import sys
import tempfile

root, channel, phase = sys.argv[1:]
if phase not in {"pending", "installed"}:
    raise SystemExit("invalid settings rebind floor receipt phase")
name = f"settings-rebind-runtime-floor-{channel}.json"
path = os.path.join(root, name)
fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=root)
try:
    os.fchmod(fd, 0o600)
    payload = json.dumps(
        {"schema": "settings-rebind-floor-receipt.v1", "channel": channel, "phase": phase},
        separators=(",", ":"),
    ).encode() + b"\n"
    os.write(fd, payload)
    os.fsync(fd)
    os.close(fd)
    fd = -1
    os.replace(temporary, path)
    directory = os.open(root, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
finally:
    if fd >= 0:
        os.close(fd)
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

# Explicit operator recovery for exactly one missing active ownership lease.
# This is deliberately not called by deploy/start: the failed deployment must
# already have left its host-global restart fence and proved quiescence in
# place, and the operator must name the existing binding. No JSON file is
# edited by this path and it never starts a writer.
recover_lost_instance_state_lease() {
  local compose_function="$1"
  local channel="$2"
  local binding_id="${INSTANCE_LOST_LEASE_BINDING_ID:-}"
  local backup_root="${INSTANCE_STATE_RECOVERY_BACKUP_PATH:-/app/instance-ownership/backups/${channel}/lost-lease-recovery}"
  if [ -z "${binding_id}" ]; then
    echo "instance state recovery: INSTANCE_LOST_LEASE_BINDING_ID is required" >&2
    return 78
  fi
  "${compose_function}" run --rm --no-deps -T instance-state-init \
    python -m app.instance.runtime deployment-recover-lost-lease \
      --channel "${channel}" \
      --instance-state-root /app/instance-state \
      --host-global-root /app/instance-ownership \
      --backup-root "${backup_root}" \
      --quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json \
      --owner-receipt-path /app/instance-ownership/legacy-owner-inventory.json \
      --vault-binding-id "${binding_id}"
}

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
  local quiescence_inventory_host_target_path owner_inventory_host_target_path
  local principal_attempt_id principal_receipt_path principal_receipt_host_path
  local receipt_verify_rc
  local native_producer
  local principal_loopback_flag=""
  local mvr05_stop_services
  local -a mvr05_stop_service_args
  local mvr05_effective_compose_path mvr05_fence_plan_host_path
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  inventory_helper="${repo_root}/scripts/instance_state_writer_inventory.py"
  controller_pid="$$"

  # The principal floor is an irreversible compatibility boundary, so merely
  # deploying a capable image never activates it. Validate the complete opt-in
  # and channel topology declaration before init, lease acquisition, or writer
  # stop; error receipts name variables/boolean state only, never env values.
  case "${MVR03_PRINCIPAL_CUTOVER:-0}" in
    0) ;;
    1)
      case "${MVR03_PRINCIPAL_LOOPBACK_LISTENER:-}" in
        0) ;;
        1) principal_loopback_flag="--loopback-listener" ;;
        *)
          echo "instance state deployment: MVR03_PRINCIPAL_LOOPBACK_LISTENER must be an explicit boolean" >&2
          return 78
          ;;
      esac
      for native_producer in \
        scripts/deploy_channel.sh \
        scripts/start_full_system.sh \
        scripts/export_runtime_env.sh; do
        if [ ! -f "${repo_root}/${native_producer}" ]; then
          echo "instance state deployment: a declared principal native producer is missing" >&2
          return 78
        fi
      done
      ;;
    *)
      echo "instance state deployment: MVR03_PRINCIPAL_CUTOVER must be a boolean" >&2
      return 78
      ;;
  esac

  # The host-global state dir is resolved and prepared by the caller before
  # this producer runs (deploy_channel.sh calls prepare_instance_ownership_host_state_dir
  # ahead of prepare_instance_state_deployment); re-deriving it here would add
  # a second, unnecessary python3 dependency to this pure-delivery step.
  if [ -z "${INSTANCE_OWNERSHIP_HOST_STATE_DIR:-}" ]; then
    echo "instance state deployment: INSTANCE_OWNERSHIP_HOST_STATE_DIR must be resolved before prepare_instance_state_deployment runs" >&2
    return 78
  fi
  quiescence_inventory_host_target_path="$(
    _instance_state_deployment_host_ownership_path "${quiescence_inventory_path}"
  )" || {
    echo "instance state deployment: quiescence inventory path must live under /app/instance-ownership" >&2
    return 78
  }
  owner_inventory_host_target_path="$(
    _instance_state_deployment_host_ownership_path "${inventory_path}"
  )" || {
    echo "instance state deployment: legacy-owner inventory path must live under /app/instance-ownership" >&2
    return 78
  }
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

  mvr05_effective_compose_path="$(mktemp "${TMPDIR:-/tmp}/mvr05-effective-compose.XXXXXX")"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi
  chmod 600 "${mvr05_effective_compose_path}"
  mvr05_raw_compose_path="$(mktemp "${TMPDIR:-/tmp}/mvr05-raw-compose.XXXXXX")"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${mvr05_effective_compose_path}"
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi
  chmod 600 "${mvr05_raw_compose_path}"
  DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT="${mvr05_effective_compose_path}" \
    "${compose_function}" config --no-interpolate --no-env-resolution \
    > "${mvr05_raw_compose_path}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${mvr05_effective_compose_path}"
    rm -f -- "${mvr05_raw_compose_path}"
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi
  if [ ! -s "${mvr05_effective_compose_path}" ]; then
    python3 "${inventory_helper}" redact-compose-fence-config \
      --compose-path "${mvr05_raw_compose_path}" \
      --output "${mvr05_effective_compose_path}"
    inventory_rc=$?
  elif [ -s "${mvr05_raw_compose_path}" ]; then
    inventory_rc=92
  fi
  rm -f -- "${mvr05_raw_compose_path}"
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${mvr05_effective_compose_path}"
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi
  mvr05_fence_plan_host_path="${INSTANCE_OWNERSHIP_HOST_STATE_DIR}/mvr05-fence-plan-${controller_pid}.json"
  rm -f -- "${mvr05_fence_plan_host_path}"
  mvr05_stop_services="$(
    python3 "${inventory_helper}" compose-fence-plan \
      --compose-path "${mvr05_effective_compose_path}" \
      --receipt-output "${mvr05_fence_plan_host_path}"
  )"
  inventory_rc=$?
  rm -f -- "${mvr05_effective_compose_path}"
  if [ "${inventory_rc}" -ne 0 ] || [ -z "${mvr05_stop_services}" ]; then
    rm -f -- "${inventory_host_path}"
    rm -f -- "${owner_inventory_host_path}"
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    [ "${inventory_rc}" -ne 0 ] && return "${inventory_rc}"
    return 1
  fi
  read -r -a mvr05_stop_service_args <<< "${mvr05_stop_services}"
  "${compose_function}" stop "${mvr05_stop_service_args[@]}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${inventory_host_path}"
    rm -f -- "${owner_inventory_host_path}"
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi

  # The service-name fence is paired with a database-side assertion: no old
  # image, host process, or unclassified client may retain a live PostgreSQL
  # session when the irreversible floor is recorded. Require two consecutive
  # empty snapshots to avoid accepting a transient healthcheck gap.
  "${compose_function}" exec -T db sh -ec '
    consecutive=0
    attempts=0
    while [ "$attempts" -lt 20 ]; do
      count="$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select count(*) from pg_stat_activity where pid <> pg_backend_pid() and datname = current_database() and backend_type = '\''client backend'\''")"
      if [ "$count" = 0 ]; then consecutive=$((consecutive + 1)); else consecutive=0; fi
      [ "$consecutive" -ge 2 ] && exit 0
      attempts=$((attempts + 1))
      sleep 0.1
    done
    echo "MVR-05 database session fence did not drain" >&2
    exit 75
  '
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${mvr05_fence_plan_host_path}"
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
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
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi
  _instance_state_deployment_deliver_private_inventory \
    "${inventory_host_path}" "${quiescence_inventory_host_target_path}" \
    "${runtime_uid}" "${runtime_gid}"
  inventory_rc=$?
  rm -f -- "${inventory_host_path}"
  if [ "${inventory_rc}" -ne 0 ]; then
    rm -f -- "${owner_inventory_host_path}"
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
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
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi

  # Install pending authority after the proved stopped window and before either
  # protected-store commit; replaying this idempotent deployment reconciles it.
  _write_settings_rebind_floor_receipt "${channel}" pending || return $?

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
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi
  _instance_state_deployment_deliver_private_inventory \
    "${owner_inventory_host_path}" "${owner_inventory_host_target_path}" \
    "${runtime_uid}" "${runtime_gid}"
  inventory_rc=$?
  rm -f -- "${owner_inventory_host_path}"
  if [ "${inventory_rc}" -ne 0 ]; then
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi

  # Explicit MVR-03 authority transition. One runtime process records the floor
  # and then bootstraps the role, keeping the attempt-local floor receipt out of
  # caller-controlled flags. It consumes MVR-01B's proved lease, quiescence proof,
  # and drained owner inventory; it never adds a second drain/probe mechanism.
  # Before any role record commits, a bootstrap failure compensates only a floor
  # advanced by this in-process attempt. A numeric child status is never a clean
  # failure receipt: Compose itself can return the same code. Only a private,
  # HMAC-authenticated receipt bound to this attempt and proved lease may release
  # the stopped window. Missing/stale/invalid receipts and signals preserve it.
  if [ "${MVR03_PRINCIPAL_CUTOVER:-0}" = "1" ]; then
    principal_attempt_id="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
    inventory_rc=$?
    if [ "${inventory_rc}" -ne 0 ]; then
      echo "instance state deployment: principal cutover attempt creation failed" >&2
      return "${inventory_rc}"
    fi
    principal_receipt_path="/app/instance-ownership/principal-cutover-clean-failure-${principal_attempt_id}.json"
    principal_receipt_host_path="$(_instance_state_deployment_host_ownership_path "${principal_receipt_path}")" || {
      echo "instance state deployment: principal cutover receipt path is invalid" >&2
      return 78
    }
    rm -f -- "${principal_receipt_host_path}"
    "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
      python -m app.instance.runtime principal-cutover \
        --channel "${channel}" \
        --registry-path /app/instance-state/agentic-pkm/vault-registry.md \
        --host-global-root /app/instance-ownership \
        --inventory-path "${inventory_path}" \
        --quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json \
        --compose-base /run/scalar-rollback-policy/docker-compose.yaml \
        --native-producer-root /run/principal-fence-native-producers \
        --attempt-id "${principal_attempt_id}" \
        --clean-failure-receipt-path "${principal_receipt_path}" \
        --existing-install \
        --consumer bootstrap-init \
        ${principal_loopback_flag:+"${principal_loopback_flag}"}
    inventory_rc=$?
    if [ "${inventory_rc}" -ne 0 ]; then
      "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
        python -m app.instance.runtime principal-verify-cutover-clean-failure \
          --channel "${channel}" \
          --registry-path /app/instance-state/agentic-pkm/vault-registry.md \
          --host-global-root /app/instance-ownership \
          --quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json \
          --attempt-id "${principal_attempt_id}" \
          --clean-failure-receipt-path "${principal_receipt_path}"
      receipt_verify_rc=$?
      rm -f -- "${principal_receipt_host_path}"
      if [ "${receipt_verify_rc}" -ne 0 ]; then
        echo "instance state deployment: principal cutover requires stopped-window repair" >&2
        return "${inventory_rc}"
      fi
      _release_abandoned_instance_state_deployment_lease \
        "${compose_function}" "${channel}" "${runtime_user}" \
        "${controller_pid}" "${controller_start_token}"
      return "${inventory_rc}"
    fi
  fi

  # An explicit scalar fork is imported only while the host-global lease,
  # restart fence, stopped-writer proof, and drained-owner receipt are live.
  # Ordinary deployments never infer a scalar fork.
  if [ -n "${MVR01C_ROLL_FORWARD_LEGACY_PATH:-}" ]; then
    if [ "${MVR01C_ROLL_FORWARD_LEGACY_PATH}" != "/app/scalar-rollback/app-local.md" ]; then
      echo "MVR-01C roll-forward source must be the governed scalar volume" >&2
      _release_abandoned_instance_state_deployment_lease \
        "${compose_function}" "${channel}" "${runtime_user}" \
        "${controller_pid}" "${controller_start_token}"
      return 78
    fi
    "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
      python -m app.instance.runtime scalar-rollback-roll-forward \
        --channel "${channel}" \
        --instance-state-root /app/instance-state \
        --host-global-root /app/instance-ownership \
        --legacy-path "${MVR01C_ROLL_FORWARD_LEGACY_PATH}" \
        --inventory-path "${inventory_path}" \
        --quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json
    inventory_rc=$?
    if [ "${inventory_rc}" -ne 0 ]; then
      _release_abandoned_instance_state_deployment_lease \
        "${compose_function}" "${channel}" "${runtime_user}" \
        "${controller_pid}" "${controller_start_token}"
      return "${inventory_rc}"
    fi
  fi

  # MVR-01C is an explicit authority cutover, never an inferred side effect of
  # deploying the capable image. Keep the deployment lease, restart fence,
  # stopped-writer proof, and drained-owner receipt live through the one atomic
  # authority commit; only deployment-finish may clear that stopped window.
  if [ -n "${MVR01C_ROLLBACK_VAULT_BINDING_ID:-}" ] || [ -n "${MVR01C_ROLLBACK_VAULT_ROOT:-}" ]; then
    if [ -z "${MVR01C_ROLLBACK_VAULT_BINDING_ID:-}" ] || [ -z "${MVR01C_ROLLBACK_VAULT_ROOT:-}" ]; then
      echo "MVR-01C cutover requires both rollback binding and root" >&2
      _release_abandoned_instance_state_deployment_lease \
        "${compose_function}" "${channel}" "${runtime_user}" \
        "${controller_pid}" "${controller_start_token}"
      return 78
    fi
    "${compose_function}" run --rm --no-deps -T \
      --volume "${MVR01C_ROLLBACK_VAULT_ROOT}:/app/selected-vault:ro" \
      --user "${runtime_user}" instance-state-init \
      python -m app.instance.runtime authority-cutover \
        --channel "${channel}" \
        --instance-state-root /app/instance-state \
        --host-global-root /app/instance-ownership \
        --rollback-vault-binding-id "${MVR01C_ROLLBACK_VAULT_BINDING_ID}" \
        --selected-root /app/selected-vault \
        --compose-base /run/scalar-rollback-policy/docker-compose.yaml \
        --compose-overlay /run/scalar-rollback-policy/docker-compose.scalar-rollback.yml \
        --gateway-config /run/scalar-rollback-policy/nginx.conf \
        --native-launcher /app/scripts/scalar_rollback_native.sh \
        --inventory-path "${inventory_path}" \
        --quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json
    inventory_rc=$?
    if [ "${inventory_rc}" -ne 0 ]; then
      _release_abandoned_instance_state_deployment_lease \
        "${compose_function}" "${channel}" "${runtime_user}" \
        "${controller_pid}" "${controller_start_token}"
      return "${inventory_rc}"
    fi
  fi

  # MVR-05A8: after every fallible stopped-window precondition above has
  # completed, seal scalar rollback immediately before finalization can permit
  # the first binding-keyed migration or restarted runtime write.
  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime mvr05-record-floor \
      --channel "${channel}" \
      --registry-path /app/instance-state/agentic-pkm/vault-registry.md \
      --host-global-root /app/instance-ownership \
      --quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json \
      --fence-plan "/app/instance-ownership/mvr05-fence-plan-${controller_pid}.json"
  inventory_rc=$?
  rm -f -- "${mvr05_fence_plan_host_path}"
  if [ "${inventory_rc}" -ne 0 ]; then
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi

  # SETTINGS-05A installs only the dormant record/floor while the same proved
  # stopped window that seals MVR-05 is still live. This is the production and
  # existing-install producer; API, picker, and watcher activation remain sealed.
  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime settings-rebind-install-dormant \
      --channel "${channel}" \
      --registry-path /app/instance-state/agentic-pkm/vault-registry.md \
      --host-global-root /app/instance-ownership \
      --quiescence-proof-path /app/instance-ownership/deployment-quiescence-proof.json
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi

  # Publish the host receipt only after both deployment proof and the atomic
  # SETTINGS record/floor commit succeeded. A crash before this point leaves no
  # rollback fence; a crash after it has the complete protected state.
  _write_settings_rebind_floor_receipt "${channel}" installed
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    _release_abandoned_instance_state_deployment_lease \
      "${compose_function}" "${channel}" "${runtime_user}" \
      "${controller_pid}" "${controller_start_token}"
    return "${inventory_rc}"
  fi

  "${compose_function}" run --rm --no-deps -T --user "${runtime_user}" instance-state-init \
    python -m app.instance.runtime deployment-finish \
      "${finish_args[@]}"
  inventory_rc=$?
  if [ "${inventory_rc}" -ne 0 ]; then
    return "${inventory_rc}"
  fi
}
