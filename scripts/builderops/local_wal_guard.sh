#!/usr/bin/env bash
set -euo pipefail

# This runs in the local control-plane database health check. A failed check is
# intentionally loud in Docker health status before WAL or the shared volume
# can exhaust the host disk.
pgdata="${PGDATA:-/var/lib/postgresql/data}"
wal_limit_bytes="${BUILDEROPS_LOCAL_WAL_MAX_BYTES:-2147483648}"
disk_limit_percent="${BUILDEROPS_LOCAL_DISK_MAX_USED_PERCENT:-85}"

archive_mode="$(psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -Atqc 'SHOW archive_mode')"
archive_command="$(psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -Atqc 'SHOW archive_command')"

if [[ "$archive_mode" != "off" && "$archive_mode" != "(disabled)" ]] || [[ -n "$archive_command" ]]; then
  echo "local BuilderOps WAL archive drift: archive_mode=$archive_mode archive_command=${archive_command:+set}" >&2
  exit 70
fi

wal_bytes="$(du -sb "$pgdata/pg_wal" | awk '{print $1}')"
if (( wal_bytes > wal_limit_bytes )); then
  echo "local BuilderOps WAL growth exceeds ${wal_limit_bytes} bytes: ${wal_bytes}" >&2
  exit 71
fi

disk_used_percent="$(df -P "$pgdata" | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')"
if [[ ! "$disk_used_percent" =~ ^[0-9]+$ ]] || (( disk_used_percent >= disk_limit_percent )); then
  echo "local BuilderOps disk usage guard exceeded ${disk_limit_percent}%: ${disk_used_percent:-unknown}%" >&2
  exit 72
fi
