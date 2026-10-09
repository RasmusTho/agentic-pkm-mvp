#!/usr/bin/env bash

# Resolve the one host-global ownership authority independently of checkout and
# Compose project. Callers export the absolute path before Compose interpolation.
resolve_instance_ownership_host_state_dir() {
  local configured="${INSTANCE_OWNERSHIP_HOST_STATE_DIR:-}"
  if [ -z "${configured}" ]; then
    configured="${XDG_STATE_HOME:-${HOME:?HOME is required}/.local/state}/agentic-pkm/instance-ownership"
  fi
  case "${configured}" in
    /*) ;;
    *)
      echo "INSTANCE_OWNERSHIP_HOST_STATE_DIR must be an absolute host path" >&2
      return 64
      ;;
  esac
  INSTANCE_OWNERSHIP_HOST_STATE_DIR="$(python3 - "${configured}" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
)" || return $?
  export INSTANCE_OWNERSHIP_HOST_STATE_DIR
}

resolve_instance_ownership_host_state_identity() {
  local caller_uid caller_gid runtime_uid runtime_gid
  caller_uid="$(id -u)" || return $?
  caller_gid="$(id -g)" || return $?

  if [ "${LOCAL_UID+x}${LOCAL_GID+x}" != "" ]; then
    runtime_uid="${LOCAL_UID:-}"
    runtime_gid="${LOCAL_GID:-}"
  else
    runtime_uid="${caller_uid}"
    runtime_gid="${caller_gid}"
  fi
  case "${runtime_uid}:${runtime_gid}" in
    *[!0-9:]*|:*|*:|*:*:*)
      echo "LOCAL_UID and LOCAL_GID must be a complete numeric runtime identity" >&2
      return 64
      ;;
  esac
  if [ "${caller_uid}" != "0" ] && \
      { [ "${runtime_uid}" != "${caller_uid}" ] || [ "${runtime_gid}" != "${caller_gid}" ]; }; then
    echo "non-root host-state access must use the caller's runtime identity" >&2
    return 64
  fi
  INSTANCE_OWNERSHIP_HOST_STATE_UID="${runtime_uid}"
  INSTANCE_OWNERSHIP_HOST_STATE_GID="${runtime_gid}"
  export INSTANCE_OWNERSHIP_HOST_STATE_UID INSTANCE_OWNERSHIP_HOST_STATE_GID
}

prepare_instance_ownership_host_state_dir() {
  resolve_instance_ownership_host_state_dir || return $?
  resolve_instance_ownership_host_state_identity || return $?
  python3 - \
    "${INSTANCE_OWNERSHIP_HOST_STATE_DIR}" \
    "${INSTANCE_OWNERSHIP_HOST_STATE_UID}" \
    "${INSTANCE_OWNERSHIP_HOST_STATE_GID}" <<'PY'
import os
import stat
import sys

path, raw_uid, raw_gid = sys.argv[1:]
if not raw_uid.isascii() or not raw_uid.isdecimal() or not raw_gid.isascii() or not raw_gid.isdecimal():
    raise SystemExit("host-global ownership state runtime identity is invalid")
uid_text = raw_uid.lstrip("0") or "0"
gid_text = raw_gid.lstrip("0") or "0"
# uid_t and gid_t are 32-bit unsigned values on the supported Linux hosts;
# the all-ones value is reserved by chown-family calls to mean "unchanged".
if (
    len(uid_text) > 10
    or len(gid_text) > 10
):
    raise SystemExit("host-global ownership state runtime identity is out of range")
runtime_uid, runtime_gid = int(uid_text), int(gid_text)
if runtime_uid > 4_294_967_294 or runtime_gid > 4_294_967_294:
    raise SystemExit("host-global ownership state runtime identity is out of range")
if os.geteuid() != 0 and (runtime_uid != os.geteuid() or runtime_gid != os.getegid()):
    raise SystemExit("host-global ownership state identity differs from the caller")
if os.path.realpath(path) != path:
    raise SystemExit("host-global ownership state directory must be canonical")

missing = []
cursor = path
while True:
    try:
        existing = os.lstat(cursor)
        break
    except FileNotFoundError:
        parent = os.path.dirname(cursor)
        if parent == cursor:
            raise SystemExit("host-global ownership state parent is unavailable")
        missing.append(cursor)
        cursor = parent

if not stat.S_ISDIR(existing.st_mode):
    raise SystemExit("host-global ownership state parent is not a directory")

def can_traverse(metadata):
    if runtime_uid == 0:
        return True
    if metadata.st_uid == runtime_uid:
        return bool(metadata.st_mode & stat.S_IXUSR)
    if metadata.st_gid == runtime_gid:
        return bool(metadata.st_mode & stat.S_IXGRP)
    return bool(metadata.st_mode & stat.S_IXOTH)

ancestor = cursor
while True:
    metadata = os.lstat(ancestor)
    if not stat.S_ISDIR(metadata.st_mode) or not can_traverse(metadata):
        raise SystemExit("host-global ownership state parent is not accessible to the runtime identity")
    if ancestor == os.path.dirname(ancestor):
        break
    ancestor = os.path.dirname(ancestor)

for directory in reversed(missing):
    created = False
    try:
        os.mkdir(directory, 0o700)
        created = True
    except FileExistsError:
        pass
    if created and os.geteuid() == 0:
        os.chown(directory, runtime_uid, runtime_gid)
    metadata = os.lstat(directory)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != runtime_uid
        or metadata.st_gid != runtime_gid
    ):
        raise SystemExit("host-global ownership state directory has an unexpected owner")

metadata = os.lstat(path)
if (
    not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != runtime_uid
    or metadata.st_gid != runtime_gid
):
    raise SystemExit("host-global ownership state directory has an unexpected owner")
if stat.S_IMODE(metadata.st_mode) != 0o700:
    os.chmod(path, 0o700)
    metadata = os.lstat(path)
if stat.S_IMODE(metadata.st_mode) != 0o700 or os.path.realpath(path) != path:
    raise SystemExit("host-global ownership state directory must be canonical and private")
PY
}
