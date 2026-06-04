State: Filed parent feature issue. GitHub Issue #1559 is the authoritative backlog and validation
surface for Context Bundles production runtime integration. This file is the local source/reference
copy for source anchors, implementation task order, and the validation path.

# [Feature] Context Bundles — Production Runtime Integration

Live GitHub parent issue:
[`#1559`](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559).

GitHub is the authoritative backlog and validation surface. Keep validation receipts, child issue
state, and owner-doc promotion decisions on the GitHub issue; keep this local file aligned as the
source-anchor and verification-path reference.

## Context

`docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` defines the context bundle as the inspectable bridge
between retrieval, orientation, resurfacing, companion UI, governed write proposals, provenance, and
write guards. The capability is delivered at the typed-contract / Pydantic layer (closed parent #894
and children), but no production route constructs, emits, consumes, links, or projects bundles
against the real vault. This feature validates the runtime integration of that contract through
bounded child issues without claiming shipped runtime behavior before those issues are delivered.

## Scope

- Expose a read-only production route that returns an inspectable `ContextBundle`.
- Emit bundles from the real retrieval path (`app/retrieval/capability.py::RetrievalResponse`).
- Consume bundles in the production orientation and resurfacing paths.
- Carry bundle linkage through governed write proposals without bypassing WriteGuard.
- Expose bundle provenance and exclusions through a receipt/query projection.
- Promote owner docs only after runtime evidence exists.
- Keep production wiring separate from Knowledge Compilation wiring (`app/knowledge_compilation/`).

## Source Anchors

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to writeback and write guards`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to provenance and receipts`
- `docs/CONTEXT_BUNDLES/README.md :: Owner-Doc Promotion Trigger`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Persistence rules`

## Constraints

- Context Bundles are inspectable runtime support objects, not canonical truth; no hidden authority.
- Must not bypass WriteGuard (`app/write_guard.py`), trust semantics, policy gates, or receipt posture.
- No direct vault mutation in construction or read-side consumption slices.
- No direct DB imports in new code; route through capability/ports layers.
- No new event family unless `docs/EVENTS.md` + event-envelope tests are in the same slice.
- No owner-doc promotion until runtime evidence exists.
- Keep production route wiring separate from Knowledge Compilation wiring.
- Local-first, single-user, quality-over-scale; single-vault scope.

## Acceptance Criteria

See GitHub Issue #1559 for the live acceptance checklist. Each criterion is validated by a child
issue closing with a validation receipt on #1559; owner-doc promotion is recorded only after runtime
evidence (final child #1566).

## Implementation Tasks

1. `docs/CONTEXT_BUNDLES_RUNTIME/EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md` — filed as #1560 (ready).
2. `docs/CONTEXT_BUNDLES_RUNTIME/EMIT_FROM_REAL_RETRIEVAL.md` — filed as #1562; depends on #1560.
3. `docs/CONTEXT_BUNDLES_RUNTIME/CONSUME_IN_ORIENTATION_AND_RESURFACING.md` — filed as #1563; depends on #1562.
4. `docs/CONTEXT_BUNDLES_RUNTIME/CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md` — filed as #1564; depends on #1562.
5. `docs/CONTEXT_BUNDLES_RUNTIME/EXPOSE_RECEIPT_PROJECTION.md` — filed as #1565; depends on #1563, #1564.
6. `docs/CONTEXT_BUNDLES_RUNTIME/PROMOTE_OWNER_DOCS.md` — filed as #1566; depends on #1560, #1562-#1565.

## Verification Path

- Each child task PR resolves the named `Verify:` targets in the task spec it implements.
- Construction route and real-retrieval emission verify before downstream consumption/linkage tasks.
- Parent-level verification checks that every production surface preserves provenance, exclusions,
  and authority flags.

## Validation / Acceptance Path

- Use GitHub Issue #1559 as the parent feature validation hub.
- Keep validation evidence on #1559 until runtime support is accepted.
- Promote owner-doc truth only after receipts show bundles are constructed, emitted, consumed,
  linked, and receipted in the shipped runtime (final child #1566).
