State: Accepted and implemented capability contract. GOVPROF-01 through GOVPROF-03 were delivered by PRs #5731, #5733, and #5735; parent #4944 accepted the evidence on 2026-09-29. The separate YouTube overlay renderer is delivered under Issue #4117 as a read-only consumer and is not part of this capability.

# Governed Vault Profile

## Capability boundary

This capability supports one vault-local, owner-visible Profile Note: a reviewable preference-memory artifact, not hidden model state, human-authored knowledge, or a YouTube-local profile. The delivered ProfileAgent is the only system agent permitted to write approved profile content. Other agents can submit a provenance-bearing `ProfileUpdateCandidate` through an inspectable handoff, but that handoff is data rather than an instruction, approval, or consumer-context input.

The ProfileAgent authority, confirmation/write path, durable receipt binding, and rebuildable same-scope consumer projection are implemented and accepted within GOVPROF-01 through GOVPROF-03. This capability does not grant external egress or broad filesystem access. The separate YSNV2-10 four-part YouTube overlay renderer is delivered under Issue #4117 and consumes only the same-scope projection.

## Authority and lifecycle

`ProfileUpdateCandidate` -> admissible candidate -> visible unchecked proposal -> owner confirmation -> governed write -> terminal receipt -> consumable approved profile version.

The proposal appears immediately after the Profile Note frontmatter/title and before profile content. It is distinguishable, initially unchecked, and names proposed change, provenance, and uncertainty. A checked item is the owner confirmation signal; creation and writing are separate passes. Policy/admission, WriteGuard, idempotency, and a completed confirmation/write receipt are prerequisites for a consumable version.

Direct owner correction has precedence over agent-derived material. It is never silently overwritten; any reconciliation is visible and receipt-bound.

## Cross-Task Invariants / Interaction Safety

1. **One approved-content writer.** Only ProfileAgent can write approved Profile Note content. Candidates, model output, unchecked proposals, and consumer code have no direct write route.
2. **No approval laundering.** A candidate is data, an unchecked proposal is not approval, and a confirmation without a completed governed write/receipt is not a consumable version.
3. **Version-bound consumption.** Consumers may read only an owner-approved, ProfileAgent-written, same-scope projection whose version is bound to the completed receipt. They must show explicit no-profile behavior when that projection is absent, pending, stale, out of scope, or unreceipted.
4. **Owner precedence.** A direct owner correction remains authoritative across retries and restart. A pending or replayed agent proposal cannot overwrite it.
5. **Partial failures stay visible and retry-safe.** A failed proposal pass creates no approved content. A write failure after confirmation records a truthful non-terminal outcome and preserves the candidate/proposal/confirmation linkage for idempotent recovery; it does not expose a new consumer version. Restart recovers only durable, receipt-linked state and never invents approval from in-memory state.
6. **Local-first and bounded access.** The Profile Note and approved versions remain owner-readable in the vault. This contract grants neither egress nor broad filesystem access; retention, scope, and consumer-read rights are explicit checks in later slices.

## Implementation tasks and execution order

1. [Define Profile Authority And Persistence](DEFINE_PROFILE_AUTHORITY_AND_PERSISTENCE.md) — delivered as GOVPROF-01 / #4945 by PR #5731. Establishes the durable authority records, version/receipt binding, owner correction precedence, and restart/partial-failure posture.
2. [Govern Profile Update Proposals And Confirmed Writes](GOVERN_PROFILE_UPDATE_PROPOSALS_AND_CONFIRMED_WRITES.md) — delivered as GOVPROF-02 / #4946 by PR #5733. Wires candidate admission, visible proposals, confirmation, and the ProfileAgent-only write path.
3. [Project Approved Profile To Same-Scope Consumers](PROJECT_APPROVED_PROFILE_TO_SAME_SCOPE_CONSUMERS.md) — delivered as GOVPROF-03 / #4947 by PR #5735. Adds the rebuildable same-scope projection and explicit no-profile behavior that the #4117 renderer consumes.

## Capability acceptance

- [x] All three slices merged with their task-level `Verify:` targets and posted validation receipts to parent #4944.
- [x] Parent #4944 accepted the combined proof that only approved, receipt-bound, same-scope versions can be consumed and that direct owner corrections survive proposal/write failure and restart.
- [x] Owner-doc promotion review confirmed that the ProfileAgent authority, confirmed writes, receipt-bound versions, and same-scope projection can be described as delivered; the separate #4117 YouTube renderer was delivered later as its own consumer slice.

## Relationship to GitHub Issues

GitHub parent #4944 was accepted and closed after GOVPROF-01 through GOVPROF-03 were delivered and the owner docs were promoted. This directory is the durable capability contract. The separate #4117 renderer consumes the read-only same-scope seam; its YouTube overlay behavior is not part of the delivered GOVPROF capability.

## Source authority

- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: D4 — resolved direction 2026-07-25`
- `docs/YOUTUBE_SOURCE_NOTE_V2/APPLY_GOVERNED_INTEREST_OVERLAY.md :: Contract`
- `docs/PANEL_AGENT.md :: Canonical confirmation semantics`
- `docs/PANEL_AGENT.md :: Option B — Proposal generator + executor split (accepted decision)`
- `docs/AGENT-FLOWS.md :: Handoff artifacts and agent-to-agent continuity`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Preference memory`
