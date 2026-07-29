#!/usr/bin/env bash
set -euo pipefail

[ "$(id -u)" -eq 0 ] || {
  echo "native scalar rollback requires the root-owned launcher" >&2
  exit 78
}

selected_root="${SCALAR_ROLLBACK_VAULT_ROOT:?validated selected root is required}"
legacy_path="${DESIGN_HANDOFF_APP_LOCAL_SETTINGS:?scalar legacy projection is required}"
[ -d "${selected_root}" ] && [ -f "${legacy_path}" ] || exit 78

if [ -x /usr/bin/sandbox-exec ]; then
  profile="(version 1) (deny default) (allow process*) (allow file-read* (subpath \"${selected_root}\") (literal \"${legacy_path}\"))"
  exec /usr/bin/sandbox-exec -p "${profile}" "$@"
fi

if command -v bwrap >/dev/null 2>&1; then
  exec bwrap --unshare-all --die-with-parent --ro-bind "${selected_root}" /app/selected-vault \
    --ro-bind "${legacy_path}" /app/scalar-rollback/app-local.md --proc /proc --dev /dev "$@"
fi

echo "native scalar rollback sandbox unavailable; refusing startup" >&2
exit 78
