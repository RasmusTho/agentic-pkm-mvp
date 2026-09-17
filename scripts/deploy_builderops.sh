#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PIN_FILE="${BUILDEROPS_PIN_FILE:-${ROOT}/config/deploy/builderops.env}"
PREVIOUS_PIN_FILE="${BUILDEROPS_PREVIOUS_PIN_FILE:-${ROOT}/config/deploy/builderops.previous.env}"
RECEIPT_DIR="${BUILDEROPS_RECEIPT_DIR:-${ROOT}/ops/deployments/builderops}"
# This host-local path is intentionally fixed so callers cannot select
# different lock files and run concurrent deployments under separate locks.
LOCK_PATH="/tmp/agentic-pkm-mvp-builderops-lock/deployment.lock"
BUILDEROPS_PIN_FILE="${PIN_FILE}"
export BUILDEROPS_PIN_FILE

# shellcheck source=lib/builderops_compose.sh
source "${ROOT}/scripts/lib/builderops_compose.sh"
# shellcheck source=builderops/preflight_app_password_secret.sh
source "${ROOT}/scripts/builderops/preflight_app_password_secret.sh"

# Keep the duplicate-writer snapshot and every subsequent pin/Compose/Tailscale
# mutation in one host-local critical section. Re-entry is accepted only when
# the lock helper passes an inherited descriptor whose lock is still held;
# argv/environment markers alone cannot bypass the interlock.
if [ -z "${BUILDEROPS_DEPLOYMENT_LOCK_FD:-}" ]; then
  exec python3 "${ROOT}/scripts/builderops/deployment_lock.py" \
    --lock-path "${LOCK_PATH}" \
    -- bash "${BASH_SOURCE[0]}" "$@"
fi

python3 "${ROOT}/scripts/builderops/deployment_lock.py" \
  --lock-path "${LOCK_PATH}" \
  --assert-held --fd "${BUILDEROPS_DEPLOYMENT_LOCK_FD}" || {
  echo "BuilderOps deployment interlock proof is missing or invalid" >&2
  exit 75
}

usage() {
  echo "usage: scripts/deploy_builderops.sh deploy <attested-candidate-pair-receipt.json> | rollback | unattended-deploy <attested-candidate-pair-receipt.json> | unattended-rollback" >&2
  exit 2
}

read_pin() {
  local file="${1:?pin file required}" key="${2:?key required}"
  awk -F= -v key="${key}" '$1 == key {print substr($0, length(key) + 2); exit}' "${file}"
}

write_pin() {
  local file="${1:?pin file required}" source_sha="${2:?source SHA required}" digest="${3:?digest required}" postgres_digest="${4:?postgres digest required}" candidate_receipt_sha="${5:-}"
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
    printf 'BUILDEROPS_CANDIDATE_RECEIPT_SHA=%s\n' "${candidate_receipt_sha}"
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

archive_candidate_receipt() {
  local source="${1:?candidate receipt source required}" receipt_sha="${2:?candidate receipt SHA required}"
  RECEIPT_DIR="${RECEIPT_DIR}" SOURCE="${source}" RECEIPT_SHA="${receipt_sha}" python3 - <<'PY'
import hashlib
import os
import stat
import tempfile
from pathlib import Path

receipt_dir = Path(os.environ["RECEIPT_DIR"])
source = Path(os.environ["SOURCE"])
receipt_sha = os.environ["RECEIPT_SHA"]
raw = source.read_bytes()
if hashlib.sha256(raw).hexdigest() != receipt_sha:
    raise SystemExit("candidate receipt changed after attestation")
candidate_dir = receipt_dir / "candidate-pairs"
candidate_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
if os.environ.get("BUILDEROPS_AUTHORIZATION_MODE") == "unattended":
    if not candidate_dir.is_absolute():
        raise SystemExit("unattended candidate receipt directory must be absolute")
    current = candidate_dir
    while True:
        metadata = current.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0:
            raise SystemExit("unattended candidate receipt directory must be root-owned")
        if metadata.st_mode & 0o022:
            raise SystemExit("unattended candidate receipt directory must not be writable")
        if current == Path("/"):
            break
        current = current.parent
target = candidate_dir / f"{receipt_sha}.json"
descriptor, temporary = tempfile.mkstemp(dir=candidate_dir, prefix=f".{target.name}.tmp.")
try:
    os.fchmod(descriptor, 0o640)
    if os.geteuid() == 0:
        os.fchown(descriptor, 0, 0)
    with os.fdopen(descriptor, "wb") as stream:
        descriptor = -1
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    temporary = ""
finally:
    if descriptor >= 0:
        os.close(descriptor)
    if temporary:
        Path(temporary).unlink(missing_ok=True)
PY
}

snapshot_candidate_receipt() {
  local source="${1:?candidate receipt source required}"
  RECEIPT_DIR="${RECEIPT_DIR}" SOURCE="${source}" python3 - <<'PY'
import os
import stat
import tempfile
from pathlib import Path

receipt_dir = Path(os.environ["RECEIPT_DIR"])
source = Path(os.environ["SOURCE"])
descriptor = os.open(source, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
try:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("candidate receipt must be a regular file")
    raw = os.read(descriptor, metadata.st_size)
finally:
    os.close(descriptor)
candidate_dir = receipt_dir / "candidate-pairs"
candidate_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
if os.environ.get("BUILDEROPS_AUTHORIZATION_MODE") == "unattended":
    if not candidate_dir.is_absolute():
        raise SystemExit("unattended candidate receipt directory must be absolute")
    current = candidate_dir
    while True:
        metadata = current.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0:
            raise SystemExit("unattended candidate receipt directory must be root-owned")
        if metadata.st_mode & 0o022:
            raise SystemExit("unattended candidate receipt directory must not be writable")
        if current == Path("/"):
            break
        current = current.parent
descriptor, temporary = tempfile.mkstemp(
    dir=candidate_dir,
    prefix=f".{source.name}.snapshot.",
    suffix=".json",
)
try:
    os.fchmod(descriptor, 0o640)
    if os.geteuid() == 0:
        os.fchown(descriptor, 0, 0)
    with os.fdopen(descriptor, "wb") as stream:
        descriptor = -1
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(temporary)
    temporary = ""
finally:
    if descriptor >= 0:
        os.close(descriptor)
    if temporary:
        Path(temporary).unlink(missing_ok=True)
PY
}

load_attested_candidate_pair() {
  local receipt="${1:?candidate pair receipt required}"
  local expected_repository="RasmusTho/agentic-pkm-mvp"
  local expected_workflow="RasmusTho/agentic-pkm-mvp/.github/workflows/app-image-build.yml"
  local builderops_socket snapshot_receipt
  snapshot_receipt="$(snapshot_candidate_receipt "${receipt}")" || {
    record_preflight_refusal "candidate_receipt_snapshot_refused" 75
    exit 75
  }
  candidate_snapshot="${snapshot_receipt}"
  trap 'if [ -n "${candidate_snapshot:-}" ]; then rm -f -- "${candidate_snapshot}"; fi' EXIT
  command -v gh >/dev/null 2>&1 || {
    echo "gh CLI is required to verify the BuilderOps candidate pair attestation" >&2
    exit 69
  }
  IFS=$'\t' read -r target_sha target_digest target_postgres_digest < <(
    python3 - "${snapshot_receipt}" <<'PY'
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
  target_receipt_sha="$(python3 - "${snapshot_receipt}" <<'PY'
import hashlib
import sys
from pathlib import Path

print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
  target_receipt_file="${snapshot_receipt}"
  [ "${BUILDEROPS_DOCKER_CONTEXT}" = "builderops" ] || {
    echo "BuilderOps attestation must run with the fixed VM 102 builderops context" >&2
    exit 75
  }
  builderops_socket="$(docker context inspect --format '{{.Endpoints.docker.Host}}' builderops 2>/dev/null)" || {
    echo "BuilderOps attestation requires the local VM 102 Docker context" >&2
    exit 75
  }
  [ "${builderops_socket}" = "unix:///run/docker-builderops.sock" ] || {
    echo "BuilderOps attestation requires the local VM 102 Docker context" >&2
    exit 75
  }
  gh attestation verify "${snapshot_receipt}" \
    --repo "${expected_repository}" \
    --signer-workflow "${expected_workflow}" \
    --source-ref refs/heads/main \
    --source-digest "${target_sha}" >/dev/null
  archive_candidate_receipt "${target_receipt_file}" "${target_receipt_sha}" || {
    record_preflight_refusal "candidate_receipt_archive_refused" 75 "${target_sha}" "${target_digest}" "${target_postgres_digest}"
    exit 75
  }
  target_receipt_file="${RECEIPT_DIR}/candidate-pairs/${target_receipt_sha}.json"
  rm -f -- "${candidate_snapshot}"
  candidate_snapshot=""
  export target_sha target_digest target_postgres_digest target_receipt_sha target_receipt_file
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

BUILDEROPS_LOOPBACK_FORWARDER_SERVICE="builderops-loopback-forwarder.service"

preflight_loopback_forwarder() {
  local service="${BUILDEROPS_LOOPBACK_FORWARDER_SERVICE}" systemctl_bin unit_state
  systemctl_bin="$(command -v systemctl)" || {
    echo "BuilderOps loopback forwarder refresh requires systemctl" >&2
    return 75
  }
  [ -x "${systemctl_bin}" ] || {
    echo "BuilderOps loopback forwarder requires an executable systemctl" >&2
    return 75
  }
  unit_state="$("${systemctl_bin}" show --property=LoadState --value "${service}")" || {
    echo "BuilderOps loopback forwarder unit preflight failed for ${service}" >&2
    return 75
  }
  [ "${unit_state}" = "loaded" ] || {
    echo "BuilderOps loopback forwarder unit is not loaded: ${service} (${unit_state})" >&2
    return 75
  }
  "${systemctl_bin}" restart "${service}" || {
    echo "BuilderOps loopback forwarder refresh failed" >&2
    return 75
  }
}

refresh_loopback_forwarder() {
  local service="${BUILDEROPS_LOOPBACK_FORWARDER_SERVICE}" systemctl_bin
  systemctl_bin="$(command -v systemctl)" || {
    echo "BuilderOps loopback forwarder refresh requires systemctl" >&2
    return 75
  }
  [ -x "${systemctl_bin}" ] || {
    echo "BuilderOps loopback forwarder refresh requires an executable systemctl" >&2
    return 75
  }
  "${systemctl_bin}" restart "${service}" || {
    echo "BuilderOps loopback forwarder refresh failed" >&2
    return 75
  }
}

record_receipt() {
  local action="${1}" source_sha="${2}" digest="${3}" postgres_digest="${4}" previous_digest="${5}" previous_postgres_digest="${6}" engine_id timestamp path
  engine_id="$(builderops_engine_id "${BUILDEROPS_DOCKER_CONTEXT}")"
  builderops_valid_engine_id "${engine_id}" || {
    echo "BuilderOps Docker engine info is invalid or unavailable while recording receipt" >&2
    return 75
  }
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "${RECEIPT_DIR}"
  path="${RECEIPT_DIR}/${timestamp}-${action}.json"
  ACTION="${action}" SOURCE_SHA="${source_sha}" IMAGE_DIGEST="${digest}" POSTGRES_IMAGE_DIGEST="${postgres_digest}" PREVIOUS_DIGEST="${previous_digest}" PREVIOUS_POSTGRES_DIGEST="${previous_postgres_digest}" \
    CANDIDATE_RECEIPT_SHA="${target_receipt_sha:-}" CANDIDATE_RECEIPT_FILE="${target_receipt_file:-}" \
    ENGINE_ID="${engine_id}" RECORDED_AT="${timestamp}" python3 - "${path}" <<'PY'
import json
import hashlib
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
    "candidate_receipt_sha": os.environ.get("CANDIDATE_RECEIPT_SHA"),
    "authorization_mode": os.environ.get("BUILDEROPS_AUTHORIZATION_MODE", "manual"),
    "authorization_fingerprint": os.environ.get("BUILDEROPS_AUTHORIZATION_FINGERPRINT"),
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
    "receipt_type": "builderops_vm_rebuild_activation_refusal.v1",
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
    "authorization_mode": os.environ.get("BUILDEROPS_AUTHORIZATION_MODE", "manual"),
    "authorization_fingerprint": os.environ.get("BUILDEROPS_AUTHORIZATION_FINGERPRINT"),
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

requested_action="${1:-}"
authorization_mode="manual"
case "${requested_action}" in
  unattended-deploy)
    authorization_mode="unattended"
    action="deploy"
    ;;
  unattended-rollback)
    authorization_mode="unattended"
    action="rollback"
    ;;
  *)
    action="${requested_action}"
    ;;
esac
export BUILDEROPS_AUTHORIZATION_MODE="${authorization_mode}"
unset BUILDEROPS_AUTHORIZATION_FINGERPRINT
load_contexts
current_sha="$(read_pin "${PIN_FILE}" BUILDEROPS_SOURCE_SHA)"
current_digest="$(read_pin "${PIN_FILE}" BUILDEROPS_IMAGE_DIGEST)"
current_postgres_digest="$(read_pin "${PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_DIGEST)"

validate_unattended_authorization() {
  local requested_operation="${1:?operation required}"
  local authorization_file="${BUILDEROPS_AUTHORIZATION_FILE:-/etc/builderops/owner-authorization.json}"
  local builderops_socket
  authorization_fingerprint="$({
    python3 "${ROOT}/scripts/builderops/owner_authorization.py" validate \
      --file "${authorization_file}" \
      --action "${requested_operation}" \
      --hostname "$(hostname -s)"
  })" || {
    record_preflight_refusal "owner_authorization_refused" 78
    exit 78
  }
  export BUILDEROPS_AUTHORIZATION_FINGERPRINT="${authorization_fingerprint}"
  [ "${BUILDEROPS_DOCKER_CONTEXT}" = "builderops" ] || {
    record_preflight_refusal "unattended_builderops_context_refused" 75
    exit 75
  }
  builderops_socket="$(docker context inspect --format '{{.Endpoints.docker.Host}}' builderops 2>/dev/null)" || {
    record_preflight_refusal "unattended_builderops_context_unavailable" 75
    exit 75
  }
  [ "${builderops_socket}" = "unix:///run/docker-builderops.sock" ] || {
    record_preflight_refusal "unattended_builderops_context_refused" 75
    exit 75
  }
}

validate_unattended_rollback_candidate() {
  local previous_receipt_sha candidate_file
  python3 "${ROOT}/scripts/builderops/owner_authorization.py" secure-file \
    --file "${PREVIOUS_PIN_FILE}" >/dev/null 2>&1 || {
    record_preflight_refusal "rollback_pin_custody_refused" 78
    exit 78
  }
  previous_receipt_sha="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_CANDIDATE_RECEIPT_SHA)"
  [[ "${previous_receipt_sha}" =~ ^[0-9a-f]{64}$ ]] || {
    record_preflight_refusal "rollback_candidate_provenance_missing" 78
    exit 78
  }
  candidate_file="${RECEIPT_DIR}/candidate-pairs/${previous_receipt_sha}.json"
  python3 "${ROOT}/scripts/builderops/owner_authorization.py" verify-candidate \
    --file "${candidate_file}" \
    --receipt-sha "${previous_receipt_sha}" \
    --source-sha "${target_sha}" \
    --image-digest "${target_digest}" \
    --postgres-digest "${target_postgres_digest}" >/dev/null 2>&1 || {
    record_preflight_refusal "rollback_candidate_provenance_refused" 78
    exit 78
  }
  target_receipt_sha="${previous_receipt_sha}"
  target_receipt_file="${candidate_file}"
  export target_receipt_sha target_receipt_file
}

case "${action}" in
  deploy)
    [ "$#" -eq 2 ] || { [ "${authorization_mode}" = "unattended" ] && usage; }
    candidate_receipt="${2}"
    [ -n "${candidate_receipt:-}" ] || usage
    if [ "${authorization_mode}" = "unattended" ]; then
      validate_unattended_authorization deploy
    fi
    load_attested_candidate_pair "${candidate_receipt}"
    ;;
  rollback)
    [ "$#" -eq 1 ] || usage
    if [ "${authorization_mode}" = "unattended" ]; then
      validate_unattended_authorization rollback
    fi
    [ -f "${PREVIOUS_PIN_FILE}" ] || { echo "previous BuilderOps pin is unavailable" >&2; exit 2; }
    target_sha="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_SOURCE_SHA)"
    target_digest="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_IMAGE_DIGEST)"
    target_postgres_digest="$(read_pin "${PREVIOUS_PIN_FILE}" BUILDEROPS_POSTGRES_IMAGE_DIGEST)"
    if [ "${authorization_mode}" = "unattended" ]; then
      validate_unattended_rollback_candidate
    fi
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
builderops_preflight_control_plane_secrets
"${ROOT}/scripts/builderops/configure_tailnet_tls.sh" --preflight

placeholder_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000"
pin_backup="$(mktemp "${PIN_FILE}.rollback.XXXXXX")"
cp "${PIN_FILE}" "${pin_backup}"

activate_target() {
  builderops_preflight_control_plane_secrets || return
  # Refuse before pin, database, or container mutation when the fixed
  # loopback unit or restart authority is unavailable. The post-recreation
  # refresh below is still required because API recreation invalidates the
  # cached address.
  preflight_loopback_forwarder || return
  write_pin "${PIN_FILE}" "${target_sha}" "${target_digest}" "${target_postgres_digest}" "${target_receipt_sha:-}" || return
  builderops_compose "${ROOT}" pull db api worker migrate || return
  builderops_compose "${ROOT}" up -d db || return
  builderops_compose "${ROOT}" up --abort-on-container-exit --exit-code-from migrate migrate || return
  builderops_compose "${ROOT}" up -d --force-recreate api worker || return
  refresh_loopback_forwarder || return
  wait_ready || return
  "${ROOT}/scripts/builderops/configure_tailnet_tls.sh" || return
  builderops_assert_single_writer_after_activation || return
}

reactivate_previous_release() {
  # Never restore a previous BuilderOps release while a competing Product or
  # BuilderOps writer is visible. The original failure remains actionable and
  # the operator must resolve the writer boundary before another mutation.
  builderops_assert_failure_domain || return
  builderops_preflight_control_plane_secrets || return
  # A rollback must also prove the loopback unit and restart authority before
  # restoring its pin or recreating any service; otherwise a forwarder outage
  # becomes a second late mutation failure.
  preflight_loopback_forwarder || return
  cp "${pin_backup}" "${PIN_FILE}" || return
  builderops_compose "${ROOT}" pull db api worker || return
  builderops_compose "${ROOT}" up -d --force-recreate db api worker || return
  refresh_loopback_forwarder || return
  wait_ready || return
  builderops_assert_single_writer_after_activation || return
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
