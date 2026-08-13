---
name: Companion UI Local Access Model
description: Localhost, LAN, Tailscale, token, and CSRF posture for Companion UI access
doc_role: Access model / security posture
authority: Binding docs-first access model for Companion UI browser dev/staging and future production hardening.
owner: Companion UI / product architecture
last_reviewed: 2026-07-06
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

- The Companion UI channel launchers bind to `127.0.0.1` by default.
- LAN/Tailscale UAT requires an explicit `CUI_BIND_LAN=1` operator action, which binds the UI to
  `0.0.0.0`.
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

## Containerized Deployment Proxy Trust

In the documented `docker compose` deployment the browser never talks to the
runtime API directly. It talks to the `companion-ui` container, which relays the
same-origin `/api/companion/*` calls to the `api` container over the Docker
bridge network. Neither hop is loopback, so the loopback/API-key-gated
vault-selection routes (`/vault/browse`, `/vault/select`, `/vault/initialize`)
returned `401` on every onboarding action — the picker was unreachable in the
shipped topology (#3102).

Rules (implemented, #3102):

- The runtime trusts the `companion-ui` container's own server-side proxy call
  to those routes by construction. It resolves `COMPANION_UI_PROXY_HOSTS`
  (comma-separated hostnames/IPs/CIDRs; default the compose service name
  `companion-ui`) to the container's bridge address and authorises a request
  whose immediate peer is that container.
- This trusts the container's *own* call only. It does **not** look through
  `X-Forwarded-For` to launder the (non-loopback) browser address into loopback,
  and it is scoped to the resolved companion-ui address — an unrelated bridge or
  LAN peer that forges `X-Forwarded-For: 127.0.0.1` is still rejected (the #2706
  anti-spoofing posture is preserved).
- The browser→`companion-ui` hop remains the trust boundary and is still governed
  by the UI bind: loopback by default, LAN/Tailscale only with the explicit
  `CUI_BIND_LAN=1` operator opt-in on trusted devices. Enabling `CUI_BIND_LAN=1`
  therefore also makes vault selection reachable from that LAN/Tailnet through
  the trusted proxy; treat the network as trusted-device only, as above.
- Set `COMPANION_UI_PROXY_HOSTS=` (empty) to opt out and fall back to the plain
  loopback/API-key gate.

The production devUI reads delivered by #4841 are intentionally narrower than those general
Companion vault routes:

- Browser authority comes from an explicit all-loopback `COMPANION_UI_BIND_HOST` host-publish
  declaration. The production compose path is `127.0.0.1:8113:8113`; the container may listen on
  `0.0.0.0` and see a nonloopback Docker peer without treating either fact as browser authority.
  Missing, wildcard, LAN, bridge, Tailscale, mixed-resolution, or unresolvable declarations disable
  the devUI routes. `CUI_BIND_LAN=1` does not widen this production devUI exception.
- The browser request must use a loopback-local `Host` and carry no forwarded identity, including
  `Via`. The gateway sends no inbound Host, API key, authorization, forwarding, Via, client-IP, or
  proxy identity to FastAPI.
- FastAPI rejects forwarded identity first, then accepts the existing direct-loopback + local-Host
  path or only the server-derived `trusted_companion_proxy` subject from
  `resolve_auth_subject(request, None)`. An API key or arbitrary network peer cannot enter this
  read-only exception.
- The exception is limited to exact GET `/api/devui/overview` and strict GET
  `/api/devui/focus?subject=...`. It grants no wildcard, write, page, asset, CORS, or remote-browser
  access. The later #4836 presentation must consume it without widening it.

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
