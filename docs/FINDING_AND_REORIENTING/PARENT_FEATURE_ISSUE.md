State: Created on GitHub as Issue #392 and closed on 2026-04-18. This file is the local source for the delivered parent feature issue; GitHub is the authoritative backlog and validation record.
# [Feature] Finding, reorienting, and resurfacing as distinct cognitive capabilities

> **Created and delivered.** GitHub Issue #392: https://github.com/RasmusTho/agentic-pkm-mvp/issues/392. Keep this file aligned with the issue contract and with the delivered capability history; the live GitHub issue remains the authoritative backlog and validation surface.

## Context

The user's ability to come back to work and recognize what still matters is currently collapsed into ASK-style question answering. At the architecture level, retrieval, orientation, and resurfacing are blurred into one concern; at the runtime level, the conflation is visible as Finding 2 in `docs/plans/V60_ARCHITECTURE_TARGET.md` (zone read from artifact payload as if stored), where an attentional overlay is treated as if it were a durable artifact field.

This is not primarily a bug. It is a missing semantic distinction. The v6.0 target state in Pillars 6 and 7 of `docs/plans/V60_ARCHITECTURE_TARGET.md` says this directly: retrieval should combine scope, relations, and provenance; retrieval, orientation, and resurfacing should stay related but distinct. The v6.0 capability evolution plan says it another way: "ASK is deprecated as an architectural center" and "Retrieval becomes a capability, not an agent."

This feature names and specifies the distinction. It is docs-only. It does not touch `app/retrieval/*`, `app/agents/ask/*`, the ObjectStore payload shape, or any migrations. Finding 2 is referenced but not owned here; its fix lives in the v5.x enablement lane.

The cognitive-prosthetic framing that must be preserved throughout:
> Let the user come back to work and rediscover what mattered without doing the remembering themselves. Separate "I asked a question" from "I lost my place and need to be led home" from "this has quietly become relevant again."

## Scope

Produce a specification directory at `docs/FINDING_AND_REORIENTING/` that:

- Names retrieval, orientation, and resurfacing as three distinct capabilities.
- Specifies what each capability uniquely does for the user that the other two cannot.
- Binds salience to derived-only representation and cites Finding 2 as the cautionary tale.
- Frames ASK's deprecation as an architectural center in text, while leaving runtime/API compatibility untouched.
- Defers all interaction-surface authority questions (Panel, Chat, mutation rights, where these capabilities are consumed from) to a separate `INTERACTION_SURFACES_AND_AUTHORITY` capability.

The outcome boundary of this feature is conceptual clarity in the docs tree, not a shipped runtime change.

## Source Anchors

- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 6 "Retrieval should combine scope, relations, and provenance rather than overloading one boundary"
- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 7 "Retrieval, orientation, and resurfacing stay related but distinct"
- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 7A "Capability-based composition replaces agent-per-function expansion"
- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Delta 6 "From scope-only retrieval to relation-aware retrieval"
- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Delta 7 "From retrieval-as-orientation to explicit retrieval/orientation/resurfacing separation"
- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Architecture review Finding 2 "Zone read from artifact payload as if stored" (cited only, not owned)
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` :: Fixed Decisions "ASK is deprecated as an architectural center"
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` :: Fixed Decisions "Retrieval becomes a capability, not an agent"
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` :: Representation posture (salience is derived)
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` :: §Recovering orientation
- `docs/HUMAN-FLOWS.md` :: Retrieve and re-orient

## Constraints

- Docs-only. No task may modify `app/retrieval/*`, `app/agents/ask/*`, the ObjectStore payload shape, ingest code, or any Python file.
- No task may propose a data migration or a schema change.
- No task may fix Finding 2. The fix belongs to the v5.x enablement lane; this feature references Finding 2 as motivation only.
- No task may claim authority over interaction surfaces (Panel, Chat, mutation rights). Those questions must be deferred to `INTERACTION_SURFACES_AND_AUTHORITY`.
- No task may propose a durable salience field, a durable zone field, or any other stored attentional overlay.
- Retrieval, orientation, and resurfacing must each be specified as reusable capabilities, not as new architectural agents.
- The cognitive-prosthetic framing must be preserved in every task file's `## Purpose` section, not just in the README.
- Each task must be independently mergeable as a docs change. If a task cannot be verified on its own, the breakdown is too coarse and must be split further.

## Acceptance Criteria

- [ ] `docs/FINDING_AND_REORIENTING/README.md` exists and satisfies the feature-breakdown skill contract for spec directory READMEs.
- [ ] Retrieval, orientation, and resurfacing are each specified in their own task file, and each task file states what that capability uniquely does for the user that the other two cannot.
- [ ] The three contracts are mutually exclusive in behavior: no contract overlaps the others' stated unique function.
- [ ] A dedicated task documents salience as always-derived and cites Finding 2 as the cautionary tale without attempting to fix it.
- [ ] A dedicated task frames ASK's deprecation as an architectural center, distinguishes that from runtime/API compatibility, and explicitly defers interaction-surface authority questions to `INTERACTION_SURFACES_AND_AUTHORITY`.
- [ ] A human returning after an interruption could read the task files and correctly name which of the three capabilities applies to their situation.
- [ ] Each task specifies what "why this was surfaced" looks like for its own capability, and the three explanation shapes differ from each other.
- [ ] All task files adhere to the feature-breakdown frontmatter and section contract.
- [ ] No task touches any file outside `docs/FINDING_AND_REORIENTING/`.
- [ ] No task creates a GitHub issue on its own; issue creation is a separate Phase 3 step.

## Out of Scope

- Fixing Finding 2 (`app/agents/ask/graph.py:22`, `app/agents/ask/utils.py:38,70`, `app/api/routes/ask.py:91-92`). That is a v5.x enablement fix, not a v6 spec task.
- Any modification to `app/retrieval/*`, `app/agents/ask/*`, or the ObjectStore payload shape.
- Writing a ranking algorithm, a surfacing queue implementation, or any signal-weighting rule.
- Deciding which interaction surface (Panel, Chat, API, Deep Agents in Chat) consumes these capabilities, in what mode, and with what mutation rights. That is the `INTERACTION_SURFACES_AND_AUTHORITY` capability.
- Owner-doc promotion of these contracts into `docs/ARCHITECTURE.md`, `docs/RETRIEVAL.md`, or `docs/CONCEPTS/` as stable truth. Promotion is a later PR that runs after the capability is validated.
- Data migration, schema change, or any runtime-visible change of any kind.
- Registering the new spec directory in `docs/DOCS_INDEX.md`. That is Phase 3's job.

## Suggested Validation

Validation for this feature is primarily readability and boundary-coherence. The proof that the spec works is that a reader can do three things with it.

1. **Separation check.** A reviewer reads all six task files and can, without hesitation, name three distinct user verbs and say which verb each capability serves. If any two capabilities read as "basically the same thing with different wording," the spec has failed and must be rewritten.
2. **Reorientation walk-through.** A reviewer describes a concrete scenario: "I came back after a week away, I don't remember where I was on the v6 work, and there is no question in my head yet." The reviewer then walks through the three contracts and identifies which one applies first (orientation), which one may apply next (resurfacing), and when retrieval would become the right capability (once a question has formed). If the walk-through cannot distinguish them, Pillar 7 is not yet satisfied.
3. **Explanation-shape check.** A reviewer drafts the "why this was surfaced" sentence for each of the three capabilities and confirms the three sentences differ in structure, not just in subject. If all three explanations reduce to "because it matched your query," the spec has collapsed resurfacing into retrieval and is not accepted.

## Source Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md`
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/HUMAN-FLOWS.md`
- `docs/DESIGN_PRINCIPLES.md`
- `docs/ARCHITECTURE.md` (retrieval-related sections)
- `docs/RETRIEVAL.md`

## Implementation Tasks

Tasks live in this directory. Conceptual reading order is listed; tasks are independently mergeable as docs changes.

1. [NAME_THE_THREE_CAPABILITIES.md](NAME_THE_THREE_CAPABILITIES.md) — the core naming and boundary spec.
2. [DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md](DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md) — the find-and-return contract.
3. [DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md](DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md) — the regain-situational-understanding contract.
4. [DEFINE_RESURFACING_CAPABILITY_CONTRACT.md](DEFINE_RESURFACING_CAPABILITY_CONTRACT.md) — the bring-back-into-attention contract.
5. [DOCUMENT_SALIENCE_AS_DERIVED.md](DOCUMENT_SALIENCE_AS_DERIVED.md) — salience-is-always-derived spec.
6. [DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md](DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md) — text-only deprecation framing.

## Verification Path

Each task verifies at docs-only level:

- The task file exists at the expected path.
- The task file satisfies the feature-breakdown frontmatter contract and section contract.
- The task file preserves the cognitive-prosthetic framing in its `## Purpose` section.
- The task file does not propose any code change, schema change, or file edit outside `docs/FINDING_AND_REORIENTING/`.
- The task file states what its output uniquely contributes that no other task in this directory contributes.

Per-task acceptance is verified at PR review; capability-level acceptance is verified on this parent feature issue.

## Validation / Acceptance Path

Post-merge validation for the capability happens on this parent feature issue. The validation log should record:

- A short reviewer note on the separation check (are the three capabilities mutually distinguishable in prose).
- A short reviewer note on the reorientation walk-through (does a concrete scenario pick out the right capability).
- A short reviewer note on the explanation-shape check (do the three "why this was surfaced" sentences differ structurally).
- A link to any downstream ticket that attempts to implement these contracts in code, so that implementation feedback can flow back into spec correction if the contracts turn out to be unimplementable.

Owner-doc promotion — updating `docs/ARCHITECTURE.md`, `docs/RETRIEVAL.md`, or the relevant `docs/CONCEPTS/` files to reflect these contracts as accepted truth — is a separate PR, triggered only after all validation notes above are positive and at least one downstream implementation ticket has confirmed the contracts are workable.
