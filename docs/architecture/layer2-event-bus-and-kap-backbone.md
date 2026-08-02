State: Design record (issue #4545, 2026-08-02; the bounded docs-only deliverable owner decision OD-3 option (a) committed to — `docs/architecture/evolution-graph.md :: Owner decisions`, epic #2778). Resolves the Layer-2 event-bus direction and the Heimdal/KAP-backbone question **at design level only**. It authorizes no build work, schedules nothing, and asserts nowhere that the Layer-2 substrate is built or scheduled; build work waits on the named substrate prerequisites below.
Doc role: Architecture design record (Layer-2 platform substrate)
Authority: Authoritative for the chosen event-bus direction and the KAP-backbone contract decision, as design. Subordinate to owner docs (`docs/ROADMAP.md`, `docs/STATUS.md`, `docs/ARCHITECTURE.md`) and to the owner-gated enactment channel: formal promotion of any mechanism to the Layer-2 substrate remains R-PROMOTE (`docs/HEIMDAL/OWNER_DECISIONS.md`) and lands via ADR/CES, not via this doc. Shipped-runtime truth stays with `docs/EVENTS.md` and the code it documents.
Owner: Architecture / CES stewardship
Temporal class: strategic
Review cadence: event-driven

# Layer-2 event-bus substrate and KAP-backbone design

## Purpose and placement

`docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` §5 left two Layer-2 substrate rows marked **Open design
(Fable)**: the cross-constituent **event bus** (generalize the existing outbox vs. a stream-native
bus) and the **provenance/replay backbone** (shared with the KAP acquisition line vs.
Heimdal-native). `docs/architecture/evolution-graph.md` carries the same two open questions on its
Layer-2 event-bus and Heimdal sensor nodes. This document closes both at design level.

It lives under `docs/architecture/`, not `docs/HEIMDAL/`, deliberately: the three-layer model
(`ECOSYSTEM_SOS_MODEL.md` §3) defines Layer 2 as substrate *owned by no single constituent*, and
warns that confusing the layers is the main architectural failure mode. A Layer-2 design filed
inside one constituent's directory would embody exactly that confusion. The Heimdal-constituent
design detail stays where it is (`docs/HEIMDAL/FABLE_COMPANION.md`); this doc consolidates the
ecosystem-level decisions and links down.

What has already happened, and is not re-decided here:

- `FABLE_COMPANION.md` §4 designed Heimdal's v1 stream (append-only log + per-consumer cursors,
  DB-native, outbox-disciplined) and §5/§9-k the Heimdal↔KAP boundary.
- ADR-0049 ratified the §9-k reshape: **Heimdal is the ecosystem ingestion organ** (watch → fetch →
  transcribe → attribute for all external sources; Mimer owns cognition from the handoff).
- The v1 stream shipped: `heimdal_observation_log` + per-consumer cursors + the
  `heimdal.observation.published.v1` schema (`docs/EVENTS.md :: Heimdal observation log`), and the
  Episode Resolution Engine generalized the cursor pattern to the shared outbox table
  (`docs/EVENTS.md :: Secondary per-consumer cursor readers`, ERE-04 #3179).

This doc's job is to take those constituent-local facts and answer the two questions **at Layer-2
scope**, name the substrate prerequisites, and reconcile the evolution graph.

## Event-bus direction

**Decision: generalize the outbox — as a discipline, not as a table.** The Layer-2 event-bus
substrate is the **append-only-log + durable-per-consumer-cursor contract**, DB-native, reusing the
existing outbox machinery verbatim. A stream-native broker is rejected as the substrate direction
now, and is designated as an ADR-gated *transport swap* behind the same contract later.

The contract (each element already normative in `docs/EVENTS.md`; listed here as the Layer-2
composition, not restated):

1. **Envelope** — the canonical outbox envelope (`event`/`event_id`/`trace_id`/`source`/
   `timestamp`/`payload`/`meta`), reused via `app.events.schema.make_outbox_event`.
2. **Write discipline** — deterministic idempotency key via the single shared
   `derive_idempotency_key` helper (KERNEL-02) and schema-registry validation at write (KERNEL-08).
3. **Log semantics** — a canonical stream is insert-only (no `delivered_at`, no updates ever;
   corrections are new rows), per the shipped `heimdal_observation_log` contract.
4. **Consumption** — each consumer owns a durable `(consumer_id, position)` cursor, advanced
   explicitly and monotonically; reading never mutates shared delivery state; replay = rewind your
   own cursor; a new read-model rebuilds from event zero.
5. **Seam discipline** — consumers read through the owning constituent's read API, never by
   querying another constituent's table directly.

Why "generalize the outbox" and not "reuse the outbox table": the DB outbox is a *work queue*
(single logical consumer, `delivered_at` completion) and stays exactly that — the event log of
Mimer's plane per `docs/architecture/formal-model.md` (`P.outbox` in the state tuple, the §2.2
at-least-once consumer contract, and the FD-P failure domain are all unchanged by this design).
What generalizes is the *pattern*. This is not speculative: the pattern is already instantiated
twice in shipped runtime, in both directions the substrate needs —

- a **new canonical stream** beside the outbox (`heimdal_observation_log`, #3039), and
- a **secondary cursor reader** over the outbox table itself, without touching `delivered_at`
  (ERE-04 `vault.activity` stream, #3179 — documented as the precedent every future secondary
  reader follows).

Why not stream-native now (`FABLE_COMPANION.md` §4.3(b), reasoning adopted at Layer-2 scope): a
broker adds always-on infrastructure and a second persistence technology to operate, back up, and
secure inside the most sensitive trust boundary, for volumes that do not demand it; and the
DB-native log meets every stated requirement (multi-consumer, replay-from-zero, at-least-once,
idempotent). The decisive Layer-2 point is that **the contract is the substrate, the transport is
an implementation**: the five clauses above are written so a broker can implement them without
consumer changes. Adopting one later is a transport swap plus an ADR — reopened on evidence
(measured volume, or ECOSYSTEM_SOS_MODEL §4 split-trigger 2 moving Heimdal to separately
credentialed infrastructure) — not a redesign. This design therefore forecloses nothing that
stream-native would have bought.

Non-divergence guarantee: this design changes no transition, invariant, consistency rule, or
failure domain in `docs/architecture/formal-model.md`. Any *future* new canonical stream extends
the formal model's state tuple and must carry its own formal-model reconciliation in the change
that builds it — build work, expressly not performed here.

## KAP-backbone decision

The open question, as carried by the evolution graph's Heimdal node: do Heimdal's
ingestion/acquisition constituents (Karakeep-class sources, screen/audio sensors) share **one
backbone contract** with the KAP acquisition line, or use a **distinct** one?

**Decision: one shared backbone contract — the Heimdal published-observation backbone.** Every
Heimdal ingestion/acquisition constituent publishes onto the shared contract: the append-only
observation log, the `heimdal.observation.published.v1` payload schema, per-consumer cursor
consumption, and the fixed shared provenance primitives (`content_identity` join key, immutable raw
evidence, single-touch source rule, stage-local replay with `stage_versions` lineage —
`FABLE_COMPANION.md` §5.2's primitives table, which remains the concrete form of the D-BACKBONE
guardrail). No per-source topics, logs, read APIs, or cursors.

Grounding, in order of authority:

- **ADR-0049 §1** (ratifying `FABLE_COMPANION.md` §9-k): Heimdal owns watch → fetch → transcribe →
  attribute for *all* external sources. The earlier §5.2 "separate backbones" recommendation was
  superseded at ownership level by that reshape — with one ingestion organ there is one acquisition
  backbone, with Mimer downstream of the published event. This doc records the contract-level
  consequence.
- **The Karakeep precedent proves it concretely** (KMA-01, #3372;
  `docs/EVENTS.md :: Karakeep published-evidence profile`): a Karakeep-class source conforms to the
  *existing* published-v1 schema and log — "no Karakeep-specific topic, log, read API, or cursor is
  introduced". That is the shared-backbone answer executed for the first non-sensor source class,
  and it is the template for screen/audio sensor constituents.
- **The rejected alternative** (each source class gets its own backbone, or sensors ride KAP's
  batch pipeline) is `FABLE_COMPANION.md` §5.2 alternative (a)/(b) territory: it either smears the
  raw privacy seam across a contract that is neither encrypted nor consent-aware, or forks the
  provenance vocabulary the ecosystem needs to join across constituents. Both remain rejected.

Boundary honesty about the delivered KAP pipeline: KAP Phase 2 (KA-01..06) shipped a batch
pipeline whose stage events ride the DB outbox (`docs/KNOWLEDGE_ACQUISITION/README.md`). That is
shipped reality and stays valid. ADR-0049 names the migration of KAP's acquisition front-end from
Mimer to Heimdal as issue-first enactment work; as that work lands, the front-end converges onto
the shared backbone contract decided here. **This design decides the contract, not the migration**
— it schedules no KAP refactor, and the two lines continue to meet downstream at the candidate
(the existing triage path), which this design leaves untouched.

## Substrate prerequisites

Per OD-3's own consequence ("the design *names* its substrate prerequisites"), the prerequisites
this design depends on are, exactly as the evolution graph's critical path orders them:

1. **Kernel closeout** — #2899 (post-merge kernel audit) and #2901 (second-writer removal). The
   bus contract is the outbox discipline generalized; generalizing a journal whose own honesty
   audit is unfinished bakes in whatever the audit would have moved.
2. **FD-P backup** — outbox/decisions/audit are canonical, non-rebuildable stores
   (`formal-model.md` §5). Every stream this design adds inherits FD-P's exposure; a canonical
   ecosystem bus on an unbacked-up failure domain widens the largest unbounded-loss surface.
3. **Property layer** — P-1..P-7 (from #2781). The bus contract's clauses (idempotency,
   append-only, cursor monotonicity) are exactly the kind of standing law the property layer makes
   machine-checked; building more producers/consumers before the law is pinned multiplies
   unverified surface.

**Build work waits on these prerequisites.** Concretely, all of the following are deferred until
they land, and none is authorized or scheduled by this document: formal Layer-2 promotion of the
bus contract or the provenance primitives (R-PROMOTE, owner-gated, via ADR/CES); any stream-broker
transport swap; the KAP acquisition front-end migration; and any new canonical stream or secondary
cursor reader beyond those already shipped. The live state of the prerequisites is their GitHub
issues, not this doc — nothing here claims they are complete, in progress, or scheduled.

## Reconciliation with the evolution graph

`docs/architecture/evolution-graph.md` recommends deferring "Layer-2 event bus + Heimdal build —
until kernel closeout + FD-P backup land", and OD-3 chose design-now/build-after-substrate. This
document **conforms to that recommendation and does not supersede it**: it is the design OD-3
option (a) commissioned, its prerequisites section restates the graph's hard edge
(kernel closeout → bus) as binding on build work, and the graph's own node/edge structure remains
the sequencing authority. What this doc changes is only the *open-question* annotations: the
"Open Fable design (generalize outbox vs stream-native)" note on the event-bus node and the
"KAP-backbone question open" note on the Heimdal node are resolved at design level, with the graph
linking forward here (writeback performed in the same change that lands this doc).

## What this design does not do

- No runtime code, migration, dependency, or config change (OD-3 option (a); issue #4545).
- No assertion that the Layer-2 substrate is built or scheduled; no implementation plan with dates.
- No enactment of substrate promotion — R-PROMOTE stays owner-gated (ADR/CES).
- No re-decision of OD-1/OD-2/OD-4, of ADR-0049's boundary, or of any FIXED charter constraint.
- No change to the KAP pipeline's shipped behavior or to the triage/promotion path.

## References

- `docs/architecture/evolution-graph.md` — OD-3, the Layer-2/Heimdal nodes, the critical path.
- `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md` — three-layer model, §5 substrate inventory this resolves.
- `docs/HEIMDAL/FABLE_COMPANION.md` §4, §5, §9-k — the constituent-local design consolidated here.
- `docs/HEIMDAL/OWNER_DECISIONS.md` — D-BACKBONE guardrail; R-PROMOTE, R-SPLIT reserved decisions.
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` — the ratified ingestion-organ boundary.
- `docs/EVENTS.md` — outbox envelope/idempotency/schema registry; Heimdal observation log; ERE-04
  secondary cursor readers; Karakeep published-evidence profile.
- `docs/architecture/formal-model.md` — the outbox/event-log contract this design must not, and
  does not, diverge from.
