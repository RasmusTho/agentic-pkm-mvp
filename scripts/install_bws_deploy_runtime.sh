#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
runtime_root="/opt/yggdrasil/bws-deploy-runtime"
launcher_path="/usr/local/libexec/yggdrasil-bws-deploy"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root)
      [[ $# -ge 2 ]] || { echo "missing --runtime-root value" >&2; exit 64; }
      runtime_root="$2"
      shift 2
      ;;
    --install-root)
      [[ $# -ge 2 ]] || { echo "missing --install-root value" >&2; exit 64; }
      launcher_path="$2/yggdrasil-bws-deploy"
      shift 2
      ;;
    *)
      echo "usage: $0 [--runtime-root ABSOLUTE_PATH] [--install-root ABSOLUTE_DIRECTORY]" >&2
      exit 64
      ;;
  esac
done

if [[ "$runtime_root" != /* || "$runtime_root" == "/" || -L "$runtime_root" \
  || "$launcher_path" != /* || "$launcher_path" == "/" || -L "$launcher_path" ]]; then
  echo "refusing invalid BWS deploy runtime path" >&2
  exit 78
fi

bootstrap_python="$(command -v python3.12 || true)"
if [[ -z "$bootstrap_python" ]] \
  || ! "$bootstrap_python" -c 'import sys; sys.version_info >= (3, 12) or sys.exit(78)' >/dev/null 2>&1; then
  echo "BWS deploy runtime requires Python 3.12 or newer" >&2
  exit 78
fi

runtime_python="$runtime_root/bin/python3"
if [[ -x "$runtime_python" ]]; then
  "$bootstrap_python" -m venv --upgrade "$runtime_root"
else
  "$bootstrap_python" -m venv "$runtime_root"
fi
if [[ ! -x "$runtime_python" ]] \
  || ! "$runtime_python" -c 'import sys; sys.version_info >= (3, 12) or sys.exit(78)' >/dev/null 2>&1; then
  echo "BWS deploy venv must use Python 3.12 or newer" >&2
  exit 78
fi

"$runtime_python" -m pip install \
  --disable-pip-version-check \
  --requirement "$repo_root/requirements-bws-deploy.txt"
if ! PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$runtime_python" -c \
  'import bitwarden_sdk, psycopg, app.ops.postgres_deploy_linux' >/dev/null 2>&1; then
  echo "BWS deploy runtime dependency check failed" >&2
  exit 78
fi

mkdir -p "$(dirname "$launcher_path")"
launcher_tmp="$(mktemp)"
trap 'rm -f -- "$launcher_tmp"' EXIT
{
  printf '#!%s\n' "$runtime_python"
  tail -n +2 "$repo_root/scripts/postgres_deploy_service.py"
} > "$launcher_tmp"
install -m 0755 "$launcher_tmp" "$launcher_path"
