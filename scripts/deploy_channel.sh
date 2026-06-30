#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
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
  scripts/deploy_channel.sh deploy <dev|test|prod> <sha> [--dry-run] [--ack-forward-only]
  scripts/deploy_channel.sh rollback <dev|test|prod> [sha] [--dry-run]

Environment:
  DEPLOY_DRY_RUN=1                  print the plan and stop before writes/docker
  DEPLOY_ACK_FORWARD_ONLY=1         acknowledge forward-only migrations
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
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --ack-forward-only) ack_forward_only=1 ;;
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
  printf 'APP_IMAGE_REPOSITORY=%s\nAPP_IMAGE_TAG=%s\n' "${image_repository}" "${sha}" >"${file}"
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
}

compose() {
  (
    cd "${ROOT}" || exit 1
    docker compose \
      --env-file "config/deploy/${channel}.env" \
      -f docker-compose.yaml \
      -f "${compose_overlay}" \
      -p "${compose_project}" \
      "$@"
  )
}

wait_json_ok() {
  local url="$1" deadline body
  deadline=$((SECONDS + health_timeout))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    if body="$(curl -fsS --max-time 3 "${url}" 2>/dev/null)"; then
      if "${PYTHON}" -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") is True else 1)' <<<"${body}"; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

health_gate() {
  wait_json_ok "http://127.0.0.1:${api_port}/healthz" || return 1
  curl -fsS --max-time 3 "http://127.0.0.1:${ui_port}/healthz" >/dev/null
}

version_gate() {
  local version_json health_json version_sha health_sha
  version_json="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/version")"
  health_json="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/api/health")"
  version_sha="$("${PYTHON}" -c 'import json,sys; print(json.load(sys.stdin).get("git_sha", ""))' <<<"${version_json}")"
  health_sha="$("${PYTHON}" -c 'import json,sys; print((json.load(sys.stdin).get("version") or {}).get("git_sha", ""))' <<<"${health_json}")"
  [ "${version_sha}" = "${target_sha}" ] || {
    echo "/version reported ${version_sha}, expected ${target_sha}" >&2
    return 1
  }
  [ "${health_sha}" = "${target_sha}" ] || {
    echo "/api/health version reported ${health_sha}, expected ${target_sha}" >&2
    return 1
  }
}

record_receipt() {
  local receipt_path timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "${receipt_dir}"
  receipt_path="${receipt_dir}/${channel}-latest.json"
  "${PYTHON}" - "$receipt_path" <<PY
import json
import sys
from pathlib import Path

payload = {
    "channel": "${channel}",
    "action": "${action}",
    "sha": "${target_sha}",
    "previous_sha": "${current_sha}",
    "image": "${image_repository}:${target_sha}",
    "recorded_at": "${timestamp}",
    "migration_receipt": json.loads('''${MIGRATION_RECEIPT_JSON:-{"migrations_checked":0,"reversible":[],"forward_only":[],"classification_decisions":[]}}'''),
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
migration_gate "${current_sha:-}" "${target_sha}"

if [ "${dry_run}" = "1" ]; then
  echo "dry-run: stopping before pin write, docker recreate, health gate, and receipt write"
  exit 0
fi

mkdir -p "$(dirname "${pin_file}")"
if [ -n "${current_sha}" ]; then
  write_pin "${previous_pin_file}" "${current_sha}"
fi
write_pin "${pin_file}" "${target_sha}"

compose pull api worker watcher companion-ui
compose up -d --force-recreate api worker watcher companion-ui
health_gate || {
  echo "health gate failed; attempting rollback to previous pin" >&2
  if [ -n "${current_sha}" ]; then
    write_pin "${pin_file}" "${current_sha}"
    compose up -d --force-recreate api worker watcher companion-ui || true
  fi
  exit 1
}
version_gate
scripts/companion_ui_postdeploy_smoke.sh "${channel}"
record_receipt
