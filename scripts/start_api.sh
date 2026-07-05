#!/bin/bash
set -euo pipefail

# DB wait + extensions + `alembic upgrade head` live in the shared migration
# authority (KERNEL-05, #2850). Under compose the `migrate` one-shot service
# has already completed by the time api starts (depends_on ordering), so this
# is an idempotent re-run; for bare-metal starts it is the migration producer.
bash "$(dirname "$0")/run_migrations.sh"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
