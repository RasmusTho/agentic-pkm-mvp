State: Accepted - docs/governance decision for #1487. No runtime, API, UI, transport, notification, polling, SSE, WebSocket, worker, or ambient resurfacing behavior is implemented.

# ADR-0011: Orientation Push and Ambient Resurfacing Boundary

**Date:** 2026-06-02
**Status:** Accepted - docs/governance decision for #1487

---

## Context

ADR-0007 introduced `GET /api/companion/orientation` as a note-independent,
read-only Workspace Orientation Snapshot. That surface is pull-based and
snapshot-shaped: the human/UI asks for orientation, the runtime composes bounded
read-side projections, and no write path, hidden state, or notification surface
is created.

Phase 4 left two later questions open: push/ambient resurfacing and multi-agent
reads. This ADR resolves only the push/ambient resurfacing boundary. Multi-agent
reads remain #1459 and must not be collapsed into this decision.

Ambient resurfacing is desirable because some material becomes relevant again
without an explicit query. The risk is that "ambient" gets implemented as a
notification system, hidden nudge bus, background agent action, or server-pushed
stream that competes with the user's document-first attention. That would violate
`companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`, the salience contract, and the
Workspace Orientation read-only boundary.

## Decision

The shipped orientation posture remains **pull, snapshot, read-only**.

`GET /api/companion/orientation` remains the authoritative orientation read
surface. It is not a push endpoint, streaming endpoint, notification endpoint,
or agent coordination bus.

Server-initiated push transport is not approved for the next slice. The
following remain deferred and require a later ADR or explicit owner decision
before use:

- server-sent events;
- WebSockets;
- background workers that push orientation state into the UI;
- browser or OS notifications;
- notification inboxes, badges, counters, sounds, banners, or urgency feeds.

A later bounded implementation issue may add **ambient orientation refresh**
only with client-initiated foreground reads. The allowed v1 transport shape is:

- existing or additive read-only orientation snapshot reads;
- optional low-frequency polling only while Companion UI is open and the
  relevant orientation/resurfacing surface is mounted or visible;
- visibility/focus-triggered refetch after staleness, not background wakeup;
- no server-initiated stream;
- no durable state created by the refresh itself.

Ambient refresh is therefore eligible only as a constrained read optimization
over the existing orientation projection. It is not autonomous delivery and not
notification infrastructure.

## Invalidation and Source Authority

Invalidation authority belongs to server-declared orientation metadata and
source watermarks, not to client-side heuristics.

A future ambient refresh implementation must derive stale/refresh eligibility
from the same orientation contract concepts already used by the read-side
snapshot:

- `meta.as_of`;
- `meta.freshness`;
- `meta.stale_after`;
- `source_watermarks`;
- `degraded_reasons`;
- resurfacing runtime signals carrying `authority_role` and `source_ref`.

The UI may schedule a refetch when the server-declared snapshot is stale or when
the user re-enters a visible orientation surface. The UI must not infer that a
candidate is important, urgent, actionable, or notification-worthy. Importance,
source, provenance, and degradation remain server-declared projection data.

## Low-Noise and No-Notification Rules

Ambient refresh must preserve low attentional load by default.

Required posture:

- default off unless enabled by an explicit feature flag, user preference, or
  bounded test-only configuration;
- bounded concurrent resurfacing marks or candidates;
- no alert, chime, banner, modal, badge, count, inbox, dock/browser
  notification, or urgency color;
- no focus stealing, scroll jump, route change, document displacement, or
  automatic opening of resurfaced material;
- no repeated pulsing or animation loops;
- no resurfacing of low-provenance material as strong guidance;
- no automatic action execution from a surfaced item.

The only acceptable user-facing posture is ambient availability inside the
existing document/orientation surface, with provenance visible when the human
chooses to inspect it.

## Degradation and Opt-Out

Ambient refresh must be easy to disable and honest when degraded.

A future implementation must provide:

- an opt-out or disabled state that stops refresh scheduling;
- explicit degraded state when source watermarks, resurfacing runtime, or
  orientation metadata are unavailable;
- stale-but-visible state rather than fabricated freshness;
- safe fallback to manual pull refresh;
- no cached resurfacing claim presented as current after its freshness window.

If any required source is unavailable or conflicting, the surface must omit the
ambient resurfacing update or mark it degraded. It must not invent a reason why
material surfaced.

## Governance and Follow-On Actions

Ambient resurfacing is read-side projection only.

Any action from a resurfaced item must route through existing governed paths:

- read/open actions remain read-only;
- UI-only dismissal, expansion, or hover remains ephemeral unless a later ADR
  explicitly admits persisted preference state;
- write, review, trust, memory, promotion, or lifecycle transitions route
  through Panel, Canvas, memory review, or another existing governance boundary;
- receipts are produced only by the executing governed path, not by the ambient
  refresh read.

The orientation surface may continue to expose bounded `mutation_intents` only
where an existing ADR allows them. ADR-0011 does not add new mutation-intent
classes.

## Forbidden Paths

The orientation push/ambient path must not:

- create a notification system;
- create an inbox or queue the user is expected to process;
- stream or push state from the server in the next implementation slice;
- wake the UI in the background;
- mutate vault, memory, session, Panel, Canvas, WriteGuard, receipt, or
  governance state;
- persist dismiss/snooze/pin state through the orientation read path;
- make salience, recency, or resurfacing presence an action-authorizing source;
- use client-side ranking as authority;
- hide source/provenance/degradation details from the human;
- mix this decision with multi-agent reads (#1459).

## Rejected Alternatives

### 1. Keep all ambient resurfacing indefinitely deferred

Rejected. The design and salience contracts make ambient resurfacing a real
future capability, and a bounded foreground refresh slice can be tested without
weakening read-only orientation semantics.

### 2. Approve server push, SSE, or WebSockets now

Rejected. The repo does not yet have enough evidence that server-initiated
transport is needed. Approving it now would add operational complexity and raise
the risk of notification-centric or hidden-nudge behavior before the simpler
foreground pull model is proven.

### 3. Implement notifications for newly relevant material

Rejected. Resurfacing is contextual return, not notification delivery.
Notifications, badges, counters, and urgency feeds are incompatible with the
document-first Companion UI boundary.

### 4. Let the UI decide what is important

Rejected. The UI renders server-declared projection data. Source authority,
provenance, ranking signals, and degradation must come from the runtime
projection, not from client-only heuristics.

## Consequences

Positive:

- The current orientation endpoint remains pull/snapshot/read-only.
- The repo gets an eligible follow-up shape for ambient resurfacing without
  approving server push or notification infrastructure.
- Future implementation can be tested against concrete low-noise, provenance,
  degradation, opt-out, and no-write requirements.
- #1458 has a clear rewrite/split posture instead of remaining an ambiguous
  implementation tracker.

Costs and constraints:

- The first eligible ambient refresh slice cannot use SSE, WebSockets, or
  server-initiated push even if those transports might be useful later.
- The UI must implement refresh scheduling conservatively and only from
  server-declared freshness/staleness metadata.
- Any persisted preference, dismissal, snooze, or pin state remains out of scope
  unless a later ADR explicitly admits it.

## Contract Impact

`companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` must continue to state
that the shipped orientation endpoint has no push, streaming, SSE, WebSocket,
notification, or ambient resurfacing transport. It should also point to this ADR
as the future boundary for any ambient refresh child issue.

`docs/adr/ADR-0007-workspace-state-contract-scope-split.md` remains correct:
Phase 4 push/ambient resurfacing was deferred to a later ADR. This ADR resolves
that open question by allowing only a later bounded client-initiated ambient
refresh issue, not server push.

## Verification Requirements

- ADR is present at
  `docs/adr/ADR-0011-orientation-push-ambient-resurfacing.md`.
- ADR is indexed in `docs/adr/INDEX.md`.
- Workspace Orientation Contract points to ADR-0011 while preserving the current
  no-push/no-ambient-transport implementation claim.
- `python3 scripts/docs_guard.py` passes.
- `git diff --check` passes.

## Follow-up Issue Impact

#1458 should not be implemented as written. After this ADR lands, #1458 should
remain blocked until it is rewritten or replaced by a bounded implementation
child for client-initiated foreground ambient refresh.

That child must specify:

- exact read endpoint and polling/refetch trigger;
- default-off feature flag or user preference;
- refresh interval or staleness policy;
- bounded candidate/mark limits;
- source watermark and degraded-state handling;
- opt-out behavior;
- UI affordance constraints proving non-notification-centric behavior;
- tests proving no write path, no notification UI, no hidden state, and no
  automatic action execution.

## References

- Issue #1487: ADR boundary decision
- Issue #1458: deferred push/ambient resurfacing tracker
- Issue #1450: Workspace Orientation epic Phase 4
- `docs/adr/ADR-0007-workspace-state-contract-scope-split.md`
- `docs/research/workspace-state-contract-v61-architecture-memo.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`
- `companion-ui/docs/RESURFACING_HEURISTICS.md`
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
