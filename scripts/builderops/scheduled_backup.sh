#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
OPERATOR_ENV_FILE="${BUILDEROPS_OPERATOR_ENV_FILE:-/Users/Shared/builderops/operator.env}"
if [[ ! -r "$OPERATOR_ENV_FILE" ]]; then
  echo "BuilderOps operator environment file is unavailable" >&2
  exit 78
fi

# Only non-secret selectors and secret-file roots may cross from the operator
# file. Credential values themselves remain Docker secrets under that root.
while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  case "$key" in
    BUILDEROPS_DOCKER_CONTEXT|PRODUCT_DOCKER_CONTEXT|BUILDEROPS_SECRET_ROOT|BUILDEROPS_WALG_S3_PREFIX)
      export "$key=$value"
      ;;
    *)
      echo "unsupported BuilderOps operator environment key: $key" >&2
      exit 78
      ;;
  esac
done <"$OPERATOR_ENV_FILE"

# shellcheck source=../lib/builderops_compose.sh
source "$ROOT/scripts/lib/builderops_compose.sh"
builderops_assert_failure_domain
builderops_validate_recovery_target "$ROOT"
builderops_compose "$ROOT" --profile ops run --rm --no-deps backup
