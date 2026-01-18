#!/usr/bin/env bash
set -euo pipefail

rm -f tmp/flightrecorder-*.log tmp/flightrecorder-test-once.log

set +e
START_FLIGHT_RECORDER=1 START_WATCHERS=0 START_WORKER=0 VAULT_ROOT= scripts/start_full_system.sh >/dev/null 2>&1
STATUS=$?
set -e
if [ $STATUS -eq 0 ]; then
  echo "expected start_full_system.sh to fail without VAULT_ROOT" >&2
  exit 1
fi

LOG_FILE=$(ls -1 tmp/flightrecorder-*.log 2>/dev/null | head -n 1 || true)
if [ -z "$LOG_FILE" ]; then
  echo "flight recorder log not created" >&2
  exit 1
fi
if [ ! -s "$LOG_FILE" ]; then
  echo "flight recorder log is empty" >&2
  exit 1
fi

scripts/flight_recorder.sh --once --log-path tmp/flightrecorder-test-once.log >/dev/null 2>&1
if ! grep -q "Flight recorder snapshot" tmp/flightrecorder-test-once.log; then
  echo "flight recorder once log missing snapshot marker" >&2
  exit 1
fi

echo "flight recorder invariant checks passed"
