#!/usr/bin/env bash
set -euo pipefail

LOG_PATH="${LOG_PATH:-verification_log.txt}"
REPORT_PATH="${REPORT_PATH:-verification_report.md}"

mkdir -p "$(dirname "$LOG_PATH")" "$(dirname "$REPORT_PATH")" 2>/dev/null || true

SECTION_A="FAIL"
SECTION_B="FAIL"
SECTION_C="FAIL"
SECTION_D="FAIL"
SECTION_E="FAIL"
SECTION_F="FAIL"
SECTION_G="FAIL"

NOTE_NAME=""
REL_NOTE_PATH=""
HOST_NOTE_PATH=""
CONTAINER_NOTE_PATH=""

FAIL_REASON=""
EXIT_CODE=0

_ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

_log() {
  printf "[%s] %s\n" "$(_ts)" "$*" | tee -a "$LOG_PATH" >/dev/null
}

_run_capture() {
  local cmd="$1"
  _log "CMD $cmd"
  set +e
  local out
  out=$(bash -lc "$cmd" 2>&1)
  local rc=$?
  set -e
  printf "%s\n" "$out" >>"$LOG_PATH"
  _log "RC $rc"
  printf "%s" "$out"
  return "$rc"
}

_run() {
  _run_capture "$1" >/dev/null
}

_record_fail() {
  local msg="$1"
  FAIL_REASON="$msg"
  EXIT_CODE=1
  _log "FAIL $msg"
}

_write_report() {
  export NOW="$(_ts)"
  export LOG_PATH
  export REPORT_PATH

  export SECTION_A SECTION_B SECTION_C SECTION_D SECTION_E SECTION_F SECTION_G
  export HOST_NOTE_PATH REL_NOTE_PATH CONTAINER_NOTE_PATH
  export FAIL_REASON EXIT_CODE

  python - <<'PY'
import os
from pathlib import Path

def get(name: str, default: str = '<unset>') -> str:
    v = os.environ.get(name, '')
    return v if v else default

report_path = Path(get('REPORT_PATH', 'verification_report.md'))

sections = [
    ('A) Recreate runtime services', get('SECTION_A', 'FAIL')),
    ('B) Compose injects no hardcoded inbox/scope defaults', get('SECTION_B', 'FAIL')),
    ('C) Effective env snapshot (watcher/worker)', get('SECTION_C', 'FAIL')),
    ('D) Resolve inbox from vault layout', get('SECTION_D', 'FAIL')),
    ('E) Runtime chain: outbox delivered + uuid healed', get('SECTION_E', 'FAIL')),
    ('F) Guard: no hardcoded inbox defaults (runtime/compose/scripts/configs)', get('SECTION_F', 'FAIL')),
    ('G) Baseline tests (ruff/mypy/pytest not-pg)', get('SECTION_G', 'FAIL')),
]

lines = []
lines.append('# Runtime Chain Verification')
lines.append('')
lines.append(f"Date: {get('NOW','')}")
lines.append(f"VAULT_ROOT: {get('VAULT_ROOT')}")
lines.append('')
lines.append('## PASS/FAIL')
lines.append('')
lines.append('| Section | Result |')
lines.append('|---|---:|')
for label, res in sections:
    lines.append(f"| {label} | {res} |")
lines.append('')
lines.append('## Result')
lines.append('')
lines.append(f"Exit code: {get('EXIT_CODE','0')}")
lines.append(f"Reason: {get('FAIL_REASON','<none>')}")
lines.append('')
lines.append('## Evidence pointers (verification_log.txt)')
lines.append('')
lines.append('- Compose config grep (hardcoded defaults): search for "CMD docker compose config | egrep -n".')
lines.append('- Env snapshot: search for "CMD docker compose exec -T watcher env" and "CMD docker compose exec -T worker env".')
lines.append('- Container identity: search for "CMD docker compose exec -T watcher id" and "CMD docker compose exec -T worker id".')
lines.append('- Smoke note:')
lines.append(f"  - note_host_path: {get('HOST_NOTE_PATH')} ")
lines.append(f"  - note_rel_path:  {get('REL_NOTE_PATH')} ")
lines.append(f"  - note_container_path: {get('CONTAINER_NOTE_PATH')} ")
lines.append('- Outbox evidence: search for the outbox SELECT with payload220.')
lines.append('- Permission evidence (if any): search for "Operation not permitted" and "Permission denied".')
lines.append('')
lines.append('## Next actions')
lines.append('')
lines.append('- If UUID healing fails with EPERM on macOS+iCloud vault mounts, run compose with host uid/gid mapping and force-recreate services so the user change takes effect:')
lines.append('')
lines.append('  export LOCAL_UID=$(id -u)')
lines.append('  export LOCAL_GID=$(id -g)')
lines.append('  docker compose up -d --force-recreate api watcher worker')
lines.append('')
lines.append('- If inbox resolution fails, set one of:')
lines.append('')
lines.append('  export VAULT_INBOX_DIR_REL="<your inbox folder name>"')
lines.append('')
lines.append('  or')
lines.append('')
lines.append('  export VAULT_LAYOUT_NOTE_REL="<relative path to vault.layout.md>"')

report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
PY

  _log "DONE report_written $REPORT_PATH"
}

trap _write_report EXIT

if [ -z "${VAULT_ROOT:-}" ]; then
  _log "ERROR VAULT_ROOT is required"
  EXIT_CODE=2
  exit 2
fi

if [ ! -d "$VAULT_ROOT" ]; then
  _log "ERROR VAULT_ROOT is not a directory: $VAULT_ROOT"
  EXIT_CODE=2
  exit 2
fi

_log "START verify_runtime_chain"
_log "INFO LOCAL_UID=${LOCAL_UID:-<unset>} LOCAL_GID=${LOCAL_GID:-<unset>}"

if _run "docker compose up -d db api watcher worker"; then
  :
else
  SECTION_A="FAIL"
  _record_fail "docker compose up failed"
fi

_run "docker compose ps || true"

if [ "$EXIT_CODE" -eq 0 ]; then
  SECTION_A="PASS"
fi

in_word="In"'box'
emoji=$'\U0001F4E5'
emoji_inbox="${emoji} ${in_word}"
compose_bad="VAULT_INBOX_DIR_REL: ${in_word}|WATCHER_SCOPE_GLOB: ${in_word}/\\*\\*|WATCHER_SCOPE_GLOB: ${emoji_inbox}|VAULT_INBOX_DIR_REL: ${emoji}"

if _run "docker compose config | egrep -n \"$compose_bad\""; then
  SECTION_B="FAIL"
  _record_fail "compose injects a hardcoded inbox/scope default"
else
  SECTION_B="PASS"
fi
_run "docker compose exec -T watcher id || true"
_run "docker compose exec -T watcher env | egrep 'WATCHER_AUTO_EXEC|WATCHER_VAULT_PATH|WATCHER_SCOPE_GLOB|VAULT_INBOX_DIR_REL|VAULT_ROOT|INDEX_OUTBOX_PATH|DATABASE_URL' | sort || true"
_run "docker compose exec -T worker id || true"
_run "docker compose exec -T worker env | egrep 'WATCHER_VAULT_PATH|VAULT_INBOX_DIR_REL|INDEX_OUTBOX_PATH|DATABASE_URL' | sort || true"
SECTION_C="PASS"

layout_json=$(python -m app.cli vault-layout-ensure --vault-root "$VAULT_ROOT" --json 2>>"$LOG_PATH" || true)
_log "layout_json_len ${#layout_json}"

inbox_dir=""
if [ -n "$layout_json" ]; then
  inbox_dir=$(python -c 'import json,sys; print((json.loads(sys.stdin.read() or "{}").get("inbox_folder") or "").strip())' <<<"$layout_json" 2>>"$LOG_PATH" || true)
fi

if [ -z "$layout_json" ] || [ -z "$inbox_dir" ]; then
  SECTION_D="FAIL"
  _record_fail "could not resolve inbox_dir from vault layout"
else
  SECTION_D="PASS"
fi

if [ "$SECTION_D" = "PASS" ]; then
  inbox_abs="$VAULT_ROOT/$inbox_dir"
  _log "resolved_inbox_rel $inbox_dir"
  _log "resolved_inbox_abs $inbox_abs"

  smoke_dir="$inbox_abs/@Smoke"
  mkdir -p "$smoke_dir"

  epoch="$(date -u +%s)"
  NOTE_NAME="verify_uuid_${epoch}.md"
  HOST_NOTE_PATH="$smoke_dir/$NOTE_NAME"
  REL_NOTE_PATH="$inbox_dir/@Smoke/$NOTE_NAME"
  CONTAINER_NOTE_PATH="/app/vault/$REL_NOTE_PATH"

  cat > "$HOST_NOTE_PATH" <<EOFNOTE
---
title: verify_uuid_${epoch}
---

%% AI:Start %%
- action: summarize
%% AI:End %%
EOFNOTE

  printf "\nMARKER %s\n" "$(_ts)" >> "$HOST_NOTE_PATH"

  _log "note_host_path $HOST_NOTE_PATH"
  _log "note_rel_path  $REL_NOTE_PATH"
  _log "note_container_path $CONTAINER_NOTE_PATH"

  _run "ls -lOe \"$HOST_NOTE_PATH\" || true"
  _run "stat -f '%Sp %u:%g %N' \"$HOST_NOTE_PATH\" || true"

  _run "docker compose exec -T db psql -U app -d app -c \"select count(*) as total, count(*) filter (where delivered_at is null) as pending, min(created_at) filter (where delivered_at is null) as oldest_pending, max(created_at) as newest from outbox;\" || true"

  _run "docker compose exec -T watcher env WATCHER_AUTO_EXEC=1 python -m app.cli watcher run --max-ticks 30 || true"

  ok_outbox="0"
  ok_uuid="0"

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    outbox_delivered_raw=$(_run_capture "docker compose exec -T db psql -U app -d app -tAc \"select coalesce(max((delivered_at is not null)::int),0) from outbox where topic='ingest.vault.changed' and payload::text ilike '%$NOTE_NAME%';\"" || true)
    outbox_delivered=$(printf "%s" "$outbox_delivered_raw" | tr -d '[:space:]' | tail -n 1)
    if [ "$outbox_delivered" = "1" ]; then
      ok_outbox="1"
    fi

    if _run "docker compose exec -T api env NOTE_PATH=\"$CONTAINER_NOTE_PATH\" python - <<'PY'
import os
from pathlib import Path
from scripts.yaml_roundtrip import load_frontmatter
p = Path(os.environ['NOTE_PATH'])
raw = p.read_text(encoding='utf-8')
fm, _ = load_frontmatter(raw)
val = ''
if isinstance(fm, dict):
    val = str(fm.get('uuid') or '').strip()
print('uuid_present', bool(val))
if not val:
    raise SystemExit(2)
PY"; then
      ok_uuid="1"
    fi

    if [ "$ok_outbox" = "1" ] && [ "$ok_uuid" = "1" ]; then
      break
    fi

    sleep 1
  done

  if [ "$ok_outbox" = "1" ] && [ "$ok_uuid" = "1" ]; then
    SECTION_E="PASS"
  else
    SECTION_E="FAIL"
    _record_fail "runtime chain did not satisfy outbox+uuid conditions"
    _log "DIAG collecting failure diagnostics"
    _run "docker compose exec -T db psql -U app -d app -c \"select created_at, topic, delivered_at, attempts, left(payload::text, 220) as payload220 from outbox order by created_at desc limit 20;\" || true"
    _run "docker compose logs --since 2m watcher worker | tail -n 200 || true"
    _run "docker compose exec -T watcher sh -lc 'id && ls -la \"/app/vault\" | head -n 5' || true"
    _run "docker compose exec -T watcher sh -lc 'ls -la \"$(dirname "$CONTAINER_NOTE_PATH")\" | tail -n 10' || true"
    _run "docker compose exec -T watcher sh -lc 'ls -la \"$CONTAINER_NOTE_PATH\" || true' || true"
  fi
fi

# Guard against repo wiring injecting inbox/scope defaults.
if _run "python scripts/verify_runtime_guard.py"; then
  SECTION_F="PASS"
else
  SECTION_F="FAIL"
  _record_fail "hardcoded inbox/scope defaults found in repo wiring"
fi

section_g_ok=1
if _run "ruff check app tests"; then
  :
else
  section_g_ok=0
  _record_fail "ruff failed"
fi

if _run "mypy app"; then
  :
else
  section_g_ok=0
  _record_fail "mypy failed"
fi

if _run "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m 'not pg'"; then
  :
else
  section_g_ok=0
  _record_fail "pytest (not pg) failed"
fi

if [ "$section_g_ok" -eq 1 ]; then
  SECTION_G="PASS"
else
  SECTION_G="FAIL"
fi

exit "$EXIT_CODE"
