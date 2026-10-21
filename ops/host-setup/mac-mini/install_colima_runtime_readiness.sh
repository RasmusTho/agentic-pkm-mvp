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
echo "Artifacts: helper, mount producer, mount boundary, substrate unit, containerd drop-in, docker drop-in"
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
python3 - "$RUNTIME_ENV_FILE" "$PROFILE" <<'PYVALIDATE'
import re
import sys
from pathlib import Path
allowed = set("COLIMA_RUNTIME_PROVIDER COLIMA_PROFILE COLIMA_DOCKER_CONTEXT LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT COLIMA_EXPECTED_PERSISTENT_IDENTITY COLIMA_EXPECTED_PERSISTED_INVENTORY COLIMA_EXPECTED_PERSISTENT_FSTYPE COLIMA_PERSISTENT_DATA_PATH COLIMA_DOCKER_DATA_PATH COLIMA_CONTAINERD_DATA_PATH COLIMA_PERSISTED_CONFIG_ROOT COLIMA_MIN_FREE_BLOCKS COLIMA_MIN_FREE_INODES COLIMA_CPU COLIMA_MEMORY COLIMA_DISK".split())
values = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line or line.startswith("#"):
        continue
    key, sep, value = line.partition("=")
    if not sep or key not in allowed or key in values or not re.fullmatch(r"[a-zA-Z0-9_./:=+-]+", value):
        sys.exit("invalid, duplicate, or nonliteral Colima profile assignment")
    values[key] = value
for key in ("COLIMA_PROFILE", "COLIMA_DOCKER_CONTEXT", "LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT", "COLIMA_RUNTIME_PROVIDER", "COLIMA_EXPECTED_PERSISTENT_IDENTITY", "COLIMA_EXPECTED_PERSISTED_INVENTORY", "COLIMA_EXPECTED_PERSISTENT_FSTYPE", "COLIMA_PERSISTENT_DATA_PATH", "COLIMA_MIN_FREE_BLOCKS", "COLIMA_MIN_FREE_INODES", "COLIMA_CPU", "COLIMA_MEMORY", "COLIMA_DISK"):
    if key not in values:
        sys.exit("missing required profile field: " + key)
if values["COLIMA_PROFILE"] != sys.argv[2]:
    sys.exit("profile target differs from reviewed configuration")
if values["COLIMA_RUNTIME_PROVIDER"] != "colima" or values["COLIMA_EXPECTED_PERSISTENT_FSTYPE"] != "ext4":
    sys.exit("unapproved runtime or persistent filesystem")
if not re.fullmatch(r"(?:UUID|LABEL|PARTUUID)=[a-zA-Z0-9_.+-]+", values["COLIMA_EXPECTED_PERSISTENT_IDENTITY"]):
    sys.exit("persistent identity must be a stable filesystem identifier")
for key in ("COLIMA_EXPECTED_PERSISTED_INVENTORY", "COLIMA_MIN_FREE_BLOCKS", "COLIMA_MIN_FREE_INODES", "COLIMA_CPU", "COLIMA_MEMORY", "COLIMA_DISK"):
    if not values[key].isdigit() or (key != "COLIMA_EXPECTED_PERSISTED_INVENTORY" and int(values[key]) == 0):
        sys.exit("invalid numeric Colima profile field: " + key)
for key, expected in {
    "COLIMA_DOCKER_DATA_PATH": "/var/lib/docker",
    "COLIMA_CONTAINERD_DATA_PATH": "/var/lib/containerd",
    "COLIMA_PERSISTED_CONFIG_ROOT": "/var/lib/docker/containers",
}.items():
    if values.get(key, expected) != expected:
        sys.exit("unsupported daemon metadata path: " + key)
persistent = values["COLIMA_PERSISTENT_DATA_PATH"]
if not persistent.startswith("/") or "/../" in persistent + "/" or persistent in ("/", "/var", "/var/lib", "/var/lib/docker", "/var/lib/containerd"):
    sys.exit("persistent mount must be a distinct absolute mount target")
if not values["LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT"].isdigit() or not 3 <= int(values["LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT"]) <= 15:
    sys.exit("usernet timeout must be a bounded integer in minutes (3..15)")
PYVALIDATE
# Cold-start serialization and isolated proof are established by the operator
# runbook, never inferred from this installer or a successful CLI exit.
[ "${COLIMA_COLD_START_AUTHORIZED:-0}" = 1 ] || { echo "host serialization not established" >&2; exit 78; }
if [ "$PROFILE" = default ]; then
  [ "${COLIMA_ISOLATED_PROOF_ACCEPTED:-0}" = 1 ] || { echo "isolated proof required before default installation" >&2; exit 78; }
fi
# Variables in the remote script are expanded in the guest.
# shellcheck disable=SC2016
_colima_runtime_bounded 30 "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo sh -c '
  for unit in docker.service docker.socket containerd.service; do
    state=$(systemctl show "$unit" -p ActiveState --value) || exit 1
    case "$state" in inactive|failed) ;; *) exit 1;; esac
  done
'

# Persist across installer failure and guest reboot. Never remove these masks
# until every artifact and configuration has been installed and read back.
_colima_runtime_bounded 30 "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl mask docker.service docker.socket containerd.service

install_guest_file_atomic() {
  local source="$1" target="$2" mode="$3"
  local temporary="${target}.new"
  _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo mkdir -p "$(dirname "$target")"
  COLIMA_BOUNDED_STDIN_FILE="$source" _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo install -m "$mode" /dev/stdin "$temporary"
  _colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo mv "$temporary" "$target"
  local expected_hash actual_hash
  expected_hash="$(shasum -a 256 "$source" | awk '{print $1}')"
  actual_hash="$(_colima_runtime_bounded 30 "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo sha256sum "$target")"
  [ "${actual_hash%% *}" = "$expected_hash" ] || { echo "installed artifact identity mismatch" >&2; return 1; }
}

install_guest_file_atomic "$ROOT/scripts/lib/colima_runtime_readiness.sh" \
  "$GUEST_LIBEXEC/yggdrasil-colima-runtime-readiness" 0755
install_guest_file_atomic "$ROOT/scripts/lib/colima_data_mount_provision.sh" \
  "$GUEST_LIBEXEC/yggdrasil-colima-data-mount" 0755
install_guest_file_atomic "$HERE/systemd/yggdrasil-colima-persistent-substrate.service" \
  "$GUEST_SYSTEMD/yggdrasil-colima-persistent-substrate.service" 0644
install_guest_file_atomic "$HERE/systemd/colima-data-mount.service" \
  "$GUEST_SYSTEMD/colima-data-mount.service" 0644
install_guest_file_atomic "$HERE/systemd/containerd.service.d/20-yggdrasil-persistent-substrate.conf" \
  "$GUEST_SYSTEMD/containerd.service.d/20-yggdrasil-persistent-substrate.conf" 0644
install_guest_file_atomic "$HERE/systemd/docker.service.d/20-yggdrasil-containerd-readiness.conf" \
  "$GUEST_SYSTEMD/docker.service.d/20-yggdrasil-containerd-readiness.conf" 0644
install_guest_file_atomic "$RUNTIME_ENV_FILE" "$GUEST_CONFIG/colima-runtime.env" 0644

_colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl daemon-reload
_colima_runtime_bounded "${COLIMA_INSTALL_SSH_TIMEOUT_SECONDS:-30}" "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl enable yggdrasil-colima-persistent-substrate.service
_colima_runtime_bounded 30 "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemd-analyze verify colima-data-mount.service yggdrasil-colima-persistent-substrate.service
if [ "${COLIMA_RUNTIME_ACTIVATE:-0}" = 1 ]; then
  _colima_runtime_bounded 30 "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl unmask docker.service docker.socket containerd.service
  if ! _colima_runtime_bounded 30 "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemd-analyze verify docker.service containerd.service; then
    _colima_runtime_bounded 30 "$COLIMA_BIN" ssh --profile "$PROFILE" -- sudo systemctl mask docker.service docker.socket containerd.service
    exit 1
  fi
  echo "Complete installed manifest verified; startup gates activated; services remain stopped"
else
  echo "Complete installed manifest verified; services remain persistently masked and stopped"
fi
