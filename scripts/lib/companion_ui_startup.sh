#!/usr/bin/env bash
# Shared helpers for the canonical Companion UI operator startup/doctor commands.
#
# This library is sourced by the per-channel wrapper scripts
# (scripts/dev/start_niflheim_ui.sh, scripts/test/start_bifrost_ui.sh,
# scripts/prod/start_midgard_ui.sh and their *_doctor.sh siblings).
#
# It is channel-agnostic: a wrapper sets the CUI_* configuration variables
# below, then calls cui_run_start or cui_run_doctor. Channel identity, vault
# guard, ports, compose project, and serve module are all supplied by the
# wrapper so this library never special-cases a named vault internally.
#
# Required CUI_* configuration (set by the wrapper before calling an entry point):
#   CUI_CHANNEL                 dev|test|prod
#   CUI_EXPECTED_VAULT_PATTERN  egrep pattern matched against the VAULT_ROOT basename
#   CUI_EXPECTED_VAULT_LABEL    human label for the expected vault (e.g. "Niflheim/Nifelheim")
#   CUI_API_PORT                runtime API host port (e.g. 18001)
#   CUI_UI_PORT                 Companion UI host port (e.g. 8111)
#   CUI_COMPOSE_FILES           COMPOSE_FILE value for start_full_system.sh
#   CUI_COMPOSE_PROJECT         COMPOSE_PROJECT_NAME for the channel (e.g. pkm-dev)
#   CUI_SERVE_MODULE            companion_ui.workspace.serve_dev_page | serve_production_page
#
# Optional behaviour flags (default safe):
#   CUI_BIND_LAN=1              bind the UI to 0.0.0.0 for LAN/Tailscale UAT (default: 127.0.0.1)
#   CUI_TARGET_NOTE=<rel-path>  optional note path to verify via /api/companion/workspace
#   CUI_WATCHER_AUTO_EXEC       passthrough to start_full_system.sh (prod wrapper sets 0 by default)
#   CUI_DB_LABEL                expected channel DB name to report (e.g. app_dev/app_test/app)

# ── repo + python resolution ────────────────────────────────────────────────

cui_repo_root() {
  local lib_dir
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
  (cd "${lib_dir}/../.." && pwd)
}

cui_python_bin() {
  if [ -n "${CUI_PYTHON:-}" ] && [ -x "${CUI_PYTHON}" ]; then
    printf '%s\n' "${CUI_PYTHON}"
    return 0
  fi
  local root
  root="$(cui_repo_root)"
  if [ -x "${root}/.venv/bin/python" ]; then
    printf '%s\n' "${root}/.venv/bin/python"
    return 0
  fi
  if command -v python3.12 >/dev/null 2>&1; then command -v python3.12; return 0; fi
  if command -v python3 >/dev/null 2>&1; then command -v python3; return 0; fi
  if command -v python >/dev/null 2>&1; then command -v python; return 0; fi
  return 1
}

# ── logging ──────────────────────────────────────────────────────────────────

cui_log()  { printf '[companion-ui:%s] %s\n' "${CUI_CHANNEL:-?}" "$*"; }
cui_warn() { printf '[companion-ui:%s] WARN: %s\n' "${CUI_CHANNEL:-?}" "$*" >&2; }
cui_err()  { printf '[companion-ui:%s] ERROR: %s\n' "${CUI_CHANNEL:-?}" "$*" >&2; }
cui_die()  { cui_err "$*"; exit 1; }

cui_lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# ── configuration guard ───────────────────────────────────────────────────────

cui_require_config() {
  local missing=""
  local key
  for key in CUI_CHANNEL CUI_EXPECTED_VAULT_PATTERN CUI_EXPECTED_VAULT_LABEL \
             CUI_API_PORT CUI_UI_PORT CUI_COMPOSE_FILES CUI_COMPOSE_PROJECT CUI_SERVE_MODULE; do
    if [ -z "${!key:-}" ]; then
      missing="${missing} ${key}"
    fi
  done
  if [ -n "${missing}" ]; then
    cui_die "wrapper did not set required config:${missing}"
  fi
}

# ── channel env loading + vault guard ─────────────────────────────────────────

# Loads .env.<channel>.local into the environment. Fails fast if the file is
# absent. Uses the repo's space-safe Python-based env parser.
cui_load_channel_env() {
  local root env_file
  root="$(cui_repo_root)"
  env_file=".env.${CUI_CHANNEL}.local"
  if [ ! -f "${root}/${env_file}" ]; then
    cui_die "missing ${env_file} in repo root (${root}). Create it with channel config (PKM_ENVIRONMENT=${CUI_CHANNEL}, VAULT_ROOT=...). See .env.example."
  fi
  # shellcheck source=/dev/null
  source "${root}/scripts/lib/load_env_defaults.sh"
  ( cd "${root}" && load_env_defaults_file "${env_file}" ) >/dev/null 2>&1 || true
  # load_env_defaults_file runs in a subshell for the parser; re-load into this
  # shell by re-sourcing in the repo root so exported keys persist.
  cd "${root}" || cui_die "cannot cd to repo root ${root}"
  load_env_defaults_file "${env_file}"
}

# Verifies VAULT_ROOT basename matches the expected channel vault. Read-only.
cui_guard_vault_name() {
  local base base_lc
  if [ -z "${VAULT_ROOT:-}" ]; then
    cui_die "VAULT_ROOT is not set after loading .env.${CUI_CHANNEL}.local; cannot confirm channel vault."
  fi
  base="$(basename "${VAULT_ROOT}")"
  base_lc="$(cui_lower "${base}")"
  if printf '%s' "${base_lc}" | grep -Eq "${CUI_EXPECTED_VAULT_PATTERN}"; then
    cui_log "vault guard OK: resolved vault '${base}' matches expected ${CUI_EXPECTED_VAULT_LABEL}"
    return 0
  fi
  cui_die "vault guard FAILED: resolved vault '${base}' (VAULT_ROOT=${VAULT_ROOT}) does not look like ${CUI_EXPECTED_VAULT_LABEL}. Refusing to start ${CUI_CHANNEL} channel against the wrong vault."
}

# ── docker / colima ───────────────────────────────────────────────────────────

# Returns 0 if the Docker daemon is reachable.
cui_docker_ok() {
  command -v docker >/dev/null 2>&1 || return 1
  docker info >/dev/null 2>&1 || return 1
  return 0
}

# ── runtime orchestration ─────────────────────────────────────────────────────

# Single-shot probe of the runtime API /healthz. Read-only. Returns 0 if healthy.
cui_api_healthy_now() {
  curl -fsS --max-time 3 "http://127.0.0.1:${CUI_API_PORT}/healthz" >/dev/null 2>&1
}

cui_start_runtime() {
  local root _rc
  root="$(cui_repo_root)"
  # Restarting the UI should not recreate an already-healthy stack. When the
  # runtime API is up, skip the full start_full_system.sh recreate (and its
  # watcher/worker health race). Set CUI_FORCE_RECREATE=1 to force a rebuild,
  # e.g. after changing runtime code or compose config.
  if [ "${CUI_FORCE_RECREATE:-0}" != "1" ] && cui_api_healthy_now; then
    cui_log "runtime API already healthy on port ${CUI_API_PORT} — skipping full stack recreate (set CUI_FORCE_RECREATE=1 to force)"
    return 0
  fi
  cui_log "starting runtime API via scripts/start_full_system.sh (project=${CUI_COMPOSE_PROJECT})"
  (
    cd "${root}" || exit 1
    COMPOSE_FILE="${CUI_COMPOSE_FILES}" \
    COMPOSE_PROJECT_NAME="${CUI_COMPOSE_PROJECT}" \
    PKM_ENVIRONMENT="${CUI_CHANNEL}" \
    START_MODE=runtime \
    ${CUI_WATCHER_AUTO_EXEC:+WATCHER_AUTO_EXEC="${CUI_WATCHER_AUTO_EXEC}"} \
    scripts/start_full_system.sh
  ) || {
    _rc=$?
    # start_full_system.sh can exit non-zero even when the stack came up
    # (e.g. its final Python health-check step exits 1 while all containers
    # are actually healthy). Treat this as a warning and let cui_wait_healthz
    # be the authoritative health gate instead of aborting here.
    cui_warn "start_full_system.sh exited non-zero (rc=${_rc}) — checking API health to confirm stack state"
  }
}

# Polls the runtime API /healthz. Read-only. Returns 0 on healthy.
cui_wait_healthz() {
  local url attempts i
  url="http://127.0.0.1:${CUI_API_PORT}/healthz"
  attempts="${CUI_HEALTH_ATTEMPTS:-30}"
  i=1
  while [ "${i}" -le "${attempts}" ]; do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      cui_log "runtime API healthy at ${url}"
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  return 1
}

# Locates the API container for the compose project and lists /app/vault.
# Read-only. Prints a human summary; returns non-zero if mount is missing.
cui_verify_vault_mount() {
  local cid count
  cid="$(docker ps --filter "label=com.docker.compose.project=${CUI_COMPOSE_PROJECT}" \
          --filter "name=api" --format '{{.ID}}' 2>/dev/null | head -n1)"
  if [ -z "${cid}" ]; then
    cui_warn "no running api container found for project ${CUI_COMPOSE_PROJECT}; cannot confirm /app/vault mount"
    return 1
  fi
  if ! docker exec "${cid}" sh -c 'test -d /app/vault' >/dev/null 2>&1; then
    cui_warn "api container ${cid} has no /app/vault directory; vault mount is missing/stale"
    return 1
  fi
  count="$(docker exec "${cid}" sh -c 'ls -1 /app/vault 2>/dev/null | wc -l' 2>/dev/null | tr -d '[:space:]')"
  cui_log "vault mount OK: container ${cid} sees /app/vault (host VAULT_ROOT=${VAULT_ROOT:-unknown}, top-level entries=${count:-0})"
  return 0
}

# ── UI port handling ───────────────────────────────────────────────────────────

# Prints PIDs (one per line) listening on the given TCP port.
cui_port_listener_pids() {
  local port="$1"
  # `|| true` so an empty result (lsof exit 1) does not abort callers under
  # `set -o pipefail`.
  { lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null || true; } | sort -u
}

# Returns 0 if the given PID is a Companion UI dev/production server.
cui_pid_is_companion() {
  local pid="$1" cmd
  cmd="$(ps -o command= -p "${pid}" 2>/dev/null || true)"
  printf '%s' "${cmd}" | grep -Eq 'companion_ui\.workspace\.serve_(dev|production)_page'
}

# Frees the UI port ONLY if the listener is a Companion UI server. Never touches
# unrelated processes (SSH, Colima, Docker, etc.) — fails with instructions
# instead.
cui_free_ui_port() {
  local pids pid
  pids="$(cui_port_listener_pids "${CUI_UI_PORT}")"
  if [ -z "${pids}" ]; then
    return 0
  fi
  for pid in ${pids}; do
    if cui_pid_is_companion "${pid}"; then
      cui_log "replacing stale Companion UI listener on ${CUI_UI_PORT} (pid ${pid})"
      kill "${pid}" 2>/dev/null || true
    else
      cui_die "UI port ${CUI_UI_PORT} is held by a non-Companion process (pid ${pid}: $(ps -o command= -p "${pid}" 2>/dev/null | head -c 120)). Refusing to kill an unrelated process. Free the port manually or choose another UI port."
    fi
  done
  # brief settle so the port is released before bind
  sleep 1
}

# ── network helpers (best effort, read-only) ──────────────────────────────────

cui_lan_ip() {
  local ip
  ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
  if [ -z "${ip}" ]; then ip="$(ipconfig getifaddr en1 2>/dev/null || true)"; fi
  printf '%s' "${ip}"
}

cui_tailscale_ip() {
  command -v tailscale >/dev/null 2>&1 || return 0
  { tailscale ip -4 2>/dev/null || true; } | head -n1
}

# ── Companion UI server ────────────────────────────────────────────────────────

cui_start_ui() {
  local root py app_dir host log_path
  root="$(cui_repo_root)"
  app_dir="${root}/companion-ui/companion-app"
  log_path="${root}/tmp/companion-ui-${CUI_CHANNEL}.log"
  mkdir -p "${root}/tmp"
  py="$(cui_python_bin)" || cui_die "no usable python interpreter found for Companion UI server"

  if [ "${CUI_BIND_LAN:-0}" = "1" ]; then
    host="0.0.0.0"
    cui_log "binding UI to 0.0.0.0 (LAN/Tailscale UAT)"
  else
    host="127.0.0.1"
    cui_log "binding UI to 127.0.0.1 (loopback default; set CUI_BIND_LAN=1 for LAN/Tailscale UAT)"
  fi

  cui_free_ui_port

  cui_log "starting Companion UI (${CUI_SERVE_MODULE}) on ${host}:${CUI_UI_PORT}"
  (
    cd "${app_dir}" || exit 1
    COMPANION_API_BASE_URL="http://127.0.0.1:${CUI_API_PORT}" \
    HOST="${host}" \
    PORT="${CUI_UI_PORT}" \
    nohup "${py}" -m "${CUI_SERVE_MODULE}" >"${log_path}" 2>&1 &
    printf '%s' "$!" >"${root}/tmp/companion-ui-${CUI_CHANNEL}.pid"
  )
  CUI_UI_LOG_PATH="${log_path}"
  CUI_UI_HOST="${host}"

  # wait for the UI to accept connections
  local i=1
  while [ "${i}" -le 15 ]; do
    if curl -fsS --max-time 3 "http://127.0.0.1:${CUI_UI_PORT}/" >/dev/null 2>&1; then
      cui_log "Companion UI responding on 127.0.0.1:${CUI_UI_PORT}"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  cui_warn "Companion UI did not respond on 127.0.0.1:${CUI_UI_PORT} within timeout; check ${log_path}"
  return 1
}

# ── target note verification (optional, read-only) ────────────────────────────

cui_verify_target_note() {
  local note url
  note="${CUI_TARGET_NOTE:-}"
  [ -n "${note}" ] || return 0
  url="http://127.0.0.1:${CUI_API_PORT}/api/companion/workspace?note_path=$(printf '%s' "${note}" | sed 's/ /%20/g')"
  if curl -fsS --max-time 5 "${url}" >/dev/null 2>&1; then
    cui_log "target note OK: '${note}' is reachable via /api/companion/workspace"
    return 0
  fi
  cui_warn "target note '${note}' could not be loaded via /api/companion/workspace (note may not exist in the ${CUI_CHANNEL} vault)"
  return 1
}

# ── final operator summary ─────────────────────────────────────────────────────

cui_print_summary() {
  local lan ts query
  lan="$(cui_lan_ip)"
  ts="$(cui_tailscale_ip)"
  query=""
  if [ -n "${CUI_TARGET_NOTE:-}" ]; then
    query="?note_path=$(printf '%s' "${CUI_TARGET_NOTE}" | sed 's/ /%20/g')"
  fi
  echo ""
  echo "================ Companion UI (${CUI_CHANNEL}) ready ================"
  echo "  channel     : PKM_ENVIRONMENT=${CUI_CHANNEL}  project=${CUI_COMPOSE_PROJECT}  db=${CUI_DB_LABEL:-derived}"
  echo "  runtime API : http://127.0.0.1:${CUI_API_PORT}/healthz"
  echo "  UI (local)  : http://127.0.0.1:${CUI_UI_PORT}/${query}"
  if [ "${CUI_BIND_LAN:-0}" = "1" ]; then
    [ -n "${lan}" ] && echo "  UI (LAN)    : http://${lan}:${CUI_UI_PORT}/${query}"
    [ -n "${ts}" ]  && echo "  UI (Tailscale): http://${ts}:${CUI_UI_PORT}/${query}"
  else
    echo "  UI bind     : 127.0.0.1 only (set CUI_BIND_LAN=1 for LAN/Tailscale UAT)"
  fi
  echo "  API log     : ${CUI_API_LOG_PATH:-see scripts/start_full_system.sh output / tmp/}"
  echo "  UI log      : ${CUI_UI_LOG_PATH:-tmp/companion-ui-${CUI_CHANNEL}.log}"
  echo "===================================================================="
}

# ── entry points ───────────────────────────────────────────────────────────────

cui_run_start() {
  cui_require_config
  cui_log "canonical startup begin"
  cui_load_channel_env
  cui_guard_vault_name
  if ! cui_docker_ok; then
    cui_die "Docker/Colima is not available. Start Docker Desktop or 'colima start', then retry."
  fi
  cui_start_runtime
  if ! cui_wait_healthz; then
    cui_die "runtime API never became healthy at http://127.0.0.1:${CUI_API_PORT}/healthz"
  fi
  cui_verify_vault_mount || cui_warn "continuing despite vault-mount check warning"
  cui_start_ui || cui_warn "Companion UI start reported a warning"
  cui_verify_target_note || true
  cui_print_summary
  cui_log "canonical startup complete"
}

# Read-only diagnostic. Never starts services or mutates vault/runtime state.
cui_run_doctor() {
  cui_require_config
  local rc=0
  echo "============ Companion UI doctor (${CUI_CHANNEL}) ============"
  echo "  channel: PKM_ENVIRONMENT=${CUI_CHANNEL}  project=${CUI_COMPOSE_PROJECT}  db=${CUI_DB_LABEL:-derived}"

  # 1. Docker / Colima
  if cui_docker_ok; then
    echo "  [ok]   docker/colima reachable"
  else
    echo "  [FAIL] docker/colima unavailable (start Docker Desktop or 'colima start')"
    rc=1
  fi

  # 2. Channel env file + vault resolution (read-only)
  local root env_file
  root="$(cui_repo_root)"
  env_file=".env.${CUI_CHANNEL}.local"
  if [ -f "${root}/${env_file}" ]; then
    echo "  [ok]   ${env_file} present"
    # shellcheck source=/dev/null
    source "${root}/scripts/lib/load_env_defaults.sh"
    ( cd "${root}" && load_env_defaults_file "${env_file}" ) >/dev/null 2>&1 || true
    cd "${root}" 2>/dev/null && load_env_defaults_file "${env_file}" >/dev/null 2>&1 || true
    if [ -n "${VAULT_ROOT:-}" ]; then
      local base base_lc
      base="$(basename "${VAULT_ROOT}")"
      base_lc="$(cui_lower "${base}")"
      if printf '%s' "${base_lc}" | grep -Eq "${CUI_EXPECTED_VAULT_PATTERN}"; then
        echo "  [ok]   vault resolves to ${CUI_EXPECTED_VAULT_LABEL} ('${base}')"
      else
        echo "  [FAIL] vault '${base}' does not match expected ${CUI_EXPECTED_VAULT_LABEL}"
        rc=1
      fi
    else
      echo "  [FAIL] VAULT_ROOT not set by ${env_file}"
      rc=1
    fi
  else
    echo "  [FAIL] ${env_file} missing (see .env.example)"
    rc=1
  fi

  # 3. API health (read-only)
  if curl -fsS --max-time 3 "http://127.0.0.1:${CUI_API_PORT}/healthz" >/dev/null 2>&1; then
    echo "  [ok]   runtime API healthy on :${CUI_API_PORT}"
  else
    echo "  [warn] runtime API not healthy on :${CUI_API_PORT} (not started yet?)"
  fi

  # 4. Vault mount (read-only; only if container running)
  if cui_docker_ok; then
    if cui_verify_vault_mount >/dev/null 2>&1; then
      echo "  [ok]   api container sees /app/vault"
    else
      echo "  [warn] api container vault mount missing/stale or container not running"
    fi
  fi

  # 5. UI port occupancy (read-only)
  local pids pid
  pids="$(cui_port_listener_pids "${CUI_UI_PORT}")"
  if [ -z "${pids}" ]; then
    echo "  [ok]   UI port ${CUI_UI_PORT} is free"
  else
    for pid in ${pids}; do
      if cui_pid_is_companion "${pid}"; then
        echo "  [ok]   UI port ${CUI_UI_PORT} held by Companion UI (pid ${pid}, replaceable)"
      else
        echo "  [warn] UI port ${CUI_UI_PORT} held by NON-Companion pid ${pid}: $(ps -o command= -p "${pid}" 2>/dev/null | head -c 80)"
      fi
    done
  fi

  # 6. UI process reachable (read-only)
  if curl -fsS --max-time 3 "http://127.0.0.1:${CUI_UI_PORT}/" >/dev/null 2>&1; then
    echo "  [ok]   Companion UI responding on :${CUI_UI_PORT}"
  else
    echo "  [info] Companion UI not responding on :${CUI_UI_PORT} (not started yet?)"
  fi

  # 7. Target note (optional, read-only)
  if [ -n "${CUI_TARGET_NOTE:-}" ]; then
    if curl -fsS --max-time 5 "http://127.0.0.1:${CUI_API_PORT}/api/companion/workspace?note_path=$(printf '%s' "${CUI_TARGET_NOTE}" | sed 's/ /%20/g')" >/dev/null 2>&1; then
      echo "  [ok]   target note '${CUI_TARGET_NOTE}' reachable"
    else
      echo "  [warn] target note '${CUI_TARGET_NOTE}' not reachable"
    fi
  fi

  # 8. Tailscale IP
  local ts
  ts="$(cui_tailscale_ip)"
  if [ -n "${ts}" ]; then
    echo "  [ok]   tailscale IP detected: ${ts}"
  else
    echo "  [info] no tailscale IP detected (LAN-only or tailscale down)"
  fi

  # 9. Channel-specific extra checks (e.g. prod automation-flag safety).
  if declare -f cui_extra_doctor >/dev/null 2>&1; then
    cui_extra_doctor || rc=1
  fi

  echo "============================================================="
  return "${rc}"
}
