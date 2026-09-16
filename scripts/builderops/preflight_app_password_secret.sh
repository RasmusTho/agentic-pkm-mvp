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

builderops_preflight_runtime_secrets() {
  local secret_root secret_name source_secret metadata
  secret_root="${BUILDEROPS_SECRET_ROOT:?BuilderOps host secret root is required}"
  for secret_name in \
    database-owner-url \
    database-app-url \
    api-credentials.json \
    executor-credentials.json \
    probe-token
  do
    source_secret="${secret_root%/}/${secret_name}"
    if [[ ! -f "$source_secret" || -L "$source_secret" ]]; then
      echo "BuilderOps runtime secret ${secret_name} must be a regular file" >&2
      return 78
    fi
    metadata="$(stat -c '%u:%g:%a' "$source_secret")"
    if [[ "$metadata" != "0:101:640" ]]; then
      echo "BuilderOps runtime secret ${secret_name} must be owned by 0:101 with mode 0640" >&2
      return 78
    fi
  done
}

builderops_preflight_control_plane_secrets() {
  builderops_preflight_app_password_secret || return
  builderops_preflight_runtime_secrets
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  builderops_preflight_control_plane_secrets
fi
