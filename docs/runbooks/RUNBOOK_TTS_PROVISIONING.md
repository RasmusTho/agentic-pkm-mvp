State: Operator runbook for provisioning Companion UI local TTS on a runtime host.
Doc role: Operations runbook
Authority: Step-by-step provisioning procedure; the runtime contract is companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md.
Owner: runtime integration
Temporal class: operational

# Runbook — Provision Companion TTS (external-SSD, containerized runtime)

Mechanism issue: #2082. Health-surface contract: `companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md`
(delivered by #1699). This runbook covers the **machine-local** half — model files on the SSD and
enablement — which cannot live in the repo.

## How it fits together
- The runtime image bakes the engines: `piper` (CLI on PATH) + `kokoro_onnx` (Python).
- Compose bind-mounts the SSD root `${TTS_HOST_ROOT}` → `/data/tts` in the `api` container; the app
  reads the fixed container paths `TTS_MODEL_DIR=/data/tts/models`, `TTS_CACHE_DIR=/data/tts/cache`,
  `TTS_LOG_DIR=/data/tts/logs` (tracked in `docker-compose.yaml`).
- Machine-specific values live in `.env.prod.local` (`TTS_HOST_ROOT`, `TTS_ENABLED`); never committed.
- TTS stays **off** until a host sets `TTS_ENABLED=true`, so a merged mechanism cannot 503 prod.

## Provisioning steps (on the runtime host, e.g. Demerzel)
1. Create the SSD layout:
   `mkdir -p "$TTS_HOST_ROOT"/{models/piper,models/kokoro,cache/audio,cache/plans,logs}`
2. Fetch models: `scripts/fetch_tts_models.sh "$TTS_HOST_ROOT/models"`
   (confirm upstream URLs/checksums on first run).
3. Set `~/workspace-prod/.env.prod.local`: `TTS_HOST_ROOT=...`, `TTS_ENABLED=true`.
4. Deploy (prod overlay pattern — cherry-pick the merged commit, do NOT `git pull`; see
   project demerzel prod ops):
   `docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod up -d --build api`
   — validate the engine builds on the host arch (linux/arm64 on Apple silicon); if a pinned wheel
   lacks an arm64 build, swap to a system `piper` binary and set `TTS_PIPER_COMMAND`.
5. Verify: `curl -s http://127.0.0.1:18000/api/companion/tts/status | jq '.environment, .providers'`
   → `TTS_ENABLED=true`, providers `available=true`. Post the receipt to #1699 (this is AC4) and close it.

## Dev / test
Leave `TTS_ENABLED` unset (defaults false). To exercise locally, point `TTS_HOST_ROOT` at a scratch
dir, run the fetch script into `"$TTS_HOST_ROOT/models"`, and set `TTS_ENABLED=true`.
