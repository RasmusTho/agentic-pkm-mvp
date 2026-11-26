---
status: Proposed
owner: Architecture / CES
date: 2026-11-26
---

# ADR-0070: Remote AI-client access to the MCP v1 profile through an outbound tunnel

**This record is a proposal. It admits nothing.** Until the owner ratifies it and the matching
client contract is merged, [ADR-0061](ADR-0061-mimer-mcp-client-adapter.md) and
[ADR-0069](ADR-0069-mcp-v2-authority-profile.md) are unchanged: local stdio only, no remote client,
no new authentication, and no production effect.

## Context

[Issue #6665](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6665) asks for a remote AI client,
initially ChatGPT on a tablet, to capture a short note and retrieve existing notes. The dated
[feasibility receipt on #6666](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6666#issuecomment-7201688857)
established:

- OpenAI documents full custom MCP, including writes, for Business and Enterprise/Edu on ChatGPT
  web; Pro is limited to read/fetch. Other plans, tablet use, tunnel price, and any API-billing
  prerequisite are not stated or not verified. No account check or live client test has been run.
- Secure MCP Tunnel is outbound-only and forwards to a local stdio command. The unchanged v1 sidecar
  works over stdio in a synthetic local probe, so a new MCP HTTP transport is not needed for
  connectivity.
- Over stdio the sidecar receives no end-user identity. One child process is shared by all tunnel
  sessions. The client documents no replay of interrupted calls; control-plane redelivery is not
  documented.

Properties of the delivered v1 path that are acceptable for a local process and not for a remote one:

1. The trust posture assumes the process that spawns the sidecar is a local user session. A tunnel
   daemon executes requests that originate in a provider's cloud.
2. The runtime classifies a loopback caller as trusted before it considers an API key; the health,
   legacy search, and note-read routes have no authentication dependency; and the sidecar accepts only
   the fixed capture actor. A remote call is neither separately admitted nor distinguishable.
3. Capture and note reads follow the process-selected vault, and legacy search is not bound to a vault
   at all.
4. Search returns `uuid` and title while note-read needs a path (client contract §4.2), and `ask` is
   the only route that returns both. Note-read returns an absolute host path and serves any readable
   file inside the selected root. Whatever is read leaves the host.
5. Captured text is vault content. Existing automation may classify it, call a model, or act on
   syntax it contains.

## Proposed decision

Admit one additional, separately enabled profile, **remote-tunnel v1**, with all of the following.
The local v1 profile and the v2 profile are unchanged.

### 1. Topology and exposure

- The tunnel client runs on the host that serves the Mimer loopback API and spawns the existing
  `mimer-mcp --profile v1` command over stdio in an explicit **remote mode**. Remote mode requires a
  readable credential reference (section 3), rejects `--profile v2`, generates its own trace
  identifiers, uses only the API origin provisioned with that credential, and refuses to start when
  any of this is missing. A2 packaging, the B1 stdio wire, and the rejection of listener and TLS
  switches are unchanged. Without remote mode the sidecar behaves exactly as today.
- The only new network path is outbound HTTPS from the tunnel client to the provider's documented
  tunnel endpoint. No inbound firewall rule, public endpoint, or LAN listener.
- The tunnel client's own health and admin server stays on loopback or a Unix socket; remote UI
  access, raw HTTP logging, the companion tunnel binary, and any additional forwarding target stay
  disabled.
- One active tunnel-client instance per tunnel.
- **Streamable HTTP is not admitted.** Revisit only if per-person identity becomes a requirement or
  the stdio path fails qualification.
- Remote mode restricts this adapter; it is not host isolation. A process running under the same
  account can still call the ordinary loopback API.

### 2. Operations

The grant is a subset of the five v1 tools. It is configuration, not code.

| Tool | Proposed default | Precondition |
| --- | --- | --- |
| `mimer.health` | granted | none beyond remote admission |
| `mimer.capture` | granted | inert capture (below) |
| `mimer.retrieve` | granted once its reads qualify | binding-filtered results that can be opened |
| `mimer.read_note` | granted once its reads qualify | binding-owned Markdown only |
| `mimer.ask` | **not granted** | separate qualification: it sends synthesized content, spends model budget, and appends receipts |

- Delivery may be staged: **health and capture first**, retrieval after its preconditions are met. A
  stage never claims the outcome of a later one. Without qualified remote reads, an ambiguous capture
  is handed to the owner for verification; the client does not retry.
- **Inert capture:** the runtime rejects or neutralizes panel and action syntax in remotely captured
  text and runs no secondary classification, proposal, or note rewrite for it. No automation,
  including one triggered by a later local capture, interprets it as an instruction or sends it to
  secondary classification; ingestion and indexing remain permitted. This is verified through the real
  watcher path, not only at the endpoint.
- **Remote reads:** search results are filtered to the granted binding and carry a binding-relative
  way to open them (client contract §9 F3). Only Markdown notes owned by that binding are readable;
  nested vaults, hidden content, and system content are excluded; responses carry no absolute host
  path. The same exclusions apply to search results, including titles.
- A tool outside the grant is not listed and is refused if called. The sidecar filter is launch
  configuration and defence in depth: the runtime grant is authoritative and adds no sidecar route.

### 3. Identity, authority, and vault binding

- Tunnel, workspace, and provider account controls decide who can reach the tool. They are
  **transport admission only** and grant no vault authority.
- The runtime admits remote mode through a distinct, server-derived subject established by a
  host-provisioned credential that the tunnel's caller never supplies or sees and that is not the
  general API key. Remote ingress is identified independently of credential validity, and that
  identification can only restrict access, never grant it. An uncredentialed, wrong, expired, or
  revoked remote request, or an ungranted route, is refused **before** the trusted-loopback
  classification can admit it. Revocation takes effect on the next request.
- Caller-supplied headers, MCP metadata, tool arguments, and tunnel identifiers are not identity.
- The grant names exactly one vault binding and has an expiry. The runtime resolves it server-side for
  capture, search (including index filtering), and note-read, refuses when it is unavailable, and
  never follows or changes the process vault selection. No caller can name a vault or a path outside it.
- Writes use the existing governed write chain. The capture actor stays unchanged; the remote
  principal is recorded in the native receipt context. No new policy store, grant ledger, or receipt
  authority is created: existing auth, context, and governance owners are extended, including the
  server-derived subject set and single-credential preflight of the local operator principal.
- The grant is **single-owner**. All users who can invoke the workspace app share it, so the app is
  published to the owner only. Per-person attribution is out of scope and would reopen this decision.

### 4. Secrets and lifecycle

- The tunnel runtime key is restricted to tunnel read and use. It and the runtime credential are
  referenced from owner-readable files provisioned through the approved secret boundary, with defined
  rotation, and never placed in the repository, command line, logs, or receipts. Administrative keys
  are never stored on the host. The tunnel is associated with exactly one owner workspace.
- **Revoking the runtime grant on the host is the authoritative kill** and needs no provider
  cooperation. Stopping the tunnel client, revoking its key, and deleting the tunnel are additional
  controls. Removing the workspace app is not relied on unless qualified. A call already admitted may
  complete and is reconciled under section 5.
- Rollback removes the grant and service. Local v1 use, vault content, and receipts are unaffected.

### 5. Ambiguity, logging, and privacy

- Capture keeps ADR-0061 behaviour: no adapter retry, `capture_ambiguous` with `retryable: false`,
  and verify-before-retry (client contract §6 W5). Because redelivery semantics are undocumented,
  qualification must show that disconnect-after-write and restart cause no second append, or the
  profile stays disabled for writes.
- Sidecar, runtime access log, and tunnel-client logs for remote mode contain operation, outcome, and
  trace identifier only: no query strings, note paths, payloads, or credentials, including
  diagnostics from the protocol SDK and HTTP client.
- Tool results are disclosed to the provider and handled under the owner's plan terms there. Choosing
  which vault is bound is therefore a data-disclosure decision made by the owner.

### 6. Admission gates and supersession

Source implementation may start only after owner ratification **and** the merge of this record and
the matching client contract text. On acceptance this record partially supersedes ADR-0061 C1 for
remote mode only, and amends client contract §2 and the §4 route behaviour named above. Enabling the
profile then requires, in order: merged and verified implementation; the owner's eligible account
confirmed; qualified DEV/TEST acceptance with the real client, including tablet use and
protocol-version negotiation; and a separate, explicit production authorization. A read-only result
never counts as write acceptance.

## Alternatives

| Alternative | Consequence |
| --- | --- |
| Private Streamable HTTP behind the tunnel with per-person authorization | Gives real end-user identity; adds a listener, an authorization server the tunnel does not carry, and token lifecycle. Not justified for a single owner. |
| Public HTTPS MCP endpoint (needed for Claude custom connectors) | Internet exposure of vault operations. Rejected. |
| Claude Code Remote Control from the tablet, using the local stdio sidecar | No new transport or listener and no new subscription where an eligible plan exists, but remote control covers the whole host session rather than five tools, results pass through that provider, and it is unqualified. A separate decision; not admitted here. |
| No remote access | No cost or exposure; the requested outcome is not delivered. |

## Consequences

This is more than configuration. Capture-only needs: a runtime remote subject with grant, revocation
and pinned binding; inert capture; sidecar remote mode and log suppression; tunnel service
configuration; and negative tests on the actual entrypoints. Retrieval additionally needs
binding-filtered search with openable results and restricted note reads. Cost outside the repository is an eligible provider plan (about USD 240–600 per year
for ChatGPT Business at the list prices observed on 2026-11-26; the minimum seat count was stated
inconsistently) plus any tunnel or API charge the owner's account reveals.

This ADR does not authorize a purchase, a credential, a tunnel, a deployment, or access to
production data, and it does not change MCP v2.

## References

- [ADR-0061](ADR-0061-mimer-mcp-client-adapter.md), [ADR-0069](ADR-0069-mcp-v2-authority-profile.md)
- [`MIMER_CLIENT_CONTRACT.md`](../contracts/MIMER_CLIENT_CONTRACT.md)
- [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) and
  [tunnel client documentation](https://github.com/openai/tunnel-client/tree/main/docs)
- [ChatGPT custom MCP help article](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)
