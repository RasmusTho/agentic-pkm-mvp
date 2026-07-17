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
  echo "usage: scripts/deploy_builderops.sh deploy <attested-candidate-pair-receipt.json> | rollback" >&2
  exit 2
}

read_pin() {
  local file="${1:?pin file required}" key="${2:?key required}"
  awk -F= -v key="${key}" '$1 == key {print substr($0, length(key) + 2); exit}' "${file}"
}

write_pin() {
  local file="${1:?pin file required}" source_sha="${2:?source SHA required}" digest="${3:?digest required}" postgres_digest="${4:?postgres digest required}"
  local repository postgres_repository tmp
  repository="$(read_pin "${PIN_FILE}" BUILDEROPS_IMAGE_REPOSITORY)"
  postgres_repository="$(read_pin "${PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_REPOSITORY)"
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
  [[ "${3}" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "PostgreSQL/WAL-G image pin must be an immutable sha256 digest" >&2; exit 2; }
}

load_attested_candidate_pair() {
  local receipt="${1:?candidate pair receipt required}"
  local expected_repository="RasmusTho/agentic-pkm-mvp"
  local expected_workflow="RasmusTho/agentic-pkm-mvp/.github/workflows/app-image-build.yml"
  command -v gh >/dev/null 2>&1 || {
    echo "gh CLI is required to verify the BuilderOps candidate pair attestation" >&2
    exit 69
  }
  gh attestation verify "${receipt}" \
    --repo "${expected_repository}" \
    --signer-workflow "${expected_workflow}" >/dev/null
  IFS=$'\t' read -r target_sha target_digest target_postgres_digest < <(
    python3 - "${receipt}" <<'PY'
import json
import re
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {
    "receipt_version": 1,
    "repository": "RasmusTho/agentic-pkm-mvp",
    "workflow": ".github/workflows/app-image-build.yml",
    "event_name": "push",
    "source_ref": "refs/heads/main",
    "restore_gate": "encrypted-full-backup-plus-archived-wal",
    "platform": "linux/amd64",
}
if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in expected.items()):
    raise SystemExit("candidate pair receipt has invalid trusted provenance")
source_sha = payload.get("source_sha")
control = payload.get("control_plane_image_digest")
postgres = payload.get("postgres_walg_image_digest")
if not isinstance(source_sha, str) or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
    raise SystemExit("candidate pair receipt has invalid source SHA")
for name, value in (("control-plane", control), ("PostgreSQL/WAL-G", postgres)):
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise SystemExit(f"candidate pair receipt has invalid {name} digest")
print(source_sha, control, postgres, sep="\t")
PY
  )
  export target_sha target_digest target_postgres_digest
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
  local action="${1}" source_sha="${2}" digest="${3}" postgres_digest="${4}" previous_digest="${5}" previous_postgres_digest="${6}" engine_id timestamp path
  engine_id="$(builderops_engine_id "${BUILDEROPS_DOCKER_CONTEXT}")"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "${RECEIPT_DIR}"
  path="${RECEIPT_DIR}/${timestamp}-${action}.json"
  ACTION="${action}" SOURCE_SHA="${source_sha}" IMAGE_DIGEST="${digest}" POSTGRES_IMAGE_DIGEST="${postgres_digest}" PREVIOUS_DIGEST="${previous_digest}" PREVIOUS_POSTGRES_DIGEST="${previous_postgres_digest}" \
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
    "postgres_walg_image_digest": os.environ["POSTGRES_IMAGE_DIGEST"],
    "previous_image_digest": os.environ["PREVIOUS_DIGEST"],
    "previous_postgres_walg_image_digest": os.environ["PREVIOUS_POSTGRES_DIGEST"],
    "schema_version": ready["database"]["schema_version"],
    "authority_epoch": ready["database"]["authority_epoch"],
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
current_postgres_digest="$(read_pin "${PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_DIGEST)"

case "${action}" in
  deploy)
    [ "$#" -eq 2 ] || usage
    load_attested_candidate_pair "${2}"
    ;;
  rollback)
    [ "$#" -eq 1 ] || usage
    [ -f "${PREVIOUS_PIN_FILE}" ] || { echo "previous BuilderOps pin is unavailable" >&2; exit 2; }
    target_sha="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_SOURCE_SHA)"
    target_digest="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_IMAGE_DIGEST)"
    target_postgres_digest="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_DIGEST)"
    ;;
  *) usage ;;
esac

validate_identity "${target_sha}" "${target_digest}" "${target_postgres_digest}"
builderops_assert_failure_domain
builderops_validate_recovery_target "${ROOT}"
"${ROOT}/scripts/builderops/configure_tailnet_tls.sh" --preflight

placeholder_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000"
pin_backup="$(mktemp "${PIN_FILE}.rollback.XXXXXX")"
cp "${PIN_FILE}" "${pin_backup}"

activate_target() {
  write_pin "${PIN_FILE}" "${target_sha}" "${target_digest}" "${target_postgres_digest}" || return
  builderops_compose "${ROOT}" pull db api worker migrate || return
  builderops_compose "${ROOT}" up -d db || return
  builderops_compose "${ROOT}" up --abort-on-container-exit --exit-code-from migrate migrate || return
  builderops_compose "${ROOT}" up -d --force-recreate api worker || return
  wait_ready || return
  "${ROOT}/scripts/builderops/configure_tailnet_tls.sh" || return
}

reactivate_previous_release() {
  cp "${pin_backup}" "${PIN_FILE}" || return
  builderops_compose "${ROOT}" pull db api worker || return
  builderops_compose "${ROOT}" up -d --force-recreate db api worker || return
  wait_ready || return
}

if ! activate_target; then
  if ! reactivate_previous_release; then
    rm -f "${pin_backup}"
    echo "CRITICAL: BuilderOps target activation failed and the previous live release could not be restored" >&2
    exit 1
  fi
  rm -f "${pin_backup}"
  echo "BuilderOps activation gate failed; previous pin and live API/worker release restored without rewinding the database" >&2
  exit 1
fi

if [ "${action}" = deploy ] && [ "${current_digest}" != "${placeholder_digest}" ]; then
  cp "${pin_backup}" "${PREVIOUS_PIN_FILE}"
fi
rm -f "${pin_backup}"
record_receipt "${action}" "${target_sha}" "${target_digest}" "${target_postgres_digest}" "${current_digest}" "${current_postgres_digest}"
