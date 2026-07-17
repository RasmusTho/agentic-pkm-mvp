#!/usr/bin/env bash
set -euo pipefail

mode="${1:-configure}"
if [ "${mode}" != configure ] && [ "${mode}" != --preflight ]; then
  echo "usage: configure_tailnet_tls.sh [--preflight]" >&2
  exit 64
fi

backend_port="${BUILDEROPS_API_PORT:-18100}"
https_port="${BUILDEROPS_TAILNET_HTTPS_PORT:-443}"
if [[ ! "$backend_port" =~ ^[1-9][0-9]{1,4}$ || "$backend_port" -gt 65535 ]]; then
  echo "BUILDEROPS_API_PORT must be a valid TCP port" >&2
  exit 64
fi
if [[ ! "$https_port" =~ ^[1-9][0-9]{1,4}$ || "$https_port" -gt 65535 ]]; then
  echo "BUILDEROPS_TAILNET_HTTPS_PORT must be a valid TCP port" >&2
  exit 64
fi
command -v tailscale >/dev/null 2>&1 || {
  echo "tailscale CLI is required for the encrypted BuilderOps boundary" >&2
  exit 69
}

node_status="$(tailscale status --json)"
python3 -c '
import json, sys
status = json.load(sys.stdin)
if status.get("BackendState") != "Running":
    raise SystemExit("tailscale backend is not running")
' <<<"$node_status"

target="http://127.0.0.1:${backend_port}"
serve_status="$(tailscale serve status --json)"
python3 -c '
import json, os, sys
status = json.load(sys.stdin)

def active_funnel(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if "funnel" in str(key).lower() and child not in (False, None, "", [], {}):
                return True
            if active_funnel(child):
                return True
    elif isinstance(value, list):
        return any(active_funnel(child) for child in value)
    return False

if active_funnel(status):
    raise SystemExit("public Funnel exposure is forbidden for BuilderOps")
' <<<"$serve_status"

if [ "${mode}" = --preflight ]; then
  echo "BuilderOps tailnet preflight passed without mutation"
  exit 0
fi

tailscale serve --bg --yes --https="$https_port" "$target" >/dev/null
serve_status="$(tailscale serve status --json)"
TARGET="$target" HTTPS_PORT="$https_port" python3 -c '
import json, os, sys
status = json.load(sys.stdin)
encoded = json.dumps(status, sort_keys=True)
if os.environ["TARGET"] not in encoded or os.environ["HTTPS_PORT"] not in encoded:
    raise SystemExit("tailscale HTTPS serve mapping was not installed")
' <<<"$serve_status"

echo "BuilderOps tailnet HTTPS boundary maps :${https_port} to ${target}"
