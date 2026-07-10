State: Canonical hub client contract (owner rulings 2026-07-07, enacted via `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`). Closes the ecosystem audit's remaining T2 work: the "Mimer client contract" named by Epic B #3020 / #3023 / `bifrost#1` now exists as a committed hub artifact. Current-state contract over shipped surfaces; every named gap is marked as follow-on work, not claimed solved.
Doc role: Core SoT contract
Authority: Canonical for how external clients attach to Mimer: the callable surface, the two write transports (governed HTTP API and direct filesystem), the authority envelope, and the concurrent-writer client discipline. Serves BOTH client families — Bifrost native shells (`RasmusTho/bifrost`, ADR-0050) and external app agents (Claude app, Codex app, and peers). Subordinate to `docs/INTEGRATION_FABRIC_CONTRACT.md` (class taxonomy + authority rule), `docs/AGENT-FLOWS.md` (participation modes and zones), `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (the decided multi-writer mechanism, supersedes ADR-0053, resolves #3114; T2/T3 enactment pending), and `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` / `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` (runtime write mechanics). `docs/ARCHITECTURE.md` and `docs/STATUS.md` win on current runtime truth.
Owner: Architecture spine (Rasmus)
Temporal class: strategic
Review cadence: event-driven (re-verify at each Epic B wave boundary and when ADR-0055's T2/T3 enactment lands)
Source of truth: mixed
Last reviewed: 2026-07-07

# Mimer Client Contract

## 1. Purpose and audience

This is the single hub contract for every external client of Mimer (the shipped knowledge-and-cognition constituent, `app/`). One contract, two client families:

- **Bifrost native shells** — the iPhone/Watch/iPad clients (Epic B #3020; B1 `bifrost#1`/#3023), which render Mimer and Heimdal surfaces and read/write the vault.
- **External app agents** — Claude app, Codex app, and any comparable agent runtime the human points at Mimer or the vault.

The families share almost the entire seam (same HTTP API, same vault, same invariants, same auth gap), so one artifact serves both; where postures differ, the difference is stated per family in place. This closes audit item T2 (`docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §10): "Mimer client contract" now greps to a real file, and `bifrost#1`/#3023 Source Anchors can resolve here.

**What this contract is not.** It is not an SDK or a consistency mechanism. The published `_heimdal/**` schema is a client-facing manifest, while runtime parsing/enforcement remains in `app/heimdal/settings_notes.py`; the full multi-writer mechanism remains follow-on work (§9 F6).

## 2. Classification and transports

### Integration classes (per `docs/INTEGRATION_FABRIC_CONTRACT.md`)

- An external app agent is an **Agent runtime** (class 10). When it renders Mimer content to the human it additionally answers the **External UI shell** (class 8) fields.
- A Bifrost shell is an **External UI shell** (class 8) and, as the surface the human types into, participates in the **Human surface** (class 1) role. The human driving either family always remains class 1 — the client never absorbs the human's authority.
- Per-class contract-field answers are in §8.

### Participation modes (per `docs/AGENT-FLOWS.md` §3)

A client under this contract operates in two modes simultaneously:

- **API-mediated caller** — governed writes and retrieval through the HTTP surface (§4). Mediated-write semantics apply (AGENT-FLOWS §4).
- **Mode (c) direct filesystem agent** — direct reads and writes of vault Markdown under the human's delegation (§5). Observed-write semantics apply: Mimer observes, classifies, and indexes the result; a direct write is not APPLY, produces no Mimer receipt of its own, and confers no authority.

**MCP is not a transport of this contract.** The `mcp.vault.append_note` descriptor is an internal orchestrator descriptor (`docs/settings/tools/mcp.vault.append_note.yaml`), not an externally callable endpoint; no MCP server exists in `app/`, and the MCP topology stance is owner-deferred (ADR-0047). This contract does not reopen that deferral. Mode (d) MCP/RBAC attachment remains future work.

## 3. Authority envelope — the three hard invariants

Every client, both families, both transports:

1. **Never semantic authority.** The client never decides what a vault note means, never owns a Core-6 field, and never treats its own output as human-canonical. Client output enters at the zone posture of where it lands (AGENT-FLOWS §7); promotion to human-canonical knowledge is a human act through the trust path (`docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`).
2. **Every durable mutation stays inside a named transport.** There are exactly two: the governed API path (§4) and the direct-filesystem path (§5). No bespoke side channels, no client-invented write mechanisms, no local write queue that replays into the vault without the human.
3. **Never a hidden source of truth.** No client-local store may hold meaning that the vault + companion set cannot rebuild (`docs/INTEGRATION_FABRIC_CONTRACT.md` authority rule). Client caches are opaque external durability: rebuildable, never written back as authority.

How each transport stays inside the envelope:

- **API transport — safe by construction.** The capture endpoint runs the full governed chain (WriteGuard → DecisionToken → deterministic append → AuthorityReceipt → outbox event; §4.1), so invariants hold mechanically: the write is admissible before mutation and accountable after it.
- **Filesystem transport — safe by discipline plus observation.** The filesystem cannot enforce governance, and Mimer does not pretend it can (AGENT-FLOWS §12). The envelope holds through the client discipline of §6, the zone/exclusion rules of §5, and Mimer's post-hoc observation: the watcher ingests the changed file (mtime + sha256, `app/watcher/watcher.py`), classifies it by zone and provenance, and the result stays non-canonical until the human promotes it. A blocked or failed governed API write must never be re-routed as a direct filesystem write — that is a governance bypass, not a degradation.

## 4. Callable HTTP surface (v1, shipped)

Base URL: the Mimer runtime API (`app/api/app.py`). All routes below exist on `main` today. Trace correlation: send `x-trace-id` on every call; the runtime's TraceIdMiddleware propagates it into spans, receipts, and events.

**v1 auth posture (owner ruling):** LAN/loopback-only. The client-facing routes below carry no auth dependency today; `X-API-Key` machinery exists (`app/auth.py`) but is applied to only three routes in `companion.py`. A client under this contract MUST refuse to operate against a Mimer host that is not loopback, LAN, or tailnet (`docs/SECURITY_TRUST_BOUNDARIES.md`). Per-agent identity/keys is the named first hardening slice (§9 F2), not a v1 blocker.

| Operation | Method + path | Purpose | Provenance/trace | Governance |
| --- | --- | --- | --- | --- |
| Capture (write) | `POST /api/companion/capture` | Friction-free intake into the vault inbox note | `x-trace-id`; actor currently fixed (§9 F1) | Full governed chain (§4.1) |
| Retrieve | `GET /search?q=` | Hybrid retrieval over the durable index (KERNEL-05) | `x-trace-id` | Read-only |
| Ask | `POST /api/ask` | Grounded Q&A with per-source citations | `x-trace-id` | Read-only |
| Read note | `GET /api/artifacts/note?note_path=` | Fetch one note's title/body/hash by vault-relative path | `x-trace-id` | Read-only; traversal-guarded |
| Health | `GET /healthz`, `GET /readyz`, `GET /api/status`, `GET /version` | Liveness/readiness/status/build discovery | — | Read-only |

### 4.1 `POST /api/companion/capture` (the governed write)

Implementation: `app/api/routes/capture.py`. Request body is exactly `{"text": "<non-empty string>"}` — the schema is `extra="forbid"`, so any additional field (including a provenance or due-date field) is rejected with 422. The write is an append-only timestamped bullet (`- [<utc-iso>] <text>`) to the vault inbox note (`<inbox_dir_rel>/inbox.md` by convention).

Governed chain, in order: WriteGuard gate (`companion.capture.append`) → GovernedWriteAdapter issues a DecisionToken (write class `vault_capture_append`) → deterministic append via `app.knowledge.write_ops.append_note_relative` returning a runtime `WriteReceipt` → AuthorityReceipt recorded → `capture.inbox.appended` outbox event (JSONL audit log + DB outbox mirror) persisted **before** success is acknowledged.

Success response (`200`): `{outcome: "written", note_path, operation, adapter, captured_at, trace_id, events_emitted, governed_write, ingest_warning}` — `governed_write` carries the PolicyDecision, DecisionToken, and AuthorityReceipt verbatim; `ingest_warning` (nullable) is set when the write landed but downstream ingest signaling degraded — the capture is durable, the index may lag. The client MUST surface this receipt, not fabricate its own acknowledgement.

Error contract (a client must handle each named state; never retry blindly):

| Status | `error` | Meaning | Client behavior |
| --- | --- | --- | --- |
| 422 | (schema) / `empty_capture` | Extra fields, or whitespace-only text; nothing written | Fix the request; surface to human |
| 409 | `writeguard_blocked` | WriteGuard denies writes; `reason` included; nothing written | Surface reason verbatim; do NOT fall back to a direct FS write |
| 409 | `inbox_convention_unresolved` | Inbox note convention could not resolve; nothing written | Surface to human |
| — | vault-selection state (structured JSON: `{state: "vault_selection_required", reason, …}` — `reason` ∈ `vault_root_misconfigured` / `no_vault_bound` / `uninitialized`; there is no `error` field) | No active vault selected | Match on `state`, not `error`; surface; the human selects a vault; never guess a vault |
| 500 | `authority_receipt_persistence_failed`, state `not_acknowledged` | **The append may have landed** but its AuthorityReceipt could not be persisted | Do NOT blind-retry (duplicate-append risk). Verify by reading the inbox note (§6 W5) or hand to the human |

### 4.2 Read surface and the uuid→path gap

- `GET /search?q=` returns `{"results": [{uuid, title}, …]}`, fixed k=10. A retrieval failure propagates as an error — no silent filler (#2989).
- `POST /api/ask` takes `{"question": …}` (alias `query`; optional `zone_strategy`) and returns an answer with per-source attribution: each source carries `uuid, title, origin, plane, zone, path`.
- When the ASK model backend accepts a connection but fails to respond before the configured LLM timeout,
  `POST /api/ask` returns HTTP 504 with FastAPI detail
  `{error: "llm_backend_timeout", provider, timeout_seconds, trace_id, message}`. Clients must surface
  this as degraded model-provider availability, not as an empty grounded answer and not as an
  invitation to answer from client memory.
- `GET /api/artifacts/note?note_path=` reads a note **by vault-relative path** (absolute paths and traversal rejected with 400 `invalid_path`; missing note → 404 `note_not_found`). Response: `{artifact_id, note_path, title, body, content_hash}` — note the response's `note_path` is the **absolute resolved filesystem path**, not the vault-relative path the request took; clients must not echo it to other hosts or store it as a stable identifier.

**The gap, stated honestly:** search returns *uuid*; note-fetch keys by *path*; no endpoint resolves uuid→path. **v1 posture: thin read + filesystem enrichment.** A client that needs the body behind a search hit either (a) uses `/api/ask`, whose sources include `path`, or (b) resolves the uuid itself against its filesystem view of the vault (frontmatter `uuid` field). A uuid-resolving fetch or enriched search payload is follow-on work (§9 F3), not something a client may emulate by inventing a hidden uuid→path store it treats as authoritative (invariant 3: any such cache is rebuildable and disposable).

**Index-lag honesty:** the retrieval index is a rebuildable projection that trails the vault (watcher → ingest → index). A client MUST NOT present a retrieval miss as absence-of-knowledge without saying the index may lag, and MUST NOT assume read-your-write through `/search` after any write (§6 W6). The vault note outranks any projection of it (AGENT-FLOWS §10).

## 5. Direct-filesystem write transport (owner-permitted, 2026-07-07)

The owner has ruled that direct filesystem vault writes by external clients are **permitted now** — this extends the writer set that `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` governs (Mac runtime, Obsidian human, iCloud sync, Bifrost clients) with the external-app-agent class, ahead of that model's own T2/T3 enactment. Enacted via ADR-0056. Permission is not safety; §6 is the discipline that makes the permission survivable during the enactment gap.

### Where a client may write

- **Declared agent workspace roots** (AGENT-FLOWS §7) are the default write surface for app agents: drafting, synthesis, notes the client itself authors. Output lands at draft-zone standing — observed, classified, never auto-canonical.
- **Human-directed edits to any vault note** are permitted when the human directs the edit in the live session (matching ADR-0055's writer set, which does not restrict which notes the human's own session may touch). The client discipline of §6 (read-fresh, ownership courtesy, atomic replace) applies with full force here, because this is exactly the surface where a collision destroys human-authored prose — and it is exactly the "rewritten note class" ADR-0055 targets for its stale-detection + conflict-staging mechanism once enacted.
- **Bifrost shells** additionally read/write the `_heimdal/**` control surface (settings/interests/consent/attention) — that is their product surface. Its versioned client schema is [`schemas/heimdal-control-notes.schema.json`](../../schemas/heimdal-control-notes.schema.json), mechanically checked against the runtime registry in `app/heimdal/settings_notes.py`. The schema is a published contract view; the registry remains the runtime authority.

### Exclusion list — never direct-write, either family

| Surface | Why |
| --- | --- |
| The capture inbox note (`<inbox_dir_rel>/inbox.md` or `VAULT_CAPTURE_NOTE_REL` override) | It is the runtime's actively-appended governed target; a client rewrite races the governed append and LWW can silently drop a capture. Intake goes through `POST /api/companion/capture` only. |
| Companion notes (`⚙️ System/companions/`, legacy `_system/companions/`) | KnowledgePort-only, system-owned (`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`). |
| System-plane settings/bootstrap notes and other system-owned paths | Runtime-owned via KnowledgePort; a direct edit forks runtime state. |
| `_heimdal/**` — **app agents only** | It is Bifrost's/the runtime's control seam; app agents have no role there. (Bifrost writes it by design, above.) |
| iCloud "conflicted copy" artifacts | Never create, never silently resolve; surface to the human (§6 W8). |

### Provenance on direct writes (the transport's governed-write equivalent)

The filesystem does not enforce attribution (AGENT-FLOWS §4: best effort), so the client supplies it. Every file an external client **creates** in the vault MUST carry a provenance frontmatter block; every substantive edit to an existing note SHOULD append to it:

```yaml
agent_provenance:
  author: <client-id>        # e.g. claude-app, codex-app, bifrost-ios
  model: <model-id>          # where applicable
  written_at: <utc-iso>
  origin: direct-fs
  trace: <trace-id or session ref, if any>
```

This is a v1 convention owned by this contract: advisory to the runtime today (observation-time classification may read it; nothing enforces it), binding on clients now, and the input to the per-agent identity slice (§9 F2). It exists so the AGENT-FLOWS §13 questions ("who wrote this, under what delegation, into which zone") stay answerable without the runtime.

### Bifrost coordinated filesystem access

Per ADR-0055 item 5, Bifrost uses Apple's coordinated-access APIs — `NSFileCoordinator` / `UIDocument` — for vault files, not plain `FileManager` I/O. This preserves offline-first operation while cooperating with iCloud's coordination layer; it does not replace the hub's stale-detection or conflict-artifact responsibilities.

## 6. Concurrent-writer safety model

This is the load-bearing section. The writer set over one iCloud-synced vault is now: the Mac runtime, the human in Obsidian, Bifrost shells, and external app agents — plus iCloud sync as a transport that can materialize conflicts as files.

### Substrate guarantee, stated honestly

**Decided, runtime mechanism not yet enacted.** `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (Accepted 2026-07-07, supersedes ADR-0053, resolves #3114) is the owner's ruling on the full multi-writer model: atomic writes everywhere; stale-detection + detect-and-stage conflict artifacts for **rewritten note classes**; last-write-wins retained for **append-only classes**; iCloud conflicted-copy quarantine at ingest; writer-identity/timestamp provenance tagging; enforcement at GATE tier via `WriteGuard`, generalized to also cover `append_note_relative` (closing INV-VW2). The schema and classification contract are published below; the runtime mechanism remains #3132 feature work, and the `append_note_relative` guard repair remains #3129.

### Note-classification contract (ADR-0055 item 6)

All writers consume this table; individual runtime code must not create a competing class mapping. `rewritten` means atomic replace plus the stale-detection/conflict-staging mechanism when #3132 lands. `append-only` means atomic append with no stale check; `create-once` is the Sources-zone variant, where a re-derivation creates a new note rather than rewriting the original.

| Path / note pattern | Class | Contract posture |
| --- | --- | --- |
| `_heimdal/**` (except the explicit append-only rows below) | rewritten | Control notes use the published schema; stale detection and conflict staging apply when enacted. |
| `_heimdal/steering.log.md` | append-only | Immutable steering entries append through the governed append seam. |
| human-authored Markdown outside managed append-only zones | rewritten | Preserve human prose; never silently overwrite a stale version. |
| `⚙️ System/companions/**`, legacy `_system/companions/**` | rewritten | Runtime-owned companion notes; direct client writes remain forbidden. |
| `<inbox_dir_rel>/inbox.md` | append-only | Governed capture endpoint only; direct filesystem writes are forbidden. |
| event-log producer paths | append-only | Append-only event history; no rewritten-note stale check. |
| `Sources/**` (settings-resolved default root) | append-only / create-once | Sensor/acquisition writers create material notes; re-derivation makes a new note, never a silent rewrite. |
| Episode notes (the Episode Note Store's materialized Markdown) | rewritten | Re-cut/re-time and human edits, including `closed`, require rewritten-note protection. |

Until that enactment lands, today's runtime substrate is unchanged from what ADR-0053 described: concurrent writes to the same vault note resolve as **silent last-write-wins**. The general write primitive is a blind in-place overwrite with no stale check (`app/knowledge/adapters.py:29-40`); compare-and-swap exists only in the panel-watcher family (`OptimisticWriteGuard`, `app/components/concurrency.py:118-131`); `append_note_relative` does not itself assert the WriteGuard (audit INV-VW2); iCloud conflicted copies are ingested as ordinary notes (INV-VW3 absent).

Therefore: the rules below are **client discipline that shrinks the collision window and makes collisions detectable and attributable during the enactment gap — they do not eliminate LWW today** and they implement no INV-VW1/VW2/VW3 enforcement themselves. They are **binding on external app agents** (the writer class this contract admits) and **recommended for Bifrost during B1** (ADR-0053's "B1 is unconstrained" ruling, carried forward by ADR-0055, governs Bifrost until enactment lands). When ADR-0055's mechanism ships, it becomes binding for all writers over the rewritten-note classes, including this one — at that point this section's discipline becomes a client-side complement to real enforcement rather than the only mitigation.

### Client write discipline (normative)

- **W1 — Prefer governed append for durable intake.** Anything shaped like "remember/capture this" goes through `POST /api/companion/capture`. Appends through one governed writer serialize at the runtime and carry receipts; they are the lowest-risk durable write in the system.
- **W2 — Read-fresh, write-promptly, verify-staleness.** Before any whole-file write: read the file and record its content hash; keep the read→write window as short as possible; immediately before writing, re-check the hash. If the file changed since the read, re-read and re-apply the edit on the new content — never write the stale version. This mirrors `OptimisticWriteGuard.write_if_unchanged` semantics client-side, anticipating the stale-check ADR-0055 decided for rewritten classes. It is advisory, not atomic — the TOCTOU window is real and is exactly the residual risk that persists until ADR-0055's mechanism is enacted.
- **W3 — Ownership courtesy.** Default to creating and editing files the client itself authored (workspace roots, §5). Edit a human-authored note only on explicit human direction in the live session, and prefer append/patch-shaped edits over whole-file rewrites of prose the human may have open in Obsidian.
- **W4 — Atomic replace.** Whole-file writes land as write-to-temp-then-rename within the same directory, so the watcher and other readers never observe a half-written note. Never leave temp files in the vault on failure.
- **W5 — Idempotency by verification, not by retry.** No client-supplied idempotency key exists on the capture endpoint today (the runtime derives an idempotency key for the outbox *event*, not the write — §9 F5). So: after `not_acknowledged` (500) or a transport timeout where the response was lost, the write may have landed. Verify by reading the target (the inbox note tail for captures; the file content for FS writes) before any retry. Direct FS whole-file writes are idempotent by content (re-applying the identical content is safe); appends are not — check for the marker/timestamp line before re-appending.
- **W6 — Write-ordering vs the watcher.** The watcher detects changes by mtime + sha256 and feeds ingest; the index trails the file. After a write, the file is truth and the index is eventually consistent. Never re-write a file to "fix" perceived index lag, and never treat index state as evidence the write failed.
- **W7 — One transport per note; reconciling FS vs API writes.** The only note both transports touch by design is excluded from FS writes (the capture inbox, §5), so a governed API write and a direct FS write to the same note should not occur under this contract. If a client nevertheless observes it caused such a collision (e.g. it rewrote a note between another writer's read and write), the reconciliation is: the file's current content is the outcome (LWW), the AuthorityReceipt/outbox event remains the truthful record of *what the governed write did at its time*, and the client surfaces the suspected collision to the human rather than silently re-asserting its own version. Receipts are authoritative for what happened, never for what is currently true (AGENT-FLOWS §10).
- **W8 — iCloud conflict artifacts.** If a client encounters a `… (conflicted copy …)` sibling, it must not merge, delete, or adopt it silently: surface it to the human. Detection/quarantine at ingest is ADR-0055 item 3 enactment work (INV-VW3) — not yet landed.

### Failure modes and degradation (both transports)

| Condition | Client behavior |
| --- | --- |
| API unreachable | Degrade to read-only over the declared filesystem roots (if granted) and say so. No shadow write queue that replays later without the human (invariant 3: hidden truth in transit). |
| WriteGuard blocked / vault unselected | Surface the structured reason verbatim. Never fall back from a blocked governed write to a direct FS write (invariant 2). |
| `not_acknowledged` (500) | Treat as "written-but-unaccounted": verify by read (W5); no blind retry. |
| Retrieval/ask failure | Propagate; never answer from client memory while claiming vault grounding. |
| Suspected same-note collision | Report to the human with both versions' evidence; do not silently re-write (W7). |
| Filesystem access absent | Operate API-only; the contract's API surface is sufficient for capture/retrieve/ask. |

## 7. Health and observability duties

- Check `GET /healthz` (or `/api/status`) before entering a write flow; use `GET /version` to record which runtime build served a session when reporting anomalies.
- Send `x-trace-id` on every call and log it client-side, so a capture, its receipt, and its outbox event are joinable across the seam.
- Surface — verbatim, to the human — every named error state in §4.1. Degradation must be legible (`docs/INTEGRATION_FABRIC_CONTRACT.md` health field): a client that silently absorbs `writeguard_blocked` or `not_acknowledged` violates this contract.
- Direct FS writes have no runtime receipt; the client's own log plus the provenance block (§5) is the audit trail until ADR-0055's item 4 (writer provenance) enactment lands at the substrate.

## 8. Integration-fabric contract fields

Answers per `docs/INTEGRATION_FABRIC_CONTRACT.md` §Contract fields.

### External app agent (Agent runtime, class 10; + External UI shell, class 8, when rendering)

| Field | Answer |
| --- | --- |
| Allowed role | Capability + interface: retrieve/ask over indexed material; governed capture to the vault inbox; drafting/synthesis via direct FS in workspace roots; human-directed note edits; relaying human intent (UI control-action boundary #2475 — transport of intent, no approval loop). |
| Authority limits | The three invariants (§3); plus: no promotion, no lifecycle/frontmatter mutation of human notes beyond human-directed edits, no companion/system-plane/`_heimdal` writes, no capture-inbox FS writes, no runtime-settings mutation. |
| Persistence class | Durable human meaning: only via governed capture or observed workspace/human-directed Markdown at its zone standing. Runtime projection: none owned. External durability (agent memory/caches): opaque, rebuildable, never authoritative. |
| Provenance requirement | `x-trace-id` on every API call; provenance frontmatter block on created files (§5); per-request agent identity is F1/F2 follow-on — until then the capture actor is fixed at `companion.capture` and API-side attribution is honestly weak. |
| Event boundary | API side effects cross via the runtime's outbox events (`capture.inbox.appended` with DecisionToken/AuthorityReceipt ids). FS side effects cross via watcher ingest (mtime + sha256), classified at observation time. No bespoke side channels. |
| Health / observability | §7 duties; failures degrade legibly per §6's table. |
| Replacement strategy | The coupling is this contract's HTTP calls + Markdown-in-vault. Any HTTP-capable agent attaches by implementing the same calls; removing an agent loses no meaning (nothing authoritative lives client-side). Its workspace files remain plain Markdown in the vault. |

### Bifrost native shell (External UI shell, class 8; participates in Human surface, class 1)

| Field | Answer |
| --- | --- |
| Allowed role | Interface: render Mimer/Heimdal surfaces; capture/review/steer/confirm hot paths; read/write vault notes incl. `_heimdal/**` control notes (design-of-record: `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md`). |
| Authority limits | The three invariants (§3); the shell is the runtime container, not the human — it transports the human's actions and never originates authority. No journey becomes app-only (topology doc): Obsidian + the notes alone must remain sufficient. |
| Persistence class | None inside Mimer beyond vault Markdown written on the human's behalf; shell-local state is opaque and rebuildable. |
| Provenance requirement | `x-trace-id` on API calls; provenance block on created notes (§5); per-device identity is F2 follow-on (audit: "no per-device identity/session model"). |
| Event boundary | HTTP API + watcher ingest, as above. |
| Health / observability | §7; additionally B1 cites ADR-0055, not a client-side invention, as its consistency posture. |
| Replacement strategy | Delete the app, lose nothing: vault + companion set rebuild everything; the contract surface lets a successor shell attach without hub changes. |

## 9. Runtime gaps — feature-breakdown inputs (deferred, not solved here)

Named follow-on work; each routes through `feature-breakdown`/`docs-to-issue`, none blocks v1 clients operating under the postures above:

- **F1 — Capture provenance field + per-agent actor.** The capture schema is `{text}` with `extra="forbid"`; the actor is hardcoded `companion.capture`, so a Claude-app capture and a Bifrost capture are indistinguishable in DecisionToken/AuthorityReceipt/event. Add an optional provenance object to the schema and thread it through the governed chain.
- **F2 — Auth coverage + per-agent/per-device identity (first hardening slice).** Apply the existing `X-API-Key` machinery to the four client routes and introduce per-client identity/keys; serves both families (and Bifrost B1's remote posture). Owner-ruled as the first hardening slice, not a v1 blocker.
- **F3 — uuid-resolving note fetch or enriched search payload.** Close the §4.2 uuid→path gap at the API instead of by client-side filesystem enrichment.
- **F4 — API versioning + published OpenAPI for the client surface.** The hub API is unversioned and `api/openapi.yaml` documents 2 of 23+ route modules (audit §3; the surface is still growing); a client-publishable contract needs both.
- **F5 — Client-visible idempotency key on capture.** Lets a client retry safely after `not_acknowledged`/timeout instead of verify-by-read (§6 W5).
- **F6 — Full multi-writer consistency model: enactment.** The decision itself is made — `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (Accepted 2026-07-07) resolves #3114 and gates B2 (#3024). What remains is **T2/T3 enactment**: the note-class classification table, closing INV-VW2 (`append_note_relative` WriteGuard coverage), the INV-VW1 stale-check generalization, INV-VW3 conflict-copy handling, and writer provenance at the substrate. This contract's §6 discipline is the interim client-side complement to today's unenacted mechanism, not a substitute for it.
- **F7 — `_heimdal/**` published note-shape schema (audit G3): delivered by #3131.** [`schemas/heimdal-control-notes.schema.json`](../../schemas/heimdal-control-notes.schema.json) publishes the registry's note kinds, paths, authorities, sections, and field-authority split. `tests/heimdal/test_published_control_surface_schema.py` prevents drift from `settings_notes.py`; schema-version evolution remains a future contract change, not a silent runtime edit.

## 10. SBS reconciliation

Per the repo's architecture-artifact convention (binding classification against the operating model and owner docs):

| Claim | Class | Basis |
| --- | --- | --- |
| One hub contract answering per-class fields for a multi-class integration | **Conform** | `docs/INTEGRATION_FABRIC_CONTRACT.md` multi-class precedent (Obsidian) and contract fields answered as required |
| Governed API write chain as described (§4.1) | **Conform** | Restates shipped behavior (`app/api/routes/capture.py`); GOV invariants per `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` |
| Direct-FS participation as mode (c) with observed-write semantics | **Conform** | `docs/AGENT-FLOWS.md` §3/§4/§7 already define the mode; this contract binds clients to it |
| Admitting external app agents to the live writer set | **Extend** | Owner ruling 2026-07-07, enacted via ADR-0056; extends the writer set ADR-0055 governs (supersedes ADR-0053) to a new writer class, ahead of that model's own T2/T3 enactment |
| Client write discipline W1–W8 | **Extend** | New client-side obligations; introduces no runtime mechanism, forks no `GOVERNED_WRITE_PROTOCOL`/`OBSIDIAN_KNOWLEDGE_PORT` semantics, and defers to ADR-0055's enactment for real enforcement |
| Provenance frontmatter convention (§5) | **Extend** | New convention on a surface AGENT-FLOWS §4 names as best-effort; advisory to the runtime until F1/F2 land, anticipates ADR-0055 item 4 |
| MCP-transport assumption retired for clients | **Conform** | ADR-0047 (deferred stance) and the audit's A2-class finding; no stance is reopened |

No reshape: no existing boundary, charter, contract, or ADR is altered. The one authority-affecting change (new writer class) is routed through ADR-0056 as required.

## 11. References

- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md` — the enacting decision (T2 closure, transport set, writer-set extension).
- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` — the decided multi-writer mechanism (supersedes ADR-0053, resolves #3114); T2/T3 enactment tracked there.
- `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2/§3/§9/§10/§11 — evidence base (G1–G7, T1–T6, INV-VW1..3).
- `docs/INTEGRATION_FABRIC_CONTRACT.md` — class taxonomy, contract fields, authority rule.
- `docs/AGENT-FLOWS.md` §3/§4/§7/§10/§12/§13 — participation modes, observed writes, zones, provenance rules.
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`, `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` — the write machinery this contract rides.
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`, ADR-0047 — why MCP is not a client transport today.
- `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` — Bifrost topology design-of-record; Epic B #3020, B1 #3023/`bifrost#1`; ADR-0050.
- `app/api/routes/{capture,search,ask,artifacts}.py`, `app/auth.py`, `app/knowledge/{adapters,write_ops}.py`, `app/components/concurrency.py`, `app/watcher/watcher.py` — implementation evidence (descriptive, not normative; `docs/ARCHITECTURE.md` owns runtime truth).
