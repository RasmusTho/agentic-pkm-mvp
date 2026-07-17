#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
source "${ROOT}/scripts/lib/deploy_channel_compose.sh"
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
receipt_dir="${ROOT}/ops/deployments"
promotion_dir="${ROOT}/ops/promotions"
image_repository="${APP_IMAGE_REPOSITORY:-ghcr.io/rasmustho/pkm-app}"
health_timeout="${DEPLOY_HEALTH_TIMEOUT_SECONDS:-90}"

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

current_sha="$(read_pin "${pin_file}" 2>/dev/null || true)"
target_sha="$(resolve_target_sha "${target_sha}")"

list_changed_migrations() {
  local from_sha="$1" to_sha="$2"
  if [ -z "${from_sha}" ] || ! git -C "${ROOT}" rev-parse --verify "${from_sha}^{commit}" >/dev/null 2>&1; then
    find "${ROOT}/app/alembic/versions" -type f -name '*.py' -print 2>/dev/null || true
    return 0
  fi
  git -C "${ROOT}" diff --name-only "${from_sha}..${to_sha}" -- app/alembic/versions \
    | while IFS= read -r path; do
        [ -n "${path}" ] && [ -f "${ROOT}/${path}" ] && printf '%s\n' "${ROOT}/${path}"
      done
}

migration_gate() {
  local from_sha="$1" to_sha="$2" receipt_json forward_count
  local -a migration_paths
  migration_paths=()
  while IFS= read -r path; do
    [ -n "${path}" ] && migration_paths+=("${path}")
  done < <(list_changed_migrations "${from_sha}" "${to_sha}")
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

recreate_channel_services() {
  if [ "${action}" = "deploy" ] && [ "${ack_embedding_rebuild_required}" = "1" ]; then
    # During an acknowledged embedding-dimension cutover, /readyz must stay red
    # until the governed full rebuild completes. Start the runtime first, prove
    # API liveness, then start the gateway without re-applying its service_healthy
    # dependency. The later live smoke still admits only the sole exact
    # embedding_index=rebuild_required transition; the API container healthcheck
    # remains strict on /readyz throughout.
    compose up -d --force-recreate api worker watcher heimdal-capture-watch || return 1
    wait_json_ok "http://127.0.0.1:${api_port}/healthz" || return 1
    compose up -d --force-recreate --no-deps companion-ui || return 1
    return 0
  fi

  compose up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui
}

rollback_failed_startup() {
  local reason="$1"
  echo "${reason}; attempting rollback to previous pin" >&2
  if [ -n "${current_sha}" ]; then
    write_pin "${pin_file}" "${current_sha}"
    if ! compose up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui; then
      echo "rollback recreate failed for previous pin ${current_sha}" >&2
    fi
  fi
}

capture_watch_gate() {
  # Surface a broken heimdal-capture-watch (e.g. missing/invalid HEIMDAL_RAW_STORE_KEY, which
  # its own healthcheck fails loud on) at deploy time instead of letting it sit unhealthy and
  # silent. Deliberately does NOT roll back api/worker: capture-watch runs its own
  # healthcheck/restart loop and must not block unrelated services (docker-compose.yaml). A
  # failure here fails the deploy loudly (non-zero exit) after the api deploy is already recorded.
  local cid deadline status
  cid="$(compose ps -q heimdal-capture-watch 2>/dev/null | head -1)"
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
  # See scripts/prod_deploy_retry_preflight.py and
  # docs/HEALTH.md :: Outbox and dead-letter signals.
  local receipt_json rc=0 dsn_from_file="" runtime_env_ref="" runtime_env_file=""

  # Resolve the channel's governed runtime env file the way the running stack
  # actually resolves it, in the same precedence order Compose interpolation
  # sees: (1) the WATCHER_RUNTIME_ENV_FILE ref in the channel pin file (read
  # via _deploy_channel_env_value, like the shared compose lib); (2) an
  # exported shell WATCHER_RUNTIME_ENV_FILE; (3) the docker-compose.yaml
  # service env_file default `./tmp/runtime.env`. Committed pin files carry
  # only APP_IMAGE_* keys, so on a real host the default in step (3) IS the
  # live configuration -- stopping at step (1) would make this gate skip on
  # every real prod deploy (the round-2 D1 gap). The extracted DSN is
  # injected ONLY into the single preflight subprocess env below -- never
  # exported into this shell, never passed to Compose, never printed (#3875
  # redaction posture). Ambient shell DATABASE_URL/DB_DSN remains the
  # fallback when the resolved file provides none.
  runtime_env_ref="$(_deploy_channel_env_value "${pin_file}" WATCHER_RUNTIME_ENV_FILE)"
  if [ -z "${runtime_env_ref}" ]; then
    # Outside the pinning wrapper, Compose interpolation reads the exported
    # shell value; honor it between the governed pin value and the default.
    # (The wrapper itself pins/unsets this var for the actual service
    # selection -- this fallback only widens the DSN lookup, governed value
    # first.)
    runtime_env_ref="${WATCHER_RUNTIME_ENV_FILE:-}"
  fi
  if [ -z "${runtime_env_ref}" ]; then
    # docker-compose.yaml: `${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}`,
    # resolved against the compose project directory = ${ROOT} (directory of
    # the first -f file; the wrapper also cd's there). Keep this literal in
    # sync with docker-compose.yaml.
    runtime_env_ref="./tmp/runtime.env"
  fi
  if [ -n "${runtime_env_ref}" ]; then
    case "${runtime_env_ref}" in
      /*) runtime_env_file="${runtime_env_ref}" ;;
      ./*) runtime_env_file="${ROOT}/${runtime_env_ref#./}" ;;
      *) runtime_env_file="${ROOT}/${runtime_env_ref}" ;;
    esac
  fi
  if [ -n "${runtime_env_file}" ] && [ -f "${runtime_env_file}" ]; then
    dsn_from_file="$(_deploy_channel_env_value "${runtime_env_file}" DATABASE_URL)"
    if [ -z "${dsn_from_file}" ]; then
      dsn_from_file="$(_deploy_channel_env_value "${runtime_env_file}" DB_DSN)"
    fi
  fi

  if [ -n "${dsn_from_file}" ]; then
    receipt_json="$(DATABASE_URL="${dsn_from_file}" "${PYTHON}" "${ROOT}/scripts/prod_deploy_retry_preflight.py")" || rc=$?
  else
    receipt_json="$("${PYTHON}" "${ROOT}/scripts/prod_deploy_retry_preflight.py")" || rc=$?
  fi

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

version_gate() {
  local version_json health_json version_sha health_sha
  version_json="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/version")"
  health_json="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/api/health")"
  version_sha="$("${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin).get("git_sha", ""))' <<<"${version_json}")"
  health_sha="$("${PYTHON}" -c 'import json,sys; data=json.load(sys.stdin); value=data.get("version"); print(value.get("git_sha", "") if isinstance(value, dict) else (value if isinstance(value, str) else ""))' <<<"${health_json}")"
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
  local receipt_json
  if ! receipt_json="$("${PYTHON}" -m app.release_channels.fleet_model_fitness "${channel}" --root "${ROOT}" --json --require-pinned)"; then
    echo "fleet-model fitness gate failed" >&2
    if [ -n "${receipt_json}" ]; then
      echo "${receipt_json}" >&2
    fi
    return 1
  fi
  FLEET_MODEL_FITNESS_JSON="${receipt_json}"
  export FLEET_MODEL_FITNESS_JSON
}

record_receipt() {
  local receipt_path timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "${receipt_dir}"
  receipt_path="${receipt_dir}/${channel}-latest.json"
  "${PYTHON}" - "$receipt_path" <<PY
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
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
PY
  if [ "${channel}" = "prod" ]; then
    mkdir -p "${promotion_dir}"
    cp "${receipt_path}" "${promotion_dir}/prod-deploy-${target_sha}.json"
  fi
  echo "recorded deploy receipt: ${receipt_path}"
}

echo "deploy plan: action=${action} channel=${channel} current=${current_sha:-unset} target=${target_sha} image=${image_repository}:${target_sha}"
if [ "${action}" = "rollback" ] && [ "${dry_run}" = "1" ]; then
  echo "dry-run: stopping before pin write, docker recreate, health gate, and receipt write"
  exit 0
fi
migration_gate "${current_sha:-}" "${target_sha}"

if [ "${dry_run}" = "1" ]; then
  echo "dry-run: stopping before pin write, docker recreate, health gate, and receipt write"
  exit 0
fi

if ! scripts/companion_ui_postdeploy_smoke.sh preflight; then
  echo "companion UI preflight failed before channel mutation" >&2
  exit 86
fi

# Deploy-only by contract (#3903 Constraints): rollback must stay ungated so
# the prior stable ref is always recoverable (DEFINE_ROLLBACK_CONTRACT.md).
if [ "${channel}" = "prod" ] && [ "${action}" = "deploy" ]; then
  prod_pending_retry_preflight || exit 87
fi

DEPLOY_EMBEDDING_REBUILD_REQUIRED_ACK="${ack_embedding_rebuild_required}"
export DEPLOY_EMBEDDING_REBUILD_REQUIRED_ACK

mkdir -p "$(dirname "${pin_file}")"
if [ -n "${current_sha}" ]; then
  write_pin "${previous_pin_file}" "${current_sha}"
fi
write_pin "${pin_file}" "${target_sha}"

compose pull api worker watcher heimdal-capture-watch companion-ui
if ! recreate_channel_services; then
  rollback_failed_startup "service recreate/liveness gate failed"
  exit 1
fi
if ! health_gate; then
  rollback_failed_startup "health gate failed"
  exit 1
fi
version_gate
fleet_model_fitness_gate
COMPANION_UI_ALLOW_EMBEDDING_REBUILD_REQUIRED="${ack_embedding_rebuild_required}" \
  COMPANION_UI_EXPECTED_SHA="${target_sha}" \
  scripts/companion_ui_postdeploy_smoke.sh "${channel}"
record_receipt
capture_watch_gate || {
  echo "deploy: heimdal-capture-watch is not healthy (api/worker left in place and receipt recorded); resolve its config and re-check" >&2
  exit 1
}
