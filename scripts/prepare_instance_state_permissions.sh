#!/usr/bin/env bash

# Establish the private ownership contract for the two instance-state roots.
# Some macOS/Colima bind mounts reject a redundant recursive chown even when
# every existing entry already has the requested owner and group. Preflight
# the complete tree first so that a matching mount needs no chown at all; an
# actual mismatch still requires a successful repair. Python is used for the
# metadata walk because this script runs in the Linux image while its contract
# is exercised from macOS/Colima hosts as well.

set -euo pipefail

: "${LOCAL_UID:?LOCAL_UID is required}"
: "${LOCAL_GID:?LOCAL_GID is required}"

case "${LOCAL_UID}" in
  ''|*[!0-9]*)
    echo "instance-state permissions: LOCAL_UID must be numeric" >&2
    exit 78
    ;;
esac
case "${LOCAL_GID}" in
  ''|*[!0-9]*)
    echo "instance-state permissions: LOCAL_GID must be numeric" >&2
    exit 78
    ;;
esac

if [ "$#" -eq 0 ]; then
  echo "instance-state permissions: at least one root is required" >&2
  exit 78
fi

for root in "$@"; do
  test -d "${root}" || {
    echo "instance-state permissions: required root is missing" >&2
    exit 1
  }

  preflight_rc=0
  python - "${LOCAL_UID}" "${LOCAL_GID}" "${root}" <<'PY' || preflight_rc=$?
import os
import stat
import sys

uid = int(sys.argv[1])
gid = int(sys.argv[2])
root = sys.argv[3]
stack = [root]
mismatch = False

while stack:
    current = stack.pop()
    try:
        metadata = os.lstat(current)
    except OSError:
        raise SystemExit(11)
    if not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit(11)
    if metadata.st_uid != uid or metadata.st_gid != gid:
        mismatch = True
    if current == root and stat.S_IMODE(metadata.st_mode) != 0o700:
        mismatch = True
    try:
        entries = list(os.scandir(current))
    except OSError:
        raise SystemExit(11)
    for entry in entries:
        try:
            entry_metadata = entry.stat(follow_symlinks=False)
        except OSError:
            raise SystemExit(11)
        if entry_metadata.st_uid != uid or entry_metadata.st_gid != gid:
            mismatch = True
        if stat.S_ISDIR(entry_metadata.st_mode):
            stack.append(entry.path)

raise SystemExit(10 if mismatch else 0)
PY

  case "${preflight_rc}" in
    0)
      ;;
    10)
      chown -R "${LOCAL_UID}:${LOCAL_GID}" "${root}"
      ;;
    *)
      echo "instance-state permissions: ownership preflight failed" >&2
      exit "${preflight_rc}"
      ;;
  esac

  chmod 0700 "${root}"
done
