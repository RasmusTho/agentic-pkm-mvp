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

  if [ "${HOST_SECRET_PROVIDER:-}" = "bws" ]; then
    runtime_env_ref="${BWS_DEPLOY_RUNTIME_ENV_FILE:-}"
    case "${runtime_env_ref}" in
      /*) ;;
      *)
        echo "BWS runtime env preflight: blocked reason=missing_or_relative_path" >&2
        return 78
        ;;
    esac
  else
    runtime_env_ref="$(
      ROOT="${root}" CHANNEL_ENV_FILE="${channel_env_file}" "${PYTHON:-python3}" - 2>/dev/null <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["ROOT"])
from scripts.compose_env import compose_env_value

channel_env_file = Path(os.environ["CHANNEL_ENV_FILE"])
try:
    channel_lines = channel_env_file.read_text(encoding="utf-8").splitlines()
except FileNotFoundError:
    channel_lines = []
for line in channel_lines:
    if line.startswith("WATCHER_RUNTIME_ENV_FILE="):
        print(compose_env_value(line.split("=", 1)[1]))
        break
PY
    )"
  fi
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

# Compose interpolation reads the caller environment and its CLI --env-file;
# a service-level env_file does not supply values for fields such as `user:`.
# Read only the two numeric process-identity fields from the governed runtime
# env. Never source the file or use it as Compose's CLI --env-file, because it
# also contains database and other runtime bindings.
deploy_channel_runtime_identity_preflight() {
  local runtime_env_file="${1:?runtime env file required}"
  local identity_bindings runtime_uid runtime_gid

  identity_bindings=""
  if [ -e "${runtime_env_file}" ] || [ -L "${runtime_env_file}" ]; then
    if [ ! -f "${runtime_env_file}" ]; then
      echo "runtime identity preflight: blocked reason=invalid_runtime_env" >&2
      return 78
    fi
    if ! identity_bindings="$(
      RUNTIME_ENV_FILE="${runtime_env_file}" "${PYTHON:-python3}" - 2>/dev/null <<'PY'
from __future__ import annotations

import os
from pathlib import Path
import re
import sys


try:
    raw = Path(os.environ["RUNTIME_ENV_FILE"]).read_bytes()
except (KeyError, OSError):
    raise SystemExit(2) from None
if len(raw) > 1_048_576:
    raise SystemExit(2)

values: dict[str, list[bytes]] = {"LOCAL_UID": [], "LOCAL_GID": []}
for line in raw.splitlines():
    for key in values:
        prefix = key.encode("ascii") + b"="
        if line.startswith(prefix):
            values[key].append(line[len(prefix):])

if not values["LOCAL_UID"] and not values["LOCAL_GID"]:
    raise SystemExit(0)
if any(len(entries) != 1 for entries in values.values()):
    raise SystemExit(2)
uid, gid = values["LOCAL_UID"][0], values["LOCAL_GID"][0]
if not re.fullmatch(rb"[0-9]+", uid) or not re.fullmatch(rb"[0-9]+", gid):
    raise SystemExit(2)
if not uid.lstrip(b"0") or not gid.lstrip(b"0"):
    raise SystemExit(2)
print(uid.decode("ascii") + "\t" + gid.decode("ascii"))
PY
    )"; then
      echo "runtime identity preflight: blocked reason=invalid_runtime_env" >&2
      return 78
    fi
  fi

  if [ -n "${identity_bindings}" ]; then
    IFS=$'\t' read -r runtime_uid runtime_gid <<<"${identity_bindings}"
    if [[ ! "${runtime_uid}" =~ ^[0-9]+$ ]] || [[ ! "${runtime_gid}" =~ ^[0-9]+$ ]]; then
      echo "runtime identity preflight: blocked reason=invalid_runtime_env" >&2
      return 78
    fi
    LOCAL_UID="${runtime_uid}"
    LOCAL_GID="${runtime_gid}"
    export LOCAL_UID LOCAL_GID
    return 0
  fi

  if [ "${HOST_SECRET_PROVIDER:-}" = "bws" ]; then
    echo "runtime identity preflight: blocked reason=missing_runtime_identity" >&2
    return 78
  fi

  # Local development without a generated runtime env keeps the host identity
  # behavior. A present but malformed/partial governed identity never falls
  # through to this compatibility path.
  LOCAL_UID="${LOCAL_UID:-$(id -u)}"
  LOCAL_GID="${LOCAL_GID:-$(id -g)}"
  export LOCAL_UID LOCAL_GID
}

deploy_channel_runtime_identity_matches_snapshot() {
  local runtime_env_snapshot="${1:?runtime env snapshot required}"
  local expected_uid="${LOCAL_UID:-$(id -u)}"
  local expected_gid="${LOCAL_GID:-$(id -g)}"
  local actual_uid actual_gid preflight_rc

  if deploy_channel_runtime_identity_preflight "${runtime_env_snapshot}"; then
    actual_uid="${LOCAL_UID}"
    actual_gid="${LOCAL_GID}"
  else
    preflight_rc=$?
    LOCAL_UID="${expected_uid}"
    LOCAL_GID="${expected_gid}"
    export LOCAL_UID LOCAL_GID
    return "${preflight_rc}"
  fi

  LOCAL_UID="${expected_uid}"
  LOCAL_GID="${expected_gid}"
  export LOCAL_UID LOCAL_GID
  if [ "${actual_uid}" != "${expected_uid}" ] || [ "${actual_gid}" != "${expected_gid}" ]; then
    echo "runtime identity preflight: blocked reason=runtime_identity_changed" >&2
    return 78
  fi
}

_deploy_channel_model_access_config_blocked() {
  local reason="${1:?reason required}"
  echo "model-access runtime env preflight: blocked reason=${reason}" >&2
  return 78
}

deploy_channel_model_access_runtime_env_preflight() {
  local runtime_env_file="${1:?model-access runtime env file required}"
  local bindings assignment key value
  local -a model_access_keys=(
    MODEL_ACCESS_CODEX_VLAN_ENDPOINT
    MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE
    MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT
    MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY
  )

  # Never let inherited shell values bypass this file's allowlist, including
  # when the optional host-local file is absent.
  for key in "${model_access_keys[@]}"; do
    unset "${key}"
  done

  if [ ! -e "${runtime_env_file}" ] && [ ! -L "${runtime_env_file}" ]; then
    echo "model-access runtime env preflight: ok status=optional_missing" >&2
    return 0
  fi
  if [ ! -f "${runtime_env_file}" ]; then
    _deploy_channel_model_access_config_blocked invalid_file
    return $?
  fi

  if ! bindings="$(
    RUNTIME_ENV_FILE="${runtime_env_file}" "${PYTHON:-python3}" - 2>/dev/null <<'PY'
from __future__ import annotations

import os
from pathlib import PurePosixPath
import sys
from urllib.parse import urlsplit


allowed = {
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT",
    "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY",
}


def refuse() -> None:
    raise SystemExit(2)


try:
    with open(os.environ["RUNTIME_ENV_FILE"], "rb") as stream:
        raw_content = stream.read(65537)
    if len(raw_content) > 65536:
        refuse()
    content = raw_content.decode("utf-8")
except (OSError, UnicodeError):
    refuse()

values: dict[str, str] = {}
for line in content.splitlines():
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    if "=" not in line:
        refuse()
    key, value = line.split("=", 1)
    if key not in allowed or key in values:
        refuse()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        refuse()
    if key == "MODEL_ACCESS_CODEX_VLAN_ENDPOINT":
        try:
            endpoint = urlsplit(value)
            hostname = endpoint.hostname
        except ValueError:
            refuse()
        if (
            endpoint.scheme != "https"
            or not endpoint.netloc
            or not hostname
            or endpoint.username is not None
            or endpoint.password is not None
        ):
            refuse()
    elif value and not PurePosixPath(value).is_absolute():
        refuse()
    values[key] = value

for key in sorted(allowed):
    sys.stdout.write(f"{key}={values.get(key, '')}\n")
PY
  )"; then
    _deploy_channel_model_access_config_blocked invalid_contents
    return $?
  fi

  while IFS= read -r assignment; do
    key="${assignment%%=*}"
    value="${assignment#*=}"
    case "${key}" in
      MODEL_ACCESS_CODEX_VLAN_ENDPOINT|MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE|MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT|MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY)
        export "${key}=${value}"
        ;;
      *)
        _deploy_channel_model_access_config_blocked invalid_parser_output
        return $?
        ;;
    esac
  done <<< "${bindings}"

  echo "model-access runtime env preflight: ok status=allowlist_validated" >&2
}

_deploy_channel_runtime_env_aliases_model_access_file() {
  local runtime_env_file="${1:?runtime env file required}"
  local model_access_env_file="${2:?model-access env file required}"
  [ -e "${runtime_env_file}" ] \
    && [ -e "${model_access_env_file}" ] \
    && [ "${runtime_env_file}" -ef "${model_access_env_file}" ]
}

deploy_channel_model_access_preflight() {
  local runtime_env_file="${1:?governed runtime env file required}"
  local model_access_env_file="${2:?model-access env file required}"
  local key
  local -a model_access_keys=(
    MODEL_ACCESS_CODEX_VLAN_ENDPOINT
    MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE
    MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT
    MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY
  )

  if _deploy_channel_runtime_env_aliases_model_access_file \
    "${runtime_env_file}" "${model_access_env_file}"; then
    _deploy_channel_model_access_config_blocked runtime_env_alias
    return $?
  fi

  # Rollback must remain available when optional new-route configuration is
  # absent or malformed. Do not consume those references during recovery, and
  # clear ambient values so a previous-good mock image receives no MARR path.
  if [ "${action:-deploy}" = "rollback" ]; then
    for key in "${model_access_keys[@]}"; do
      export "${key}="
    done
    echo "model-access runtime env preflight: skipped reason=rollback" >&2
    return 0
  fi

  deploy_channel_model_access_runtime_env_preflight "${model_access_env_file}"
}

_deploy_channel_snapshot_runtime_env_file() {
  local runtime_env_file="${1:?runtime env file required}"
  local model_access_env_file="${2:?model-access env file required}"
  local snapshot_file="${3:?private runtime env snapshot required}"

  if ! RUNTIME_ENV_SOURCE="${runtime_env_file}" \
    MODEL_ACCESS_ENV_SOURCE="${model_access_env_file}" \
    RUNTIME_ENV_SNAPSHOT="${snapshot_file}" \
    "${PYTHON:-python3}" - 2>/dev/null <<'PY'
from __future__ import annotations

import os
import shutil
import stat


def refuse() -> None:
    raise SystemExit(2)


try:
    source_fd = os.open(
        os.environ["RUNTIME_ENV_SOURCE"], os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    )
except FileNotFoundError:
    # Preserve the existing optional env_file behavior while pinning absence:
    # Compose receives an empty private file, so a later path replacement is
    # never picked up during this deployment.
    raise SystemExit(0)
except OSError:
    refuse()

try:
    before = os.fstat(source_fd)
    if not stat.S_ISREG(before.st_mode):
        refuse()
    try:
        model_access_stat = os.stat(os.environ["MODEL_ACCESS_ENV_SOURCE"])
    except FileNotFoundError:
        model_access_stat = None
    if model_access_stat is not None and (before.st_dev, before.st_ino) == (
        model_access_stat.st_dev,
        model_access_stat.st_ino,
    ):
        refuse()

    snapshot_fd = os.open(
        os.environ["RUNTIME_ENV_SNAPSHOT"],
        os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fchmod(snapshot_fd, 0o600)
        with os.fdopen(os.dup(source_fd), "rb") as source, os.fdopen(
            snapshot_fd, "wb"
        ) as snapshot:
            snapshot_fd = -1
            shutil.copyfileobj(source, snapshot)
            snapshot.flush()
        after = os.fstat(source_fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            refuse()
    finally:
        if snapshot_fd >= 0:
            os.close(snapshot_fd)
finally:
    os.close(source_fd)
PY
  then
    _deploy_channel_model_access_config_blocked runtime_env_snapshot
    return $?
  fi
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
mac_host_roots = ("/Users", "/Volumes")
linux_vault_root = "/srv"


def under_mac_host_root(path: str) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in mac_host_roots)


def is_canonical_linux_vault() -> bool:
    return (
        selector == lexical_path == resolved_path
        and lexical_path.startswith(f"{linux_vault_root}/")
    )


# Runtime consumers receive the selector string, not its host-side realpath.
# Keep the established Mac rule separate from Linux: Mac selectors and their
# resolved paths must both remain beneath a Mac host root. Linux selectors must
# already be normalized and resolve to themselves, so aliases and `..` paths do
# not gain a same-path bind. The /srv parent itself is never mounted.
# `instance-state-init` never receives this selector or a selected-vault mount;
# it validates the host-produced opaque receipt through its bounded mounts.
lexical_path = os.path.normpath(selector) if os.path.isabs(selector) else ""
resolved_path = os.path.realpath(selector)
raise SystemExit(
    0
    if (
        under_mac_host_root(lexical_path)
        and under_mac_host_root(resolved_path)
    )
    or is_canonical_linux_vault()
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

# HAR-02's migration cryptographic preflight is itself a declared raw-store
# consumer. Restrict this bootstrap to the explicit one-shot migration command
# used by apply_changed_migrations: implicit dependency starts and unrelated
# service ups must not receive or borrow its handle. Unlike the API ingress
# layer, this required migration authority never degrades open — a missing,
# malformed, or shared-domain-divergent key prevents Docker from starting.
_deploy_channel_needs_migration_secret() {
  local channel="${1:?channel required}"
  shift
  [ "${DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING:-0}" = "1" ] || return 1
  [ "${#}" -eq 6 ] || return 1
  [ "${1}" = "up" ] \
    && [ "${2}" = "--abort-on-container-exit" ] \
    && [ "${3}" = "--exit-code-from" ] \
    && [ "${4}" = "migrate" ] \
    && [ "${5}" = "--force-recreate" ] \
    && [ "${6}" = "migrate" ]
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

  local runtime_env_ref runtime_env_file llm_provider runtime_llm_provider
  local vault_host_root vault_container_root receipt_host_dir
  local model_access_env_file="/etc/yggdrasil/model-access/runtime.env"
  local -a compose_args
  compose_args=(-f "${root}/docker-compose.yaml" -f "${root}/${compose_overlay}")

  _deploy_channel_resolve_runtime_env_file "${root}" "${channel}" "${channel_env_file}"
  runtime_env_ref="${DEPLOY_CHANNEL_RUNTIME_ENV_REF}"
  runtime_env_file="${DEPLOY_CHANNEL_RUNTIME_ENV_FILE}"

  if [ "${channel}" = "dev" ] || [ "${channel}" = "test" ] || [ "${channel}" = "prod" ]; then
    deploy_channel_model_access_preflight \
      "${runtime_env_file}" "${model_access_env_file}" || return $?
  fi

  resolve_instance_ownership_host_state_dir || return $?

  # The governed runtime env file supplies Product's normal runtime settings.
  # It must remain distinct from the MARR path-reference file validated above;
  # otherwise base Compose's service env_file chain would forward every MARR
  # entry and bypass the explicit four-key environment mapping.

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

  receipt_host_dir="$(_deploy_channel_env_value "${channel_env_file}" DEVUI_VM102_RECEIPT_HOST_DIR)"
  if [ -z "${receipt_host_dir}" ] && [ -n "${runtime_env_file}" ] && [ -f "${runtime_env_file}" ]; then
    receipt_host_dir="$(_deploy_channel_env_value "${runtime_env_file}" DEVUI_VM102_RECEIPT_HOST_DIR)"
  fi
  if [ "${action:-deploy}" != "rollback" ] && [ -n "${receipt_host_dir}" ]; then
    if [ ! -d "${receipt_host_dir}" ] || [ ! -r "${receipt_host_dir}" ] || [ ! -x "${receipt_host_dir}" ]; then
      echo "VM-102 receipt source preflight: blocked reason=unavailable" >&2
      return 78
    fi
    receipt_host_dir="$(cd -- "${receipt_host_dir}" 2>/dev/null && pwd -P)" || {
      echo "VM-102 receipt source preflight: blocked reason=uncanonicalizable" >&2
      return 78
    }
    case "${receipt_host_dir}" in
      /Users|/Users/*|/Volumes|/Volumes/*)
        echo "VM-102 receipt source preflight: blocked reason=writable_host_alias" >&2
        return 78
        ;;
      /*) ;;
      *)
        echo "VM-102 receipt source preflight: blocked reason=relative_path" >&2
        return 78
        ;;
    esac
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

  if [ -f "/etc/yggdrasil/bws-deploy/${channel}.json" ]; then
    export HOST_SECRET_PROVIDER=bws
  fi
  if [ "${HOST_SECRET_PROVIDER:-}" = "bws" ]; then
    (cd "${root}" && "${PYTHON:-python3}" -m app.ops.postgres_deploy_linux guard "${channel}" --compose-command "${1:-}") || return $?
    compose_args+=(-f "${root}/docker-compose.bws.yml")
    case "${BWS_DATABASE_TARGET:-}" in
      local) ;;
      external) compose_args+=(-f "${root}/docker-compose.bws-external.yml") ;;
      *) echo "database deployment refused; missing supervised database target" >&2; return 78 ;;
    esac
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
    local runtime_env_snapshot_file
    signboard_override_file="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-signboard-override.XXXXXX")"
    compose_stdout_file="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-compose-stdout.XXXXXX")"
    compose_stderr_file="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-compose-stderr.XXXXXX")"
    if [ "${channel}" = "dev" ] || [ "${channel}" = "test" ] || [ "${channel}" = "prod" ]; then
      runtime_env_snapshot_file="$(mktemp "${TMPDIR:-/tmp}/agentic-pkm-runtime-env.XXXXXX")"
    else
      runtime_env_snapshot_file=""
    fi
    # EXIT here is scoped to this `( ... )` subshell only (traps set inside a
    # subshell do not leak into the parent shell), so this fires exactly once
    # when the subshell running the actual Compose invocation exits, on every
    # path including an early `exit 1` above or a failing Compose command.
    trap 'rm -f -- "${signboard_override_file}" "${compose_stdout_file}" "${compose_stderr_file}"; if [ -n "${runtime_env_snapshot_file}" ]; then rm -f -- "${runtime_env_snapshot_file}"; fi' EXIT
    _deploy_channel_signboard_override_document > "${signboard_override_file}"
    compose_args+=(-f "${signboard_override_file}")

    # Compose gives the caller shell precedence over --env-file values. Pin the
    # governed selectors here so a stale parent shell cannot swap the selected
    # runtime env, provider selector, or vault after the decisions above. For
    # Product channels, pass a private point-in-time copy of the already-distinct runtime
    # env file: Compose cannot then follow a path replacement back to the
    # model-access file between preflight and reading its env_file. The copy is
    # a service env_file, never a CLI --env-file, so DSNs are not interpolated.
    if [ "${channel}" = "dev" ] || [ "${channel}" = "test" ] || [ "${channel}" = "prod" ]; then
      _deploy_channel_snapshot_runtime_env_file \
        "${runtime_env_file}" "${model_access_env_file}" "${runtime_env_snapshot_file}" || return $?
      deploy_channel_runtime_identity_matches_snapshot "${runtime_env_snapshot_file}" || return $?
      runtime_env_ref="${runtime_env_snapshot_file}"
    fi
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
    if [ "${action:-deploy}" != "rollback" ] && [ -n "${receipt_host_dir}" ]; then
      export DEVUI_VM102_RECEIPT_HOST_DIR="${receipt_host_dir}"
    else
      unset DEVUI_VM102_RECEIPT_HOST_DIR
    fi

    if [ "${HOST_SECRET_PROVIDER:-}" = "bws" ]; then
      unset HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE
      if _deploy_channel_needs_migration_secret "${channel}" "$@"; then
        export HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE="${BWS_MIGRATE_SECRET_ENV_FILE:?supervised migration secret handle required}"
      fi
    fi

    local -a compose_command
    compose_command=(
      docker compose
      --env-file "${channel_env_file}"
      "${compose_args[@]}"
      -p "${compose_project}"
      "$@"
    )

    if [ "${HOST_SECRET_PROVIDER:-}" != "bws" ] && _deploy_channel_needs_capture_secret "${channel}" "$@"; then
      compose_command=(
        "${PYTHON:-python3}" -m app.ops.host_secret_bootstrap
        --channel "${channel}"
        --consumer heimdal-capture-watch
        -- "${compose_command[@]}"
      )
    fi

    if [ "${HOST_SECRET_PROVIDER:-}" != "bws" ] && _deploy_channel_needs_api_ingress_secret "${channel}" "$@" \
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

    if [ "${HOST_SECRET_PROVIDER:-}" != "bws" ] && _deploy_channel_needs_migration_secret "${channel}" "$@"; then
      # Outermost so any future nested consumer bootstrap may scrub the shared
      # handle without erasing this migrate-only alias. The alias is only an
      # env-file path; the bootstrap owns/removes the file and never exports a
      # raw secret binding into the ambient process environment.
      compose_command=(
        sh -c 'cd "$1" && export PYTHONPATH="$1${PYTHONPATH:+:${PYTHONPATH}}" && shift && exec "$@"' _ "${root}"
        "${PYTHON:-python3}" -m app.ops.host_secret_bootstrap
        --channel "${channel}"
        --consumer heimdal-raw-migrate
        -- sh -c 'export HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE="${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"; unset HOST_SECRET_RUNTIME_ENV_FILE; exec "$@"' _
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
    # The MVR-05 deployment fence has one narrower internal `config` consumer:
    # it names an already-created private output file, and this wrapper writes
    # only service names, DB-role labels, dependencies, and the migration-runner
    # command there. Raw effective config never crosses this boundary.
    if [ "${1:-}" = "config" ] && [ -n "${DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT:-}" ]; then
      case "${DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT}" in
        /*) ;;
        *)
          echo "governed compose config handoff failed: output=invalid" >&2
          return 92
          ;;
      esac
      set +e
      "${compose_command[@]}" >"${compose_stdout_file}" 2>"${compose_stderr_file}"
      compose_rc=$?
      set -e
      if [ "${compose_rc}" -ne 0 ]; then
        echo "governed compose command failed: output=redacted" >&2
        return "${compose_rc}"
      fi
      if ! "${PYTHON:-python3}" "${root}/scripts/instance_state_writer_inventory.py" \
        redact-compose-fence-config \
        --compose-path "${compose_stdout_file}" \
        --output "${DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT}" \
        >"${compose_stderr_file}" 2>&1; then
        echo "governed compose config handoff failed: output=redacted" >&2
        return 92
      fi
      return 0
    fi
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
      elif [ "${DEPLOY_MIGRATION_GATE_TOKEN_ONLY:-0}" = "1" ]; then
        # The migration gate-only probe is the one governed command whose
        # stdout is an authority token. The caller validates its exact shape
        # and cardinality; no general Compose output crosses this boundary.
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
