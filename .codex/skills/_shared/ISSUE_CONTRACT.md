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

## Verify: marker rule

Every Acceptance Criterion declares its verification inline with a `Verify:` marker:

- Behavioral AC → concrete test pointer: `Verify: \`tests/<path>::<test_name>\``. The test may be
  new (to be written by the builder); the name is the spec-level commitment.
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
