State: Superseded — redundant snapshot. The live companion note + Note Context plan is `docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md`.
# Plan: Companion Note + Note Context (superseded snapshot)

This file is a compatibility pointer. It is retained only to preserve historical lineage.

The canonical, current-truth plan for the companion note + Note Context track lives at
`docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md`. Use that document.

## Why this was demoted

This was a frozen 2026-03-27 snapshot that read as flatly "Delivered — Parts 1–8 done". It
contradicted the sibling plan, which carries the re-baselined current truth for the *same* shipped
track — including later v5.7 / #971 work (single write path, creation-eligibility policy, orphan
detection) and remaining doc-sync items (#229) that this snapshot omitted. Per `docs/STATUS.md`
(v5.6 closure receipt "Companion note + Note Context doc-sync correction: Issue #229 / PR #237"),
the re-baselined plan reflects current truth, so this redundant snapshot was demoted to a stub. No
unique still-live content was lost: the delivered Part→exit-criteria detail is subsumed by the
"Shipped" section of the live plan.

The companion-note **contract** (`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`) is unchanged and
remains the normative field/ownership authority.
