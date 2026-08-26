#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OPERATOR_ENV_FILE="${BUILDEROPS_OPERATOR_ENV_FILE:-/Users/Shared/builderops/operator.env}"
if [[ ! -r "$OPERATOR_ENV_FILE" ]]; then
  echo "BuilderOps operator environment file is unavailable" >&2
  exit 78
fi
secret_root="$(awk -F= '$1 == "BUILDEROPS_SECRET_ROOT" {print substr($0, index($0,"=")+1); exit}' "$OPERATOR_ENV_FILE")"
docker_context="$(awk -F= '$1 == "BUILDEROPS_DOCKER_CONTEXT" {print substr($0, index($0,"=")+1); exit}' "$OPERATOR_ENV_FILE")"
if [[ -z "$secret_root" || -z "$docker_context" ]]; then
  echo "BUILDEROPS_SECRET_ROOT and BUILDEROPS_DOCKER_CONTEXT are required" >&2
  exit 78
fi

python_bin="$(command -v python3)"
launch_agents="$HOME/Library/LaunchAgents"
mkdir -p "$launch_agents"

probe_plist="$launch_agents/com.yggdrasil.builderops-probe.plist"
sed -e "s#__PYTHON__#$python_bin#g" \
    -e "s#__PROBE__#$HERE/builderops_probe.py#g" \
    -e "s#__PROBE_TOKEN__#$secret_root/probe-token#g" \
    -e "s#__STATUS_TOKEN__#$secret_root/status-token#g" \
    -e "s#__DOCKER_CONTEXT__#$docker_context#g" \
    "$HERE/com.yggdrasil.builderops-probe.plist" >"$probe_plist"

launchctl unload "$probe_plist" 2>/dev/null || true
launchctl unload "$launch_agents/com.yggdrasil.builderops-backup.plist" 2>/dev/null || true
launchctl load "$probe_plist"
