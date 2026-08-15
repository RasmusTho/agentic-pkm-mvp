#!/usr/bin/env bash
# Shared, refusal-first readiness contract for a Colima-hosted Docker daemon.
# Host entrypoints call colima_runtime_bind_and_ready. The checked-in guest
# helper is invoked by systemd with --guest or --docker-preflight. This file
# never prunes, recreates, deletes, or edits Docker/containerd metadata.

_colima_runtime_receipt() {
  local state="$1" reason="$2" persisted="${3:-}" docker_count="${4:-}"
  local path="${COLIMA_RUNTIME_RECEIPT_PATH:-}"
  [ -n "$path" ] || return 0
  COLIMA_RECEIPT_STATE="$state" \
  COLIMA_RECEIPT_REASON="$reason" \
  COLIMA_RECEIPT_PERSISTED="$persisted" \
  COLIMA_RECEIPT_DOCKER="$docker_count" \
  COLIMA_RECEIPT_CONTEXT="${DOCKER_CONTEXT:-${COLIMA_DOCKER_CONTEXT:-}}" \
  COLIMA_RECEIPT_SUBSTRATE="${COLIMA_SUBSTRATE_READY:-false}" \
  COLIMA_RECEIPT_CONTAINERD="${COLIMA_CONTAINERD_READY:-false}" \
  COLIMA_RECEIPT_METADATA="${COLIMA_METADATA_READY:-false}" \
  COLIMA_RECEIPT_INVENTORY="${COLIMA_INVENTORY_EXACT:-false}" \
  COLIMA_RECEIPT_PATH="$path" \
  python3 - "$path" <<'PY'
import json
import os
from pathlib import Path

def optional_int(name):
    value = os.environ.get(name, "")
    return int(value) if value.isdigit() else None

payload = {
    "schema": "colima-docker-startup-gate.v1",
    "state": os.environ.get("COLIMA_RECEIPT_STATE", "unknown"),
    "reason_code": os.environ.get("COLIMA_RECEIPT_REASON", "unknown"),
    "failure_reason": os.environ.get("COLIMA_RECEIPT_REASON", "unknown"),
    "docker_context": os.environ.get("COLIMA_RECEIPT_CONTEXT") or None,
    "persistent_substrate_ready": os.environ.get("COLIMA_RECEIPT_SUBSTRATE") == "true",
    "containerd_rpc_ready": os.environ.get("COLIMA_RECEIPT_CONTAINERD") == "true",
    "containerd_metadata_ready": os.environ.get("COLIMA_RECEIPT_METADATA") == "true",
    "persisted_inventory_count": optional_int("COLIMA_RECEIPT_PERSISTED"),
    "docker_inventory_count": optional_int("COLIMA_RECEIPT_DOCKER"),
    "inventory_exact": os.environ.get("COLIMA_RECEIPT_INVENTORY") == "true",
}
target = Path(os.environ["COLIMA_RECEIPT_PATH"])
target.parent.mkdir(parents=True, exist_ok=True)
temporary = target.with_suffix(target.suffix + ".tmp")
temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(target)
PY
}

_colima_runtime_fail() {
  local reason="$1"
  local display_reason="${reason//-/ }"
  printf 'ERROR: Colima runtime readiness refused (%s)\n' "$display_reason" >&2
  _colima_runtime_receipt "refused" "$reason" "${2:-}" "${3:-}"
  return 1
}

_colima_runtime_bounded() {
  local seconds="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    if [ -n "${COLIMA_BOUNDED_STDIN_FILE:-}" ]; then
      timeout --foreground "$seconds" "$@" < "$COLIMA_BOUNDED_STDIN_FILE"
    else
      timeout --foreground "$seconds" "$@"
    fi
    return $?
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    if [ -n "${COLIMA_BOUNDED_STDIN_FILE:-}" ]; then
      gtimeout "$seconds" "$@" < "$COLIMA_BOUNDED_STDIN_FILE"
    else
      gtimeout "$seconds" "$@"
    fi
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$seconds" "$@" <<'PY'
import os
import subprocess
import sys

try:
    stdin = open(os.environ["COLIMA_BOUNDED_STDIN_FILE"], "rb") if os.environ.get("COLIMA_BOUNDED_STDIN_FILE") else None
    result = subprocess.run(sys.argv[2:], check=False, timeout=float(sys.argv[1]), stdin=stdin)
except subprocess.TimeoutExpired:
    sys.exit(124)
finally:
    if "stdin" in locals() and stdin is not None:
        stdin.close()
sys.exit(result.returncode)
PY
    return $?
  fi
  return 124
}

_colima_runtime_findmnt() {
  local field="$1" target="$2"
  "${COLIMA_FINDMNT_BIN:-findmnt}" -n -o "$field" --target "$target" 2>/dev/null
}

_colima_runtime_require_writable_mount() {
  local path="$1" expected_source="$2" expected_identity="${COLIMA_EXPECTED_PERSISTENT_IDENTITY:-}" source source_base fstype identity_field identity_value blocks inodes
  "${COLIMA_MOUNTPOINT_BIN:-mountpoint}" -q "$path" 2>/dev/null || return 1
  [ -d "$path" ] && [ -w "$path" ] || return 1
  source="$(_colima_runtime_findmnt SOURCE "$path")" || return 1
  source_base="${source%%\[*}"
  [ "$source_base" = "$expected_source" ] || return 1
  case "$expected_identity" in
    UUID=*) identity_field=UUID; identity_value="${expected_identity#UUID=}";;
    LABEL=*) identity_field=LABEL; identity_value="${expected_identity#LABEL=}";;
    PARTUUID=*) identity_field=PARTUUID; identity_value="${expected_identity#PARTUUID=}";;
    *) return 1;;
  esac
  [ -n "$identity_value" ] || return 1
  identity="$(_colima_runtime_findmnt "$identity_field" "$path")" || return 1
  [ "$identity" = "$identity_value" ] || return 1
  fstype="$(_colima_runtime_findmnt FSTYPE "$path")" || return 1
  [ "$fstype" = "${COLIMA_EXPECTED_PERSISTENT_FSTYPE:-}" ] || return 1
  blocks="$(${COLIMA_DF_BIN:-df} -Pk "$path" 2>/dev/null | awk 'NR == 2 {print $4}')" || return 1
  inodes="$(${COLIMA_DF_BIN:-df} -Pi "$path" 2>/dev/null | awk 'NR == 2 {print $4}')" || return 1
  case "$blocks" in ''|*[!0-9]*) return 1;; esac
  case "$inodes" in ''|*[!0-9]*) return 1;; esac
  [ "$blocks" -ge "${COLIMA_MIN_FREE_BLOCKS:-1}" ] || return 1
  [ "$inodes" -ge "${COLIMA_MIN_FREE_INODES:-1}" ] || return 1
}

colima_guest_check_persistent_substrate() {
  local persistent_path="${COLIMA_PERSISTENT_DATA_PATH:-}"
  local docker_path="${COLIMA_DOCKER_DATA_PATH:-/var/lib/docker}"
  local containerd_path="${COLIMA_CONTAINERD_DATA_PATH:-/var/lib/containerd}"
  local expected_source="${COLIMA_EXPECTED_PERSISTENT_SOURCE:-}"
  [ -n "$persistent_path" ] && [ -n "$expected_source" ] || return 1
  _colima_runtime_require_writable_mount "$persistent_path" "$expected_source" || return 1
  _colima_runtime_require_writable_mount "$docker_path" "$expected_source" || return 1
  _colima_runtime_require_writable_mount "$containerd_path" "$expected_source" || return 1
  COLIMA_SUBSTRATE_READY=true
  export COLIMA_SUBSTRATE_READY
}

colima_guest_wait_containerd() {
  local ctr_bin="${COLIMA_CTR_BIN:-ctr}" namespace="${COLIMA_CONTAINERD_NAMESPACE:-moby}"
  local timeout_seconds="${COLIMA_CONTAINERD_READY_TIMEOUT_SECONDS:-180}"
  local sleep_seconds="${COLIMA_READINESS_SLEEP_SECONDS:-1}" deadline
  deadline=$((SECONDS + timeout_seconds))
  while true; do
    if _colima_runtime_bounded "${COLIMA_CTR_COMMAND_TIMEOUT_SECONDS:-15}" "$ctr_bin" version >/dev/null 2>&1 \
      && _colima_runtime_bounded "${COLIMA_CTR_COMMAND_TIMEOUT_SECONDS:-15}" "$ctr_bin" --namespace "$namespace" containers list >/dev/null 2>&1 \
      && _colima_runtime_bounded "${COLIMA_CTR_COMMAND_TIMEOUT_SECONDS:-15}" "$ctr_bin" --namespace "$namespace" snapshots list >/dev/null 2>&1; then
      COLIMA_CONTAINERD_READY=true
      COLIMA_METADATA_READY=true
      export COLIMA_CONTAINERD_READY COLIMA_METADATA_READY
      return 0
    fi
    [ "$SECONDS" -lt "$deadline" ] || return 1
    [ "$sleep_seconds" -gt 0 ] 2>/dev/null && sleep "$sleep_seconds"
  done
}

colima_guest_assert_persisted_inventory() {
  local persisted expected
  persisted="$(_colima_runtime_persisted_count)" || {
    _colima_runtime_fail persisted-inventory-root-not-readable
    return 1
  }
  case "$persisted" in ''|*[!0-9]*) _colima_runtime_fail persisted-inventory-count-unreadable; return 1;; esac
  expected="${COLIMA_EXPECTED_PERSISTED_INVENTORY:-}"
  case "$expected" in ''|*[!0-9]*) _colima_runtime_fail expected-inventory-count-not-configured "$persisted"; return 1;; esac
  if [ "$persisted" -ne "$expected" ]; then
    _colima_runtime_fail persisted-inventory-mismatch "$expected" "$persisted"
    return 1
  fi
  COLIMA_PERSISTED_INVENTORY_READY=true
  export COLIMA_PERSISTED_INVENTORY_READY
  _colima_runtime_receipt ready persisted-inventory-exact "$expected" "$persisted"
}

colima_guest_readiness_gate() {
  COLIMA_SUBSTRATE_READY=false
  COLIMA_CONTAINERD_READY=false
  COLIMA_METADATA_READY=false
  export COLIMA_SUBSTRATE_READY COLIMA_CONTAINERD_READY COLIMA_METADATA_READY
  if ! colima_guest_check_persistent_substrate; then
    _colima_runtime_fail persistent-substrate-not-ready
    return 1
  fi
  if ! colima_guest_wait_containerd; then
    _colima_runtime_fail containerd-rpc-or-metadata-not-ready
    return 1
  fi
  if [ "${COLIMA_INVENTORY_PREFLIGHT_REQUIRED:-1}" = "1" ] && ! colima_guest_assert_persisted_inventory; then
    return 1
  fi
  return 0
}

_colima_runtime_persisted_count() {
  local root="${COLIMA_PERSISTED_CONFIG_ROOT:-/var/lib/docker/containers}" count entries
  if [ -d "$root" ]; then
    entries="$(find "$root" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null)" || return 1
    printf '%s\n' "$entries" | awk 'NF {count++} END {print count + 0}'
    return 0
  fi
  if command -v "${COLIMA_BIN:-colima}" >/dev/null 2>&1; then
    entries="$(_colima_runtime_bounded "${COLIMA_SSH_TIMEOUT_SECONDS:-30}" "${COLIMA_BIN:-colima}" ssh --profile "${COLIMA_PROFILE:-default}" -- sh -c "find '$root' -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null")" || return 1
    count="$(printf '%s\n' "$entries" | awk 'NF {count++} END {print count + 0}')"
    printf '%s\n' "$count"
    return 0
  fi
  return 1
}

colima_runtime_assert_inventory() {
  local persisted expected docker_count
  persisted="$(_colima_runtime_persisted_count)" || {
    _colima_runtime_fail persisted-inventory-root-not-readable
    return 1
  }
  case "$persisted" in ''|*[!0-9]*) _colima_runtime_fail persisted-inventory-count-unreadable; return 1;; esac
  expected="${COLIMA_EXPECTED_PERSISTED_INVENTORY:-$persisted}"
  case "$expected" in ''|*[!0-9]*) _colima_runtime_fail expected-inventory-count-invalid; return 1;; esac
  DOCKER_CONTEXT="${COLIMA_DOCKER_CONTEXT:-${DOCKER_CONTEXT:-colima}}"
  export DOCKER_CONTEXT
  _colima_runtime_bounded "${COLIMA_DOCKER_COMMAND_TIMEOUT_SECONDS:-15}" docker context inspect "$DOCKER_CONTEXT" >/dev/null 2>&1 || {
    _colima_runtime_fail docker-context-not-ready "$expected" ""
    return 1
  }
  local docker_listing
  docker_listing="$(_colima_runtime_bounded "${COLIMA_DOCKER_COMMAND_TIMEOUT_SECONDS:-15}" docker ps -aq 2>/dev/null)" || {
    _colima_runtime_fail docker-inventory-unreadable "$expected" ""
    return 1
  }
  docker_count="$(printf '%s\n' "$docker_listing" | awk 'NF {count++} END {print count + 0}')"
  if [ "$docker_count" -ne "$expected" ]; then
    _colima_runtime_fail persisted-inventory-mismatch "$expected" "$docker_count"
    return 1
  fi
  COLIMA_INVENTORY_EXACT=true
  export COLIMA_INVENTORY_EXACT
  _colima_runtime_receipt ready inventory-exact "$expected" "$docker_count"
}

_colima_runtime_load_profile() {
  local profile_file="${COLIMA_RESOURCE_PROFILE_FILE:-}" key value
  [ -n "$profile_file" ] || return 0
  [ -r "$profile_file" ] || return 1
  while IFS='=' read -r key value; do
    case "$key" in
      COLIMA_RUNTIME_PROVIDER|COLIMA_PROFILE|COLIMA_DOCKER_CONTEXT|COLIMA_USERNET_TIMEOUT|LIMA_USERNET_TIMEOUT|COLIMA_EXPECTED_PERSISTENT_SOURCE|COLIMA_EXPECTED_PERSISTENT_IDENTITY|COLIMA_EXPECTED_PERSISTED_INVENTORY|COLIMA_EXPECTED_PERSISTENT_FSTYPE|COLIMA_PERSISTENT_DATA_PATH|COLIMA_DOCKER_DATA_PATH|COLIMA_CONTAINERD_DATA_PATH|COLIMA_PERSISTED_CONFIG_ROOT|COLIMA_MIN_FREE_BLOCKS|COLIMA_MIN_FREE_INODES|COLIMA_CPU|COLIMA_MEMORY|COLIMA_DISK)
        [ -n "$value" ] && export "$key=$value"
        ;;
    esac
  done < "$profile_file"
}

colima_runtime_bind_and_ready() {
  local root="${1:-.}" profile="${COLIMA_PROFILE:-default}" colima_bin="${COLIMA_BIN:-colima}"
  _colima_runtime_load_profile || { _colima_runtime_fail resource-profile-unreadable; return 1; }
  profile="${COLIMA_PROFILE:-$profile}"
  if [ "${COLIMA_RUNTIME_PROVIDER:-}" != "colima" ]; then
    [ "${COLIMA_READINESS_REQUIRED:-0}" = "1" ] || return 0
    _colima_runtime_fail colima-provider-not-declared
    return 1
  fi
  if ! command -v "$colima_bin" >/dev/null 2>&1; then
    [ "${COLIMA_READINESS_REQUIRED:-0}" = "1" ] || return 0
    _colima_runtime_fail colima-command-unavailable
    return 1
  fi
  DOCKER_CONTEXT="${COLIMA_DOCKER_CONTEXT:-colima}"
  LIMA_USERNET_TIMEOUT="${COLIMA_USERNET_TIMEOUT:-${LIMA_USERNET_TIMEOUT:-120}}"
  export DOCKER_CONTEXT COLIMA_PROFILE="$profile" LIMA_USERNET_TIMEOUT
  if ! _colima_runtime_bounded "${COLIMA_STATUS_TIMEOUT_SECONDS:-30}" "$colima_bin" status --profile "$profile" --json >/dev/null 2>&1; then
    if [ "${AUTO_START_COLIMA:-0}" = "1" ]; then
      _colima_runtime_bounded "${COLIMA_START_TIMEOUT_SECONDS:-180}" "$colima_bin" start --profile "$profile" >/dev/null 2>&1 || { _colima_runtime_fail colima-start-failed; return 1; }
    else
      _colima_runtime_fail colima-not-ready
      return 1
    fi
  fi
  _colima_runtime_bounded "${COLIMA_DOCKER_COMMAND_TIMEOUT_SECONDS:-15}" docker context inspect "$DOCKER_CONTEXT" >/dev/null 2>&1 || { _colima_runtime_fail docker-context-not-ready; return 1; }
  _colima_runtime_bounded "${COLIMA_DOCKER_COMMAND_TIMEOUT_SECONDS:-15}" docker info >/dev/null 2>&1 || { _colima_runtime_fail docker-api-not-ready; return 1; }
  _colima_runtime_bounded "${COLIMA_SSH_TIMEOUT_SECONDS:-30}" "$colima_bin" ssh --profile "$profile" -- "${COLIMA_GUEST_READINESS_COMMAND:-/usr/local/libexec/yggdrasil-colima-runtime-readiness}" --docker-preflight || { _colima_runtime_fail guest-substrate-or-containerd-not-ready; return 1; }
  colima_runtime_assert_inventory || return 1
  printf 'Colima runtime readiness: ready (profile=%s context=%s root=%s)\n' "$profile" "$DOCKER_CONTEXT" "$root" >&2
}

if [ "${1:-}" = "--substrate" ]; then
  colima_guest_check_persistent_substrate || _colima_runtime_fail persistent-substrate-not-ready
elif [ "${1:-}" = "--guest" ] || [ "${1:-}" = "--docker-preflight" ]; then
  COLIMA_INVENTORY_PREFLIGHT_REQUIRED=1
  export COLIMA_INVENTORY_PREFLIGHT_REQUIRED
  colima_guest_readiness_gate
fi
