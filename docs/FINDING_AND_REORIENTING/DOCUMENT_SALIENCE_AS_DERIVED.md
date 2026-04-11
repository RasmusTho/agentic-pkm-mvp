---
name: Document Salience as Derived
description: Specify salience as always computed, never stored, across all three capabilities in this directory; cite Finding 2 as the cautionary tale without attempting to fix it.
task_id: FINDING_AND_REORIENTING-05
source_anchor: docs/plans/V60_ARCHITECTURE_TARGET.md :: Architecture review Finding 2
parent_capability: FINDING_AND_REORIENTING
prerequisites: [FINDING_AND_REORIENTING-01]
depends_on: [NAME_THE_THREE_CAPABILITIES.md]
can_parallelize_with: [DEFINE_RETRIEVAL_CAPABILITY_CONTRACT, DEFINE_ORIENTATION_CAPABILITY_CONTRACT, DEFINE_RESURFACING_CAPABILITY_CONTRACT]
---

# Document Salience as Derived

## Purpose

Let the user come back to work and rediscover what mattered without doing the remembering themselves. Making that real requires a system that computes relevance at the moment it matters, not one that pre-writes relevance onto artifacts and reads it back later. This task is the explicit docs-level commitment that salience is derived, always, in every capability in this directory. It exists to keep retrieval, orientation, and resurfacing from quietly re-introducing stored attentional overlays the next time a performance or convenience argument surfaces.

## What This Task Does

This task produces the salience-is-derived specification inside `docs/FINDING_AND_REORIENTING/`. It:

- States the core rule: salience is never stored on an artifact, never written at ingest, and never referenced in a way that assumes a durable salience field.
- Lists the signals that salience may be derived from, at the conceptual level only, with no weights or thresholds.
- Binds the rule to all three capability contracts in this directory: retrieval must not read a stored salience field, orientation must not persist its situational frame as durable state, resurfacing must not cache its decisions as durable attention markers on artifacts.
- Cites Finding 2 in `docs/plans/V60_ARCHITECTURE_TARGET.md` as the cautionary tale showing what happens when an attentional overlay is treated as if it were stored: the runtime read zone from payloads that were never written, and silently returned `None`. This spec references that outcome as the reason for the rule and explicitly does not fix Finding 2; the fix lives in the v5.x enablement lane.
- Anchors the rule to `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`, which is the upstream concept contract this task makes operational for the three capabilities.

## Concretely

The rule this document writes:

- **Salience is a first-class concept and a derived representation.** It is real in the user model and computed in the runtime model. It has no durable home on any artifact, in any payload, in any mirror, or in any projection.
- **Allowed signal families (concept-level only):** recency, active context, current commitments, unresolved status / open-loop pressure, surprise or novelty, recent interaction, temporal drift / staleness, relational change, review cadence. These are named as conceptual inputs the three capabilities may draw on. Exact weights, thresholds, and fusion rules are out of scope.
- **Forbidden moves:**
  - No durable `salience` field on any artifact.
  - No durable `zone` field on any artifact, regardless of what the current runtime does.
  - No persistent "attentional state" on an artifact from any capability in this directory.
  - No implication that ingest should set an attentional flag.
  - No implication that a mirror, receipt, or projection should carry salience as stored truth.
- **Required stance:** when any capability in this directory needs a salience signal, it computes that signal at the moment the capability runs. Computation may be cached for the lifetime of a single decision; it is not persisted as a durable artifact property.

Finding 2 as cautionary tale (cite, do not fix):

- Pointer: `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Architecture review findings :: Finding 2 "Zone read from artifact payload as if stored."
- What went wrong: the runtime read `zone` from the artifact payload in ASK code, but no ingest path ever wrote it. The result was that every read silently returned `None`, producing a false-positive architecture in which zone appeared to work but never did.
- Why this document cites it: Finding 2 is the exact failure mode that happens when an attentional overlay is treated as durable. The fix for Finding 2 is owned by the v5.x enablement lane; this spec does not own that fix and does not propose any edit to `app/agents/ask/*` or `app/retrieval/*`. The citation here is motivational only.

How this rule shows up in the three sibling contracts:

- **Retrieval:** may read scope, relations, provenance (per Pillar 6). May use derived salience signals as influence on ranking within a single query. Must not read a stored salience field. Must not write one.
- **Orientation:** builds a situational frame at request time from derived signals. Must not persist the frame. May cite the salience signals it used inside its explanation, so the user can see where the frame came from.
- **Resurfacing:** decides to present an item based on a change in derived relevance. Must not cache the decision as a durable field on the artifact. May record that a decision happened as a receipt or trace, but receipts and traces are not the same as artifact-level attentional state.

## Why This Matters

Every prior time the system has tried to treat salience as stored, it has either created a silent-failure bug (Finding 2) or quietly promoted a runtime overlay into semantic authority. `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` is clear that salience is "usually not a durable essence of an artifact" and that zone is "a projection over signals … not the authoritative ontology of attentional meaning." This task turns that concept-level posture into an operational rule for the three capabilities in this directory, so that none of them can drift back toward stored salience without the drift being visible.

Without this spec:

- Resurfacing is the most likely capability to re-introduce stored salience, because pre-computing is easier than computing at decision time.
- Retrieval is the second most likely, because it is always under pressure to be faster.
- Orientation is the third, because a persisted situational frame is a seductive convenience.
- Any of these three drifts reopens the shape of Finding 2 at a new location.

## Acceptance Criteria

- [ ] The document states the core rule in one sentence: salience is derived, never stored.
- [ ] The document lists the allowed signal families at the conceptual level, with no weights or thresholds.
- [ ] The document lists the forbidden moves as explicit don'ts, not as soft suggestions.
- [ ] The document binds the rule to each of the three sibling contracts and describes how the rule applies to each.
- [ ] The document cites Finding 2 in `docs/plans/V60_ARCHITECTURE_TARGET.md` as the cautionary tale.
- [ ] The document explicitly states that it does not fix Finding 2 and does not propose any edit to `app/agents/ask/*`, `app/retrieval/*`, or any other code file.
- [ ] The document cites `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` as the upstream concept contract.
- [ ] The document does not propose any data migration, schema change, or payload field.

## How to Verify (Pre-Merge)

- Read the document alongside the three capability contracts and confirm each contract respects the rule.
- Grep the document for any language that proposes persisting attention-related state. Any such language must be removed.
- Confirm the Finding 2 citation includes both the anchor and the "cite only, do not fix" note.
- Confirm that nothing in the document touches code or tests.
- A reviewer other than the author signs off on all four checks.

## Out of Scope

- Fixing Finding 2.
- Defining a ranking algorithm or a signal-fusion rule.
- Deciding whether any user-facing durable marker of salience is ever acceptable. The upstream concept contract leaves this open; this task stays within that openness.
- Modifying any code file or any schema.
- Specifying how receipts or traces of resurfacing decisions should be stored. That is a separate concern.

## Related Docs

- `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Architecture review Finding 2
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/CONCEPTS/LAYERING_MODEL.md` :: zone is derived, not a gate
- Sibling task files in this directory.

## Related GitHub Issues

When this spec is promoted into an implementation issue, reference: "Implements FINDING_AND_REORIENTING/DOCUMENT_SALIENCE_AS_DERIVED." Mark the issue docs-only. Do not combine this issue with any code-side fix for Finding 2; Finding 2's fix must remain in the v5.x enablement lane.
