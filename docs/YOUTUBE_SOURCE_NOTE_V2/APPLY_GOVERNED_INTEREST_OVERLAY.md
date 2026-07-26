---
name: Apply governed interest overlay
description: Produce read-only, evidence-separated relevance connections from an owner-approved context allowlist.
task_id: YSNV2-10
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Owner decision record (D4)
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-05, VAULT_WIDE_RELEVANCE_PROFILE]
depends_on: [PRODUCE_EVIDENCE_ANCHORED_SYNTHESIS_AND_CLAIMS.md]
can_parallelize_with: []
---

# Apply Governed Interest Overlay

## Purpose

Make relevance helpful and falsifiable without turning similarity, prior behavior, or agent memory into ungoverned owner preference.

## What This Task Does

After the future vault-wide relevance-profile contract is delivered, reads only its authorized same-scope projection after ProfileAgent has completed a valid Panel checkbox confirmation, governed profile write, and receipt. It emits four-part proposal connections: source evidence, system inference, owner link/match signal, and suggested use. This task never creates, infers, proposes, or mutates the profile.

## Concretely

The overlay is read-only and excludes suppressed/tombstoned, secret, unapproved or unrelated agent-memory, and ungranted cross-scope context. A behavior-derived profile is admissible only through its future vault-wide owner contract; it cannot be reconstructed from YouTube behavior. ProfileUpdateCandidate A2A handoffs and pending ProfileAgent suggestions, whether unchecked or checked but not yet receipted, are not profile state and are inadmissible. The authorized, approved ProfileAgent projection is the sole exception to the agent-memory exclusion. If no governed profile is present, the note renders one explicit no-profile line and stops.

## Why This Matters

Relevance claims are easy to make plausible and hard to audit. A single vault-wide profile avoids a hidden YouTube-specific model of the owner and keeps the profile governable at one boundary.

## Acceptance Criteria

- [ ] Overlay consumes only the authorized same-scope vault-wide profile projection written by ProfileAgent with a completed confirmation receipt, and rejects ProfileUpdateCandidate handoffs, pending suggestions, local reconstruction, secret, suppressed, unapproved or unrelated agent-memory, and ungranted cross-scope material.
  Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_consumes_only_authorized_vault_wide_profile_projection`.
- [ ] Every connection preserves separate source evidence/anchor, system inference, owner link/match signal, and suggested use; incomplete connections are dropped.
  Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_connection_requires_anchor_and_owner_link_with_separated_fields`.
- [ ] Cold start is a single explicit no-profile line and never constructs a profile from YouTube behavior or prior notes.
  Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_cold_start_does_not_construct_local_behavior_profile`.
- [ ] Overlay system inference and suggested-use prose follow D6 while `source_says` and quotations retain original source language.
  Verify: `tests/knowledge_acquisition/test_interest_overlay.py::test_overlay_system_inference_and_suggested_use_follow_source_language_policy`.

## How to Verify (Pre-Merge)

- Run the four named focused tests with allowed, denied, cross-scope, no-context, and language-policy fixtures.

## Out of Scope

Creating, proposing, or mutating the vault-wide profile; the ProfileAgent; ProfileUpdateCandidate A2A handoffs; its high-placement AI panel; answering standing questions; or automatic follow-up actions.

## Related Docs

- `docs/architecture/cross-scope-flow.md`
- `docs/PANEL_AGENT.md :: Canonical confirmation semantics`
- `docs/AGENT-FLOWS.md :: Handoff artifacts and agent-to-agent continuity`
- Future vault-wide relevance-profile owner contract (not yet authored)
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Authority stays human-first`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:med`, `agent:blocked` pending YSNV2-05 and the future vault-wide relevance-profile contract; D4 direction is recorded. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; behavior-profile authority and cross-scope policy have high hidden-defect risk.
