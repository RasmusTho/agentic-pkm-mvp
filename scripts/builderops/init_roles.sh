#!/usr/bin/env bash
set -euo pipefail

: "${BUILDEROPS_DATABASE_APP_PASSWORD_FILE:?BuilderOps app-role password file is required}"
: "${PGDATA:?PostgreSQL data directory is required}"
if [[ ! -r "$BUILDEROPS_DATABASE_APP_PASSWORD_FILE" ]]; then
  echo "BuilderOps app-role password file is unavailable" >&2
  exit 78
fi

# The entrypoint supplies a postgres-owned copy on tmpfs only for this first
# initialization. Remove it on both success and failure; the root-only Docker
# secret is never read by this script.
cleanup() {
  rm -f -- "$BUILDEROPS_DATABASE_APP_PASSWORD_FILE"
}
trap cleanup EXIT

# psql reads the tmpfs-staged file through its shell-capture meta-command;
# quoted variable interpolation then produces a correctly escaped SQL literal.
# The raw value never enters argv, the parent environment, or a durable SQL file.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 <<'SQL'
BEGIN;
\set app_password `cat "$BUILDEROPS_DATABASE_APP_PASSWORD_FILE"`
SELECT format('CREATE ROLE builderops_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'builderops_app')
\gexec
SELECT format('ALTER ROLE builderops_app LOGIN PASSWORD %L', :'app_password')
\gexec
GRANT CONNECT ON DATABASE builderops TO builderops_app;
GRANT USAGE ON SCHEMA public TO builderops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE builderops_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO builderops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE builderops_owner IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO builderops_app;
COMMIT;
SQL

umask 077
printf '%s\n' 'builderops-app-role-init-ready-v1' > "${PGDATA}/.builderops-app-role-init-ready"
rm -f -- "${PGDATA}/.builderops-app-role-init-pending"
