---
name: Companion UI Production Exposure Security Profile
description: Network exposure, auth, CSRF/CORS, rendering, and authority posture for Companion UI production-readiness review
doc_role: Security exposure profile
authority: Companion UI exposure-security companion to LOCAL_ACCESS_MODEL; does not implement runtime hardening.
owner: Companion UI / security architecture
last_reviewed: 2026-06-04
source_contracts:
  - companion-ui/docs/LOCAL_ACCESS_MODEL.md
  - companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md
  - companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md
  - docs/SECURITY_ARCHITECTURE.md
  - docs/SECURITY_TRUST_BOUNDARIES.md
governing_issue: "#1589"
---

# Companion UI Production Exposure Security Profile

## Purpose

This profile defines how to reason about Companion UI exposure before production or networked use.
It records posture and review inputs only. It does not implement auth, TLS, CORS, CSRF, renderer
changes, deployment automation, or runtime behavior.

The current system is personal/local-first but normally runs as a trusted-device server. LAN and
Tailscale are the default operator access posture, while public-internet scenarios remain
unsupported unless a separate hardening contract accepts them.

## Exposure posture

| Exposure mode | Current support posture | Auth/session assumption | CSRF/CORS posture | Review level | Notes |
| --- | --- | --- | --- | --- | --- |
| Localhost loopback | Supported opt-out when bound to `127.0.0.1`. | No auth required for loopback-only personal use. | Keep CORS restrictive; mutating routes use explicit non-GET methods. | Level 1 for read-only changes, Level 2 for mutation/rendering changes. | Threat model is mainly local process/browser-origin mistakes and accidental data exposure. |
| LAN | Default trusted-device server posture, not production hardening. | Network trust alone is not production-grade auth. Token/session auth should precede broader supported non-loopback use. | Arbitrary origins must not be allowed for mutation-capable routes; cookie auth would require CSRF protection. | Level 2 minimum. | Treat as trusted-device personal/staging only. |
| Tailscale | Preferred over open LAN for personal multi-device access. | Tailnet membership is not a substitute for application auth once mutation-capable flows mature. | Same as LAN; be explicit about browser origin and session behavior. | Level 2 minimum. | Lower exposure than public internet, but not equivalent to loopback. |
| Public internet | Unsupported. | Requires separate accepted auth, TLS, reverse-proxy, token/session, CORS/CSRF, rate-limit, and operational contract before support. | Must be designed before exposure; no default permissive posture. | Level 3 or higher before support. | Do not expose current Companion UI/API publicly as a supported mode. |

## Auth token and API key posture

Current loopback posture:

- no token, cookie, or login is required for loopback-only development;
- provider API keys stay in local environment/config surfaces and must not appear in browser state,
  URLs, logs, prompts, traces, or docs;
- UI access must not grant shell access, direct vault filesystem access, or provider-key access.

Future non-loopback posture:

- use an operator-issued bearer token or local session secret before supported LAN/Tailscale use;
- never place bearer tokens in URLs;
- make token rotation a local operator action;
- scope tokens to Companion UI/API access only;
- require a separate implementation issue for token/session behavior.

## CSRF, CORS, and session assumptions

Current assumptions:

- no cookie-auth session is currently declared as production support;
- mutating endpoints use explicit `POST` or `DELETE`, not `GET`;
- runtime routes must classify and enforce authority server-side;
- CORS should remain restrictive by default.

Review triggers:

- introducing cookie-based auth makes CSRF protection mandatory for mutation routes;
- allowing non-loopback browser origins requires a CORS review;
- exposing mutation-capable API routes to LAN/Tailscale requires token/session posture review;
- exposing diagnostic routes or event tails outside loopback requires a separate review.

## Rendering and sanitization expectations

The renderer remains a projection of vault Markdown, not an authority surface.

Required expectations:

- vault files are never read directly by the browser;
- vault paths and content enter the browser only through runtime API responses;
- renderer output is a rebuildable projection;
- renderer-side output must not call write endpoints;
- plugin execution, Dataview execution, arbitrary remote file loading, and direct vault writes are
  out of scope for the renderer contract;
- unsafe Markdown, HTML, asset, or embed behavior should be reviewed before broader exposure.

## Authority invariants

- Companion UI is a projection/control surface, not file authority.
- The browser must not classify its own durable authority.
- Runtime/server-side code owns mutation classification.
- Governance-bearing mutations route through policy, WriteGuard, idempotency, and receipt behavior.
- Canvas/body co-authoring remains distinct from governance-bearing mutation and uses user-present
  confirmation, undo, and session-log provenance rather than Panel governance receipts.
- UI-local stores must not hold meaning-bearing artifacts as hidden truth.

## Unsupported exposure modes

The following are unsupported until separate accepted hardening work exists:

- public internet exposure;
- multi-user operation;
- enterprise auth/OAuth/SAML/SSO;
- browser direct vault filesystem access;
- tokenless non-loopback production use;
- permissive CORS for mutation-capable endpoints;
- cookie/session auth without CSRF protection;
- renderer plugin execution or Dataview-like code execution;
- remote asset loading that bypasses runtime asset policy.

## Review checklist

- What bind address and network path are in scope?
- Is the surface read-only, body co-authoring, governance-bearing, diagnostic, or operational?
- Which routes from `docs/security/API_SECURITY_MATRIX.md` become reachable?
- Are auth/session/token assumptions explicit?
- Are CORS and CSRF assumptions explicit?
- Are renderer and asset behaviors still read-only projections?
- Does the change preserve no-direct-vault-access?
- Does the change preserve body co-authoring versus governance-bearing write lanes?
- Is public exposure explicitly unsupported or covered by a separate accepted contract?
