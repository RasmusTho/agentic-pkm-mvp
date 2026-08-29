#!/usr/bin/env bash
set -euo pipefail

readonly source_secret="/run/secrets/builderops_database_app_password"
staged_secret="${BUILDEROPS_DATABASE_APP_PASSWORD_FILE:?BuilderOps app-role staged password file is required}"
staged_directory="/run/builderops-init"
pgdata="${PGDATA:-/var/lib/postgresql/data}"
initialization_pending="${pgdata}/.builderops-app-role-init-pending"
initialization_ready="${pgdata}/.builderops-app-role-init-ready"

# The official entrypoint drops root before it executes initdb scripts. Stage
# only the app-role password, only before the initial PGDATA bootstrap, and
# only into the postgres-owned tmpfs declared by the BuilderOps Compose file.
stage_app_password() {
  if [[ ! -r "$source_secret" ]]; then
    echo "BuilderOps app-role source secret file is unavailable" >&2
    exit 78
  fi
  if [[ "$(stat -c '%u:%a' "$source_secret")" != "0:600" ]]; then
    echo "BuilderOps app-role source secret metadata is not root-only" >&2
    exit 78
  fi
  if [[ "$staged_secret" != "$staged_directory/app-password" ]] || ! awk \
    -v target="$staged_directory" '$2 == target && $3 == "tmpfs" { found = 1 } END { exit !found }' \
    /proc/mounts; then
    echo "BuilderOps app-role staging tmpfs is unavailable" >&2
    exit 78
  fi
  install -d -m 0700 -o postgres -g postgres "$staged_directory"
  install -m 0400 -o postgres -g postgres "$source_secret" "$staged_secret"
}

prepare_initialization_state() {
  if [[ ! -s "${pgdata}/PG_VERSION" ]]; then
    install -m 0600 -o postgres -g postgres /dev/null "$initialization_pending"
    stage_app_password
    return
  fi
  if [[ -e "$initialization_pending" ]]; then
    if [[ ! -s "$initialization_ready" || -L "$initialization_ready" ]]; then
      echo "BuilderOps PostgreSQL initialization is incomplete; refusing startup" >&2
      exit 78
    fi
    rm -f -- "$initialization_pending"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "$(id -u)" -eq 0 ]]; then
    prepare_initialization_state
  fi

  exec /usr/local/bin/docker-entrypoint.sh "$@"
fi
