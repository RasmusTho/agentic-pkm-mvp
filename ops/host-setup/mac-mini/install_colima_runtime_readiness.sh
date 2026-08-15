#!/usr/bin/env bash
# Install the checked-in Colima guest readiness artifacts.
# Default is a redacted dry-run. Set COLIMA_RUNTIME_APPLY=1 only from the
# governed host procedure after the isolated candidate proof is accepted.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
source "$ROOT/scripts/lib/colima_runtime_readiness.sh"
PROFILE="${COLIMA_PROFILE:-default}"
COLIMA_BIN="${COLIMA_BIN:-colima}"
GUEST_LIBEXEC="/usr/local/libexec"
GUEST_CONFIG="/etc/yggdrasil"
GUEST_SYSTEMD="/etc/systemd/system"

if ! command -v "$COLIMA_BIN" >/dev/null 2>&1; then
  echo "Colima command is unavailable; refusing host artifact installation" >&2
  exit 78
fi

echo "Colima readiness install plan: profile=${PROFILE} context=${COLIMA_DOCKER_CONTEXT:-colima}"
echo "Artifacts: helper, mount boundary, substrate unit, containerd drop-in, docker drop-in"
if [ "${COLIMA_RUNTIME_APPLY:-0}" = "1" ]; then
  echo "Mutation: enabled"
else
  echo "Mutation: refused-dry-run"
  exit 0
fi

RUNTIME_ENV_FILE="${COLIMA_RUNTIME_ENV_FILE:-}"
if [ -z "$RUNTIME_ENV_FILE" ] || [ ! -r "$RUNTIME_ENV_FILE" ]; then
  echo "COLIMA_RUNTIME_ENV_FILE must name an operator-reviewed guest environment file" >&2
  exit 78
fi
for required_key in COLIMA_RUNTIME_PROVIDER COLIMA_EXPECTED_PERSISTENT_SOURCE COLIMA_EXPECTED_PERSISTENT_FSTYPE COLIMA_PERSISTENT_DATA_PATH; do
  if ! awk -F= -v key="$required_key" '$1 == key && $2 != "" {found=1} END {exit(found ? 0 : 1)}' "$RUNTIME_ENV_FILE"; then
    echo "guest environment is missing required key: $required_key" >&2
    exit 78
  fi
done
if ! awk -F= '
  BEGIN {
    split("COLIMA_RUNTIME_PROVIDER COLIMA_PROFILE COLIMA_DOCKER_CONTEXT COLIMA_USERNET_TIMEOUT LIMA_USERNET_TIMEOUT COLIMA_EXPECTED_PERSISTENT_SOURCE COLIMA_EXPECTED_PERSISTENT_FSTYPE COLIMA_PERSISTENT_DATA_PATH COLIMA_DOCKER_DATA_PATH COLIMA_CONTAINERD_DATA_PATH COLIMA_PERSISTED_CONFIG_ROOT COLIMA_MIN_FREE_BLOCKS COLIMA_MIN_FREE_INODES COLIMA_CPU COLIMA_MEMORY COLIMA_DISK", keys, " ")
    for (i in keys) allowed[keys[i]] = 1
  }
  /^[[:space:]]*#/ || NF == 0 {next}
  !allowed[$1] {bad=1}
  END {exit(bad ? 1 : 0)}
' "$RUNTIME_ENV_FILE"; then
  echo "guest environment contains an unapproved key" >&2
  exit 78
fi

install_guest_file() {
  local source="$1" target="$2" mode="$3"
  _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo mkdir -p "$(dirname "$target")"
  COLIMA_BOUNDED_STDIN_FILE="$source" _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo install -m "$mode" /dev/stdin "$target"
}

install_guest_file_atomic() {
  local source="$1" target="$2" mode="$3"
  local temporary="${target}.new"
  _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo mkdir -p "$(dirname "$target")"
  COLIMA_BOUNDED_STDIN_FILE="$source" _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo install -m "$mode" /dev/stdin "$temporary"
  _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo mv "$temporary" "$target"
}

install_guest_file "$ROOT/scripts/lib/colima_runtime_readiness.sh" \
  "$GUEST_LIBEXEC/yggdrasil-colima-runtime-readiness" 0755
install_guest_file "$HERE/systemd/yggdrasil-colima-persistent-substrate.service" \
  "$GUEST_SYSTEMD/yggdrasil-colima-persistent-substrate.service" 0644
install_guest_file "$HERE/systemd/colima-data-mount.service" \
  "$GUEST_SYSTEMD/colima-data-mount.service" 0644
install_guest_file "$HERE/systemd/containerd.service.d/20-yggdrasil-persistent-substrate.conf" \
  "$GUEST_SYSTEMD/containerd.service.d/20-yggdrasil-persistent-substrate.conf" 0644
install_guest_file "$HERE/systemd/docker.service.d/20-yggdrasil-containerd-readiness.conf" \
  "$GUEST_SYSTEMD/docker.service.d/20-yggdrasil-containerd-readiness.conf" 0644
install_guest_file_atomic "$RUNTIME_ENV_FILE" "$GUEST_CONFIG/colima-runtime.env" 0644

_colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl daemon-reload
_colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl enable yggdrasil-colima-persistent-substrate.service
echo "Colima readiness artifacts installed; no service restart was requested"
