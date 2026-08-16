State: Filed target-state capability specification. It defines no shipped ProfileAgent, Profile Note, approved profile, proposal handling, confirmation path, persistence, receipt, or consumer projection. Parent validation hub: #4944 (`agent:blocked`).

# Governed Vault Profile

## Capability boundary

This capability owns one vault-local, owner-visible Profile Note: a reviewable preference-memory artifact, not hidden model state, human-authored knowledge, or a YouTube-local profile. The future ProfileAgent is the only system agent permitted to write its approved profile content. Every other agent can submit a provenance-bearing `ProfileUpdateCandidate` through an inspectable handoff, but that handoff is data rather than an instruction, approval, or consumer-context input.

The specification is a Product/Runtime target-state contract. It makes no runtime delivery claim and does not authorize vault access, egress, profile creation, or consumer behavior today.

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

1. [Define Profile Authority And Persistence](DEFINE_PROFILE_AUTHORITY_AND_PERSISTENCE.md) — GOVPROF-01, issue #4945. Establishes the durable contract, state records, version/receipt binding, owner correction precedence, and restart/partial-failure posture.
2. [Govern Profile Update Proposals And Confirmed Writes](GOVERN_PROFILE_UPDATE_PROPOSALS_AND_CONFIRMED_WRITES.md) — GOVPROF-02, issue #4946. Depends on GOVPROF-01; wires candidate admission, visible proposal, confirmation and the ProfileAgent-only write path.
3. [Project Approved Profile To Same-Scope Consumers](PROJECT_APPROVED_PROFILE_TO_SAME_SCOPE_CONSUMERS.md) — GOVPROF-03, issue #4947. Depends on GOVPROF-02; adds the rebuildable same-scope projection and explicit no-profile behavior, including the eventual #4117 consumer admission.

## Capability acceptance

- [ ] All three slices have merged with their task-level `Verify:` targets and each has posted a validation receipt to parent #4944.
- [ ] The parent validation hub records an end-to-end proof that only approved, receipt-bound, same-scope versions can be consumed and that direct owner corrections survive proposal/write failure and restart.
- [ ] An owner-doc promotion review determines whether current-state documentation can truthfully claim any shipped ProfileAgent behavior; until then this specification remains target-state only.

## Relationship to GitHub Issues

GitHub parent #4944 is the authoritative validation hub and remains `agent:blocked` while children are outstanding. This directory is the durable target-state specification; task frontmatter is the machine join to filed child issues. No child may be treated as a runtime delivery claim before its own governed verification and parent acceptance.

## Source authority

- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: D4 — resolved direction 2026-07-25`
- `docs/YOUTUBE_SOURCE_NOTE_V2/APPLY_GOVERNED_INTEREST_OVERLAY.md :: Contract`
- `docs/PANEL_AGENT.md :: Canonical confirmation semantics`
- `docs/PANEL_AGENT.md :: Option B — Proposal generator + executor split (accepted decision)`
- `docs/AGENT-FLOWS.md :: Handoff artifacts and agent-to-agent continuity`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Preference memory`
