#!/usr/bin/env bash
set -euo pipefail

builderops_compose() {
  local root="${1:?repo root required}"
  shift
  local pin_file="${BUILDEROPS_PIN_FILE:-${root}/config/deploy/builderops.env}"
  local context="${BUILDEROPS_DOCKER_CONTEXT:?BuilderOps Docker context is required}"
  docker --context "${context}" compose \
    --env-file "${pin_file}" \
    -f "${root}/docker-compose.builderops.yml" \
    -p builderops-control-plane \
    "$@"
}

builderops_engine_id() {
  local context="${1:?Docker context required}"
  docker --context "${context}" info --format '{{.ID}}'
}

builderops_validate_recovery_target() {
  local root="${1:?repo root required}"
  local secret_root="${BUILDEROPS_SECRET_ROOT:?BuilderOps host secret root is required}"
  local archive_target="${BUILDEROPS_WALG_S3_PREFIX:?BuilderOps WAL archive target is required}"
  python3 "$root/app/builderops/control_plane/recovery.py" \
    "$secret_root/recovery-target.json" --expected-url "$archive_target" >/dev/null
}

builderops_assert_failure_domain() {
  local builder_context="${BUILDEROPS_DOCKER_CONTEXT:?BuilderOps Docker context is required}"
  local product_context="${PRODUCT_DOCKER_CONTEXT:?Product Docker context is required}"
  local builder_id product_id builder_projects product_projects

  [ "${builder_context}" != "${product_context}" ] || {
    echo "BuilderOps and Product Docker contexts must differ" >&2
    return 70
  }
  builder_id="$(builderops_engine_id "${builder_context}")"
  product_id="$(builderops_engine_id "${product_context}")"
  [ -n "${builder_id}" ] && [ -n "${product_id}" ] && [ "${builder_id}" != "${product_id}" ] || {
    echo "BuilderOps and Product must use distinct container engines" >&2
    return 71
  }

  builder_projects="$(docker --context "${builder_context}" compose ls --format json)"
  product_projects="$(docker --context "${product_context}" compose ls --format json)"
  if printf '%s' "${builder_projects}" | grep -Eq '"Name"[[:space:]]*:[[:space:]]*"pkm-'; then
    echo "Product project detected on BuilderOps engine" >&2
    return 72
  fi
  if printf '%s' "${product_projects}" | grep -Eq '"Name"[[:space:]]*:[[:space:]]*"builderops-control-plane"'; then
    echo "BuilderOps project detected on Product engine" >&2
    return 73
  fi
}
