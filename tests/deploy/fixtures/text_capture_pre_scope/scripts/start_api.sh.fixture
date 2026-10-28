#!/bin/bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  if [ "$#" -ne 2 ] || [ "$1" != --source-bootstrap-only ]; then
    exit 78
  fi
  # Same API instance/target/database context; the selector grants no authority.
  python -m app.ops.native_source_bootstrap --preflight "$2" || exit $?
fi

# DB wait + extensions + `alembic upgrade head` live in the shared migration
# authority (KERNEL-05, #2850). Under compose the `migrate` one-shot service
# has already completed by the time api starts (depends_on ordering), so this
# is an idempotent re-run; for bare-metal starts it is the migration producer.
bash "$(dirname "$0")/run_migrations.sh"

if [ "$#" -ne 0 ]; then
  exec python -m app.ops.native_source_bootstrap --run "$2"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
