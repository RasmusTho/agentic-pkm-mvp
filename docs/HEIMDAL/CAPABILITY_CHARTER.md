State: Enacted charter with a shipped v1 baseline. This 2026-07-04 Fable entry contract remains the design record for Heimdal's fixed constraints and originally open problems; the v1 capture-to-projection pipeline is implemented in `app/heimdal/`, while later modalities and named follow-ons remain target-state work.
Doc role: Capability charter (Draft) — Fable entry point
Authority: Authoritative for the *scope contract* of the Heimdal architecture window: what is fixed, what is open, and the proposed fitness invariants. Subordinate to `ECOSYSTEM_SOS_MODEL.md` (where Heimdal sits) and `OWNER_DECISIONS.md` (owner-reserved calls). Claims no shipped reality.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: this doc + `ECOSYSTEM_SOS_MODEL.md`, `OWNER_DECISIONS.md`, owner decision session 2026-07-04.

# Heimdal A3 — Capability charter (Fable entry point)

## What Heimdal is

**Heimdal = Event Capture & Attribution.** It continuously observes reality and converts observation
into **attributed, timestamped events** carrying **confidence** and **provenance**. Its responsibility
ends at a **published event**. Everything downstream (knowledge promotion in Munin, agent reasoning in
Hugin) is a read-model of that stream and is out of scope here.

This charter is the contract for the Fable-5 architecture window (`FABLE_WINDOW.md`). Fable solves the
OPEN problems **within** the FIXED constraints. Anything that would change a FIXED constraint, or that
appears in `OWNER_DECISIONS.md`, stops and returns to the owner.

---

## FIXED — constraints Fable may not touch `[conform to owner decisions + SoS model]`

These are settled. Fable designs within them; it does not relitigate them.

1. **Position in the SoS.** Heimdal is a **sibling constituent**, not a subsystem of Munin. It owns
   the append-only fact stream; other constituents are downstream read-models. (`ECOSYSTEM_SOS_MODEL.md` §1–§2)
2. **Ends at a published event.** Heimdal's boundary is a published, attributed event. It does not
   own knowledge promotion, memory, or agent action.
3. **Event-log-vs-projection.** The event stream is append-only and canonical for "what was observed";
   downstream projections never mutate it and never make an event canonical knowledge without governed
   promotion.
4. **Consent posture.** Single-party consent; **always-on capture OFF by default** (opt-in per
   place/session); third parties present must be **marked/degraded** in the resulting events. This is a
   guardrail, not a design variable. (`OWNER_DECISIONS.md` D-CONSENT)
   **Posture ruling updated by [ADR-0060](../adr/ADR-0060-capture-posture-b-full-voice-identity.md)
   (2026-07-10):** the owner has ruled the *target* posture B-full (always-on) with voice
   identification, activation staged behind explicit gates. The mechanism here is unchanged —
   opt-in per place/session and third-party marking/degradation stand; ungranted third parties
   stay degraded even under B-full.
5. **Raw-layer privacy seam.** The raw observation layer is **encrypted at rest and isolated**. Access
   is **policy-gated** (CrossScopeFlow-grant), available to trusted downstream agents under policy —
   not human-only, and not open. Only **published, minimized, attributed** events cross the seam by
   default. (`OWNER_DECISIONS.md` D-PRIVACY)
6. **Identity is shared substrate.** Attribution resolves against the **shared Layer-2 identity/entity
   register**; Heimdal does not mint a private, divergent notion of "who." (`ECOSYSTEM_SOS_MODEL.md` §5)
7. **Retention.** Primary model is **event-triggered relevance decay**; the raw layer additionally
   carries a **bounded hard retention** for privacy. Fable may design the mechanism, not replace the
   model. (`OWNER_DECISIONS.md` D-RETENTION)
8. **Provenance is non-negotiable.** Every event carries provenance and confidence; raw evidence is
   immutable and replayable through improved stages (KAP replayability principle). The *shared
   provenance standard* is a fixed guardrail even though the backbone choice (below) is open.
9. **Repo topology.** Monorepo with a hard internal seam until a split-trigger fires
   (`ECOSYSTEM_SOS_MODEL.md` §4). Fable may recommend a split-trigger has been met; it may not
   unilaterally split.
10. **Governance is Layer 1, not runtime.** Cross-constituent rules are contracts enacted via CES/ADR.
    Fable proposes contracts; it does not build a governance service.

---

## OPEN — the problems Fable must solve `[extend]`

Each item is a genuine design problem. Fable should produce a recommended design + alternatives +
trade-offs, and flag anything that turns out to need an owner decision.

1. **Event contract / schema / ontology.** What is an "event"? The minimal envelope (identity,
   time, actor(s), observed content, confidence, provenance, sensitivity, consent-state). How events
   relate (episodes, threads, correlation). Prose-mirror-of-schema style, consistent with
   `docs/architecture/*` contract docs. **Scope clarified by [ADR-0054](../adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md):** Heimdal designs single-stream boundary *hints* only; multi-stream episode fusion and `episode_ref` assignment are a **Mimer** organ (the Episode Resolution Engine), out of Heimdal's window.
2. **Confidence model.** What confidence means (transcription certainty, attribution certainty,
   interpretation certainty — likely orthogonal, not one scalar), how it is produced, and how
   downstream must treat low-confidence events.
3. **Attribution + entity-resolution coupling.** How raw observation is resolved to canonical
   identities in the shared register; how ambiguity/unknown actors are represented; how attribution
   errors are corrected without mutating the append-only record (correction-as-new-event).
4. **Event-bus choice.** Whether the Layer-2 bus generalizes the existing DB outbox
   (`docs/EVENTS.md`) or is a new stream-native transport; delivery/ordering/replay semantics;
   backpressure. (`ECOSYSTEM_SOS_MODEL.md` §5)
5. **Heimdal vs. KAP.** Whether Heimdal shares KAP's acquire→candidate→publish backbone
   (generalized to a real-time stream) or owns a stream-native backbone, given the fixed shared
   provenance standard. **Owner explicitly left this to Fable** (`OWNER_DECISIONS.md` D-BACKBONE).
6. **Consent model (mechanism).** How the fixed consent posture is realized: place/session opt-in,
   third-party detection and event degradation, consent-state on every event, revocation, and its
   effect on already-captured raw data.
7. **Trust / threat model.** Adversaries and failure modes for the most sensitive data in the
   ecosystem: raw-layer compromise, mis-attribution, covert capture, exfiltration via a downstream
   agent's CrossScopeFlow grant, and the mitigations that keep the privacy seam intact.
8. **Proposed fitness invariants.** The named architecture invariants Heimdal must satisfy, in the
   style of `docs/testing/invariant-tests.md` (see below for seeds).

---

## Proposed fitness invariants (seeds for Fable to refine) `[extend]`

Advisory starting set — Fable should refine, formalize, and map each to an enforcement level and a
future test path, consistent with the invariant registry pattern.

- **HEIM-1 Append-only truth.** A published event is immutable; corrections are new events, never
  edits. Enforcement: high.
- **HEIM-2 Provenance survives.** Every event and every downstream projection of it carries
  resolvable provenance back to the raw evidence. Enforcement: high.
- **HEIM-3 Consent-gated capture.** No capture occurs without an active consent-state; always-on is
  off unless explicitly opted in. Enforcement: high.
- **HEIM-4 Seam minimization.** Only minimized, attributed events cross the raw→published seam;
  raw payload never leaks into a published event by default. Enforcement: high.
- **HEIM-5 Policy-gated raw access.** Raw-layer reads require a CrossScopeFlow grant and produce a
  receipt; no ungoverned raw read path exists. Enforcement: high.
- **HEIM-6 Attribution honesty.** Confidence is never silently upgraded; unknown/ambiguous actors are
  represented explicitly, not guessed as a canonical identity. Enforcement: medium.
- **HEIM-7 Decay is event-triggered.** Relevance decay fires on triggering events, not merely age;
  the raw layer honors its bounded hard-retention regardless. Enforcement: medium.
- **HEIM-8 Not authority.** A Heimdal event is candidate evidence; it cannot become canonical human
  knowledge without a governed authority transition in Munin. Enforcement: high.

## SBS reconciliation summary

| Section | Reconciliation |
|---|---|
| FIXED constraints (position, seam, consent, identity, retention, provenance, topology, governance) | `conform` to owner decisions + `ECOSYSTEM_SOS_MODEL.md` |
| OPEN problems (event contract, confidence, attribution, bus, backbone, consent mechanism, threat model, invariants) | `extend` — new capability design within fixed boundaries |
| Any FIXED change proposed by Fable | `reshape` → back to owner via CES/ADR |

## References

- `ECOSYSTEM_SOS_MODEL.md` — where Heimdal sits (A1).
- `OWNER_DECISIONS.md` — reserved owner calls + captured decisions (A4).
- `FABLE_WINDOW.md` — how the Fable window runs (A5).
- ADR-0043 — naming.
- `docs/testing/invariant-tests.md` — invariant-registry pattern the fitness seeds follow.
- `docs/KNOWLEDGE_ACQUISITION/README.md` — KAP acquire→candidate→publish precedent.
