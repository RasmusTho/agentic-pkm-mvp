#!/usr/bin/env bash
# scripts/builderops_api_client.sh — API-only BuilderOps control-plane client
# wrapper for automation worktrees.
#
# Runs the authenticated control-plane client:
#
#   python3 -m app.builderops.control_plane <command> ...
#
# This is the cutover replacement for the legacy direct-SQLite BuilderOps CLI
# wrapper. It reaches the independent BuilderOps service over ONE authenticated
# API boundary. It exposes NO --db-path, opens NO local SQLite database, and
# SSHes into NO database-owning CLI. When the service is unavailable or the
# credential is rejected, the client fails closed (non-zero exit) and never
# creates local authority.
#
# Usage from any automation worktree (cwd is the repo root or any worktree).
# Output is always a JSON object on stdout; no --json flag exists or is needed:
#
#   scripts/builderops_api_client.sh status
#   scripts/builderops_api_client.sh record \
#     --repository RasmusTho/agentic-pkm-mvp --scope issue:3791 \
#     --stack builderops-control-plane --source-ref github:issue:3791 \
#     --record-id learning-3791 --record-type LearningSignal --state active \
#     --idempotency-key record-learning-3791
#
# Mutations additionally require host/worktree-owned route configuration; the
# wrapper injects it before the subcommand so callers cannot accidentally skip
# the CLI's fail-closed manifest gate:
#   BUILDEROPS_DELIVERY_MANIFEST_DIR — directory containing addressed-repo manifests
#   BUILDEROPS_TASK_CLASS            — route task class (for example implementation)
#
# Credentials are host-owned and never inlined here or committed to the repo:
#   BUILDEROPS_API_URL         — control-plane base URL (required), e.g.
#                                https://<builderops-host>.<tailnet>.ts.net:<port>
#   BUILDEROPS_API_TOKEN_FILE  — path to a host secret file holding the scoped
#                                bearer token (preferred), OR
#   BUILDEROPS_API_TOKEN       — the scoped bearer token in the environment
#
# Exactly one of BUILDEROPS_API_TOKEN_FILE or BUILDEROPS_API_TOKEN is set by the
# host; the token value is read transiently and is never logged.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/lib/resolve_repo_python.sh"

PYTHON="$(builderops_resolve_python "$APP_ROOT")" || true
if [ -z "$PYTHON" ]; then
    echo "ERROR: BuilderOps API client requires the repo virtualenv, but no usable .venv/bin/python3 was found." >&2
    echo "Run from the canonical checkout, or create the canonical repo venv first:" >&2
    echo "  cd /Users/rasmusthornberg/code/agentic-pkm-mvp && python3 -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

if [ -z "${BUILDEROPS_API_URL:-}" ]; then
    echo "ERROR: BUILDEROPS_API_URL is required (host-owned control-plane base URL)." >&2
    echo "The API-only client requires the control-plane API; it has no local-store fallback." >&2
    exit 2
fi

cd "$APP_ROOT"
case "${1:-}" in
    status|receipt)
        exec "$PYTHON" -m app.builderops.control_plane "$@"
        ;;
    "")
        exec "$PYTHON" -m app.builderops.control_plane "$@"
        ;;
    *)
        if [ -z "${BUILDEROPS_DELIVERY_MANIFEST_DIR:-}" ] || [ -z "${BUILDEROPS_TASK_CLASS:-}" ]; then
            echo "ERROR: BuilderOps mutations require BUILDEROPS_DELIVERY_MANIFEST_DIR and BUILDEROPS_TASK_CLASS." >&2
            exit 2
        fi
        exec "$PYTHON" -m app.builderops.control_plane \
            --delivery-manifest-dir "$BUILDEROPS_DELIVERY_MANIFEST_DIR" \
            --task-class "$BUILDEROPS_TASK_CLASS" "$@"
        ;;
esac
