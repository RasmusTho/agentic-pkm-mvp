---
name: Heimdal Client Scaffold And Capture Folder Binding
description: Stand up the second bounded client in the Yggdrasil shell — Heimdal area with its own module boundary, visual capture-folder binding, and the capture session state machine (no audio yet).
task_id: HCAP-01
source_anchor: docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §3 What the shell actually shares vs isolates
parent_capability: Heimdal Capture Client
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Heimdal Client Scaffold And Capture Folder Binding

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

Topology C hosts two bounded clients in one shell; only Mimer exists so far. This task creates the
Heimdal client's structural home (INV-B3-6: own directory, imports shell + `YggdrasilCore` only),
its entry surface, the capture-folder binding, and the session state machine every later slice
drives. Deliberately no audio recording yet — the skeleton must be right first.

## What This Task Does

- Creates `Yggdrasil/Yggdrasil/Heimdal/` with a `HeimdalShellView` reachable from `RootView`
  alongside the Mimer client (compact: a tab or top-level switch; regular: a sidebar section —
  match how MIPAD-01 shaped the adaptive shell if it has merged; otherwise extend the `TabView`
  and leave adaptation to the B2 lane).
- **Capture-folder binding:** a "Choose capture folder" flow reusing the exact
  `UIDocumentPickerViewController(forOpeningContentTypes: [.folder])` + security-scoped-bookmark
  pattern from `VaultManager` (dyslexia-rule: visual pick, never a typed path). Persist the
  bookmark separately from vault bookmarks (e.g. `yggdrasil.captureFolder`); resolve + refresh on
  staleness the way `VaultManager.activate` does. The folder the operator picks is the hub's
  `HEIMDAL_CAPTURE_WATCH_DIR` as seen through iCloud Drive.
- **Capture session state machine** as a plain, UI-independent type (e.g.
  `CaptureSessionModel: ObservableObject`): states `idle → recording ⇄ paused(interruption) →
  finalizing → staged`, plus `deliveryPending/delivered/failed` per staged item. Fully
  unit-testable without AVFoundation (audio engine injected later by HCAP-02).
- Heimdal area shows: binding state (folder bound/unbound), a disabled record button (enabled by
  HCAP-02), and an empty staged-items list (filled by HCAP-02/03).

## Concretely

Fresh simulator run → Heimdal area → "Choose capture folder" → pick a folder in Files →
relaunch → binding survives (bookmark), state machine unit tests pass:
`idle→recording→paused→recording→finalizing→staged` transitions and illegal-transition rejection.

## Why This Matters

Every capture guarantee (INV-B3-1's accountability, JD's truthful queue view) hangs off this state
machine; the folder binding is the transport. Getting the boundary right now (INV-B3-6) is what
keeps the future app-split a repackaging.

## Acceptance Criteria

- [ ] Heimdal client area exists in its own directory importing only shell modules +
  `YggdrasilCore` (no Mimer lens imports). `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/HeimdalBoundaryTests.swift::testHeimdalSourcesImportNoMimerInternals`
  (new; scans `Heimdal/` sources' import/type references for `Mimer` symbols).
- [ ] Capture-folder pick persists a security-scoped bookmark distinct from vault bookmarks and
  survives relaunch, with stale-bookmark refresh. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/CaptureFolderBindingTests.swift::{testBookmarkPersistsAndResolves,testStaleBookmarkRefreshes}`
  (new).
- [ ] The session state machine enforces its transition table and rejects illegal transitions.
  `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/CaptureSessionModelTests.swift::testTransitionTableAndIllegalMoves`
  (new).
- [ ] Shell navigation reaches the Heimdal area on iPhone without regressing existing journeys.
  `Verify:` bifrost `Yggdrasil/YggdrasilUITests/HeimdalShellUITests.swift::testHeimdalAreaReachable`
  (new) + existing UI tests green.

## How to Verify (Pre-Merge)

- bifrost CI green (`xcodebuild build test`, both destinations if MIPAD-01 landed; otherwise
  iPhone), `swiftlint --strict` clean.

## Out of Scope

- Audio recording (HCAP-02), delivery (HCAP-03), device note/consent surface (HCAP-04), Watch
  (HCAP-06).
- Any vault write — the capture folder is not the vault; this slice writes only UserDefaults
  bookmark data.

## Related Docs

- `docs/HEIMDAL_CAPTURE_CLIENT/README.md` (INV-B3-1/-B3-6; transport model)
- `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` §3
- bifrost: `Yggdrasil/Yggdrasil/Vault/VaultManager.swift` (the binding pattern to reuse)

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:ready`), linking hub #3026
and this spec file. TCD hint: Sonnet / medium effort — pattern reuse plus a clean state machine;
no novel decisions.
