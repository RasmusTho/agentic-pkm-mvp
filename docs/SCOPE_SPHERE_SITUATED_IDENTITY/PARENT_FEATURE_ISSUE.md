State: Parent feature issue draft. Docs-only capability breakdown exists; GitHub feature issue creation and implementation remain future work.

## Context

Priority 2b in `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` requires separating scope, sphere, and situated identity as distinct properties. The capability currently has no specification directory, so implementation cannot be safely decomposed into bounded, independently verifiable tasks.

This parent issue draft defines the capability-level contract and acceptance path for the new `docs/SCOPE_SPHERE_SITUATED_IDENTITY/` specification.

## Scope

- establish one capability specification directory for scope/sphere/situated-identity separation,
- define bounded implementation tasks with explicit acceptance and verification markers,
- define parent-level verification and validation/acceptance path,
- keep this slice docs-only (no runtime/schema changes).

## Source Anchors

- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` :: Priority 2b — Scope, sphere, and situated identity as distinct properties (v6.0 enabling)
- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` :: Relation To Existing Capability Specifications
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `.codex/skills/feature-breakdown/SKILL.md`

## Constraints

- docs-only for this feature-breakdown slice,
- task specs must satisfy feature-breakdown frontmatter and section contracts,
- task specs must be independently mergeable/verifiable,
- no duplication of concept-contract semantics where references are sufficient.

## Acceptance Criteria

- [ ] Specification directory exists with capability README, execution order, and acceptance path.  
  Verify: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/README.md`.
- [ ] Bounded task files exist with required frontmatter and required sections.  
  Verify: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/*.md` task files.
- [ ] Parent issue draft exists with full feature-issue section contract and linked implementation tasks.  
  Verify: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/PARENT_FEATURE_ISSUE.md`.
- [ ] Dependency notes identify gating impact on Priorities 3–5.  
  Verify: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/README.md` dependency notes section.

## Out of Scope

- runtime code, migrations, schema updates,
- creation of child implementation issues,
- owner-doc promotion claiming capability support as shipped.

## Suggested Validation

- `rg -n "^---$|^task_id:|^source_anchor:|^parent_capability:" docs/SCOPE_SPHERE_SITUATED_IDENTITY/*.md`
- `rg -n "^## (Purpose|What This Task Does|Concretely|Why This Matters|Acceptance Criteria|How to Verify \(Pre-Merge\)|Out of Scope|Related Docs|Related GitHub Issues)" docs/SCOPE_SPHERE_SITUATED_IDENTITY/*.md`
- `rg -n "^## (Context|Scope|Source Anchors|Constraints|Acceptance Criteria|Out of Scope|Suggested Validation|Source Docs|Implementation Tasks|Verification Path|Validation / Acceptance Path)" docs/SCOPE_SPHERE_SITUATED_IDENTITY/PARENT_FEATURE_ISSUE.md`

## Source Docs

- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `.codex/skills/feature-breakdown/SKILL.md`

## Implementation Tasks

- `docs/SCOPE_SPHERE_SITUATED_IDENTITY/DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md`
- `docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`
- `docs/SCOPE_SPHERE_SITUATED_IDENTITY/EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md`
- `docs/SCOPE_SPHERE_SITUATED_IDENTITY/VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`

## Verification Path

- Task-level verification follows each task's `How to Verify (Pre-Merge)` section.
- Verification evidence is recorded on child task PRs before merge.

## Validation / Acceptance Path

- Parent issue remains open while task slices land.
- Cross-surface validation scenarios are executed per `VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`.
- Owner-doc promotion occurs only after parent acceptance criteria and validation receipts are complete.
