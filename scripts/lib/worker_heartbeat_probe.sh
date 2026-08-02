#!/usr/bin/env bash
# Container-boundary worker heartbeat probe (#4361).
#
# In every channel (dev/test/prod), `/app/tmp` (or `/app/tmp-test` for the
# test channel) is the `runtime-tmp` Docker-managed named volume declared
# once in docker-compose.yaml -- it is never a host bind mount, even under
# the app-bind code overlay (docker-compose.app-bind.yml only binds `./` at
# `/app`; the more specific `runtime-tmp` mount at `/app/tmp` still shadows
# it for that nested path). Reading a host-side `tmp/worker_heartbeat.json`
# path can therefore never observe a heartbeat written inside the worker
# container -- this is what made a fully healthy pinned-image prod stack
# fail `make prod-start-full` with "worker heartbeat file missing" (#4361).
#
# Probe through the container boundary instead, mirroring the existing
# `wait_for_watcher_heartbeat` / `watcher_heartbeat_ready` pattern in
# scripts/start_full_system.sh, which already does this correctly for the
# watcher heartbeat.

# Resolve the channel-correct container path for the worker heartbeat file.
# Mirrors the `_container_tmp_dir` selection in scripts/start_full_system.sh.
resolve_container_worker_heartbeat_path() {
  local compose_project="${1:-${COMPOSE_PROJECT_NAME:-}}"
  case "$compose_project" in
    pkm-test) printf '%s' "/app/tmp-test/worker_heartbeat.json" ;;
    *)        printf '%s' "/app/tmp/worker_heartbeat.json" ;;
  esac
}

# Returns 0 when the worker container reports a non-empty heartbeat file at
# the given container path, 1 otherwise. The caller injects a
# `run_docker_compose` function (a thin `docker compose [...]` wrapper) so
# this stays testable without a real docker daemon.
worker_heartbeat_ready() {
  local container_path="$1"
  run_docker_compose exec -T worker sh -c "test -s ${container_path}" >/dev/null 2>&1
}

# Prints the last line of the worker heartbeat file through the container
# boundary. Best-effort: callers should not fail startup on this alone.
tail_worker_heartbeat() {
  local container_path="$1"
  run_docker_compose exec -T worker sh -c "tail -n 1 ${container_path}"
}
