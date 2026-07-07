---
name: Adaptive Three-Column Shell On iPad
description: Regular-width (iPad) presents the Mimer client as a NavigationSplitView three-column canvas; compact width (iPhone) keeps the shipped TabView unchanged.
task_id: MIPAD-01
source_anchor: docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §2 Platform footprint
parent_capability: Mimer iPad Thinking Canvas
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Adaptive Three-Column Shell On iPad

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

The design-of-record makes iPadOS the primary Mimer canvas: "multi-column layout: source/list ·
item · inspector — the review feed and its context at once." Today `MimerShellView` is a `TabView`
that renders scaled-up on iPad. This task builds the adaptive skeleton every other B2 slice hangs
on. It is deliberately layout-only: no new data flows, no writes.

## What This Task Does

- In `Yggdrasil/Yggdrasil/Mimer/MimerShellView.swift` (or a new sibling `MimerCanvasView.swift`),
  branch on `@Environment(\.horizontalSizeClass)`: compact keeps the existing `TabView` exactly as
  shipped; regular presents a `NavigationSplitView` with sidebar (lens/source selection), content
  (the selected lens's list), and detail (initially a `YggEmptyState` placeholder — MIPAD-02 fills
  it).
- Sidebar entries are the existing six lenses (Today/A16, Interests/A18, Entities/A17,
  Consent/A19, Notes browser, Settings/A14) — same `VaultFileStore` instance, same lens views,
  re-hosted not rewritten. Where a lens view assumes tab presentation (e.g. its own
  `NavigationStack`), hoist the assumption behind the size-class branch rather than editing the
  iPhone code path.
- Adds an iPad simulator destination to bifrost CI so iPad layout is exercised on every PR (e.g. a
  second `xcodebuild test -destination 'platform=iOS Simulator,name=iPad Pro 13-inch (M4)'` run,
  or one destination matrix — implementer's choice; the pinning discipline from bifrost#8 applies).

## Concretely

```swift
// Shape, not prescription:
struct MimerShellView: View {
    @Environment(\.horizontalSizeClass) private var hSize
    var body: some View {
        if hSize == .regular { MimerCanvasView(fileStore: fileStore) }   // iPad
        else { MimerTabView(fileStore: fileStore) }                      // shipped B1 TabView, untouched
    }
}
```

Expected result in the iPad simulator: three visible columns in landscape; sidebar collapses
normally in portrait; every lens reachable from the sidebar shows the same content it shows on
iPhone.

## Why This Matters

Every subsequent B2 slice (browse columns, side-by-side JE, drag-drop) targets the regular-width
canvas. If the split-view skeleton is wrong — or silently changes iPhone behavior — the rest of
B2 builds on sand and INV-B2-1 is unenforceable.

## Acceptance Criteria

- [ ] Regular width presents `NavigationSplitView` with sidebar/content/detail; all six lenses are
  reachable from the sidebar. `Verify:` bifrost
  `Yggdrasil/YggdrasilUITests/MimerCanvasUITests.swift::testIPadShowsThreeColumnCanvasWithAllLenses`
  (new; runs on the iPad simulator destination).
- [ ] Compact width still presents the shipped `TabView` with unchanged tab set and behavior.
  `Verify:` bifrost existing `YggdrasilUITests` stay green on the iPhone destination, plus
  `MimerCanvasUITests.swift::testIPhoneKeepsTabBar` (new).
- [ ] bifrost CI runs the test suite on BOTH an iPhone and an iPad simulator destination.
  `Verify:` `.github/workflows/ci.yml` diff + a green CI run on the PR head showing both
  destinations.

## How to Verify (Pre-Merge)

- bifrost CI green on both destinations; `swiftlint --strict` clean.
- Authoring environments without `Xcode.app` rely on CI as the gate (bifrost's documented posture).

## Out of Scope

- Any detail-column content beyond a placeholder (MIPAD-02).
- Entity confirmation, annotation, drag-drop (MIPAD-03/04).
- Any vault write path change — this slice performs no writes.
- Keyboard shortcuts (MIPAD-02 carries them with the navigation they act on).

## Related Docs

- `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` §2 (iPad commitments), §3 (shell vs client boundary)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md` (invariants INV-B2-1..5)
- bifrost: `Yggdrasil/Yggdrasil/Mimer/MimerShellView.swift`, `Yggdrasil/Yggdrasil/App/RootView.swift`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:ready` — write-free, outside
the B2 write gate per the README's gate re-cut), linking hub #3024 as the tracking parent and this
spec file as its contract. TCD hint: Sonnet / medium effort — SwiftUI adaptive-layout work with a
strict no-regression constraint; no novel design decisions.
