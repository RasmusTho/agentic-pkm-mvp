# Companion UI Semantic Projection Alignment

State: Alignment doc (maps Companion UI contracts onto the semantic architecture; target-state semantics).
Doc role: Companion UI alignment contract
Authority: Aligns the Companion UI contracts to **Layer 7 (UI projection)** of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` and the authority/runtime boundaries in `docs/SEMANTIC_AUTHORITY_MATRIX.md` and `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`. It does not replace the individual Companion UI contracts; each remains authoritative for its own surface. This doc states the shared projection/mutation/authority/runtime-overlay rules they must all satisfy and records the alignment findings.
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/SEMANTIC_AUTHORITY_MATRIX.md, docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md, docs/CONCEPTS/RELATION_TAXONOMY.md, companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md, companion-ui/docs/WORKSPACE_STATE_CONTRACT.md, companion-ui/docs/CANVAS_SUGGESTION_FLOW.md, companion-ui/docs/UI_RUNTIME_BOUNDARIES.md, companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, epic #1363, issue #1368.

## Purpose

The Companion UI is a **semantic projection layer** (Layer 7). It renders and mediates over the authoritative surfaces; it is never itself a source of truth. The individual Companion UI contracts already encode this in places ("Panel does not own vault I/O", "UI does not reclassify actions locally", the workspace `runtime`/`canvas` durability posture, the canvas body-edit vs governance-bearing lane split). This document unifies those statements into one alignment surface so the projection semantics are consistent across every contract and explicitly tied to the semantic architecture.

It is an alignment doc, not a rewrite: each contract below remains authoritative for its own surface. This doc states the shared rules and flags any divergence for follow-up.

## Layer 7 projection rules (binding across all Companion UI contracts)

### Projection semantics — what the UI may do

| Capability | Allowed? | Constraint |
| --- | --- | --- |
| project / render | Yes | Render authoritative or derived state; the document remains the cognitive anchor |
| summarize | Yes | Summaries are projections; never written back as durable fields without governance |
| overlay | Yes | Overlays (salience/`zone`, temporal) are runtime/derived; never a gate, never durable authority |
| infer | Yes (as suggestion) | Inferred content is surfaced as inferred, with a confirm path; never as confirmed fact |
| stage | Yes | Produces a proposal-bearing object; non-durable until governance applies it |
| queue | Yes | A queue is runtime/proposal-staging state; discardable |
| propose | Yes | Routes through the governance-bearing lane; server classifies authority |
| mutate durably | Only via governed path | Server-side authority classification + WriteGuard + receipt; UI never self-authorizes |
| receipt | Surfaces, does not author | The UI renders receipts; the governance layer authors them |

### Runtime boundary — what is durable vs not

The UI must keep these distinct (owner: `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`):

- **Runtime overlay state** (panel layout, focus, salience/temporal overlays, workspace aggregate) — ephemeral/derived; never written to the durable surface as authoritative.
- **Durable semantic state** (vault note body/frontmatter, companion notes) — changed only through the governed mutation path.
- **Machine-derived state** (retrieval results, rendered views) — rebuildable mirrors; surfaced as candidates, not truth.
- **Retrieval projections** — ranked candidates with their staleness markers; activation is a separate governed step.
- **Governance state** (proposals, receipts, guard status) — surfaced with provenance; authored by the server, not the UI.

### Mutation semantics — the lanes

Companion UI mutations fall into distinct lanes that must not be collapsed (consistent with `CANVAS_SUGGESTION_FLOW.md` and `INTERACTION_SURFACES_AND_AUTHORITY`):

- **Direct body edits (co-authoring lane):** human-driven edits to a note body / canvas; the human is the author. Not a governance-bearing system mutation, but still persisted via the backend write path, not a hidden UI store.
- **Governance-bearing mutations:** metadata/frontmatter edits, relation edits, lifecycle changes, proposal applications. These route through the governance lane; the server classifies authority and a receipt is produced.
- **Metadata edits:** changes to durable frontmatter fields are governance-bearing (owner: `FRONTMATTER.md`).
- **Relation edits:** typed-relation changes follow the relation taxonomy; provenance/inferred relations stay visible as such (owner: `docs/CONCEPTS/RELATION_TAXONOMY.md`).
- **Proposal applications:** apply a staged proposal → governed mutation → receipt. The UI confirms; it does not author the durable change.
- **Receipt generation:** owned by the governance layer; the UI displays receipts and provenance at interaction time, not only in audit trails.

### Authority boundaries — what the UI must never do

- **No UI-owned semantic truth.** No meaning-bearing artifact lives only in a UI/app store.
- **No implicit authority escalation.** A UI flow cannot turn a projection or proposal into durable authority without the governed path.
- **Server-side classification ownership.** The server, not the UI, classifies whether a mutation is body-edit vs governance-bearing and what authority it carries.
- **Governance routing ownership.** The governance layer owns admissibility, WriteGuard, and receipts; the UI routes to it and renders the result.

## Contract alignment findings

Each Companion UI contract mapped to the Layer 7 rules. "Aligned" = the contract already enforces the rule; cross-link added.

| Contract | Layer 7 role | Alignment finding |
| --- | --- | --- |
| `PANEL_COMPANION_UI_CONTRACT.md` | Panel projection + confirm/write-back | Aligned. Already states Panel is note-bound projection, "does not own vault I/O", "does not reclassify actions locally", surfaces evidence/provenance/receipts, and routes confirmation through the write-back boundary. |
| `WORKSPACE_STATE_CONTRACT.md` | Workspace projection aggregate | Aligned. Has explicit Authority Rules, a `runtime`/`canvas` Durability Posture, WriteGuard-blocked and partial-aggregate payloads. Workspace state is a read projection, not a durable artifact. |
| `CANVAS_SUGGESTION_FLOW.md` | Canvas co-authoring + suggestion projection | Aligned. Separates body-edit lane from governance-bearing lane, defines hard invariants and session-log turn kinds; co-authoring is human-authored, governance-bearing routes through the server. |
| `UI_RUNTIME_BOUNDARIES.md` | UI runtime boundary | Aligned. States UI-local state is ephemeral, durable state must be explicitly persisted and vault-compatible, no hidden app databases for meaning-bearing artifacts, provenance visible at interaction time. |
| `VAULT_MARKDOWN_RENDERER_CONTRACT.md` | Render projection | Aligned. Renderer is a projection of vault Markdown; render output is a rebuildable mirror, not authority. |
| `PANEL_CONFIRMATION_API_CONTRACT.md` / `PANEL_DURABLE_PROJECTION_MAPPING.md` | Confirm → governed mutation | Aligned. Confirmation maps to a governed write-back with receipts; durable projection mapping keeps the durable target explicit. |

No contract was found to assert UI-owned semantic truth or self-authorized durable mutation. The alignment is therefore additive: this doc names the shared rules and the cross-links; no contract rewrite was required. Any future Companion UI contract must satisfy the Layer 7 rules above.

## Cross-references

- Parent semantic map (Layer 7): `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.
- Per-entity authority (Panel state, Workspace state, Context bundle, Proposal, Receipt rows): `docs/SEMANTIC_AUTHORITY_MATRIX.md`.
- Runtime vs durable boundary: `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`.
- Relation edits: `docs/CONCEPTS/RELATION_TAXONOMY.md`.
- Interaction-surface authority (Panel/Chat/Automation): `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`.
- Workflow mutation/governance detail: #1371 follow-up.

## Verification path

This document is verified by the existence of:
- explicit **Layer 7 projection rules** covering what the UI may project/summarize/overlay/infer/stage/queue/propose/mutate;
- a **runtime boundary** section separating runtime overlay / durable / machine-derived / retrieval / governance state;
- **mutation semantics** distinguishing direct body edits, governance-bearing mutations, metadata edits, relation edits, proposal applications, and receipt generation;
- **authority boundaries** stating no UI-owned truth, no implicit escalation, server-side classification, and governance routing ownership; and
- a **contract alignment findings** table mapping each Companion UI contract to these rules and confirming consistency.
