State: Active capability specification directory. Docs-only breakdown is present; implementation and owner-doc promotion remain future work.

# Scope, Sphere, and Situated Identity

## Capability Boundary

This specification directory defines the v6.0 enabling capability that separates:
- operational scope,
- sphere membership,
- situated identity,

as distinct, non-collapsed runtime properties.

The purpose is to prevent context semantics from collapsing back into a single `domain` concept while preserving current shipped v5.x behavior until bounded implementation tasks land.

## Execution Order

1. `DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md`
2. `THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`
3. `EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md`
4. `VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`

## Acceptance Path

This capability is accepted when:
- all task-level acceptance criteria in this directory are merged with passing verification receipts,
- parent feature validation evidence confirms scope/sphere/identity remain distinct across runtime surfaces,
- downstream priority consumers can bind to explicit context dimensions without reintroducing single-domain collapse.

## Verification Path

- Task-level verification runs on each task issue/PR using each task file's `How to Verify (Pre-Merge)` section.
- Parent validation evidence is collected on the parent feature issue before owner-doc promotion.

## Validation / Acceptance Path

- Keep parent feature issue open as the validation hub while task issues merge.
- After all task issues merge, run cross-surface acceptance checks from `VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`.
- Promote owner-doc claims only after validation receipts show the capability is supported truthfully.

## Dependency Notes (Priority 3-5)

This capability gates later priorities in `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`:
- Priority 3 (receipts + SUGGEST/APPLY gating) depends on context dimensions being explicit so receipts can report correct context provenance.
- Priority 4 (retrieval capability extraction) depends on distinct scope/sphere/identity inputs rather than one overloaded context field.
- Priority 5 (commitment runtime minimum) depends on stable context dimensions so commitment semantics do not inherit ambiguous domain-like context.

## Related Docs

- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `.codex/skills/feature-breakdown/SKILL.md`

## Related GitHub Issues

- Parent feature issue: `PARENT_FEATURE_ISSUE.md` in this directory; open as GitHub issue #645.
- Slice issues created from task files: #651 (SSI-01, delivered PR #660), #652 (SSI-02), #653 (SSI-03), #654 (SSI-04).
