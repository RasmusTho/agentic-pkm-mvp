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

## Child to parent reference

A child slice governed by a parent feature issue declares that edge with exactly one line, on its
own line in the body (conventionally at the end of `## Context`):

```
Parent: #<N>
```

Plain text, one parent, no bold or prose around the number — the line is machine-parsed
(INV-DG-3). Orphan slices (no governing parent) carry no `Parent:` declaration at all.
`scripts/validate_issue_readiness.py` fails readiness (`malformed_parent_reference`) when a
declared reference — a `Parent:`-prefixed line carrying a `#<digits>` token — is not exactly this
shape or appears more than once. Descriptive parent prose without an issue-number token is not a
declaration. The parent→child direction is owned by the epic delivery ledger
(`verification-and-closure :: Parent Issue Closure :: Structured child ledger (epic delivery
ledger v1)`), not by this line.

## Verify: marker rule

Every Acceptance Criterion declares its verification inline with a `Verify:` marker:

- Behavioral AC → concrete test pointer: `Verify: \`tests/<path>::<test_name>\``. The test may be
  new (to be written by the builder); the name is the spec-level commitment.
- Enforcement AC (a behavioral AC asserting a guard, gate, or invariant holds on the live path)
  → the `Verify:` test must exercise the **production call site**, not the guard in isolation:
  `Verify: \`tests/<path>::<test_name>\`` and the test asserts `<guard>` is invoked from
  `<runtime entrypoint>`. A unit test of the guard function alone does not discharge an
  enforcement AC.
- Non-behavioral AC → concrete observable target, one of: doc writeback path plus anchor
  (`Verify: doc writeback at \`docs/<path> :: <anchor>\``), roadmap diff
  (`Verify: roadmap diff: \`docs/<path> :: <anchor>\``), runtime receipt
  (`Verify: runtime receipt: <identity>.v<N>`), a bare repo anchor
  (`Verify: \`<path> :: <anchor>\``), a diff-of-file target
  (`Verify: diff of \`<repo path>\` <what the diff adds>`), or a marker-presence target
  (`Verify: \`<literal>\` present in \`<repo path>\``). A durable repository path or anchor is
  what makes the target concrete; prose without one is not a target.
- A backticked canonical target may carry a trailing prose annotation on the same marker line
  (an enforcement note, or "removed or rewritten as delivered."); the target stays the
  backticked segment.
- The `Verify:` marker opens its own (optionally bulleted) line per the body template. An
  inline tail on the AC line (`- [ ] text. Verify: <target>`) also declares a marker when its
  target is grammar-resolvable; any other mid-line mention inside AC prose is not a marker.
- One AC may declare **several targets, one `Verify:` line each**. Never join targets on a
  single marker line — no ` + `, `and`, or comma between two targets. A joined line is one
  target to the grammar,
  its backticks no longer pair, and validation reports a missing file for a path that exists.
  The split lines are sub-bullets of the same acceptance item and do not change the AC count:

  ```
  - [ ] Both current-state docs describe the binding as shipped.
    - Verify: doc writeback at `docs/DB_SCHEMA.md :: DB Schema (Current Reality)`
    - Verify: doc writeback at `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deployment and Environments`
  ```
- The machine grammar for these forms is
  `app/builderops/issue_contract_validation.py :: is_resolvable_verify_target`;
  `tests/governance/test_verify_target_contract_parity.py` keeps this section and the grammar
  in parity.
- An AC without a resolvable `Verify:` target is not executable; the Issue must not be
  `agent:ready` until the AC is refined or split.
- Ready-label validation permits a behavioral `tests/...py::test_name` target to name a new test
  file that the implementing builder will add. Every other file-based `Verify:` target must resolve
  to an existing repository file.
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
- Persistence impact: <durable/rebuildable/none>
- Derived/rebuildable impact: <effect or none>
- New or changed contract: <contract or none>
- Owner-doc impact: <none / will-update-in-PR / follow-up-issue>
- Transition debt impact: <reduces / adds bounded debt / no effect>
- Boundary risk: <the one thing that must not cross a boundary because of this change, or none>

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
