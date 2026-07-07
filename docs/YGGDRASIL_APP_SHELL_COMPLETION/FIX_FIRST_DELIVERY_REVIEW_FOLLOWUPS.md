---
name: Fix First Delivery Review Followups
description: Close the four non-blocking follow-ups documented at B1's first delivery — attention-lens audit-trail accuracy, numbered-list parsing, YAML leading-zero round-trip, and lens-view boilerplate.
task_id: YGGSHELL-03
source_anchor: RasmusTho/bifrost#1 :: delivery receipt (2026-07-06, "documented non-blocking follow-ups")
parent_capability: Yggdrasil App Shell Completion
prerequisites: []
depends_on: []
can_parallelize_with: [ALIGN_VAULT_WRITES_TO_COORDINATED_FILE_ACCESS, TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL]
---

# Fix First Delivery Review Followups

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

B1's delivery review (bifrost PR #2; 13 issues found and fixed pre-merge) documented four real but
non-blocking follow-ups in the `bifrost#1` closing receipt. Closing B1 without either fixing or
re-triaging them lets known defects ride into B2's foundation.

## What This Task Does

Fixes the four items named in the `bifrost#1` delivery receipt (2026-07-06T12:36 comment):

1. **Attention lens manual-override audit-trail accuracy gap** —
   `Yggdrasil/Yggdrasil/Mimer/Lenses/AttentionLensView.swift`: the recorded manual-override audit
   trail can misstate what the human actually did. Make the recorded override entry reflect the
   action taken.
2. **Numbered-list markdown parsing edge case** —
   `Packages/YggdrasilCore/Sources/YggdrasilCore/MarkdownDocument.swift`: a numbered-list form is
   mis-parsed by the block parser. Reproduce, fix, and pin with a test.
3. **`Int` round-trip edge in the YAML codec for leading-zero values** —
   `Packages/YggdrasilCore/Sources/YggdrasilCore/YAMLCodec.swift`/`YAMLValue.swift`: a scalar like
   `007` can round-trip with changed meaning (parsed as `Int`, re-serialized without the leading
   zeros). Preserve the original scalar form for values whose re-serialization would not be
   byte-identical.
4. **Duplicated boilerplate across the five lens views** —
   `Yggdrasil/Yggdrasil/Mimer/Lenses/*.swift`: extract the shared load/error/save scaffolding into a
   common component so the five lenses stop drifting apart.

If any item turns out to already be fixed (e.g. absorbed by an intervening bifrost PR) or not
reproducible, the issue records that finding explicitly per item instead of silently skipping it.

## Concretely

```bash
# In RasmusTho/bifrost:
xcodebuild test -scheme Yggdrasil   # includes the new pinning tests below
swiftlint --strict                  # still clean after the lens refactor
```

## Why This Matters

Items 1–3 silently corrupt or misreport durable vault data: an inaccurate audit trail undermines the
override receipts the human steers by; a parser edge mangles rendered notes; a YAML round-trip
change rewrites a field the client never meant to touch — the exact "never clobber fields other
writers own" promise the typed wrappers exist for. Item 4 is the cheap moment to stop five copies of
the same scaffolding from diverging before B2 adds more lenses.

## Acceptance Criteria

- [ ] The attention lens records a manual-override audit entry that matches the action actually
  taken. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/AttentionLensAuditTests.swift::testManualOverrideAuditMatchesAction` (new).
- [ ] The numbered-list edge case parses correctly and is pinned. `Verify:` bifrost
  `Packages/YggdrasilCore/Tests/YggdrasilCoreTests/MarkdownDocumentTests.swift::testNumberedListEdgeCase`
  (new).
- [ ] A leading-zero scalar round-trips byte-identically through the YAML codec. `Verify:` bifrost
  `Packages/YggdrasilCore/Tests/YggdrasilCoreTests/YAMLCodecTests.swift::testLeadingZeroScalarRoundTripsVerbatim`
  (new).
- [ ] The five lens views share one load/error/save scaffold; no behavioral change. `Verify:`
  bifrost CI green on existing lens behavior (`xcodebuild test`) + `swiftlint --strict` clean; the
  PR diff shows the extraction.

## How to Verify (Pre-Merge)

- bifrost CI (`macos-14`): `xcodebuild build test` green including the three new pinning tests;
  `swiftlint --strict` clean.
- Each of the four items has either a fix commit + test or an explicit "already fixed by
  <ref>/not reproducible because <evidence>" note in the PR body.

## Out of Scope

- New lens capability or UI redesign — this is convergence, not expansion.
- The write-path/coordination work (YGGSHELL-01) and provenance work (YGGSHELL-02).

## Related Docs

- `RasmusTho/bifrost#1` closing delivery receipt and `RasmusTho/bifrost#2` review round (public
  GitHub record naming the four items)
- bifrost: `Yggdrasil/Yggdrasil/Mimer/Lenses/`, `Packages/YggdrasilCore/Sources/YggdrasilCore/`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:ready`), linking hub #3023.
TCD hint: Sonnet / medium effort — four small, locally-verifiable fixes with named tests; escalate
only if the YAML scalar-form preservation forces a codec redesign.
