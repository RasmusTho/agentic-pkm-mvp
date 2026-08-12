#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
source "${ROOT}/scripts/lib/deploy_channel_compose.sh"
source "${ROOT}/scripts/lib/instance_state_deployment.sh"
PYTHON="${PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${ROOT}/.venv/bin/python" ]; then
    PYTHON="${ROOT}/.venv/bin/python"
  elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON="$(command -v python3.12)"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
  else
    PYTHON="$(command -v python)"
  fi
fi

usage() {
  cat >&2 <<'EOF'
usage:
  scripts/deploy_channel.sh deploy <dev|test|prod> <sha> [--dry-run] [--ack-forward-only] [--ack-embedding-rebuild-required]
  scripts/deploy_channel.sh rollback <dev|test|prod> [sha] [--dry-run]

Environment:
  DEPLOY_DRY_RUN=1                  print the plan and stop before writes/docker
  DEPLOY_ACK_FORWARD_ONLY=1         acknowledge forward-only migrations
  DEPLOY_ACK_EMBEDDING_REBUILD_REQUIRED=1
                                    acknowledge only the embedding-index rebuild transition
  DEPLOY_HEALTH_TIMEOUT_SECONDS=90  health gate timeout
  MVR03_PRINCIPAL_CUTOVER=1         explicitly activate the one-time principal floor/role cutover
  MVR03_PRINCIPAL_LOOPBACK_LISTENER is pinned from config/deploy/<channel>.env (0 or 1)
EOF
}

action="${1:-}"
channel="${2:-}"
target_sha=""

case "${action}" in
  deploy)
    [ "$#" -ge 3 ] || { usage; exit 2; }
    target_sha="${3:-}"
    case "${target_sha}" in
      --*)
        usage
        exit 2
        ;;
    esac
    shift 3
    ;;
  rollback)
    [ "$#" -ge 2 ] || { usage; exit 2; }
    if [ "$#" -ge 3 ] && [[ "${3:-}" != --* ]]; then
      target_sha="${3}"
      shift 3
    else
      shift 2
    fi
    ;;
  *)
    usage
    exit 2
    ;;
esac

dry_run="${DEPLOY_DRY_RUN:-0}"
ack_forward_only="${DEPLOY_ACK_FORWARD_ONLY:-0}"
ack_embedding_rebuild_required="${DEPLOY_ACK_EMBEDDING_REBUILD_REQUIRED:-0}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --ack-forward-only) ack_forward_only=1 ;;
    --ack-embedding-rebuild-required) ack_embedding_rebuild_required=1 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

case "${channel}" in
  dev)
    compose_overlay="docker-compose.dev.yml"
    compose_project="pkm-dev"
    api_port="18001"
    ui_port="8111"
    ;;
  test)
    compose_overlay="docker-compose.test.yml"
    compose_project="pkm-test"
    api_port="18002"
    ui_port="8112"
    ;;
  prod)
    compose_overlay="docker-compose.prod.yml"
    compose_project="pkm-prod"
    api_port="18000"
    ui_port="8113"
    ;;
  *) usage; exit 2 ;;
esac

pin_file="${ROOT}/config/deploy/${channel}.env"
previous_pin_file="${ROOT}/config/deploy/${channel}.previous.env"
migration_pending_file="${ROOT}/config/deploy/${channel}.migration-pending.env"
migration_no_baseline_marker="__NO_BASELINE__"
receipt_dir="${ROOT}/ops/deployments"
promotion_dir="${ROOT}/ops/promotions"
image_repository="${APP_IMAGE_REPOSITORY:-ghcr.io/rasmustho/pkm-app}"
health_timeout="${DEPLOY_HEALTH_TIMEOUT_SECONDS:-90}"

# Pin the topology declaration from the governed channel file before the
# shared deployment wrapper runs. Do not inherit an ambient shell value across
# channels: Docker-published dev/test/prod API traffic is not proven loopback
# inside the container, while a future channel may explicitly declare 1.
if [ "${action}" = "deploy" ] && [ "${MVR03_PRINCIPAL_CUTOVER:-0}" = "1" ]; then
  mvr03_principal_loopback_listener="$(
    awk -F= '/^MVR03_PRINCIPAL_LOOPBACK_LISTENER=/{print $2; exit}' "${pin_file}"
  )"
  case "${mvr03_principal_loopback_listener}" in
    0|1)
      export MVR03_PRINCIPAL_LOOPBACK_LISTENER="${mvr03_principal_loopback_listener}"
      ;;
    *)
      echo "MVR03_PRINCIPAL_LOOPBACK_LISTENER is missing or invalid for the selected channel" >&2
      exit 78
      ;;
  esac
  unset mvr03_principal_loopback_listener
fi

read_pin() {
  local file="$1"
  [ -f "${file}" ] || return 1
  awk -F= '/^APP_IMAGE_TAG=/{print $2; exit}' "${file}"
}

write_pin() {
  local file="$1" sha="$2"
  local tmp_file
  tmp_file="$(mktemp "${file}.tmp.XXXXXX")"
  if [ -f "${file}" ]; then
    awk -F= '$1 != "APP_IMAGE_REPOSITORY" && $1 != "APP_IMAGE_TAG" { print }' "${file}" >"${tmp_file}"
  fi
  printf 'APP_IMAGE_REPOSITORY=%s\nAPP_IMAGE_TAG=%s\n' "${image_repository}" "${sha}" >>"${tmp_file}"
  mv "${tmp_file}" "${file}"
}

resolve_target_sha() {
  local sha="$1"
  if [ -n "${sha}" ]; then
    git -C "${ROOT}" rev-parse --verify "${sha}^{commit}" >/dev/null
    git -C "${ROOT}" rev-parse "${sha}^{commit}"
    return 0
  fi
  if [ "${action}" = "rollback" ] && [ -f "${previous_pin_file}" ]; then
    read_pin "${previous_pin_file}"
    return 0
  fi
  if [ "${action}" = "rollback" ] && [ "${dry_run}" = "1" ]; then
    if [ -n "${current_sha}" ]; then
      printf '%s\n' "${current_sha}"
      return 0
    fi
    git -C "${ROOT}" rev-parse HEAD
    return 0
  fi
  echo "target sha is required" >&2
  exit 2
}

MIGRATIONS_CHECKED=0
FORWARD_ONLY_COUNT=0
FORWARD_ONLY_MIGRATION_STARTED=0
FORWARD_ONLY_MIGRATION_APPLIED=0
MIGRATION_EXECUTION_STARTED=0
MIGRATION_EXECUTION_APPLIED=0
migration_materialize_dir="$(mktemp -d "${TMPDIR:-/tmp}/pkm-deploy-migrations.XXXXXX")"
deploy_lock_dir=""
trap 'rm -rf "${migration_materialize_dir}"; [ -n "${deploy_lock_dir}" ] && rmdir "${deploy_lock_dir}" 2>/dev/null' EXIT

acquire_channel_mutation_lock() {
  # Serialize the mutation phase (pending-marker + pin writes + compose) per
  # channel. Two concurrent deploys would otherwise race the durable
  # pending-migration marker: the first finisher's cleanup deletes the record
  # the still-running attempt depends on for crash recovery.
  deploy_lock_dir="${pin_file}.lock"
  if ! mkdir "${deploy_lock_dir}" 2>/dev/null; then
    deploy_lock_dir=""
    echo "channel mutation blocked: another deploy/rollback appears to hold ${pin_file}.lock; remove that directory only after verifying no deploy_channel.sh process is running" >&2
    exit 89
  fi
}

# The lock must cover the mutable-state snapshot as well as writes. Acquiring
# it later would let a slow classifier retain a stale current_sha while another
# invocation completes a deployment, then roll back that newer deployment.
mkdir -p "$(dirname "${pin_file}")"
acquire_channel_mutation_lock
current_sha="$(read_pin "${pin_file}" 2>/dev/null || true)"
target_sha="$(resolve_target_sha "${target_sha}")"
scalar_rollback=0
if [ "${action}" = "rollback" ] && \
  ! git -C "${ROOT}" cat-file -e "${target_sha}:app/instance/runtime.py" 2>/dev/null; then
  scalar_rollback=1
fi

prepare_scalar_rollback_environment() {
  if [ -z "${current_sha}" ]; then
    echo "scalar rollback requires a current image for the trusted guard" >&2
    return 78
  fi
  if [ -z "${SCALAR_ROLLBACK_VAULT_BINDING_ID:-}" ]; then
    echo "scalar rollback requires SCALAR_ROLLBACK_VAULT_BINDING_ID" >&2
    return 78
  fi
  case "${SCALAR_ROLLBACK_VAULT_ROOT:-}" in
    /*) ;;
    *)
      echo "scalar rollback requires an absolute SCALAR_ROLLBACK_VAULT_ROOT" >&2
      return 78
      ;;
  esac
  if [ ! -d "${SCALAR_ROLLBACK_VAULT_ROOT}" ]; then
    echo "scalar rollback selected root is not a directory" >&2
    return 78
  fi
  case "${SCALAR_ROLLBACK_HTPASSWD:-}" in
    /*) ;;
    *)
      echo "scalar rollback requires an absolute SCALAR_ROLLBACK_HTPASSWD" >&2
      return 78
      ;;
  esac
  if [ ! -f "${SCALAR_ROLLBACK_HTPASSWD}" ]; then
    echo "scalar rollback gateway credential file is missing" >&2
    return 78
  fi
  if [ ! -s "${SCALAR_ROLLBACK_HTPASSWD}" ] || ! awk '
    /^[^:[:space:]]+:[^[:space:]]+$/ { seen = 1; next }
    { invalid = 1 }
    END { exit (seen && !invalid) ? 0 : 1 }
  ' "${SCALAR_ROLLBACK_HTPASSWD}"; then
    echo "scalar rollback gateway credential file is empty or invalid" >&2
    return 78
  fi
  case "${SCALAR_ROLLBACK_AUTH_NETRC:-}" in
    /*) ;;
    *)
      echo "scalar rollback requires an absolute SCALAR_ROLLBACK_AUTH_NETRC" >&2
      return 78
      ;;
  esac
  if [ ! -f "${SCALAR_ROLLBACK_AUTH_NETRC}" ]; then
    echo "scalar rollback authenticated probe credential file is missing" >&2
    return 78
  fi
  if ! SCALAR_ROLLBACK_AUTH_PROBE_USER="$(
    "${PYTHON}" - \
      "${SCALAR_ROLLBACK_AUTH_NETRC}" \
      "${SCALAR_ROLLBACK_HTPASSWD}" <<'PY'
import netrc
import os
import stat
import sys

netrc_path, htpasswd_path = sys.argv[1:]
if stat.S_IMODE(os.stat(netrc_path).st_mode) & 0o077:
    raise SystemExit(1)
credentials = netrc.netrc(netrc_path).authenticators("127.0.0.1")
if credentials is None:
    raise SystemExit(1)
login, _, password = credentials
if not login or not password:
    raise SystemExit(1)
with open(htpasswd_path, encoding="utf-8") as handle:
    users = {line.split(":", 1)[0] for line in handle if ":" in line}
if login not in users:
    raise SystemExit(1)
print(login)
PY
  )"; then
    echo "scalar rollback authenticated probe credential is invalid or does not match htpasswd" >&2
    return 78
  fi
  MVR01C_SCALAR_ROLLBACK=1
  SCALAR_ROLLBACK_GUARD_IMAGE="${image_repository}:${current_sha}"
  SCALAR_ROLLBACK_PREVIOUS_IMAGE="${image_repository}:${target_sha}"
  PKM_ENVIRONMENT="${channel}"
  SCALAR_ROLLBACK_PORT="${api_port}"
  export MVR01C_SCALAR_ROLLBACK
  export SCALAR_ROLLBACK_GUARD_IMAGE SCALAR_ROLLBACK_PREVIOUS_IMAGE
  export SCALAR_ROLLBACK_VAULT_BINDING_ID SCALAR_ROLLBACK_VAULT_ROOT
  export SCALAR_ROLLBACK_HTPASSWD SCALAR_ROLLBACK_AUTH_NETRC
  export SCALAR_ROLLBACK_AUTH_PROBE_USER
  export PKM_ENVIRONMENT SCALAR_ROLLBACK_PORT
}

read_pending_migration_field() {
  local field="$1"
  [ -f "${migration_pending_file}" ] || return 1
  awk -F= -v field="${field}" '$1 == field { print $2; exit }' "${migration_pending_file}"
}

write_pending_migration() {
  local from_sha="$1" to_sha="$2" tmp_file persisted_from
  persisted_from="${from_sha:-${migration_no_baseline_marker}}"
  tmp_file="$(mktemp "${migration_pending_file}.tmp.XXXXXX")"
  # A first-ever channel deploy has no prior pin; persist the explicit
  # sentinel so a same-target retry can distinguish "from nothing" from a
  # corrupted marker.
  printf 'FROM_SHA=%s\nTARGET_SHA=%s\nACK_FORWARD_ONLY=%s\n' \
    "${persisted_from}" "${to_sha}" "${ack_forward_only}" >"${tmp_file}"
  mv "${tmp_file}" "${migration_pending_file}"
}

list_changed_migrations() {
  # Every materialization step is explicitly guarded: this function's output
  # is consumed as the authoritative migration set, so any git-object or
  # filesystem failure must surface as a nonzero return, never as a silently
  # truncated (or empty) list.
  local from_sha="$1" to_sha="$2"
  local path destination git_paths rc
  if [ -z "${from_sha}" ] || ! git -C "${ROOT}" rev-parse --verify "${from_sha}^{commit}" >/dev/null 2>&1; then
    set +e
    git_paths="$(git -C "${ROOT}" ls-tree -r --name-only "${to_sha}" -- app/alembic/versions)"
    rc=$?
    set -e
    [ "${rc}" -eq 0 ] || return "${rc}"
    while IFS= read -r path; do
      [ -n "${path}" ] && [[ "${path}" = *.py ]] || continue
      destination="${migration_materialize_dir}/${path}"
      mkdir -p "$(dirname "${destination}")" || return 1
      git -C "${ROOT}" show "${to_sha}:${path}" >"${destination}" || return $?
      printf '%s\n' "${destination}"
    done <<<"${git_paths}"
    return 0
  fi
  set +e
  git_paths="$(git -C "${ROOT}" diff --diff-filter=AMCR --name-only "${from_sha}..${to_sha}" -- app/alembic/versions)"
  rc=$?
  set -e
  [ "${rc}" -eq 0 ] || return "${rc}"
  while IFS= read -r path; do
    [ -n "${path}" ] || continue
    destination="${migration_materialize_dir}/${path}"
    mkdir -p "$(dirname "${destination}")" || return 1
    git -C "${ROOT}" show "${to_sha}:${path}" >"${destination}" || return $?
    printf '%s\n' "${destination}"
  done <<<"${git_paths}"
  return 0
}

migration_gate() {
  local from_sha="$1" to_sha="$2" receipt_json forward_count migration_output rc
  local -a migration_paths
  migration_paths=()
  set +e
  migration_output="$(list_changed_migrations "${from_sha}" "${to_sha}")"
  rc=$?
  set -e
  if [ "${rc}" -ne 0 ]; then
    echo "migration gate blocked: failed to materialize the exact ${from_sha:-<initial>}..${to_sha} migration set from git objects; refusing to classify" >&2
    return "${rc}"
  fi
  while IFS= read -r path; do
    [ -n "${path}" ] && migration_paths+=("${path}")
  done <<<"${migration_output}"
  if [ "${#migration_paths[@]}" -gt 0 ]; then
    receipt_json="$("${PYTHON}" - "$ack_forward_only" "${migration_paths[@]}" <<'PY'
import json
import sys
from pathlib import Path

from app.release_channels.reversibility import check_all_migrations

ack = sys.argv[1] == "1"
paths = [Path(p) for p in sys.argv[2:]]
receipt = check_all_migrations(paths)
receipt["ack_forward_only"] = ack
print(json.dumps(receipt, sort_keys=True))
if receipt["forward_only"] and not ack:
    print(
        "forward-only migrations require DEPLOY_ACK_FORWARD_ONLY=1 or --ack-forward-only",
        file=sys.stderr,
    )
    sys.exit(42)
PY
)"
  else
    receipt_json="$("${PYTHON}" - "$ack_forward_only" <<'PY'
import json
import sys

ack = sys.argv[1] == "1"
print(json.dumps({
    "migrations_checked": 0,
    "reversible": [],
    "forward_only": [],
    "classification_decisions": [],
    "ack_forward_only": ack,
}, sort_keys=True))
PY
)"
  fi || {
    rc=$?
    if [ "${rc}" -eq 42 ]; then
      echo "migration gate blocked before recreate" >&2
    fi
    return "${rc}"
  }
  forward_count="$("${PYTHON}" -c 'import json,sys; print(len(json.loads(sys.stdin.read()).get("forward_only", [])))' <<<"${receipt_json}")"
  echo "migration gate ok: ${#migration_paths[@]} migration(s), forward_only=${forward_count}"
  MIGRATIONS_CHECKED="${#migration_paths[@]}"
  FORWARD_ONLY_COUNT="${forward_count}"
  MIGRATION_RECEIPT_JSON="${receipt_json}"
  export MIGRATION_RECEIPT_JSON
}

compose() {
  deploy_channel_compose \
    "${ROOT}" \
    "${channel}" \
    "${compose_overlay}" \
    "${compose_project}" \
    "${pin_file}" \
    "$@"
}

ensure_prod_instance_state_volume() {
  if [ "${channel}" != "prod" ]; then
    return 0
  fi
  if docker volume inspect pkm-prod_instance-state >/dev/null 2>&1; then
    return 0
  fi
  docker volume create --label agentic-pkm.surface=instance-state \
    pkm-prod_instance-state >/dev/null
}

wait_json_ok() {
  local url="$1" deadline body
  deadline=$((SECONDS + health_timeout))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    if body="$(curl -fsS --max-time 3 "${url}" 2>/dev/null)"; then
      if "${PYTHON}" -c 'import json,sys; data=json.load(sys.stdin); sys.exit(0 if isinstance(data, dict) and data.get("ok") is True else 1)' <<<"${body}"; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

health_gate() {
  wait_json_ok "http://127.0.0.1:${api_port}/healthz" || return 1
  wait_json_ok "http://127.0.0.1:${ui_port}/healthz" || return 1
}

embedding_provider_preflight_gate() {
  # Explicit embedding sources are authoritative.  Validate them in the
  # recreated API before the channel health gate can report this deployment
  # healthy; LLM_PROVIDER spillover intentionally remains tolerant.
  compose exec -T api python -m app.cli settings validate --json
}

retire_scalar_rollback_services() {
  local service container_ids cid rc=0
  for service in scalar-rollback-gateway scalar-rollback-guard; do
    container_ids="$(
      docker ps -aq \
        --filter "label=com.docker.compose.project=${compose_project}" \
        --filter "label=com.docker.compose.service=${service}"
    )" || rc=$?
    if [ "${rc}" -ne 0 ]; then
      echo "scalar rollback retirement: ${service} lookup failed" >&2
      return "${rc}"
    fi
    while IFS= read -r cid; do
      [ -n "${cid}" ] || continue
      docker rm -f "${cid}" >/dev/null || return $?
    done <<<"${container_ids}"
  done
}

recreate_channel_services() {
  local rc=0
  if [ "${scalar_rollback}" = "1" ]; then
    compose stop api worker watcher heimdal-capture-watch companion-ui \
      scalar-rollback-gateway || return $?
    compose up -d --force-recreate \
      scalar-rollback-guard api scalar-rollback-gateway
    return $?
  fi
  if [ "${action}" != "deploy" ]; then
    retire_scalar_rollback_services || return $?
  fi
  if [ "${action}" = "deploy" ] && [ "${ack_embedding_rebuild_required}" = "1" ]; then
    # During an acknowledged embedding-dimension cutover, /readyz must stay red
    # until the governed full rebuild completes. Start the runtime first, prove
    # API liveness, then start the gateway without re-applying its service_healthy
    # dependency. The later live smoke still admits only the sole exact
    # embedding_index=rebuild_required transition; the API container healthcheck
    # remains strict on /readyz throughout.
    compose up -d --force-recreate api worker watcher heimdal-capture-watch || rc=$?
    [ "${rc}" -eq 0 ] || return "${rc}"
    wait_json_ok "http://127.0.0.1:${api_port}/healthz" || return 1
    rc=0
    compose up -d --force-recreate --no-deps companion-ui || rc=$?
    [ "${rc}" -eq 0 ] || return "${rc}"
    return 0
  fi

  compose up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui
}

scalar_rollback_gateway_auth_gate() {
  local status body rc=0
  status="$(
    curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 3 \
      --user "${SCALAR_ROLLBACK_AUTH_PROBE_USER}:definitely-invalid" \
      "http://127.0.0.1:${api_port}/healthz"
  )" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "scalar rollback gate: authenticated gateway is unreachable" >&2
    return "${rc}"
  fi
  if [ "${status}" != "401" ]; then
    echo "scalar rollback gate: authenticated gateway did not reject invalid credentials (status ${status})" >&2
    return 1
  fi
  rc=0
  body="$(
    curl --noproxy '*' -fsS --max-time 3 \
      --netrc-file "${SCALAR_ROLLBACK_AUTH_NETRC}" \
      "http://127.0.0.1:${api_port}/healthz"
  )" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "scalar rollback gate: provisioned credential cannot authenticate" >&2
    return "${rc}"
  fi
  if ! "${PYTHON}" -c '
import json
import sys

payload = json.load(sys.stdin)
raise SystemExit(0 if isinstance(payload, dict) and payload.get("ok") is True else 1)
' <<<"${body}"; then
    echo "scalar rollback gate: authenticated gateway health response is invalid" >&2
    return 1
  fi
}

scalar_rollback_runtime_gate() {
  local service cid status rc=0
  for service in api scalar-rollback-gateway; do
    cid="$(compose ps -q "${service}")" || rc=$?
    if [ "${rc}" -ne 0 ] || [ -z "${cid}" ]; then
      echo "scalar rollback gate: ${service} container is missing" >&2
      if [ "${rc}" -ne 0 ]; then
        return "${rc}"
      fi
      return 1
    fi
    rc=0
    status="$(
      docker inspect -f \
        '{{if .State.Health}}{{.State.Health.Status}}{{else if .State.Running}}running{{else}}stopped{{end}}' \
        "${cid}" 2>/dev/null
    )" || rc=$?
    if [ "${rc}" -ne 0 ]; then
      echo "scalar rollback gate: ${service} state is unreadable" >&2
      return "${rc}"
    fi
    case "${status}" in
      healthy|running) ;;
      *)
        echo "scalar rollback gate: ${service} is ${status}" >&2
        return 1
        ;;
    esac
  done
  scalar_rollback_gateway_auth_gate
}

apply_changed_migrations() {
  # Rollback migrations are governed separately by rollback-promotion. Running
  # an older target image's `alembic upgrade head` against a newer stamped
  # database would fail before the known-good runtime can be restored.
  if [ "${action}" != "deploy" ] || [ "${MIGRATIONS_CHECKED}" -eq 0 ]; then
    return 0
  fi

  # A pre-cutover producer blocked on the migration's table lock must not be
  # allowed to resume after commit and create a legacy-only row. Drain every
  # runtime writer before Alembic takes its snapshot, then run the one-shot
  # migration authority explicitly before any target runtime is recreated.
  compose stop api worker watcher heimdal-capture-watch companion-ui || return $?
  MIGRATION_EXECUTION_STARTED=1
  if [ "${FORWARD_ONLY_COUNT}" -gt 0 ]; then
    # From this point a nonzero Docker result is ambiguous: Alembic may have
    # committed before the client lost the container result. Fail closed by
    # retaining the schema-compatible target unless unchanged DB revision is
    # proven by the governed recovery workflow.
    FORWARD_ONLY_MIGRATION_STARTED=1
  fi
  compose up --abort-on-container-exit --exit-code-from migrate --force-recreate migrate || return $?
  MIGRATION_EXECUTION_APPLIED=1
  if [ "${FORWARD_ONLY_COUNT}" -gt 0 ]; then
    FORWARD_ONLY_MIGRATION_APPLIED=1
  fi
  rm -f "${migration_pending_file}"
}

rollback_failed_startup() {
  local reason="$1" original_status="$2" forward_only_count="0"
  if [ "${scalar_rollback}" = "1" ]; then
    echo "${reason} (status ${original_status}); retaining the current guard pin and scalar rollback target for a fail-closed retry" >&2
    return 0
  fi
  if [ -n "${MIGRATION_RECEIPT_JSON:-}" ]; then
    forward_only_count="$("${PYTHON}" -c 'import json,os; print(len(json.loads(os.environ["MIGRATION_RECEIPT_JSON"]).get("forward_only", [])))' 2>/dev/null || printf 'unknown')"
  fi
  if [ "${MIGRATION_EXECUTION_STARTED}" = "1" ]; then
    if [ "${forward_only_count}" = "0" ]; then
      if [ "${MIGRATION_EXECUTION_APPLIED}" = "1" ]; then
        echo "${reason} (status ${original_status}); reversible migration(s) were applied but are not reversed by the deploy hot path; the target pin is retained until rollback-promotion proves and executes the governed reversal" >&2
      else
        echo "${reason} (status ${original_status}); reversible migration execution started and its commit state is ambiguous; the target pin is retained until database revision is reconciled" >&2
      fi
      return 0
    fi
    if [ "${FORWARD_ONLY_MIGRATION_APPLIED}" = "1" ]; then
      echo "${reason} (status ${original_status}); forward-only migration(s) are not auto-reversed; they were applied, so the target pin is retained for a compatible forward fix instead of restoring a potentially schema-incompatible previous image" >&2
    else
      echo "${reason} (status ${original_status}); forward-only migration execution started and its commit state is ambiguous; the target pin is retained until unchanged database revision is proven or a compatible forward fix is applied" >&2
    fi
    return 0
  fi
  if [ -n "${current_sha}" ]; then
    echo "${reason} (status ${original_status}); attempting rollback to previous pin" >&2
    if ! write_pin "${pin_file}" "${current_sha}"; then
      echo "rollback pin restore failed for previous pin ${current_sha}" >&2
      return 0
    fi
    if [ "${action}" = "deploy" ]; then
      # Only a deploy attempt that never started migration execution may clear
      # its own marker (and only after the pin restore proved effective). A
      # failing rollback must not delete the durable record of an unrelated
      # interrupted deploy's ambiguous migration state.
      rm -f "${migration_pending_file}"
    fi
    if ! MVR01C_SCALAR_ROLLBACK=0 INSTANCE_STATE_LEGACY_ROLLBACK=1 \
      compose up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui; then
      echo "rollback recreate failed for previous pin ${current_sha}" >&2
    fi
  else
    echo "${reason} (status ${original_status}); rollback unavailable because no previous pin was recorded; retaining the no-baseline migration marker for same-target retry" >&2
  fi
}

run_postmutation_gate() {
  local reason="$1" rc=0
  shift
  "$@" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    if [ "${action}" = "deploy" ]; then
      rollback_failed_startup "${reason}" "${rc}"
    elif [ "${rollback_target_recreated:-0}" != "1" ]; then
      echo "manual rollback failed before target services were established; restoring pre-rollback pin and services" >&2
      rollback_failed_startup "${reason}" "${rc}"
    else
      echo "manual rollback gate failed: ${reason} (status ${rc}); retaining rollback target ${target_sha} instead of restoring pre-rollback pin ${current_sha:-unset}" >&2
    fi
    return "${rc}"
  fi
}

capture_watch_gate() {
  # Surface a broken heimdal-capture-watch (e.g. missing/invalid HEIMDAL_RAW_STORE_KEY, which
  # its own healthcheck fails loud on) at deploy time instead of letting it sit unhealthy and
  # silent. This is a required post-mutation gate: a failure routes through the shared rollback
  # path before a successful deploy receipt is recorded.
  local cid deadline status ps_output rc=0
  ps_output="$(compose ps -q heimdal-capture-watch)" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "capture-watch gate: service lookup failed (status ${rc})" >&2
    return "${rc}"
  fi
  cid="$(head -1 <<<"${ps_output}")"
  if [ -z "${cid}" ]; then
    echo "capture-watch gate: heimdal-capture-watch container not found after deploy" >&2
    return 1
  fi
  deadline=$(( $(date +%s) + 120 ))
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || echo missing)"
    case "${status}" in
      healthy) return 0 ;;
      unhealthy) echo "capture-watch gate: container unhealthy — check HEIMDAL_RAW_STORE_KEY / HEIMDAL_CAPTURE_WATCH_DIR for channel ${channel}" >&2; return 1 ;;
    esac
    sleep 3
  done
  echo "capture-watch gate: heimdal-capture-watch did not become healthy within 120s (last status: ${status})" >&2
  return 1
}

prod_pending_retry_preflight() {
  # Read-only PROD deploy-only preflight (#3903): detect pending DB-outbox
  # rows already at a terminal retry boundary -- one more failure and the
  # worker dead-letters them on its own, no code change involved. Runs before
  # pin write or Compose mutation so a restart never silently consumes rows
  # that are already deterministically doomed (the #3124 postmortem: eight
  # panel.scan.requested rows already at retry-3 dead-lettered the moment
  # the worker restarted, undetected by every other gate). Never mutates the
  # outbox; deliberately NOT applied to rollback (the prior stable ref must
  # always be recoverable -- docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md).
  # DSN sourcing (#3903 rounds 4 and 6): the effective DATABASE_URL/DB_DSN a
  # running prod service binds to is resolved ENTIRELY inside
  # scripts/prod_deploy_retry_preflight.py, by asking
  # app.release_channels.channel_isolation_preflight (the one purpose-built,
  # tested Compose environment:-vs-env_file: resolver) what docker-compose.prod.yml
  # actually binds -- not by this wrapper reading pin/runtime-env files and
  # guessing precedence by hand (rounds 2 and 3 both tried that and were both
  # wrong: Compose's own `environment:` block always wins over `env_file:` for
  # the same key, and the prod overlay sets DATABASE_URL/DB_DSN directly in
  # `environment:`). This wrapper therefore has no DSN of its own to inject;
  # the preflight subprocess inherits this shell's environment exactly as the
  # real `docker compose` invocation below does, AND resolves the same
  # `--env-file "${pin_file}"` interpolation contribution that invocation
  # passes to Compose (round 6: an ambient DATABASE_URL/DB_DSN override still
  # wins over both, matching Compose's real precedence). Nothing is printed
  # either way (#3875 redaction posture). See
  # scripts/prod_deploy_retry_preflight.py and
  # docs/HEALTH.md :: Outbox and dead-letter signals.
  local receipt_json rc=0
  receipt_json="$("${PYTHON}" "${ROOT}/scripts/prod_deploy_retry_preflight.py")" || rc=$?

  # Always emit exactly one status line -- ok / skipped:<reason> / blocked --
  # derived from the receipt's status+reason fields (counts and reason codes
  # only). A silent skip of a prod safety gate is indistinguishable from a
  # pass: the false-green pattern this repo has been burned by.
  printf '%s' "${receipt_json}" | "${PYTHON}" -c '
import json, sys
try:
    data = json.loads(sys.stdin.read() or "{}")
except Exception:
    data = {}
status = data.get("status") or "error"
if status == "skipped":
    line = "prod pending-retry preflight: skipped:" + str(data.get("reason") or "unknown")
elif status == "blocked":
    line = (
        "prod pending-retry preflight: blocked terminal_pending_count="
        + str(data.get("terminal_pending_count"))
    )
elif status == "ok":
    line = "prod pending-retry preflight: ok"
else:
    line = "prod pending-retry preflight: " + str(status)
print(line)
'

  if [ "${rc}" -ne 0 ]; then
    echo "prod deploy blocked before pin or Compose mutation: pending outbox work is already at the terminal retry boundary and would dead-letter on worker startup" >&2
    printf '%s\n' "${receipt_json}" >&2
    echo "guidance: inspect the reported topic(s) (e.g. python -m app.cli events-doctor --path \"\$INDEX_OUTBOX_PATH\") to find why processing keeps failing, resolve the underlying cause, then redeploy; this preflight is read-only and never mutates the outbox" >&2
    return 1
  fi
  return 0
}

dev_test_environment_env_file_clobber_preflight() {
  # Read-only dev/test deploy-only preflight (#4230): detect a CHANNEL_SERVICES
  # service whose explicit `environment:` block resolves a key to an empty
  # string while that service's env_file chain would otherwise supply a
  # non-empty value for the same key -- the exact shape that crash-looped
  # heimdal-capture-watch on every dev-channel deploy until commit f95a6811
  # deleted the offending `environment:` entries (that instance is already
  # fixed; this preflight guards the still-open general class). Runs before
  # write_pin / migration execution, mirroring prod_pending_retry_preflight's
  # placement and rationale: read-only, no Docker, no network, resolved
  # entirely by app.release_channels.channel_isolation_preflight (the one
  # purpose-built, tested Compose environment:-vs-env_file: resolver), never
  # re-derived from pin/runtime-env files by hand. Deliberately NOT applied to
  # rollback or the prod channel (prod's own DSN-scoped gate above is
  # unaffected -- docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md).
  local receipt_json rc=0
  receipt_json="$(
    "${PYTHON}" "${ROOT}/scripts/dev_test_environment_clobber_preflight.py" "${channel}"
  )" || rc=$?

  printf '%s' "${receipt_json}" | "${PYTHON}" -c '
import json, sys
try:
    data = json.loads(sys.stdin.read() or "{}")
except Exception:
    data = {}
status = data.get("status") or "error"
if status == "blocked":
    line = (
        "dev/test environment clobber preflight: blocked violation_count="
        + str(data.get("violation_count"))
    )
elif status == "skipped":
    line = "dev/test environment clobber preflight: skipped:" + str(data.get("reason") or "unknown")
elif status == "ok":
    line = "dev/test environment clobber preflight: ok"
else:
    line = "dev/test environment clobber preflight: " + str(status)
print(line)
'

  if [ "${rc}" -ne 0 ]; then
    echo "dev/test deploy blocked before pin or Compose mutation: a service environment: override would clobber a non-empty env_file value (heimdal-capture-watch clobber class, #4230)" >&2
    printf '%s\n' "${receipt_json}" >&2
    echo "guidance: remove the blank environment: override for the reported key(s) so the value rides the env_file chain instead (see docker-compose.yaml's heimdal-capture-watch comment for the pattern); this preflight is read-only and never mutates compose, pin, or env_file layers" >&2
    return 1
  fi
  return 0
}

version_gate() {
  local version_json health_json version_sha health_sha rc=0
  version_json="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/version")" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "version gate: /version fetch failed (status ${rc})" >&2
    return "${rc}"
  fi
  rc=0
  health_json="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/api/health")" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "version gate: /api/health fetch failed (status ${rc})" >&2
    return "${rc}"
  fi
  rc=0
  version_sha="$("${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin).get("git_sha", ""))' <<<"${version_json}")" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "version gate: /version response parse failed (status ${rc})" >&2
    return "${rc}"
  fi
  rc=0
  health_sha="$("${PYTHON}" -c 'import json,sys; data=json.load(sys.stdin); value=data.get("version"); print(value.get("git_sha", "") if isinstance(value, dict) else (value if isinstance(value, str) else ""))' <<<"${health_json}")" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "version gate: /api/health response parse failed (status ${rc})" >&2
    return "${rc}"
  fi
  [ "${version_sha}" = "${target_sha}" ] || {
    echo "/version reported ${version_sha}, expected ${target_sha}" >&2
    return 1
  }
  [ "${health_sha}" = "${target_sha}" ] || {
    echo "/api/health version reported ${health_sha}, expected ${target_sha}" >&2
    return 1
  }
}

fleet_model_fitness_gate() {
  local receipt_json rc=0
  receipt_json="$("${PYTHON}" -m app.release_channels.fleet_model_fitness "${channel}" --root "${ROOT}" --json --require-pinned)" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "fleet-model fitness gate failed" >&2
    if [ -n "${receipt_json}" ]; then
      echo "${receipt_json}" >&2
    fi
    return "${rc}"
  fi
  FLEET_MODEL_FITNESS_JSON="${receipt_json}"
  export FLEET_MODEL_FITNESS_JSON
}

record_receipt() {
  local receipt_path receipt_tmp promotion_path promotion_tmp promotion_backup timestamp rc
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "${receipt_dir}" || return $?
  receipt_path="${receipt_dir}/${channel}-latest.json"
  receipt_tmp="$(mktemp "${receipt_path}.tmp.XXXXXX")" || return $?
  "${PYTHON}" - "$receipt_tmp" <<PY
import json
import os
import sys
from pathlib import Path

payload = {
    "channel": "${channel}",
    "action": "${action}",
    "sha": "${target_sha}",
    "previous_sha": "${current_sha}",
    "image": "${image_repository}:${target_sha}",
    "recorded_at": "${timestamp}",
    "migration_receipt": json.loads(os.environ.get("MIGRATION_RECEIPT_JSON", "{}")),
    "fleet_model_fitness": json.loads(os.environ.get("FLEET_MODEL_FITNESS_JSON", "{}")),
    "embedding_rebuild_required_acknowledged": (
        os.environ.get("DEPLOY_EMBEDDING_REBUILD_REQUIRED_ACK", "0") == "1"
    ),
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\\n",
    encoding="utf-8",
)
PY
  rc=$?
  if [ "${rc}" -ne 0 ]; then
    rm -f "${receipt_tmp}"
    return "${rc}"
  fi
  if [ "${channel}" = "prod" ]; then
    mkdir -p "${promotion_dir}" || {
      rc=$?
      rm -f "${receipt_tmp}"
      return "${rc}"
    }
    promotion_path="${promotion_dir}/prod-deploy-${target_sha}.json"
    promotion_tmp="$(mktemp "${promotion_path}.tmp.XXXXXX")" || {
      rc=$?
      rm -f "${receipt_tmp}"
      return "${rc}"
    }
    promotion_backup=""
    if [ -f "${promotion_path}" ]; then
      promotion_backup="$(mktemp "${promotion_path}.backup.XXXXXX")" || {
        rc=$?
        rm -f "${receipt_tmp}" "${promotion_tmp}"
        return "${rc}"
      }
      rc=0
      cp "${promotion_path}" "${promotion_backup}" || rc=$?
      if [ "${rc}" -ne 0 ]; then
        rm -f "${receipt_tmp}" "${promotion_tmp}" "${promotion_backup}"
        return "${rc}"
      fi
    fi
    rc=0
    cp "${receipt_tmp}" "${promotion_tmp}" || rc=$?
    if [ "${rc}" -ne 0 ]; then
      rm -f "${receipt_tmp}" "${promotion_tmp}"
      if [ -n "${promotion_backup}" ]; then
        rm -f "${promotion_backup}"
      fi
      return "${rc}"
    fi
    rc=0
    mv "${promotion_tmp}" "${promotion_path}" || rc=$?
    if [ "${rc}" -ne 0 ]; then
      rm -f "${receipt_tmp}" "${promotion_tmp}"
      if [ -n "${promotion_backup}" ]; then
        rm -f "${promotion_backup}"
      fi
      return "${rc}"
    fi
  fi
  rc=0
  mv "${receipt_tmp}" "${receipt_path}" || rc=$?
  if [ "${rc}" -ne 0 ]; then
    rm -f "${receipt_tmp}"
    if [ "${channel}" = "prod" ]; then
      if [ -n "${promotion_backup}" ]; then
        if ! mv "${promotion_backup}" "${promotion_path}"; then
          echo "deploy receipt rollback failed to restore existing promotion receipt ${promotion_path}" >&2
        fi
      else
        rm -f "${promotion_path}"
      fi
    fi
    return "${rc}"
  fi
  if [ -n "${promotion_backup:-}" ]; then
    rm -f "${promotion_backup}"
  fi
  echo "recorded deploy receipt: ${receipt_path}"
}

echo "deploy plan: action=${action} channel=${channel} current=${current_sha:-unset} target=${target_sha} image=${image_repository}:${target_sha}"
if [ "${action}" = "rollback" ] && [ "${dry_run}" = "1" ]; then
  echo "dry-run: stopping before pin write, docker recreate, health gate, and receipt write"
  exit 0
fi
if [ "${action}" = "deploy" ]; then
  deploy_channel_tts_config_preflight "${ROOT}" "${channel}" "${pin_file}" || exit $?
else
  # Rollback must remain reachable even when the caller carries a stale TTS
  # selector whose host directory no longer exists. Bypass deploy validation,
  # pin the tracked disabled fallback, and clear the machine-local root before
  # the first Compose parse so fail-closed bind semantics cannot block recovery.
  DEPLOY_TTS_CONFIG_GOVERNED=1
  DEPLOY_TTS_ENABLED=false
  unset DEPLOY_TTS_HOST_ROOT
  export DEPLOY_TTS_CONFIG_GOVERNED DEPLOY_TTS_ENABLED
fi
migration_from_sha="${current_sha:-}"
if [ "${action}" = "deploy" ] && [ -f "${migration_pending_file}" ]; then
  pending_target="$(read_pending_migration_field TARGET_SHA || true)"
  pending_from="$(read_pending_migration_field FROM_SHA || true)"
  pending_ack="$(read_pending_migration_field ACK_FORWARD_ONLY || true)"
  if [ -z "${pending_target}" ] || [ -z "${pending_from}" ]; then
    echo "migration retry blocked: pending migration marker is incomplete: ${migration_pending_file}" >&2
    exit 88
  fi
  if [ "${pending_target}" != "${target_sha}" ]; then
    echo "migration retry blocked: pending target ${pending_target} must be reconciled before deploying ${target_sha}" >&2
    exit 88
  fi
  if [ "${pending_from}" = "${migration_no_baseline_marker}" ]; then
    # First-ever deploy of this channel: replay the full-tree classification.
    migration_from_sha=""
  else
    migration_from_sha="${pending_from}"
  fi
  if [ "${pending_ack}" = "1" ]; then
    ack_forward_only=1
  fi
  echo "migration retry: revalidating ${migration_from_sha:-<no-baseline>}..${target_sha} from durable pending marker"
fi
migration_gate "${migration_from_sha}" "${target_sha}"

if [ "${dry_run}" = "1" ]; then
  echo "dry-run: stopping before pin write, docker recreate, health gate, and receipt write"
  exit 0
fi

if ! scripts/companion_ui_postdeploy_smoke.sh preflight; then
  echo "companion UI preflight failed before channel mutation" >&2
  exit 86
fi

if [ "${scalar_rollback}" = "1" ]; then
  prepare_scalar_rollback_environment || exit $?
fi

prepare_instance_ownership_host_state_dir

if [ "${action}" = "rollback" ]; then
  INSTANCE_STATE_LEGACY_ROLLBACK=1
else
  INSTANCE_STATE_LEGACY_ROLLBACK=0
fi
export INSTANCE_STATE_LEGACY_ROLLBACK

# Deploy-only by contract (#3903 Constraints): rollback must stay ungated so
# the prior stable ref is always recoverable (DEFINE_ROLLBACK_CONTRACT.md).
if [ "${channel}" = "prod" ] && [ "${action}" = "deploy" ]; then
  prod_pending_retry_preflight || exit 87
fi

# Same deploy-only-by-contract posture as the prod gate above (#4230): dev and
# test never previously ran any Compose environment:-vs-env_file: precedence
# check before mutation.
if { [ "${channel}" = "dev" ] || [ "${channel}" = "test" ]; } && [ "${action}" = "deploy" ]; then
  dev_test_environment_env_file_clobber_preflight || exit 90
fi

ensure_prod_instance_state_volume

DEPLOY_EMBEDDING_REBUILD_REQUIRED_ACK="${ack_embedding_rebuild_required}"
export DEPLOY_EMBEDDING_REBUILD_REQUIRED_ACK

if [ "${action}" = "deploy" ] && [ "${MIGRATIONS_CHECKED}" -gt 0 ]; then
  write_pending_migration "${migration_from_sha}" "${target_sha}"
fi
if [ "${scalar_rollback}" = "1" ]; then
  # Scalar compatibility mode is not a channel downgrade. Keep the capable
  # current image pinned as the durable trusted guard and record the old target
  # in the ordinary rollback anchor, so the same command can resume without an
  # explicit SHA after a crash or partial container establishment.
  write_pin "${previous_pin_file}" "${target_sha}"
elif [ -n "${current_sha}" ] && [ "${current_sha}" != "${target_sha}" ]; then
  # A same-target retry (or same-SHA redeploy) reads current_sha == target_sha
  # because a prior failed attempt already advanced the pin; overwriting the
  # rollback anchor with the failed target would make the true last-known-good
  # SHA unrecoverable through the rollback contract.
  write_pin "${previous_pin_file}" "${current_sha}"
fi
if [ "${scalar_rollback}" != "1" ]; then
  write_pin "${pin_file}" "${target_sha}"
fi
rollback_target_recreated=0

postdeploy_smoke_gate() {
  COMPANION_UI_ALLOW_EMBEDDING_REBUILD_REQUIRED="${ack_embedding_rebuild_required}" \
    COMPANION_UI_EXPECTED_SHA="${target_sha}" \
    scripts/companion_ui_postdeploy_smoke.sh "${channel}"
}

if [ "${scalar_rollback}" = "1" ]; then
  run_postmutation_gate "image pull failed" \
    compose pull scalar-rollback-guard api scalar-rollback-gateway || exit $?
else
  run_postmutation_gate "image pull failed" \
    compose pull api worker watcher heimdal-capture-watch companion-ui || exit $?
fi
if [ "${scalar_rollback}" != "1" ] && [ "${action}" = "deploy" ]; then
  run_postmutation_gate "scalar rollback service retirement failed" \
    retire_scalar_rollback_services || exit $?
fi
if [ "${action}" = "deploy" ]; then
  if prepare_instance_state_deployment compose "${channel}"; then
    :
  else
    instance_state_rc=$?
    exit "${instance_state_rc}"
  fi
fi
run_postmutation_gate "migration execution failed" apply_changed_migrations || exit $?
run_postmutation_gate "service recreate/liveness gate failed" \
  recreate_channel_services || exit $?
rollback_target_recreated=1
if [ "${scalar_rollback}" = "1" ]; then
  run_postmutation_gate "scalar rollback runtime gate failed" \
    scalar_rollback_runtime_gate || exit $?
else
  run_postmutation_gate "embedding provider configuration preflight failed" \
    embedding_provider_preflight_gate || exit $?
  run_postmutation_gate "health gate failed" health_gate || exit $?
  run_postmutation_gate "version gate failed" version_gate || exit $?
  run_postmutation_gate "fleet-model fitness gate failed" \
    fleet_model_fitness_gate || exit $?
  run_postmutation_gate "companion UI post-deploy smoke failed" \
    postdeploy_smoke_gate || exit $?
  run_postmutation_gate "required capture-watch gate failed" \
    capture_watch_gate || exit $?
fi
run_postmutation_gate "deploy receipt creation failed" record_receipt || exit $?
