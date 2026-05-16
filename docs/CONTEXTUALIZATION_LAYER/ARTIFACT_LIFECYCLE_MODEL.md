State: Initial lifecycle model for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept contract
Authority: Names the lifecycle states, transitions, and applicability per artifact class for the Contextualization Layer. Not a state machine, not a validator, not a watcher implementation, not a governance/authority model, not a database schema, not a runtime implementation plan.

# Artifact Lifecycle Model for the Contextualization Layer

## 1. Purpose

This document defines the **lifecycle model** for the artifact classes introduced in `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md`.

It exists so that later work on review queues, promotion flows, recall and explanation surfaces, stale-content handling, and retention policy can talk about the same lifecycle states without each surface inventing its own vocabulary, and without collapsing fundamentally different lifecycles into a single one.

It is intentionally narrow:

- It defines *which lifecycle states* apply to which artifact class.
- It defines *which transitions are allowed*, *which are prohibited*, and *which are deferred* to neighbouring contracts.
- It separates lifecycle (what state an artifact is in) from activation/use-right (what an artifact may do in that state), which is the scope of `docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md` (planned in [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943)).
- It does **not** specify a state machine, a validator, a watcher, a database schema, a prompt template, an activation engine, or a runtime implementation.

This document is **target-state semantics, not runtime claim**. Nothing here asserts that any of these states is currently enforced by code.

## 2. Relationship to existing Contextualization Layer docs

This document builds directly on:

- `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` — artifact classes, durability tiers, activation/use rights vocabulary.
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` — placement modes, `artifact_class` and `memory_type` vs `artifact_type` distinction, per-class metadata shapes.
- `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md` — companion note placement, linkage, types, readability and editability rules.

And it cross-cuts (without replacing) the following concept contracts, which remain authoritative for their own scope:

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — agent-memory lifecycle (Observe → Candidate → Review → Promote/Reject/Revise → Decay/archive → Recall → Explain) and authority rules.
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` — bridge-artifact lifecycle, exclusion tracking, authority flags, stale/expiry.
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md` — three-surface model for vault notes, healing scenarios, rebuild from companions.
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` — stale vs drift vs historical validity vs re-evaluation need.

## 3. Load-bearing invariants

The following invariants from the prior Contextualization Layer docs are load-bearing for everything below:

- **Markdown is the shared substrate, not the shared semantics.** Different lifecycles may sit side by side in the same folder.
- **Artifact classes are distinct.** Human knowledge artifacts, agentic memory artifacts, bridge/assembly artifacts, machine mirror artifacts, and companion metadata notes have different lifecycles. They must not be collapsed.
- **`memory_type` is for agentic memory semantics; `artifact_type` is for artifact classification.** Lifecycle state applies to the *artifact*, not to the cognitive class of memory it carries.
- **Context bundles are bridge/assembly artifacts, not agentic memory.** A bundle may contain or reference memory artifacts, but it does not inherit their lifecycle.
- **Machine mirrors are rebuildable technical projections.** They cannot be treated as durable source knowledge or as authoritative memory.
- **Unreviewed memory must never become hidden authority.** Lifecycle state alone does not grant authority; authority granting is governed by `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` and the activation/use-right semantics in [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943).

## 4. Lifecycle principles

1. **Lifecycle is class-specific.** Not every state applies to every class. Borrowing a state across classes is a category error and is called out in Section 7.
2. **Lifecycle state is not authority.** An artifact being `reviewed` or `accepted` does not, by itself, grant the right to instruct or to authorize a write. Authority is granted by the activation/use-right contract (see [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943)), gated by trust semantics, and recorded via receipts.
3. **Review and promotion are explicit and only apply to agentic memory.** Editing a human knowledge artifact is *not* "promoting" it. Assembling a context bundle is *not* "promoting" its sources into memory. Regenerating a machine mirror is *not* "reviewing" it.
4. **Activation is separate from existence and from retrieval.** Whether an artifact may enter working context for a task is governed by activation semantics, not by lifecycle state. Lifecycle state is one *input* to activation, but not the whole story.
5. **Machine mirrors are rebuildable.** Discarding a mirror does not lose information when the source remains. Treating a mirror as if it carried independent state is a misclassification.
6. **Companion metadata notes have their own lifecycle, parallel to the target.** A companion may be regenerated, revised, or archived independently of its target; the companion does not *replace* the target.

## 5. Per-class lifecycle sections

### 5.1 Human Knowledge Artifacts

**Primary audience:** the human. The artifact belongs to the human.

**Lifecycle states**

- `created` — the human (or import) brought the artifact into existence.
- `working` — the human is actively writing, drafting, refining. May also be called `draft`. Aligns with the `maturity` / `status` posture defined in `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` §5.
- `settled` — the human considers the artifact mature enough for stable use. Equivalent to the existing `maturity: settled` posture.
- `revised` — a settled artifact has been meaningfully changed and re-enters a working/settled cycle.
- `stale` — the artifact may no longer reflect current world, tools, or context, per `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`. **Stale does not mean wrong.**
- `archived` — the artifact is retained but moved out of active use. Historical validity remains; current validity is not implied.

**Transitions**

- `created → working → settled` is the normal authoring path.
- `settled → revised → working/settled` is the normal correction path.
- `* → stale` is signalled by time, drift, or contradiction, not by a human action.
- `* → archived` is an explicit human decision.

**States that do not apply**

- `candidate`, `reviewed`, `accepted/promoted`, `rejected` — these are agentic-memory states. Human knowledge artifacts are *authored*, not *promoted*. A human writing a note is not a system reviewing a candidate.
- `regenerated`, `discarded` — these are machine-mirror states. A human knowledge artifact is not rebuilt from a source artifact; it *is* the source artifact.
- `invalidated` — applies *only* in the narrow sense that another human knowledge artifact (e.g. a corrected note, a superseding decision) explicitly supersedes it. The default for human knowledge is `revised` plus `stale`, not `invalidated`.

### 5.2 Agentic Memory Artifacts

**Primary audience:** mixed — human and agent. The artifact is system-maintained, but must remain human-readable and human-editable.

This is the only class for which the canonical memory lifecycle from `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` applies in full.

**Lifecycle states**

- `observed` — the system noticed an event, pattern, or candidate fact. No memory artifact has been created yet.
- `candidate` — the observation has been materialised as a candidate memory artifact, marked clearly as unreviewed.
- `reviewed` — the candidate has been checked against human review, policy, source grounding, or stronger evidence. Outcome is one of `accepted/promoted`, `rejected`, or `revised`.
- `accepted/promoted` — the candidate has become a more durable memory artifact and/or has been promoted into a more stable memory class (e.g. `preference_candidate` accepted as a stable `preference_memory`).
- `rejected` — the candidate is not accepted. The rejection is recorded; the candidate artifact may be retained for audit or archived.
- `revised` — the memory has been corrected, narrowed, or reclassified. Provenance to the prior version is preserved.
- `stale` — the memory may no longer be safely treated as current. It remains inspectable. **Stale agentic memory must not silently authorize action**; re-validation belongs to activation semantics ([#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943)).
- `invalidated` — the memory has been contradicted, superseded, or proven wrong. It must not instruct or authorize action without an explicit re-review. The original is retained with the invalidation reason for audit.
- `archived` — the memory is retained but no longer in active use. Recall may still surface it with an `archived` marker; it does not enter working context by default.
- `discarded` — the memory artifact has been removed. Provenance and receipts are preserved per `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; the recalled support material is gone.

**Transitions**

- `observed → candidate` is the materialisation step.
- `candidate → reviewed → {accepted, rejected, revised}` is the review path. **No artifact may skip from `observed` or `candidate` directly to `accepted/promoted` without an explicit review record.**
- `accepted → revised → reviewed → …` is the correction cycle.
- `* → stale` is signalled by time, drift, validity expiry, or contradiction.
- `stale → reviewed → {accepted, revised, invalidated}` is the re-validation path.
- `* → invalidated` requires an explicit superseding artifact or review decision.
- `* → archived` and `archived → discarded` are governance decisions; discard preserves audit trail unless the audit contract explicitly says otherwise.

**States that do not apply**

- `regenerated` is not an agentic-memory state. Memory is reviewed and promoted, not rebuilt from a source.
- `created` is folded into `observed` / `candidate`; calling a memory artifact "created" without distinguishing whether it has been reviewed obscures the very distinction the lifecycle is for.

### 5.3 Bridge / Assembly Artifacts

**Primary audience:** the system, with human review for explainability. Examples: `context_bundle`, `working_context_snapshot`, `execution_context_bundle`, `reorientation_bundle` (see `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` §7 and `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`).

**Lifecycle states**

- `assembled` — the bundle has been selected and recorded, with included items, excluded items, trigger, scope, and authority flags. Equivalent to the bundle lifecycle step 1–3 in `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`.
- `exposed` — the bundle has been made available for review or downstream use. Authority flags are in effect.
- `consumed` — the bundle has been used by an answering, orienting, resurfacing, or proposing surface. The receipt of consumption is attached.
- `stale` — the bundle's supporting assumptions no longer hold, or its `stale_after` has passed.
- `expired` — the bundle's authority is no longer current. It may remain inspectable for audit, but it does not silently inherit current authority.
- `archived-for-audit` — the bundle is retained for audit/explanation purposes after expiry. No active authority.
- `discarded` — the bundle has been removed. Receipts and provenance survive per the bundle contract.

**Transitions**

- `assembled → exposed → consumed` is the normal use path.
- `* → stale → expired` is the temporal decay path.
- `expired → archived-for-audit` or `expired → discarded` are governance decisions.

**States that do not apply (prohibited)**

- `candidate`, `reviewed`, `accepted/promoted`, `rejected`, `revised` — **a bridge artifact is never promoted into memory or knowledge**. Promotion of bundle *content* into memory happens through the agentic-memory lifecycle (Section 5.2), on the underlying material, not on the bundle itself. This is the explicit normative rule from `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`: *"A context bundle must not silently promote retrieved context into memory or knowledge."*
- `regenerated` — bridges are not rebuilt from a source projection; if context is needed again, a *new* bundle is assembled, with its own identity, receipts, and authority flags.

### 5.4 Machine Mirror Artifacts

**Primary audience:** the system. Examples: chunks, embeddings, vector indexes, graph projections, caches, search-result records (see `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` §8).

**Lifecycle states**

- `generated` — the mirror has been produced from its source (a human knowledge artifact or an agentic memory artifact).
- `current` — the mirror's `source_hash` still matches the source, the generator version is still in use, and the projection is treated as current.
- `stale` — the source has changed, the generator has changed, or another signal indicates the mirror may no longer match. The mirror remains usable for diagnostics but should not be relied on for retrieval without re-validation.
- `regenerated` — the mirror has been rebuilt from the source. Identity may be preserved (same index slot) or replaced (new record); the source remains the same.
- `discarded` — the mirror has been removed. **No knowledge is lost**, because the source artifact remains and the mirror is rebuildable by definition.

**Transitions**

- `generated → current` is automatic on successful generation.
- `current → stale` is signalled by `source_hash` mismatch, generator version change, or explicit invalidation.
- `stale → regenerated → current` is the rebuild path.
- `current → discarded` and `stale → discarded` are governance decisions; both are safe because the source remains.

**States that do not apply (prohibited)**

- `candidate`, `reviewed`, `accepted/promoted`, `rejected`, `revised` — **machine mirrors are never reviewed and never promoted**. Their authority is the authority of their source. Editing a mirror manually as if it carried independent meaning is a misclassification.
- `archived` in the agentic-memory sense — a mirror is rebuildable, so retention semantics are about cache and cost, not about historical record. If a "machine mirror" carries information that would be lost on discard, it is not a mirror; it has become either agentic memory or human knowledge and must be reclassified accordingly.
- `invalidated` as a permanent label — a mirror that is no longer current is `stale`. If the source itself was invalidated, the mirror is discarded or regenerated against the new source, not labelled `invalidated` independently.

### 5.5 Companion Metadata Notes

**Primary audience:** the system, with human inspectability. Examples per `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md` §8: `processing_companion`, `activation_companion`, `retrieval_companion`, `provenance_companion`, `review_companion`, `synthesis_companion`, `mixed_companion`.

A companion is *about* a target artifact, not a replacement for it. Its lifecycle runs *in parallel* with the target, not embedded in it.

**Lifecycle states**

- `created` — the companion has been created (lazily when the system has something to write, or eagerly per a future companion-location policy).
- `reconciled` — the companion has been re-checked against the target (typically via `target_hash`) and is up to date with the target.
- `revised` — the companion has been updated, by the system or by a human edit, in a way that preserved its alignment with the target.
- `regenerated` — the companion has been rebuilt from scratch (e.g. after a parser version change, a target rename, or a structural reorganisation). Human-managed blocks in the companion are not silently overwritten per `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md` §10.
- `stale` — the target has changed materially and the companion has not yet been reconciled.
- `archived` — the target has been archived; the companion follows.
- `discarded` — the companion has been removed. Discard is safe when the companion only carried machine-derived signals; discard requires explicit human handling when the companion carries human-authored sections (e.g. human-review notes).

**Transitions**

- `created → reconciled` is the normal post-creation step.
- `reconciled → stale → reconciled` is the routine target-change cycle.
- `* → revised` happens on human edit or on a managed-block system update.
- `* → regenerated` is the rebuild path; managed-block boundaries from `COMPANION_NOTE_PATTERN.md` §10 apply.
- `archived` follows the target; `discarded` is bounded by the human-authored-content rule above.

**States that do not apply**

- `candidate`, `reviewed`, `accepted/promoted`, `rejected` — companion metadata notes are *not* agentic memory candidates. A `synthesis_companion` may *contain* candidate memories awaiting review (per `COMPANION_NOTE_PATTERN.md` §8), but those candidate memories follow the agentic-memory lifecycle (Section 5.2), not the companion's own lifecycle.
- `invalidated` as the companion's own state — if a companion's content is wrong, it is `revised` or `regenerated`. If the target is invalidated, the companion follows the target.

## 6. Applicability matrix

Rows are lifecycle terms. Columns are artifact classes. Values:

- `applies` — the state is a normal part of this class's lifecycle.
- `conditional` — the state applies only under named conditions; see the per-class section.
- `n/a` — the state does not belong to this class's lifecycle.
- `prohibited` — using this state for this class is a category error and must not be done.

| Lifecycle term | Human Knowledge | Agentic Memory | Bridge / Assembly | Machine Mirror | Companion Metadata |
|---|---|---|---|---|---|
| `created` | applies | conditional (folded into `observed` / `candidate`) | n/a (use `assembled`) | n/a (use `generated`) | applies |
| `processed` | conditional (ingest pipeline step; see `ARTIFACT_MODEL_AND_LIFECYCLES.md` `ingest_state`) | n/a | n/a | conditional (generation is processing) | conditional (processing companion) |
| `candidate` | prohibited | applies | prohibited | prohibited | prohibited |
| `reviewed` | prohibited (humans author; they do not review their own knowledge as candidates) | applies | prohibited | prohibited | prohibited |
| `accepted` / `promoted` | prohibited | applies | prohibited (normative rule from `CONTEXT_BUNDLE_CONTRACT.md`) | prohibited | prohibited |
| `rejected` | prohibited | applies | prohibited | prohibited | prohibited |
| `revised` | applies | applies | n/a (a new bundle is assembled instead) | n/a (a regeneration replaces it) | applies |
| `activated` | conditional (deferred to [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943)) | conditional (deferred to [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943)) | conditional (deferred to [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943); bundle `exposed`/`consumed` is the lifecycle correlate) | conditional (deferred to [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943); mirrors do not "activate", they are retrieved) | conditional (deferred to [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943)) |
| `stale` | applies | applies | applies | applies | applies |
| `invalidated` | conditional (only by explicit superseding artifact) | applies | n/a (use `expired`) | n/a (use `stale`; rebuild from source) | n/a (follows target) |
| `archived` | applies | applies | applies (as `archived-for-audit`) | n/a (rebuildable; discard instead) | applies (follows target) |
| `regenerated` | prohibited | prohibited | prohibited (assemble a new bundle instead) | applies | applies |
| `discarded` | prohibited (use `archived`) | applies | applies | applies | applies |

This matrix is normative for lifecycle state vocabulary. The activation/use-right gating that hangs off each state is **not** defined here; it is deferred to [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943).

## 7. Transition model

### Allowed transitions per class

These are listed in Sections 5.1–5.5. The transition lists are not closed; future contracts may add transitions, but adding a transition that is currently `prohibited` requires an explicit amendment to this document.

### Prohibited transitions (category errors)

- Any transition that moves a human knowledge artifact into `candidate`, `reviewed`, `accepted/promoted`, or `rejected`. Human knowledge is authored, not reviewed-as-candidate.
- Any transition that moves a bridge/assembly artifact into `accepted/promoted`. Promoting a bundle is a category error; promote the bundle's *content* via the agentic-memory lifecycle instead.
- Any transition that moves a machine mirror into `reviewed`, `accepted/promoted`, or `rejected`. Mirrors are rebuildable projections; they carry no independent authority.
- Any transition that moves a companion metadata note into `candidate`, `reviewed`, `accepted/promoted`, or `rejected`. Companions are not themselves agentic memory candidates, even when they carry candidate-memory *references*.
- Any transition that uses `regenerated` for a human knowledge, agentic memory, or bridge artifact. Regeneration is a machine-mirror and companion-metadata concept.

### Ambiguous transitions deferred to other contracts

- The transition from `accepted/promoted` (memory) into being *used* in an agent turn is *activation*, governed by [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943). This document does not define when an accepted memory may be activated for `instructional` or `action_authorizing` use.
- The transition from `stale` back to `current` for a human knowledge artifact — i.e. whether the artifact is treated as current again after a re-validation — is the subject of `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`. This document only names `stale` as a state, not the re-validation policy.
- The transition from `stale → invalidated` for agentic memory in the presence of contradicting evidence is governed by `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` contradiction and staleness handling. This document only names the state.

## 8. Stale vs invalidated vs archived

These three words are commonly confused. They are not synonyms.

- **`stale`** — the artifact *may* no longer reflect current world, tools, context, or external reality. Stale **does not mean wrong**. A stale artifact must be *checked before use*; it does not have to be removed or rejected. Re-validation may move a stale artifact back to a current state. This is consistent with `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` §2.
- **`invalidated`** — the artifact has been *contradicted*, *superseded*, or *proven wrong*. An invalidated artifact must not instruct or authorize action without an explicit re-review. The original is retained with the invalidation reason; provenance is preserved per the receipts contract. Invalidation is a category-specific state: it applies in full to agentic memory; for human knowledge it requires an explicit superseding artifact; for bridges it is expressed as `expired`; for mirrors it manifests as `stale` plus regeneration or discard.
- **`archived`** — the artifact is *retained but out of active use*. Archival does not imply the artifact is wrong, stale, or invalidated. Archived artifacts remain inspectable, may carry historical authority, and are explicitly excluded from default activation. The archive boundary is a governance decision, not a temporal one.

A single artifact may carry combinations: an agentic memory artifact may be `accepted/promoted` and `stale`, or `revised` and `archived`. Combinations are governed by the per-class lifecycle and by the contracts in Section 2.

## 9. Regenerate vs discard semantics for machine mirrors

Machine mirrors are rebuildable technical projections. Their lifecycle has two operations that are easy to misread.

- **`regenerated`** — the mirror is rebuilt from its source (a human knowledge artifact or, when explicitly allowed, an agentic memory artifact). Regeneration may:
  - preserve the mirror's identity (same `artifact_id`, new `source_hash`, new `generated_at`), e.g. when only the source content changed; or
  - replace the mirror entirely with a new record, e.g. when the generator version or projection schema changed.
  In either case, **no knowledge is lost**: the source remains authoritative, and any prior receipts that referenced the old mirror remain inspectable.
- **`discarded`** — the mirror is removed. **This is a safe operation.** Discarding a machine mirror does *not* destroy source knowledge or authoritative memory because, by definition (`HUMAN_AND_AGENTIC_ARTIFACTS.md` §6), a mirror is rebuildable from higher-durability sources. If a "mirror" exists whose discard *would* lose information, it is not a mirror — it has been misclassified and must be reclassified into human knowledge or agentic memory before further changes.

These operations are **not** review operations. A regenerated mirror has not been "reviewed and accepted"; it has been rebuilt. A discarded mirror has not been "rejected"; it has been removed because the cache or projection was no longer wanted.

## 10. Companion note lifecycle behavior

Companion metadata notes have a parallel lifecycle (Section 5.5), not an embedded one. The key constraints:

- A companion may be **regenerated** independently of its target, but **may not replace** the target. The primary artifact remains authoritative for its own content.
- A companion may carry **candidate memory references** in a `synthesis_companion` or `mixed_companion` (per `COMPANION_NOTE_PATTERN.md` §8). Those candidate memories are themselves agentic memory artifacts and follow the agentic-memory lifecycle (Section 5.2). The companion does not "review" them.
- A companion that has accumulated human-authored content (e.g. human-review notes in a `review_companion`) **may not be silently discarded** by a regeneration cycle; managed-block boundaries from `COMPANION_NOTE_PATTERN.md` §10 govern this.
- A companion's `stale` state is driven by `target_hash` mismatch or by an explicit target change. Reconciliation, not review, is the normal correction path.

## 11. Examples

These examples are illustrative. They reference the artifact metadata samples in `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` §12 and the lifecycle states above. They are not a runtime schema and not a fixture set; concrete fixtures are the scope of [#941](https://github.com/RasmusTho/agentic-pkm-mvp/issues/941).

### 11.1 Human knowledge artifact

A concept note `Contextualization Layer.md` moves `created → working → settled`. The human revises it three months later: `settled → revised → working → settled`. Two years later the human knowledge artifact remains valuable but the surrounding system has changed; the note becomes `stale` without being wrong, in the sense of `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`. The human eventually moves it to `archived`. At no point did the note pass through `candidate` or `accepted/promoted` — those states do not exist for human knowledge.

### 11.2 Agentic memory artifact

A `preference_candidate` is materialised by an observation: `observed → candidate`. A review surface presents it; the human accepts it: `candidate → reviewed → accepted/promoted`. The accepted preference is used for several months. The human's preference changes; a new candidate contradicts it: the old preference is `revised` against the new evidence, the new candidate is reviewed and promoted, and the prior version is retained with `invalidated` plus provenance. The invalidated version is `archived` for audit. At no point did the activation of this preference for any specific agent turn become part of *this* lifecycle — that is the scope of [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943).

### 11.3 Bridge / assembly artifact

A context bundle `ctxb_2026-05-14_draft-metadata-contract` is `assembled` for a drafting task with `authority_flags.may_write: false`. It is `exposed` to the drafting agent and `consumed`. After two hours its `stale_after` passes; it becomes `stale` and then `expired`. Some of its included material was promoted into agentic memory via a separate `candidate → reviewed → accepted` cycle on the underlying memory artifacts. The bundle itself was **not** promoted; it moves to `archived-for-audit` because a receipt later refers to it. No `accepted/promoted` state ever applied to the bundle.

### 11.4 Machine mirror artifact

A chunked embedding record is `generated` from a human knowledge artifact and held as `current`. The human edits the source; `source_hash` no longer matches; the embedding becomes `stale`. The indexer rebuilds it: `stale → regenerated → current`. Later the projection schema changes; the embedding is `discarded` and a fresh embedding is `generated` from the same source. No knowledge was lost in any step, because the human knowledge artifact remained authoritative throughout.

### 11.5 Companion metadata note

A `synthesis_companion` for a project document is `created` when the synthesis pipeline first runs. It is `reconciled` against the project document on each subsequent ingest. A human edits the companion to remove a wrong derived link (`revised`). The project document is renamed; the companion's `target_path` is updated and the companion is `reconciled` against the new path. The companion's `Candidate Memories` section contains a candidate that is later reviewed and promoted into agentic memory — that promotion happens on the *candidate memory artifact*, not on the companion; the companion's own state moves `reconciled → revised` to reflect the removal of the now-promoted candidate from its pending list.

## 12. Non-runtime claims

This document defines lifecycle **semantics**, not lifecycle **implementation**.

- No state machine is wired here.
- No validator is required by this document.
- No watcher, scanner, or resolver is specified.
- No prompt template, retrieval recipe, or activation engine is implied.
- No database schema, migration, or storage backend is locked.

If a later runtime needs to enforce these states, it must add validators, tests, and guards in its own change, and that change must update the relevant owner doc to describe shipped reality. Until that happens, this document is target-state vocabulary.

## 13. Non-goals

This document is explicitly **not**:

- A formal state-machine specification.
- An activation, retrieval, or recall policy.
- A governance, authority, or trust model.
- A database or storage schema.
- A final frontmatter or on-disk shape.
- A fixture set — see [#941](https://github.com/RasmusTho/agentic-pkm-mvp/issues/941).
- A use-right or activation contract — see [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943).
- A claim that any of these states is currently enforced in runtime code.

## 14. Open questions

The following are deliberately left open. They are recorded so later contracts and implementation work can resolve them explicitly.

- **When does `stale` become `invalidated` automatically for an agentic memory artifact?** Or is automatic transition prohibited, requiring human or policy review every time?
- **What is the minimum review record needed for `candidate → accepted/promoted`?** Identity of reviewer, timestamp, rationale, or all three?
- **Should `archived` agentic memory remain retrievable by default**, or should retrieval require an explicit "include archived" flag? Likely the latter, but this is an activation-semantics question for [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943).
- **How is `revised` represented when the prior version must be retained for audit?** A linked predecessor `artifact_id`, an append-only revision log inside the companion, or a separate immutable record?
- **What is the policy for a `synthesis_companion` whose target has been archived?** Does the companion follow into archive automatically, or does it persist as a candidate-memory holding area?
- **Should bundle `expired` always require `archived-for-audit`**, or is a direct `expired → discarded` path acceptable when no receipt references the bundle?

These questions are not blockers for naming the lifecycle model. They are the first concrete decisions later contracts and implementation lanes will need to make.

## 15. Follow-up links

- [#941](https://github.com/RasmusTho/agentic-pkm-mvp/issues/941) — concrete fixtures that will instantiate this lifecycle vocabulary.
- [#943](https://github.com/RasmusTho/agentic-pkm-mvp/issues/943) — activation/use-right semantics built on top of these lifecycle states.
- [#900](https://github.com/RasmusTho/agentic-pkm-mvp/issues/900) — parent Agent Memory feature; tracks the broader implementation-preparation cluster.
