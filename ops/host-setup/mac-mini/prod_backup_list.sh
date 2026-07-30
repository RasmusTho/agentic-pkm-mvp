#!/bin/bash
# Read-only dump lister for the prod-backup watcher's loopback ssh hop.
#
# Why this exists: launchd starts the watcher as an unattributed process with no
# TCC grants, so macOS refuses it access to /Volumes/T7 (verified on this host
# 2026-07-29 — `stat` succeeds while `listdir` returns EPERM). An sshd session
# does hold that access, so prod_backup_probe.py re-reads the directory through
# a loopback ssh into the same account and runs this script there.
#
# This is the only thing that key should ever be able to do. Install it as a
# forced command in ~/.ssh/authorized_keys:
#
#   command="$HOME/bin/prod-backup-list.sh",no-port-forwarding,no-agent-forwarding,\
#   no-X11-forwarding,no-pty ssh-ed25519 AAAA... prod-backup-list
#
# It only ever reads. It never writes, never touches the backup job, and never
# runs pg_dump — a broken backup must not be able to hide behind a broken watcher.
set -uo pipefail
export PATH=/usr/bin:/bin

DIR="${BACKUP_DIR:-/Volumes/T7/prod-db-backups}"

# Distinguish the three blind states the watcher must report differently:
# not mounted, mounted-but-unreadable, and readable-but-empty.
if [ ! -d "$DIR" ]; then
  echo "MISSING"
  exit 0
fi
if ! /bin/ls "$DIR" >/dev/null 2>&1; then
  echo "DENIED"
  exit 0
fi

# BSD stat: "<epoch-mtime> <path>" per matching file.
found=0
for f in "$DIR"/${BACKUP_GLOB:-prod-*.dump}; do
  [ -f "$f" ] || continue
  /usr/bin/stat -f '%m %N' "$f"
  found=1
done
[ "$found" -eq 1 ] || echo "EMPTY"
exit 0
