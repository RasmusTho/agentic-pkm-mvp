State: Concept contract companion (normalized vocabulary and concept-drift map; implementation-aware but ontology-led).

# Ontology Vocabulary — canonical terms and drift map

## Purpose

This document normalizes the most important terms used across the repo.

It answers:
- which term should be canonical,
- which existing terms are overloaded or ambiguous,
- which ontology layer a term belongs to,
- how implementation terms should be interpreted without letting them redefine the domain.

This document is subordinate to:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
- `docs/PROJECT_KERNEL.md`

For the **field-level and semantic-layer-ownership** view of artifact/runtime/governance
terminology (`artifact_class`, `artifact_type`, `memory_type`, `kind`, `mirror`, runtime/workspace
state, etc.), see the companion `docs/CONCEPTS/ARTIFACT_TERMINOLOGY_NORMALIZATION.md`, which is
subordinate to this document for domain terms and aligns terminology to the seven semantic layers in
`docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.

## Usage rule

When a term appears in multiple ontology layers, the canonical human-first meaning wins.
Implementation terms may remain in code and migration-era docs, but should be interpreted through the vocabulary below.

Temperature/storage metaphors such as `hot`, `warm`, `cool`, `cold`, and sometimes `archive`
should not carry canonical semantics by themselves.
Current repo working language may use:
- `writing surface` / `writing plane`
- `retention surface` / `retention plane`
- `retained artifact`

Important:
- this memo does **not** treat those terms as settled field-standard language,
- only as current repo-level working language pending further semantic refinement,
- see `docs/research/cognitive-semantics-literature-memo.md`.

## Canonical vocabulary

| Canonical term | Ontology layer | Definition | Prefer over | Avoid / constrain |
| --- | --- | --- | --- | --- |
| `Actor` | Actor | Something that can participate in processes and carry attribution. | ad hoc use of "source" or "component" for agency | Treating every emitter as an ontological agent without qualification |
| `Human` | Actor | The primary bearer of meaning, authority, and accountability. | "user" when meaning/authority is central | Reducing the human to just an API caller |
| `System Agent` | Actor | A bounded assisting actor that can observe, propose, retrieve, transform, plan, or execute within limits. | runtime component names when discussing agency in general | Using "agent" for every helper, pipeline, or service without clarifying role |
| `Delegation` | Provenance / accountability | A bounded authorization from a human to a system agent. | implicit "auto-run" framing | Treating automation as authority-free |
| `Sphere` | Context structure | An overlapping region of human life, concern, practice, or meaning. | `domain` when the point is lived belonging | Treating human context as an exclusive bucket by default |
| `Situated Role Identity` | Context structure / relation | The mode of self, tone, responsibility, and judgment active in a situation. | vague `persona` talk when role-bound meaning is central | Requiring a heavy identity engine just to acknowledge role-sensitive use |
| `Context` | Context structure | A situated configuration of currently relevant spheres, role identities, purposes, commitments, and constraints. | `domain` when the point is what is relevant right now | Treating all context as long-lived static classification |
| `Shared Participation` | Context relation | The relation by which an artifact, commitment, or concern meaningfully belongs to more than one sphere or context. | `bridge` when the point is overlap in meaning | Treating overlap as if it exists only after a runtime permission object is created |
| `Operational Scope` | Boundary / runtime-facing context term | A narrower working boundary used for retrieval, action gating, path defaults, and similar runtime behavior. | broad human use of `domain` when runtime scope is what is meant | Letting operational scope pretend to be the whole human model |
| `Explicit Cross-Scope Allowance` | Boundary / permission relation | A bounded, auditable permission for persistent or reusable crossing between operational scopes. | `bridge` when the permission function should be explicit | Treating the allowance as the primary human mental model of overlap |
| `Cognitive Artifact` | Artifact | Any persistent or semi-persistent object used in thinking, creating, remembering, planning, or orienting. | "object" as a general domain word | Using "object" as if it were already semantically clear |
| `Projection` | Representation / boundary | A bounded representation of an artifact for a runtime, store, search, mirror, or API purpose. | raw `object` when representation is what is meant | Treating a projection as the whole artifact |
| `Work Artifact` | Artifact | A cognitive artifact used to advance work or thinking. | generic "note" when the artifact is not specifically a vault note | Collapsing all work artifacts into notes |
| `Retained Artifact` | Artifact | Current repo working term for a cognitive artifact preserved for long-horizon retention, rediscovery, citation, or later reuse without requiring immediate note conversion. | `archive artifact`, `cold object` when functional meaning matters | Letting storage-temperature metaphors define the concept or treating this wording as more literature-settled than it is |
| `Source Role` | Role / epistemic relation | The role an artifact plays when used as evidence, grounding, or reference in a context. | broad unqualified `source` when epistemic role is what matters | Treating sourcehood as always intrinsic |
| `Creative Artifact` | Artifact | A cognitive artifact for generative or exploratory creative work. | forcing creative material into "knowledge" vocabulary | Assuming all artifacts are propositional knowledge |
| `Project Artifact` | Artifact | A cognitive artifact tied to a project or multi-step effort over time. | generic "document" | Treating project structure as just tags or metadata |
| `Reflective Artifact` | Artifact | A cognitive artifact used for reflection, self-observation, or learning. | "journal note" when broader reflection is intended | Implicitly treating reflection as therapy-only |
| `System Artifact` | Artifact | An artifact whose primary purpose is coordination, traceability, or explainability. | "log" or "mirror" when speaking generally | Treating system artifacts as human-authored meaning |
| `Mirror Artifact` | Artifact / projection-facing specialization | A portable machine-side projection of a human-facing artifact with selected metadata/history. | vague `note log` or raw `mirror` when portability/projection is meant | Treating the mirror as the primary human artifact |
| `Receipt Artifact` | Artifact / accountability specialization | A human-legible system artifact that records what happened, with what authority, and with what result. | generic `log` when accountability is meant | Treating receipts as backend-only diagnostics |
| `Execution Artifact` | Artifact / process specialization | A generated artifact used to coordinate or record execution rather than to serve as a human project or note. | overloading `plan` or `run` | Treating execution artifacts as human commitments by default |
| `Vault Note` | Artifact / implementation-facing specialization | A human-facing editable artifact in the current repo working concept of a writing plane, typically represented as a vault markdown note. | generic "note" when writing-surface specificity matters | Using "note" to mean every artifact in the system |
| `Writing Plane` | Boundary / plane | Current repo working term for the primary human-facing editable writing surface. | `warm plane` when the functional meaning matters | Treating temperature metaphor as canonical or treating this wording as final field-backed ontology |
| `Retention Plane` | Boundary / plane | Current repo working term for the retained-material surface for rediscovery, inspection, citation, and later reuse. | `cold plane`, `archive plane` when the functional meaning matters | Letting low-frequency-storage analogies define the concept or treating this wording as final field-backed ontology |
| `Commitment` | Commitment structure | Something requiring attention, maintenance, progress, or decision. | overloading "task" or "project" | Modeling all open loops as notes |
| `Project` | Commitment structure | A commitment requiring multiple steps over time. | generic "plan" or "set" when commitment is meant | Treating project as just a folder or tag |
| `Next Action` | Commitment structure | The next concrete step that can advance a commitment. | vague "action" when GTD-like meaning matters | Using "action" for both checkbox label and ontological action without distinction |
| `Waiting State` | Commitment structure / state | A blocked or deferred commitment dependent on another actor or event. | generic "pending" | Treating waiting as equivalent to inactivity |
| `Review Cycle` | Commitment structure / operation | A recurring re-orientation practice that restores trust in the system. | one-off "review" wording | Treating review only as content approval |
| `Cognitive Operation` | Operation | A meaningful activity performed on artifacts or commitments in order to understand, create, decide, remember, or advance work. | endpoint or feature names when discussing domain behavior | Elevating ASK or RAG to the central domain model |
| `Inquiry` | Operation | A question-driven or exploratory cognitive operation. | making `Question` the primitive | Treating all retrieval as explicit Q&A |
| `Proposal` | System artifact / process object | A recommended interpretation, change, or next step that has not yet been adopted. | mixing with `intent` | Treating every proposal as consent |
| `Intent` | Process object | An expressed will that something should be done. | using `proposal` for explicit requested action | Collapsing system suggestion and human-approved intent |
| `Action` | Operation / transition | A concrete performed step that changes state, artifact, or commitment trajectory. | overloaded checkbox/action-catalog term in domain discussion | Using action labels as if they were domain primitives |
| `Transition` | Transition | A state-changing progression such as review, promotion, acceptance, rejection, archive. | objectifying review or promotion | Treating `promotion` as a durable entity |
| `Review` | Transition / operation | A process or transition of examination, evaluation, or approval. | raw `review_state` when discussing ontology | Treating review solely as a status field |
| `Promotion` | Transition | A transition in which an artifact changes role, maturity, or standing. | "promotion object" or treating it as a standalone thing | Collapsing it with plan, intent, and result |
| `Receipt` | System artifact / accountability object | A human-legible record of what happened, by whom or by what, under what authority, and with what result. | generic "log" when human-facing accountability is meant | Treating receipts as optional diagnostics only |
| `Provenance` | Provenance | The explanatory context for origin, dependence, and transformation. | reducing to `origin` or path alone | Treating provenance as just metadata garnish |
| `Metacognitive State` | Metacognitive layer | A state concerning understanding, uncertainty, attention, load, or calibration. | hiding this behind retrieval/ranking language | Ignoring open loops, attention, and calibration |
| `Open Loop` | Metacognitive layer / commitment structure | Anything that still has the human's attention without being sufficiently clarified or closed. | generic "inbox item" when broader meaning is intended | Treating all open loops as content artifacts |
| `Attentional Salience` | Metacognitive layer / projection-facing semantic | How mentally near, activated, or ready-to-hand something is in a situation. | vague `hot` / `foreground` language when the semantic meaning matters | Treating salience as a permanent artifact essence |
| `Attentional Relevance` | Metacognitive layer / relation | How useful, timely, or important something would be to surface in the current context. | flattening it into retrieval score or recency alone | Treating ranking heuristics as the full ontology |
| `Zone` | Runtime overlay / projection | A derived runtime overlay for attentional proximity or surface shaping. | treating `hot/warm/cold` as canonical | Letting zone language redefine the ontology of relevance |

## Drift map for overloaded repo terms

| Existing term | Observed drift | Most likely ontology class | Recommendation |
| --- | --- | --- | --- |
| `note` | Used for writing artifact, markdown file, object kind, and generic content unit | `Vault Note` or `Work Artifact` depending on context | Reserve `Vault Note` for writing-surface editable notes; use `Cognitive Artifact` / `Work Artifact` elsewhere |
| `object` | Used for domain artifact, store row, external file surrogate, and generic payload container | Usually implementation-facing `Object Record`, not base ontology | Avoid as a domain term; use artifact language in docs and reserve object for storage/runtime when necessary |
| `source` | Used for provenance origin, evidence role, emitter identity, and file path | Usually `Source Role`, `Provenance`, or emitter attribution depending on context | Always qualify: `source role`, `source emitter`, `source_ref`, or `origin` |
| `agent` | Used for true assisting actors, deterministic pipelines, services, and roles | `System Agent` or role | Keep `System Agent` for bounded assisting actors; call simple components/services by their architectural name when agency is not intended |
| `review` | Used for process, state field, approval, and promotion-related gating | `Review` transition/process | Distinguish `review` (process), `review state` (state marker), and approval/acceptance (decision/transition) |
| `promotion` | Used for panel intent, agent flow, maturity change, and frontmatter update | `Promotion` transition | Treat as a transition with associated intent/receipt, not a standalone object |
| `memory` | Used for human memory, external memory, in-process cache, and historical memory-store designs | `external cognitive support` at domain level; implementation varies | Constrain usage carefully; do not use `memory` as a blanket synonym for artifact store |
| `warm` / `cold` / `hot` / `cool` | Used as if cognitive function were a storage-temperature tier | Usually `writing plane`, `retention plane`, or a salience distinction depending on context | Treat as non-canonical metaphor; rewrite active SoT docs toward function language |
| `zone` | Used for salience semantics, ranking buckets, and UI foreground/background language | Usually runtime `Zone` overlay informed by `Attentional Salience` / `Attentional Relevance` | Keep as runtime overlay language; point upstream when semantic meaning matters |
| `domain` | Used for lived life area, runtime retrieval boundary, storage grouping, and trust/exposure policy | Usually `Operational Scope`; sometimes `Sphere` or `Context` depending on meaning | Do not let `domain` silently carry all context jobs at once |
| `bridge` | Used for overlap in meaning, repeated cross-context reuse, and runtime permission structure | Usually `Explicit Cross-Scope Allowance`; sometimes `Shared Participation` if the point is human overlap | Avoid using it as the default mental model of overlap |
| `plan` | Used for commitment structure, generated execution artifact, and planner output schema | `Plan Artifact` or `Project` depending on context | Distinguish project/commitment from execution plan |
| `action` | Used for checkbox labels, ontological operations, tool calls, and next actions | `Action`, `Next Action`, or action-catalog item depending on context | Qualify as `next action`, `catalog action`, or `performed action` |
| `artifact` | Sometimes means any content, sometimes only durable human-readable output | `Cognitive Artifact` | Prefer as the general domain term over `object` |
| `projection` | Used inconsistently for mirrors, store rows, retrieval docs, and frontmatter summaries | `Projection` | Use for bounded representations, not for the artifact itself |
| `receipt` | Used sparsely despite being conceptually central | `Receipt` | Promote as the canonical accountability term |

## Interpretation rules for key docs

### `docs/CORE_CONTRACT.md`
- Read `note or object` as a migration-era compression of at least two layers:
  - `Vault Note` / human-facing artifact
  - storage/runtime representation
- Do not treat `object` there as the preferred domain term going forward.

### `docs/ARCHITECTURE.md`
- Read `object store`, `store_objects`, and `objects` as implementation/storage terms.
- Read `note` carefully: it sometimes means `Vault Note`, sometimes any ingested artifact.
- Read `agent` as an architectural/runtime term that may be narrower than `System Agent` in the ontology.

### `docs/HUMAN-FLOWS.md`
- This is closest to the domain perspective, but still compresses:
  - artifact,
  - commitment,
  - proposal,
  - receipt,
  - and action into "note flows".
- Interpret it through `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` when revising.

### `docs/AGENTS.md`
- This document uses `agent` in an implementation-architecture sense.
- It should later be revised to distinguish:
  - ontological `System Agent`,
  - runtime component,
  - and role in a workflow.
- Development-time terms such as `coding agent`, `Codex`, or repo assistant do not belong to this
  runtime ontology layer; read those from the root `AGENTS.md` and `docs/development/DEV_WORKFLOW.md`.

## Runtime seam notes

These notes do not redefine the ontology.
They record where the active runtime most clearly compresses multiple ontology layers.

- `app/ingest/vault_alpha.py`
  - `note` means at least three things at once:
    - a human-facing vault note,
    - a mirror-backed ingest path,
    - and repeated runtime/store/index projections with `kind="note"`.
  - `review_state` and `maturity` are both present, which supports keeping them distinct in the
    ontology even though downstream runtime paths do not always preserve that distinction.

- `app/planner/schema.py`
  - `Plan` is currently an execution-oriented runtime artifact, not the same thing as a project,
    commitment, or review cycle in the human ontology.
  - `source_object_uuid` is runtime wording and should not be mistaken for the domain's preferred
    term for a human artifact.

- `app/promotion/consumer.py` and `app/services/note_update.py`
  - `promotion` currently resolves into `review_state` mutation in both vault frontmatter and store
    payload.
  - This is a strong sign that runtime naming and ontology naming are still misaligned here.

- `app/domain/plan.py` and `app/agents/planner/graph.py`
  - `plan` currently means execution plan much more than human project or commitment structure.
  - action names such as `promote_to_evergreen` and `update_review_state` converge on the same
    runtime mutation shape, which confirms that transition vocabulary is compressed in active code.

- `app/services/vault_sync.py`
  - legacy sync paths still write `kind="note"` objects directly into persistence using
    `review_state` as a key semantic marker.
  - treat `note` here as an implementation-era storage label, not as the preferred domain term.

- `app/services/note_log.py`
  - `note log` currently names a mirror path and future logging surface more than a fully realized
    receipt model.
  - Treat `note log`, `mirror`, and `receipt` as related but not yet fully separated concepts.

## Documentation rewrite priorities

The following terms should be corrected first in active SoT docs:
1. `note`
2. `object`
3. `source`
4. `agent`
5. `review`
6. `promotion`
7. `memory`
8. `plan`
9. `action`
10. `domain`
11. `bridge`

## Source of truth rule

If a runtime or schema term conflicts with the ontology:
- the ontology defines what the concept means,
- architecture defines how the runtime is currently wired,
- schema/code define how the current system represents it.

These layers must not be silently collapsed.
