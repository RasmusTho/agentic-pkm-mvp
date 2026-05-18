State: Initial context activation semantics for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept contract
Authority: Defines use-right semantics (visible, retrievable, activatable, instructional, action_authorizing) per artifact class and lifecycle state. Defines the stale-but-visible vs activatable distinction, the unreviewed-memory hidden-authority guard, bridge-artifact assembly semantics, and recall explanation requirements. Not an activation engine, not a retrieval algorithm, not a prompt template, not a runtime implementation, not a governance/authority model, not a DB schema.

# Context Activation Semantics for the Contextualization Layer

## 1. Purpose

This document defines the **context activation semantics** used by the Contextualization Layer.

It answers: once an artifact exists in the system, what may the system do with it?

Specifically it defines:

- the five **use rights** — *visible*, *retrievable*, *activatable*, *instructional*, *action_authorizing* — and what each one permits and withholds;
- how these rights differ across the five artifact classes: Human Knowledge Artifacts, Agentic Memory Artifacts, Bridge / Assembly Artifacts, Machine Mirror Artifacts, and Companion Metadata Notes;
- the **stale-but-visible vs activatable/current** distinction and what it means for each class;
- the **unreviewed memory → hidden authority guard** — why unreviewed memory may never receive instructional or action-authorizing rights;
- how bridge / context-bundle artifacts assemble context from memory and knowledge without themselves becoming agentic memory;
- how **recall explanations** should describe why something was activated.

This document is **target-state semantics, not runtime claim**. Nothing here asserts that any of these use rights is currently enforced by code. The runtime is free to ignore them until a later authority/governance contract or implementation slice grants them enforcement weight.

## 2. Relationship to existing Contextualization Layer docs

This document builds directly on:

- `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` (§9) — the initial vocabulary for the five use rights and their default stances per artifact class.
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` (§9) — use rights as descriptive metadata hooks; per-class metadata shapes; `review_state`, `activation_policy`, `stale_after`, `validity` fields.
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md` (§4, §8) — lifecycle state is not authority; stale vs invalidated vs archived semantics; the `activated` term deferred to this document.
- `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md` — companion note types, `activation_companion`, `review_companion`, human editability and managed-block rules.

And it cross-cuts (without replacing) the following concept contracts:

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — canonical agent-memory lifecycle, authority rules, and the observation → candidate → review → promote / reject / revise chain.
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` — context-bundle authority flags, receipts, and the prohibition against silent context-to-memory promotion.
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` — trust tiers, write-gating, and authority boundaries. This document defers to that contract for authority-granting decisions; it only defines the vocabulary of use rights.
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` — stale vs drift vs historical validity vs re-evaluation need.

## 3. Load-bearing invariants

The following invariants from the prior Contextualization Layer docs are load-bearing for everything below:

- **Existence is not permission.** An artifact existing in storage does not, by itself, grant any use right beyond visibility. Each right above *visible* must be earned by meeting the conditions defined in this document.
- **Lifecycle state is not authority.** `accepted/promoted` is not the same as `activatable`, and `activatable` is not the same as `instructional`. The lifecycle model names what state an artifact is in; this document names what the artifact may do in that state. The two are separate concerns.
- **Unreviewed memory must never become hidden authority.** A memory artifact in `candidate` or `unreviewed` state may not receive `instructional` or `action_authorizing` rights regardless of any other signal. This is not a policy preference; it is a categorical safety constraint of the Contextualization Layer.
- **Context bundles are bridge / assembly artifacts, not agentic memory.** Assembling context into a bundle does not promote that context into memory. A bundle's use rights are scoped to its `authority_flags`; they do not transfer to its source artifacts and they do not make the bundle itself an authoritative memory artifact.
- **Machine mirrors carry the authority of their source, not independent authority.** Retrievability of a mirror does not grant any use right that the source artifact does not already hold.
- **Stale does not mean wrong.** A stale artifact may be visible and retrievable; activation depends on re-validation, not on silent demotion.

## 4. The five use rights

### 4.1 `visible`

**What it permits:** the artifact appears in the human's browse surface (vault, file tree, panel, notes list). The human may navigate to it, open it, and read it.

**What it does not permit:** anything the system does on the artifact's behalf — retrieval into search results, entry into working context, influencing agent reasoning, or authorizing action.

**Minimum condition to hold:** the artifact exists and has not been explicitly hidden, revoked, or placed under a governance restriction. Visibility is the default state for all persistent artifacts that have not been specifically restricted.

**Applies to:** all five artifact classes. Even a stale agentic memory artifact that cannot be activated remains *visible* unless it has been archived with a deliberate hide-from-browse posture.

**Default by class:**
- Human Knowledge Artifacts: `visible = true` by default.
- Agentic Memory Artifacts: `visible = true` by default, including `candidate` and `unreviewed` artifacts. Visibility here enables human inspection and review.
- Bridge / Assembly Artifacts: `visible` to inspection surfaces (audit, provenance) after `exposed` state; may be hidden from human vault browse by configuration.
- Machine Mirror Artifacts: `visible` to system tooling; not human-browse-visible by default (they are technical projections, not human notes).
- Companion Metadata Notes: `visible` to system and to human inspection; may be surfaced in the human view depending on placement pattern (see `COMPANION_NOTE_PATTERN.md` §5).

### 4.2 `retrievable`

**What it permits:** the artifact may appear in retrieval and search results — full-text search, semantic search, link traversal, backlinking, query results. The system surfaces it as a candidate response to a query or lookup.

**What it does not permit:** entry into an agent's working context, influencing agent reasoning, or authorizing action. Retrieval is presentation of candidates; activation is the separate step of admitting a candidate into working context.

**Minimum conditions to hold:**
- The artifact is indexed or otherwise reachable by the retrieval surface.
- The artifact's `activation_policy` (or class-level default) does not restrict retrieval itself — e.g. a `activation_policy: blocked` posture suppresses both retrieval and activation.
- The artifact's governance posture (per `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`) does not restrict retrieval.

**Stale artifacts and retrievability:** a stale artifact may remain retrievable. Retrieval should surface the artifact's `validity` or `stale_after` posture alongside the result so the consumer can re-validate before activation. Surfacing stale context silently without a stale marker is an error.

**Default by class:**
- Human Knowledge Artifacts: `retrievable = true` by default for indexed artifacts.
- Agentic Memory Artifacts: `retrievable = true` even for `candidate` and `unreviewed` artifacts. Retrieval into a review queue is an authorized use. Retrieval into agent working context without review is not; see Section 5.2.
- Bridge / Assembly Artifacts: retrievable for audit and provenance surfaces; typically not retrievable into a new working context as if they were content — the bundle's content is already in its `included_artifacts`.
- Machine Mirror Artifacts: `retrievable = true` for the system (this is their primary use). Their authority in results is the authority of their source.
- Companion Metadata Notes: retrievable for the system surfaces that manage them (processing pipelines, review queues, activation surfaces). Not retrievable into human note search results by default.

### 4.3 `activatable`

**What it permits:** the artifact may enter an agent's working context for a specific task. It is selected, included in a context assembly (e.g. a context bundle), and presented to the agent as part of the context it may draw on for answering, orienting, or resurfacing.

**What it does not permit:** influencing how the agent reasons or behaves (that is `instructional`), or authorizing a write or action (that is `action_authorizing`). A knowledge artifact included in working context tells the agent what exists; an instructional artifact tells the agent how to behave; an action-authorizing artifact permits the agent to act. These are separate rights and must not be collapsed.

**Minimum conditions to hold:**
- The artifact holds `retrievable` (Section 4.2).
- The artifact's lifecycle state is `activatable/current` — see Section 6.
- The artifact's `activation_policy` permits activation (see Section 4.3.1).
- For agentic memory artifacts: `review_state` is `reviewed` / `accepted` — an `unreviewed` or `candidate` artifact does not hold `activatable` for working context use. See Section 5.2 and Section 7.

**Stale artifacts and activatability:** a stale artifact is **not** activatable by default. See Section 6 for the stale-but-visible / activatable-current distinction.

**Default by class:**
- Human Knowledge Artifacts: `activatable` conditional on lifecycle state. A `settled` or `working` (non-stale) human note with no governance restriction is activatable.
- Agentic Memory Artifacts: `activatable` only if `review_state: reviewed` or `accepted`. `candidate` and `unreviewed` artifacts are not activatable for agent working context. See Section 7.
- Bridge / Assembly Artifacts: `activatable` is inapplicable in the same sense — a bundle *is* an activation artifact. Its `assembled` / `exposed` lifecycle state and its `authority_flags` govern what the bundle may do, not the standard five use rights. See Section 8.
- Machine Mirror Artifacts: not `activatable` in the human-knowledge / agentic-memory sense. A machine mirror is a retrieval aid; it is consumed by the retrieval surface, not by the agent's context window directly. The artifact that enters working context is the source that the mirror indexes.
- Companion Metadata Notes: not `activatable` for agent task working context directly. A companion's content may be surfaced through the review or activation surface it serves; the companion itself does not enter agent context as a content artifact.

#### 4.3.1 `activation_policy`

The `activation_policy` field (placed in companion metadata per `ARTIFACT_METADATA_CONTRACT.md` §3.2) declares the conditions under which an artifact may be activated. It is a metadata hint, not enforced governance, until a later contract grants it enforcement weight.

Illustrative policy values:

| Value | Meaning |
|---|---|
| `explicit_only` | Artifact may only be activated when explicitly referenced by a task or by the human. It does not enter context via semantic retrieval alone. |
| `explicit_or_contextual` | Artifact may be activated by explicit reference or by semantic retrieval when a task's context is closely related. |
| `on_resume` | Artifact is activated when a task or session resumes from a prior checkpoint. |
| `review_queue_only` | Artifact may enter the review queue surface, but not agent task working context. Appropriate for `candidate` or `unreviewed` agentic memory. |
| `blocked` | Artifact may not be retrieved or activated; suppresses both rights. |

These are illustrative; additional policy values may be introduced by later contracts. The `activation_policy` supplements class-level defaults but cannot elevate an artifact above its class or `review_state` ceiling. An `unreviewed` agentic memory artifact cannot reach `activatable` by setting `activation_policy: explicit_or_contextual` — the review requirement is categorical, not overridable by policy.

### 4.4 `instructional`

**What it permits:** the artifact may influence how the agent reasons, responds, or behaves — not only what it knows. This includes: behavioral preferences ("prefer concise answers"), stylistic rules ("use ISO dates"), procedural hints ("when writing a concept note, follow structure X"), constraints ("never send a push notification during this task"), and similar content that shapes agent behavior rather than informing it.

**What it does not permit:** authorizing a write, a notification, or any downstream action. `instructional` governs reasoning posture; `action_authorizing` governs action output.

**Minimum conditions to hold:**
- The artifact holds `activatable` (Section 4.3).
- For agentic memory artifacts: `review_state: accepted` (not merely `reviewed`). An artifact that has been reviewed but not yet promoted to `accepted` does not hold `instructional`.
- The artifact's governance posture (per `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`) grants instructional authority.

**Why `instructional` requires more than `activatable`:** an artifact in working context is visible to the agent and may be referenced in responses. An artifact that is instructional actively shapes the agent's behavior. A preference candidate that has not yet been accepted by the human should not quietly steer the agent. The distinction prevents retrieved-but-unconfirmed signals from functioning as behavioral directives.

**Default by class:**
- Human Knowledge Artifacts: `instructional` conditional on explicit behavioral content and on governance posture. Most human knowledge artifacts (notes, concepts, source notes) are not `instructional`; decision records and preference artifacts that contain explicit directives may be, with governance sign-off.
- Agentic Memory Artifacts: `instructional` only for `accepted` (promoted) artifacts of `memory_type` that carries behavioral signal — `preference_memory`, `policy_memory`, `procedural_memory`. `candidate` and `unreviewed` artifacts never hold `instructional`. See Section 7.
- Bridge / Assembly Artifacts: `instructional` is not a bundle-level right. The bundle's `authority_flags` (specifically flags beyond `may_answer`, `may_orient`, `may_resurface`) capture what the bundle may support; this mapping is defined by `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`, not by this use right.
- Machine Mirror Artifacts: never `instructional`. A mirror carries no independent behavioral authority.
- Companion Metadata Notes: never `instructional` directly. Companion content (e.g. review decisions in a `review_companion`) may surface information that shapes agent behavior, but that surface is the review/activation surface, not the companion itself acting as an instructional artifact.

### 4.5 `action_authorizing`

**What it permits:** the artifact may justify a system action — a write to storage, a push notification, a downstream API call, a vault mutation, a label change, or any other state-change action. When the system is deciding whether it may perform an action, an artifact with this right may serve as the authorizing record.

**What it does not permit:** any of the lower rights that the artifact does not separately hold. `action_authorizing` is the ceiling of the use-right stack; it does not bypass the conditions of the lower rights.

**Minimum conditions to hold:**
- The artifact holds `instructional` (Section 4.4), or is a specific class of artifact whose authority is explicitly action-authorizing by design (e.g. a human decision record that explicitly grants a permission, a governance rule in `policy_memory`).
- The artifact's governance posture (per `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`) grants action-authorizing authority.
- The specific action must be within the artifact's stated scope or the `authority_flags` of the bundle that surfaces it.

**Why `action_authorizing` is the narrowest right:** retrieval, activation, and even reasoning influence are recoverable from misuse — a retrieved artifact that should not have been retrieved can be ignored; an instructional artifact that influenced an answer can be corrected. An authorized action (a write, a push, a downstream call) may be hard or impossible to undo. The bar is intentionally high.

**Default by class:**
- Human Knowledge Artifacts: `action_authorizing` for explicit, stable, authoritative artifacts — decision records, permission grants, policy notes. Not `action_authorizing` by default for notes, drafts, or `stale` artifacts.
- Agentic Memory Artifacts: `action_authorizing` only for `accepted/promoted` artifacts of `memory_type: policy_memory` or `memory_type: preference_memory` with a strong acceptance record and no staleness signal. `candidate`, `unreviewed`, `stale`, and `invalidated` artifacts never hold `action_authorizing`. See Section 7.
- Bridge / Assembly Artifacts: the `authority_flags.may_write` flag in the bundle contract is the closest analogue. A bundle without `may_write: true` does not authorize writebacks even if its content includes action-authorizing artifacts. The source artifacts' use rights are separate from the bundle's authority flags.
- Machine Mirror Artifacts: never `action_authorizing`. A mirror carries no independent authority.
- Companion Metadata Notes: never `action_authorizing` directly. The managed-block pattern means a companion's system fields can drive system behavior (e.g. re-ingest triggers), but that is governed by the processing pipeline contract, not by this use right.

## 5. Use-right defaults per artifact class

This section summarises the default use-right posture for each artifact class. These are defaults, not enforcement claims. Specific artifacts may hold higher or lower rights based on lifecycle state, `activation_policy`, `review_state`, governance posture, and the conditions in Section 4.

### 5.1 Human Knowledge Artifacts

| Use right | Default | Conditions to hold higher |
|---|---|---|
| `visible` | true | n/a — default |
| `retrievable` | true | indexed and not governance-blocked |
| `activatable` | conditional | lifecycle `working` or `settled`, not `stale`, not governance-blocked |
| `instructional` | false | explicit behavioral content, governance grant |
| `action_authorizing` | false | decision record / permission grant, governance grant, not stale |

Human knowledge artifacts default to *visible* and *retrievable* because they are the human's own work and the human may want to find any of it. The bar rises as the right becomes more consequential.

### 5.2 Agentic Memory Artifacts

| Use right | Default | Conditions to hold higher |
|---|---|---|
| `visible` | true | n/a — default (enables review) |
| `retrievable` | true | indexed; `review_queue_only` policy restricts to review surfaces |
| `activatable` | false | `review_state: reviewed` or `accepted`; lifecycle `current`; not `stale` |
| `instructional` | false | `review_state: accepted`; `memory_type` carries behavioral signal; governance grant |
| `action_authorizing` | false | `review_state: accepted`; `memory_type: policy_memory` or `preference_memory`; governance grant; not stale |

The step from `retrievable` to `activatable` is gated by human review. This is the central safety boundary of the agentic memory model. See Section 7.

### 5.3 Bridge / Assembly Artifacts (Context Bundles)

The standard five use rights map awkwardly onto bridge artifacts because a bundle *is* an activation artifact, not an artifact that gets activated. The relevant governance surface is the `authority_flags` block defined in `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`.

| Equivalent | Bundle correlate |
|---|---|
| `visible` | bundle is inspectable at any lifecycle state |
| `retrievable` | bundle may be surfaced in audit / provenance lookup |
| `activatable` | bundle is in `assembled` / `exposed` state and authority flags are in effect |
| `instructional` | no direct bundle-level analogue; governed by `authority_flags` content |
| `action_authorizing` | `authority_flags.may_write: true` is required for any writeback |

Bundle assembly semantics are in Section 8. The key constraint: a bundle may contain, reference, or be assembled from artifacts that hold high use rights, but the bundle does not inherit those use rights. Assembling a context bundle from accepted memories does not make the bundle an authoritative memory artifact; consuming a bundle with `may_write: true` does not make every source artifact action-authorizing.

### 5.4 Machine Mirror Artifacts

| Use right | Default | Notes |
|---|---|---|
| `visible` | system-only | Not human-browse-visible; visible to system tooling |
| `retrievable` | true (system) | Primary use; authority is the source's authority |
| `activatable` | n/a | Mirrors are consumed by retrieval; the source enters context |
| `instructional` | never | Mirrors carry no independent behavioral authority |
| `action_authorizing` | never | Mirrors carry no independent authority |

### 5.5 Companion Metadata Notes

| Use right | Default | Notes |
|---|---|---|
| `visible` | conditional | Visible to system and to human inspection; placement pattern governs human browse visibility |
| `retrievable` | system-only | Retrieved by system surfaces (processing, review, activation) |
| `activatable` | n/a | Companions serve content surfaces; they do not enter agent working context as content |
| `instructional` | never | |
| `action_authorizing` | never | |

## 6. Stale-but-visible vs activatable/current

### 6.1 The distinction

An artifact may be **stale** and still **visible and retrievable**. These two properties are independent.

- **`stale-but-visible`:** the artifact is in `stale` lifecycle state (per `ARTIFACT_LIFECYCLE_MODEL.md` §8). It exists, the human may browse to it, and it may appear in search results with a stale marker. The system has not deleted it and must not silently remove it from browse.
- **`activatable/current`:** the artifact is not stale, has passed any applicable re-validation, and is in a lifecycle state that satisfies the `activatable` conditions in Section 4.3.

### 6.2 Why the distinction matters

Stale does not mean wrong. A concept note written three years ago may still be accurate; a preference memory from last month may still apply. The stale state says: *this has not been re-validated recently; check before use.* It does not say: *this is incorrect; hide it.*

The system's obligation when surfacing a stale artifact:

- Surface the `validity` or `stale_after` posture alongside the result — never silently surface stale content as if it were current.
- Block activation into working context until re-validation occurs.
- Allow retrieval into review and re-validation surfaces.
- Keep the artifact visible so the human can decide to re-validate, update, or archive it.

### 6.3 Per-class stale behavior

| Artifact class | Stale and visible? | Stale and retrievable? | Stale and activatable? |
|---|---|---|---|
| Human Knowledge | yes | yes, with stale marker | no; re-validation required first |
| Agentic Memory | yes | yes, with stale marker | no; re-validation and review required |
| Bridge / Assembly | yes (for audit) | audit only | no; `stale → expired`; new bundle required |
| Machine Mirror | system-only | for diagnostics only | n/a; regeneration required |
| Companion Metadata | yes | system surfaces | n/a |

### 6.4 Re-validation pathway

Re-validation does not automatically restore `activatable` status. The steps are:

1. The artifact is surfaced in a re-validation surface (review queue, re-check prompt, human review panel) with its stale marker.
2. A human or an authorized review process checks the artifact against current reality.
3. If still valid: the artifact's `validity` field is updated, `stale_after` is extended, and the artifact returns to `activatable/current` status.
4. If no longer valid: the artifact is `revised` (corrected and re-reviewed) or `invalidated` (superseded) per the lifecycle rules in `ARTIFACT_LIFECYCLE_MODEL.md` §5.

For agentic memory specifically: re-validation of a stale artifact does not bypass the original review requirement. A `candidate` or `unreviewed` artifact that became stale still requires a full review cycle before it may become `activatable`.

## 7. Reviewed vs unreviewed memory — the hidden-authority guard

### 7.1 The core rule

> **An unreviewed agentic memory artifact must not become hidden authority.**

This is not a style preference. It is the central safety constraint of the Contextualization Layer's agentic memory model, already stated in `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` §9 and `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md` §3.

An unreviewed artifact in `candidate` or `unreviewed` `review_state` may hold:
- `visible = true` (the human can inspect it)
- `retrievable = true` (it may appear in review queues and search results with an `unreviewed` marker)

An unreviewed artifact may **never** hold:
- `activatable = true` for agent task working context
- `instructional = true`
- `action_authorizing = true`

No policy value, no high confidence score, no proximity to a strong source reference, and no time elapsed since observation bypasses this rule.

### 7.2 Why this is categorical

An agent working with unreviewed memory as if it were reviewed memory may:

- apply incorrect behavioral preferences silently,
- authorize actions based on agent-generated summaries the human has not confirmed,
- drift away from the human's actual intent without a visible signal.

The visibility and retrievability of `unreviewed` artifacts exist precisely to make review possible. Allowing them to silently become `activatable` would close the review loop before review occurs. The distinction is the difference between memory the human has confirmed and memory the system believes the human holds.

### 7.3 Review state vocabulary

The `review_state` field introduced in `ARTIFACT_METADATA_CONTRACT.md` §4 carries the following values for agentic memory use rights:

| `review_state` | Maximum use right |
|---|---|
| `unreviewed` | `retrievable` (for review surfaces only) |
| `reviewed` | `activatable` (for reading surfaces; not yet `instructional`) |
| `accepted` | `instructional` (and conditionally `action_authorizing` per Section 4.5) |
| `rejected` | `visible` only; never activatable |
| `revised` | Depends on the review state of the *revised* version; the prior version reverts to `visible` only |

These are use-right ceilings, not floors. An `accepted` artifact may still be blocked from `action_authorizing` by governance posture, staleness, or scope mismatch.

### 7.4 Surfacing the review state in recall

When a `reviewed` or `accepted` agentic memory artifact is activated, the activation receipt should record its `review_state` at activation time. If an artifact's `review_state` was `accepted` at the time of activation and has since been `revised` or `invalidated`, the receipt preserves the state it held at activation — this is the audit record, not a retroactive permission grant.

## 8. Bridge artifacts — assembling context without becoming memory

### 8.1 The boundary

A bridge / assembly artifact (context bundle, working-context snapshot, reorientation bundle) assembles context from memory and knowledge artifacts for a specific task. It is a per-use selection, not a memory artifact.

> **Assembling a context bundle from reviewed, accepted memories does not promote those memories' authority into the bundle.**
>
> **Consuming a context bundle does not promote its contents into new memory artifacts.**

This boundary is already stated in `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` §5 and `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md` §5.3. It is restated here because use-right semantics make the implication concrete.

### 8.2 What governs a bundle's use rights

A context bundle's authority is governed by its `authority_flags` block (per `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`), not by the use rights of its constituent artifacts.

| `authority_flag` | What it permits |
|---|---|
| `may_answer: true` | bundle may support answering a query |
| `may_orient: true` | bundle may support re-orientation (resuming a task, understanding state) |
| `may_resurface: true` | bundle may surface prior context |
| `may_propose: true` | bundle may support proposing candidates for human review |
| `may_write: true` | bundle may authorize a writeback or state-change action |

Omitting or setting a flag to `false` removes that permission. The flags are orthogonal: a bundle may support answering without supporting writeback.

**The `may_write` flag is the action-authorizing signal for bridge artifacts.** A bundle without `may_write: true` does not authorize any writeback regardless of the use rights of its source artifacts.

### 8.3 Assembly does not transfer memory semantics

A context bundle may contain:
- human knowledge artifacts,
- reviewed and accepted agentic memory artifacts,
- machine mirror retrieval results (as candidate references, not as content),
- companion note signals (e.g. activation policy, last activation time).

Including an `accepted` preference memory in a bundle does not make the bundle a memory artifact. The bundle follows bridge / assembly lifecycle states (`assembled → exposed → consumed → stale → expired`), not the agentic memory lifecycle. When the bundle expires, the preference memory it referenced remains in its own lifecycle state, unchanged by its inclusion in the bundle.

### 8.4 Explicit promotion is the only path from bundle to memory

If, after consuming a bundle, the system wishes to record a new memory (e.g. "this user consistently answered questions about X by drawing on Y"), that observation must enter the agentic memory lifecycle:

`observed → candidate → reviewed → accepted/promoted`

The bundle's receipts (per `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`) provide provenance for the observation. The bundle itself is not the memory; the reviewed and promoted candidate is.

### 8.5 Receipts and inspectability

Every context bundle should produce a receipt that records:

- which artifacts were included (`included_artifacts`)
- which were excluded and why (`excluded_artifacts` with reasons when present)
- what authority flags were in effect
- what the bundle was consumed to do (`consumed_by`, `outcome_ref`)

Receipts exist so that activation explanations (Section 9) can trace context provenance to the bundle that carried it, and the bundle back to its source artifacts. The receipt is the audit trail for post-hoc inspection; it does not grant authority.

## 9. Recall explanations — describing why something was activated

### 9.1 What a recall explanation is

A recall explanation is a human-readable description of why a specific artifact entered an agent's working context for a specific task. It is the output of the activation surface, not of the retrieval surface.

Recall explanations exist because:

- the human has the right to understand what context the agent is working with and why;
- traceability of activated context is required for the unreviewed-memory guard (Section 7) to be auditable;
- review surfaces need to know *why* a memory was activated to evaluate whether the activation was appropriate.

### 9.2 What a recall explanation must describe

A well-formed recall explanation answers the following questions, where applicable:

1. **What was activated?** — the artifact's `title`, `artifact_class`, `artifact_type`, and `memory_type` (for agentic memory).
2. **What use right was in effect?** — the highest use right applied: `activatable`, `instructional`, or `action_authorizing`.
3. **What lifecycle state was it in?** — `working`, `settled`, `accepted/promoted`, etc. at activation time.
4. **What review state was it in?** — `reviewed` / `accepted` for agentic memory; n/a for human knowledge.
5. **Why was it selected?** — which of these activation reasons applies:
   - *explicit reference* — the human or the task explicitly named this artifact
   - *contextual relevance* — retrieval surfaced it as relevant to the current task scope
   - *policy applicability* — the artifact is a policy or preference that applies to the current task type
   - *resume continuity* — the artifact is part of the prior state for a task being resumed
   - *authority signal* — the artifact carries action-authorizing status needed for a requested action
6. **What was not activated, and why?** — when the activation surface chose to exclude a retrieved candidate, the explanation should record the exclusion reason (e.g. `stale`, `unreviewed`, `outside scope`, `activation_policy: explicit_only`). This is the complement of the bundle's `excluded_artifacts` field.
7. **Which bundle or assembly carried the artifact into context?** — the `artifact_id` of the context bundle or context snapshot, when applicable.

### 9.3 What a recall explanation must not do

- **It must not claim authority it did not hold at activation time.** An `accepted` memory artifact activated for `instructional` purposes should not be described as having been `action_authorizing` unless that right was explicitly granted and used.
- **It must not retroactively apply a review state that did not exist at activation time.** If an artifact was `reviewed` (not `accepted`) when activated, the explanation records `reviewed`, not `accepted`.
- **It must not describe a bundle's authority flags as the source artifacts' use rights.** The bundle's `may_write` flag is a bundle-level permission; it does not mean each source artifact holds `action_authorizing`.

### 9.4 Explanation granularity and surfaces

The appropriate granularity for a recall explanation depends on the surface:

| Surface | Granularity |
|---|---|
| Human review panel (activation audit) | Full explanation per artifact: all seven fields in §9.2 |
| Agent-facing context preamble | Summary: title, use right, activation reason (3–4 fields) |
| Inline trace in a task snapshot or activation trace artifact | Compact: title, use right, review state, bundle reference |
| System log / receipt | Machine-readable: all fields; may be verbose |

The compact and summary forms should be derivable from the full explanation without information loss — they are projections, not independent records.

### 9.5 Explanation requirements by use right

| Use right applied | Minimum explanation requirements |
|---|---|
| `activatable` | artifact identity, lifecycle state, activation reason, bundle reference |
| `instructional` | all of the above, plus `review_state: accepted`, memory type, behavioral claim summary |
| `action_authorizing` | all of the above, plus explicit action scope, authority source (which accepted artifact or decision record), and receipt reference |

Applying `instructional` or `action_authorizing` without recording the required fields is a violation of the recall contract — not a runtime enforcement failure (there is no enforcer yet), but a gap that the later authority/governance contract will need to close.

## 10. Use rights and the activation policy field

The `activation_policy` field (Section 4.3.1) supplements but does not override the use-right conditions defined in this document.

- `activation_policy` can restrict a higher use right (e.g. limiting an `activatable` artifact to `explicit_only` trigger, preventing broad retrieval-based activation).
- `activation_policy` cannot elevate a lower use right (e.g. an `unreviewed` agentic memory artifact cannot be made `activatable` by setting `activation_policy: explicit_or_contextual`).
- `activation_policy` records the intended policy, not the enforcement. Until a runtime activation surface reads and applies it, the policy is a documentation commitment.

## 11. Non-runtime claims

This document defines **activation semantics**, not **activation implementation**.

- No activation engine is wired here.
- No retrieval algorithm, ranking function, or prompt builder is specified.
- No validator for use rights is required by this document.
- No database schema, migration, or storage backend is locked.

These semantics should be treated as the vocabulary that later runtime implementation slices attach to. When runtime enforcement is added, it must be reflected in an owner doc update that describes the shipped behavior.

## 12. Non-goals

This document is explicitly **not**:

- A governance or authority model. Trust tiers, write-gating, and authority limits live in `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`.
- A retrieval or ranking algorithm.
- A prompt template.
- A formal ontology.
- A database schema.
- An implementation plan.
- A validation tooling specification.
- A child implementation issue. Implementation issues for use-right enforcement belong to the runtime implementation phase and should be created only when this document has been accepted as authoritative.

## 13. Relationship to ARTIFACT_LIFECYCLE_MODEL.md

This document fulfills the deferred `activated` lifecycle state from `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md` §6 (Applicability Matrix). That document marks `activated` as `conditional (deferred to #943)` for all five artifact classes; this document defines the conditions.

The relationship is:

- `ARTIFACT_LIFECYCLE_MODEL.md` says what state an artifact is in.
- This document says what an artifact in a given state may do.
- An artifact moves into an `activated` posture when it satisfies the `activatable` conditions in Section 4.3 and is selected for a task's working context. The selection is recorded in the context bundle's receipts and in any associated activation trace artifact.

## 14. Open questions

The following are deliberately left open. They are recorded so later contracts and implementation work can resolve them explicitly.

- **What is the minimum review record for `reviewed` → `accepted` transition** — i.e. what evidence must be recorded for a memory to hold `instructional` rights? Human-authored acceptance, timestamp, rationale, or all three?
- **Should archived agentic memory remain retrievable for re-validation surfaces by default**, or should this require an explicit "include archived" flag?
- **What is the policy for a stale `accepted` preference memory** — does it fall back to `retrieved` only, or does the system proactively surface it in a re-validation queue before it becomes `stale`?
- **How should activation explanations be stored** — as fields on the context bundle receipt, as a separate `activation_trace` artifact, or both?
- **What is the minimal explanation for an `activatable`-only activation** in a low-footprint context (quick retrieval, no bundle assembly)?
- **How does `activation_policy: explicit_only` interact with bundle construction** — does it block the artifact from being included by the bundle assembler, or does it only block the agent from drawing on it if included?
- **Should `action_authorizing` activations require a distinct confirmation step** (e.g. a human approval signal, a second-factor receipt) beyond the standard activation explanation?

These questions are not blockers for defining the use-right semantics. They are the first decisions later implementation and governance contracts will need to make.
