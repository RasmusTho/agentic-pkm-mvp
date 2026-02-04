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
    echo "NOTE_NO_AI_REL=${NOTE_NO_AI_REL:-<unset>}"
    echo "NOTE_WITH_AI_REL=${NOTE_WITH_AI_REL:-<unset>}"
  } >"$REPORT_PATH"
  _log "DONE report_written $REPORT_PATH"
}

trap _write_report EXIT

if [[ -z "${VAULT_ROOT:-}" ]]; then
  _log "ERROR: VAULT_ROOT is required"
  exit 2
fi
if [[ ! -d "$VAULT_ROOT" ]]; then
  _log "ERROR: VAULT_ROOT is not a directory: $VAULT_ROOT"
  exit 2
fi

_log "START verify_vaultwide_panel"
_log "INFO vault_root=$VAULT_ROOT"
_log "INFO test_dir_rel=$TEST_DIR_REL"

NOTE_NO_AI_NAME="vaultwide_no_ai_${EPOCH}.md"
NOTE_WITH_AI_NAME="vaultwide_with_ai_${EPOCH}.md"

NOTE_NO_AI_REL="${TEST_DIR_REL}/${NOTE_NO_AI_NAME}"
NOTE_WITH_AI_REL="${TEST_DIR_REL}/${NOTE_WITH_AI_NAME}"

NOTE_NO_AI_HOST="${VAULT_ROOT}/${NOTE_NO_AI_REL}"
NOTE_WITH_AI_HOST="${VAULT_ROOT}/${NOTE_WITH_AI_REL}"

mkdir -p "$(dirname "$NOTE_NO_AI_HOST")"

cat >"$NOTE_NO_AI_HOST" <<EOF
---
title: vaultwide_no_ai_${EPOCH}
---
This is an eligible note without an AI fence.
marker:${EPOCH}
EOF

cat >"$NOTE_WITH_AI_HOST" <<EOF
---
title: vaultwide_with_ai_${EPOCH}
---

%% AI:Start %%
Instruction: help me
%% AI:End %%

marker:${EPOCH}
EOF

_pass "created test notes outside inbox (if any)"
_log "NOTE_NO_AI_HOST=$NOTE_NO_AI_HOST"
_log "NOTE_WITH_AI_HOST=$NOTE_WITH_AI_HOST"

if _run "docker compose ps"; then
  _pass "docker compose ps"
else
  _fail "docker compose ps"
fi

if _run "docker compose exec -T watcher sh -lc 'test -f \"/app/vault/${NOTE_NO_AI_REL}\" && test -f \"/app/vault/${NOTE_WITH_AI_REL}\"'"; then
  _pass "notes visible in watcher container under /app/vault"
else
  _fail "notes NOT visible in watcher container under /app/vault"
fi

_run "docker compose exec -T watcher env | egrep 'WATCHER_VAULT_PATH|WATCHER_SCOPE_GLOB|WATCHER_AUTO_EXEC|PANEL_PROACTIVE_ASSIST|STORE_BACKEND|DATABASE_URL|INDEX_OUTBOX_PATH' | sort || true"

if _run "docker compose exec -T watcher env WATCHER_AUTO_EXEC=1 python -m app.cli watcher run --max-ticks 30"; then
  _pass "watcher run (max-ticks 30)"
else
  _fail "watcher run failed"
fi

wait_ok_ingest() {
  local note_name="$1"
  local ok="0"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    raw="$(docker compose exec -T db psql -U app -d app -tAc \"select coalesce(max((delivered_at is not null)::int),0) from outbox where topic='ingest.vault.changed' and payload::text ilike '%${note_name}%';\" 2>/dev/null || true)"
    val="$(printf \"%s\" \"$raw\" | tr -d '[:space:]' | tail -n 1)"
    _log \"ingest_delivered_try[$i] note=$note_name val=$val\"
    if [[ \"$val\" == \"1\" ]]; then
      ok=\"1\"
      break
    fi
    sleep 1
  done
  [[ \"$ok\" == \"1\" ]]
}

if wait_ok_ingest "$NOTE_NO_AI_NAME"; then
  _pass "ingest.vault.changed delivered for no-ai note"
else
  _fail "ingest.vault.changed NOT delivered for no-ai note"
fi

if wait_ok_ingest "$NOTE_WITH_AI_NAME"; then
  _pass "ingest.vault.changed delivered for with-ai note"
else
  _fail "ingest.vault.changed NOT delivered for with-ai note"
fi

check_outbox_topic_exists() {
  local topic="$1"
  local note_name="$2"
  raw="$(docker compose exec -T db psql -U app -d app -tAc \"select coalesce(max(1),0) from outbox where topic='${topic}' and payload::text ilike '%${note_name}%';\" 2>/dev/null || true)"
  val="$(printf \"%s\" \"$raw\" | tr -d '[:space:]' | tail -n 1)"
  _log \"topic_exists topic=$topic note=$note_name val=$val\"
  [[ \"$val\" == \"1\" ]]
}

if check_outbox_topic_exists "panel.intent.created" "$NOTE_NO_AI_NAME"; then
  _pass "panel.intent.created exists for no-ai note"
else
  _fail "panel.intent.created missing for no-ai note"
fi

if check_outbox_topic_exists "panel.intent.created" "$NOTE_WITH_AI_NAME"; then
  _pass "panel.intent.created exists for with-ai note"
else
  _fail "panel.intent.created missing for with-ai note"
fi

if check_outbox_topic_exists "promote.intent.created" "$NOTE_NO_AI_NAME"; then
  _fail "unexpected promote.intent.created for no-ai note (no checkboxes)"
else
  _pass "no promote.intent.created for no-ai note (no checkboxes)"
fi

if check_outbox_topic_exists "promote.intent.created" "$NOTE_WITH_AI_NAME"; then
  _fail "unexpected promote.intent.created for with-ai note (no checkboxes)"
else
  _pass "no promote.intent.created for with-ai note (no checkboxes)"
fi

_log "=== host file checks ==="
NOTE_NO_AI_HOST="$NOTE_NO_AI_HOST" NOTE_WITH_AI_HOST="$NOTE_WITH_AI_HOST" python - <<'PY' >>"$LOG_PATH" 2>&1 || true
import os
from pathlib import Path

paths = [
    Path(os.environ["NOTE_NO_AI_HOST"]),
    Path(os.environ["NOTE_WITH_AI_HOST"]),
]
for p in paths:
    txt = p.read_text(encoding="utf-8")
    print("FILE", p)
    print("HAS_PANEL_FENCE=", "%% AI" in txt)
    print("HAS_ASSIST=", "<!--ai:assist:start-->" in txt)
    print("HAS_SUGGESTED_ACTIONS=", "<!--ai:suggested_actions:start-->" in txt)
    print("--- head ---")
    print("\n".join(txt.splitlines()[:30]))
    print()
PY

if NOTE_NO_AI_HOST="$NOTE_NO_AI_HOST" python - <<'PY' >/dev/null 2>&1
import os
from pathlib import Path
txt = Path(os.environ["NOTE_NO_AI_HOST"]).read_text(encoding="utf-8")
assert "<!--ai:assist:start-->" in txt
assert "<!--ai:suggested_actions:start-->" in txt
PY
then
  _pass "no-ai note got panel proposals + question (host)"
else
  _fail "no-ai note missing panel proposals/question (host)"
fi

if NOTE_WITH_AI_HOST="$NOTE_WITH_AI_HOST" python - <<'PY' >/dev/null 2>&1
import os
from pathlib import Path
txt = Path(os.environ["NOTE_WITH_AI_HOST"]).read_text(encoding="utf-8")
assert "<!--ai:assist:start-->" in txt
assert "<!--ai:suggested_actions:start-->" in txt
PY
then
  _pass "with-ai note got proposals + question (host)"
else
  _fail "with-ai note missing proposals/question (host)"
fi

_log "=== outbox recent rows ==="
_run "docker compose exec -T db psql -U app -d app -c \"select created_at, topic, delivered_at, attempts, left(payload::text, 220) as payload220 from outbox order by created_at desc limit 30;\" || true"

if [[ "$FAIL" -eq 0 ]]; then
  _log "SUMMARY PASS=$PASS FAIL=$FAIL"
  exit 0
fi

_log "SUMMARY PASS=$PASS FAIL=$FAIL"
exit 1
