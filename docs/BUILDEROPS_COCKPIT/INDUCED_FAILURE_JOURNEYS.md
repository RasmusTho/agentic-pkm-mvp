---
name: Induced Failure Journeys
description: Playwright journeys that prove the cockpit goes red-not-calm when a source dies, in the post-merge browser lane
task_id: BOPS-COCKPIT-02
source_anchor: "docs/BUILDEROPS_COCKPIT/README.md :: Verification model"
parent_capability: BuilderOps Cockpit
github_issue: 4448
prerequisites: [BOPS-COCKPIT-01]
depends_on: [REGISTRY_READ_TIME_JOIN.md]
can_parallelize_with: [GITHUB_LIVE_PLANE.md, DOCS_PLANE_CAPABILITY_LANES.md, COGNITIVE_LOAD_SIBLING.md]
---

# Induced Failure Journeys

## Purpose

The cockpit's worst failure mode is a false-green: an empty or degraded surface read as calm. That
mode is Playwright-inducible, and the owner's rule is that the inducing journey must exist while
the surface is in operation — verify-the-verifier applied to the cockpit itself.

## What This Task Does

Adds browser-level journeys for the served `/cockpit` surface, running in the existing post-merge
browser lane (`.github/workflows/browser-runtime.yml`, push-to-main path-filtered), never as a
required PR check. **The lane runs individually named test files, not directories** — this slice
must add its own non-`continue-on-error` step to `browser-runtime.yml` invoking
`pytest -q tests/companion_ui/test_cockpit_journeys.py`, exactly like the existing
`test_runtime_unavailable_browser.py` step; a journey file dropped into the directory without the
workflow step would silently never run, which is the precise false-green this task exists to
prevent. The file must live at `tests/companion_ui/test_cockpit_journeys.py` (already inside the
lane's push paths filter) and must carry both exclusion mechanisms every existing browser test
uses: `pytestmark = pytest.mark.browser_runtime` (the marker `scripts/select_pr_tests.py`'s PR
marker expression deselects) plus the `COMPANION_UI_BROWSER_TESTS` env gate.

The journeys:

- **Dead-source journey**: start the API with an unreadable dispatcher store path, load
  `/cockpit`, assert the refused claim is rendered (the "cannot be counted" state, red framing,
  and no band showing `0`) — red-not-calm.
- **True-emptiness journey**: empty but readable store; assert the dated positive claim renders
  with fresh source pills and bands present at zero.
- **Populated journey**: seeded store; assert locked band order, evidence spine present per card,
  per-source freshness pills, and out-links carrying the authority URL.
- **Keyboard journey**: cards reachable in natural tab order, expandable via keyboard, focus ring
  visible.

Journeys assert against rendered DOM text, not implementation internals.

## Concretely

```
COMPANION_UI_BROWSER_TESTS=1 pytest tests/companion_ui/test_cockpit_journeys.py -m "not pg"
```

Expected locally with Playwright installed: all journeys pass; the dead-source journey fails
loudly if the surface ever renders a calm zero over a dead source.

## Why This Matters

Without the induced-failure journey, the honesty machinery in `cockpit_registry.py` is only
unit-proven — nothing asserts the *rendered surface* refuses calm. A regression in `cockpit.js`
could show `0` over a refused claim and every unit test would stay green.

## Acceptance Criteria

- [ ] A dead dispatcher source renders refused-not-calm on the served surface
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_dead_source_renders_refusal_not_calm`
    (enforcement AC: the journey drives the production `/cockpit` route against an API process
    whose store path is unreadable, asserting the refusal text and the absence of any zero count)
- [ ] True emptiness renders as a dated positive claim with fresh pills
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_true_emptiness_is_dated_claim`
- [ ] Populated state renders locked band order, spine, freshness pills, and out-links
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_populated_bands_spine_freshness`
- [ ] Cards reachable and expandable via keyboard with a visible focus ring
  - Verify: `tests/companion_ui/test_cockpit_journeys.py::test_keyboard_reachability_and_focus`
- [ ] The journey file is wired into the post-merge browser lane as its own non-`continue-on-error`
      step
  - Verify: diff of `.github/workflows/browser-runtime.yml` adding a step that runs
    `tests/companion_ui/test_cockpit_journeys.py`
- [ ] The journey module is excluded from the required PR lane by the same mechanism as every
      existing browser test
  - Verify: `pytestmark = pytest.mark.browser_runtime` present in
    `tests/companion_ui/test_cockpit_journeys.py`, deselected by the PR marker expression in
    `scripts/select_pr_tests.py`

## How to Verify (Pre-Merge)

- `COMPANION_UI_BROWSER_TESTS=1 pytest tests/companion_ui/test_cockpit_journeys.py` locally (or on
  the mini — the laptop is not the runtime environment; skip-markers must make the suite green
  without the browser env set).
- Confirm the journey module is deselected from the required PR lane by the marker expression
  (`not browser_runtime` in `scripts/select_pr_tests.py`) — note the selector *does* include
  `tests/companion_ui` in the PR lane on path grounds; exclusion happens through the marker, so
  the marker line is load-bearing.

## Out of Scope

- Journeys for planes not yet joined (GitHub live, docs, CKM) — added by the tasks that add the
  planes, extending this file.
- Any required-PR-check change; any new CI workflow (the existing browser lane is the home).
- Visual-diff/screenshot testing.

## Related Docs

- `docs/BUILDEROPS_COCKPIT/README.md`
- `.github/workflows/browser-runtime.yml`

## Related GitHub Issues

One bounded issue: implement the four journeys and lane wiring. Reference
"Implements BUILDEROPS_COCKPIT/INDUCED_FAILURE_JOURNEYS".
