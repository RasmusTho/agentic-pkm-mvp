#!/usr/bin/env bash
set -euo pipefail

[ "$(id -u)" -eq 0 ] || {
  echo "native scalar rollback requires the root-owned launcher" >&2
  exit 78
}

launcher_metadata="$(stat -f '%u:%Lp' "$0" 2>/dev/null || stat -c '%u:%a' "$0" 2>/dev/null || true)"
[ "${launcher_metadata}" = "0:755" ] || {
  echo "native scalar rollback launcher must be root-owned mode 0755" >&2
  exit 78
}

selected_root="${SCALAR_ROLLBACK_VAULT_ROOT:?validated selected root is required}"
legacy_path="${DESIGN_HANDOFF_APP_LOCAL_SETTINGS:?scalar legacy projection is required}"
[ -d "${selected_root}" ] && [ -f "${legacy_path}" ] || exit 78

# Native old-image startup remains unsupported until it can be forced through
# the same authenticated mutation-filtering boundary as the Compose path.
# A filesystem sandbox alone cannot prevent a loopback/bypass API listener.
echo "native scalar rollback authenticated mutation filter unavailable; refusing startup" >&2
exit 78
