State: Concept contract (workflow mutation and governance semantics; target-state semantics over current write-safety posture).
Doc role: Core SoT
Authority: Owns the workflow mutation and governance semantics under Layer 4 (Governance/Authority) of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`: the mutation classes, which mutations require governance / receipts / review, the proposal lifecycle and receipt linkage, reversibility semantics, and the authority boundaries that prevent uncontrolled or hidden mutation. Consolidates the mutation semantics distributed across trust, panel, canvas, and write-guard contracts; it does not redefine those owner contracts.
Owner: Workflow mutation and governance semantics
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/SEMANTIC_AUTHORITY_MATRIX.md, docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md, docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md, docs/CONCEPTS/RELATION_TAXONOMY.md, docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md, docs/PANEL_AGENT.md, docs/FRONTMATTER.md, docs/CANVAS_CHAT_SURFACE/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md, epic #1363, issue #1371.

# Workflow Mutation and Governance Semantics

"Mutation" is not just text editing. Editing a note body, changing a frontmatter field, adding a typed relation, applying an agent proposal, and recording a lifecycle transition are different acts with different authority requirements. The repo already has strong bounded-mutation concepts, but they are distributed across the trust, panel, canvas, and write-guard contracts. This document unifies them into one mutation-and-governance model.

It is the Layer 4 mutation detail for `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` and the workflow detail for `docs/SEMANTIC_AUTHORITY_MATRIX.md`.

## Mutation classes

| Mutation class | What it changes | Governed? | Receipt? | Review? | Reversibility |
| --- | --- | --- | --- | --- | --- |
| Direct body edit (human) | Note/canvas body, human-authored | write path, not gov-bearing¹ | no (human authorship) | no | reversible (edit history) |
| Metadata edit | Durable frontmatter fields | yes | yes | cond² | reversible |
| Relation edit | Typed relations (taxonomy) | cond³ | cond | cond | reversible |
| Lifecycle change | `review_state`/`maturity`/`supersedes` | yes | yes | cond | reversible (state) |
| Cross-note mutation | Changes spanning multiple notes | yes | yes | yes | varies |
| Proposal application | Applies a staged change | yes | yes | yes (the proposal *is* the review object) | depends on applied change |
| Governance queueing | Stages a change for review | yes (staging) | on apply | yes | reversible (reject) |
| Agent-authored change | Any durable change originated by an agent | yes (always) | yes | yes | depends on change |
| Machine-generated artifact | System-authored artifact (companion, mirror) | cond⁴ | cond | cond | mirror: rebuildable |
| Review-required mutation | Any mutation a policy marks as needing human review | yes | yes | yes (mandatory) | varies |
| Reversible mutation | A mutation with a safe inverse | yes | yes | cond | reversible |
| Irreversible mutation | A mutation with no safe inverse (external send, delete, downstream call) | yes (highest bar) | yes | yes (mandatory) | irreversible |

### Notes

1. A human direct body edit is the human authoring their own artifact; it persists through the backend write path (not a hidden UI store) but is not a governance-bearing *system* mutation. It still respects WriteGuard health gates.
2. Metadata edits are governance-bearing because frontmatter fields are durable contract fields (`FRONTMATTER.md`); review is required when the field carries authority (trust posture, permission, policy).
3. Relation edits are governed per the relation's class: authoritative relations (`supersedes`, `decision_about`) are governance-bearing; confirming an inferred relation is a governed transition; a generic human `links_to` is a body-level association (owner: `RELATION_TAXONOMY.md`).
4. Machine-generated companion notes are governed system writes (receipted); machine-generated mirrors are internal/rebuildable and not individually receipted as durable mutations (owner: `MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`).

## Governance semantics

- **Which mutations require governance:** every durable change to the human surface that is not a human's own direct body edit — i.e. metadata edits, lifecycle changes, cross-note mutations, agent-authored changes, proposal applications, and all irreversible mutations. Governance owns admissibility, write-safety gating, and the receipt.
- **Which mutations require receipts:** every governance-bearing mutation produces a human-legible receipt recording what changed, by what authority, and with what result (owner: `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`). Receipts are durable governance records, not mirrors.
- **Which mutations require review:** agent-authored durable changes, cross-note mutations, irreversible mutations, agentic-memory promotion (`candidate → accepted`), and any mutation a policy profile marks review-required. Review is the human (or a human-authorized rule) approving before the durable change applies.
- **Which mutations are runtime-only:** changes to runtime/session/UI/overlay/workspace/retrieval state. These are not governance-bearing and produce no receipt — but they must never reach the durable surface without crossing into a governed mutation (owner: `RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`).
- **Which mutations are reversible:** prefer reversible mutations; an irreversible mutation escalates to the highest bar (mandatory review + explicit confirmation) and must be clearly marked as irreversible at confirmation time.
- **Trust gating runs independently:** trust tier (`assert`/`suggest`/`apply`) constrains whether material may be asserted, only suggested, or applied, on top of the mutation-class rules (owner: `TRUST_SEMANTICS_CONTRACT.md`).
- **WriteGuard blocks in unsafe states:** all durable writes are blocked in degraded/safe_mode/unhealthy states regardless of mutation class (owner: `ARCHITECTURE.md` boundary enforcement; repo invariant).

## Proposal lifecycle

A proposal is the canonical vehicle for a not-yet-adopted change. Its lifecycle:

```
creation → staging → review → application → receipt
                       └────▶ rejection (discarded, no durable change)
```

- **Creation.** A proposal is created (by an agent, a capability, or the human) targeting a specific artifact via a `proposal_for` relation (owner: `RELATION_TAXONOMY.md`). It carries provenance: what context/bundle produced it, what evidence supports it.
- **Staging.** The proposal is held as proposal-bearing, non-durable state. It changes nothing on the durable surface (owner: `RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`, authority matrix).
- **Review.** The proposal is the review object. A human or authorized rule evaluates it. For agent-authored and irreversible changes, review is mandatory.
- **Application.** On approval, the change applies through the governed mutation path (WriteGuard + trust gate), producing the durable mutation.
- **Receipt linkage.** Application produces a receipt that links the proposal, its provenance, the applied change, and the resulting artifact state. The receipt — not the proposal — is the durable authorizing record.
- **Rejection.** On rejection the proposal is discarded with no durable change; the rejection may itself be recorded for audit. Rejection is side-effect-free (owner: discardability semantics, `RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`).
- **Provenance.** A proposal's provenance (source bundle, evidence, originating agent) is preserved into the receipt so the durable change is explainable after the fact.

## Reversibility semantics

- **Reversible mutations** (body edits, metadata edits, relation edits, lifecycle changes) have a safe inverse (edit history, field revert, relation revoke, state revert). They are the default and the preferred form.
- **Irreversible mutations** (external sends, deletes, downstream API calls, notifications) have no safe inverse. They require the highest governance bar: mandatory review, explicit human confirmation, an `action-authorizing` source, and a receipt — and must be presented as irreversible at confirmation time (consistent with `CONTEXT_ACTIVATION_SEMANTICS.md` §4.5 on why action-authorizing is the narrowest right).
- A mutation whose reversibility is unknown is treated as irreversible (stricter boundary wins).

## Authority boundaries — prohibited mutation paths

These are the failure modes this contract exists to prevent:

1. **Uncontrolled agent mutation.** An agent may never apply a durable change without a proposal, review (where required), governance, and a receipt. Agents propose; the human or a human-authorized rule decides (kernel constraint).
2. **Implicit authority escalation.** No mutation gains authority it was not granted — a `suggest`-tier source cannot become an `apply`, a proposal cannot self-approve, a projection cannot become durable.
3. **Hidden durable writes.** No durable change to the human surface occurs without a receipt. There is no silent write path.
4. **UI/runtime bypasses around governance.** The Companion UI and runtime layers route mutations to governance; they do not classify or authorize their own durable writes (owner: `companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md`). Runtime state never becomes durable except through a governed mutation.

## Cross-references

- Parent semantic map (Layer 4) and artifact-flow topology: `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.
- Per-entity authority + mutation boundary rules: `docs/SEMANTIC_AUTHORITY_MATRIX.md`.
- Trust tiers and write gating: `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`.
- Receipts: `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
- Relation edits: `docs/CONCEPTS/RELATION_TAXONOMY.md`.
- Runtime vs durable (staging, discardability): `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`.
- Panel/canvas mutation surfaces: `docs/PANEL_AGENT.md`, `docs/CANVAS_CHAT_SURFACE/README.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`.
- Companion UI mutation lanes: `companion-ui/docs/SEMANTIC_PROJECTION_ALIGNMENT.md`.

## Verification path

This document is verified by the existence of:
- a **mutation classes** table covering at least direct body edits, metadata edits, relation edits, proposal application, governance queueing, agent-authored changes, machine-generated artifacts, review-required, reversible, and irreversible mutations;
- **governance semantics** stating which mutations require governance / receipts / review / are runtime-only / reversible;
- a **proposal lifecycle** (creation → staging → review → application → receipt, plus rejection) with provenance and receipt linkage;
- **reversibility semantics**; and
- **authority boundaries** prohibiting uncontrolled agent mutation, implicit escalation, hidden durable writes, and UI/runtime governance bypasses.
