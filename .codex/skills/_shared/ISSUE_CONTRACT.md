State: Shared skill contract. Canonical GitHub Issue contract shape.

# Issue Contract

Single source for the canonical Issue body shape. Skills reference this file instead of carrying
their own copies; skill-specific deviations stay in the skill that owns them.

## Title shape

`<type>: <short bounded outcome>`

## Canonical sections

Issue bodies must contain exactly these sections:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## SBS Impact`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`
- `## Applies learning (optional)` — leave blank unless the slice was shaped by a prior
  retrospective outcome; when filled, link the retro entry, BuilderOps record, or PR that informed
  the slice shape. Intake lanes that always carry provenance (for example `learning-to-issue`) may
  make this section required for their issues.

Parent feature issues additionally carry `## Implementation Tasks`, `## Verification Path`, and
`## Validation / Acceptance Path` (see `feature-breakdown`).

## Issue self-sufficiency rule

An Issue must be self-sufficient on info and context. Every agent or human who picks it up must be
able to understand and execute the bounded task from the Issue body alone — without requiring access
to machine-local ephemeral state (SQLite stores, local caches, worktree state, in-memory runtime
data, or any artefact that is not reproducible from the checked-in repo plus public GitHub data).

**Prohibited in Issue bodies:**

- Instructions that depend on a specific local file path, local DB, or local runtime state that is
  not reproducible across devices (e.g. "reconcile records in my local sqlite", "check the
  worktree-local store").
- Context that references ephemeral operational state as if it were shared fact (e.g. "the June 18
  records in the local BuilderOps store").
- Scope or acceptance criteria that can only be verified on the machine that authored the Issue.

**Correct pattern:** promote the relevant material to a durable authority surface (GitHub Issue
body, linked PR, owner doc) before authoring the Issue that depends on it. If the material cannot be
promoted, the Issue should not depend on it.

## Verify: marker rule

Every Acceptance Criterion declares its verification inline with a `Verify:` marker:

- Behavioral AC → concrete test pointer: `Verify: \`tests/<path>::<test_name>\``. The test may be
  new (to be written by the builder); the name is the spec-level commitment.
- Enforcement AC (a behavioral AC asserting a guard, gate, or invariant holds on the live path)
  → the `Verify:` test must exercise the **production call site**, not the guard in isolation:
  `Verify: \`tests/<path>::<test_name>\`` and the test asserts `<guard>` is invoked from
  `<runtime entrypoint>`. A unit test of the guard function alone does not discharge an
  enforcement AC.
- Non-behavioral AC → concrete observable target: doc writeback path plus anchor
  (`Verify: doc writeback at \`docs/<path> :: <anchor>\``), roadmap diff, or runtime receipt.
- An AC without a resolvable `Verify:` target is not executable; the Issue must not be
  `agent:ready` until the AC is refined or split.
- `Suggested Validation` lists the commands and procedures that execute the declared `Verify:`
  targets — coupled to the ACs, not a duplicate of them.

The canonical long-form rule lives in `docs/development/DEV_WORKFLOW.md` ("Acceptance
verifiability"); this file is the skill-facing summary.

## Body template

```
## Context
<1-2 sentences of background; link the governing doc, record, or PR>

## Scope
<What changes. Name files and artifacts.>

## Source Anchors
- `<path> :: <section or stable anchor ID>`

## SBS Impact
- Primary subsystem: <Product SBS subsystem, or Builder System / CES boundary>
- Secondary subsystem(s): <subsystems or none>
- Write class: <authority-bearing / mechanical / derived / governance/docs/process / none>
- Authority impact: <effect or none>
- Persistence impact: <durable/rebuildable/none>
- Derived/rebuildable impact: <effect or none>
- Human knowledge impact: <effect or none>
- Memory impact: <effect or none>
- Retrieval/context impact: <effect or none>
- Sync/deployment impact: <effect or none>
- External boundary impact: <effect or none>
- New or changed contract: <contract or none>
- Owner-doc impact: <none / will-update-in-PR / follow-up-issue>
- Transition debt impact: <reduces / adds bounded debt / no effect>
- Fitness rule impact: <strengthens / weakens / follow-up / no effect>

## Constraints
- <what must not change>

## Acceptance Criteria
- [ ] <bounded outcome>
  - Verify: `<test pointer or doc writeback target>`

## Out of Scope
- <what this issue deliberately excludes>

## Suggested Validation
- <commands that execute the Verify: targets>

## Source Docs
- `<path>`

## Applies learning (optional)
<provenance link, or leave blank>
```
