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

## BuilderOps Model Inquiry host entrypoints

The Model Inquiry host owns the fixed `yggdrasil-model-inquiry` launcher plus
two stable headless role commands: `fable-model-inquiry-role` and
`codex-model-inquiry-role`. They resolve declared credentials through the host
secret contract and require no interactive subscription session. Install all
three as durable, owner-only wrappers bound to the current repository checkout:

```bash
repo_root="$(git rev-parse --show-toplevel)"
python3 "$repo_root/scripts/install_model_inquiry_host.py" install \
  --repo-root "$repo_root" \
  --bin-dir "$HOME/.local/bin" \
  --python "$repo_root/.venv/bin/python3"
```

The operation is idempotent. An exact rerun reports the launcher and both role
entrypoints as `unchanged`; an unrelated existing file, stale subscription
launcher, symlinked bin directory, or unsafe permissions fails closed and must
be inspected rather than overwritten.
If an I/O failure interrupts the two-role install, an exact first wrapper may
remain while the second is absent. Do not delete it as rollback: rerun the same
command, which validates the retained wrapper and converges the missing role.
Any reported temporary-file cleanup failure remains an install failure and
requires inspection of owner-only `.<entrypoint>.*.tmp` files in the bin
directory.

Before advertising the launcher as healthy, run the sanitized, read-only check:

```bash
python3 "$repo_root/scripts/install_model_inquiry_host.py" check \
  --repo-root "$repo_root" \
  --bin-dir "$HOME/.local/bin" \
  --python "$repo_root/.venv/bin/python3"
```

The check succeeds only when all three wrappers match the selected checkout and
interpreter and the current `PATH` resolves all three names to those exact
files. Discoverability alone is not sufficient for `yggdrasil-model-inquiry`;
its exact repo-owned declared-credential lineage/content must match. It probes
no provider CLI, does not invoke a provider, and does not inspect
authentication. Provider access instead requires the declared
`anthropic.api-key` and `openai.api-key` Keychain items for the consumer
`builderops-model-inquiry`; a missing value fails a run closed as
`credential_unavailable` naming only that logical identifier.

After a reboot or checkout promotion, run the same `check` command through the
actual non-interactive transport:

```bash
ssh -T Tailscale_macmini \
  'PATH="$HOME/.local/bin:$PATH"; python3 /path/to/repo/scripts/install_model_inquiry_host.py check --repo-root /path/to/repo --bin-dir "$HOME/.local/bin" --python /path/to/repo/.venv/bin/python3'
```

If `check` reports a stale wrapper after an intentional checkout or interpreter
move, inspect the fixed launcher and both role wrappers first. Only when they are
confirmed as superseded installation artifacts, move them to an owner-only
backup directory and rerun
`install`. The installer intentionally does not overwrite or delete a stale,
symlinked, or unrelated command. Uninstall uses the same rule: verify lineage,
back up or remove exactly those three wrapper files, then rerun `check` to confirm
they are unavailable.

## Notes
- Embeddings must never route to the gaming PC (identity drift would force a full
  index rebuild — see `docs/LLM_ROUTING.md`). The gateway enforces this; don't
  bypass it.
- Keep the mini headless-friendly: enable Screen Sharing + Remote Login (SSH) in
  System Settings so the operator can reach it from the MacBook Air over Tailscale.
