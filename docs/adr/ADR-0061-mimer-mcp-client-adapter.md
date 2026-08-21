State: Accepted (owner decision, 2026-08-21; [receipt on #3371](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3371#issuecomment-5375222455)). Admits MCP (Model Context Protocol) as an additional protocol-tier client adapter over Mimer's existing client contract and selects **A2 + B1 + C1 for v1**: a constituent-owned sidecar over the governed HTTP API, stdio only with no network listener, and the inherited loopback/LAN/tailnet trust posture with no new authentication. The fixed external operation boundary is exactly ask, governed capture, retrieve/search, note-read, and health. Streamable HTTP over tailnet/LAN and per-device authentication are deferred, separately gated follow-ons and must not be enabled implicitly. Acceptance authorizes bounded downstream implementation; it does not claim that an MCP server is shipped or operationally accepted. Numbering note: issues #3366–#3371 originally named this decision "ADR-0058", but ADR-0058 is already taken (event-horizon closure decay); this record is **ADR-0061** and supersedes those stale references.
Doc role: Decision record (ADR)
Authority: Authoritative for (a) admitting MCP as an additional protocol-tier client adapter over the Mimer client contract, (b) the selected A2/B1/C1 topology, wire-transport, and trust posture, and (c) the fixed operation boundary of the external MCP surface. It is not implementation evidence and never becomes an independent authority path: the adapter delegates to the operations and authority envelope of `docs/contracts/MIMER_CLIENT_CONTRACT.md` and creates no second knowledge API or vault-write path.
Owner: Architecture (Rasmus)
Temporal class: Durable decision. Supersede via a new ADR if the accepted topology, transport, authentication posture, or operation boundary changes.
Source of truth: This ADR owns the accepted MCP adapter decision; `docs/contracts/MIMER_CLIENT_CONTRACT.md` owns the resulting client authority and transport contract. ADR-0047 remains authoritative for the distinct consumer-side remote-multiplex seam, and ADR-0056 remains authoritative except for its MCP deferral/closed transport-set wording, which this ADR supersedes in part.

# ADR-0061: Admit MCP as an additional Mimer client adapter — topology, wire transport, and auth posture

**Date:** 2026-07-11
**Status:** Accepted (owner decision, 2026-08-21)

---

## Context

The app-connectivity audit (`docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md` §5 build list, item B1)
ranks a Mimer MCP server as the highest-leverage external-connectivity build item: it would let
MCP-capable clients (Claude Desktop/app, Codex app, and peers) reach Mimer's shipped ask,
capture, retrieve, note-read, and health surfaces through a standard protocol instead of a
bespoke HTTP client per app. Parent feature #3366 and children #3368–#3370 sequence the build;
this ADR is child #3371 (MIMER-MCP-01), the owner-gated ratification head. Its accepted contract must
land before any adapter code is treated as authorized, and acceptance alone is not evidence that
the server exists.

Two accepted decisions currently stand in the way, by design:

- **ADR-0047 (Deferred, D4)** deferred the four-rule MCP topology stance "until a concrete
  remote/sibling MCP server is actually on the table," and named its revisit trigger as exactly that
  event. B1 now puts a concrete server on the table, so the deferral's own condition to revisit is
  met. Note the seam ADR-0047 discusses is the **consumer/remote-multiplex** side (Mimer consuming
  other servers via `RemoteMCPProvider`, `app/orchestrator/mcp_tool_provider.py`); this ADR is about
  the **producer** side (Mimer *hosting* a server). Its candidate Rule 2 — "each constituent owns and
  operates the MCP server(s) exposing its own capability contracts" — is the rule this ADR would
  enact.
- **ADR-0056 (Accepted)** fixed Mimer's client transport set at governed HTTP API + direct
  filesystem and stated "MCP remains deferred per ADR-0047," while explicitly reserving the path
  back: "if MCP is later ratified, it attaches as an additional adapter under the same contract, not
  as a replacement authority path," and "supersede only if the owner … admits a new client transport
  (e.g. a ratified MCP attachment under a revisited ADR-0047)." This ADR is precisely that reserved
  event, prepared for an owner ruling.

What an external client can actually reach today is the FastAPI runtime (`app/api/app.py`): the
governed write chain `POST /api/companion/capture` (WriteGuard → DecisionToken → deterministic
append → AuthorityReceipt → outbox event) plus read routes `GET /search`, `POST /api/ask`,
`GET /api/artifacts/note`, and health/status/version. The internal descriptors
(`app/mcp/vault_tools.py`, `docs/settings/tools/mcp.vault.append_note.yaml`) are **internal
orchestrator plumbing**, not an external transport; an external MCP server must not reuse them (see
§ Relationship to the internal ToolProvider).

The owner selected all three sub-decisions in one receipt: **A2 topology**, **B1 stdio-only wire
transport**, and **C1 inherited trust posture**. The operation boundary and authority invariants
remain fixed (§ Invariants across all options).

## Invariants across all options

These hold for every option below and are not up for selection; they are the reason MCP can attach
without reopening the authority model.

1. **Fixed operation boundary — exactly five operations.** The external MCP surface exposes
   **ask, governed capture, retrieve/search, note-read, and health** — one-for-one with the shipped
   HTTP surface (`MIMER_CLIENT_CONTRACT.md` §4). It exposes nothing else.
2. **Explicit exclusions across every option.** No **generic vault write** (only the single governed
   capture-append path), and **no receipt read-back** operation or tool. No new semantic authority,
   no hidden durable store, no retrieval engine, no client-local source of truth. No reuse of
   `app/mcp/vault_tools.py` as an external transport.
3. **MCP is an adapter, never an authority path.** Every tool delegates to the corresponding
   client-contract operation and returns its result verbatim. Capture returns the API's
   PolicyDecision, DecisionToken, and AuthorityReceipt **unchanged**; it never fabricates a receipt.
   A blocked or failed governed write (WriteGuard denial, `not_acknowledged`, timeout,
   vault-selection failure) fails legibly and **never** falls back to a direct filesystem mutation.
4. **No hidden state bridges partial failure.** The adapter is stateless apart from ephemeral
   connection state. If the transport dies after the runtime accepted a capture but before the client
   sees the response, the client observes an ambiguous outcome governed by the client contract's
   verify-before-retry rule (§6 W5); the server queues no replay.
5. **Read truth stays honest.** Search/index misses keep the documented index-lag posture; ask
   failures never become answers from adapter memory; note paths are not promoted into stable
   cross-host identifiers.
6. **Transport cannot widen exposure.** A healthy protocol handler reachable on an interface outside
   the owner-accepted trust posture is a failed deployment, not partial success.

## Options and recommendation

Each sub-decision preserves the alternatives and consequences considered (attack surface,
governance load, future flexibility). The [owner receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3371#issuecomment-5375222455)
accepted the recommended A2/B1/C1 bundle exactly; the unselected alternatives remain historical
decision context only.

### Sub-decision A — Topology (who hosts the server, how it is packaged)

Constituent ownership is effectively forced by ADR-0047 candidate Rule 2 (each constituent owns its
own server; no third-party-hosted registry of the operator's surfaces). The live variation is
*packaging* — where the MCP SDK dependency and any network listener live relative to the core
runtime.

- **A1 — In-process module inside the Mimer runtime.** The MCP server is a module in `app/` sharing
  the FastAPI process, calling internal ask/retrieve/capture services directly.
  - *Attack surface:* the MCP SDK dependency and (for a network transport) a listener run inside the
    core runtime process.
  - *Governance load:* higher and ongoing — because the module can reach internal services and
    WriteGuard/`write_ops` directly, every change must be reviewed to prove it did not bypass the
    governed chain or the exclusion list. The "adapter never an authority path" invariant is
    enforced by discipline, not structure.
  - *Future flexibility:* tightest coupling to the runtime's lifecycle and dependency set; a bad MCP
    SDK release can destabilize the core runtime.
- **A2 — Separate constituent-owned adapter process (sidecar) over the governed HTTP API.** A
  distinct process/executable that is an HTTP client of the same loopback API an external client
  uses; it has no in-process access to internal tooling.
  - *Attack surface:* MCP SDK dependency and any listener live outside the core runtime; the runtime
    exposes only its existing loopback HTTP surface.
  - *Governance load:* lowest and structural — the sidecar *cannot* bypass the governed chain
    because it has no path to `WriteGuard`/`write_ops`; it can only call the same governed endpoints
    every other external client calls. The five-operation boundary is enforced by construction (it
    can only call five routes).
  - *Future flexibility:* MCP SDK/runtime upgrades are isolated from the core runtime; the semantic
    adapter stays independently testable from the wire packaging (as #3368 requires); the trade is
    one more managed process and an extra loopback hop.
- **A3 — Third-party / shared MCP gateway hosting Mimer's surfaces.** Rejected on its face: it
  violates ADR-0047 Rule 2 ("no third-party-hosted registry of the operator's surfaces") and the
  capability README non-goal ("no generic third-party MCP server receives direct vault-write
  access"). Listed only to record that it was considered and excluded.

**Recommendation (A): A2 — separate constituent-owned sidecar over the governed HTTP API.** It gives
the strongest structural guarantee of invariant 3 (adapter never an authority path) at the cost of
one extra process and a loopback hop — a good trade under the project's data-integrity-first,
security-proportionate posture, and it matches the audit/index framing ("adapter over the existing
ask/capture/retrieve/read-note/health surface with capture-receipt forwarding").

### Sub-decision B — Wire transport (which MCP wire protocol(s), bound where)

- **B1 — stdio only.** The MCP client spawns the server as a local subprocess and speaks over
  stdin/stdout.
  - *Attack surface:* **no network listener at all** — the smallest possible surface. The server
    inherits the trust of the local user session that launches it.
  - *Governance load:* minimal — no bind config, no origin checks, no network auth to get wrong.
  - *Future flexibility:* one client per spawned process; no remote/tailnet access. Fits the primary
    desktop clients (Claude Desktop, Codex app), which both support stdio.
- **B2 — Streamable HTTP, bound loopback/LAN/tailnet.** A long-lived listener that multiple and
  remote (tailnet) clients can reach.
  - *Attack surface:* a network listener — the meaningful new surface. Requires explicit bind
    defaults, origin/`Host`-header checks, and an authentication decision (sub-decision C) before it
    is usable.
  - *Governance load:* higher — every deployment must prove the listener is on an approved interface
    and rejects untrusted callers (the #3369 hardening/security work).
  - *Future flexibility:* supports remote clients across the tailnet and multiplexed sessions;
    aligns with ADR-0056's LAN/loopback/tailnet posture; the natural home for later multi-device use.
- **B3 — Both (stdio for local, HTTP for tailnet).** Maximum reach and maximum surface plus config;
  the union of B1 and B2's obligations.

**Recommendation (B): B1 (stdio) for v1, with B2 (streamable HTTP over tailnet) named as a gated
follow-on.** stdio unblocks the two primary clients with zero network attack surface and no new
authentication, letting v1 ship the semantic tool surface (#3368) and a minimal transport (#3369)
without standing up a hardened listener. Enabling B2 later pulls the per-device auth slice
(sub-decision C / ADR-0056 §9 F2) forward as its explicit gate.

### Sub-decision C — Authentication / trust posture

- **C1 — Inherit the ADR-0056 v1 posture (LAN/loopback/tailnet-only; no per-agent auth).** stdio
  inherits the local-session trust of whoever launched it; the loopback HTTP API the sidecar calls
  keeps its current no-per-route-auth posture. Matches the shipped contract exactly.
  - *Consequence:* zero new auth machinery in v1; safe **only** while there is no network listener
    (i.e., under B1). If a listener is added (B2) without C2, network trust is the only gate — the
    same flag-as-gate weakness ADR-0047 Rule 4 warns against.
- **C2 — Per-agent / per-device token on the network transport.** A bearer/API key is required and
  verified before any tool call on the HTTP transport (brings ADR-0056 §9 F2, the named first
  hardening slice, forward as a precondition of B2). Reuses the existing `X-API-Key` machinery
  (`app/auth.py`).
  - *Consequence:* real per-caller admission on the listener; modest key-management load; the
    correct gate the moment a network listener exists. Unnecessary for stdio.
- **C3 — mTLS / strong mutual identity.** Over-engineered for a single-operator trusted LAN/tailnet;
  security is proportionate and TCD-gated here. Recorded and set aside.

**Recommendation (C): C1 for v1 (because the recommended transport is stdio, no listener ships), with
C2 as the mandatory gate on B2.** No network listener means no new auth is required in v1; the moment
the HTTP transport is enabled, C2 (per-device token + origin/bind checks) becomes a precondition, not
an option. This directly enacts ADR-0047 Rule 4's "admission allowlist, legible degradation" intent
on the producer side.

### Recommended bundle

**A2 + B1 + C1 for v1:** a constituent-owned sidecar adapter process that calls Mimer's existing
governed loopback HTTP API, speaks MCP over **stdio** to locally-spawned desktop clients, and
inherits the ADR-0056 LAN/loopback/tailnet trust posture with **no network listener and no new auth**
in v1. The tailnet streamable-HTTP transport (B2) plus per-device auth (C2) are the named, separately
gated follow-on for remote/multi-device use. This bundle: enacts ADR-0047 Rule 2 on the producer
side; adds MCP as a third client transport under ADR-0056's same contract and invariants; carries the
smallest attack surface and lowest governance load that still unblocks the primary clients; and keeps
the semantic adapter (#3368) independently testable from the wire packaging (#3369), matching the
capability spec.

## Relationship to the internal ToolProvider (tool-policy contract)

The external MCP **server** accepted here is the producer side and is distinct from the internal MCP
**ToolProvider** (`app/orchestrator/mcp_tool_provider.py`, consumer/remote-multiplex side governed by
`docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`). They share only the protocol name.
Resolving the spec's open question: the internal tool-policy contract is **unaffected** — its
descriptor registry, ToolProvider boundary, validation, and executor semantics do not change. The
only recommended change there is a **narrow clarifying note** distinguishing the external
producer-side adapter (this ADR) from the internal consumer-side ToolProvider, so future readers do
not conflate them or reuse `vault_tools.py` as an external transport. ADR-0047's live
silent-fallback gap (`except Exception: pass`, consumer side) is out of scope here and stays tracked
under ADR-0047 Rule 4.

## Conform / extend / reshape against the SoT

- **ADR-0056 — Extend (superseded in part).** This ADR adds a third client transport
  (MCP) alongside HTTP API + direct filesystem, exactly the reserved "admits a new client transport"
  event ADR-0056 anticipated. It preserves every ADR-0056 invariant — the three hard authority
  invariants, the exclusion list, capture as the only write path, index-lag honesty — and reshapes
  none of them. ADR-0056 §2 is amended to list MCP as an admitted but not-yet-shipped adapter; its
  authority envelope is untouched.
- **ADR-0047 — Extend / enact on the producer side (revisit-trigger satisfied).** The audit's B1
  build item puts the concrete Mimer server proposal on the table that ADR-0047 D4 named as its
  revisit trigger. This
  ADR ratifies candidate **Rule 2** (constituent-owned server)
  on the producer side and imports the intent of **Rule 4** (admission/legible degradation) into the
  producer transport's trust posture. It does **not** reshape ADR-0047's consumer-side deferral or
  touch the remote-multiplex seam; the consumer-side silent-fallback gap remains ADR-0047's to close.
- **SBS — conforms, no reshape.** Primary subsystem EBF (external-boundary fabric — a new external
  protocol adapter); GOV retains the capture authority envelope and receipt; HIX/RCA are consumed
  through existing ask/retrieval/read surfaces; OEF owns health and acceptance evidence. No new
  semantic authority, no Builder System change, no boundary charter altered. This is an Extend-class
  item on the ecosystem-federation seam, correctly routed through an ADR per the boundary-audit rule.

## Constraints honored

- Decision and contract writeback only — no code, dependency, transport process, service unit,
  network listener, client configuration, startup change, or promotion is added by this slice.
- Accepted and superseding language is grounded in the linked #3371 owner-decision receipt; the
  accepted bundle is the owner's ruling, not an agent-selected recommendation.
- The external server is never conflated with the internal ToolProvider, and `vault_tools.py` is
  never proposed as an external transport.
- Single-operator posture preserved: server ownership follows constituent ownership under one human
  apex authority; stdio inherits the local user session and creates no listener. Any later
  Streamable HTTP listener requires the separately gated B2 + C2 decision and implementation.

## Consequences

- **Accepted bundle:** the client contract §2 gains MCP as an admitted, not-yet-shipped adapter under
  A2/B1/C1. #3368 and #3369 may be reassessed for readiness only after this accepted docs contract
  lands and verifies; this ADR does not mutate their live lifecycle state.
- **No new exposure in v1:** stdio introduces no network listener and no per-device authentication.
  Remote/multi-device MCP and its auth remain a named, separately gated follow-on (B2 + C2).
- **Numbering debris cleared:** issues #3366–#3371 reference "ADR-0058" for this decision; that
  number belongs to event-horizon closure decay. This record is ADR-0061 and supersedes those
  stale issue-text references, which should be read as pointing here. The
  `MIMER_MCP_CLIENT_ADAPTER/` spec docs' filename and decision-number anchors were corrected to
  ADR-0061 by the #4320 docs pass; #3371's executable contract was corrected before this delivery.

## Owner decision receipt

The owner accepted the recommendation on 2026-08-21 in the durable
[owner-decision receipt on GitHub Issue #3371](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3371#issuecomment-5375222455):

- **A2 topology:** constituent-owned Mimer MCP sidecar over the existing governed HTTP API.
- **B1 transport for v1:** stdio only; no network listener.
- **C1 trust posture for v1:** inherit the existing loopback/LAN/tailnet posture; add no new
  authentication while the adapter is stdio-only.

The receipt accepts exactly the five operations in § Invariants across all options and rejects
generic vault writes, separate receipt read-back, internal `vault_tools` reuse, hidden client
authority, and direct-filesystem fallback. Streamable HTTP over tailnet/LAN and per-device
authentication are explicitly deferred and require a separate gated follow-on. The receipt
authorizes bounded downstream implementation but does not claim a shipped or operationally
accepted server.

## References

- `docs/adr/ADR-0047-mcp-topology-federation-stance.md` — deferred four-rule topology stance; Rule 2
  (constituent-owned servers), Rule 4 (admission/legible degradation), revisit trigger (D4).
- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md` — accepted transport set (HTTP + direct
  FS), reserved "admits a new client transport" supersession path, v1 LAN/loopback auth posture.
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §2 (classification/transports), §4 (callable HTTP
  surface), §3 (three hard invariants), §9 F2 (per-agent identity hardening slice).
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md` — internal ToolProvider / remote-multiplex
  seam (distinct from the external server proposed here).
- `docs/architecture/ecosystem-federation.md` § Dual-role + MCP → MCP topology stance; § SBS
  reconciliation.
- `docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md` §5 build list — B1 (Mimer MCP server).
- `docs/MIMER_MCP_CLIENT_ADAPTER/README.md`, `RATIFY_MCP_CLIENT_ADAPTER.md`,
  `EXPOSE_GOVERNED_MIMER_TOOLS_OVER_MCP.md`, `PACKAGE_AND_HARDEN_MIMER_MCP_TRANSPORT.md` — capability
  spec and child tasks (#3366, #3368–#3371).
- `app/api/app.py`, `app/api/routes/capture.py` (governed chain), `app/mcp/vault_tools.py` +
  `docs/settings/tools/mcp.vault.append_note.yaml` (internal plumbing, not an external transport).
