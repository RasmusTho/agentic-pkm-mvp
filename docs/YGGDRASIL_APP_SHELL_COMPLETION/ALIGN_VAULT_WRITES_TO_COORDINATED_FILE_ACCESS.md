---
name: Align Vault Writes To Coordinated File Access
description: Adopt ADR-0055 item 5 in the bifrost client — NSFileCoordinator/UIDocument coordinated vault I/O plus client-side stale-verify — replacing plain FileManager writes.
task_id: YGGSHELL-01
source_anchor: docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: Decision item 5
parent_capability: Yggdrasil App Shell Completion
prerequisites: []
depends_on: []
can_parallelize_with: [FIX_FIRST_DELIVERY_REVIEW_FOLLOWUPS]
---

# Align Vault Writes To Coordinated File Access

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

ADR-0055 item 5 (Accepted 2026-07-07) rules that Bifrost clients write vault files using Apple's
coordinated-access APIs (`NSFileCoordinator`/`UIDocument`), not plain `FileManager` I/O, so the
client cooperates with iCloud's own coordination instead of racing it. The shipped B1 client uses
plain `String.write(atomically:)` and explicitly documents that it adds no coordination — compliant
under ADR-0053's interim ruling at delivery time, now behind the decided model.

## What This Task Does

- Routes every vault read and write in `Yggdrasil/Yggdrasil/Vault/VaultFileStore.swift` (including
  `readMany` and `readModifyWrite`) through `NSFileCoordinator` coordinated reads/writes (or
  `UIDocument` where a document lifecycle fits better — implementer's choice, ADR-0055 permits
  either), inside the existing security-scoped access sessions.
- Adds the client-side stale-verify discipline from `docs/contracts/MIMER_CLIENT_CONTRACT.md` §6 W2
  to `readModifyWrite`: record a content hash at read; immediately before writing, re-check; if the
  file changed since the read, re-read and re-apply the mutation on the fresh content instead of
  writing the stale version. Bounded retries; surface persistent contention as an error, never as a
  silent overwrite.
- Keeps atomic whole-file replacement semantics (temp + rename or the coordinated-write equivalent)
  so no reader ever observes a half-written note (contract §6 W4).
- Preserves `YggdrasilCore`'s platform-agnosticism: coordination lives in the app-side
  `VaultFileStore`, not in the Swift package.

## Concretely

```swift
// Shape, not prescription:
func readModifyWrite(_ path: String, _ mutate: (String) throws -> String) throws {
    try coordinated(writingTo: url(path)) { coordinatedURL in
        let before = try String(contentsOf: coordinatedURL, encoding: .utf8)
        let after = try mutate(before)          // read-merge-write on fresh content
        try atomicReplace(coordinatedURL, with: after)
    }
}
```

CI proves it: `xcodebuild test` runs `VaultFileStoreTests` covering the coordinated path and the
stale re-apply behavior (two interleaved mutations to one file both survive).

## Why This Matters

Until the hub-side ADR-0055 enactment (#3132) ships stale-detection at the substrate, the client's
own discipline is the only thing shrinking the lost-update window on `_heimdal/**` control notes and
any human note the app edits — the exact "rewritten note class" ADR-0055 protects. A phone writing
an interests note while the Mac runtime folds a decision into the same file is the live scenario.

## Acceptance Criteria

- [ ] All vault file reads/writes in `VaultFileStore` go through coordinated file access
  (`NSFileCoordinator` or `UIDocument`); no plain uncoordinated `FileManager`/`String.write` vault
  I/O remains on the app's vault path. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/VaultFileStoreTests.swift::testWritesUseCoordinatedAccess` (new; asserts
  the coordination seam is exercised from the store's public API, not a helper in isolation).
- [ ] `readModifyWrite` re-checks content freshness before writing and re-applies the mutation on
  changed content; a stale write is never emitted. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/VaultFileStoreTests.swift::testStaleWriteIsReappliedOnFreshContent`
  (new; mutates the file between read and write and asserts the final content contains both changes).
- [ ] Whole-file writes remain atomic (no partial-content observation window). `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/VaultFileStoreTests.swift::testWholeFileWriteIsAtomicReplace` (new or
  extended existing).
- [ ] `YggdrasilCore` still builds and tests with `swift build`/`swift test` alone (no
  UIKit/coordination dependency introduced into the package). `Verify:` bifrost CI package step
  green on the PR head SHA.

## How to Verify (Pre-Merge)

- bifrost CI (`.github/workflows/ci.yml`, `macos-14`): `xcodebuild build test` green including the
  three named tests; `swiftlint --strict` clean.
- The authoring environment may lack `Xcode.app` (this repo's known gap) — CI is the accepted gate;
  state any local-toolchain limitation in the PR body per bifrost's PR template.

## Out of Scope

- Conflict-artifact staging, note-class tables, iCloud conflicted-copy quarantine — hub-side
  ADR-0055 enactment (#3132), not client work.
- Writer-provenance tagging and the README consistency-narrative rewrite
  (TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL).
- Routing writes through the hub HTTP API — ADR-0055 item 5 explicitly keeps the client
  offline-first on the filesystem transport.

## Related Docs

- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (items 1, 5)
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5–§6 (Bifrost family; W2/W4)
- `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` §3 (what the shell shares vs isolates)
- bifrost: `Yggdrasil/Yggdrasil/Vault/VaultFileStore.swift`, `Yggdrasil/README.md :: Vault write consistency`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:ready`), linking hub #3023 as
the tracking parent and this spec file as its contract. TCD hint: Sonnet / high effort —
concurrency-adjacent single-seam change with real design choice (coordinator vs UIDocument);
escalate to Opus only if coordination semantics fight the security-scoped bookmark flow.
