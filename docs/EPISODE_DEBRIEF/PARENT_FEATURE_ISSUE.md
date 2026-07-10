State: FILED — the parent feature issue is live as #3331 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the archived draft + local pointer. The whole capability stays agent:blocked (see `README.md :: Blocked on Episode Resolution Engine core delivery`) until ERE core delivery lands — #3177 (ERE-02), #3179 (ERE-04), #3181 (ERE-06); ERE parent #3175 tracks overall progress but is not itself the blocking condition. Children were filed agent:blocked: #3334 (DEBRIEF-01, blocked on ERE core #3175/#3177/#3179/#3181), #3333 (DEBRIEF-02, blocked on DEBRIEF-01/#3334), #3332 (DEBRIEF-03, blocked on DEBRIEF-02/#3333). No child in this capability flips to agent:ready on this spec PR's merge alone.
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue #3331; this file is the archived draft + local pointer
Last reviewed: 2026-07-07

# [Episode Debrief] parent: episode closure → provenance-cited retro synthesis → reviewable in companion UI

Title on GitHub: `[Episode Debrief] parent: episode closure synthesizes a provenance-cited debrief,
reviewable accept/dismiss in the companion UI`

## Context

`docs/research/yggdrasil-closed-loops-ideation.md :: 4. Episode debrief` names the gap: episodes
(meetings, builds, trips) generate exhaust nobody distills; the retro never happens. The Episode
Resolution Engine (`docs/EPISODE_RESOLUTION_ENGINE/`, parent #3175) specifies episode closure only as a
decay trigger (`EMIT_CLOSURE_AND_DERIVE_DECAY.md`) — closure has no other consumer. This capability is
that second consumer: reusing the already-live Create engine
(`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`, EXP-3/EXP-4, #2996/#2997) to
synthesize decisions/commitments/open-loops/key-captures into one candidate artifact per closed episode,
linked from the Episode note, reviewable with a lightweight accept/dismiss.

**This parent, and every child, is blocked from the moment it is filed.** The capability cannot execute
against a real `episode.closed` event, a real Episode note, or a real `episode_ref` binding until three
named ERE children merge — see Scope and the Constraints section below.

## Scope

The capability outcome — not one PR: a durable idempotent trigger from episode closure (respecting the
episode's own scope, never widening it); Create-engine synthesis of a four-section provenance-cited
debrief note, linked from the Episode note via an additive `debrief_ref`, never touching the note's
human-owned content; a companion UI review surface with accept/dismiss, where dismiss never deletes the
artifact. Cross-episode rollups, re-cutting episode bounds, and briefing-delivery mechanics are
explicitly out of scope (see `README.md :: Out of Scope`).

## Source Anchors

- `docs/EPISODE_DEBRIEF/README.md` (spec: tasks, cross-task invariants, capability ACs, blocked-on-ERE
  section)
- `docs/research/yggdrasil-closed-loops-ideation.md :: 4. Episode debrief` (grounding capture)
- `docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md` (the closure event this consumes)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: §2` (the Create engine reused)
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md` (`review_state` vocabulary conformed to)

## SBS Impact

- Primary subsystem: HKA (candidate-class debrief artifact — a new Human Knowledge Artifact class)
- Secondary subsystem(s): SIP (episode closure/`episode_ref` consumption, `debrief_ref` cross-reference),
  CAO (Create-engine synthesis orchestration, reused not rebuilt), GOV (WriteGuard-gated writes,
  review-disposition receipts), RCA (retrieval-seam assembly of decisions/commitments/captures)
- Write class: mixed — mechanical/derived durable via guarded seam (debrief note + `debrief_ref` append,
  candidate/proposal class); no authority-bearing write anywhere in this capability (accept/dismiss are
  `review_state` flips, never `authority_state` promotions or AuthorityReceipts)
- Authority impact: none — debrief content never exceeds `authority_state: proposal`; accept/dismiss are
  review dispositions on the canonical `review_state` axis, not authority transitions
- Persistence impact: new vault note class (episode debrief, staged under `_system/episode-debriefs/`,
  no expiry sweep), one additive frontmatter field on Episode notes (`debrief_ref`); reuses existing
  decision-receipt/commitment/episode-projection substrates as read-only inputs
- Derived/rebuildable impact: debrief inputs are drawn from existing durable sources (decision receipts,
  commitments, `episode_ref`-bound artifacts); the debrief note itself is new durable candidate content
  once written, not a rebuildable projection
- Human knowledge impact: a new human-legible synthesis artifact, candidate-class until human disposition
  (`review_state: draft → reviewed | archived`), never silently authored as canonical
- Memory impact: none — no MEM/machine-memory promotion; debrief content is excluded from ingest indexing
  like other staging-adjacent candidate content until/unless a future capability decides otherwise
- Retrieval/context impact: none beyond existing Create-engine retrieval-seam consumption (read-only,
  activation-gated); the debrief note itself is never citable evidence
- Sync/deployment impact: none beyond the existing vault sync path; no new external dependency
- External boundary impact: none
- New or changed contract: `create.episode_debrief` OutputKind added to the Create engine's closed enum
  (`EXPANSION_CONNECT_AND_CREATE.md` §2.1); `debrief_ref` frontmatter field on Episode notes; new outbox
  topics `debrief.trigger.created`, `episode_debrief.reviewed`, `episode_debrief.dismissed`
- Owner-doc impact: will-update-in-PR — `EXPANSION_CONNECT_AND_CREATE.md` §2.1 output-kinds table
  (bundled with DEBRIEF-02, not a follow-up)
- Transition debt impact: reduces — closes the "closure → synthesis is unwired" gap named in the
  ideation capture; ERE's closure event gains a real second consumer beyond decay
- Fitness rule impact: extends `create_never_autowrites_canonical` and `synthesis_carries_source_provenance`
  coverage to a fourth OutputKind; candidate new fitness-rule row (`debrief_dismiss_never_deletes`) once
  delivered

## Constraints

Blocked until #3177 (ERE-02), #3179 (ERE-04), and #3181 (ERE-06) merge to `main` — see
`README.md :: Blocked on Episode Resolution Engine core delivery`. No task in this capability may mutate
an Episode note's `time`/`title`/`goal`/`space`/`protagonists`/`segmentation`/body (ERE-07's invariant,
extended). No debrief may fuse across scopes the source episode did not fuse (ERE-08's invariant,
inherited unchanged). No acceptance-by-silence for debriefs. Dismiss never deletes. `review_state` and
`authority_state` stay distinct axes per `STATE_AXES_CONTRACT.md` — no new value invented outside that
contract's closed vocabulary.

## Acceptance Criteria

The capability-level ACs in `docs/EPISODE_DEBRIEF/README.md :: Capability acceptance criteria`, each with
its `Verify:` target there — including the fixture end-to-end loop, the never-mutates-episode-content
invariant, the idempotent-one-debrief-per-closure invariant, the scope-never-crossed invariant, the
dismiss-never-deletes invariant, and (post-unblock) a real-episode live validation receipt from the test
channel posted to this issue.

## Implementation Tasks

`docs/EPISODE_DEBRIEF/` — DEBRIEF-01 → DEBRIEF-02 → DEBRIEF-03, a strict flat chain (no parallelization):
1. [TRIGGER_DEBRIEF_ON_CLOSURE](TRIGGER_DEBRIEF_ON_CLOSURE.md) — blocked on ERE #3177/#3179/#3181
2. [SYNTHESIZE_DEBRIEF_NOTE](SYNTHESIZE_DEBRIEF_NOTE.md) — blocked on DEBRIEF-01
3. [SURFACE_DEBRIEF_FOR_REVIEW](SURFACE_DEBRIEF_FOR_REVIEW.md) — blocked on DEBRIEF-02

## Verification Path

Per-task `Verify:` targets (each task file couples ACs to `How to Verify (Pre-Merge)`). No task in this
capability can execute against a real ERE signal before the unblock condition; tests run against fixture
payloads shaped to the ERE-02/04/06 contracts in the interim, and the PR states this explicitly rather
than silently green-lighting on fixtures alone.

## Validation / Acceptance Path

After the unblock condition (#3177/#3179/#3181 merged): each delivered child posts a validation receipt
here (test run links, tick output). After DEBRIEF-03 merges: the fixture end-to-end capability test runs.
One real closed episode is then validated end-to-end on the mac mini test channel (real vault, real
closure) and the receipt is posted here before owner-doc promotion (`EXPANSION_CONNECT_AND_CREATE.md`
§2.1 flip from `will-update-in-PR` to delivered truth, plus a `docs/STATUS.md` Cognitive Expansion ladder
row if the owner judges the capability worth its own row).

## Out of Scope

Re-cutting or modifying episode bounds (ERE-owned, human-terminal); debriefs for still-open episodes;
automatic acceptance; cross-episode synthesis (rollups over weeks — future); briefing delivery mechanics
(Daily Briefing capability, named as a future receipt-consumer seam only).

## Suggested Validation

`pytest -q -m "not pg" tests/episode_debrief/`; `python -m app.cli episode-debrief tick --json` /
`synthesize --json` against a fixture vault; post-unblock, the same commands against the Bifrost test
vault on the mac mini test channel; receipts to this issue.

## Source Docs

`docs/EPISODE_DEBRIEF/README.md`; `docs/research/yggdrasil-closed-loops-ideation.md`;
`docs/EPISODE_RESOLUTION_ENGINE/README.md`; `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`.
