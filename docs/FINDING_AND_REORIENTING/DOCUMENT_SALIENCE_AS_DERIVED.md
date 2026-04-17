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

This is the operational specification for salience in the three capabilities: retrieval, orientation, and resurfacing. It translates `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` into a binding commitment for this directory.

### Core Rule

**Salience is always derived, never stored.**

Salience is real in the user's model — they experience what is mentally near, what deserves attention, what is pressing. But in the runtime model, salience has no durable home on any artifact, in any payload, in any mirror, or in any projection. When any capability in this directory needs a salience signal, it computes that signal at the moment the capability runs. Computation may be cached for the lifetime of a single decision; it is never persisted as a durable artifact property.

This rule exists because salience is situational and relational, not essential. What matters changes when context changes, when time passes, when relations shift, or when the human's open loops resolve. A stored salience field would capture a frozen moment and then slowly become obsolete, creating silent failures where the system appears to work but returns stale answers (see Finding 2, below).

The prohibition is specifically against storing salience as the durable essence of an artifact. Durable operational fields such as review cadence, commitment state, due date, or last-reviewed timestamp may still exist as input signals, provided they are not treated as salience itself.

### Allowed Signal Families (Concept-Level Only)

The three capabilities may derive salience signals from any of the following signal families. **This list is conceptual only; no weights, thresholds, or fusion rules are specified here.** Those decisions are implementation details downstream of this spec.

- **Recency:** how recently an artifact was created, accessed, or modified.
- **Active context:** what domain, role, or situational frame is the human currently engaged in.
- **Current commitments:** what open-loop items (tasks, reviews, decisions waiting) are associated with this artifact.
- **Unresolved status / open-loop pressure:** whether an artifact carries a state that signals a decision or action is still pending.
- **Surprise or novelty:** whether an artifact is new, recently changed, or represents a relation that is newly discovered.
- **Recent interaction:** whether an artifact has been recently cited, linked from, or mentioned in other work.
- **Temporal drift / staleness:** how long it has been since an artifact was actively in use or relevant to current work.
- **Relational change:** whether the artifact's relations to other work have changed in ways that alter its relevance.
- **Review cadence:** how often an artifact surfaces for review and whether it has been marked for periodic re-evaluation.

### Forbidden Moves

To enforce that salience stays derived, the following moves are forbidden. Any task that proposes these must be rejected at review.

- **No durable `salience` field on any artifact.** The runtime must not add a `salience` property to any artifact payload, frontmatter, or metadata, regardless of whether the field is set during ingest, promotion, or later.
- **No durable `zone` field on any artifact,** regardless of what the current v5.x runtime does. The v5.x runtime reads `zone` from payloads that never had it written; this is the exact anti-pattern this spec forbids.
- **No persistent "attentional state" on any artifact.** No capability in this directory may mark an artifact with an attentional overlay, hotness label, temperature, or any equivalent that claims to be a durable property of the artifact itself.
- **No treating operational fields as salience itself.** Durable fields such as review cadence, commitment state, due date, or last-reviewed timestamp may inform a derived salience calculation, but they must not be renamed, read, or governed as durable attentional truth.
- **No implication that ingest should set an attentional flag.** Ingest writes artifact identity, domain, and provenance. It must not attempt to set any salience-related property.
- **No implication that a mirror, receipt, or projection should carry salience as stored truth.** Mirrors and receipts are structural aids for the runtime; they are not the place to store salience. Projections (such as ordered lists or ranked views) are ephemeral; they must not be promoted into artifact-level attentional state.

### How This Rule Applies to Each Capability

**Retrieval:** Retrieval may consult any of the signal families above to influence ranking within a single query execution. For example, it may weight recent matches higher, or prefer artifacts with unresolved status. It must not read a stored salience field, and it must not write one. It must not assume that a high-ranking result is the same as a resurfacing decision; the two are distinct user needs.

**Orientation:** Orientation builds a situational frame at request time, drawing on the signal families above to help the human regain context after an interruption. It must not persist the frame as a durable field on any artifact. It may cite the signals it used inside its explanation — e.g., "this remains open because it has unresolved status" — so the human can see where the reorientation came from and decide whether the frame is still correct.

**Resurfacing:** Resurfacing decides to bring an artifact back into view based on a change in derived relevance (a signal family above shifted in a way that matters). It must not cache the decision as a durable field on the artifact — no "attention marker," no "resurfaced on [date]" property. It may record that a resurfacing decision happened as a receipt or trace, but receipts and traces are structural records of what the system did, not the same as artifact-level attentional state.

### Finding 2 as Cautionary Tale

**Do not fix Finding 2; cite it only.**

- **Location:** `app/agents/ask/graph.py:22`, `app/agents/ask/utils.py:38,70`, `app/api/routes/ask.py:91-92`.
- **What went wrong:** The v5.x runtime reads `zone` from the artifact payload in ASK code, but no ingest path ever wrote it. The result is that every read silently returns `None`, producing a false-positive architecture in which zone appears to work but never does.
- **Why this spec cites it:** Finding 2 is the exact failure mode that happens when an attentional overlay is treated as if it were durable. The fix for Finding 2 belongs to the v5.x enablement lane; this spec does not own that fix and does not propose any edit to `app/agents/ask/*`, `app/retrieval/*`, or any other code file. The citation here is motivational: this is what happens when salience is mistaken for something stored.
- **Related:** `docs/plans/V60_ARCHITECTURE_TARGET.md` :: Architecture review findings :: Finding 2.

### Upstream Contract

This spec operationalizes `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`, which is the upstream concept-level commitment that "salience is usually not a durable essence of an artifact" and that "runtime overlays such as zone are derived projections over multiple signals, not the authoritative ontology of attentional meaning." This spec takes that posture and binds it to the three capabilities in this directory so that none of them can quietly drift toward stored salience without the drift becoming visible at review time.

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
