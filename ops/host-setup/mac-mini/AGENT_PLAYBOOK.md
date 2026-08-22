# Agent Playbook — Mac mini (macOS)

You are an operator or host agent running on the Mac mini. The Mac mini is
**Ollama-only**: install and verify Ollama/model serving, but do not install or
start the Yggdrasil API, database, worker, watcher, Companion UI, or gateway.
Those product-runtime services belong on the new Linux/Tailscale hosts. Work
top to bottom; stop and report if a step fails.

## Preconditions (the operator did these by hand)
- Tailscale installed and signed in (same tailnet as the gaming PC + Air).
- This repo is cloned locally.
- Homebrew + `python3` available (`brew --version`, `python3 --version`).

## Steps
1. **Config.** Ensure `ops/host-setup/config.env` exists (copy from
   `config.example.env`). Set `GAMING_PC_HOST` to the gaming PC's Tailscale name
   (`tailscale status` lists peers). Keep `EMBED_MODEL` as-is — it is pinned here.

2. **Install and verify Ollama only.** The existing `install.sh` also provisions
   the legacy gateway and is not an approved live-runtime installer for this
   topology. Until that script is split, install Ollama and pull the approved
   models through the normal host package flow without running the legacy gateway
   setup.

3. **Verify Ollama only:** confirm the Ollama service is reachable on its
   operator-approved host endpoint and that the approved models are present.
   Do not verify or start the legacy gateway; it is not part of the Mac mini
   runtime boundary anymore.

4. **Report only the Ollama endpoint and model inventory** to the operator. The
   product-runtime host must later configure its explicit Tailscale-reachable
   endpoint; do not start a local Yggdrasil stack from this playbook.

## BuilderOps Model Inquiry host entrypoints

Under ADR-0064's 2026-07-30 owner-cost ruling, current host-local Builder model
inquiry uses the existing subscription-backed GUI-session bridge as its
sanctioned operational auth. Metered provider API keys are intentionally
unprovisioned. This Model Inquiry-only subscription path is never a CKM
credential source or fallback.

The repository also owns the distinct dormant provider-API launcher
`yggdrasil-model-inquiry-provider-api` plus two stable provider-API role commands:
`fable-model-inquiry-role` and `codex-model-inquiry-role`. They preserve the
declared-credential mechanism for any future metered path, but they are not the
current operational auth and do not replace or retire the sanctioned
subscription bridge or its `yggdrasil-model-inquiry` launcher. Install or verify
these owner-only wrappers only to validate that versioned mechanism against the
current repository checkout:

```bash
repo_root="$(git rev-parse --show-toplevel)"
python3 "$repo_root/scripts/install_model_inquiry_host.py" install \
  --repo-root "$repo_root" \
  --bin-dir "$HOME/.local/bin" \
  --python "$repo_root/.venv/bin/python3"
```

The operation is idempotent. An exact rerun reports the provider-API launcher and both role
entrypoints as `unchanged`; an unrelated existing file, subscription command
occupying one of these provider-API wrapper names, symlinked bin directory, or
unsafe permissions fails closed and must be inspected rather than overwritten.
The installer does not inspect, overwrite, or declare stale the separately
sanctioned subscription launcher or bridge.
If an I/O failure interrupts the two-role install, an exact first wrapper may
remain while the second is absent. Do not delete it as rollback: rerun the same
command, which validates the retained wrapper and converges the missing role.
Any reported temporary-file cleanup failure remains an install failure and
requires inspection of owner-only `.<entrypoint>.*.tmp` files in the bin
directory.

Before treating the provider-API wrappers as matching the selected checkout,
run the sanitized, read-only check:

```bash
python3 "$repo_root/scripts/install_model_inquiry_host.py" check \
  --repo-root "$repo_root" \
  --bin-dir "$HOME/.local/bin" \
  --python "$repo_root/.venv/bin/python3"
```

The check succeeds only when all three wrappers match the selected checkout and
interpreter and the current `PATH` resolves all three names to those exact
files. Discoverability alone is not sufficient for
`yggdrasil-model-inquiry-provider-api`;
its exact repo-owned declared-credential lineage/content must match. It probes
no provider CLI, does not invoke a provider, and does not inspect
authentication.

**Provider access on this host is provisioned — never ask the owner to provision
it.** Both providers' subscription CLI logins are present in this host's login
keychain (verified 2026-07-30) and are the sanctioned operational auth for
host-local Builder model inquiry per the owner cost ruling in
`docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner
cost ruling on the model-inquiry path`. This exception is confined to Model
Inquiry and must never be offered to CKM. Before concluding anything about
provider access, verify it empirically — existence checks only, never print or
copy secret values:

```bash
KC="$HOME/Library/Keychains/login.keychain-db"; for s in "Claude Code-credentials" "Codex Auth"; do security find-generic-password -s "$s" "$KC" >/dev/null 2>&1 && echo "$s: present" || echo "$s: MISSING"; done
```

A failing inquiry run on this host is a wiring problem — a fresh ssh session
that cannot reach the login keychain, a Codex credentials-store setting that
reverted to `keyring`, or a stale launcher — never missing provisioning. The
declared `anthropic.api-key` and `openai.api-key` identifiers for the consumer
`builderops-model-inquiry` are **intentionally unprovisioned** under the same
ruling: a run over the provider-API path fails closed as
`credential_unavailable` naming only that logical identifier, and that outcome
is expected state, not an owner TODO.

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
