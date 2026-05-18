State: Initial metadata contract for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept contract
Authority: Names the minimal metadata fields, placement modes, and per-class metadata shapes used by the Contextualization Layer artifact classes. Not an ontology, not a governance/authority model, not a database schema, not a final frontmatter standard, not a runtime implementation plan.

# Artifact Metadata Contract for the Contextualization Layer

## 1. Purpose

This document defines a **minimal metadata contract** for the artifact classes introduced in `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md`.

Its job is to make it possible for the system to distinguish and support the different artifact classes — without each surface inventing its own metadata vocabulary, and without locking down details that should remain open for later contract and implementation work.

This document is explicitly:

- **Not a full ontology.** Domain-level meaning (notes, concepts, projects, decisions, sources, agents, commitments, …) remains owned by the existing concept contracts under `docs/CONCEPTS/`.
- **Not a governance or authority model.** Trust tiers, write gating, and authority limits live in `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, and adjacent contracts.
- **Not a database schema.** No tables, no migrations, no indexes are defined here.
- **Not a runtime implementation.** No code paths, no readers, no writers, no validators are wired here.
- **Not a final frontmatter standard.** Field names below are logical; their on-disk form is a downstream decision.
- A **documentation-level contract** that future implementation and validation work can attach to.

## 2. Relationship to the Artifact Model

This contract sits directly on top of `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` and reuses its vocabulary without restating it. For metadata purposes the relevant artifact classes are:

- **Human Knowledge Artifact** — what the human writes and owns. Primary audience is the human.
- **Agentic Memory Artifact** — system-maintained supporting material that helps an agent remember, explain, and continue work. Primary audience is mixed human + agent.
- **Bridge / Assembly Artifact** — per-use selections that carry context between memory/knowledge and active cognition. The canonical example is a context bundle.
- **Machine Mirror Artifact** — rebuildable technical projections (chunks, embeddings, indexes, caches, search results, graph projections).

Two invariants from the prior doc are load-bearing for everything below:

- **Markdown is the shared substrate, not the shared semantics.** Two `.md` files in the same folder can be three different kinds of object; the metadata is what tells the system which is which.
- **Context bundles are bridge / assembly artifacts, not agentic memory.** A bundle may contain, reference, or be assembled from agentic memory artifacts, but it does not inherit their lifecycle or activation semantics. The metadata shape for bundles in Section 7 follows this rule.

Note: the prior doc's Section 3 names three *initial* classes; bridge / assembly is carved out as a boundary inside the agentic memory section and as a separate row in the durability table. This metadata contract treats bridge / assembly as a fourth class with its own metadata shape, which is consistent with that boundary and does not reopen the vocabulary.

This contract also covers the expanded life-wide artifact taxonomy introduced in `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md`. That document names the concrete artifact sub-classes a life-wide PKM must support across all life areas — from ephemeral `shopping_list` and `email_summary` artifacts to durable `evergreen_note`, `decision_record`, and `media_note` artifacts, through agentic memory candidates and machine mirrors. The `artifact_class` values, lifecycle postures, authority flags, provenance kinds, and work-relation values in Sections 4–8 below align with and are informed by that taxonomy. When the taxonomy's authority / provenance / work-relation axes and this contract appear to diverge, the taxonomy governs the conceptual intent; this contract governs the field-level expression.

The taxonomy's Section 14 ("Implications for future work") explicitly lists updating this contract as the first required follow-up. This revision delivers that update.

## 3. Metadata Placement Principles

Not all metadata belongs in the same place. This contract defines three placement modes. The same logical field may move between modes depending on artifact class and intended audience.

### 3.1 Inline Minimal Frontmatter

Used when metadata is human-meaningful and does not pollute the primary reading experience of the note.

Typical examples:

- `title`
- `artifact_class`
- `artifact_type`
- `status` / `maturity`
- `created`
- `updated`
- human-facing `tags`

Rule of thumb: if a reader would expect to see the field when opening the note, it can sit inline.

### 3.2 Companion Metadata Note

Used when metadata is useful for the agent / system but would clutter a primary human note. The companion lives alongside the primary note (the exact location convention is left to `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` and to later companion-location work).

Typical examples:

- processing state (e.g. last ingest, last hash, error state)
- `activation_policy`
- retrieval hints and tuning fields
- derived / machine-suggested links
- `stale_after`
- `last_activated`, `activation_count`
- source mapping back to ingested raw material
- candidate memory references

Rule of thumb: if the field exists for the system's benefit and a human reader would find it visually noisy, it belongs in the companion.

### 3.3 Structured Agentic Artifact

Used for agentic memory artifacts and bridge / assembly artifacts. Here the artifact itself is *both* human-readable and machine-usable; its metadata is part of the artifact, not bolted onto a primary human note.

Typical examples:

- task snapshot
- activation trace
- reflection record
- synthetic summary
- preference candidate
- context bundle (bridge / assembly)

Rule of thumb: if the artifact only exists because the system needed it, but a human must still be able to read and correct it, it is a structured agentic / bridge artifact and carries its own metadata.

## 4. Shared Minimal Fields

A small set of fields can recur across artifact classes. None of them are mandatory for every artifact; they are reusable building blocks.

| Field | Meaning |
| --- | --- |
| `artifact_id` | Stable identifier for the artifact across renames and moves. May be a UUID, hash, or other stable token. |
| `artifact_class` | One of `human_knowledge`, `agentic_memory`, `bridge_artifact`, `machine_mirror`, `companion_metadata`. |
| `artifact_type` | Sub-type within the class (e.g. `concept_note`, `task_snapshot`, `context_bundle`, `embedding_record`). |
| `title` | Short human-readable label. |
| `created` | When the artifact came into existence. |
| `updated` | Last meaningful change. |
| `author_type` | `human`, `agent`, `system`, or `mixed`. |
| `primary_audience` | `human`, `agent`, `system`, or `mixed`. |
| `source_refs` | References to the artifacts this one is grounded in or derived from. |
| `review_state` | Posture toward human review (e.g. `unreviewed`, `reviewed`, `accepted`, `rejected`). |
| `lifecycle` | Stability and retention posture: `ephemeral`, `active`, `durable`, `archived`, `rebuildable`. |
| `authority` | Trust and action boundary. A map or set of flags; see Section 4.1. |
| `provenance` | Where the artifact or its claims originated. See Section 4.1 and Section 11. |
| `work_relation` | Why the artifact exists in the workflow: `capture`, `orient`, `decide`, `execute`, `learn`, `create`, `remember`, `resurface`, `communicate`. |
| `privacy` | Privacy posture: `private`, `review-required`, `internal`. Relevant especially for media, contact, financial, and screenshot artifacts. |
| `review` | Whether the artifact is pending or has undergone human review. |
| `review_on` | Scheduled or condition-based review date. |
| `review_reason` | Why this artifact is flagged for review. |

These are **logical fields**. They may live inline in a primary note, in a companion metadata note, inside a structured agentic / bridge artifact, or in another documented metadata surface introduced later. Where they live is governed by Section 3, not by this list.

### 4.1 Dimension independence

The fields above capture distinct, non-substitutable axes. Collapsing any two of them is an anti-pattern. None of them may be inferred from folder path, Markdown format, or MOC membership.

- **`artifact_class`** — the broad semantic artifact family (`human_knowledge`, `agentic_memory`, `bridge_artifact`, `machine_mirror`, `companion_metadata`). For life-wide PKM artifacts, the value often names a concrete taxonomy class directly (e.g. `shopping_list`, `email_summary`, `evergreen_note`). Class is not determined by where the file lives.
- **`artifact_type`** — the concrete form or subtype within a class (e.g. `concept_note`, `task_snapshot`, `context_bundle`, `embedding_record`). For life-wide taxonomy classes whose `artifact_class` name is already specific, `artifact_type` names a further subdivision only when needed.
- **`memory_type`** — the cognitive class of an agentic memory artifact (`working_context`, `episodic_memory`, `semantic_memory`, `prospective_memory`, `procedural_memory`, `preference_memory`, `policy_memory`). This axis applies only to `agentic_memory` artifacts and must not be conflated with `artifact_type`. The two are orthogonal: the same form can carry different cognitive classes, and the same cognitive class can take different forms.
- **`lifecycle`** — the stability and retention posture (`ephemeral`, `active`, `durable`, `archived`, `rebuildable`). A folder or MOC is not a lifecycle. Promotion from `ephemeral` or `active` into `durable` is governance-bearing; see `LIFE_WIDE_ARTIFACT_TAXONOMY.md` Section 4.
- **`authority`** — the trust and action boundary. Flags include `human_authored`, `ai_generated`, `source_authoritative`, `governance_bearing`, `requires_review`, `agent_editable`. A folder path, a Markdown heading, an AI-generated summary, or MOC membership is not authority.
- **`provenance`** — where the artifact or its claims originated. Provenance is distinct from authority: an artifact may have clear provenance (an AI summary knows its source) but remain non-authoritative. Provenance kinds: `user_authored`, `own_photo`, `own_screenshot`, `own_scan`, `email_thread`, `youtube_url`, `web_article`, `book`, `pdf`, `ai_summary`, `ai_caption`, `ai_extraction`, `machine_index`.
- **`work_relation`** — why the artifact exists in the workflow. A note whose `work_relation` is `orient` must not be silently mutated the way a note whose `work_relation` is `execute` may be under explicit instruction.

### 4.2 Required, recommended, and optional by artifact family

The table below states a default field posture. "Required" means a conformant artifact should carry the field. "Recommended" means expected for most artifacts in the family. "Optional" means it may be omitted. "—" means the field does not apply to this family. No runtime enforcement is defined here.

| Field | HK | AM | BA | MM | CN |
| --- | --- | --- | --- | --- | --- |
| `artifact_class` | Required | Required | Required | Required | Required |
| `artifact_type` | Recommended | Recommended | Required | Recommended | Recommended |
| `title` | Required | Required | Recommended | Optional | Recommended |
| `lifecycle` | Recommended | Required | Recommended | Required | Recommended |
| `authority` | Recommended | Required | Required | Required | Required |
| `provenance` | Recommended | Required | Required | Optional | Recommended |
| `work_relation` | Recommended | Recommended | Recommended | Optional | Optional |
| `privacy` | Optional | Optional | Optional | Optional | Optional |
| `review` / `review_state` | Optional | Required | Optional | Optional | Optional |
| `created` / `updated` | Recommended | Required | Required | Required | Recommended |
| `source_refs` | Optional | Required | Required | Required | Optional |
| `memory_type` | — | Required | — | — | — |
| `confidence` | — | Recommended | — | — | — |
| `stale_after` | Optional | Required | Required | Optional | Optional |
| `activation_policy` | — | Required | — | — | Optional |

HK = Human Knowledge Artifact, AM = Agentic Memory Artifact, BA = Bridge / Assembly Artifact, MM = Machine Mirror Artifact, CN = Companion Metadata Note.

### 4.3 AI-generated metadata rules

These rules apply to any field or artifact that AI has produced or may produce. They are normative for this contract and consistent with `LIFE_WIDE_ARTIFACT_TAXONOMY.md` Section 12.

**Non-authoritativeness by default.** AI-generated metadata and AI-generated artifacts are non-authoritative by default. An AI-generated field does not carry the weight of human-authored knowledge unless a human or governed process has explicitly reviewed and promoted it.

**Allowed AI actions.** AI may suggest classification, captions, summaries, provenance hints, tags, link candidates, `memory_type` assignments, and draft companion notes. AI may create agentic memory candidates and machine mirror artifacts outright. AI may edit fields that are explicitly scoped as `agent_editable` in the `authority` map.

**What AI must not do.**
- AI must not silently promote source material into durable human knowledge (`evergreen_note`, `synthesis_note`, `decision_record`).
- AI must not silently mutate governance-bearing metadata (lifecycle classification, authority assertions, `decision_record` content, classification fields that drive downstream behavior).
- AI must not treat an `ai_suggestion` artifact or an unreviewed agentic memory candidate as authoritative knowledge.
- Where authority, lifecycle, classification, or cross-note effects are involved, AI must queue a proposal rather than commit a change.

**Marking AI-generated fields.** When individual fields in an otherwise human-owned artifact are AI-generated, they should be grouped or marked as such (e.g. an `ai_generated_fields` list in the `authority` block, or by carrying those fields in a companion note rather than inline).

**Promotion path.** Promotion from `ai_suggestion` or unreviewed agentic memory into a durable Human Knowledge Artifact requires explicit human review or a governed process. `review_state: queued` is the expected staging state before review; promotion produces a different artifact class, not a mutation of the suggestion in place.

## 5. Human Knowledge Artifact Metadata

### Recommended inline metadata (primary note)

- `title`
- `artifact_class` — for life-wide HK artifacts, the `artifact_class` value names the concrete taxonomy class directly: `evergreen_note`, `source_note`, `literature_note`, `synthesis_note`, `decision_record`, `reflection_note`, `project_note`, `area_dashboard`, `daily_log`, `shopping_list`, `checklist`, `media_note`, `screenshot_note`, `scan_or_receipt_note`, `email_summary`, `youtube_source_note`, `contact_note`, `fleeting_capture`. The value `human_knowledge` remains acceptable as a catch-all when the specific sub-class is not yet determined.
- `artifact_type` — a further subdivision within the class when the `artifact_class` alone is not specific enough (e.g. `artifact_class: media_note` + `artifact_type: photo`).
- `lifecycle` — for human knowledge artifacts: `ephemeral` (shopping list, fleeting capture), `active` (project note, email summary), or `durable` (evergreen, decision record). Not needed on every note but meaningful on anything with a non-obvious retention horizon.
- `status` or `maturity` (e.g. `draft`, `working`, `settled`)
- `created`
- `updated`
- `tags` — only when useful for **human** navigation
- `work_relation` — optional; only when the artifact's role is non-obvious from its class (e.g. `work_relation: decide` on a note whose class alone does not make that clear).
- `privacy` — optional; include for artifacts containing personal, financial, health, or sensitive data.

The bar for adding a field to a primary human note: a human reader would find the field meaningful and not visually noisy.

### Belongs in a companion metadata note, not the primary note

- `activation_policy`
- `authority` details and AI-generated field lists
- `provenance` details beyond a simple `source_refs` pointer
- retrieval scores and ranking signals
- processing state (ingest result, content hash, parser version)
- embedding / chunk metadata
- agent annotations and machine-suggested links
- `last_activated`, `activation_count`
- noisy machine-derived link lists
- candidate memory references awaiting review
- `review_on`, `review_reason` when these are system-managed rather than human-authored

### Example

Primary note `Contextualization Layer.md`:

```yaml
---
artifact_class: human_knowledge
artifact_type: concept_note
title: Contextualization Layer
maturity: working
created: 2026-05-14
updated: 2026-05-14
---
```

Companion metadata note (location convention out of scope here):

```yaml
---
artifact_class: companion_metadata
target: ./Contextualization Layer.md
target_artifact_class: human_knowledge
activation_policy: explicit_or_contextual
last_processed:
last_activated:
derived_links: []
candidate_memories: []
---
```

These examples are illustrative. The final on-disk shape (field names, file naming, location, separator characters) is a downstream contract decision and is not locked here.

## 6. Agentic Memory Artifact Metadata

### Recommended metadata

- `artifact_class: agentic_memory`
- `memory_type` — the cognitive class (see below)
- `artifact_type` — the form the memory artifact takes (see below)
- `title`
- `purpose`
- `source_refs` or `derived_from`
- `confidence`
- `validity`
- `stale_after` or `expires_at`
- `activation_policy`
- `allowed_consumers`
- `human_review`
- `last_activated`
- `activation_count`

`memory_type` and `artifact_type` capture two independent dimensions: *what kind of memory this is* and *what shape the memory artifact takes*. The same form can carry different cognitive classes; the same cognitive class can be expressed in several forms.

### Allowed `memory_type` values (canonical cognitive classes)

These mirror the memory classes defined in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`:

- `working_context` — short-lived recall used during an active task or interaction.
- `episodic_memory` — that something happened, when, and in what situation.
- `semantic_memory` — stabilized meaning the system can reuse across situations (the canonical contract calls this "semantic knowledge"; named `semantic_memory` here for symmetry with the other classes).
- `prospective_memory` — future-oriented obligations or intentions (commitment, reminder, waiting state, candidate action).
- `procedural_memory` — repeated ways of doing something, versioned or traceable when used to drive repeated action.
- `preference_memory` — stable or semi-stable user preferences, defaults, and styles.
- `policy_memory` — boundaries, permissions, and safety rules that govern what the system may do (the canonical contract calls this "policy / authority memory").

`context_bundle` is **not** a `memory_type`. See Section 7.

### Common `artifact_type` values for agentic memory artifact forms

These are common forms an agentic memory artifact may take. The list is illustrative, not closed:

- `task_snapshot`
- `synthetic_summary`
- `reflection_record`
- `activation_trace`
- `preference_candidate`
- `procedural_hint`

Form is orthogonal to cognitive class. A `task_snapshot` may carry `working_context` (active task state), `episodic_memory` (what happened so far), or `prospective_memory` (what is still owed) depending on the intent of the snapshot.

### Required properties of any agentic memory artifact

- human-readable
- human-editable
- organized in a way a human can grasp (folder structure, file naming, links)
- clearly marked as agent- or system-generated unless authored by a human

Agentic memory artifacts that fail any of the above stop being agentic memory and become machine mirrors (Section 8); their metadata should be migrated accordingly rather than left in an ambiguous state.

## 7. Bridge / Assembly Artifact Metadata

Bridge / assembly artifacts assemble or carry context between memory / knowledge and active cognition. They are per-use selections, not retained memory.

### Examples

- `context_bundle`
- `working_context_snapshot`
- `execution_context_bundle`
- `reorientation_bundle`

### Recommended metadata

When the bridge artifact is a `context_bundle`, the metadata shape below tracks the required field set in `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` so bundles produced under this contract remain inspectable *and* governable.

- `artifact_class: bridge_artifact`
- `artifact_type` (one of the examples above, or a later-named subtype)
- `artifact_id` (from Section 4 — the bundle's stable identity)
- `purpose` / `intended_use`
- `trigger` (what caused the bundle to be assembled)
- `scope` (the operational scope, sphere, or task the bundle applies to)
- `assembled_for` (the task, surface, or agent this bundle was built for)
- `assembled_at` (creation time)
- `source_refs`
- `included_artifacts`
- `excluded_artifacts` *(optional, but treated as part of provenance when present — see the contract)*
- `construction_method` (how the bundle was assembled — retrieval, orientation, resurfacing, hand-built, etc.)
- `validity`
- `stale_after` / `expiry`
- `authority_flags` — a map declaring what the bundle may support. At minimum:
  - `may_answer`
  - `may_orient`
  - `may_resurface`
  - `may_propose`
  - `may_write`
- `consumed_by`
- `receipts` (why the bundle exists and how it was used; see `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` "Relation to provenance and receipts")
- `outcome_ref` *(optional — pointer to what the bundle was used to produce)*

These authority flags are separate permissions: a bundle may support an answer without supporting writeback. Omitting them produces an inspectable bundle that no longer records what authority the selected context carries, which the canonical contract treats as non-conformant.

### Boundary rules

- A bridge artifact **may** contain or reference agentic memory artifacts.
- A bridge artifact **is not itself** an agentic memory artifact.
- A bridge artifact **must not** inherit long-term memory semantics unless its content has been explicitly promoted into a memory artifact through the normal promotion path.

This mirrors the boundary already stated in `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` Section 5 and the durability split in its Section 8.

## 8. Machine Mirror Metadata

Machine mirror artifacts are rebuildable technical projections of human knowledge or agentic memory.

### Examples

- `chunk`
- `embedding_record`
- `vector_index_entry`
- `graph_projection`
- `cache_entry`
- `search_result`

### Recommended metadata

- `source_ref`
- `source_hash`
- `generated_at`
- `generator` (model / pipeline / version)
- `index_name`
- `projection_type`
- `rebuildable: true`

### Boundary rules

- Machine mirrors are **not** human knowledge artifacts.
- Machine mirrors are **not** authoritative; their authority is the authority of their source.
- Machine mirrors should be disposable and rebuildable from higher-durability artifacts.
- Machine mirrors should not be manually edited as knowledge. Manual edits that need to survive belong in the source artifact, not in the mirror.

## 9. Use Rights Metadata

The artifact model already names five use-right levels:

- `visible`
- `retrievable`
- `activatable`
- `instructional`
- `action_authorizing`

For this contract, these are **descriptive metadata hooks**, not enforced governance rules. The runtime is free to ignore them until a later authority/governance contract grants them enforcement weight.

Illustrative defaults:

- A human decision record may be `visible`, `retrievable`, `activatable`, and `action_authorizing`.
- An unreviewed agent reflection may be `visible` and `retrievable`, but not `instructional`.
- A stale task snapshot may be `visible` and `retrievable`, but not `activatable`.
- A machine mirror may be `retrievable` by the system but not `action_authorizing`.

These defaults are examples, not requirements. The rules for granting each right belong to a later contract.

## 10. Staleness and Validity

Common fields for temporal validity:

- `validity` (free-form posture, e.g. `current`, `stale`, `invalidated`)
- `valid_from`
- `valid_until`
- `stale_after`
- `last_validated`
- `invalidated_by`

These fields matter most for artifacts whose usefulness changes over time:

- task snapshots
- preference memories
- procedural hints
- context bundles
- project status summaries

**Stale does not mean wrong.** It means *must be checked before use.* Surfaces that consume stale artifacts should re-validate rather than silently refuse, and the human-visible behavior of stale artifacts is a downstream UI decision.

This section is consistent with, and downstream of, `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`.

## 11. Provenance and Derivation

Common fields for provenance:

- `source_refs`
- `derived_from`
- `derivation_method`
- `generated_by`
- `human_review`
- `confidence`

These fields exist so that consumers can distinguish:

- a **source-backed claim** — `source_refs` point to authoritative material, `derivation_method` is `direct_quote` or `paraphrase`.
- an **agent-generated summary** — `generated_by` names an agent, `derivation_method` is `summarization`, `human_review` is typically `unreviewed`.
- a **human-authored note** — `author_type: human`, `generated_by` empty or naming the human.
- an **imported source** — `derived_from` references an external system, `derivation_method` is `import`.
- an **inferred candidate memory** — `generated_by` names an agent, `confidence` is present, `human_review: unreviewed`.

The point is to keep these categories separable, not to lock the field set.

## 12. Examples

These four examples are illustrative. Field names, file naming, and on-disk layout are not normative here.

### 12.1 Human primary note with minimal frontmatter

```yaml
---
artifact_class: human_knowledge
artifact_type: concept_note
title: Contextualization Layer
maturity: working
created: 2026-05-14
updated: 2026-05-14
---
```

### 12.2 Companion metadata note for the same human note

```yaml
---
artifact_class: companion_metadata
target: ./Contextualization Layer.md
target_artifact_class: human_knowledge
activation_policy: explicit_or_contextual
last_processed: 2026-05-14T18:30:00Z
last_activated:
activation_count: 0
derived_links: []
candidate_memories: []
---
```

### 12.3 Agentic task snapshot

```yaml
---
artifact_class: agentic_memory
memory_type: working_context
artifact_type: task_snapshot
title: Drafting Contextualization Layer metadata contract
purpose: Resume drafting work without re-deriving context.
source_refs:
  - docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md
derived_from: chat_session:2026-05-14T18:10:00Z
confidence: medium
validity: current
stale_after: 2026-05-21
activation_policy: on_resume
allowed_consumers: [drafting_agent, panel]
human_review: unreviewed
last_activated:
activation_count: 0
---
```

### 12.4 Bridge context bundle

```yaml
---
artifact_class: bridge_artifact
artifact_type: context_bundle
artifact_id: ctxb_2026-05-14_draft-metadata-contract
purpose: Provide focused context for the metadata-contract drafting task.
trigger: task_start:draft_metadata_contract
scope: contextualization_layer.docs_authoring
assembled_for: task:draft_metadata_contract
assembled_at: 2026-05-14T18:25:00Z
source_refs:
  - docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md
  - docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md
included_artifacts:
  - docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md
  - docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md
excluded_artifacts: []
construction_method: retrieval+orientation
validity: current
stale_after: 2026-05-14T20:00:00Z
authority_flags:
  may_answer: true
  may_orient: true
  may_resurface: true
  may_propose: true
  may_write: false
consumed_by: drafting_agent
receipts:
  - bundle_created:2026-05-14T18:25:00Z
outcome_ref:
---
```

The bundle references agentic memory and human knowledge artifacts but does not become an agentic memory artifact itself. The `authority_flags` block makes the bundle governable: in this example the bundle is allowed to support answering, orientation, resurfacing, and proposing, but is **not** allowed to authorize a writeback.

### 12.5 Evergreen note

Durable, atomic human knowledge. Distinct from any source, literature, or AI-summary layer.

```yaml
---
artifact_class: evergreen_note
title: Contextualization separates substrate from semantics
lifecycle: durable
work_relation: learn
authority:
  human_authored: true
  ai_generated: false
  governance_bearing: false
created: 2026-05-18
updated: 2026-05-18
---
```

An AI may suggest a link or flag a potential contradiction but must not rewrite this artifact. It is already durable and does not require lifecycle promotion.

### 12.6 Source note and literature note (distinction)

These are two distinct artifacts. Collapsing them loses the authority boundary.

```yaml
# source_note — the book as artifact; source itself remains the authority
---
artifact_class: source_note
title: "Shape Up — Ryan Singer"
lifecycle: durable
work_relation: learn
provenance: book
authority:
  source_authoritative: false   # the published book holds source authority
  human_authored: true
  ai_generated: false
---

# literature_note — what the author says, in the user's words; not the user's own claims
---
artifact_class: literature_note
title: "Shape Up — chapter 2 paraphrase"
lifecycle: durable
work_relation: learn
source_refs:
  - "[[Shape Up — Ryan Singer]]"
authority:
  human_authored: true
  ai_generated: false
  source_authoritative: false   # faithful restatement, not the source itself
---
```

A `literature_note` is input to an `evergreen_note` or `synthesis_note`, not a substitute for it.

### 12.7 Media note

Authority remains in the original media file. AI captions and extracted fields are non-authoritative.

```yaml
---
artifact_class: media_note
artifact_type: photo
lifecycle: durable
work_relation: remember
provenance:
  source_kind: own_photo
  source_file: /Media/Photos/2026/20260518_kitchen-panel.jpg
ai_caption: "Oak veneer panel test leaning against kitchen wall."
human_caption: "Test of natural oak veneer against existing oak floor — sample looks good."
authority:
  human_authored: true
  ai_generated_fields:
    - ai_caption
  source_authoritative: false   # the photo file is the source authority
privacy: private
created: 2026-05-18
---
```

The `source_file` path is the authoritative record; the vault note carries human context and non-authoritative AI-derived fields.

### 12.8 Email summary

The email thread in the provider is the authority. This note is non-authoritative by default.

```yaml
---
artifact_class: email_summary
lifecycle: active
work_relation: orient
provenance:
  source_kind: email_thread
  provider: gmail
  thread_id: "<gmail thread id>"
authority:
  source_authoritative: false
  ai_generated: true
  requires_review: true
review_state: unreviewed
created: 2026-05-18
---
```

Actions, decisions, and references extracted from this summary MAY be promoted into separate artifacts via explicit review. The summary itself is not knowledge.

### 12.9 Shopping list

Ephemeral and operational. Not evergreen by default; the list does not become durable knowledge.

```yaml
---
artifact_class: shopping_list
lifecycle: ephemeral
work_relation: execute
authority:
  human_authored: true
  ai_generated: false
  governance_bearing: false
  agent_editable: true   # checking items off is agent-editable under explicit instruction
created: 2026-05-18
---
```

Patterns extracted from many shopping lists MAY be promoted into a durable preference or reference note via explicit human review, but the list itself is operational and not retained as knowledge.

### 12.10 Agentic memory candidate (unreviewed)

AI-produced candidate awaiting human promotion. Non-authoritative until reviewed.

```yaml
---
artifact_class: agentic_memory
artifact_type: preference_candidate
memory_type: preference_memory
title: "Preferred note length: concise atomic claims over long summaries"
purpose: Proposed preference candidate derived from session observations.
derived_from: session:2026-05-18T10:00:00Z
confidence: medium
lifecycle: active
authority:
  ai_generated: true
  human_authored: false
  requires_review: true
review_state: queued
review_reason: AI-derived preference candidate; human confirmation required before activation.
stale_after: 2026-06-18
activation_policy: review_required
allowed_consumers: []
---
```

This candidate does not enter the `activation_policy` flow until `review_state` is promoted to `accepted` by a human or governed process.

### 12.11 Machine mirror

Rebuildable, system-derived, non-authoritative. Must not be manually edited as knowledge.

```yaml
---
artifact_class: machine_mirror
artifact_type: embedding_record
lifecycle: rebuildable
source_ref: docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md
source_hash: sha256:...
generated_at: 2026-05-18T12:00:00Z
generator: text-embedding-3-small/v1
index_name: vault_semantic_index
projection_type: dense_embedding
rebuildable: true
authority:
  system_authoritative: true
  human_authored: false
  source_authoritative: false
---
```

The mirror's authority is the authority of its source. Deleting this record and regenerating it from the source produces an equivalent artifact.

## 13. Non-goals

This document does **not**:

- define a full ontology or domain model,
- define a governance, authority, or trust model,
- define a database schema or migration plan,
- define a final frontmatter standard,
- define a prompt template or retrieval recipe,
- define a runtime implementation plan or roadmap commitment,
- decide that all metadata must live in Markdown frontmatter — companion notes, sidecar files, runtime state, and other surfaces remain valid carriers.

## 14. Open Questions

The following are deliberately left open. They are recorded so later work can resolve them explicitly rather than by accident.

- **Which fields should eventually be validated by docs tooling?** What is the minimal validation surface that catches mis-classified artifacts without burdening human notes?
- **Which companion metadata files should be generated automatically**, and which require an explicit human or agent action?
- **Which agentic memory artifacts require human review before activation?** In particular, which subtypes may carry `instructional` or `action_authorizing` rights without a review step?
- **How should stale metadata be surfaced in the human UI?** Quiet expiry, visible badge, prompt-on-use, or active review queue?
- **Which metadata should sync across devices and which can remain local / rebuildable?** Durability tier is a strong input but not the only one — privacy, cost, and device role also matter.
- **Should bridge artifacts be retained, rotated, or summarized?** And under what conditions should a bridge artifact's content be promoted into an agentic memory artifact?

These questions are not blockers for naming the metadata contract. They are the first concrete things later contracts and implementation lanes will need to answer once this vocabulary is in use.
