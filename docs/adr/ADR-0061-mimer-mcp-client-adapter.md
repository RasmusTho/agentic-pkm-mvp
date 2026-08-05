State: Proposed (owner decision pending, 2026-07-11). Prepares — but does not make — the decision to admit MCP (Model Context Protocol) as an additional protocol-tier client adapter over Mimer's existing client contract, exposing exactly the already-shipped ask, governed-capture, retrieve/search, note-read, and health operations. Enumerates topology, wire-transport, and authentication alternatives with consequences and a recommendation. It changes no current authority: `docs/contracts/MIMER_CLIENT_CONTRACT.md`, ADR-0047, and ADR-0056 remain authoritative and MCP is NOT an admitted Mimer client transport until an owner-decision receipt on #3371 accepts one option. Only then may this ADR become Accepted and record supersession precisely. Numbering note: issues #3366–#3371 (and, before the #4320 correction, the specification directory) name this decision "ADR-0058", but ADR-0058 is already taken (event-horizon closure decay); this record is **ADR-0061** and supersedes those stale "ADR-0058" references.
Doc role: Decision record (ADR)
Authority: Not authoritative while Proposed — advisory decision-preparation only. If accepted by an owner receipt on #3371, it becomes authoritative for (a) admitting MCP as an additional protocol-tier client adapter over the Mimer client contract, (b) the topology/wire-transport/auth posture of that adapter, and (c) the fixed operation boundary of the external MCP surface. It never becomes an independent authority path: the adapter delegates to the operations and authority envelope of `docs/contracts/MIMER_CLIENT_CONTRACT.md` and creates no second knowledge API or vault-write path.
Owner: Architecture (Rasmus)
Temporal class: Proposed decision-preparation; becomes a Durable decision only on an accepting owner receipt. Supersede via a new ADR only after acceptance.
Source of truth: While Proposed, the authoritative records remain ADR-0047, ADR-0056, and `docs/contracts/MIMER_CLIENT_CONTRACT.md`. This ADR is the proposal surface plus (on acceptance) the decision record; its design content, if accepted, lands in the Mimer client contract § Classification and transports.

# ADR-0061: Admit MCP as an additional Mimer client adapter — topology, wire transport, and auth posture (proposed)

**Date:** 2026-07-11
**Status:** Proposed (owner decision pending)

---

## Context

The app-connectivity audit (`docs/audits/APP_MCP_CONNECTIVITY_2026-07-07.md` §5 build list, item B1)
ranks a Mimer MCP server as the highest-leverage external-connectivity build item: it would let
MCP-capable clients (Claude Desktop/app, Codex app, and peers) reach Mimer's shipped ask,
capture, retrieve, note-read, and health surfaces through a standard protocol instead of a
bespoke HTTP client per app. Parent feature #3366 and children #3368–#3370 sequence the build;
this ADR is child #3371 (MIMER-MCP-01), the owner-gated ratification head that must land before any
adapter code is written.

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

Three sub-decisions need one owner ruling each: **topology** (who hosts the server and how it is
packaged), **wire transport** (which MCP wire protocol(s) are exposed and where they bind), and
**authentication / trust posture** (what gates a caller). The operation boundary and authority
invariants are fixed and identical across all options (§ Invariants across all options).

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

Each sub-decision is presented with concrete alternatives and honest consequences (attack surface,
governance load, future flexibility). A recommendation follows each, and a combined recommended
bundle closes the section. **None of these is chosen until the owner rules on #3371.**

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

The external MCP **server** proposed here is the producer side and is distinct from the internal MCP
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

- **ADR-0056 — Extend (supersede-in-part on acceptance).** This ADR adds a third client transport
  (MCP) alongside HTTP API + direct filesystem, exactly the reserved "admits a new client transport"
  event ADR-0056 anticipated. It preserves every ADR-0056 invariant — the three hard authority
  invariants, the exclusion list, capture as the only write path, index-lag honesty — and reshapes
  none of them. On acceptance, ADR-0056 §2 is amended to list MCP as an admitted adapter; its
  authority envelope is untouched.
- **ADR-0047 — Extend / enact (revisit-trigger satisfied).** B1 is the concrete server that ADR-0047
  D4 named as its revisit trigger. This ADR ratifies candidate **Rule 2** (constituent-owned server)
  on the producer side and imports the intent of **Rule 4** (admission/legible degradation) into the
  producer transport's trust posture. It does **not** reshape ADR-0047's consumer-side deferral or
  touch the remote-multiplex seam; the consumer-side silent-fallback gap remains ADR-0047's to close.
- **SBS — conforms, no reshape.** Primary subsystem EBF (external-boundary fabric — a new external
  protocol adapter); GOV retains the capture authority envelope and receipt; HIX/RCA are consumed
  through existing ask/retrieval/read surfaces; OEF owns health and acceptance evidence. No new
  semantic authority, no Builder System change, no boundary charter altered. This is an Extend-class
  item on the ecosystem-federation seam, correctly routed through an ADR per the boundary-audit rule.

## Constraints honored

- Decision-preparation only while Proposed — no code, dependency, transport process, service unit, or
  client configuration is added by this ADR's PR, and no current-state owner doc is promoted. The
  Mimer client contract, ADR-0047, and ADR-0056 remain unchanged and authoritative.
- No Accepted or superseding language takes force until an owner-decision receipt on #3371 is linked
  from § Owner decision receipt. The recommendation is advisory; the ruling is the owner's.
- The external server is never conflated with the internal ToolProvider, and `vault_tools.py` is
  never proposed as an external transport.
- Single-operator posture preserved: server ownership follows constituent ownership under one human
  apex authority; security is proportionate (trusted LAN/tailnet now, per-device auth as the gate on
  any network listener), consistent with the project's data-integrity-first, security-TCD-gated
  stance.

## Consequences

- **If accepted (recommended bundle):** #3368 (expose governed tools over MCP) and #3369 (package and
  harden transport) unblock; the client contract §2 gains MCP as an admitted adapter; the primary
  desktop clients can reach Mimer over a standard protocol with no new network surface or auth in v1.
  Remote/multi-device use and its auth are a named, separately gated follow-on (B2 + C2).
- **If accepted with a different bundle:** the downstream slices bind to whatever topology/transport/
  auth the owner selects; the invariants and five-operation boundary hold regardless of which bundle
  wins.
- **If declined:** MCP stays deferred; ADR-0056's HTTP + direct-FS transport set and ADR-0047's
  deferral both stand unchanged; #3368–#3370 remain blocked and #3366 stays a blocked validation hub.
- **Numbering debris cleared:** issues #3366–#3371 reference "ADR-0058" for this decision; that
  number belongs to event-horizon closure decay. This record is ADR-0061 and supersedes those
  stale issue-text references, which should be read as pointing here. The
  `MIMER_MCP_CLIENT_ADAPTER/` spec docs' filename and decision-number anchors were corrected to
  ADR-0061 by the #4320 docs pass.

## Owner decision receipt

**No owner ruling is recorded yet.** This ADR stays `State: Proposed` and claims no acceptance or
supersession until an explicit owner-decision receipt is posted on **GitHub Issue #3371** and linked
from this section. Only after that link exists may this ADR's state become Accepted, may ADR-0056 §2
be amended to admit MCP, and may `docs/contracts/MIMER_CLIENT_CONTRACT.md` § Classification and
transports be updated to exactly the ruled option.

The single question the owner must answer to move this to Accepted:

> **Do you accept admitting MCP as an additional Mimer client adapter now under the recommended bundle
> — a constituent-owned sidecar over the governed HTTP API (A2), stdio wire transport for v1 (B1),
> inheriting the ADR-0056 LAN/loopback/tailnet trust posture with no network listener and no new auth
> (C1) — with the tailnet streamable-HTTP transport and per-device auth (B2 + C2) as a separately
> gated follow-on? Or do you prefer a different topology/transport/auth bundle, or to keep MCP
> deferred?**

The pivotal sub-choice inside that question is the **exposure/transport posture** (B1 stdio-only vs
B2 tailnet HTTP), because it determines the network attack surface and whether the per-device auth
slice (C2) must ship in v1; topology (A2) and auth (C1/C2) largely follow from it.

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
