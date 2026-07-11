State: Accepted (owner decision, 2026-07-07). Decides where the Episode Resolution Engine lives and refines the segmentation-ownership half of ADR-0051. Grounded in `docs/research/EPISODE_RESOLUTION_ENGINE.md`; this ADR is the normative decision, that doc is the advisory grounding. Amends ADR-0051 §5 and clarifies the Heimdal Capability Charter; enacts no code.
Doc role: Decision record (ADR)
Authority: Authoritative for the constituent placement of the Episode Resolution Engine and for which constituent owns multi-stream episode segmentation and `episode_ref` assignment. It does NOT define the engine's internal design, segmentation thresholds, the decay curve, or any schema/runtime change — those remain downstream and owner-open.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the engine's constituent placement is reversed).
Source of truth: This ADR plus `docs/research/EPISODE_RESOLUTION_ENGINE.md`, and the docs it refines (`docs/adr/ADR-0051-episode-as-ontological-primitive.md` §5, `docs/HEIMDAL/CAPABILITY_CHARTER.md`).

# ADR-0054: The Episode Resolution Engine is a Mimer organ — Heimdal contributes single-stream boundary proposals

**Date:** 2026-07-07
**Status:** Accepted (owner decision, 2026-07-07)

---

## Context

[ADR-0051](./ADR-0051-episode-as-ontological-primitive.md) enacted the `Episode` entity, the `episode_ref` dimension, and an **opt-out segmentation** posture. Its §5 named the boundary proposer as "capture (Heimdal)" — correct while segmentation reads only Heimdal's own single event stream.

`docs/research/EPISODE_RESOLUTION_ENGINE.md` then developed the *runtime organ* ADR-0051 presupposes but never scoped: the subsystem that (1) segments streams into episodes, (2) assigns `episode_ref` to the information that originated inside them, and (3) emits closure so event-triggered relevance decay fires. Developing it surfaced one decision ADR-0051 did not settle: once segmentation is **multi-stream** — correlating Heimdal events with calendar, location, and vault activity — *which constituent owns the engine?* Heimdal ([ADR-0049](./ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md)) "ends at a published event" and may not write knowledge; Mimer ([ADR-0044](./ADR-0044-research08-d1-conforms-to-acknowledged-sos.md)) is the knowledge-and-cognition constituent that owns the `Episode` Artifact. This ADR records the owner's placement decision and refines ADR-0051 §5 accordingly.

## Decision (owner, 2026-07-07)

### 1. The Episode Resolution Engine lives in Mimer

The engine that fuses multiple information streams into episodes and assigns `episode_ref` is a **Mimer** organ, not a Heimdal one. Three grounds, in descending strength:

1. **Assignment is a Mimer write.** `episode_ref` is stamped on Mimer artifacts (notes, chats) on the metadata-bundle / HKA authority path. Heimdal is fixed to end at a published event (Capability Charter FIXED #2; HEIM-2) and cannot write knowledge. The assignment half must be in Mimer regardless of where detection sits.
2. **Fusion is cognition, not sensing.** Correlating sensor events with vault activity and calendar to construct a situation model is inference over the knowledge plane — Mimer's role, not Heimdal's.
3. **The entity is already Mimer's.** ADR-0051 (OD-1) placed `Episode` as a Mimer Layer-3 Artifact; the organ that produces it belongs where it is canonicalized.

> **Amendment (owner decision, 2026-07-10; #3420):** `episode_ref` assignment is a candidate-tier metadata write: low-trust, reversible, and conferring no authority. It is a Mimer write because the field lives on Mimer artifacts' metadata bundles, not because it rides the HKA authority path. This follows ADR-0051 §3.1 orthogonality and §5's opt-out posture; confirmed or human-ratified bindings may later use a governed path, which is outside this ADR amendment.

### 2. Heimdal contributes single-stream boundary proposals only

Heimdal continues to propose episode boundaries **from its own attributed events** (a single-stream attribution refinement it is well placed to make, consistent with "Heimdal owns attribution"). It does **not** own multi-stream segmentation, cross-stream fusion, or `episode_ref` assignment. Heimdal becomes one contributing stream among several, not the segmenter of record.

### 3. The seam

Heimdal proposes single-stream boundary hints → the **Mimer Episode Resolution Engine** fuses them with the other streams (calendar, location, vault activity), resolves canonical episodes, assigns `episode_ref`, and emits closure→decay. Only minimized, attributed events cross the raw→published seam, exactly as today (HEIM-4/5 untouched).

### 4. This refines ADR-0051 §5 (not a reversal)

ADR-0051's opt-out posture is unchanged: proposed boundaries stand by default; the only human action is a re-cut; it does not pass through WriteGuard. What changes is *who proposes*: §5's "proposed by capture (Heimdal)" is refined to "single-stream proposals from Heimdal, fused and assigned by the Mimer Episode Resolution Engine." ADR-0051 is amended by a pointer to this ADR; its decision text otherwise stands.

### 5. Cross-scope fusion is a gated CrossScopeFlow

Because fusion correlates signals across scopes and spheres, a candidate episode that spans scopes is itself a **CrossScopeFlow** event and must be gated and receipted, never silently constructed. This is a first-class engine constraint, not an afterthought.

### 6. No `session` primitive; "Event" stays reserved

"Session" maps onto `Episode`; the engine assigns episode context and does not mint a competing session object. The organ is named the **Episode Resolution Engine**, not an "event engine" — ADR-0051 §6 reserves "Event" for the Heimdal sensor event and outbox plumbing.

## Constraints honored

- Decision record + doc refinements only — no code, schema, or runtime change.
- Refines, does not fork: ADR-0051's entity, dimension, and opt-out posture are preserved; only segmentation *ownership* moves, which is the explicit subject of this ADR (the one `reshape` the grounding doc flagged, now enacted via CES/ADR).
- Preserves Heimdal's FIXED constraints (ends at published event, seam minimization, policy-gated raw access) and the constituent-independence model of ADR-0044.

## Consequences

- The Heimdal Capability Charter OPEN #1 ("how events relate — episodes, threads, correlation") is clarified: Heimdal designs single-stream boundary *hints*; multi-stream episode fusion and assignment are a Mimer capability, out of Heimdal's window.
- The Episode Resolution Engine is now a scoped Mimer capability a future implementation epic can build against. **No implementation issues exist yet** — the engine, the vault-activity stream contract, and the `episode_ref` metadata-bundle wiring (deferred by ADR-0051 as `future_runtime`) still need bounded issues before code.
- Event-triggered relevance decay gains its runtime owner: the Mimer engine emits closure; retrieval consumes it.

## When to revisit

Supersede with a new ADR only if the owner moves the engine out of Mimer, or lets Heimdal own multi-stream segmentation or `episode_ref` assignment. Internal engine design and threshold tuning do not require an ADR revision.

## References

- Grounding: [EPISODE_RESOLUTION_ENGINE](../research/EPISODE_RESOLUTION_ENGINE.md)
- Refines: [ADR-0051](./ADR-0051-episode-as-ontological-primitive.md) §5 (segmentation ownership)
- Related ADRs: ADR-0021 (CES stewardship practice), ADR-0044 (Yggdrasil/Mimer/Heimdal structure), ADR-0045 (constituent interaction tiers), ADR-0049 (Heimdal ingestion organ)
- Clarifies: [Heimdal Capability Charter](../HEIMDAL/CAPABILITY_CHARTER.md) OPEN #1
