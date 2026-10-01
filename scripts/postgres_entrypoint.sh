#!/usr/bin/env bash
# BWS-04: preserve the official image initialization protocol, but never pass
# credential environment variables to either temporary or steady-state servers.
set -Eeo pipefail
source /usr/local/bin/docker-entrypoint.sh

pg_ctl() {
  env -u POSTGRES_PASSWORD -u PGPASSWORD pg_ctl "$@"
}

exec() {
  # The upstream root-to-postgres re-exec must return through this wrapper.
  # Its inherited password exists only in the short-lived initialization shell;
  # file_env has already removed POSTGRES_PASSWORD_FILE on that upstream path.
  if [[ "${1:-}" == gosu && "${2:-}" == postgres && "${3:-}" == /usr/local/bin/docker-entrypoint.sh ]]; then
    builtin exec gosu postgres /usr/local/bin/yggdrasil-postgres-entrypoint.sh "${@:4}"
  fi
  unset POSTGRES_PASSWORD PGPASSWORD
  builtin exec "$@"
}

_main "$@"
