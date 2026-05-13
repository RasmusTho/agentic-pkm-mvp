State: Filed parent feature issue. GitHub Issue #894 is the authoritative backlog and validation
surface for Context Bundles. This file remains the local source/reference copy for source anchors,
implementation task order, and validation path.

# [Feature] Context Bundles

Live GitHub parent issue:
[`#894`](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894).

GitHub is the authoritative backlog and validation surface. Keep validation receipts, child issue
state, and owner-doc promotion decisions on the GitHub issue; keep this local file aligned as the
source-anchor and verification-path reference.

## Context

`docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` defines the context bundle as the inspectable bridge
between retrieval, orientation, resurfacing, companion UI, governed write proposals, provenance,
and write guards. The implementation-ready breakdown now lives in `docs/CONTEXT_BUNDLES/`.

This feature issue exists to validate the runtime capability through bounded child issues without
claiming shipped runtime behavior before those issues are delivered.

## Scope

- deliver the context-bundle capability through bounded child issues derived from
  `docs/CONTEXT_BUNDLES/`,
- validate schema, retrieval emission, orientation usage, resurfacing usage, write-proposal linkage,
  and receipt recording in dependency order,
- keep initial implementation single-vault/local-scope until
  `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` exists,
- and keep parent-level validation and acceptance evidence on GitHub Issue #894.

## Source Anchors

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Required fields`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Authority flags`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to writeback and write guards`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to provenance and receipts`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `docs/FINDING_AND_REORIENTING/README.md`

## Constraints

- Do not implement runtime behavior from this parent issue; implement only from bounded child issues.
- Do not claim that context bundles are already emitted or consumed unless `docs/STATUS.md` already
  says so.
- Preserve the contract distinction that a context bundle is not memory, not chat context, and not
  a new source of truth.
- Preserve write-guard and trust-semantics boundaries.
- Keep every task independently mergeable and independently verifiable.
- Keep initial implementation single-vault/local-scope until
  `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` exists.

## Acceptance Criteria

- [ ] Schema slice delivered: a minimal inspectable context bundle schema exists with required
  fields, included/excluded item structure, distinct authority flags, and expiry posture.
  Verify: child issue #895 closes with PR validation resolving
  `tests/context_bundles/test_context_bundle_schema.py` targets.
- [ ] Retrieval emission slice delivered: retrieval can emit a bundle or stable bundle reference
  while preserving ranked candidates, selected context, exclusions, and `may_write=false` by
  default.
  Verify: child issue #896 closes with PR validation resolving
  `tests/retrieval/test_context_bundle_emission.py` targets.
- [ ] Orientation and resurfacing usage slices are delivered without treating bundles as memory or
  write authority.
  Verify: future child issues for `USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md` and
  `USE_CONTEXT_BUNDLE_FOR_RESURFACING.md` close with validation receipts on #894.
- [ ] Write-proposal linkage and receipt slices are delivered without bypassing write guards.
  Verify: future child issues for `CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md` and
  `RECORD_CONTEXT_BUNDLE_RECEIPTS.md` close with validation receipts on #894.
- [ ] Owner-doc promotion decision is recorded only after runtime evidence proves bundles are
  emitted, consumed, and receipted truthfully.
  Verify: final validation comment on #894 links delivered child PRs and either opens an
  owner-doc promotion PR or states why no owner-doc promotion is warranted yet.

## Out of Scope

- Implementing Context Bundles directly from this parent issue.
- Implementing agent memory.
- Promoting retrieved context into memory or durable knowledge.
- Cross-vault, multi-vault, or vault-topology assumptions before
  `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` exists.
- Claiming current runtime support in `docs/STATUS.md` beyond docs/spec preparation.
- Defining companion UI behavior beyond the bundle's implementation contract.

## Suggested Validation

- Review every child issue for the repo issue contract and inline `Verify:` targets before marking
  it `agent:ready`.
- After each child PR merges, add a short validation receipt to #894 with issue number, PR number,
  tests/commands run, and any remaining capability gaps.
- Before owner-doc promotion, confirm `docs/STATUS.md`, `docs/ROADMAP.md`, and relevant owner docs
  do not claim unsupported runtime behavior.

## Source Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `docs/FINDING_AND_REORIENTING/README.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`
- `.codex/skills/feature-breakdown/SKILL.md`

## Implementation Tasks

1. `docs/CONTEXT_BUNDLES/DEFINE_CONTEXT_BUNDLE_SCHEMA.md` — filed as #895.
2. `docs/CONTEXT_BUNDLES/EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md` — filed as #896; depends on #895.
3. `docs/CONTEXT_BUNDLES/USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md`
4. `docs/CONTEXT_BUNDLES/USE_CONTEXT_BUNDLE_FOR_RESURFACING.md`
5. `docs/CONTEXT_BUNDLES/CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md`
6. `docs/CONTEXT_BUNDLES/RECORD_CONTEXT_BUNDLE_RECEIPTS.md`

## Verification Path

- Each child task PR resolves the named `Verify:` targets in the task spec it implements.
- Schema and emission tasks verify structure before downstream usage tasks are treated as complete.
- Parent-level verification checks that every implementation surface preserves provenance,
  exclusions, and authority flags.

## Validation / Acceptance Path

- Use GitHub Issue #894 as the parent feature validation hub.
- Create child implementation issues from the task files in dependency order.
- Keep validation evidence on #894 until runtime support is accepted.
- Promote owner-doc truth only after receipts show bundles are emitted, consumed, and bounded by
  write authority in the shipped runtime.
