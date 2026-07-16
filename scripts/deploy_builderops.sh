#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PIN_FILE="${BUILDEROPS_PIN_FILE:-${ROOT}/config/deploy/builderops.env}"
PREVIOUS_PIN_FILE="${BUILDEROPS_PREVIOUS_PIN_FILE:-${ROOT}/config/deploy/builderops.previous.env}"
RECEIPT_DIR="${BUILDEROPS_RECEIPT_DIR:-${ROOT}/ops/deployments/builderops}"
BUILDEROPS_PIN_FILE="${PIN_FILE}"
export BUILDEROPS_PIN_FILE

# shellcheck source=lib/builderops_compose.sh
source "${ROOT}/scripts/lib/builderops_compose.sh"

usage() {
  echo "usage: scripts/deploy_builderops.sh deploy <source-sha> <sha256:digest> | rollback" >&2
  exit 2
}

read_pin() {
  local file="${1:?pin file required}" key="${2:?key required}"
  awk -F= -v key="${key}" '$1 == key {print substr($0, length(key) + 2); exit}' "${file}"
}

write_pin() {
  local file="${1:?pin file required}" source_sha="${2:?source SHA required}" digest="${3:?digest required}"
  local repository postgres_repository postgres_digest tmp
  repository="$(read_pin "${PIN_FILE}" BUILDEROPS_IMAGE_REPOSITORY)"
  postgres_repository="$(read_pin "${PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_REPOSITORY)"
  postgres_digest="$(read_pin "${PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_DIGEST)"
  tmp="$(mktemp "${file}.tmp.XXXXXX")"
  {
    printf 'BUILDEROPS_IMAGE_REPOSITORY=%s\n' "${repository}"
    printf 'BUILDEROPS_IMAGE_DIGEST=%s\n' "${digest}"
    printf 'BUILDEROPS_SOURCE_SHA=%s\n' "${source_sha}"
    printf 'BUILDEROPS_POSTGRES_IMAGE_REPOSITORY=%s\n' "${postgres_repository}"
    printf 'BUILDEROPS_POSTGRES_IMAGE_DIGEST=%s\n' "${postgres_digest}"
    printf 'BUILDEROPS_DOCKER_CONTEXT=%s\n' "${BUILDEROPS_DOCKER_CONTEXT}"
    printf 'PRODUCT_DOCKER_CONTEXT=%s\n' "${PRODUCT_DOCKER_CONTEXT}"
  } >"${tmp}"
  mv "${tmp}" "${file}"
}

load_contexts() {
  BUILDEROPS_DOCKER_CONTEXT="${BUILDEROPS_DOCKER_CONTEXT:-$(read_pin "${PIN_FILE}" BUILDEROPS_DOCKER_CONTEXT)}"
  PRODUCT_DOCKER_CONTEXT="${PRODUCT_DOCKER_CONTEXT:-$(read_pin "${PIN_FILE}" PRODUCT_DOCKER_CONTEXT)}"
  export BUILDEROPS_DOCKER_CONTEXT PRODUCT_DOCKER_CONTEXT
}

validate_identity() {
  [[ "${1}" =~ ^[0-9a-f]{40}$ ]] || { echo "source SHA must be 40 lowercase hex characters" >&2; exit 2; }
  [[ "${2}" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "image pin must be an immutable sha256 digest" >&2; exit 2; }
}

wait_ready() {
  local token_file="${BUILDEROPS_PROBE_TOKEN_FILE:?BuilderOps probe token file is required}"
  local token deadline body
  token="$(<"${token_file}")"
  deadline=$((SECONDS + ${BUILDEROPS_HEALTH_TIMEOUT_SECONDS:-90}))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    # Pass the bearer header over an inherited descriptor, never argv or a
    # durable curl config/log surface.
    if body="$(curl -fsS --max-time 3 --config /dev/fd/3 \
      "http://127.0.0.1:${BUILDEROPS_API_PORT:-18100}/readyz" \
      3<<<"header = \"Authorization: Bearer ${token}\"" 2>/dev/null)" \
      && python3 -c 'import json,sys; p=json.load(sys.stdin); assert p.get("ready") is True' <<<"${body}"; then
      READY_JSON="${body}"
      export READY_JSON
      return 0
    fi
    sleep 2
  done
  return 1
}

record_receipt() {
  local action="${1}" source_sha="${2}" digest="${3}" previous_digest="${4}" engine_id timestamp path
  engine_id="$(builderops_engine_id "${BUILDEROPS_DOCKER_CONTEXT}")"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "${RECEIPT_DIR}"
  path="${RECEIPT_DIR}/${timestamp}-${action}.json"
  ACTION="${action}" SOURCE_SHA="${source_sha}" IMAGE_DIGEST="${digest}" PREVIOUS_DIGEST="${previous_digest}" \
    ENGINE_ID="${engine_id}" RECORDED_AT="${timestamp}" python3 - "${path}" <<'PY'
import json
import os
import sys
from pathlib import Path

ready = json.loads(os.environ["READY_JSON"])
payload = {
    "receipt_version": 1,
    "action": os.environ["ACTION"],
    "project": "builderops-control-plane",
    "engine_context": os.environ["BUILDEROPS_DOCKER_CONTEXT"],
    "engine_id": os.environ["ENGINE_ID"],
    "source_sha": os.environ["SOURCE_SHA"],
    "image_digest": os.environ["IMAGE_DIGEST"],
    "previous_image_digest": os.environ["PREVIOUS_DIGEST"],
    "schema_version": ready["schema_version"],
    "authority_epoch": ready["authority_epoch"],
    "recorded_at": os.environ["RECORDED_AT"],
    "database_restore_performed": False,
}
path = Path(sys.argv[1])
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(path.parent / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
PY
  echo "recorded BuilderOps ${action} receipt: ${path}"
}

action="${1:-}"
load_contexts
current_sha="$(read_pin "${PIN_FILE}" BUILDEROPS_SOURCE_SHA)"
current_digest="$(read_pin "${PIN_FILE}" BUILDEROPS_IMAGE_DIGEST)"

case "${action}" in
  deploy)
    [ "$#" -eq 3 ] || usage
    target_sha="${2}"
    target_digest="${3}"
    ;;
  rollback)
    [ "$#" -eq 1 ] || usage
    [ -f "${PREVIOUS_PIN_FILE}" ] || { echo "previous BuilderOps pin is unavailable" >&2; exit 2; }
    target_sha="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_SOURCE_SHA)"
    target_digest="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_IMAGE_DIGEST)"
    ;;
  *) usage ;;
esac

validate_identity "${target_sha}" "${target_digest}"
builderops_assert_failure_domain
builderops_validate_recovery_target "${ROOT}"

placeholder_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000"
if [ "${action}" = deploy ] && [ "${current_digest}" != "${placeholder_digest}" ]; then
  cp "${PIN_FILE}" "${PREVIOUS_PIN_FILE}"
fi
write_pin "${PIN_FILE}" "${target_sha}" "${target_digest}"

builderops_compose "${ROOT}" pull db api worker migrate
builderops_compose "${ROOT}" up -d db
builderops_compose "${ROOT}" up --abort-on-container-exit --exit-code-from migrate migrate
builderops_compose "${ROOT}" up -d --force-recreate api worker
if ! wait_ready; then
  echo "BuilderOps readiness gate failed; authoritative database was not restored or rewound" >&2
  exit 1
fi
record_receipt "${action}" "${target_sha}" "${target_digest}" "${current_digest}"
