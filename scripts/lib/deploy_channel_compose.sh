#!/usr/bin/env bash
set -euo pipefail

_deploy_channel_compose_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_deploy_channel_compose_lib_dir}/instance_ownership_host_state.sh"
source "${_deploy_channel_compose_lib_dir}/signboard_root.sh"
unset _deploy_channel_compose_lib_dir

_deploy_channel_env_value() {
  local file_path="${1:?env file required}"
  local key="${2:?env key required}"
  [ -f "${file_path}" ] || return 0
  awk -v key="${key}" '
    index($0, key "=") == 1 {
      print substr($0, length(key) + 2)
      exit
    }
  ' "${file_path}"
}

_deploy_channel_uses_full_host_vault_path() {
  local vault_path="${1:?vault path required}"
  python3 - "${vault_path}" <<'PY'
import os
import sys

selector = sys.argv[1]
roots = ("/Users", "/Volumes")


def under_full_host_root(path: str) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in roots)


# The container receives the selector string, not its host-side realpath. Both
# views must stay under a same-path mount: this rejects relative selectors,
# outside symlinks into /Users, and /Users symlinks that escape the mounts.
lexical_path = os.path.normpath(selector) if os.path.isabs(selector) else ""
resolved_path = os.path.realpath(selector)
raise SystemExit(
    0
    if under_full_host_root(lexical_path) and under_full_host_root(resolved_path)
    else 1
)
PY
}

_deploy_channel_signboard_container_root() {
  local signboard_host_root="${1:?signboard host root required}"
  local vault_host_root="${2:-}"
  local vault_container_root="${3:-}"
  python3 - "${signboard_host_root}" "${vault_host_root}" "${vault_container_root}" <<'PY'
import os
import stat
import sys

signboard_host_root, vault_host_root, vault_container_root = sys.argv[1:]
same_path_roots = ("/Users", "/Volumes")


def normalized_absolute(path: str) -> str:
    return os.path.normpath(path) if os.path.isabs(path) else ""


def contained(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


lexical_signboard = normalized_absolute(signboard_host_root)
resolved_signboard = os.path.realpath(signboard_host_root)
try:
    signboard_stat = os.stat(resolved_signboard)
except OSError:
    raise SystemExit(3)
permission_pairs = (
    stat.S_IRUSR | stat.S_IXUSR,
    stat.S_IRGRP | stat.S_IXGRP,
    stat.S_IROTH | stat.S_IXOTH,
)
if (
    not stat.S_ISDIR(signboard_stat.st_mode)
    or not any(
        (signboard_stat.st_mode & pair) == pair
        for pair in permission_pairs
    )
    or not os.access(resolved_signboard, os.R_OK | os.X_OK)
):
    raise SystemExit(3)
try:
    with os.scandir(resolved_signboard):
        pass
except OSError:
    raise SystemExit(3)

if any(
    contained(lexical_signboard, root) and contained(resolved_signboard, root)
    for root in same_path_roots
):
    sys.stdout.write(resolved_signboard)
    raise SystemExit(0)

lexical_vault = normalized_absolute(vault_host_root)
resolved_vault = os.path.realpath(vault_host_root) if lexical_vault else ""
lexical_container = normalized_absolute(vault_container_root)
if not (
    contained(lexical_signboard, lexical_vault)
    and contained(resolved_signboard, resolved_vault)
    and lexical_container
):
    raise SystemExit(3)

relative = os.path.relpath(resolved_signboard, resolved_vault)
container_signboard = os.path.normpath(os.path.join(lexical_container, relative))
if not contained(container_signboard, lexical_container):
    raise SystemExit(3)
sys.stdout.write(container_signboard)
PY
}

_deploy_channel_needs_dev_capture_secret() {
  local channel="${1:?channel required}"
  shift
  [ "${channel}" = "dev" ] || return 1
  [ "${1:-}" = "up" ] || return 1
  local arg
  for arg in "$@"; do
    [ "${arg}" = "heimdal-capture-watch" ] && return 0
  done
  return 1
}

# The api process is a declared consumer of heimdal.raw-store-key (#4422): the
# governed media/screen ingress lanes encrypt through the raw store. Bootstrap
# fires whenever `up` includes the api service (named explicitly, or implied by
# an un-filtered `up`). Posture is degrade-visibly, never fail-deploy: the
# availability precheck proves the contract and Keychain item resolve before
# any wrap is added, so an unprovisioned key skips the layer loudly and the
# api startup preflight reports the ingress lanes unavailable.
# The api ingress secret layer is additive and degrade-visibly: when the host
# secret contract cannot be loaded or does not declare the api consumer in this
# environment (e.g. a harness root without config/secrets), the deploy proceeds
# WITHOUT the layer — loudly — and the api startup preflight reports the
# ingress lanes unavailable. A deploy never fails because this layer could not
# be prepared.
_deploy_channel_api_ingress_bootstrap_available() {
  local channel="${1:?channel required}"
  local root="${2:?repo root required}"
  # Runs from ${root} with ${root} on PYTHONPATH: the contract path is
  # repo-relative and the app package must be THIS deploy's, never whatever
  # checkout the caller's shell happens to sit in.
  # The precheck also proves the Keychain item is actually resolvable
  # (value discarded, never printed): the bootstrap mechanism is fail-closed
  # for kind raw-store-key, so wrapping compose while the item is missing
  # would fail the whole deploy — the opposite of this slice's
  # degrade-visibly posture. Missing item ⇒ skip the layer loudly; the api
  # startup preflight then reports the ingress lanes unavailable.
  if (
    cd "${root}" \
      && PYTHONPATH="${root}${PYTHONPATH:+:${PYTHONPATH}}" "${PYTHON:-python3}" - "${channel}" <<'PY' 2>/dev/null
import sys

from app.ops.host_secret_bootstrap import _security_keychain_lookup
from app.ops.host_secret_contract import load_host_secret_contract

contract = load_host_secret_contract()
contract.require_declared(
    channel=sys.argv[1], consumer="heimdal-api-ingress", secret="heimdal.raw-store-key"
)
account = contract.keychain_account(
    channel=sys.argv[1], consumer="heimdal-api-ingress", secret="heimdal.raw-store-key"
)
value = _security_keychain_lookup(contract.keychain_service, account)
if not value:
    raise SystemExit(1)
PY
  )
  then
    return 0
  fi
  echo "deploy: api ingress secret layer unavailable (contract missing, heimdal-api-ingress consumer undeclared, or Keychain item unresolvable); continuing without it — the api startup preflight will report the ingress lanes unavailable" >&2
  return 1
}

_deploy_channel_needs_api_ingress_secret() {
  local channel="${1:?channel required}"
  shift
  [ "${1:-}" = "up" ] || return 1
  shift
  local arg saw_service=0
  for arg in "$@"; do
    case "${arg}" in
      -*) continue ;;
    esac
    saw_service=1
    [ "${arg}" = "api" ] && return 0
  done
  [ "${saw_service}" = "0" ] && return 0
  return 1
}

deploy_channel_compose() {
  local root="${1:?repo root required}"
  local channel="${2:?channel required}"
  local compose_overlay="${3:?channel compose overlay required}"
  local compose_project="${4:?compose project required}"
  local channel_env_file="${5:?channel env file required}"
  shift 5

  resolve_instance_ownership_host_state_dir || return $?

  local runtime_env_ref runtime_env_file llm_provider runtime_llm_provider
  local vault_host_root vault_container_root
  local -a compose_args
  compose_args=(-f "${root}/docker-compose.yaml" -f "${root}/${compose_overlay}")

  # Resolve the governed runtime env file path. It is used below ONLY to read
  # VAULT_HOST_ROOT for the overlay decision, to pin WATCHER_RUNTIME_ENV_FILE
  # for the service `env_file:` layer, and to resolve the non-secret
  # LLM_PROVIDER selector. It is NEVER passed to Compose as a CLI `--env-file`:
  # that would expose its DSNs and other values to Compose interpolation (#3875
  # — a previous dead `env_args` block here looked like it did exactly that; do
  # not reintroduce it).
  runtime_env_ref="$(_deploy_channel_env_value "${channel_env_file}" WATCHER_RUNTIME_ENV_FILE)"
  if [ -z "${runtime_env_ref}" ]; then
    case "${channel}" in
      test) runtime_env_ref="./tmp-test/runtime.env" ;;
      *) runtime_env_ref="./tmp/runtime.env" ;;
    esac
  fi
  runtime_env_file=""
  case "${runtime_env_ref}" in
    /*) runtime_env_file="${runtime_env_ref}" ;;
    ./*) runtime_env_file="${root}/${runtime_env_ref#./}" ;;
    *) runtime_env_file="${root}/${runtime_env_ref}" ;;
  esac

  llm_provider="$(_deploy_channel_env_value "${channel_env_file}" LLM_PROVIDER)"
  runtime_llm_provider=""
  if [ -n "${runtime_env_file}" ] && [ -f "${runtime_env_file}" ]; then
    runtime_llm_provider="$(_deploy_channel_env_value "${runtime_env_file}" LLM_PROVIDER)"
  fi
  if [ -n "${runtime_llm_provider}" ]; then
    llm_provider="${runtime_llm_provider}"
  fi

  vault_host_root="$(_deploy_channel_env_value "${channel_env_file}" VAULT_HOST_ROOT)"
  if [ -z "${vault_host_root}" ] && [ -n "${runtime_env_file}" ] && [ -f "${runtime_env_file}" ]; then
    vault_host_root="$(_deploy_channel_env_value "${runtime_env_file}" VAULT_HOST_ROOT)"
  fi

  vault_container_root=""
  if [ -n "${vault_host_root}" ]; then
    if _deploy_channel_uses_full_host_vault_path "${vault_host_root}"; then
      vault_container_root="${vault_host_root}"
      compose_args+=(-f "${root}/docker-compose.full-host-vault.yml")
    else
      vault_container_root="/app/vault"
      compose_args+=(-f "${root}/docker-compose.legacy-vault.yml")
    fi
    if [ "${channel}" = "test" ]; then
      compose_args+=(-f "${root}/docker-compose.test-vault.yml")
    fi
  fi
  if [ "${MVR01C_SCALAR_ROLLBACK:-0}" = "1" ]; then
    compose_args+=(-f "${root}/docker-compose.scalar-rollback.yml")
  fi

  (
    cd "${root}" || exit 1

    # Resolve the Signboard root independently of the generated runtime env so
    # a channel deploy can repair a missing or stale runtime-env entry without
    # regenerating that file. The stdin overlay below carries no value: Compose
    # forwards SIGNBOARD_ROOT from this governed shell when one resolves and
    # removes an env_file value when it does not. This preserves the visible
    # no-active-vault error instead of retaining a stale projection root.
    resolve_signboard_root_env
    local signboard_container_root=""
    if [ -n "${SIGNBOARD_ROOT:-}" ]; then
      if signboard_container_root="$(
        _deploy_channel_signboard_container_root \
          "${SIGNBOARD_ROOT}" \
          "${vault_host_root}" \
          "${vault_container_root}"
      )"; then
        :
      else
        signboard_container_root=""
      fi
    fi
    if [ -n "${signboard_container_root}" ]; then
      SIGNBOARD_ROOT="${signboard_container_root}"
      export SIGNBOARD_ROOT
    else
      unset SIGNBOARD_ROOT
    fi
    compose_args+=(-f -)

    # Compose gives the caller shell precedence over --env-file values. Pin the
    # governed selectors here so a stale parent shell cannot swap the selected
    # runtime env, provider selector, or vault after the decisions above. The
    # runtime env itself stays a service env_file; passing it as a CLI --env-file
    # would expose its DSNs and other values to Compose interpolation.
    export WATCHER_RUNTIME_ENV_FILE="${runtime_env_ref}"
    if [ -n "${llm_provider}" ]; then
      export LLM_PROVIDER="${llm_provider}"
    else
      unset LLM_PROVIDER
    fi
    if [ -n "${vault_host_root}" ]; then
      export VAULT_HOST_ROOT="${vault_host_root}"
      export DEPLOY_VAULT_CONTAINER_ROOT="${vault_container_root}"
    else
      unset VAULT_HOST_ROOT
      unset DEPLOY_VAULT_CONTAINER_ROOT
    fi

    local -a compose_command
    compose_command=(
      docker compose
      --env-file "${channel_env_file}"
      "${compose_args[@]}"
      -p "${compose_project}"
      "$@"
    )

    if _deploy_channel_needs_dev_capture_secret "${channel}" "$@"; then
      compose_command=(
        "${PYTHON:-python3}" -m app.ops.host_secret_bootstrap
        --channel "${channel}"
        --consumer heimdal-capture-watch
        -- "${compose_command[@]}"
      )
    fi

    if _deploy_channel_needs_api_ingress_secret "${channel}" "$@" \
        && _deploy_channel_api_ingress_bootstrap_available "${channel}" "${root}"; then
      # Outer wrap: materialize the api consumer's secret env file, then
      # re-export its handle under HOST_SECRET_RUNTIME_ENV_FILE_API before the
      # (possibly nested) capture-watch bootstrap runs — that inner bootstrap
      # scrubs the shared HOST_SECRET_RUNTIME_ENV_FILE name from the child
      # environment, and the renamed handle is what the api service's
      # env_file layer reads. The precheck above already proved the contract
      # AND the Keychain item resolve, so a bootstrap failure here is a real
      # fault, not the unprovisioned-key case (which skips the wrap). Runs
      # from ${root} with ${root} on PYTHONPATH so the contract and app
      # package are this deploy's; every compose path in the command is
      # absolute or compose-file-relative, so the cd is inert for Compose.
      # Never echoes or logs a secret value; the shim exports only a file
      # path, and the file is bootstrap-owned and removed after Compose
      # returns.
      compose_command=(
        sh -c 'cd "$1" && export PYTHONPATH="$1${PYTHONPATH:+:${PYTHONPATH}}" && shift && exec "$@"' _ "${root}"
        "${PYTHON:-python3}" -m app.ops.host_secret_bootstrap
        --channel "${channel}"
        --consumer heimdal-api-ingress
        -- sh -c 'export HOST_SECRET_RUNTIME_ENV_FILE_API="${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"; unset HOST_SECRET_RUNTIME_ENV_FILE; exec "$@"' _
        "${compose_command[@]}"
      )
    fi

    # Keep the override in memory. A temporary env/compose file would persist
    # operator paths or runtime secrets and would weaken the existing runtime
    # env ownership boundary.
    "${compose_command[@]}" <<'YAML'
services:
  api:
    environment:
      SIGNBOARD_ROOT:
YAML
  )
}
