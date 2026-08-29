#!/usr/bin/env bash
# Shell helpers for the BuilderOps PostgreSQL app-password source boundary.

builderops_preflight_app_password_secret() {
  local secret_root source_secret metadata
  secret_root="${BUILDEROPS_SECRET_ROOT:?BuilderOps host secret root is required}"
  source_secret="${secret_root%/}/database-app-password"
  if [[ ! -f "$source_secret" || -L "$source_secret" ]]; then
    echo "BuilderOps app-role source secret must be a regular file" >&2
    return 78
  fi
  metadata="$(stat -c '%u:%a' "$source_secret")"
  case "$metadata" in
    0:400|0:600) ;;
    *)
      echo "BuilderOps app-role source secret must be root-owned mode 0400 or 0600" >&2
      return 78
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  builderops_preflight_app_password_secret
fi
