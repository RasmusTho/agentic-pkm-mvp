#!/usr/bin/env bash
# Install the checked-in Colima guest readiness artifacts.
# Default is a redacted dry-run. Set COLIMA_RUNTIME_APPLY=1 only from the
# governed host procedure after the isolated candidate proof is accepted.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
PROFILE="${COLIMA_PROFILE:-default}"
COLIMA_BIN="${COLIMA_BIN:-colima}"
GUEST_LIBEXEC="/usr/local/libexec"
GUEST_SYSTEMD="/etc/systemd/system"

if ! command -v "$COLIMA_BIN" >/dev/null 2>&1; then
  echo "Colima command is unavailable; refusing host artifact installation" >&2
  exit 78
fi

echo "Colima readiness install plan: profile=${PROFILE} context=${COLIMA_DOCKER_CONTEXT:-colima}"
echo "Artifacts: helper, substrate unit, containerd drop-in, docker drop-in"
if [ "${COLIMA_RUNTIME_APPLY:-0}" = "1" ]; then
  echo "Mutation: enabled"
else
  echo "Mutation: refused-dry-run"
  exit 0
fi

install_guest_file() {
  local source="$1" target="$2" mode="$3"
  "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo mkdir -p "$(dirname "$target")"
  "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo install -m "$mode" /dev/stdin "$target" < "$source"
}

install_guest_file "$ROOT/scripts/lib/colima_runtime_readiness.sh" \
  "$GUEST_LIBEXEC/yggdrasil-colima-runtime-readiness" 0755
install_guest_file "$HERE/systemd/yggdrasil-colima-persistent-substrate.service" \
  "$GUEST_SYSTEMD/yggdrasil-colima-persistent-substrate.service" 0644
install_guest_file "$HERE/systemd/containerd.service.d/20-yggdrasil-persistent-substrate.conf" \
  "$GUEST_SYSTEMD/containerd.service.d/20-yggdrasil-persistent-substrate.conf" 0644
install_guest_file "$HERE/systemd/docker.service.d/20-yggdrasil-containerd-readiness.conf" \
  "$GUEST_SYSTEMD/docker.service.d/20-yggdrasil-containerd-readiness.conf" 0644

"$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl daemon-reload
"$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl enable yggdrasil-colima-persistent-substrate.service
echo "Colima readiness artifacts installed; no service restart was requested"
