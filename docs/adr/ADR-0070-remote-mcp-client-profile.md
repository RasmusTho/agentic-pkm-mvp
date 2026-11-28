---
status: Accepted
owner: Architecture / CES
date: 2026-11-28
---

# ADR-0070: Remote Claude connector access to the MCP v1 profile over OAuth-protected HTTPS

## Owner decision receipt

The owner ratified this record as written on 2026-11-28 in the
[ratification receipt on Issue #6667](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6667#issuecomment-7236478483), answering "Ratify OAuth version" when offered this
OAuth profile or the fixed bearer header alternative. Acceptance authorizes bounded source
implementation (#6668) only. It does not authorize a Funnel exposure, a credential, a deployment, or
access to production data; section 6 gates those separately.

[ADR-0061](ADR-0061-mimer-mcp-client-adapter.md) and [ADR-0069](ADR-0069-mcp-v2-authority-profile.md)
stay authoritative for the local stdio sidecar and the v2 profile, except for the remote-entrypoint
amendments in section 6.

## Context

[Issue #6665](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6665) asks for a remote AI client,
used from the owner's tablet, to capture a short note and retrieve existing notes.

The [feasibility receipt on #6666](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6666#issuecomment-7201688857)
covered ChatGPT. Full custom MCP there, including OpenAI's Secure MCP Tunnel, needs a Business or
Enterprise workspace. On 2026-11-27 the owner stated that no such plan exists or will be bought, and
selected a Claude custom connector with OAuth, published through Tailscale Funnel
([#6667 decision](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6667#issuecomment-7224671886)).
The tunnel→stdio profile in the first draft of this record is therefore withdrawn.

Claude custom connectors, as documented by Anthropic on 2026-11-27 (help article, not yet verified
against the owner's account):

- Are available on all Claude plans (Free limited to one custom connector).
- Are called **from Anthropic's cloud, not from the user's device**, for every Claude client
  including the mobile apps. A tailnet-only address is therefore unreachable; the server must be
  reachable over the public internet on port 443.
- Support OAuth (Claude's published client identity, automatic registration, or an owner-supplied
  client ID and secret with the redirect `https://claude.ai/api/mcp/auth_callback`), fixed request
  headers such as a bearer token, or no authentication.

The MCP authorization specification (2025-06-18) requires an HTTP MCP server that uses OAuth to
publish protected resource metadata (RFC 9728), answer unauthenticated calls with 401 and a
`WWW-Authenticate` pointer, accept tokens only in the `Authorization` header, and reject any token
not issued for its own audience (RFC 8707). The authorization server must implement OAuth 2.1 with
metadata (RFC 8414) and PKCE, and may be co-located with the resource server. Dynamic client
registration is recommended, not required.

Properties of the delivered v1 path that are acceptable for a local process and not for a remote one
(unchanged from the reviewed first draft):

1. The trust posture assumes the caller is a local user session. Here the caller is a provider's
   cloud on the public internet.
2. The runtime classifies a loopback caller as trusted before it considers an API key; the health,
   legacy search, and note-read routes have no authentication dependency; and the sidecar accepts only
   the fixed capture actor. A remote call is neither separately admitted nor distinguishable. A
   Funnel-published listener on the same host would reach the runtime **from loopback**, and the
   loopback peer's `X-Forwarded-For` is honoured, so it would land on the trusted branch.
3. The legacy capture and note-read routes follow the process-selected vault, and legacy search is
   not bound to a vault at all. Context-bound routes already exist (`/api/companion/capture/scoped`,
   `/search/scoped`, `/api/companion/vault/notes/scoped`, with `ActiveContextSetV1`), but ADR-0069
   ties their caller to the stdio v2 profile, and there is no scoped single-note read.
4. Search returns `uuid` and title while note-read needs a path (client contract §4.2), and `ask` is
   the only route that returns both. Note-read returns an absolute host path and serves any readable
   file inside the selected root. Whatever is read leaves the host.
5. Captured text is vault content that existing automation may act on. Delivered in #6674 (captured
   panel syntax is made inert) and #6675 (watcher runs honour the manual-only gate).

## Decision

Admit one additional, separately enabled profile, **remote-http v1**, with all of the following.
The local v1 stdio profile and v2 profile behaviour are unchanged; only the caller scope of the
context carrier is extended, for this ingress.

### 1. Topology and exposure

- A new **remote MCP entrypoint** serves the Streamable HTTP MCP transport on a **loopback-bound**
  listener on the host that serves the Mimer API. It reuses the existing v1 semantic tool layer
  (`mimer_mcp_sidecar.semantic`) and calls the runtime only through the existing API routes, exactly
  as the stdio sidecar does. It is a separate process and launch configuration; the stdio sidecar
  keeps rejecting listener and TLS switches (B1 unchanged for it).
- The node name carries **exactly two mappings**:
  - **Funnel, port 443 (public):** the MCP path, `/.well-known/oauth-protected-resource`,
    `/.well-known/oauth-authorization-server`, and the token endpoint, forwarded to the remote
    entrypoint's listener. Funnel is the only public path.
  - **Serve, port 8443 (tailnet only):** the authorization and consent endpoints, forwarded to a
    **separate backend listener** that no Funnel mapping reaches. The authorization server metadata
    points `authorization_endpoint` at this origin (RFC 8414 permits an endpoint on another origin).
  Membership of the tailnet confers no authority on the public mapping: every request there is
  authenticated as in section 3. No inbound firewall rule, no LAN listener, no other mapping.
- The Funnel node must not be a host where existing tooling refuses or removes active Funnel before
  changing Serve (`docs/SECURITY.md` tailnet TLS, `scripts/builderops/configure_tailnet_tls.sh`).
  Placement is confirmed during qualification; amending that check is out of scope.
- Funnel publishes a public DNS name. That name, the tailnet name, and the host stay out of the
  repository.
- **No unauthenticated MCP route.** Discovery metadata and the OAuth endpoints are the only routes
  answered without a valid token.
- Remote mode restricts this entrypoint; it is not host isolation. A process running under the same
  account can still call the ordinary loopback API.

### 2. Operations

The grant is a subset of the five v1 tools. It is configuration, not code.

| Tool | Default | Precondition |
| --- | --- | --- |
| `mimer.health` | granted | valid token |
| `mimer.capture` | granted | inert capture (delivered, #6674) |
| `mimer.retrieve` | granted once its reads qualify | binding-filtered results that can be opened |
| `mimer.read_note` | granted once its reads qualify | binding-owned Markdown only |
| `mimer.ask` | **not granted** | separate qualification: it sends synthesized content, spends model budget, and appends receipts |

- Delivery may be staged: **health and capture first**, retrieval after its preconditions are met. A
  stage never claims the outcome of a later one. Without qualified remote reads, an ambiguous capture
  is handed to the owner for verification; the client does not retry.
- **Remote reads:** search results are filtered to the granted binding and carry a binding-relative
  way to open them (client contract §9 F3). Only Markdown notes owned by that binding are readable;
  nested vaults, hidden content, and system content are excluded; responses carry no absolute host
  path. The same exclusions apply to search results, including titles.
- A tool outside the grant is not listed and is refused if called. Tool annotations stay truthful
  (#6671); a write is never presented as read-only.

### 3. Identity, authority, and vault binding

**OAuth (owner-selected).** The remote entrypoint is an OAuth 2.1 resource server. A minimal
**co-located, single-owner authorization server** issues its tokens:

- **One pre-registered client.** The owner enters its client ID and secret in Claude ("use your own
  OAuth client"). The only accepted redirect is `https://claude.ai/api/mcp/auth_callback`, matched
  exactly. No dynamic client registration and no other client in the first version.
- Authorization code with PKCE (S256) only; no implicit or password grant. Access tokens carry this
  server's canonical MCP URL as audience, and any other audience is rejected. A `resource` value that
  names anything else is refused; whether Claude sends `resource` at all is a qualification item,
  and if it does not, the audience defaults to the single canonical URL.
- Authorization codes are single-use, live at most 60 seconds, and are bound to the client, the exact
  redirect, the PKCE challenge, the audience, and `state`.
- Short-lived access tokens (default: 1 hour) and refresh tokens with a fixed lifetime (default:
  30 days), usable only with client authentication. Tokens are opaque and stored only as hashes.
  Refresh rotation, if used, accepts the previous token once within a short grace window, so a
  provider retry does not revoke the grant.
- **One host-side grant record, the runtime grant,** holds the binding, the granted tools, and the expiry; the authorization server keeps only client and token records. Every token is
  checked against it on every request, so revoking the grant ends all tokens; per-token revocation is
  optional. The client secret is still rotated on suspicion, because a leaked secret would let another
  Claude account use the shared Claude callback.
- **Owner login at the authorization step without a public password form.** The authorization and
  consent endpoints are reachable only through the tailnet-only Serve mapping (section 1). The
  backend rejects any request carrying `Tailscale-Funnel-Request`, any request from a tagged node,
  and any request whose `Tailscale-User-Login` is not the owner's. The owner's browser reaches it
  during connector setup; Anthropic's cloud never calls it. Qualification includes a negative test
  that forged `Tailscale-User-*` headers sent through Funnel are not accepted. Like the API, this
  does not protect against a process running under the same account on the host. If qualification
  shows that Claude cannot complete a flow whose authorization endpoint is tailnet-only, the fallback
  is an owner passkey on a public authorization page; a password form is not admitted.
- The owner approves an explicit consent screen naming the binding, the granted tools, and the time
  the flow started. Approval is a deliberate submit with a CSRF token; nothing is auto-approved.

**Runtime authority (carried over from the reviewed draft):**

- A valid token is **transport admission only** and grants no vault authority by itself.
- The remote entrypoint reaches the runtime only through a **separate runtime ingress** (a Unix
  socket or its own loopback port) on which loopback trust is switched off. Every request arriving
  there is the distinct, server-derived **remote subject**, whatever headers it carries; a request
  without the valid host-provisioned credential (not the general API key, never sent to the client)
  fails closed. A route allowlist is enforced in middleware on that ingress, so routes without an
  authentication dependency are covered too. Revocation takes effect on the next request.
- The remote entrypoint calls only the existing **context-bound routes**. The runtime ingress derives
  the active context from the grant and rejects any differing carrier the entrypoint sends; no
  caller-supplied context is accepted. The entrypoint's configuration refuses the ordinary API
  address, so it cannot fall back to the trusted-loopback path. The only new route is
  a scoped single-note read for remote reads. The context carrier is reused, not changed; this record
  extends its admitted caller beyond the stdio v2 profile of ADR-0069 for this ingress only.
- Caller-supplied headers, MCP metadata, tool arguments, and Funnel or Tailscale headers on
  Funnel-forwarded traffic are not identity.
- The grant names exactly one vault binding and has an expiry. The runtime resolves it server-side
  through the context-bound routes for capture, search (including index filtering), and note-read,
  refuses when it is unavailable, and never follows or changes the process vault selection. No caller
  can name a vault or a path outside it.
- Writes use the existing governed write chain. The capture actor stays unchanged; the remote
  principal is recorded in the native receipt context. No new policy store, grant ledger, or receipt
  authority is created: existing auth, context, and governance owners are extended. The
  authorization server's client and token records are transport state, not governance authority.
- The grant is **single-owner**. Anyone the owner shares the connector with acts as the owner, so it
  is not shared. Per-person attribution is out of scope and would reopen this decision.

### 4. Secrets and lifecycle

- The OAuth client secret, token-signing or hashing material, and the remote-subject credential are
  referenced from owner-readable files provisioned through the approved secret boundary, with defined
  rotation, and never placed in the repository, command line, logs, or receipts.
- **Revoking the runtime grant on the host is the authoritative kill** and needs no provider
  cooperation. Revoking OAuth tokens, rotating the client secret, stopping the entrypoint, and turning
  Funnel off are additional controls. Removing the connector in Claude is not relied on.
- Rollback turns Funnel off and removes the grant and service. Local v1 use, vault content, and
  receipts are unaffected.

### 5. Ambiguity, abuse, logging, and privacy

- Capture keeps ADR-0061 behaviour: no adapter retry, `capture_ambiguous` with `retryable: false`,
  and verify-before-retry (client contract §6 W5). Qualification must show that disconnect-after-write
  and restart cause no second append, or the profile stays disabled for writes.
- The public endpoints have a bounded request size and a global rate limit per endpoint (the source
  address is Funnel or Anthropic's shared egress, so per-source limits mean nothing), a cap on failed
  token attempts, and repeated failures are logged as a security event without the token.
- Entry-point, OAuth, runtime access, and Funnel-adjacent logs for remote mode contain operation,
  outcome, and trace identifier only: no query strings, note paths, payloads, codes, or tokens,
  including diagnostics from the protocol SDK and HTTP client.
- Tool results are disclosed to Anthropic and handled under the owner's plan terms. Choosing which
  vault is bound is therefore a data-disclosure decision made by the owner.

### 6. Admission gates and supersession

Source implementation may start only after owner ratification **and** the merge of this record and
the matching owner-doc text. On acceptance this record partially supersedes ADR-0061 B1 and C1 for
the remote entrypoint only (the stdio sidecar is unchanged) and goes beyond B2, which was limited to
loopback, LAN and tailnet. It amends, for this entrypoint only: client contract §2, the §4 rule that a
client MUST refuse a host that is not loopback, LAN or tailnet, and the §4 route behaviour named
above; the "public exposure is unsupported" row of `docs/SECURITY_TRUST_BOUNDARIES.md`; and the
ADR-0069 caller scope of the context carrier. Enabling the profile then requires, in order: merged and verified
implementation; the owner's Claude connector confirmed on the tablet; qualified DEV/TEST acceptance
with the real client, including the OAuth flow and protocol-version negotiation; and a separate,
explicit production authorization. Turning Funnel on for any environment is an exposure effect that
needs the owner's go-ahead at that time. A read-only result never counts as write acceptance.

## Alternatives

| Alternative | Consequence |
| --- | --- |
| **Fixed bearer header instead of OAuth** (Claude "request headers") | Much less to build: no authorization server, metadata, consent, or refresh handling; the bearer is the host-revocable remote credential. Costs: one long-lived secret stored at Anthropic, rotation by hand, no short-lived tokens, no owner login step. Sections 1, 2, 4 and 5 are unchanged. A reasonable single-owner choice; not selected because the owner chose OAuth. |
| External identity provider as the authorization server | Mature login and MFA; adds a dependency, an account, and audience/resource configuration the provider may not support for MCP. Not justified for one owner unless the embedded server fails qualification. |
| ChatGPT via Secure MCP Tunnel to the stdio sidecar | Needs ChatGPT Business or Enterprise. NO-GO by owner decision 2026-11-27. |
| Tailnet-only MCP, no public path | No internet exposure, but unreachable from Claude's cloud. Works only for a client running inside the tailnet (Claude Desktop, Claude Code, or an on-device MCP client), which is not this request. |
| Claude Code Remote Control from the tablet | No new transport, but it controls the whole host session rather than five tools. Not selected. |
| No remote access | No cost or exposure; the requested outcome is not delivered. |

## Consequences

More than configuration. Capture-only needs: the remote HTTP entrypoint; the single-owner
authorization server with tailnet-only authorization; resource-server token checks; the separate
runtime ingress with the remote subject, route allowlist, grant, revocation and server-built context;
threading the remote principal into the native receipt context through the existing receipt owner
(capture's fixed actor and strict request model, client contract §9 F1); log suppression; Funnel and
Serve configuration; and negative tests on the actual entrypoints. Retrieval additionally needs binding-filtered search with
openable results and the new scoped single-note read. If the
authorization server grows beyond this minimal design during implementation, the fixed bearer header
alternative is put back to the owner before continuing. No subscription is needed beyond the owner's existing
Claude plan.

The same HTTP endpoint could later serve another MCP client that supports OAuth. That would be a
separate decision with its own entitlement check.

This ADR does not authorize a credential, a Funnel exposure, a deployment, or access to production
data, and it does not change MCP v2 behaviour.

## References

- [ADR-0061](ADR-0061-mimer-mcp-client-adapter.md), [ADR-0069](ADR-0069-mcp-v2-authority-profile.md)
- [`MIMER_CLIENT_CONTRACT.md`](../contracts/MIMER_CLIENT_CONTRACT.md)
- [Claude custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp)
- [MCP authorization specification 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [Tailscale Funnel](https://tailscale.com/kb/1223/funnel)
