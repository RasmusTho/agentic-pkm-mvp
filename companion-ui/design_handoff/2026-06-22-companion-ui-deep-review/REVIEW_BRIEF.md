# Review Brief — Companion UI Deep Review

## Addressed to: Claude Design

Read `SYSTEM_CONTEXT.md`, then `SURFACE_INVENTORY.md`, then `WORKFLOWS_TO_EVALUATE.md`, then
`OBSERVED_ISSUES.md` before producing output.

## The ask, in one sentence

Evaluate whether the Companion UI's **workflows work intuitively** and whether its **functions
have been implemented well** — and return a prioritised design specification that the
implementer can act on through the governed handoff chain.

This is explicitly **not** a "does each screen look nice" pass. Aesthetics matter only where
they help or hurt the two axes below.

## The two axes (grade every journey on both)

**Axis A — Intuitiveness of the workflow.** Walking the journey as the single expert-but-
intermittent user: do I always know where I am, what just happened, and what to do next? Is
there one obvious path, or do I stop to decode? Does the UI track state *for* me, or make me
track it?

**Axis B — Quality of the implementation (as built).** Is the function actually finished and
correct as a piece of UI? Are all states designed (empty / loading / degraded / blocked /
stale)? Is the visual hierarchy right? Is the copy precise? Are affordances reachable and
consistent? Is the right thing emphasised, and the secondary thing visibly secondary?

A journey can pass one axis and fail the other (e.g. a sound concept, half-built; or a polished
surface that confuses). Say which.

### Verdict scale (use per axis, per journey)

- **Works** — ship as-is; note any optional polish.
- **Friction** — works but costs the user effort/clarity; describe the fix.
- **Broken** — fails its purpose (or an affordance is unreachable / a needed state is missing);
  describe what it should be.

## Scope

**In scope:** the journeys J1–J7 in `WORKFLOWS_TO_EVALUATE.md`; the cross-cutting passes;
hierarchy, layout, interaction grammar, state completeness, copy, reachability, responsive
integrity, and the calm/anti-dashboard posture.

**Out of scope (don't try to fix these — they have their own tracks):** Markdown/Mermaid
rendering internals, wikilink resolution, the body-edit save pipeline, runtime/data correctness,
and anything requiring repo or live-app access. Treat `OBSERVED_ISSUES.md` as known — go deeper,
don't re-list.

**Authority boundary:** produce **design specification, not code and not PRs**. Do not propose
moving runtime-declared classification (entry state, authority, receipts, posture) into the
client — that boundary is load-bearing and test-enforced (see `SYSTEM_CONTEXT.md` §4). Do not
override any owner doc in `docs/**`.

## Honour the methodology limits

The captures are static, server-rendered, no live runtime (see README §Methodology). Judge
layout, hierarchy, state composition, and copy freely. For anything that depends on motion,
focus, live data, or round-trips (re-entry animation feel, memory-review populated flow,
body-edit apply), **state the dependency and flag it for live UAT** instead of asserting from a
still.

## Deliverable format (what to return)

A single design-review document with these sections:

1. **Executive read (½ page).** The 3–5 things that most help or hurt the user's core loop
   (*open → orient → read → act with clarity → leave a clean thread*). Lead with the answer.

2. **Per-journey verdicts (J1–J7).** For each: the two-axis verdict (A: _ / B: _), 2–4 sentences
   of evidence citing specific screenshots, and **the single highest-leverage change**.

3. **Cross-cutting findings.** Hierarchy/calm, state completeness, reachability, responsive
   integrity, overlay-grammar consistency — each with a verdict and the fix.

4. **Prioritised recommendations**, grouped by type and ordered by leverage:
   - Quick visual fix
   - Structural layout change
   - Cognitive-load reduction
   - Workflow / interaction redesign
   - Strategic / future
   - **Do not change** (call out what's working and must be preserved — especially anything that
     protects the anti-dashboard posture or the server-authority boundary)

5. **Acceptance criteria / UAT checklist.** For each non-trivial recommendation, a short,
   testable statement of "done" phrased as design spec (so the implementer can validate it).
   Include which items need **live UAT** vs static verification.

Keep it concrete and prioritised. The owner optimises for the fewest, highest-leverage decisions
— a ranked list of real changes beats an exhaustive catalogue.
