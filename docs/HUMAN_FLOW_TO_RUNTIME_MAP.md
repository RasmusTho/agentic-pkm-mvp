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

The SBS allocation columns are derivative routing aids. They map each human flow to a likely
Product/Runtime SBS owner, crossed SBS-owned interface, testable requirement, and verification
anchor so agents can classify future work without hidden context. They do not replace
`docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, `docs/contracts/*.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md`,
or the relevant owner docs.

## Mapping

| Human flow | Human need | System capability | Surface | Runtime support | Provenance / receipt expectation | Primary SBS owner | Secondary SBS owners | SBS-owned interface(s) crossed | Derived testable requirement(s) | Verification anchor(s) | Transition debt / fitness rule | Likely future implementation area |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Capture → clarify → place | Drop a thought, source, or artifact into the right context without ceremony, and trust that it will not be silently rewritten | Frictionless capture; proposed (not imposed) structure; placement into operational scope and trust bucket | Vault (Markdown notes, attachments); Panel; Chat capture entry points (hosted in Companion UI / Obsidian); Automation (watcher-driven ingest) | Watcher ingest, frontmatter normalization, classification proposals, write guards on machine edits | Capture is human-authored by default; any machine-added structure carries an intent + receipt and is reversible | HKA | HIX, WSP, EBF, GOV, PDM, EXE, OEF | `ArtifactContract`; `ActiveContextSet`; `SourceObservationEvent`; `PolicyDecision` / `AuthorityReceipt`; `ExecutionRequest` when side effects run | Machine-added structure stays proposed, reversible, and receipt-backed; placement uses explicit context/source bindings rather than a global active vault. | Manual review now against `docs/FRONTMATTER.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/architecture/SBS_TRANSITION_DEBT.md :: D1`, `docs/architecture/SBS_TRANSITION_DEBT.md :: D2`, and `docs/architecture/SBS_TRANSITION_DEBT.md :: D7` | D1, D2, D7; fitness: no global `activeVault`, no authority-bearing durable write without GOV, event envelope lacks delivery semantics | `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`, `docs/FRONTMATTER.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` |
| Retrieve → orient → act | Re-enter work after time away; find the right surface, with sources visible and uncertainty preserved | Source-grounded retrieval; orientation views; resurfacing of quietly-relevant material the human did not know to ask for; explicit scope (active domain + evergreens) with auditable cross-scope allowance | Chat (read-only cognition today); Panel command surface; vault navigation in Obsidian (rails hosted in Companion UI) | Retrieval pipeline, embeddings + lexical index, orientation runtime, context bundle assembly, resurfacing signals | Every answer cites sources; orientation and resurfacing outputs name what was used and what was excluded | RCA | WSP, DRI, HIX, MEM, GOV, CAO, OEF | `ActiveContextSet`; `DerivedRepresentationContract`; `ContextBundle`; `MemoryRecord` when recall contributes; `PolicyDecision` where filters apply | Retrieved evidence remains candidate-only, carries scope/provenance, and names exclusions; orientation actions do not upgrade retrieval output into accepted truth. | CI check now for production retrieval bundle emission: `tests/retrieval/test_context_bundle_conformance.py::test_production_retrieval_bundle_conforms_to_context_bundle_contract`; manual review now for non-production retrieval/orientation/resurfacing paths against `docs/FINDING_AND_REORIENTING/README.md`, `docs/RETRIEVAL.md`, `docs/architecture/SBS_TRANSITION_DEBT.md :: D4`, and `docs/architecture/SBS_FITNESS_RULES.md :: ContextBundle must carry scope and provenance` | D4, D9; fitness: retrieval becomes truth, ContextBundle scope/provenance | `docs/FINDING_AND_REORIENTING/README.md`, `docs/FINDING_AND_REORIENTING/DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`, `docs/FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`, `docs/FINDING_AND_REORIENTING/DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`, `docs/RETRIEVAL.md` |
| Source → interpret → stabilize | Bring in external material and turn it into trustable, attributable, reusable knowledge | Source artifacts retained as first-class; interpretation notes distinct from source; attribution preserved | Vault (retained artifacts + interpretation notes); archive-brain surfaces | Archive store, source classification, retained-artifact exposure rules, summarization with provenance | Interpretation outputs link back to source artifacts; no laundering of external material into untraceable claims | EBF | HKA, SIP, DRI, RCA, GOV, OEF | `SourceObservationEvent`; `ArtifactContract`; `SemanticIdentityContract`; `DerivedRepresentationContract`; `ContextBundle` when source evidence is assembled | External/source observations remain attributable and non-authoritative until accepted; summaries and interpretations preserve source binding and do not launder source material into untraceable claims. | Manual review now against `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`, `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`, `docs/architecture/SBS_TRANSITION_DEBT.md :: D7`, and `docs/architecture/SBS_TRANSITION_DEBT.md :: D10` | D7, D8, D10; fitness: no provider-specific fields in HKA/SIP/GOV public contracts, SIP remains rebuildable | `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`, `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` |
| Intent → propose → decide → execute → receipt | Turn an intent into a bounded, reviewable action with a durable record of what happened | Intent surface; agent delegation under authority boundary; proposal → confirmation → execution; receipt artifact | Panel (primary command surface); Chat (proposals, including canvas co-edit moments); Automation (governed background paths) — surfaces hosted in Companion UI / Obsidian | Governance router, intent/event envelopes, agent runtime, write guards, receipt writer | Every executed intent leaves a human-readable receipt; proposals are inspectable and reversible | GOV | HIX, CAO, EXE, HKA, MEM, OEF | `IntentEnvelope`; `PolicyDecision`; `AuthorityReceipt`; `CapabilityContract`; `WorkflowContract`; `ExecutionRequest`; `ArtifactContract` for accepted mutations | Authority-bearing durable mutations require a decision and receipt; agents may reason and propose, while side effects run through EXE under GOV. | Manual review now against `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`, `docs/architecture/SBS_TRANSITION_DEBT.md :: D2`, and `docs/architecture/SBS_TRANSITION_DEBT.md :: D6` | D2, D6, D9; fitness: no authority-bearing durable write without GOV, no direct tool side effects from CAO without GOV/EXE | `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`, `docs/CANVAS_CHAT_SURFACE/README.md` |
| Review → reclassify → promote / archive | Periodically revisit material, change its state or scope, and keep the system from rotting into a passive dump | Review cycles; state-axis changes (review_state, maturity); promotion and archive moves under explicit intent | Vault frontmatter; Panel review commands; Chat review surfaces (hosted in Companion UI) | Commitment layer queries, state-axis machinery, archive promotion paths, lifecycle events | Reclassification produces receipts; promotion/archive moves are reversible and auditable | HKA | HIX, GOV, SIP, MEM, EXE, OEF | `ArtifactContract`; `PolicyDecision`; `AuthorityReceipt`; `SemanticIdentityContract`; `MemoryRecord` when memory material is promoted or corrected; `ExecutionRequest` for side effects | Reclassification and promotion preserve artifact identity, explicit authority, and receipts; memory or derived material is not promoted into HKA without GOV. | Manual review now against `docs/CONCEPTS/STATE_AXES_CONTRACT.md`, `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`, and `docs/architecture/SBS_TRANSITION_DEBT.md :: D5` | D2, D5, D10; fitness: no memory promotion to HKA without GOV, derived representations remain rebuildable | `docs/CONCEPTS/STATE_AXES_CONTRACT.md`, `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md` |
| Remember → recall → explain → correct | Trust that the system's "memory" about prior work, decisions, and agent actions remains legible and correctable | Inspectable agent memory; receipt-backed recall; correction path when the system's memory diverges from the human's | Chat history; Panel logs; receipts on disk; vault companion notes (session drawer hosted in Companion UI) | Session log writer, receipt store, agent memory store, governance router; guarded recall runs read-only in the ASK graph (`app/agents/ask/graph.py`) and recalled memory is attributed in the answer via a footer keyed to its recall receipt (`render_recall_footer`; #1970/#1971/#1972) | Recall surfaces show what was used — when recall fires, the ASK answer carries a "Recalled from: … · receipt &lt;id&gt;" attribution footer keyed to the recall receipt (no attribution shown when recall did not fire); corrections produce new receipts rather than rewriting prior ones | MEM | GOV, RCA, HKA, HIX, CAO, OEF | `MemoryRecord`; `AuthorityReceipt` for promotion/correction decisions; `ContextBundle` when recall contributes evidence; `CapabilityContract` for read-only recall behavior | Memory recall remains inspectable, attributed, review-aware, and correctable; unreviewed memory must not become hidden instruction or HKA authority. | Manual review now against `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, and `docs/architecture/SBS_TRANSITION_DEBT.md :: D5` | D5, D9; fitness: no memory promotion to HKA without GOV, memory becomes hidden instruction | `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` |
| Anticipate → surface → reach out (within scarcity) | See the right thing at the right moment without having to remember to check; be reached only when a moment earns it, and never during sleep or declared do-not-disturb | Contextual Relevance Engine: context model + adaptive relevance evaluator that *produces* moments; deterministic reach-out/scarcity gate (graduated ladder, context-dependent interruption threshold, zero-tolerance floor, defer-not-drop); user-declared patterns as soft guidance | Companion UI "now"/glance surface (pull, via `GET /api/companion/now`); in-app nudge; OS push (top rung, highest bar) — surfaces hosted in Companion UI | Relevance evaluator + moment materialization (`app/relevance/`) through WriteGuard, run on a governed watcher tick (`app/watcher/relevance_tick.py`) and surfaced read-only at `GET /api/companion/now` (#1958); interruptibility threshold + proactive attention loop now run on the governed relevance tick for freshly materialized moments (#1964), with in-app nudge projection; OS-send connector remains deferred; receipts on every materialization, reach-out, and deliberate suppression | Moments are non-authoritative proposals with provenance; every reach-out / deliberate suppression leaves a receipt; no external side-effects (the OS-send connector is a deferred slice) | CAO | HIX, WSP, RCA, MEM, GOV, EXE, EBF, OEF | `CapabilityContract`; `WorkflowContract`; `ActiveContextSet`; `ContextBundle`; `MemoryRecord` when memory contributes; `PolicyDecision`; `ExecutionRequest` for any external side effect | Proactive moments remain scarce, provenance-bearing, and governed; external reach-out or OS delivery is deferred unless an EXE/GOV path exists. | Manual review now against `docs/CONTEXTUAL_RELEVANCE_ENGINE/`, `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`, `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`, `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`, and `docs/architecture/SBS_TRANSITION_DEBT.md :: D6` | D6, D8, D9; fitness: no direct tool side effects from CAO without GOV/EXE, no OEF automatic control loop | `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md`, `docs/CONTEXTUAL_RELEVANCE_ENGINE/`, `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`, `docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md`, `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md` |

## How to read a row

For each row, the columns answer a different question:

- **Human need** — what is hard for unaided cognition.
- **System capability** — what Yggdrasil offers to share that load.
- **Surface** — where the human encounters the capability.
- **Runtime support** — which supporting machine surfaces make it work.
- **Provenance / receipt expectation** — what must remain true for the capability to count as a
  cognitive prosthesis rather than a black-box assistant.
- **Primary SBS owner** — the target Product/Runtime SBS subsystem that owns the semantics most
  directly affected by future work in this row.
- **Secondary SBS owners** — other Product/Runtime SBS subsystems whose contracts are commonly read,
  crossed, or constrained by the row.
- **SBS-owned interface(s) crossed** — conceptual contracts from
  `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` Part 5 or `docs/contracts/*.md` that should be checked before
  changing the row. These names are pointers to owners, not duplicated contract fields.
- **Derived testable requirement(s)** — the reviewable invariant a future issue can turn into
  concrete acceptance criteria with `Verify:` targets.
- **Verification anchor(s)** — the current proof surface for the row. `Manual review now` means no
  deterministic check owns that proof yet.
- **Transition debt / fitness rule** — SBS transition debt and architecture fitness rules most likely
  to be affected by changes in this row.
- **Likely future implementation area** — which owner doc is most likely to absorb the next
  bounded change for this row. This is a navigation hint, not a commitment.

The SBS columns are allocation and verification metadata derived from the target SBS and owner docs.
They do not change which document owns a contract, do not create new subsystem responsibilities, and
do not prove that an implementation exists.

## Caveats

- This is a *map*, not a checklist. A row does not assert the capability is fully shipped.
- This is not a full Functional Breakdown Structure and not a parallel source of truth. The
  authoritative decomposition remains `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`; contract content remains
  in `docs/contracts/*.md` and owner docs.
- The SBS allocation columns are derivative. If they conflict with `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`,
  `docs/ARCHITECTURE.md`, `docs/STATUS.md`, or a contract owner doc, the owner doc wins and this map
  should be corrected.
- Where a row's "runtime support" lists components that are still partially implemented or
  planned, the owner docs and `docs/STATUS.md` are authoritative on current state.
- New flows should be added here only after they are anchored in `docs/HUMAN-FLOWS.md` and in
  the relevant concept contract.
