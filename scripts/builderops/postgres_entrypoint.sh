#!/usr/bin/env bash
set -euo pipefail

source_secret="${BUILDEROPS_DATABASE_APP_PASSWORD_SECRET_FILE:?BuilderOps app-role source secret file is required}"
staged_secret="${BUILDEROPS_DATABASE_APP_PASSWORD_FILE:?BuilderOps app-role staged password file is required}"
staged_directory="/run/builderops-init"

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

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "$(id -u)" -eq 0 && ! -s "${PGDATA:-/var/lib/postgresql/data}/PG_VERSION" ]]; then
    stage_app_password
  fi

  exec /usr/local/bin/docker-entrypoint.sh "$@"
fi
