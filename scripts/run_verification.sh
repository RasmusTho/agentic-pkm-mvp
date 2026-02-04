#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: >> verification_log.txt

export LOG_PATH="${LOG_PATH:-verification_log.txt}"
export REPORT_PATH="${REPORT_PATH:-verification_report.md}"

bash scripts/verify_runtime_chain.sh
