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

_deploy_channel_resolve_runtime_env_file() {
  local root="${1:?repo root required}"
  local channel="${2:?channel required}"
  local channel_env_file="${3:?channel env file required}"
  local runtime_env_ref

  runtime_env_ref="$(_deploy_channel_env_value "${channel_env_file}" WATCHER_RUNTIME_ENV_FILE)"
  if [ -z "${runtime_env_ref}" ]; then
    case "${channel}" in
      test) runtime_env_ref="./tmp-test/runtime.env" ;;
      *) runtime_env_ref="./tmp/runtime.env" ;;
    esac
  fi

  DEPLOY_CHANNEL_RUNTIME_ENV_REF="${runtime_env_ref}"
  case "${runtime_env_ref}" in
    /*) DEPLOY_CHANNEL_RUNTIME_ENV_FILE="${runtime_env_ref}" ;;
    ./*) DEPLOY_CHANNEL_RUNTIME_ENV_FILE="${root}/${runtime_env_ref#./}" ;;
    *) DEPLOY_CHANNEL_RUNTIME_ENV_FILE="${root}/${runtime_env_ref}" ;;
  esac
}

_deploy_channel_tts_config_blocked() {
  local reason="${1:?reason required}"
  local path_class="${2:?path class required}"
  echo "TTS config preflight: blocked reason=${reason} keys=TTS_ENABLED,TTS_HOST_ROOT path_class=${path_class}" >&2
  return 91
}

deploy_channel_tts_config_preflight() {
  local root="${1:?repo root required}"
  local channel="${2:?channel required}"
  local channel_env_file="${3:?channel env file required}"
  local runtime_env_file parse_status parse_field path_class host_root parse_output parser_rc

  _deploy_channel_resolve_runtime_env_file "${root}" "${channel}" "${channel_env_file}"
  runtime_env_file="${DEPLOY_CHANNEL_RUNTIME_ENV_FILE}"
  parse_status="blocked"
  parse_field="validation_failed"
  path_class="not_evaluated"
  host_root=""
  parse_output="$(mktemp "${TMPDIR:-/tmp}/tts-config-preflight.XXXXXX" 2>/dev/null)"
  if [ -z "${parse_output}" ]; then
    _deploy_channel_tts_config_blocked validation_failed not_evaluated
    return $?
  fi
  parser_rc=0
  ROOT="${root}" RUNTIME_ENV_FILE="${runtime_env_file}" "${PYTHON:-python3}" - >"${parse_output}" 2>/dev/null <<'PY'
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def emit(status: str, field: str, path_class: str, host_root: str = "") -> None:
    sys.stdout.write(f"{status}\n{field}\n{path_class}\n{host_root}\n")


try:
    snapshot = Path(os.environ["RUNTIME_ENV_FILE"]).read_bytes()
    text = snapshot.decode("utf-8")
except (OSError, UnicodeError):
    emit("blocked", "validation_failed", "not_evaluated")
    raise SystemExit(0)

enabled_values = [
    line.removeprefix("TTS_ENABLED=")
    for line in text.splitlines()
    if line.startswith("TTS_ENABLED=")
]
root_values = [
    line.removeprefix("TTS_HOST_ROOT=")
    for line in text.splitlines()
    if line.startswith("TTS_HOST_ROOT=")
]
if len(enabled_values) > 1 or len(root_values) > 1:
    emit("blocked", "duplicate_key", "not_evaluated")
    raise SystemExit(0)

enabled_present = bool(enabled_values)
enabled = enabled_values[0] if enabled_present else ""
host_root = root_values[0] if root_values else ""
if not enabled_present or enabled == "false":
    emit("ok", "false", "not_required")
    raise SystemExit(0)
if enabled != "true":
    emit("blocked", "invalid_boolean", "not_evaluated")
    raise SystemExit(0)
if not host_root:
    emit("blocked", "missing_enabled_root", "empty_or_unset")
    raise SystemExit(0)

root = Path(os.environ["ROOT"])
candidate = Path(host_root)
if not candidate.is_absolute():
    emit("blocked", "invalid_enabled_root", "relative")
    raise SystemExit(0)
try:
    metadata = candidate.stat()
except FileNotFoundError:
    emit("blocked", "invalid_enabled_root", "missing")
    raise SystemExit(0)
except OSError:
    emit("blocked", "invalid_enabled_root", "inaccessible")
    raise SystemExit(0)
if not stat.S_ISDIR(metadata.st_mode):
    emit("blocked", "invalid_enabled_root", "not_directory")
    raise SystemExit(0)
permission_pairs = (
    stat.S_IRUSR | stat.S_IXUSR,
    stat.S_IRGRP | stat.S_IXGRP,
    stat.S_IROTH | stat.S_IXOTH,
)
if not any(metadata.st_mode & pair == pair for pair in permission_pairs):
    emit("blocked", "invalid_enabled_root", "inaccessible")
    raise SystemExit(0)
try:
    with os.scandir(candidate):
        pass
    resolved_candidate = candidate.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
except OSError:
    emit("blocked", "invalid_enabled_root", "inaccessible")
    raise SystemExit(0)
try:
    resolved_candidate.relative_to(resolved_root)
except ValueError:
    pass
else:
    emit("blocked", "invalid_enabled_root", "repo_contained")
    raise SystemExit(0)

emit("ok", "true", "absolute_outside_repo_accessible_directory", host_root)
PY
  parser_rc=$?
  if [ "${parser_rc}" -ne 0 ]; then
    rm -f "${parse_output}"
    _deploy_channel_tts_config_blocked validation_failed not_evaluated
    return $?
  fi
  {
    IFS= read -r parse_status || parse_status="blocked"
    IFS= read -r parse_field || parse_field="validation_failed"
    IFS= read -r path_class || path_class="not_evaluated"
    IFS= read -r host_root || host_root=""
  } < "${parse_output}"
  rm -f "${parse_output}"

  case "${parse_status}:${parse_field}" in
    ok:false)
      DEPLOY_TTS_CONFIG_GOVERNED=1
      DEPLOY_TTS_ENABLED=false
      unset DEPLOY_TTS_HOST_ROOT
      export DEPLOY_TTS_CONFIG_GOVERNED DEPLOY_TTS_ENABLED
      echo "TTS config preflight: ok enabled=false path_class=not_required"
      return 0
      ;;
    ok:true) ;;
    blocked:*)
      _deploy_channel_tts_config_blocked "${parse_field}" "${path_class}"
      return $?
      ;;
    *)
      _deploy_channel_tts_config_blocked validation_failed not_evaluated
      return $?
      ;;
  esac

  DEPLOY_TTS_CONFIG_GOVERNED=1
  DEPLOY_TTS_ENABLED=true
  DEPLOY_TTS_HOST_ROOT="${host_root}"
  export DEPLOY_TTS_CONFIG_GOVERNED DEPLOY_TTS_ENABLED DEPLOY_TTS_HOST_ROOT
  echo "TTS config preflight: ok enabled=true path_class=${path_class}"
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

_deploy_channel_signboard_override_document() {
  cat <<'YAML'
services:
  api:
    environment:
      SIGNBOARD_ROOT:
YAML
}

# host_secret_contract.json declares the `heimdal-capture-watch` consumer for
# every channel (dev/test/prod), not only dev (#4362 -- before this fix, this
# helper was dev-only and test/prod deploys never wrapped the compose
# invocation, so HEIMDAL_RAW_STORE_KEY never reached the service's env_file
# chain on those channels no matter what the Keychain held).
_deploy_channel_needs_capture_secret() {
  local channel="${1:?channel required}"
  shift
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
# ingress lanes unavailable.
#
# Scope of that promise (corrected #4489): it covers a layer that cannot be
# *prepared* — absent contract, undeclared consumer, unprovisioned item. It does
# NOT cover a declared secret whose Keychain item resolves to a MALFORMED value:
# the bootstrap fails closed on that, so the wrap fails and the deploy aborts.
# That was already true of a malformed heimdal.raw-store-key (the precheck below
# only rejects an empty value) and is now also true of an optional secret such as
# github.token. Fail-closed is the intended direction — a present-but-wrong
# credential is a misconfiguration, not an opt-out — but the operator cost is a
# whole-channel deploy failure, tracked as deferred defect
# KD-4489-malformed-declared-secret-aborts-channel-deploy on #4172.
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

_deploy_channel_principal_cutover_receipt_requested() {
  local arg
  for arg in "$@"; do
    [ "${arg}" = "principal-cutover" ] && return 0
  done
  return 1
}

# Governed Compose normally suppresses all output because config/startup text
# can contain machine paths or environment values. The MVR-03 wrapper needs two
# boolean fields from this one exact command; parse the private capture and emit a new
# whitelist-only receipt rather than forwarding any raw Compose bytes.
_deploy_channel_redact_principal_cutover_receipt() {
  local output_file="${1:?captured output file required}"
  "${PYTHON:-python3}" - "${output_file}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
except OSError:
    raise SystemExit(1)
for line in reversed(lines):
    try:
        payload = json.loads(line)
    except (TypeError, ValueError):
        continue
    advanced = payload.get("floor_advanced") if isinstance(payload, dict) else None
    if (
        payload.get("floor_recorded") is True
        and type(advanced) is bool
    ):
        print(
            json.dumps(
                {
                    "floor_advanced": advanced,
                    "floor_recorded": True,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(0)
raise SystemExit(1)
PY
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
  _deploy_channel_resolve_runtime_env_file "${root}" "${channel}" "${channel_env_file}"
  runtime_env_ref="${DEPLOY_CHANNEL_RUNTIME_ENV_REF}"
  runtime_env_file="${DEPLOY_CHANNEL_RUNTIME_ENV_FILE}"

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
    # Deliver the override document through a private temp file rather than
    # `-f -`/heredoc on the command's own stdin (fd 0): a bare `-f -` binds to
    # whatever the caller supplied on stdin, so any caller piping real data
    # into this wrapper (#4536, e.g. prepare_instance_state_deployment feeding
    # a host-produced inventory into the container) had that data silently
    # replaced by this override document instead of reaching the container.
    # Process substitution (`-f <(...)`) was tried first and works with a
    # plain command, but `docker compose` invokes its compose plugin as a
    # separate child process that inherits only stdin/stdout/stderr from the
    # `docker` CLI (Go's os/exec does not forward arbitrary fds without
    # ExtraFiles), so the plugin process cannot see a process-substitution fd
    # opened by this shell — confirmed by CI's real docker: `open
    # /dev/fd/63: no such file or directory`. The override document itself
    # carries no value of its own and no operator path or secret (Compose
    # forwards SIGNBOARD_ROOT from this governed shell via the bare `KEY:`
    # form), so a private temp file does not weaken the runtime env ownership
    # boundary the earlier in-memory-only comment protected.
    local signboard_override_file compose_stdout_file compose_stderr_file compose_rc
    signboard_override_file="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-signboard-override.XXXXXX")"
    compose_stdout_file="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-compose-stdout.XXXXXX")"
    compose_stderr_file="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-compose-stderr.XXXXXX")"
    # EXIT here is scoped to this `( ... )` subshell only (traps set inside a
    # subshell do not leak into the parent shell), so this fires exactly once
    # when the subshell running the actual Compose invocation exits, on every
    # path including an early `exit 1` above or a failing Compose command.
    trap 'rm -f -- "${signboard_override_file}" "${compose_stdout_file}" "${compose_stderr_file}"' EXIT
    _deploy_channel_signboard_override_document > "${signboard_override_file}"
    compose_args+=(-f "${signboard_override_file}")

    # Compose gives the caller shell precedence over --env-file values. Pin the
    # governed selectors here so a stale parent shell cannot swap the selected
    # runtime env, provider selector, or vault after the decisions above. The
    # runtime env itself stays a service env_file; passing it as a CLI --env-file
    # would expose its DSNs and other values to Compose interpolation.
    export WATCHER_RUNTIME_ENV_FILE="${runtime_env_ref}"
    if [ "${DEPLOY_TTS_CONFIG_GOVERNED:-0}" = "1" ]; then
      export TTS_ENABLED="${DEPLOY_TTS_ENABLED}"
      if [ "${DEPLOY_TTS_ENABLED}" = "true" ]; then
        export TTS_HOST_ROOT="${DEPLOY_TTS_HOST_ROOT}"
      else
        unset TTS_HOST_ROOT
      fi
    fi
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

    if _deploy_channel_needs_capture_secret "${channel}" "$@"; then
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
      # env_file layer reads. The precheck above proved the contract loads and
      # that heimdal.raw-store-key resolves non-empty — it does not validate
      # that value, and does not look at the consumer's other declared secrets
      # at all (#4489) — so a bootstrap failure here is a real fault
      # (malformed value) rather than the unprovisioned-key case, which skips
      # the wrap. Runs
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

    # fd 0 is left untouched above (the override document is a temp file, not
    # a stdin heredoc), so it still carries whatever the caller attached to
    # this function call. A governed TTS invocation captures child output in
    # private files: Compose diagnostics and `config` rendering may expand the
    # machine-local mount root or unrelated env-file values. Only validated
    # container IDs from the two internal `ps -q` probes cross this boundary;
    # every other success stays quiet and every failure emits a fixed receipt.
    if [ "${DEPLOY_TTS_CONFIG_GOVERNED:-0}" = "1" ]; then
      if [ "${1:-}" = "config" ]; then
        echo "governed compose output blocked: command=config" >&2
        return 92
      fi
      set +e
      "${compose_command[@]}" >"${compose_stdout_file}" 2>"${compose_stderr_file}"
      compose_rc=$?
      set -e
      if [ "${compose_rc}" -ne 0 ]; then
        echo "governed compose command failed: output=redacted" >&2
        return "${compose_rc}"
      fi
      if [ "${1:-}" = "ps" ]; then
        if [ "${2:-}" != "-q" ] || ! awk '
          NF && $0 !~ /^[0-9a-f]{12,64}$/ { invalid = 1 }
          END { exit invalid }
        ' "${compose_stdout_file}"; then
          echo "governed compose output blocked: command=ps output=invalid" >&2
          return 92
        fi
        cat "${compose_stdout_file}"
      elif _deploy_channel_principal_cutover_receipt_requested "$@"; then
        if ! _deploy_channel_redact_principal_cutover_receipt "${compose_stdout_file}"; then
          echo "governed compose output blocked: command=principal-cutover receipt=invalid" >&2
          return 92
        fi
      fi
      return 0
    fi

    "${compose_command[@]}"
  )
}
