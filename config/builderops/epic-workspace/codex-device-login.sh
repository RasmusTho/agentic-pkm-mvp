#!/usr/bin/env bash
# One-time owner login for the epic workspace Terra reserve (#6615 / #6618).
# Runs the pinned native Codex CLI in a throwaway, capability-free container and writes the
# ChatGPT subscription login only into the controller-owned directory below. The owner completes
# the device code in a browser; no API key is used and no host credential store is copied.
# Usage (from the Mac):  ssh -t bob-1-builder-system '~/epic-sandbox/runner/current/config/builderops/epic-workspace/codex-device-login.sh'
set -euo pipefail
export DOCKER_HOST=unix:///var/run/docker.sock
dir="$HOME/.config/epic-workspace/codex"
umask 077
mkdir -p "$dir"
chmod 700 "$HOME/.config/epic-workspace" "$dir"
exec docker run --rm -it --network epicws --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,exec,nosuid,size=512m \
  -e HOME=/tmp -e CODEX_HOME=/run/codex-home \
  --mount "type=bind,source=$dir,target=/run/codex-home" \
  node:22-bookworm-slim npx -y @openai/codex@0.167.0 login --device-auth
