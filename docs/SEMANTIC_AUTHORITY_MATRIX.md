State: SoT v5.5 baseline locked; target-state semantic framing. This document defines authority semantics; it does not claim every flag is enforced by current runtime code.
Doc role: Core SoT
Authority: Semantic authority matrix. Owns the per-entity authority semantics under Layer 4 (Governance/Authority) of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`: for every major artifact class, runtime structure, and machine mirror, whether it is authoritative, rebuildable, temporary, machine-derived, governance-owned, human-editable, runtime-only, proposal-bearing, receipt-bearing, retrieval-visible, activatable, instructional, and action-authorizing. Consolidates existing authority semantics; it does not redefine the owner contracts (trust tiers, activation use-rights, receipts, mirrors).
Owner: Semantic authority matrix
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md, docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md, docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md, docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md, epic #1363, issue #1365.

# Semantic Authority Matrix

This document is the per-entity authority detail for **Layer 4 (Governance/Authority)** of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`. Where the semantic map's authority topology assigns each object an authority *role*, this matrix states the concrete authority *flags* for every major semantic object.

It is a consolidation, not a new authority. Each flag's authoritative definition lives in an owner doc (named in the column legend); where a cell summarizes that owner, the owner wins on conflict and this matrix is updated to match.

## Reading rules (load-bearing)

These rules from the owner contracts bind every row below. The matrix is read **through** them, not around them:

1. **Existence is not permission.** An object existing grants nothing beyond visibility; every higher right is earned (owner: `CONTEXT_ACTIVATION_SEMANTICS.md` §3).
2. **Authority is never gained except through an explicit governance transition.** No derived/runtime/proposal/projection object becomes authoritative by silent persistence (owner: semantic map authority topology).
3. **Unreviewed memory must never become hidden authority.** A `candidate`/`unreviewed` agentic memory artifact may never hold `activatable`/`instructional`/`action_authorizing`, regardless of any other signal (owner: `CONTEXT_ACTIVATION_SEMANTICS.md` §7). Categorical.
4. **Machine mirrors carry the authority of their source, never their own.** Retrievability of a mirror grants no right the source lacks (owner: `HUMAN_AND_AGENTIC_ARTIFACTS.md` §6).
5. **The stricter boundary wins** when a flag is ambiguous or unknown (owner: `LAYERING_MODEL.md` rule 7).
6. **Lifecycle state is not authority**, and **trust tier (`assert`/`suggest`/`apply`) gates writes independently** (owners: `CONTEXT_ACTIVATION_SEMANTICS.md` §3, `TRUST_SEMANTICS_CONTRACT.md`).

## Flag legend

| Flag | Meaning | Column owner |
| --- | --- | --- |
| **authoritative** | Can be a durable source of truth | semantic map authority topology |
| **rebuildable** | Can be fully reconstructed from higher-authority sources if lost | `HUMAN_AND_AGENTIC_ARTIFACTS.md` §6/§8 |
| **temporary** | Runtime-only; non-durable unless explicitly persisted under contract | semantic map Layer 5 / #1369 |
| **machine-derived** | Produced by the system rather than authored by the human | `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` |
| **governance-owned** | Admissibility/mutation owned by the governance layer | `TRUST_SEMANTICS_CONTRACT.md`, #1371 |
| **human-editable** | The human may open and correct it, and the correction is respected | `HUMAN_AND_AGENTIC_ARTIFACTS.md` |
| **runtime-only** | Has no durable form by design | semantic map Layer 5 |
| **proposal-bearing** | Is, or stages, a not-yet-applied change | `CONTEXT_BUNDLE_CONTRACT.md`, #1371 |
| **receipt-bearing** | Is, or carries, a governance-recorded receipt | `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` |
| **retrieval-visible** | May appear in retrieval/search results | `CONTEXT_ACTIVATION_SEMANTICS.md` §4.2 |
| **activatable** | May enter an agent's working context | `CONTEXT_ACTIVATION_SEMANTICS.md` §4.3 |
| **instructional** | May influence how the agent reasons/behaves | `CONTEXT_ACTIVATION_SEMANTICS.md` §4.4 |
| **action-authorizing** | May justify a system action (write/notify/call) | `CONTEXT_ACTIVATION_SEMANTICS.md` §4.5 |

Cell values: **Y** = yes by default · **N** = no · **cond** = conditional (see notes) · **never** = categorically prohibited · **n/a** = not applicable to this entity · **sys** = system-only (not human-browse).

## Matrix A — durability and ownership

| Entity | authoritative | rebuildable | temporary | machine-derived | governance-owned | human-editable |
| --- | --- | --- | --- | --- | --- | --- |
| Human Knowledge Artifact | Y | N | N | N | N¹ | Y |
| Companion Note | Y² | N | N | N | partial | Y |
| Agentic Memory Artifact | N³ | N | N | partial | cond⁴ | Y |
| Machine Mirror Artifact | N | Y | N | Y | N | N |
| DB representation | N | Y | N | Y | N | N |
| Embedding / vector index | N | Y | N | Y | N | N |
| Runtime session | N | N | Y | Y | N | N |
| Workspace state | N | cond⁵ | Y | Y | N | N |
| Proposal | N | N | Y | cond⁶ | Y | cond⁶ |
| Receipt | Y⁷ | N | N | Y | Y | N⁸ |
| Session log | cond⁹ | N | cond⁹ | Y | partial | N |
| Context bundle | N | Y | Y | Y | cond¹⁰ | N |
| Panel state | N | N | Y | Y | N | N |
| Retrieval cache | N | Y | Y | Y | N | N |
| Governance object | Y¹¹ | N | N | N | Y | Y¹¹ |

## Matrix B — staging, accountability, and use rights

| Entity | runtime-only | proposal-bearing | receipt-bearing | retrieval-visible | activatable | instructional | action-authorizing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Human Knowledge Artifact | N | N | N | Y | cond | cond | cond¹² |
| Companion Note | N | N | cond | sys | n/a | never | never |
| Agentic Memory Artifact | N | cond³ | N | Y | cond³ | cond³ | cond³ |
| Machine Mirror Artifact | N | N | N | sys | n/a | never | never |
| DB representation | N | N | N | sys | n/a | never | never |
| Embedding / vector index | N | N | N | sys | n/a | never | never |
| Runtime session | Y | N | N | N | n/a | N | N |
| Workspace state | Y | N | N | N | n/a | never | never |
| Proposal | Y | Y | cond⁶ | cond | N | N | N¹³ |
| Receipt | N | N | Y | cond | N | N | cond¹⁴ |
| Session log | cond⁹ | N | cond | cond | N | never | never |
| Context bundle | Y | cond¹⁰ | Y | cond | special¹⁰ | via-flags¹⁰ | via-flags¹⁰ |
| Panel state | Y | N | N | N | n/a | never | never |
| Retrieval cache | Y | N | N | sys | n/a | never | never |
| Governance object | N | N | cond | cond | n/a | cond¹¹ | Y¹¹ |

### Notes

1. Human knowledge is owned by the human, not governance; governance *gates system writes to it* (WriteGuard, APPLY, trust tier) but does not own its meaning.
2. The companion note is a first-class durable system artifact (continuity/repair), **not** a cache or rebuildable projection (owner: `COMPANION_NOTE_CONTRACT.md`).
3. Agentic memory authority is entirely gated by `review_state`: `unreviewed`→retrievable only; `reviewed`→activatable; `accepted`→instructional and conditionally action-authorizing for `policy_memory`/`preference_memory` (owner: `CONTEXT_ACTIVATION_SEMANTICS.md` §7.3). A `candidate` is proposal-like for review but is not a governance proposal object.
4. Agentic memory becomes governance-relevant at the review/promotion gate; before review it is supporting material only.
5. Workspace state is reconstructable from the durable surface + session inputs, but it is not a contracted rebuild target like a DB mirror; treat as discardable.
6. A proposal may be agent- or human-authored; it is editable while staged and gains a linked receipt only upon application (owner: #1371 follow-up).
7. Receipts are authoritative within their recorded scope: they durably record what happened, with what authority, with what result (owner: `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`).
8. Receipts are append-only accountability records; they are not human-edited after creation (correction is a new record, not a mutation).
9. Session logs span a range: a canvas-session co-authoring log is a durable provenance artifact; an ephemeral runtime trace is discardable. Classify per `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` (receipt vs trace).
10. A context bundle's authority is governed by its `authority_flags` (`may_answer`/`may_orient`/`may_resurface`/`may_propose`/`may_write`), not by the use rights of its constituents. `may_write: true` is **necessary, not sufficient** — WriteGuard, policy, and human confirmation still run (owner: `CONTEXT_BUNDLE_CONTRACT.md`, `CONTEXT_ACTIVATION_SEMANTICS.md` §8). A bundle *is* an activation artifact, so `activatable` is "special" rather than a standard use right.
11. Governance objects (policy profiles, write guards, action-catalog entries, `policy_memory`) are authoritative *within governance scope*, human-editable as config-as-product, and action-authorizing by design (owners: `TRUST_SEMANTICS_CONTRACT.md`, `CONFIG_AS_PRODUCT_CONTRACT.md`, `NOTE_KIND_POLICIES.md`).
12. Human knowledge is action-authorizing only for explicit, stable, authoritative artifacts — decision records, permission grants, policy notes — not for ordinary notes/drafts/stale artifacts (owner: `CONTEXT_ACTIVATION_SEMANTICS.md` §4.5).
13. A proposal does not authorize action *as a proposal*; it authorizes only after a governance transition applies it, at which point the authorizing record is the resulting receipt.
14. A receipt that records a human decision/permission grant may *serve as* the authorizing record for an in-scope action; a diagnostic/trace-style receipt does not.

## Authority inheritance rules

1. **Mirrors inherit, never originate.** A machine mirror, DB representation, embedding/index, retrieval cache, or render cache inherits exactly the authority of the source it projects — and only `retrieval-visible`. It can never gain `instructional` or `action-authorizing` (rule 4).
2. **Companions inherit subordination.** A companion note is *about* a primary artifact and is clearly subordinate to it. It may carry governance-recorded metadata (e.g. review receipts) but does not override the primary note's meaning.
3. **Bundles do not inherit constituent authority.** A bundle assembled from accepted memories is not itself an authoritative memory; its authority is its `authority_flags` only (note 10).
4. **Proposals inherit nothing durable until applied.** Authority is conferred at the `Proposal → Receipt → Durable mutation` step (semantic map artifact-flow topology), not before.
5. **Runtime structures inherit nothing.** Session/workspace/panel/retrieval state never inherit durable authority; persisting them requires an explicit governed transition into an artifact.

## Mutation boundary rules

- **Durable human-surface writes** (vault note body/frontmatter) require explicit human intent or bounded system-write authorization, must pass WriteGuard, and must produce a receipt. Blocked in degraded/safe_mode/unhealthy states (owners: `TRUST_SEMANTICS_CONTRACT.md`, `ARCHITECTURE.md` boundary enforcement).
- **Companion-note writes** are system-owned but still governed; the human may correct and the correction is respected.
- **Agentic-memory promotion** (`candidate → accepted`) is a governed review transition; it is the only path by which agentic memory gains `instructional`/`action-authorizing` rights.
- **Mirror writes** (DB/index/cache) are internal and unguarded *as mirrors* — but a mirror write must never feed back as durable meaning without tracing to its authoritative source and passing governance.
- **Runtime-state writes** (session/workspace/panel) are unguarded but durable-prohibited: they may not be written into frontmatter or note bodies as if authoritative.
- **Governance-object edits** are config-as-product changes: versioned, validated, auditable, reversible (owner: `CONFIG_AS_PRODUCT_CONTRACT.md`).

## Rebuildability semantics

- **Rebuildable (must be reconstructable):** DB representations, embeddings/vector indexes, retrieval/render caches, search/graph projections, context bundles. If reconstruction would lose information, the object is misclassified and is really an artifact (owner: `HUMAN_AND_AGENTIC_ARTIFACTS.md` §6).
- **Not rebuildable (durable set):** Human Knowledge Artifacts, Companion Notes, Receipts, accepted Agentic Memory, Governance objects. These are the continuity set the system must work hard never to lose.
- **Discardable (no rebuild obligation):** Runtime session/workspace/panel state. Losing them costs convenience, not meaning.

## Governance escalation semantics

- A mutation that cannot be classified, or that would cross a domain/trust boundary, escalates to the stricter posture: prefer showing sources over asserting, prefer proposal over silent write (owner: `LAYERING_MODEL.md` rule 7, `TRUST_SEMANTICS_CONTRACT.md`).
- A system action that lacks an `action-authorizing` source must escalate to a human-confirmation step rather than proceed.
- An `unreviewed` memory that the system "wants" to act on escalates to the review queue, never to silent activation (rule 3).
- Detailed escalation routing (which mutations require governance/receipts/review) is owned by the workflow mutation semantics (#1371).

## Runtime persistence semantics

- Runtime-only entities (session, workspace, panel, retrieval state) persist to durable stores **only** as explicit runtime records (e.g. a session log classified as a receipt/trace), never as durable semantic artifacts.
- Persisting a runtime-derived value into a durable artifact is a governed mutation: it requires intent, passes WriteGuard, and produces a receipt — it is not a side effect of the runtime touching the value.
- The full runtime-vs-durable boundary contract (persistence rules, discardability, ownership map) is owned by #1369.

## Cross-references

- Parent semantic map and authority topology: `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` (Layer 4 + authority topology).
- Use-right definitions and the unreviewed-memory guard: `docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md`.
- Trust tiers and write gating: `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`.
- Receipts vs traces: `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`, `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`.
- Mirror/DB authority detail: `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (#1370).
- Runtime/durable boundary detail: `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (#1369).
- Workflow mutation/escalation detail: #1371 follow-up.

## Verification path

This document is verified by the existence of:
- a **per-entity authority matrix** covering at least the fifteen named entities (Human Knowledge Artifact, Companion Note, Agentic Memory Artifact, Machine Mirror Artifact, DB representation, Embedding/vector index, Runtime session, Workspace state, Proposal, Receipt, Session log, Context bundle, Panel state, Retrieval cache, Governance object) with explicit authority flags;
- **authority inheritance rules**, **mutation boundary rules**, **rebuildability semantics**, **governance escalation semantics**, and **runtime persistence semantics** sections; and
- explicit, owner-cited resolution that DB/index/mirror objects carry no independent authority and runtime state never persists as durable semantics.
