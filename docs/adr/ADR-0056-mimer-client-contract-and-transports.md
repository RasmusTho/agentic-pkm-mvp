State: Accepted (owner decisions, 2026-07-07). Enacts the single hub Mimer client contract (`docs/contracts/MIMER_CLIENT_CONTRACT.md`), fixes the client transport set at HTTP API + direct filesystem (not MCP), and admits external app agents to the live vault writer set that ADR-0055 governs. Closes the ecosystem audit's remaining T2 work.
Doc role: Decision record (ADR)
Authority: Authoritative for (a) the existence and location of the one hub client contract serving both client families, (b) the client transport decision (HTTP API + direct FS; MCP remains deferred per ADR-0047), and (c) the writer-set extension: direct filesystem vault writes by external app agents are permitted now, governed by the client contract's concurrency discipline. It does NOT design the multi-writer consistency mechanism — ADR-0055 (Accepted 2026-07-07, supersedes ADR-0053) already made that decision and resolved #3114; this ADR only adds external app agents as a writer class to ADR-0055's model, ahead of that model's own T2/T3 enactment — and it does not reopen the MCP topology deferral (ADR-0047).
Owner: Architecture (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the contract is split per client family, a new client transport is admitted, or the writer-set ruling is reversed; ADR-0055's T2/T3 enactment refines the consistency substrate underneath without superseding this record).
Source of truth: This ADR + `docs/contracts/MIMER_CLIENT_CONTRACT.md` + ADR-0055 (supersedes ADR-0053) + `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §3/§10/§11.

# ADR-0056: One hub Mimer client contract; HTTP-API + direct-FS transports; external app agents join the writer set

**Date:** 2026-07-07
**Status:** Accepted (owner decisions, 2026-07-07)

---

## Context

The 2026-07-06 ecosystem audit found that the "Mimer client contract" named by Epic B #3020 / #3023 / `bifrost#1` **did not exist as an artifact** (G2; invariant INV-CB1 violated), with the design-of-record living uncommitted on the operator's Desktop. The owner's same-day rulings (audit §11) committed the topology design-of-record (`docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md`) and interim-accepted the multi-writer question (ADR-0053: silent last-write-wins for the B1 wave; full model booked at #3114 before B2) — but the machine-facing client contract itself remained the open half of T2.

Between this ADR's drafting and its landing, the owner made the full multi-writer decision separately: **ADR-0055** (Accepted 2026-07-07) resolves #3114 and supersedes ADR-0053. It decides atomic writes everywhere, stale-detection + detect-and-stage conflict artifacts for rewritten note classes (human prose, `_heimdal/**`, companion notes), last-write-wins retained for append-only classes, writer-identity/timestamp provenance tagging, and GATE-tier enforcement via `WriteGuard`. ADR-0055 is explicit that it is the *decision*, not the *mechanism*: enactment (schema/contract materialization, the `append_note_relative` WriteGuard gap, stale-check generalization) is separate downstream work (T2/T3) that has not shipped yet. ADR-0055's enumerated writer set is Mac runtime, human via Obsidian, iCloud sync, and Bifrost clients — it does not itself name external app agents.

In parallel, the Workstream B design pass (app-agent skill family for Claude app / Codex app) established that the brief's assumed write transport — `mcp.vault.append_note` — is not externally callable: it is an internal orchestrator descriptor (`docs/settings/tools/mcp.vault.append_note.yaml`); no MCP server exists in `app/`; and the MCP topology stance is owner-deferred (ADR-0047, decision D4). What an external client can actually reach is the FastAPI runtime — with `POST /api/companion/capture` as a complete governed-write chain (WriteGuard → DecisionToken → deterministic append → AuthorityReceipt → outbox event) — plus, under mode (c) of `docs/AGENT-FLOWS.md`, the vault filesystem itself.

Three questions therefore needed one owner decision each: where the client contract lives (one doc or two), which transports it contracts, and whether external app agents may write the vault directly now or only after ADR-0055's mechanism ships.

## Decision (owner, locked 2026-07-07)

### 1. One hub client contract — T2 closed

`docs/contracts/MIMER_CLIENT_CONTRACT.md` is the single canonical client contract, serving **both** client families: Bifrost native shells (Epic B) and external app agents (Claude app / Codex app and peers). The seams overlap almost entirely (same HTTP API, same vault, same invariants, same auth gap), so one artifact with per-family field answers is chosen over two documents that would have to be kept coherent. This closes the audit's remaining T2 work: "Mimer client contract" now greps to a committed hub file, and `bifrost#1`/#3023 Source Anchors can resolve to it. (The `_heimdal/**` note-shape schema, audit G3, remains named follow-on work inside the contract, not silently claimed.)

### 2. Client transports are HTTP API + direct filesystem — not MCP

The contracted transports are:

- the **governed HTTP API** (`POST /api/companion/capture` for durable intake; `GET /search`, `POST /api/ask`, `GET /api/artifacts/note` for reads; health/status/version for discovery), and
- the **direct filesystem path** under `docs/AGENT-FLOWS.md` mode (c) observed-write semantics.

This **supersedes the working assumption** (SKILLS_REVIEW_BRIEF, Workstream B) that app-agent capture would ride `mcp.vault.append_note`: that descriptor is internal, and per ADR-0047 the MCP topology stance stays deferred until a real MCP server/attachment is on the table. This ADR does not reopen ADR-0047; if MCP is later ratified, it attaches as an additional adapter under the same contract, not as a replacement authority path.

### 3. External app agents join the live writer set — writes permitted now, made safe by contract

Direct filesystem vault writes by external app agents are **permitted now**, not deferred behind ADR-0055's enactment. This resolves the write-transport question the audit's T1 line left for the client side ("owner decision T1 gates any client direct-file write posture") in the direction of *permitted*, and it extends ADR-0055's writer set (Mac runtime, Obsidian human, iCloud sync, Bifrost clients) by one class it does not itself enumerate. The decided model applies once enacted: rewritten-note-class writes by app agents (human prose, `_heimdal/**`) get the same atomic-write + stale-detection + conflict-staging treatment ADR-0055 decided for every other writer in that class — no separate mechanism is carved out for this class. Until that enactment ships, the runtime substrate is still today's blind overwrite (`app/knowledge/adapters.py:29-40` for rewritten classes; CAS only in the panel-watcher family, `app/components/concurrency.py:118-131`).

What makes the permission survivable during the enactment gap is the client contract's concurrency model (`MIMER_CLIENT_CONTRACT.md` §6): governed-append preference, read-fresh/verify-staleness before whole-file writes, ownership courtesy, atomic replace, verify-before-retry idempotency, watcher-ordering rules, a per-note transport exclusion list (capture inbox, companions, system plane, `_heimdal/**` for app agents), provenance frontmatter on direct writes, and conflict-copy surfacing. That discipline is **binding on external app agents** and **recommended for Bifrost during B1** (**amended 2026-07-11, owner ruling:** ADR-0055 superseded ADR-0053 *in full*, so the "B1 is unconstrained" ruling is *not* carried forward by it. Instead the owner has explicitly **extended the B1 free pass for the enactment gap**, with two stop conditions — the pass ends and the posture is re-decided (a) *before* the mechanical-hygiene auto-apply flip turns on (ADR-0048 / GRADUATED_CURATION G2-3, which adds an agent writer to the same rewritten-note surfaces), and (b) *immediately* on the first observed same-note data-loss incident); it shrinks and instruments the collision window during the gap between this permission and ADR-0055's mechanism landing — it does not implement ADR-0055's mechanism itself.

### 4. v1 auth posture: LAN/loopback-only; identity is the first hardening slice

Clients operate only against loopback/LAN/tailnet Mimer hosts. Per-agent/per-device identity and key coverage on the client routes is the **named first hardening slice** (contract §9 F2) — required before any posture beyond trusted-LAN, but not a v1 blocker.

## Constraints honored

- Decision record + docs only — no code, schema, or runtime change; the governed-write chain and route behavior are restated from shipped code, not modified.
- ADR-0055 is extended in writer-set scope, not contradicted: its decided mechanism, its note-class differentiation, and its T2/T3 enactment sequencing all stand. ADR-0047's MCP deferral stands.
- SBS reconciliation is carried in the contract (§10): conform/extend classifications per claim; the one authority-affecting change (new writer class) is routed through this ADR; no reshape of any existing boundary or contract.
- The three integration-fabric hard invariants (never semantic authority, no governance bypass, no hidden source of truth) bind both transports; a blocked governed write may never degrade into a direct FS write.
- Runtime gaps are named as feature-breakdown inputs (contract §9 F1–F7), not claimed solved: capture provenance field, per-agent identity/auth, uuid-resolving fetch, API versioning/OpenAPI, capture idempotency key, ADR-0055's T2/T3 enactment, `_heimdal/**` schema.

## Consequences

- Epic B's B2/B3 and the Workstream B skill family now have a committed contract to verify against; the app-agent skills remain a later, separately gated step that sits on this artifact.
- A fourth writer class is live over the shared vault ahead of ADR-0055's mechanism landing. The risk is the same one ADR-0055 is designed to close — silent LWW on same-note collision for rewritten classes — now with client discipline and provenance conventions that make collisions rarer, detectable, and attributable in the meantime. A data-loss incident during the gap forces the §3 stop condition (amended 2026-07-11): the B1 free pass ends and the write posture is re-decided immediately — alongside prioritizing ADR-0055's T2/T3 enactment.
- The `mcp.vault.append_note`-as-client-transport assumption is retired; any doc or brief still carrying it should be read as superseded by this ADR.
- Follow-on backlog extraction (contract §9 F1–F7) routes through `feature-breakdown`/`docs-to-issue`; this ADR files no issues itself.

## When to revisit

Supersede only if the owner splits the contract per client family, admits a new client transport (e.g. a ratified MCP attachment under a revisited ADR-0047), or reverses the external-agent write permission. When ADR-0055's T2/T3 enactment lands, update the contract's §6 substrate description and binding scope rather than superseding this record.

## References

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` — the enacted contract (this ADR's design content lives there).
- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` — the decided multi-writer mechanism (supersedes ADR-0053, resolves #3114); T2/T3 enactment tracked there. Epic B **#3020**, B1 **#3023** / `bifrost#1`, B2 **#3024**.
- `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §3 (G2/G3, INV-CB1), §10 (T1/T2), §11 (owner rulings 2026-07-06).
- ADR-0047 (MCP topology deferred); ADR-0044 (constituent model — Mimer is the shipped system this contract fronts); ADR-0050 (Bifrost repo + cross-repo governance); ADR-0019 + `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` (DecisionToken/AuthorityReceipt).
- `docs/AGENT-FLOWS.md` §3/§4/§7 (mode c, observed writes, zones); `docs/INTEGRATION_FABRIC_CONTRACT.md` (classes 1/8/10, contract fields, authority rule).
- `app/api/routes/capture.py` (governed chain), `app/orchestrator/mcp_tool_provider.py` + `docs/settings/tools/mcp.vault.append_note.yaml` (why MCP is not a transport), `app/knowledge/adapters.py:29-40` / `app/components/concurrency.py:118-131` (substrate reality, pending ADR-0055 enactment).
