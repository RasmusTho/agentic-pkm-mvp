---
name: Companion UI Local Access Model
description: Localhost, LAN, Tailscale, token, and CSRF posture for Companion UI access
doc_role: Access model / security posture
authority: Binding docs-first access model for Companion UI browser dev/staging and future production hardening.
owner: Companion UI / product architecture
last_reviewed: 2026-05-19
source_contracts:
  - companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md
  - companion-ui/docs/REAL_NOTE_WORKSPACE_DEV_PAGE.md
  - docs/ENVIRONMENTS.md
governing_issue: "#1125"
---

# Local Access Model

## Purpose

Define the local auth and trusted-device access model for Companion UI before
production hardening or broader LAN/Tailscale use is implemented.

This document is docs-first. It does not implement auth, TLS, reverse proxying,
token issuance, or session cookies.

For the current production/network exposure review profile, use
`companion-ui/docs/PRODUCTION_EXPOSURE_SECURITY_PROFILE.md`. That profile consumes this access model
and the security architecture spine; it does not implement hardening.

## Loopback Bind Default

Default operator posture: bind Companion UI to `127.0.0.1` and require no auth for loopback-only
personal use.

Rules:

- The Companion UI **test/prod** channel launchers bind to `127.0.0.1` by default.
- The **dev** launcher (`make dev-ui`) binds to `0.0.0.0` by default for LAN/Tailscale UAT;
  set `CUI_BIND_LAN=0` to force loopback-only on dev.
- For test/prod, LAN/Tailscale UAT requires an explicit `CUI_BIND_LAN=1` operator action, which
  binds the UI to `0.0.0.0`. The shared lib default remains `127.0.0.1`; only the dev launcher
  pre-sets `CUI_BIND_LAN=1`.
- `HOST` is not a Companion UI channel launcher exposure control.
- The runtime API used by the page may still be local to the server process.
- No token, cookie, or login is required for loopback-only personal use.
- This default is acceptable only while the service is not reachable from other devices.

Rationale:

- Loopback-only access keeps the default threat model local to the operator's machine.
- The current server is still explicitly not public-internet ready.
- Adding auth before the trusted-device workflow is proven would create more operational complexity
  without changing the default network exposure.

## LAN and Tailscale

LAN or Tailscale access is opt-in trusted-device UAT posture.

Rules:

- The Companion UI channel launchers expose the UI on LAN/Tailscale only when `CUI_BIND_LAN=1` is
  set.
- The operator is responsible for deciding that the LAN or Tailnet is trusted
  enough for the current dev/staging posture.
- Public internet exposure is not supported.
- Work-computer or workplace-network access is deferred unless it is already
  allowed by the operator's approved network policy.

Minimum posture for LAN/Tailscale dev use:

- Use only trusted devices.
- Keep the service off the public internet.
- Prefer Tailscale over open LAN when accessing from another personal device.
- Treat LAN/Tailscale mode as dev/staging, not production.

Future production posture for non-loopback access should add token/session
auth before treating the surface as supported beyond trusted-device personal
use.

## Token or Session Auth Option

When Companion UI moves beyond loopback-only dev usage, the minimal auth option
is an operator-issued bearer token or local session secret.

Expected shape:

- The runtime generates or reads a local secret from operator configuration.
- The browser/dev page sends the token on API calls using an authorization
  header or same-site session cookie.
- The token is scoped to the local Companion UI surface.
- The token does not grant shell access, vault path access, or direct file I/O.
- The token is revocable by rotating the local secret.

This document does not choose a final implementation mechanism. It only states
that non-loopback supported access should not rely on network trust alone once
the workspace aggregate and mutation-capable browser flows mature.

## CSRF

Loopback-only dev posture has a narrower CSRF threat model but is not immune to
browser-origin mistakes.

Rules for the current local model:

- Mutating runtime endpoints must not rely on browser UI state as authority.
- Mutating requests should use JSON APIs and explicit methods, not GET.
- If cookie-based auth is introduced, CSRF protection becomes mandatory for
  mutating endpoints.
- If bearer-token auth is introduced, tokens must not be exposed in URLs.
- CORS should remain restrictive by default. Do not allow arbitrary origins for
  mutation-capable endpoints.

For the current read-only dev page:

- `GET /api/companion/workspace` is read-side only.
- `POST /api/panel/confirm` and Canvas edit endpoints remain explicit mutation
  boundaries and must keep runtime-side policy, WriteGuard, idempotency, and
  receipt checks.

## Dev and Production Profile Separation

| Concern | Dev/staging profile | Future production profile |
|---|---|---|
| Bind address | `127.0.0.1` default; `0.0.0.0` only with `CUI_BIND_LAN=1` | Localhost-first; supported non-loopback access requires explicit hardening |
| Auth | None for loopback-only | Token/session auth for supported non-loopback access |
| TLS | Not required for loopback-only dev | Required for public or reverse-proxied exposure; public exposure is not currently supported |
| Reverse proxy | Out of scope | Future hardening option |
| Public internet | Not supported | Not supported until a separate auth/TLS/reverse-proxy contract is accepted |
| Multi-user | Not supported | Non-goal unless a later product decision changes scope |

## non-goals

- public internet exposure.
- Multi-user support.
- Enterprise auth.
- OAuth/SAML/SSO.
- Browser direct vault filesystem access.
- Treating network-level trust as production-grade auth.
- Implementing auth hardening in this docs-first issue.

## Implementation Trigger

Auth hardening implementation must not start until this document is accepted.

In particular, implementation of token/session auth, CSRF middleware,
reverse-proxy behavior, or production access hardening must be scoped in a
separate implementation issue after the workspace aggregate endpoint is
delivered.

Issue #1133, or any equivalent auth-hardening issue, must treat this document
as the access-model source of truth.
