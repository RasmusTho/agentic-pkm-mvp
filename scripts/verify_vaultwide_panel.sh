#!/usr/bin/env bash
set -euo pipefail

# Verifies:
# - watcher default scope is vault-wide (notes outside inbox are detected)
# - PanelAgent engages on %%ai and can proactively create a panel for eligible notes
# - no side-effecting action events are emitted without explicit checkboxes

NOW_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
EPOCH="$(date -u +%s)"

LOG_PATH="${LOG_PATH:-tmp/verify_vaultwide_panel.${EPOCH}.log}"
REPORT_PATH="${REPORT_PATH:-tmp/verify_vaultwide_panel.${EPOCH}.report}"
TEST_DIR_REL="${TEST_DIR_REL:-__agentic_verify}"

mkdir -p "$(dirname "$LOG_PATH")" "$(dirname "$REPORT_PATH")" 2>/dev/null || true

PASS=0
FAIL=0

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

_log() {
  printf "[%s] %s\n" "$(_ts)" "$*" | tee -a "$LOG_PATH" >/dev/null
}

_fail() {
  FAIL=$((FAIL+1))
  _log "FAIL: $*"
}

_pass() {
  PASS=$((PASS+1))
  _log "PASS: $*"
}

_run() {
  local cmd="$1"
  _log "CMD: $cmd"
  set +e
  local out
  out="$(bash -lc "$cmd" 2>&1)"
  local rc=$?
  set -e
  printf "%s\n" "$out" >>"$LOG_PATH"
  _log "RC=$rc"
  return "$rc"
}

_write_report() {
  {
    echo "=== verify_vaultwide_panel ==="
    echo "NOW=$NOW_UTC"
    echo "PASS=$PASS"
    echo "FAIL=$FAIL"
    echo "VAULT_ROOT=${VAULT_ROOT:-<unset>}"
    echo "TEST_DIR_REL=$TEST_DIR_REL"
    echo "LOG_PATH=$LOG_PATH"
    echo "REPORT_PATH=$REPORT_PATH"
    echo "NOTE_ROOT_NO_AI_REL=${NOTE_ROOT_NO_AI_REL:-<unset>}"
    echo "NOTE_NESTED_WITH_AI_REL=${NOTE_NESTED_WITH_AI_REL:-<unset>}"
  } >"$REPORT_PATH"
  _log "DONE report_written $REPORT_PATH"
}

trap _write_report EXIT

if [[ -z "${VAULT_ROOT:-}" ]]; then
  set +e
  VAULT_ROOT="$(docker inspect "$(docker compose ps -q watcher 2>/dev/null)" \
    --format '{{range .Mounts}}{{if eq .Destination "/app/vault"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)"
  set -e
fi
if [[ -z "${VAULT_ROOT:-}" ]]; then
  _log "ERROR: VAULT_ROOT is required (set VAULT_ROOT or ensure watcher is running with /app/vault mounted)"
  exit 2
fi
if [[ ! -d "$VAULT_ROOT" ]]; then
  _log "ERROR: VAULT_ROOT is not a directory: $VAULT_ROOT"
  exit 2
fi

_log "START verify_vaultwide_panel"
_log "INFO vault_root=$VAULT_ROOT"
_log "INFO test_dir_rel=$TEST_DIR_REL"

NOTE_ROOT_NO_AI_NAME="vaultwide_root_no_ai_${EPOCH}.md"
NOTE_NESTED_WITH_AI_NAME="vaultwide_nested_with_ai_${EPOCH}.md"

NOTE_ROOT_NO_AI_REL="${NOTE_ROOT_NO_AI_NAME}"
NOTE_NESTED_WITH_AI_REL="${TEST_DIR_REL}/Deep/Nested/${NOTE_NESTED_WITH_AI_NAME}"

NOTE_ROOT_NO_AI_HOST="${VAULT_ROOT}/${NOTE_ROOT_NO_AI_REL}"
NOTE_NESTED_WITH_AI_HOST="${VAULT_ROOT}/${NOTE_NESTED_WITH_AI_REL}"

mkdir -p "$(dirname "$NOTE_ROOT_NO_AI_HOST")" "$(dirname "$NOTE_NESTED_WITH_AI_HOST")"

cat >"$NOTE_ROOT_NO_AI_HOST" <<EOF
---
title: vaultwide_root_no_ai_${EPOCH}
---
This is an eligible note at vault root without an AI fence.
marker:${EPOCH}
EOF

cat >"$NOTE_NESTED_WITH_AI_HOST" <<EOF
---
title: vaultwide_nested_with_ai_${EPOCH}
---

%% AI:Start %%
Instruction: help me
%% AI:End %%

marker:${EPOCH}
EOF

_pass "created test notes outside inbox (if any)"
_log "NOTE_ROOT_NO_AI_HOST=$NOTE_ROOT_NO_AI_HOST"
_log "NOTE_NESTED_WITH_AI_HOST=$NOTE_NESTED_WITH_AI_HOST"

if _run "docker compose ps"; then
  _pass "docker compose ps"
else
  _fail "docker compose ps"
fi

if _run "docker compose exec -T watcher sh -lc 'test -f \"/app/vault/${NOTE_ROOT_NO_AI_REL}\" && test -f \"/app/vault/${NOTE_NESTED_WITH_AI_REL}\"'"; then
  _pass "root + nested notes visible in watcher container under /app/vault"
else
  _fail "root + nested notes NOT visible in watcher container under /app/vault"
fi

compose_scope="$(docker compose config 2>/dev/null | rg -n 'WATCHER_SCOPE_GLOB' || true)"
if [[ -n "$compose_scope" ]]; then
  _log "compose_scope_glob_matches:"
  printf "%s\n" "$compose_scope" >>"$LOG_PATH"
  _fail "compose injects WATCHER_SCOPE_GLOB (must not)"
else
  _pass "compose does not inject WATCHER_SCOPE_GLOB"
fi

watcher_env="$(docker compose exec -T watcher env 2>/dev/null || true)"
printf "%s\n" "$watcher_env" | egrep 'WATCHER_VAULT_PATH|WATCHER_SCOPE_GLOB|WATCHER_AUTO_EXEC|PANEL_PROACTIVE_ASSIST|STORE_BACKEND|DATABASE_URL|INDEX_OUTBOX_PATH' | sort >>"$LOG_PATH" 2>&1 || true
if printf "%s\n" "$watcher_env" | rg -q '^WATCHER_SCOPE_GLOB='; then
  _fail "watcher env includes WATCHER_SCOPE_GLOB (should be unset unless operator sets it)"
else
  _pass "watcher env does not include WATCHER_SCOPE_GLOB (default computed at runtime)"
fi

stop_out="$(docker compose exec -T watcher sh -lc 'test -f /app/tmp/WATCHER_STOP && echo WATCHER_STOP_PRESENT || true' 2>/dev/null || true)"
printf "%s\n" "$stop_out" >>"$LOG_PATH" 2>&1 || true
if printf "%s\n" "$stop_out" | rg -q "WATCHER_STOP_PRESENT"; then
  _log "NOTE: WATCHER_STOP present at /app/tmp/WATCHER_STOP (this verifier uses WATCHER_STOP_FILE override for the run)"
  _pass "WATCHER_STOP present in container (ignored for verifier run via WATCHER_STOP_FILE override)"
else
  _pass "WATCHER_STOP not present in container"
fi

if _run "docker compose exec -T watcher env WATCHER_AUTO_EXEC=1 WATCHER_SUMMARY_INTERVAL=0 WATCHER_DEBOUNCE_MS=0 WATCHER_RATE_LIMIT_PER_MIN=999 WATCHER_TICK_SLEEP_SECONDS=0.05 WATCHER_STATE_DIR=/tmp/verify_watcher_state_${EPOCH} WATCHER_HEARTBEAT_PATH=/tmp/verify_watcher_heartbeat_${EPOCH}.json WATCHER_STOP_FILE=/tmp/verify_watcher_stop_${EPOCH} WATCHER_TICK_LOG_PATH=/tmp/verify_watcher_tick_${EPOCH}.jsonl python -m app.cli watcher run --max-ticks 3"; then
  _pass "watcher run (isolated state, max-ticks 3)"
else
  _fail "watcher run failed"
fi

# The watcher command above already fails the verifier if it exits non-zero.
# We intentionally avoid asserting on specific log lines here because stdout
# can vary with logging configuration across environments.
_pass "watcher run completed"

_psql_scalar() {
  local sql="$1"
  docker compose exec -T db psql -U app -d app -tAc "$sql" 2>/dev/null | tr -d '[:space:]' | tail -n 1
}

wait_ok_ingest() {
  local note_name="$1"
  local note_esc="$note_name"
  local ok="0"
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    val="$(_psql_scalar "select case when exists(select 1 from outbox where topic='ingest.vault.changed' and position('${note_esc}' in payload::text) > 0) then 1 else 0 end;")"
    _log "ingest_exists_try[$i] note=$note_name val=$val"
    if [[ "$val" == "1" ]]; then
      ok="1"
      break
    fi
    sleep 1
  done
  [[ "$ok" == "1" ]]
}

if wait_ok_ingest "$NOTE_ROOT_NO_AI_NAME"; then
  _pass "ingest.vault.changed exists for root no-ai note"
else
  _fail "ingest.vault.changed missing for root no-ai note"
fi

if wait_ok_ingest "$NOTE_NESTED_WITH_AI_NAME"; then
  _pass "ingest.vault.changed exists for nested with-ai note"
else
  _fail "ingest.vault.changed missing for nested with-ai note"
fi

check_outbox_topic_exists() {
  local topic="$1"
  local note_name="$2"
  local note_esc="$note_name"
  val="$(_psql_scalar "select case when exists(select 1 from outbox where topic='${topic}' and position('${note_esc}' in payload::text) > 0) then 1 else 0 end;")"
  _log "topic_exists topic=$topic note=$note_name val=$val"
  [[ "$val" == "1" ]]
}

if check_outbox_topic_exists "panel.intent.created" "$NOTE_ROOT_NO_AI_NAME"; then
  _pass "panel.intent.created exists for root no-ai note"
else
  _fail "panel.intent.created missing for root no-ai note"
fi

if check_outbox_topic_exists "panel.intent.created" "$NOTE_NESTED_WITH_AI_NAME"; then
  _pass "panel.intent.created exists for nested with-ai note"
else
  _fail "panel.intent.created missing for nested with-ai note"
fi

count_side_effects() {
  local note_name="$1"
  local note_esc="$note_name"
  _psql_scalar "select count(*) from outbox where position('${note_esc}' in payload::text) > 0 and (topic like 'promote.%' or topic like 'execute.%' or topic like 'action.%' or topic like 'actions.%');"
}

side_root="$(count_side_effects "$NOTE_ROOT_NO_AI_NAME")"
_log "side_effect_count root_no_ai=$NOTE_ROOT_NO_AI_NAME count=$side_root"
if [[ "$side_root" == "0" ]]; then
  _pass "no side-effect topics for root no-ai note (no checkboxes)"
else
  _fail "unexpected side-effect topics for root no-ai note (count=$side_root)"
fi

side_nested="$(count_side_effects "$NOTE_NESTED_WITH_AI_NAME")"
_log "side_effect_count nested_with_ai=$NOTE_NESTED_WITH_AI_NAME count=$side_nested"
if [[ "$side_nested" == "0" ]]; then
  _pass "no side-effect topics for nested with-ai note (no checkboxes)"
else
  _fail "unexpected side-effect topics for nested with-ai note (count=$side_nested)"
fi

_log "=== host file checks ==="
NOTE_ROOT_NO_AI_HOST="$NOTE_ROOT_NO_AI_HOST" NOTE_NESTED_WITH_AI_HOST="$NOTE_NESTED_WITH_AI_HOST" python - <<'PY' >>"$LOG_PATH" 2>&1 || true
import os
import re
from pathlib import Path

paths = [
    Path(os.environ["NOTE_ROOT_NO_AI_HOST"]),
    Path(os.environ["NOTE_NESTED_WITH_AI_HOST"]),
]
for p in paths:
    txt = p.read_text(encoding="utf-8")
    print("FILE", p)
    print("HAS_PANEL_FENCE=", "%% AI" in txt)
    print("HAS_ASSIST=", "<!--ai:assist:start-->" in txt)
    print("HAS_SUGGESTED_ACTIONS=", "<!--ai:suggested_actions:start-->" in txt)
    q_count = len(re.findall(r"^- ❓\s", txt, flags=re.M))
    print("QUESTION_LINES=", q_count)
    print("--- head ---")
    print("\n".join(txt.splitlines()[:30]))
    print()
PY

if NOTE_ROOT_NO_AI_HOST="$NOTE_ROOT_NO_AI_HOST" python - <<'PY' >/dev/null 2>&1
import os
import re
from pathlib import Path
txt = Path(os.environ["NOTE_ROOT_NO_AI_HOST"]).read_text(encoding="utf-8")
assert "<!--ai:assist:start-->" in txt
assert "<!--ai:suggested_actions:start-->" in txt
assert len(re.findall(r"^- ❓\s", txt, flags=re.M)) == 1
PY
then
  _pass "root no-ai note got panel proposals + exactly one question (host)"
else
  _fail "root no-ai note missing panel proposals/question (host)"
fi

if NOTE_NESTED_WITH_AI_HOST="$NOTE_NESTED_WITH_AI_HOST" python - <<'PY' >/dev/null 2>&1
import os
import re
from pathlib import Path
txt = Path(os.environ["NOTE_NESTED_WITH_AI_HOST"]).read_text(encoding="utf-8")
assert "<!--ai:assist:start-->" in txt
assert "<!--ai:suggested_actions:start-->" in txt
assert len(re.findall(r"^- ❓\s", txt, flags=re.M)) == 1
PY
then
  _pass "nested with-ai note got proposals + exactly one question (host)"
else
  _fail "nested with-ai note missing proposals/question (host)"
fi

_log "=== outbox recent rows ==="
_run "docker compose exec -T db psql -U app -d app -c \"select created_at, topic, delivered_at, attempts, left(payload::text, 220) as payload220 from outbox order by created_at desc limit 30;\" || true"

if [[ "$FAIL" -eq 0 ]]; then
  _log "SUMMARY PASS=$PASS FAIL=$FAIL"
  exit 0
fi

_log "SUMMARY PASS=$PASS FAIL=$FAIL"
exit 1
