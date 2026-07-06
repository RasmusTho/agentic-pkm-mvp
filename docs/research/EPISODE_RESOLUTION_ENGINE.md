State: Advisory research proposal for a runtime organ (the Episode Resolution Engine) that operationalises the `Episode` entity (ADR-0051) and the `episode_ref` dimension. Changes no runtime behaviour. Subordinate to the doctrine, the cognitive ontology, ADR-0051, ADR-0044 (Mimer/Heimdal constituent split), and the Heimdal Capability Charter. The one posture it proposes to reshape (segmentation ownership) is routed to CES/ADR below, not asserted as settled.
Doc role: Research / candidate subsystem proposal
Temporal class: timeless (changes when semantics change, not when time passes)
Review cadence: event-driven
Source of truth: mixed (this repo's canonical ontology + academic synthesis carried from ADR-0051)
Last reviewed: 2026-07-06
Last verified against: docs/research/EPISODE_AS_ONTOLOGICAL_PRIMITIVE.md, docs/adr/ADR-0051-episode-as-ontological-primitive.md, docs/HEIMDAL/CAPABILITY_CHARTER.md, docs/architecture/semantic-dimensions.md, docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md, docs/adr/ADR-0044-research08-d1-conforms-to-acknowledged-sos.md

# The Episode Resolution Engine

> **Proposal doc.** This describes the missing *runtime organ* that the Episode ontology already presupposes: the subsystem that segments multiple information streams into `Episode`s and assigns `episode_ref` to the information that originated within them. ADR-0051 defined the Episode *entity* and its opt-out segmentation *posture*; it did not define the engine that runs it, nor extend it beyond Heimdal's single stream. This doc develops that engine and surfaces the one placement decision it forces. It changes no runtime behaviour and enacts nothing on its own.

## TL;DR

- ADR-0051 gave us the **static** pieces — the `Episode` situation model, the `episode_ref` dimension, closure-driven decay — and one line of dynamics: *"Heimdal proposes an Episode boundary via five-dimension shift."* Nobody has built the organ that runs that line, and that line is **single-stream**.
- The **Episode Resolution Engine** is that organ. It does three jobs: **(1) segment** the timeline into episodes by detecting five-dimension shifts, **(2) assign** `episode_ref` to every artifact/observation that originated inside an episode, and **(3) emit closure** so event-triggered decay can fire.
- The genuinely new contribution beyond ADR-0051 is **multi-stream fusion**: correlating Heimdal events *with* calendar, location, and vault activity so that a coherent lived situation is recognised even when no single stream would reveal it. Heimdal v1 is single-stream (voice).
- This forces **one decision**: does the fusion+assignment engine live in **Heimdal** or **Mimer**? The proposal argues **Mimer**, because assignment is a knowledge-layer write Heimdal is forbidden to make, and fusion is cognition, not sensing. Heimdal keeps contributing single-stream boundary proposals.
- Moving fusion to Mimer **reshapes** the ADR-0051 posture that Heimdal owns segmentation. That reshape is routed to CES/ADR here; it is not assumed.

## Why an organ, not just an entity

ADR-0051 was careful to define the Episode *upstream of capture*, so the capture pipeline would not bake in assumptions about an undefined primitive. The symmetric gap is now visible on the other side: the entity exists, but the **runtime process that produces and maintains it** does not. Concretely, ADR-0051 leaves these undefined:

- *what* watches the streams and decides a boundary has occurred (RQ1 thresholds are open);
- *what* writes `episode_ref` onto a note, a chat, a touched file — the "assign session context to information" half;
- *what* flips `closed` and notifies the retrieval layer so decay fires.

Those three are one subsystem. Naming and placing it is the work this doc does.

## The three jobs

1. **Segmentation.** Consume signal streams and detect five-dimension shifts (new place / new people / new goal / time-gap / causal break — ADR-0051 commitment 2). Emit *proposed* episode boundaries with a `derived_from` set of the events/signals that support them. Posture stays **opt-out** (ADR-0051 interaction model): the proposal stands unless the human re-cuts.
2. **Assignment.** For each artifact/observation that originated within an episode's bounds — a Heimdal event, a vault note, a chat session, a touched file — set `episode_ref` (or `pending`/`unbound`). This is the operational meaning of *"tilldela session-kontext till information."* It must survive derivation (ADR-0051 invariant candidate `observation_episode_binding_survives`).
3. **Closure → decay.** When an episode's `closed` flips true, notify retrieval so the bound observations drop in salience (the Event Horizon Model working-model flush; ADR-0051 "relevance decay = episode closure"). Open episodes stay hot.

## The new part: multi-stream fusion

Heimdal v1 senses **one** stream (voice memos → iCloud watch). ADR-0051's "five-dimension shift" is therefore, today, a *single-stream* detector. The engine's real leverage is that the five dimensions are best recovered by **correlating several streams**, none of which is sufficient alone:

| Dimension | Weak single-stream signal | Strong fused signal |
| --- | --- | --- |
| time | event timestamp | event + calendar block + vault edit burst |
| space | (absent in voice) | device location + calendar location |
| protagonist | ASR speaker attribution | attribution + calendar attendees + note @mentions |
| goal | topic guess from transcript | topic + which Project/Area notes were open/edited |
| causation | prior event id | prior episode + preceding calendar item + linked note |

A calendar block + a location + three edited notes + one voice memo inside the same window is **one episode**, even though the voice stream alone would under-segment and the vault stream alone could not place or attribute it. Fusion is where "Heimdal's attribution logic" becomes an actual **situation engine**. It is also the part ADR-0051 did not scope.

## The decision this forces: Heimdal or Mimer?

ADR-0051 says Heimdal proposes segmentation. That is coherent while segmentation reads only Heimdal's own events. The multi-stream framing breaks that boundary and forces a placement choice.

**Proposal: the engine lives in Mimer.** Three grounds, in descending strength:

1. **Assignment is a Mimer write.** `episode_ref` is set on Mimer artifacts (notes, chats) near the metadata bundle / HKA authority path. The Heimdal Capability Charter fixes that Heimdal *ends at a published event* (HEIM-2) and does not own knowledge, memory, or promotion. Heimdal therefore **cannot** write `episode_ref` onto vault artifacts. The assignment half must be in Mimer regardless of where detection sits.
2. **Fusion is cognition, not sensing.** Correlating sensor events with vault activity and calendar to construct a situation model is inference over the knowledge plane — Mimer's role (the knowledge-and-cognition constituent, ADR-0044), not Heimdal's (the sensor constituent).
3. **The entity is already Mimer's.** ADR-0051 OD-1 placed `Episode` as a Layer-3 Artifact, canonicalised through HKA/WriteGuard. The organ that produces that entity belongs where the entity is canonicalised.

**The seam.** Heimdal keeps proposing **single-stream** boundaries from its own events (an attribution refinement it is well placed to do, and which respects "Heimdal owns attribution" from ADR-0051). The **Mimer** engine *fuses* those proposals with the other streams into canonical episodes and performs assignment. Heimdal becomes one contributing stream among several, not the segmenter of record. This keeps both constituents' independence tests intact (ADR-0044) and keeps the raw-layer privacy seam (HEIM-4/5) untouched — only minimised, attributed events cross into Mimer, as today.

## SBS reconciliation (per claim)

Per the repo convention that architecture claims state conform / extend / reshape versus the settled baseline:

- **Segmentation exists as a posture → extend.** ADR-0051 defined *that* boundaries are proposed opt-out; this doc defines the *organ* that proposes them and adds the closure→decay notification path. No conflict.
- **`episode_ref` assignment → conform.** Uses the dimension exactly as ADR-0051 defined it (survives derivation; `pending`/`unbound` allowed). This doc only says *what process* sets it.
- **Multi-stream fusion → extend (new).** ADR-0051 is silent on streams beyond Heimdal; this adds a fusion contract. Silence, not conflict — but it is net-new surface, so it is a candidate, not a clarification.
- **Segmentation *ownership* moves Heimdal → Mimer → RESHAPE.** ADR-0051's interaction model reads "Heimdal proposes." Relocating the fusion+assignment engine to Mimer, and demoting Heimdal to a single-stream contributor, changes an accepted posture. **This is the one reshape and it routes through CES/ADR** (below); it is not enacted here.

## Reshape routing (CES/ADR) — not yet enacted

The ownership relocation is an ontology/constituent reshape, not a clarification. It must route through a CES/ADR step before any implementation, and that ADR would edit: `docs/HEIMDAL/CAPABILITY_CHARTER.md` (Heimdal contributes single-stream proposals, does not own multi-stream segmentation), ADR-0051's interaction model (segmentation ownership), and `docs/architecture/semantic-dimensions.md` (the process that stamps `episode_ref`). This doc is the grounding; the ADR is the enactment. No canonical edit is made here.

## Privacy seam (load-bearing)

Fusion correlates signals **across scopes and spheres**. A fused episode can reveal that a *private-scope* location coincided with a *work-scope* note — a cross-scope inference that no single stream exposed. The engine must therefore run inside the existing `scope_binding` and cross-scope-flow gates: a fused episode that spans scopes is itself a CrossScopeFlow event and must be gated/receipted, not silently constructed. This is a first-class design constraint, not an afterthought — it is the most likely place the engine leaks.

## Do not introduce a "session" primitive

The originating intuition named "event/session context." ADR-0051 and the context-layer model (scope / sphere / situated-identity + ContextEnvelope) are explicit that no monolithic `session` entity is needed. **"Session" maps onto `Episode`.** The engine assigns episode context; it does not mint a competing session object. Introducing one would fork the ontology it is meant to serve.

## Naming

Called the **Episode Resolution Engine**, deliberately **not** an "event engine." ADR-0051 reserves the term *Event* for Heimdal sensor-events and outbox plumbing ("'Event' as a term is reserved for Heimdal sensor-events and outbox plumbing, never for the Episode"). An "event engine" name would collide with that reservation. The engine *resolves* streams into episodes — hence the name. Final naming (including any Norse constituent-style label) can follow the CES/ADR.

## Suggested build order (not scoped here)

To avoid overbuilding into the open RQ1 threshold problem:

1. **Two streams first** — Heimdal voice events + vault activity — plus the closure→decay path. Enough to prove segmentation and assignment end-to-end.
2. Add **calendar** (strongest cheap signal for time/protagonist/goal), then **location** (space).
3. Only then tune multi-stream shift thresholds (RQ1) against the real vault.

Each step is a bounded slice; none should precede the CES/ADR that resolves the placement reshape.

## Open research questions

- **RQ-E1 (inherits ADR-0051 RQ1)** — Multi-stream five-dimension shift thresholds that segment well without over/under-cutting, given heterogeneous stream cadences (a voice memo is bursty; vault edits are continuous; calendar is sparse).
- **RQ-E2** — Fusion confidence: how does a fused boundary combine per-stream confidences (Heimdal's per-axis confidence block, calendar certainty, edit-burst strength) without silently upgrading attribution (HEIM-6)?
- **RQ-E3** — Late-arriving signals: a stream can deliver evidence for an episode after its boundary was proposed (a delayed transcript, a back-dated calendar edit). Does this re-cut (RQ2 identity), or attach as a revision?
- **RQ-E4** — Cross-scope fusion policy: when a candidate episode spans scopes, is it withheld, split per scope, or surfaced as a gated CrossScopeFlow proposal?

## Out of scope

Heimdal capture internals and device feasibility; the decay curve shape (ADR-0051 RQ3); machine-memory consolidation mechanics; the event-bus / backbone choice (Heimdal D-BACKBONE, still open); Posture B ambient capture. This doc defines the *resolution organ*; those are neighbouring epics.

## Grounding

Carries the event-cognition grounding of ADR-0051 (Zacks & Tversky 2001; Zwaan & Radvansky 1998; Radvansky & Zacks 2014, Event Horizon Model). Multi-stream fusion draws on the same event-segmentation-from-multimodal-input line (Baldassano et al. 2017, nested cortical event hierarchy) applied to a personal information substrate rather than perceptual input. Constituent placement follows ADR-0044 (Mimer knowledge-and-cognition vs. Heimdal sensor) and the Heimdal Capability Charter fixed constraints.
