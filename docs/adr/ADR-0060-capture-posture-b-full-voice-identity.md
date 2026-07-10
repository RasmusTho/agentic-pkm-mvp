State: Accepted (owner decision, 2026-07-10). Supersedes the capture-posture clause of ADR-0049 §3 (Posture A discrete / Posture B deferred): the target posture is now **B-full (always-on/ambient)** with **voice identification** (operator voiceprint + per-person consent-linked third-party voiceprints). Decision record only — Posture A remains the *operational* posture until the named activation gates pass; no code, no runtime, no consent grant is enacted here. The rest of ADR-0049 (ingestion-organ boundary, markdown-first control surface, app topology) stands unchanged.
Doc role: Decision record (ADR)
Authority: Authoritative for the Heimdal capture-posture decision (A → B-full), the voiceprint consent classes, and the activation-gate discipline that sequences enactment. It does NOT define adapter design, ASR/diarization internals, enrollment mechanics, segmentation thresholds, or any schema/runtime change — those are downstream, issue-first. D-CONSENT/D-PRIVACY ownership stays with `docs/HEIMDAL/OWNER_DECISIONS.md`; this ADR refines D-CONSENT's realization, it does not reverse it.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the posture ruling or the voiceprint consent classes are reversed).
Source of truth: This ADR plus `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §3 (the clause superseded), `docs/HEIMDAL/OWNER_DECISIONS.md` (R-CONSENT/R-EXTERNAL reserved calls; D-CONSENT/D-PRIVACY), `docs/HEIMDAL/CAPABILITY_CHARTER.md` (FIXED #4/#5, HEIM-3/4/5), `docs/HEIMDAL/FABLE_COMPANION.md` (event contract: `attributions[].basis`, third-party degradation), `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md` (device evidence).

# ADR-0060: Capture posture flips to B-full (always-on) with voice identification — staged activation behind explicit gates

**Date:** 2026-07-10
**Status:** Accepted (owner decision, 2026-07-10)

---

## Context

ADR-0049 §3 shipped Heimdal v1 as **Posture A (discrete)** and reserved the flip to **Posture B
(always-on/ambient)** as a future owner decision "carrying the third-party / GDPR weight". That
decision has now been taken. A decision brief (2026-07-10, owner session) steelmanned both
postures; the owner ruled for B-full with voice identification: primarily the operator's own
voice, and additionally the people the operator frequently interacts with, resolved via
per-person consent.

The architecture was deliberately built B-ready: the consent note already writes the B-shaped
mechanism (VAD gating, third-party withhold-and-review, retention/erasure), the event contract
already carries `basis: diarization | voiceprint` in `attributions[]` with third-party speech
degraded to `withheld[]` spans by default, and ADR-0049 promised "a grant + adapter change, not a
redesign". What is *not* ready is the device chain: the Watch cannot stream (verified,
`CAPTURE_TRANSPORT_FEASIBILITY.md` Model 3), the Omi-class pendant is chosen in direction but not
acquired or tested, the B3 native capture client is spec'd but unbuilt, continuous ASR+diarization
load on the host is undimensioned, and the Episode Resolution Engine (ADR-0054) has no
implementation issues. The owner has acknowledged the pendant hardware will take a while. This ADR
therefore records the ruling now and stages activation behind explicit gates, so build work can
sequence against a settled target instead of an open fork.

## Decision (owner, 2026-07-10)

### 1. Target capture posture is B-full (supersedes ADR-0049 §3's posture clause)

Heimdal's target capture posture is **B-full**: a continuous wearable audio stream (Omi-class
pendant → iPhone → tailnet → host), not only deliberate press-to-record acts. Posture A remains
the **operational** posture until the activation gates in §4 pass — the flip is decided, the
switch-on is staged. ADR-0049 §3's "Posture B is not built in v1 / future owner decision" clause
is superseded by this ruling; ADR-0049's other decisions (ingestion organ, markdown-first control
surface with its two declared bends, Topology C) are untouched.

D-CONSENT's mechanism is preserved, not reversed: always-on capture remains **opt-in per
place/session** — under B-full the grants are expected to be *given* rather than the capability
being deferred. Charter FIXED #4 (third parties marked/degraded) and FIXED #5 / HEIM-4/5 (raw
seam, minimized published events) stand unchanged.

### 2. Voice identification is in scope — two consent classes

Voiceprint attribution (`attributions[].basis: voiceprint`, the v2 slot the event contract already
holds) is ruled in, split into two explicitly different consent classes:

- **Operator voiceprint.** Enrollment of the operator's own voice profile extends the existing
  `self_record` standing consent. This enables self-attribution on a continuous stream (the
  B-solo capability: the operator's speech publishes; unidentified speech degrades).
- **Third-party voiceprints — one grant per person.** A voice profile of another person is
  biometric-class identification. Each enrollment is a **per-person consent-linked identity
  grant**, bound to that person's entity in the shared identity register and recording the consent
  basis. This enacts the shape the event contract already anticipates ("resolved *only* via a
  pre-existing consent-linked identity"). Without a grant, the existing default stands even under
  B-full: third-party speech is not transcribed into published content; it remains a `withheld[]`
  span with `role: present, resolution: unresolved`. Enrolling a person is an explicit owner
  action, never an automatic consequence of frequent co-occurrence.

### 3. Multi-stream direction acknowledged; video/cameras NOT decided here

The B-full stream lands as one contributing stream into the Mimer Episode Resolution Engine
(ADR-0054), alongside calendar, location, and vault activity. Additional ambient sources — e.g.
home security cameras — are architecturally sanctioned by the ingestion-organ boundary (ADR-0049
§1) and by place-based grants, but **video is not an enumerated modality in the event contract and
is not decided by this ADR**. A camera/video source is its own future modality decision with its
own consent/biometric weight (person/face identification escalates beyond voice).

### 4. Activation gates — all must pass before B-full capture turns on

Staged activation, each gate producing a durable receipt:

- **G1 — Device feasibility.** Omi-class pendant acquired and spiked end-to-end (BLE → iPhone →
  tailnet → host): battery, dropout, latency measured. (Hardware not yet in hand; timing open.)
- **G2 — Continuous ASR+diarization load.** The host sustains the continuous pipeline (many hours
  per day of transcription + diarization + voiceprint matching) without degrading the production
  runtime it shares.
- **G3 — B3 native capture client delivered.** The iPhone client (Bifrost B3 slices) exists — it
  is the BLE receiver, the stream transport, and the only point where capture-time episode
  metadata (space/protagonist) can enter.
- **G4 — Cross-scope fusion gating delivered.** ADR-0054 §5's CrossScopeFlow gate for episodes
  spanning scopes is implemented, protecting the charter's cross-domain-leakage failure mode — a
  continuous stream spans life spheres by default.
- **G5 — Consent mechanism operational.** The consent-note mechanism runs in runtime, not only on
  paper: place/session grants honored by the adapter, third-party withhold-and-review working,
  retention/erasure of raw ambient audio exercised at least once.

Operator-voiceprint enrollment (the first half of §2) may be built and used under Posture A
before the gates pass — it hardens attribution on discrete memos and de-risks G2. Third-party
enrollment requires its per-person grant regardless of posture.

### 5. Enactment is issue-first

This ADR performs no code change and grants no consent. Follow-up work, filed via the normal
docs-to-issue path: the G1/G2 spike issues, the operator-voiceprint enrollment slice, the
consent-note extension for per-person voiceprint grants, and the INV-EF1 register rows any new
device/private bindings require (ADR-0046 categories iii/v).

## Constraints honored

- Decision record only — no code, no runtime, no consent grant, no glossary edit lands here.
- R-CONSENT / R-EXTERNAL are owner-reserved; this ADR records the owner exercising them, per the
  supersede path ADR-0049 itself names ("capture posture flips to always-on-default").
- D-CONSENT is refined in realization, not reversed: opt-in per place/session, third-party
  degradation default, and single-party declaration for ungranted parties all stand.
- HEIM-3 (consent-gated capture), HEIM-4 (seam minimization), and HEIM-5 (policy-gated raw
  access) are load-bearing preconditions of B-full, not relaxed by it.
- Markdown-first (ADR-0049 §2) holds: the durable record of a continuous stream is episode-level,
  minimized, human-legible artifacts — the two declared bends (attention firehose, device
  telemetry) remain the only sanctioned UI-only lenses.
- Single-user stance preserved: one operator; voice identification adds identified *subjects*, not
  users or authority holders.

## Consequences

- The posture fork is closed; build work (B3 client, spikes, engine) sequences against a settled
  target instead of a hedge.
- A real, bounded work queue is created (G1/G2 spikes, enrollment slice, consent-note extension,
  INV-EF1 rows) — none of it performed here.
- Two new consent-class obligations exist: operator-voiceprint under extended `self_record`, and
  per-person third-party grants in the entity register. The second is a standing owner
  responsibility — each enrolled person is an explicit, receipted decision.
- Third-party exposure remains the one irreversible edge: it is bounded by keeping ungranted
  speech degraded-by-default and by G5's operational withhold-and-review, which is why G5 gates
  activation rather than following it.
- Receipt/storage churn under a continuous stream is a named pressure on the charter's
  receipt-legibility invariant; the answer is episode-level aggregation at the seam, to be proven
  during G2.
- ADR-0049 §3 is amended with a pointer to this ADR; its remaining decisions are unaffected.

## When to revisit

Supersede with a new ADR only if the owner reverses the B-full ruling, redesigns the voiceprint
consent classes, or replaces the activation-gate discipline. Passing an individual gate, tuning
thresholds, or sequencing the follow-up issues does not require an ADR revision. A video/camera
modality decision is a new ADR, not a revision of this one.

## References

- Supersedes (posture clause only): [ADR-0049](./ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md) §3.
- Reserved-call register: `docs/HEIMDAL/OWNER_DECISIONS.md` (R-CONSENT, R-EXTERNAL, D-CONSENT, D-PRIVACY).
- Guardrails: `docs/HEIMDAL/CAPABILITY_CHARTER.md` FIXED #4/#5, HEIM-3/4/5/6.
- Event-contract slots this activates: `docs/HEIMDAL/FABLE_COMPANION.md` (`attributions[].basis:
  diarization|voiceprint`, `withheld[]` third-party degradation, v2 deferral list).
- Device evidence: `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md` (Watch cannot stream; pendant
  BLE→iPhone is the B-capable path; B3 client justification).
- Downstream consumers: [ADR-0051](./ADR-0051-episode-as-ontological-primitive.md) (Episode),
  [ADR-0054](./ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) (Resolution Engine, §5
  CrossScopeFlow gate → G4).
- Public/private seam pressure: [ADR-0046](./ADR-0046-inv-ef1-public-private-seam.md) (INV-EF1
  categories iii/v → §5 register rows).
