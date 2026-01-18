#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
log_dir="$ROOT/tmp"
mkdir -p "$log_dir"

INTERVAL=5
DURATION=0
ONCE=0
LOG_PATH=""

print_usage() {
  cat <<USAGE
Usage: $(basename "$0") [--once] [--interval <seconds>] [--duration <seconds>] [--log-path <path>]

Options:
  --once               Capture a single snapshot and exit.
  --interval <seconds> Sleep interval between snapshots (default: ${INTERVAL}s).
  --duration <seconds> Total run duration; zero means run until killed (default: ${DURATION}s).
  --log-path <path>    Use a specific log file path (default: tmp/flightrecorder-<timestamp>.log).
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --once)
      ONCE=1
      shift
      ;;
    --interval)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --interval" >&2
        print_usage
        exit 1
      fi
      INTERVAL="$2"
      shift 2
      ;;
    --duration)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --duration" >&2
        print_usage
        exit 1
      fi
      DURATION="$2"
      shift 2
      ;;
    --log-path)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --log-path" >&2
        print_usage
        exit 1
      fi
      LOG_PATH="$2"
      shift 2
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      print_usage
      exit 1
      ;;
  esac
done

if [[ -z "$LOG_PATH" ]]; then
  LOG_PATH="$log_dir/flightrecorder-$(date -u +"%Y%m%d-%H%M%S").log"
fi

touch "$LOG_PATH"

append_line() {
  printf "%s\n" "$1" >>"$LOG_PATH"
}

run_with_timeout() {
  if command -v timeout >/dev/null 2>&1; then
    timeout 10 "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout 10 "$@"
  else
    "$@"
  fi
}

safe_cmd() {
  local label="$1"
  shift
  append_line "\n=== $label ==="
  if ! "$@" >>"$LOG_PATH" 2>&1; then
    append_line "FAILED: $* (exit $? )"
  fi
}

flight_active=1
cleanup() {
  if [[ $flight_active -eq 1 ]]; then
    append_line "Flight recorder exiting at $(date -u +"%Y-%m-%dT%H:%M:%SZ") ($1)"
    flight_active=0
  fi
}
trap 'cleanup SIGINT; exit 0' INT
trap 'cleanup SIGTERM; exit 0' TERM

record_snapshot() {
  append_line "\n===== Flight recorder snapshot: $(date -u +"%Y-%m-%dT%H:%M:%SZ") ====="
  safe_cmd "date" date
  safe_cmd "uptime" uptime
  if command -v vm_stat >/dev/null 2>&1; then
    safe_cmd "vm_stat" vm_stat
  else
    append_line "vm_stat: not available"
  fi
  if [[ "$(uname)" == "Darwin" ]]; then
    safe_cmd "top (Darwin)" top -l 1 -n 20
  else
    safe_cmd "top (batch)" sh -c 'top -b -n 1 | head -n 20'
  fi
  safe_cmd "processes" sh -c 'ps -A -o pid,ppid,%cpu,%mem,command | sort -nrk 3 | head -n 20'
  safe_cmd "df" df -h
  safe_cmd "docker info" run_with_timeout docker info
  safe_cmd "docker compose ps" run_with_timeout docker compose ps
  safe_cmd "docker compose logs" run_with_timeout docker compose logs --tail=50 api watcher worker
}

printf "Flight recorder log: %s\n" "$LOG_PATH"

if [[ $ONCE -eq 1 ]]; then
  record_snapshot
  cleanup "once"
  exit 0
fi

start_ts=$(date +"%s")
while true; do
  record_snapshot
  if [[ $DURATION -gt 0 ]]; then
    now_ts=$(date +"%s")
    elapsed=$((now_ts - start_ts))
    if [[ $elapsed -ge $DURATION ]]; then
      cleanup "duration"
      exit 0
    fi
  fi
  sleep "$INTERVAL"
done
