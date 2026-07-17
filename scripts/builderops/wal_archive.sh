#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: wal_archive.sh push <postgres-wal-path> | fetch <wal-name> <destination>" >&2
  exit 64
fi
mode=$1

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

case "$mode" in
  push)
    [[ $# -eq 2 && -f "$2" ]] || exit 64
    # Success means the segment reached the remote object target. PostgreSQL
    # retries failures; local commits never call this wrapper.
    exec wal-g wal-push "$2"
    ;;
  fetch)
    [[ $# -eq 3 && -n "$2" && -n "$3" ]] || exit 64
    exec wal-g wal-fetch "$2" "$3"
    ;;
  *)
    echo "unsupported WAL archive operation" >&2
    exit 64
    ;;
esac
