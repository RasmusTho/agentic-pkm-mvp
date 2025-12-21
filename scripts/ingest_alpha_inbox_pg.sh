#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DB_URL="postgresql://app:app@db:5432/app"
ENV_VARS="STORE_BACKEND=pg DATABASE_URL=$DB_URL DB_DSN=$DB_URL"
EXEC="docker exec -it workspace-api-1 bash -lc"

if ! docker ps --format '{{.Names}}' | grep -q '^workspace-api-1$'; then
  echo "workspace-api-1 is not running" >&2
  exit 1
fi

echo "1/2: Ingesting vault notes (pkm-alpha) via PG store..."
$EXEC "set -euo pipefail; $ENV_VARS python -m app.cli vault-alpha-ingest --vault-root /vault --max-notes 200 --include-test-note --force"

echo "2/2: Rebuilding embeddings from PG store..."
$EXEC "set -euo pipefail; $ENV_VARS python -m app.cli index rebuild --backend pg --strict"

echo "Ingest + index run finished."
