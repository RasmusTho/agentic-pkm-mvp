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
# shellcheck source=builderops/preflight_app_password_secret.sh
source "${ROOT}/scripts/builderops/preflight_app_password_secret.sh"

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
  local repository postgres_repository local_durability_mode tmp
  repository="$(read_pin "${PIN_FILE}" BUILDEROPS_IMAGE_REPOSITORY)"
  postgres_repository="$(read_pin "${PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_REPOSITORY)"
  local_durability_mode="$(read_pin "${PIN_FILE}" BUILDEROPS_LOCAL_DURABILITY_MODE)"
  tmp="$(mktemp "${file}.tmp.XXXXXX")"
  {
    printf 'BUILDEROPS_IMAGE_REPOSITORY=%s\n' "${repository}"
    printf 'BUILDEROPS_IMAGE_DIGEST=%s\n' "${digest}"
    printf 'BUILDEROPS_SOURCE_SHA=%s\n' "${source_sha}"
    printf 'BUILDEROPS_POSTGRES_IMAGE_REPOSITORY=%s\n' "${postgres_repository}"
    printf 'BUILDEROPS_POSTGRES_IMAGE_DIGEST=%s\n' "${postgres_digest}"
    printf 'BUILDEROPS_DOCKER_CONTEXT=%s\n' "${BUILDEROPS_DOCKER_CONTEXT}"
    printf 'PRODUCT_DOCKER_CONTEXT=%s\n' "${PRODUCT_DOCKER_CONTEXT}"
    printf 'BUILDEROPS_LOCAL_DURABILITY_MODE=%s\n' "${local_durability_mode}"
  } >"${tmp}"
  mv "${tmp}" "${file}"
}

load_contexts() {
  BUILDEROPS_DOCKER_CONTEXT="${BUILDEROPS_DOCKER_CONTEXT:-$(read_pin "${PIN_FILE}" BUILDEROPS_DOCKER_CONTEXT)}"
  PRODUCT_DOCKER_CONTEXT="${PRODUCT_DOCKER_CONTEXT:-$(read_pin "${PIN_FILE}" PRODUCT_DOCKER_CONTEXT)}"
  BUILDEROPS_LOCAL_DURABILITY_MODE="${BUILDEROPS_LOCAL_DURABILITY_MODE:-$(read_pin "${PIN_FILE}" BUILDEROPS_LOCAL_DURABILITY_MODE)}"
  export BUILDEROPS_DOCKER_CONTEXT PRODUCT_DOCKER_CONTEXT BUILDEROPS_LOCAL_DURABILITY_MODE
}

assert_local_durability_posture() {
  [ "${BUILDEROPS_LOCAL_DURABILITY_MODE}" = "rebuildable" ] || {
    echo "local BuilderOps durability mode must be rebuildable; recovery egress is not configured" >&2
    exit 2
  }
}

validate_identity() {
  [[ "${1}" =~ ^[0-9a-f]{40}$ ]] || { echo "source SHA must be 40 lowercase hex characters" >&2; exit 2; }
  [[ "${2}" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "image pin must be an immutable sha256 digest" >&2; exit 2; }
  [[ "${3}" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "PostgreSQL image pin must be an immutable sha256 digest" >&2; exit 2; }
}

load_attested_candidate_pair() {
  local receipt="${1:?candidate pair receipt required}"
  local expected_repository="RasmusTho/agentic-pkm-mvp"
  local expected_workflow="RasmusTho/agentic-pkm-mvp/.github/workflows/app-image-build.yml"
  command -v gh >/dev/null 2>&1 || {
    echo "gh CLI is required to verify the BuilderOps candidate pair attestation" >&2
    exit 69
  }
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
    "durability_posture": "rebuildable",
    "platform": "linux/amd64",
}
if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in expected.items()):
    raise SystemExit("candidate pair receipt has invalid trusted provenance")
source_sha = payload.get("source_sha")
control = payload.get("control_plane_image_digest")
postgres = payload.get("postgres_image_digest")
if not isinstance(source_sha, str) or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
    raise SystemExit("candidate pair receipt has invalid source SHA")
for name, value in (("control-plane", control), ("PostgreSQL", postgres)):
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise SystemExit(f"candidate pair receipt has invalid {name} digest")
print(source_sha, control, postgres, sep="\t")
PY
  )
  gh attestation verify "${receipt}" \
    --repo "${expected_repository}" \
    --signer-workflow "${expected_workflow}" \
    --source-ref refs/heads/main \
    --source-digest "${target_sha}" >/dev/null
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
    "postgres_image_digest": os.environ["POSTGRES_IMAGE_DIGEST"],
    "previous_image_digest": os.environ["PREVIOUS_DIGEST"],
    "previous_postgres_image_digest": os.environ["PREVIOUS_POSTGRES_DIGEST"],
    "schema_version": ready["database"]["schema_version"],
    "authority_epoch": ready["database"]["authority_epoch"],
    "private_ingress": "tailscale-serve-https-loopback-no-funnel",
    "readiness_authentication": "scoped-bearer-over-loopback",
    "migration_completed": True,
    "authority_fencing_required": True,
    "dual_writer": "forbidden",
    "external_effect_reconciliation_required": True,
    "rollback_data_rewind": "forbidden",
    "recorded_at": os.environ["RECORDED_AT"],
    "database_rebuild_required": False,
}
path = Path(sys.argv[1])
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
(path.parent / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
PY
  echo "recorded BuilderOps ${action} receipt: ${path}"
}

record_preflight_refusal() {
  local reason_code="${1:?refusal reason required}" exit_code="${2:?refusal exit code required}"
  local source_sha="${3:-}" image_digest="${4:-}" postgres_digest="${5:-}" timestamp path
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "${RECEIPT_DIR}"
  path="${RECEIPT_DIR}/${timestamp}-preflight-refused.json"
  REASON_CODE="${reason_code}" EXIT_CODE="${exit_code}" SOURCE_SHA="${source_sha}" IMAGE_DIGEST="${image_digest}" POSTGRES_IMAGE_DIGEST="${postgres_digest}" \
    BUILDER_ENGINE_ID="${BUILDEROPS_OBSERVED_BUILDER_ENGINE_ID:-}" PRODUCT_ENGINE_ID="${BUILDEROPS_OBSERVED_PRODUCT_ENGINE_ID:-}" \
    OBSERVED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" python3 - "${path}" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

payload = {
    "receipt_type": "builderops_vm_rebuild_activation.v1",
    "receipt_version": 1,
    "target_vm": {"vmid": 102, "name": "builder-system"},
    "observed_at": os.environ["OBSERVED_AT"],
    "source_refs": [
        "repo:docs/BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract",
        "repo:scripts/deploy_builderops.sh#builderops_assert_failure_domain",
    ],
    "candidate_identity": {
        "source_sha": os.environ["SOURCE_SHA"] or None,
        "control_plane_image_digest": os.environ["IMAGE_DIGEST"] or None,
        "postgres_image_digest": os.environ["POSTGRES_IMAGE_DIGEST"] or None,
    },
    "selected_engine": {
        "context": os.environ["BUILDEROPS_DOCKER_CONTEXT"],
        "project": "builderops-control-plane",
        "engine_id": os.environ["BUILDER_ENGINE_ID"] or None,
    },
    "observed_engine_ids": {
        "builderops": os.environ["BUILDER_ENGINE_ID"] or None,
        "product": os.environ["PRODUCT_ENGINE_ID"] or None,
    },
    "activation_verdict": "refused",
    "activation_proven": False,
    "fencing_proven": False,
    "no_dual_writer_proven": False,
    "mutation_performed": False,
    "secret_material": "absent",
    "gaps": [
        "activation_not_proven",
        "fencing_not_proven",
        "no_dual_writer_not_proven",
    ],
    "refusals": [
        os.environ["REASON_CODE"],
        "no_mutation_performed",
    ],
    "preflight_exit_code": int(os.environ["EXIT_CODE"]),
}
payload["evidence_fingerprint"] = hashlib.sha256(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
path = Path(sys.argv[1])
serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
path.write_text(serialized, encoding="utf-8")
(path.parent / "latest.json").write_text(serialized, encoding="utf-8")
PY
  echo "recorded BuilderOps preflight refusal receipt: ${path}" >&2
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
if builderops_assert_failure_domain; then
  :
else
  failure_domain_exit=$?
  failure_domain_reason="${BUILDEROPS_FAILURE_DOMAIN_REASON:-}"
  if [ -z "${failure_domain_reason}" ]; then
    case "${failure_domain_exit}" in
      70) failure_domain_reason="builderops_product_contexts_must_differ" ;;
      71) failure_domain_reason="builderops_product_engines_must_differ" ;;
      72) failure_domain_reason="product_project_on_builderops_engine" ;;
      73) failure_domain_reason="builderops_project_on_product_engine" ;;
      74) failure_domain_reason="duplicate_builderops_engine_writers" ;;
      75) failure_domain_reason="invalid_docker_project_listing" ;;
      *) failure_domain_reason="failure_domain_preflight_refused" ;;
    esac
  fi
  record_preflight_refusal "${failure_domain_reason}" "${failure_domain_exit}" "${target_sha}" "${target_digest}" "${target_postgres_digest}"
  exit "${failure_domain_exit}"
fi
assert_local_durability_posture
"${ROOT}/scripts/builderops/configure_tailnet_tls.sh" --preflight

placeholder_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000"
pin_backup="$(mktemp "${PIN_FILE}.rollback.XXXXXX")"
cp "${PIN_FILE}" "${pin_backup}"

activate_target() {
  builderops_preflight_app_password_secret || return
  write_pin "${PIN_FILE}" "${target_sha}" "${target_digest}" "${target_postgres_digest}" || return
  builderops_compose "${ROOT}" pull db api worker migrate || return
  builderops_compose "${ROOT}" up -d db || return
  builderops_compose "${ROOT}" up --abort-on-container-exit --exit-code-from migrate migrate || return
  builderops_compose "${ROOT}" up -d --force-recreate api worker || return
  wait_ready || return
  "${ROOT}/scripts/builderops/configure_tailnet_tls.sh" || return
}

reactivate_previous_release() {
  builderops_preflight_app_password_secret || return
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
