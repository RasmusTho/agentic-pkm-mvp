---
name: Finding and Reorienting Specification
description: Specification directory for the v6.0 capability that separates retrieval, orientation, and resurfacing as distinct cognitive prosthetics.
type: specification
authority: SoT for the FINDING_AND_REORIENTING capability boundary and its docs-only task breakdown
source_of_truth: docs/plans/V60_ARCHITECTURE_TARGET.md (Pillars 6, 7, 7A; Deltas 6, 7)
related_docs:
  - docs/plans/V60_ARCHITECTURE_TARGET.md
  - docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
  - docs/CONCEPTS/USER_NEEDS_MODEL.md
  - docs/HUMAN-FLOWS.md
  - docs/DESIGN_PRINCIPLES.md
---

State: Docs-only specification lane for v6.0. No code in scope. Finding 2 (zone-read-as-stored) is referenced as cautionary context only; its fix lives in the v5.x enablement lane, not here.

# Finding, Reorienting, and Resurfacing

This directory is the specification surface for one v6.0 capability: the separation of three distinct cognitive prosthetics that the current architecture conflates under ASK-style question answering.

The capability name deliberately foregrounds the human verbs — finding, reorienting — rather than a mechanism name. The third verb, resurfacing, is added in the spec body because it is the one the user least articulates for themselves, yet it is the one the system must do without being asked.

These documents are not issue templates. Each task specification is the source of truth for what needs to be specified in the docs tree; the GitHub issues that implement these specs are execution artifacts derived from them.

## The cognitive-prosthetic framing

Let the user come back to work and rediscover what mattered without doing the remembering themselves. The spec must preserve this framing end-to-end. Anywhere a task reduces the capability to a ranking algorithm, a search box, or a question-answer loop, the spec has drifted and should be rewritten.

Separates three things that feel similar and are not:

- "I asked a question and want the right thing returned." (retrieval)
- "I lost my place and need to be led home." (orientation)
- "This has quietly become relevant again and I would not have thought to ask." (resurfacing)

## Human needs this serves

From `docs/CONCEPTS/USER_NEEDS_MODEL.md` and `docs/HUMAN-FLOWS.md`, the capability serves three user verbs, one per sub-capability:

- **Retrieve the right thing.** The user has a concrete question, lookup, or operation in mind and needs the system to return the correct material with legible provenance.
- **Re-orient after interruption.** The user has lost the thread after an interruption, a context switch, or time passing and needs to be walked back to where they were and what mattered when they left.
- **Notice what is becoming relevant again.** The user has no active query; the system must bring something back into view because open-loop pressure, temporal drift, or relational change has made it quietly matter again.

Each of these three is a distinct prosthetic function. The capability is accepted only when all three are separately named, separately specified, and each one states what it uniquely does for the user that the other two cannot.

## What this capability is NOT

The spec must hold these negatives as firmly as it holds the positives. Task writers should refuse language that collapses any of them.

- **Not generic question-answering.** ASK-as-center is explicitly deprecated in `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` Fixed Decisions. This capability is not an ASK replacement; it is the reason ASK no longer needs to be the architectural center.
- **Not a search box.** Retrieval is one of three functions, and none of them is a free-text search input. A search box is a UI affordance; this capability is a cognitive-prosthetic contract.
- **Not a ranking algorithm.** Resurfacing is not "better ranking." Ranking is a mechanism detail downstream of a surfacing decision; the decision to surface at all is what resurfacing specifies.
- **Not salience-as-stored-field.** Salience is derived, always, per `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`. No task in this directory may propose a durable `salience`, `zone`, or equivalent field on an artifact.
- **Not an agent.** Per Pillar 7A and the Fixed Decisions, retrieval is a reusable capability, not an agent. Orientation and resurfacing follow the same rule: reusable capabilities, not new architectural agents.
- **Not an interaction-surface authority decision.** Whether Panel, Chat, or another surface consumes these capabilities, and with what mutation rights, is out of scope. That question belongs to a separate `INTERACTION_SURFACES_AND_AUTHORITY` capability.
- **Not a fix for Finding 2.** The zone-read-as-stored bug in `app/agents/ask/*` is a v5.x current-state bug. This spec cites it as the cautionary tale that motivates naming salience as derived, but it does not own the fix and no task in this directory modifies any code.

## Reading order for the task files

Read the task files in this order. The order is conceptual, not a runtime dependency graph — each task is independently mergeable as a docs change, but reading them out of order makes the boundary harder to see.

1. **[NAME_THE_THREE_CAPABILITIES.md](NAME_THE_THREE_CAPABILITIES.md)** — establishes the boundary. Defines retrieval, orientation, and resurfacing as three separate capabilities and states what each one uniquely does for the user. Every other task depends on this naming.
2. **[DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md](DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md)** — the find-and-return contract. What retrieval consumes, what it produces, and what it explicitly never does.
3. **[DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md](DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md)** — the help-the-human-regain-situational-understanding contract. What signals it combines, how it explains itself, and why it is not retrieval.
4. **[DEFINE_RESURFACING_CAPABILITY_CONTRACT.md](DEFINE_RESURFACING_CAPABILITY_CONTRACT.md)** — the bring-back-into-attention contract. Its relationship to salience, why it is not ranking, and when it fires without a query.
5. **[DOCUMENT_SALIENCE_AS_DERIVED.md](DOCUMENT_SALIENCE_AS_DERIVED.md)** — the spec that binds salience to "always computed, never stored," lists allowable signals, and cites Finding 2 as the cautionary tale.
6. **[DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md](DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md)** — the text-only deprecation framing. What ASK stops being, what remains as runtime/API compat, and how the three capabilities provide what ASK used to carry.

## Relationship to the parent feature issue

The draft of the parent feature issue lives at [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). It is a draft for review, not an issue that has been created on GitHub. Phase 3 of the feature-breakdown workflow may create the actual GitHub issue from this draft.

## Acceptance criteria for the capability as a whole

The capability FINDING_AND_REORIENTING is accepted when all of the following are true at the docs level. These are capability-level criteria; each task has its own narrower acceptance.

- [ ] The three sub-capabilities — retrieval, orientation, resurfacing — are named separately in the target architecture docs, and each sub-capability's doc states what it uniquely does for the user that the other two cannot.
- [ ] The docs explicitly reject reducing any of the three to the other two. Specifically: retrieval is not orientation, resurfacing is not ranking, and orientation is not Q&A.
- [ ] Salience is documented as derived in every place this capability references it, and no spec task proposes a durable salience field.
- [ ] ASK's de-centering is framed in text, with a clear statement of what ASK stops being as an architectural center and what stays as a runtime/API compatibility concern.
- [ ] A human returning to work after an interruption could read the three contracts and correctly articulate which of the three capabilities applies to their situation.
- [ ] The system's future explanation of "why this was surfaced" differs correctly between the retrieval case, the orientation case, and the resurfacing case — i.e. each contract specifies its own explanation shape.
- [ ] All tasks in this directory are deliverable by editing `docs/` only; no task requires code, runtime, or schema change to be considered complete.
- [ ] The boundary is internally consistent: no task contradicts another, and no task takes authority that belongs to `INTERACTION_SURFACES_AND_AUTHORITY`.

When all of these are true, the parent feature issue can be closed and the three capability contracts may be promoted into the stable architecture docs in a separate, narrower PR (that owner-doc promotion is out of scope for this directory).

## Navigation

- Parent architecture target: `docs/plans/V60_ARCHITECTURE_TARGET.md` (Pillars 6, 7, 7A; Deltas 6, 7; Finding 2)
- Capability evolution plan: `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- Salience contract: `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- Human needs model: `docs/CONCEPTS/USER_NEEDS_MODEL.md`
- Human flows: `docs/HUMAN-FLOWS.md`
- Design principles: `docs/DESIGN_PRINCIPLES.md`

---

**Status:** Specification draft. Docs-only lane. Does not touch retrieval runtime, ASK runtime, payload shapes, or migrations.
