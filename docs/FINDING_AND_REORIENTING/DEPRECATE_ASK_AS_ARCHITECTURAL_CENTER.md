---
name: Deprecate ASK as Architectural Center
description: Frame the v6 deprecation of ASK-as-architectural-center in text, separate it from runtime/API compatibility, and defer all interaction-surface authority questions.
task_id: FINDING_AND_REORIENTING-06
source_anchor: docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md :: Fixed Decisions "ASK is deprecated as an architectural center"
parent_capability: FINDING_AND_REORIENTING
prerequisites: [FINDING_AND_REORIENTING-01]
depends_on: [NAME_THE_THREE_CAPABILITIES.md]
can_parallelize_with: [DOCUMENT_SALIENCE_AS_DERIVED]
---

# Deprecate ASK as Architectural Center

## Purpose

Let the user come back to work and rediscover what mattered without doing the remembering themselves. The current architecture puts ASK at the center of that work, and the center is the wrong place for it. This task writes the text-only deprecation of ASK as an architectural center: it states what ASK stops being, what stays as runtime/API compatibility, what the three capabilities in this directory now provide in its place, and what questions about interaction-surface authority are explicitly deferred. It is a framing document, not a runtime change.

## What This Task Does

This task produces the ASK-deprecation framing document inside `docs/FINDING_AND_REORIENTING/`. It:

- States that ASK is deprecated as an architectural center, quoting the Fixed Decision in `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`.
- Distinguishes three things that often get conflated when people hear "deprecated": conceptual deprecation, runtime deprecation, and API deprecation.
- Declares only the first: ASK stops being the conceptual center for retrieval, orientation, and resurfacing.
- Explicitly affirms that ASK remains available as a v5.x runtime and API surface, and that this task does not touch `app/agents/ask/*`, `app/api/routes/ask.py`, or any other runtime/API file.
- Maps what ASK used to carry onto the three capabilities in this directory: retrieval, orientation, resurfacing. Each former ASK responsibility is pointed at the capability that now owns it.
- Defers every interaction-surface authority question — which surface calls these capabilities, which surface can mutate, where Deep Agents enter, whether Chat stays read-only — to the separate `INTERACTION_SURFACES_AND_AUTHORITY` capability. This task does not attempt to answer any of those questions.

## Concretely

What ASK stops being (conceptual deprecation):

- ASK stops being the place new retrieval work is attached to.
- ASK stops being the place orientation work would plausibly live if orientation were built.
- ASK stops being the place resurfacing work would plausibly live if resurfacing were built.
- ASK stops being the reference architecture any new capability should extend.
- ASK stops being cited as "the central agent" in new design work.

What ASK remains (non-deprecation):

- ASK remains a working v5.x runtime and API surface.
- Existing callers of ASK keep working.
- `app/agents/ask/*` continues to exist and behave as it does today.
- Finding 2 remains ASK's bug and is owned by the v5.x enablement lane, not by this spec.

What replaces ASK at the conceptual center:

- **Retrieval.** The find-and-return concern that used to be centered under ASK moves to the retrieval capability contract in `DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`. Retrieval is reusable, not an agent.
- **Orientation.** The regain-situational-understanding concern that ASK was never designed for, but was silently expected to solve, moves to the orientation capability contract in `DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`. It gains its own explanation shape and its own trigger.
- **Resurfacing.** The bring-back-into-attention concern that ASK was attempting via zone overlays in `app/agents/ask/*` (Finding 2) moves to the resurfacing capability contract in `DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`. It consumes derived salience per `DOCUMENT_SALIENCE_AS_DERIVED.md` and does not store attentional state.

What this task explicitly defers:

- Which interaction surface calls retrieval, orientation, or resurfacing.
- Whether Panel, Chat, API, or something else is the primary caller for each capability.
- Whether Chat remains read-only.
- Where Deep Agents enter the picture.
- What the migration path is for existing ASK clients at the interaction level.

All of the above questions belong to `INTERACTION_SURFACES_AND_AUTHORITY`. This task must not pretend to answer them, must not suggest answers in passing, and must include an explicit deferral statement pointing to that capability.

## Why This Matters

`docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` lists this deprecation as a Fixed Decision, but the decision has not yet been framed at the docs level in a way that lets other design work act on it. Without this framing:

- New design work keeps attaching itself to ASK because there is nothing else in the docs tree to attach to.
- The capability-based architecture stays a plan bullet and never becomes a visible boundary.
- Finding 2 keeps reading as "an ASK bug" instead of as a symptom of ASK trying to own three distinct things at once.

Framing the deprecation in text, separately from any runtime or API change, is how the conceptual center moves without breaking the runtime.

## Acceptance Criteria

- [ ] The document quotes the Fixed Decision "ASK is deprecated as an architectural center" from `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`.
- [ ] The document distinguishes conceptual deprecation from runtime and API deprecation and declares only the conceptual one.
- [ ] The document explicitly states that ASK's v5.x runtime and API remain intact and untouched.
- [ ] The document states that `app/agents/ask/*`, `app/api/routes/ask.py`, and related files are not modified by this spec or by any task in this directory.
- [ ] The document maps three ASK responsibilities — retrieval, orientation, resurfacing — onto the three capability contracts in this directory, one each.
- [ ] The document explicitly defers all interaction-surface authority questions to `INTERACTION_SURFACES_AND_AUTHORITY`, by name.
- [ ] The document does not propose any migration path at the interaction layer, any API breaking change, or any runtime deprecation.
- [ ] The document cites Finding 2 as the symptom that motivates the conceptual deprecation, without fixing it.
- [ ] The document does not propose code changes.

## How to Verify (Pre-Merge)

- Grep the document for any proposed edit to `app/agents/ask/*`, `app/api/routes/ask.py`, or any other runtime file. None may be present.
- Grep for "Panel" and "Chat" and confirm they are used only in the deferral paragraph pointing at `INTERACTION_SURFACES_AND_AUTHORITY`. They must not appear in any authoritative decision in this document.
- Read the three-responsibility mapping and confirm each of retrieval, orientation, and resurfacing points to the correct sibling contract file.
- Confirm the distinction between conceptual deprecation and runtime/API deprecation is stated in at least one sentence that a skimmer cannot miss.
- A reviewer other than the author signs off on all four checks.

## Out of Scope

- Deprecating, modifying, or removing any ASK runtime code.
- Deprecating, modifying, or removing any ASK API route.
- Proposing an interaction-level migration path for existing ASK clients.
- Deciding where any of the three new capabilities are consumed from, by whom, and with what authority.
- Fixing Finding 2.
- Modifying any `.py` file.

## Related Docs

- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` :: Fixed Decisions
- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Pillar 7, Pillar 7A, Delta 7, Finding 2 (cite only)
- Sibling task files in this directory.
- `docs/ARCHITECTURE.md` :: retrieval and ASK-related sections (read-only reference)

## Related GitHub Issues

When this spec is promoted into an implementation issue, reference: "Implements FINDING_AND_REORIENTING/DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER." Mark the issue docs-only. Do not combine it with any issue that edits `app/agents/ask/*` or that proposes an API deprecation. Any runtime or API deprecation is a separate future decision outside this directory.
