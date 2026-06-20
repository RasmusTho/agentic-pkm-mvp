# Agent Playbook — Mac mini (macOS)

You are a coding agent (Claude Code / Codex) running on the Mac mini. Set this
machine up as the **always-on core**: Ollama (embeddings + small chat) + the
gaming-aware `llm-gateway`, and point the Yggdrasil runtime at the gateway.
Work top to bottom; stop and report if a step fails.

## Preconditions (the operator did these by hand)
- Tailscale installed and signed in (same tailnet as the gaming PC + Air).
- This repo is cloned locally.
- Homebrew + `python3` available (`brew --version`, `python3 --version`).

## Steps
1. **Config.** Ensure `ops/host-setup/config.env` exists (copy from
   `config.example.env`). Set `GAMING_PC_HOST` to the gaming PC's Tailscale name
   (`tailscale status` lists peers). Keep `EMBED_MODEL` as-is — it is pinned here.

2. **Run the installer:** `bash ops/host-setup/mac-mini/install.sh`
   It installs Ollama, pulls `nomic-embed-text` + `llama3.1:8b`, creates the
   gateway venv, and loads the `com.yggdrasil.llm-gateway` launchd service.

3. **Verify the gateway:**
   `curl -sS http://127.0.0.1:11500/healthz` → JSON. Check `gaming` is the
   expected host and `gaming_available` reflects reality (start a game on the PC
   and confirm it flips to `false`).

4. **Wire Yggdrasil.** In the runtime's env (`.env` / `.env.<channel>.local`), set:
   ```
   LLM_PROVIDER=ollama
   OLLAMA_URL=http://127.0.0.1:11500     # the gateway, not Ollama directly
   OLLAMA_EMBED_MODEL=nomic-embed-text:latest
   LLM_MODEL=llama3.1:8b
   ```
   Do **not** also set `OLLAMA_URL` to the raw `:11434` anywhere — everything must
   go through the gateway so the embedding-identity pin and routing hold.

5. **Start / restart the stack** the usual way (`make start` or
   `scripts/start_full_system.sh`) and confirm `/api/health` reports the llm
   router healthy and embeddings compatible (no rebuild required).

6. **End-to-end check:** with a game NOT running, send a chat through Yggdrasil
   (e.g. `/api/ask` or a panel action) and confirm via the gateway log
   (`/tmp/yggdrasil-llm-gateway.log`) that it routed to the gaming host; start a
   game and confirm the next chat stays local.

7. **Report** to the operator: gateway `/healthz`, the env you set, and the
   routed-vs-local check result.

## Notes
- Embeddings must never route to the gaming PC (identity drift would force a full
  index rebuild — see `docs/LLM_ROUTING.md`). The gateway enforces this; don't
  bypass it.
- Keep the mini headless-friendly: enable Screen Sharing + Remote Login (SSH) in
  System Settings so the operator can reach it from the MacBook Air over Tailscale.
