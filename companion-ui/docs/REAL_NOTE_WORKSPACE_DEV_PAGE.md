# Real-Note Workspace Dev Page

**Status: dev/staging only — this is not a production UI contract.**

## Visual alignment history

| Pass | PR | What changed |
|---|---|---|
| Minimal dev server (diagnostic view) | #1108 (#1103) | Plain HTML table render: functional, no visual design |
| First visual alignment pass | #1118 | Yggdrasil shell: note body as primary surface, provenance chrome, agent rail placeholder, dark design tokens — still not production UI |

The first visual alignment pass (#1118) replaces the plain diagnostic table with a
contract-aligned workspace shell. It uses Yggdrasil design tokens, preserves all
functional behavior, and adds stable `data-testid` / `data-region` attributes for
future Canvas/Panel integration. Canvas body-edit and Panel execution remain out of
scope. See `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`
and `tests/companion_ui/test_real_note_workspace_visual_shell.py` for the
implementation and verification targets.

---

## 1. Purpose and Scope

This document describes the Companion UI dev/staging page that loads a
real vault note through the runtime API and renders it through the read-only
workspace shell.

Key constraints:

- **Dev/staging page only.** Not a production UI contract. Not a production UI
  framework decision.
- **Runtime API is the only note access path.** The Companion UI dev page does
  not read vault files directly, does not know the vault path, and does not
  choose which vault is active.
- **No direct vault access.** Vault files are never accessed from the browser
  or from the Companion UI Python layer.
- **No auth/TLS/reverse-proxy implementation.** This page is suitable for local
  and Tailscale/LAN developer access only. Production hardening is deferred.
- **No public internet exposure.** The dev server must bind to `127.0.0.1` by
  default.

The Companion UI dev page reads from whichever vault is bound to the configured
runtime API. It does not know or choose the vault directly.

---

## 2. How to Start the Runtime API

Refer to the canonical runbooks rather than this document for current startup
steps:

- `docs/runbooks/RUNBOOK_STARTUP.md`
- `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md`
- `scripts/start_full_system.sh`

The runtime environment determines which vault is read. Select it via
`PKM_ENVIRONMENT`:

```bash
# dev environment (binds dev vault, e.g. Nifelheim)
PKM_ENVIRONMENT=dev scripts/start_full_system.sh

# test environment (binds test vault, e.g. Bifröst)
PKM_ENVIRONMENT=test scripts/start_full_system.sh

# prod environment (binds prod vault, e.g. Midgård)
PKM_ENVIRONMENT=prod scripts/start_full_system.sh
```

Canonical runtime API ports (from `docs/ENVIRONMENTS.md`, parallel stacks):

| Environment | Runtime API port |
|-------------|-----------------|
| `prod`      | `18000`         |
| `dev`       | `18001`         |
| `test`      | `18002`         |

Verify the runtime is healthy before opening the dev page:

```bash
curl http://localhost:<api-port>/healthz
# or
python -m app.cli status
```

---

## 3. How to Start the Companion UI Dev Page

The browser dev server ships as `companion_ui.workspace.serve_dev_page` (#1103).

### Canonical operator command (recommended)

For dev/Niflheim UAT, one repo-owned command starts the runtime API **and** the
Companion UI dev page, with guards (Issue #1358):

```bash
make dev-ui            # start dev runtime + Companion UI against Niflheim
make dev-ui-doctor     # read-only diagnostic (no services started, no vault writes)
```

`make dev-ui` (→ `scripts/dev/start_niflheim_ui.sh`):

- requires `.env.dev.local` (gitignored) and fails fast if it is missing;
- refuses to start if the resolved `VAULT_ROOT` is not Niflheim/Nifelheim;
- brings up the dev runtime via `scripts/start_full_system.sh`
  (`PKM_ENVIRONMENT=dev`, project `pkm-dev`) and waits for `/healthz` on `18001`;
- verifies the API container sees its `/app/vault` mount;
- replaces only a stale **Companion UI** listener on `8111` — never an unrelated
  SSH/Colima/Docker process — and starts the dev page;
- prints the final UAT URL(s) and the API/UI log paths.

LAN/Tailscale UAT is opt-in and explicit:

```bash
CUI_BIND_LAN=1 make dev-ui                     # bind UI to 0.0.0.0
CUI_TARGET_NOTE="Some Note.md" make dev-ui     # also verify a note via the API
```

`make dev-ui-doctor` (→ `scripts/dev/dev_ui_doctor.sh`) is read-only and reports:
Docker/Colima availability, dev vault resolution (Niflheim), API health, the
container vault mount, UI-port occupancy (distinguishing a Companion UI listener
from an unrelated process), UI reachability, an optional target note, and the
Tailscale IP. Expected output is a labelled `[ok]/[warn]/[FAIL]` checklist.

For test/Bifröst UAT/smoke verification, the same pattern is bound to the test
channel (Issue #1359):

```bash
make test-ui           # start test runtime + Companion UI against Bifröst
make test-ui-doctor     # read-only test-channel diagnostic
```

`make test-ui` (→ `scripts/test/start_bifrost_ui.sh`) uses
`PKM_ENVIRONMENT=test`, requires `.env.test.local`, refuses to start unless the
resolved vault is Bifröst/Bifrost, and reports its channel identity
(`PKM_ENVIRONMENT=test`, project `pkm-test`, DB `app_test`, API `18002`, UI
`8112`) so the test channel is never confused with dev or prod.

The manual environment-variable invocations below remain valid for ad hoc use.

### Environment variables

| Variable               | Default                     | Purpose                                       |
|------------------------|-----------------------------|-----------------------------------------------|
| `COMPANION_API_BASE_URL` | `http://127.0.0.1:18001`  | Runtime API base URL the dev page calls       |
| `HOST`                 | `127.0.0.1`                 | Bind address for the dev server               |
| `PORT`                 | `8111` (dev), `8112` (test), `8113` (prod) | Dev server listen port        |

### Companion UI dev page ports

| Environment | Companion UI dev page port |
|-------------|---------------------------|
| `dev`       | `8111`                    |
| `test`      | `8112`                    |
| `prod`      | `8113`                    |

### Local-only startup (default)

```bash
cd companion-ui/companion-app
COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=127.0.0.1 PORT=8111 \
  python -m companion_ui.workspace.serve_dev_page
```

Then open:

```
http://127.0.0.1:8111/?note_path=<valid-dev-note-path>
```

### Explicit LAN/Tailscale startup

Only use this when intentionally enabling LAN or Tailscale access.
`HOST=0.0.0.0` must be explicit. Do not expose publicly.

```bash
cd companion-ui/companion-app
COMPANION_API_BASE_URL=http://<host-lan-or-tailnet-ip>:18001 HOST=0.0.0.0 PORT=8111 \
  python -m companion_ui.workspace.serve_dev_page
```

Then from a trusted device on the same LAN or Tailnet:

```
http://<host-lan-or-tailnet-ip>:8111/?note_path=<valid-dev-note-path>
```

---

## 4. Production Launch Profile

The production launch profile is separate from the dev/staging server. It keeps
the same runtime-mediated workspace boundary, defaults to the production runtime
API port, links production-profile static assets under `/static/`, and omits
dev/staging markers from rendered output. It does not add auth, TLS, reverse
proxying, public internet exposure, or direct vault access.

```bash
cd companion-ui/companion-app
COMPANION_API_BASE_URL=http://127.0.0.1:18000 HOST=127.0.0.1 PORT=8113 \
  python -m companion_ui.workspace.serve_production_page
```

Then open:

```
http://127.0.0.1:8113/?note_path=<valid-prod-note-path>
```

Production profile defaults:

| Variable | Default | Purpose |
|---|---:|---|
| `COMPANION_API_BASE_URL` | `http://127.0.0.1:18000` | Production runtime API target |
| `HOST` | `127.0.0.1` | Localhost-first bind address |
| `PORT` | `8113` | Companion UI production profile port |

---

## 5. Environment-Bound Vault Access Model

> The Companion UI dev page reads from whichever vault is bound to the
> configured runtime API. It does not know or choose the vault directly.

Companion UI does not choose the vault. Companion UI calls the runtime API.
The runtime environment determines which vault is bound.

Mapping examples (vault names are binding examples only, not UI configuration values):

| Configured `COMPANION_API_BASE_URL` | Runtime env | Bound vault (example) |
|--------------------------------------|-------------|----------------------|
| `http://localhost:18001`             | `dev`       | Nifelheim            |
| `http://localhost:18002`             | `test`      | Bifröst              |
| `http://localhost:18000`             | `prod`      | Midgård              |

**The UI must not configure vault names.** The UI configures or receives API
targets. The runtime owns environment and vault binding.

---

## 6. Manual UAT Against Environment-Bound Vaults

### Verification steps

1. **Start the runtime for the intended environment.**

   ```bash
   PKM_ENVIRONMENT=<env> scripts/start_full_system.sh
   ```

2. **Confirm runtime environment and channel.**

   ```bash
   python -m app.cli status
   python -m app.cli settings-explain
   ```

3. **Confirm runtime vault binding.**

   The `status` / `settings-explain` output will show the resolved vault root.
   Confirm it matches the intended environment-bound vault.

4. **Start the matching Companion UI dev/staging page on the matching port.**

   ```bash
   cd companion-ui/companion-app
   COMPANION_API_BASE_URL=http://127.0.0.1:<api-port> PORT=<ui-port> \
     HOST=127.0.0.1 python -m companion_ui.workspace.serve_dev_page
   ```

5. **Set the UI API base URL to the matching runtime API port.**

   The `COMPANION_API_BASE_URL` environment variable (or equivalent
   configuration field) must point at the runtime API for the intended
   environment.

6. **Enter a `note_path` valid for that environment-bound vault.**

   Use a note path that exists in the vault bound to the selected runtime.

7. **Verify the note renders through the runtime API.**

   Check that title, path, artifact ID, body, and content hash are all visible.

8. **Verify no mutation occurs during simple load.**

   A `GET /api/companion/workspace` request is read-only. Confirm no vault
   files are modified during a load-only operation.

### Example environment mappings

> These vault names are examples of environment-bound vaults, not UI
> configuration values.

| Runtime env | API port | UI port | Bound vault (example) |
|-------------|----------|---------|----------------------|
| `dev`       | `18001`  | `8111`  | Nifelheim            |
| `test`      | `18002`  | `8112`  | Bifröst              |
| `prod`      | `18000`  | `8113`  | Midgård              |

---

## 7. Local Network / Tailscale Access

### Home network (LAN) access

1. Find the Mac mini's LAN IP address:
   ```bash
   ipconfig getifaddr en0   # Wi-Fi
   ipconfig getifaddr en1   # Ethernet
   ```

2. Start the dev page with explicit `HOST=0.0.0.0` and a specific port:
   ```bash
   COMPANION_API_BASE_URL=http://<mac-mini-lan-ip>:18001 \
     HOST=0.0.0.0 PORT=8111 python -m companion_ui.workspace.serve_dev_page
   ```

3. From an iPad or laptop on the same network:
   ```
   http://<mac-mini-lan-ip>:8111/
   ```

### Tailscale access

1. Find the Mac mini's Tailscale IP:
   ```bash
   tailscale ip -4
   ```

2. Start the dev page with explicit `HOST=0.0.0.0`:
   ```bash
   COMPANION_API_BASE_URL=http://<mac-mini-tailnet-ip>:18001 \
     HOST=0.0.0.0 PORT=8111 python -m companion_ui.workspace.serve_dev_page
   ```

3. From any device on the Tailnet:
   ```
   http://<mac-mini-tailnet-ip>:8111/
   ```

### Warnings

- **LAN/Tailscale bind must be explicit.** Setting `HOST=0.0.0.0` is a
  deliberate choice; the default is `127.0.0.1` (local only).
- **Do not expose the dev page or runtime API to the public internet.**
- **Work-computer access** from a work network may require additional approval,
  VPN policy, reverse proxy, or TLS hardening depending on workplace network
  rules. Implement those as a follow-up rather than as part of this PR.

---

## 8. Safety Rules

The following safety rules apply unconditionally to the dev/staging page:

- **Do not use real dev/test/prod vaults as automated test fixtures.** Automated
  tests must use fake clients, fixtures, or `tmp_path`.
- **Default UAT remains read-only workspace loading.** A
  `GET /api/companion/workspace` call does not mutate vault files.
- **Confirm/reject/writeback testing against any real environment vault must be
  explicitly operator-gated** and use a disposable test note. It is not part of
  this PR's scope.
- **Do not expose dev/staging UI or runtime API publicly.** LAN/Tailscale
  binding must be explicit.
- **Default bind should remain local-only** (`127.0.0.1`) unless the operator
  explicitly sets `HOST=0.0.0.0`.
- **Work-computer access is deferred** unless already safely reachable through
  the operator's approved Tailscale/network setup.
- **Do not silently fall back to a default vault path** if the runtime API
  returns an error. Surface the error; do not guess a vault.

---

## 8. Out of Scope

The following are explicitly out of scope for this dev page:

- Special-casing Midgård, Nifelheim, Bifröst, or any other named vault
- Adding direct vault-path configuration to Companion UI
- Exposing vault filesystem paths to the browser
- Using real environment vaults in automated tests
- Production auth/TLS/reverse-proxy hardening
- Public internet exposure
- Canvas bounded suggestion UI (placeholder only in the agent rail)
- Canvas body-edit behavior
- Panel execution and confirmation (agent rail is a placeholder)
- Proposal-generation UI
- Production UI framework decision

The first visual alignment pass (#1118) adds the workspace shell and design tokens.
It does not claim production UI. Canvas editing and Panel execution remain out of
scope; the agent rail renders a placeholder only.

---

## 9. Related Documents

- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — UI/runtime boundary contract
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md` — Panel render contract
- `companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md` — Panel confirm API spec
- `docs/ENVIRONMENTS.md` — environment model, vault scoping, port conventions
- `docs/runbooks/UAT_REAL_NOTE_VERTICAL_SLICE.md` — UAT runbook for this vertical slice
- `docs/runbooks/RUNBOOK_STARTUP.md` — runtime startup procedures
