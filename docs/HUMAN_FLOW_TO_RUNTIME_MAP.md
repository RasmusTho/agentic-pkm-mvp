State: SoT v5.5 baseline; v6 active planning direction. Bridge document; not a current-state claim that every mapped capability is shipped.
Doc role: Core SoT
Authority: Bridges human flows to runtime capabilities. Use it to locate the surface, runtime support, provenance expectation, and likely implementation area for a given human need. Owner docs win on current implementation truth.
Owner: Product / architecture
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-12
Last verified against: docs/PROJECT_KERNEL.md, docs/HUMAN-FLOWS.md, docs/AGENT-FLOWS.md, docs/ARCHITECTURE.md, docs/CANVAS_CHAT_SURFACE/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/FINDING_AND_REORIENTING/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md, docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md

# Human Flow to Runtime Map

> Audience: readers who already understand the product thesis (`docs/COGNITIVE_PROSTHESIS_CHARTER.md`) and the human flows (`docs/HUMAN-FLOWS.md`), and need to see how each flow lands on the runtime substrate.

This document is a bridge, not a contract. The human-flow column is normative against
`docs/HUMAN-FLOWS.md` (all six canonical loops, including
`Remember -> recall -> explain -> correct`, are anchored there). The system-capability, surface,
runtime-support, and provenance/receipt columns are descriptive — they summarize where in the
architecture each flow is supported or is *intended* to be supported. Agent-facing obligations
for these flows (per-flow authority bindings, recall/correction duties, participation modes) are
owned by `docs/AGENT-FLOWS.md`, not by this map.

Current implementation truth is owned by `docs/STATUS.md`, `docs/ROADMAP.md`, and the relevant
owner docs. Where a row describes a capability that is not yet shipped, the "likely future
implementation area" column points to the owner doc most likely to absorb that work.

Items listed in the "Runtime support" column may be shipped, partial, or planned;
`docs/STATUS.md` and the owner docs are authoritative on which is which.

The canonical interaction surfaces are **Panel**, **Chat**, and **Automation**
(`docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md`).
The Companion UI is the product/UI shell that *hosts* those surfaces, not a fourth surface;
where the "Surface" column mentions Companion UI it refers to the hosting shell.
For the product-mode interpretation of this shell (Find, Reorient, Resurface, Act), see
`docs/COMPANION_UI_PRODUCT_SPEC.md`.

## Mapping

| Human flow | Human need | System capability | Surface | Runtime support | Provenance / receipt expectation | Likely future implementation area |
| --- | --- | --- | --- | --- | --- | --- |
| Capture → clarify → place | Drop a thought, source, or artifact into the right context without ceremony, and trust that it will not be silently rewritten | Frictionless capture; proposed (not imposed) structure; placement into operational scope and trust bucket | Vault (Markdown notes, attachments); Panel; Chat capture entry points (hosted in Companion UI / Obsidian); Automation (watcher-driven ingest) | Watcher ingest, frontmatter normalization, classification proposals, write guards on machine edits | Capture is human-authored by default; any machine-added structure carries an intent + receipt and is reversible | `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`, `docs/FRONTMATTER.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` |
| Retrieve → orient → act | Re-enter work after time away; find the right surface, with sources visible and uncertainty preserved | Source-grounded retrieval; orientation views; resurfacing of quietly-relevant material the human did not know to ask for; explicit scope (active domain + evergreens) with auditable cross-scope allowance | Chat (read-only cognition today); Panel command surface; vault navigation in Obsidian (rails hosted in Companion UI) | Retrieval pipeline, embeddings + lexical index, orientation runtime, context bundle assembly, resurfacing signals | Every answer cites sources; orientation and resurfacing outputs name what was used and what was excluded | `docs/FINDING_AND_REORIENTING/README.md`, `docs/FINDING_AND_REORIENTING/DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`, `docs/FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`, `docs/FINDING_AND_REORIENTING/DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`, `docs/RETRIEVAL.md` |
| Source → interpret → stabilize | Bring in external material and turn it into trustable, attributable, reusable knowledge | Source artifacts retained as first-class; interpretation notes distinct from source; attribution preserved | Vault (retained artifacts + interpretation notes); archive-brain surfaces | Archive store, source classification, retained-artifact exposure rules, summarization with provenance | Interpretation outputs link back to source artifacts; no laundering of external material into untraceable claims | `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`, `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` |
| Intent → propose → decide → execute → receipt | Turn an intent into a bounded, reviewable action with a durable record of what happened | Intent surface; agent delegation under authority boundary; proposal → confirmation → execution; receipt artifact | Panel (primary command surface); Chat (proposals, including canvas co-edit moments); Automation (governed background paths) — surfaces hosted in Companion UI / Obsidian | Governance router, intent/event envelopes, agent runtime, write guards, receipt writer | Every executed intent leaves a human-readable receipt; proposals are inspectable and reversible | `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`, `docs/CANVAS_CHAT_SURFACE/README.md` |
| Review → reclassify → promote / archive | Periodically revisit material, change its state or scope, and keep the system from rotting into a passive dump | Review cycles; state-axis changes (review_state, maturity); promotion and archive moves under explicit intent | Vault frontmatter; Panel review commands; Chat review surfaces (hosted in Companion UI) | Commitment layer queries, state-axis machinery, archive promotion paths, lifecycle events | Reclassification produces receipts; promotion/archive moves are reversible and auditable | `docs/CONCEPTS/STATE_AXES_CONTRACT.md`, `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md` |
| Remember → recall → explain → correct | Trust that the system's "memory" about prior work, decisions, and agent actions remains legible and correctable | Inspectable agent memory; receipt-backed recall; correction path when the system's memory diverges from the human's | Chat history; Panel logs; receipts on disk; vault companion notes (session drawer hosted in Companion UI) | Session log writer, receipt store, agent memory store, governance router | Recall surfaces show what was used; corrections produce new receipts rather than rewriting prior ones | `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` |
| Anticipate → surface → reach out (within scarcity) | See the right thing at the right moment without having to remember to check; be reached only when a moment earns it, and never during sleep or declared do-not-disturb | Contextual Relevance Engine: context model + adaptive relevance evaluator that *produces* moments; deterministic reach-out/scarcity gate (graduated ladder, context-dependent interruption threshold, zero-tolerance floor, defer-not-drop); user-declared patterns as soft guidance | Companion UI "now"/glance surface (pull, via `GET /api/companion/now`); in-app nudge; OS push (top rung, highest bar) — surfaces hosted in Companion UI | Relevance evaluator + moment materialization (`app/relevance/`) through WriteGuard, run on a governed watcher tick (`app/watcher/relevance_tick.py`) and surfaced read-only at `GET /api/companion/now` (#1958); interruptibility threshold + proactive attention loop built (reach-out runtime wiring gated on #1881); receipts on every materialization, reach-out, and deliberate suppression | Moments are non-authoritative proposals with provenance; every reach-out / deliberate suppression leaves a receipt; no external side-effects (the OS-send connector is a deferred slice) | `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md`, `docs/CONTEXTUAL_RELEVANCE_ENGINE/`, `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`, `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`, `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md` |

## How to read a row

For each row, the columns answer a different question:

- **Human need** — what is hard for unaided cognition.
- **System capability** — what Yggdrasil offers to share that load.
- **Surface** — where the human encounters the capability.
- **Runtime support** — which supporting machine surfaces make it work.
- **Provenance / receipt expectation** — what must remain true for the capability to count as a
  cognitive prosthesis rather than a black-box assistant.
- **Likely future implementation area** — which owner doc is most likely to absorb the next
  bounded change for this row. This is a navigation hint, not a commitment.

## Caveats

- This is a *map*, not a checklist. A row does not assert the capability is fully shipped.
- Where a row's "runtime support" lists components that are still partially implemented or
  planned, the owner docs and `docs/STATUS.md` are authoritative on current state.
- New flows should be added here only after they are anchored in `docs/HUMAN-FLOWS.md` and in
  the relevant concept contract.
