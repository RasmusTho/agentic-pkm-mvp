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

builderops_project_listing_state() {
  local projects="${1:?Compose project listing required}"
  printf '%s' "${projects}" | python3 -c '
import json
import sys

try:
    projects = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(2)
if not isinstance(projects, list) or any(
    not isinstance(project, dict) or not isinstance(project.get("Name"), str)
    for project in projects
):
    raise SystemExit(2)
print("present" if any(project["Name"] == "builderops-control-plane" for project in projects) else "absent")
'
}

builderops_assert_failure_domain() {
  local builder_context="${BUILDEROPS_DOCKER_CONTEXT:?BuilderOps Docker context is required}"
  local product_context="${PRODUCT_DOCKER_CONTEXT:?Product Docker context is required}"
  local builder_id product_id builder_projects product_projects builder_project_state product_project_state

  unset BUILDEROPS_FAILURE_DOMAIN_REASON
  [ "${builder_context}" != "${product_context}" ] || {
    echo "BuilderOps and Product Docker contexts must differ" >&2
    return 70
  }
  builder_id="$(builderops_engine_id "${builder_context}")" || {
    echo "BuilderOps Docker engine info is invalid or unavailable" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="builderops_engine_info_unavailable"
    return 75
  }
  export BUILDEROPS_OBSERVED_BUILDER_ENGINE_ID="${builder_id}"
  product_id="$(builderops_engine_id "${product_context}")" || {
    echo "Product Docker engine info is invalid or unavailable" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="product_engine_info_unavailable"
    return 75
  }
  export BUILDEROPS_OBSERVED_PRODUCT_ENGINE_ID="${product_id}"
  [ -n "${builder_id}" ] && [ -n "${product_id}" ] && [ "${builder_id}" != "${product_id}" ] || {
    echo "BuilderOps and Product must use distinct container engines" >&2
    return 71
  }

  builder_projects="$(docker --context "${builder_context}" compose ls --format json)" || {
    echo "BuilderOps Docker Compose project listing is invalid or unavailable" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="builderops_project_listing_unavailable"
    return 75
  }
  product_projects="$(docker --context "${product_context}" compose ls --format json)" || {
    echo "Product Docker Compose project listing is invalid or unavailable" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="product_project_listing_unavailable"
    return 75
  }
  builder_project_state="$(builderops_project_listing_state "${builder_projects}")" || {
    echo "BuilderOps Docker Compose project listing is invalid or unavailable" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="invalid_docker_project_listing"
    return 75
  }
  product_project_state="$(builderops_project_listing_state "${product_projects}")" || {
    echo "Product Docker Compose project listing is invalid or unavailable" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="invalid_docker_project_listing"
    return 75
  }
  if printf '%s' "${builder_projects}" | grep -Eq '"Name"[[:space:]]*:[[:space:]]*"pkm-'; then
    echo "Product project detected on BuilderOps engine" >&2
    return 72
  fi
  if [ "${builder_project_state}" = present ] && [ "${product_project_state}" = present ]; then
    echo "duplicate BuilderOps project detected across Docker engines" >&2
    return 74
  fi
  if [ "${product_project_state}" = present ]; then
    echo "BuilderOps project detected on Product engine" >&2
    return 73
  fi
}

builderops_assert_single_writer_after_activation() {
  local builder_context="${BUILDEROPS_DOCKER_CONTEXT:?BuilderOps Docker context is required}"
  local builder_projects builder_project_state

  # Re-read both engine identities and project listings after the service
  # mutation. The deployment interlock prevents concurrent governed deploys;
  # this second read also fails closed if an out-of-band writer appeared while
  # the target was being activated.
  builderops_assert_failure_domain || return $?
  builder_projects="$(docker --context "${builder_context}" compose ls --format json)" || {
    echo "BuilderOps Docker Compose project listing is invalid or unavailable after activation" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="builderops_project_listing_unavailable_after_activation"
    return 75
  }
  builder_project_state="$(builderops_project_listing_state "${builder_projects}")" || {
    echo "BuilderOps Docker Compose project listing is invalid or unavailable after activation" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="invalid_docker_project_listing_after_activation"
    return 75
  }
  [ "${builder_project_state}" = present ] || {
    echo "BuilderOps project is absent after activation" >&2
    export BUILDEROPS_FAILURE_DOMAIN_REASON="builderops_project_missing_after_activation"
    return 75
  }
}
