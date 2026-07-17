#!/usr/bin/env bash
set -euo pipefail

: "${PGDATA:?PGDATA is required}"
: "${WALG_S3_PREFIX:?WALG_S3_PREFIX is required}"
: "${AWS_ACCESS_KEY_ID_FILE:?AWS_ACCESS_KEY_ID_FILE is required}"
: "${AWS_SECRET_ACCESS_KEY_FILE:?AWS_SECRET_ACCESS_KEY_FILE is required}"
: "${WALG_LIBSODIUM_KEY_FILE:?WALG_LIBSODIUM_KEY_FILE is required}"

for secret_file in "$AWS_ACCESS_KEY_ID_FILE" "$AWS_SECRET_ACCESS_KEY_FILE" "$WALG_LIBSODIUM_KEY_FILE"; do
  if [[ ! -r "$secret_file" ]]; then
    echo "required recovery credential file is unavailable" >&2
    exit 78
  fi
done

export AWS_ACCESS_KEY_ID="$(<"$AWS_ACCESS_KEY_ID_FILE")"
export AWS_SECRET_ACCESS_KEY="$(<"$AWS_SECRET_ACCESS_KEY_FILE")"
export WALG_LIBSODIUM_KEY="$(<"$WALG_LIBSODIUM_KEY_FILE")"
export WALG_LIBSODIUM_KEY_TRANSFORM=base64
if [[ -n "${PGPASSWORD_FILE:-}" ]]; then
  if [[ ! -r "$PGPASSWORD_FILE" ]]; then
    echo "database credential file is unavailable" >&2
    exit 78
  fi
  export PGPASSWORD="$(<"$PGPASSWORD_FILE")"
fi

wal-g backup-push "$PGDATA"

retain_full="${BUILDEROPS_BACKUP_RETAIN_FULL:-14}"
if [[ ! "$retain_full" =~ ^[1-9][0-9]*$ ]]; then
  echo "BUILDEROPS_BACKUP_RETAIN_FULL must be a positive integer" >&2
  exit 64
fi
# WAL-G retains the WAL chain required by the kept full backups; deletion is
# explicit and runs only after a new encrypted full backup succeeded.
exec wal-g delete retain FULL "$retain_full" --confirm
