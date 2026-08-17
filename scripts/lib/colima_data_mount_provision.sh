#!/usr/bin/env bash
# Refusal-first producer for the Colima persistent Docker/containerd mounts.
# The reviewed source and identity come from the systemd EnvironmentFile. This
# script never unmounts, prunes, recreates, deletes, or edits Docker metadata.
set -euo pipefail

persistent_path="${COLIMA_PERSISTENT_DATA_PATH:-}"
docker_path="${COLIMA_DOCKER_DATA_PATH:-/var/lib/docker}"
containerd_path="${COLIMA_CONTAINERD_DATA_PATH:-/var/lib/containerd}"
expected_source="${COLIMA_EXPECTED_PERSISTENT_SOURCE:-}"
expected_identity="${COLIMA_EXPECTED_PERSISTENT_IDENTITY:-}"
expected_fstype="${COLIMA_EXPECTED_PERSISTENT_FSTYPE:-}"

case "${1:-}" in
  --provision) ;;
  *)
    echo "usage: $0 --provision" >&2
    exit 64
    ;;
esac

[ -n "$persistent_path" ] && [ -n "$expected_source" ] && [ -n "$expected_identity" ] && [ -n "$expected_fstype" ] || {
  echo "persistent mount configuration is incomplete; refusing mount production" >&2
  exit 78
}

case "$expected_identity" in
  UUID=*|LABEL=*|PARTUUID=*) identity_field="${expected_identity%%=*}"; identity_value="${expected_identity#*=}" ;;
  *) echo "persistent mount identity is not canonical; refusing mount production" >&2; exit 78 ;;
esac
[ -n "$identity_value" ] || { echo "persistent mount identity is empty; refusing mount production" >&2; exit 78; }

mount_bin="${COLIMA_MOUNT_BIN:-mount}"
mountpoint_bin="${COLIMA_MOUNTPOINT_BIN:-mountpoint}"
findmnt_bin="${COLIMA_FINDMNT_BIN:-findmnt}"

normalize_source() {
  printf '%s\n' "${1%%\[*}"
}

findmnt_value() {
  local field="$1" target="$2"
  "$findmnt_bin" -n -o "$field" --target "$target" 2>/dev/null
}

verify_mount() {
  local target="$1" expected_fsroot="$2" actual_source actual_identity actual_fstype actual_fsroot
  actual_source="$(findmnt_value SOURCE "$target")" || return 1
  [ "$(normalize_source "$actual_source")" = "$(normalize_source "$expected_source")" ] || return 1
  actual_identity="$(findmnt_value "$identity_field" "$target")" || return 1
  [ "$actual_identity" = "$identity_value" ] || return 1
  actual_fstype="$(findmnt_value FSTYPE "$target")" || return 1
  [ "$actual_fstype" = "$expected_fstype" ] || return 1
  actual_fsroot="$(findmnt_value FSROOT "$target")" || return 1
  [ "$actual_fsroot" = "$expected_fsroot" ] || return 1
  "$mountpoint_bin" -q "$target" 2>/dev/null || return 1
  [ -d "$target" ] && [ -w "$target" ]
}

ensure_mount() {
  local target="$1" source="$2" fsroot="$3" kind="${4:-filesystem}"
  mkdir -p "$target"
  if ! "$mountpoint_bin" -q "$target" 2>/dev/null; then
    if [ "$kind" = "bind" ]; then
      mkdir -p "$source"
      "$mount_bin" --bind "$source" "$target"
    else
      "$mount_bin" -t "$expected_fstype" "$source" "$target"
    fi
  fi
  verify_mount "$target" "$fsroot" || {
    echo "persistent mount verification failed for $target; refusing readiness" >&2
    return 1
  }
}

ensure_mount "$persistent_path" "$expected_identity" "/"
ensure_mount "$docker_path" "$persistent_path/docker" "/docker" bind
ensure_mount "$containerd_path" "$persistent_path/containerd" "/containerd" bind
