State: Human-need-first capability brief (forward line; not current runtime truth). Pre-spec seed for a future `feature-breakdown`. Provisional capability name — rename freely before the spec dir is created.
Doc role: Plan / capability brief
Authority: States the human need, shape, and design stance for a proactive contextual-relevance capability. Does not override the capability specs it will seed, the concept contracts it anchors to, or current runtime truth in `docs/ARCHITECTURE.md` / `docs/STATUS.md`.
Owner: `docs/ROADMAP.md`
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-13
Last verified against: docs/HUMAN-FLOWS.md, docs/HUMAN_FLOW_TO_RUNTIME_MAP.md, docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md, docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md, docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md, docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md, docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md, docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/EMERGENT_FEATURES_MODEL.md, docs/FINDING_AND_REORIENTING/README.md, docs/COGNITIVE_LOAD_PROJECTION_LAYER.md, GitHub issues #1881 (governance tiers) and #1796 (parked context-lane/place-band decision)

# Contextual Relevance Engine — proactive, adaptive surfacing

> Human-need-first brief. This document says **what the human needs and the shape of the answer**,
> not the implementation. It is the seed for a later `feature-breakdown` into a spec directory
> plus a parent feature issue and child slices. It supersedes the parked decision in #1796.

## 1. The human need (north star)

> "I should see things when I need them — and that is context-dependent."

The system should reduce the cognitive cost of **knowing what to attend to right now**. The human
should not have to remember to check, or hold the shape of the day in working memory. The system
anticipates the moment, brings the right thing, and **stays quiet otherwise**.

This is a core cognitive-prosthesis function, not a feature: it is reorientation, commitment
awareness, and resurfacing made *timely*. (`docs/HUMAN-FLOWS.md` §0 cognitive-prosthesis, §3
support commitments and action, §5 human rhythms.)

**The failure mode is already written down and is the binding constraint.** `docs/HUMAN-FLOWS.md`
§0: *"a persistent stream of suggestions that the human must monitor is a new burden, not a
prosthetic aid... resurfacing should be scarce, source-linked, and non-authoritative."* A
notification firehose violates the canonical human contract. **Right thing, right moment — silent
otherwise** is the whole discipline.

## 2. One engine, not a list of features

The capability is a **general relevance engine**, not a fixed set of moments. Concrete moments —

- *Start of day* → an overview of the day's shape
- *~10 min before a meeting* → what to know walking in (the thread, last decisions, open actions, linked notes)
- *A deadline exists* → a backward plan from the deadline, each step surfaced when it is time to act

— are **illustrations and acceptance tests, never the spec.** The human's needs are open-ended and
span every kind of work the system supports (knowledge, writing, learning, planning, reflection,
creative, RPG/hobby, commitments) across work / private / creative / RPG spheres
(`docs/HUMAN-FLOWS.md` §1, §4, §9). The engine must express moments nobody enumerated in advance.

## 3. Shape of the engine

Underneath any moment are two general primitives plus a discipline layer:

- **Context model** — the open, extensible set of dimensions describing "now" (time, place, active
  work, which sphere/role the human is in, what is imminent, what has been neglected, what is being
  learned…). Builds on the existing context vocabulary — do not invent a parallel one:
  `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`, `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`,
  `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`.
- **Adaptive relevance evaluator** — given the context, *what does the human need now?* This
  **produces** moments; it does not enumerate them. Its theory layer is
  `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` (what is mentally near/far,
  pressing-because-unresolved, newly relevant, vs. drowning in everything).
- **Patterns** — how the human and the system express what matters: **user-declared first,
  system-proposed (emergent) later.** Patterns are soft guidance for the evaluator, never rigid
  rules.
- **Deterministic discipline layer** — scarcity caps, the governance tiers from #1881, vault-first
  artifacts, local-first execution, provenance, and receipts.

### 3.1 The core architectural stance: adaptive cognition, deterministic gate

The engine must be **adaptable and proactive, not deterministic and locked down.** That has a
precise meaning, and it matches how this system already separates soft cognition from hard gating:

- **What is relevant / what the human needs → adaptive cognition.** Model reasoning over the
  context model, declared patterns, and learned signal — *not* a hardcoded rule tree. It handles
  situations nobody anticipated and **adapts** as it observes what the human engages with vs.
  ignores.
- **When the engine may interrupt or act → deterministic.** Scarcity caps, the
  Act / agent-review / ask-you tiers, write guards, receipts. This stays locked down — it is where
  safety and the human's attention live.

This split is also what resolves the only real tension in "adaptive + proactive": unchecked, a
smart proactive system becomes a firehose. The answer is **smart about what matters, disciplined
about when it intrudes** — the adaptiveness never touches the authority or scarcity layer.

### 3.2 From user-defined to emergent: the same loop

"Adaptable" gives the path from declared patterns to emergent ones as a single feedback loop:

1. The human declares a pattern ("when I'm in *this* context, surface *that*").
2. The engine observes what the human actually opens vs. dismisses.
3. The engine proposes refinements and new patterns.
4. The human keeps or discards them — governed, with receipts.

User-defined is the seed; emergent is the same loop run longer. Emergent proposals are
review-class objects, never silently active authority.

## 4. Governance posture (settled in #1881)

Surfacing is mostly in the safe lane; the deterministic gate is reserved for the few effects the
audit/undo safety net cannot catch.

| Tier | Covers | Human interrupted? |
| --- | --- | --- |
| **Act** | reversible, vault-internal, clear authority — show a briefing, render an overview, log a receipt | no |
| **Agent review** | reversible but ambiguous or higher-stakes — route to a more capable agent to review/decide | no |
| **Ask you** | irreversible or external side-effects (send an email, hit an external API, delete a sole copy), or high-stakes + genuinely unclear | yes |

The safety net is the **log + Git/GitHub history** (every durable change is recorded and
revertible), so the default is *act, don't ask*. "Ask you" is precisely the set of effects the
safety net cannot reverse. Reminders, briefings, and proposed plans are **Act / agent-review**;
*sending* or *booking* is **Ask you**. (See #1881 and
`docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.)

## 5. How this fits the existing model

This is **~90% composition of capabilities the system already names**, plus one genuinely new
dimension.

| The human moment | Existing human-flow anchor | Composes |
| --- | --- | --- |
| Start-of-day overview | §5 *In review* (daily) + `Retrieve → orient → act` | orientation + commitment surfacing |
| Pre-event prep | §5 *During focused work* / *When interrupted* | resurfacing + context bundle + commitment surfacing |
| Deadline → plan | §3 *Support commitments and action* + `Review → reclassify` | commitment layer + suggest-next-action |

It composes the v6.0 capability seams already in flight — orientation / resurfacing
(`docs/FINDING_AND_REORIENTING/`), the commitment layer
(`docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`), context dimensions, and the context bundle
(`docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`) — through the standard
`trigger + context bundle + capability composition + policy + proposal/action + receipt + feedback`
pattern in `docs/EMERGENT_FEATURES_MODEL.md`. Because it rides that pattern, it cannot bypass write
guards, provenance, or authority boundaries by construction.

**The one genuinely new dimension is proactivity.** The current model is almost entirely *pull*
(the human opens orientation; the human runs review). This capability adds *push* — the system
anticipates the moment and reaches out. That **attention loop** (a quiet evaluator watching the
context model and deciding "now is the moment for X") is the real new work; everything else is
reuse.

**Doc writeback when specced:** this becomes a new concept contract (the attention loop / proactive
surfacing) plus a writeback into `docs/HUMAN-FLOWS.md` §5 (rhythms made proactive) and a new row in
`docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — per that map's rule that new flows anchor in HUMAN-FLOWS
first.

## 6. Acceptance corpus (non-exhaustive, by design)

The three illustrations above, plus the §5 rhythms and the §8 everyday scenarios in
`docs/HUMAN-FLOWS.md`, form the corpus the engine must be able to express. It is deliberately
**not** a feature checklist — a new declared pattern that the engine could not express is a design
gap, not an out-of-scope request.

## 7. Slicing direction (vault-native first, connectors last)

1. **Moments from vault data, pull-only.** Compute the illustrative moments from what is already in
   the vault (daily notes, manually-maintained agenda, existing tasks/commitments) — no external
   connectors. Mostly composition of shipped capabilities; proves the context-model →
   relevance-evaluator → surface path end to end.
2. **The attention loop (the new seam).** The trigger evaluator + the scarcity policy + the
   reach-out channel. Ship "it surfaces the right thing when you open the app" before any proactive
   push.
3. **Pattern authoring.** User-declared patterns first; the emergent feedback loop (§3.2) later.
4. **External connectors (deferred, designed-shape-now).** Calendars (work / private / family),
   email (job / private), tasks. Opt-in, behind the local-first privacy posture. **This absorbs
   #1796's Q15 (agenda/calendar source) and Q16 (location source + privacy).**

## 8. Open design questions (only the ones that shape the architecture)

Resolved already (this brief): general engine not a feature list; context model + adaptive
evaluator; user-defined → emergent patterns; adaptive cognition + deterministic gate; governance
tiers per #1881.

Still open — and primarily the human's to anchor, because they are about *the human's attention*:

- **The reach-out channel.** How does the engine proactively reach the human — a "now" surface in
  the companion UI the human glances at, vs. an OS/push notification? This is the proactivity
  substrate.
- **The scarcity rule.** The concrete policy that keeps the engine a prosthesis, not a firehose
  (e.g., a hard cap on proactive surfacings; only strong triggers earn a push; everything else
  stays pull).
- **Connector privacy posture (deferred).** The local-first guarantees for any calendar/email/
  location source — inherits #1796 Q16; do not resolve until slice 4.

## 9. Constraints (non-negotiable)

- **Scarcity is the core feature, not a setting** (`docs/HUMAN-FLOWS.md` §0).
- **Adaptive cognition, deterministic gate** — intelligence in relevance; determinism in the safety
  and scarcity layer.
- **Vault-first** — every moment has a durable Markdown artifact in the vault; the UI is a
  projection of it (`docs/HUMAN-FLOWS.md` §13).
- **Non-authoritative** — surfaced items are proposals/projections with provenance and receipts,
  never silent truth.
- **Local-first** — the "what do I need now" cognition runs locally; external sources are opt-in.
- **Governed by construction** — rides the emergent-features composition pattern; no bypass of
  write guards, provenance, or authority.

## 10. Relationship to existing backlog

- **#1796** (parked context-lane / place-band decision, `agent:needs-human`) is **superseded** by
  this brief: its calendar (Q15) and location + privacy (Q16) questions become slice 4 here. When
  this brief is broken down, retire #1796 into the new parent feature issue.
- **#1881** (proportional governance) supplies the governance tiers in §4.
- This is a forward brief. It is **not** a claim that any of it is shipped; current runtime truth
  stays in `docs/STATUS.md` and the owner docs.
