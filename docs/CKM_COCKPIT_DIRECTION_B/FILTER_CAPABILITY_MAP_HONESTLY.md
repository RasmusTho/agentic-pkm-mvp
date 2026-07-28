---
name: Filter the Capability Map Honestly
description: Add one bounded inline script that filters already-rendered capability rows while leaving trust, gaps, source content, and JS-off use intact.
task_id: CKM-DB-04
source_anchor: docs/CKM_COCKPIT_DIRECTION_B/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: CKM Cockpit Direction B
prerequisites: [CKM-DB-03]
depends_on: [RENDER_COMPATIBLE_OBSERVATION_COMPARISONS.md]
can_parallelize_with: []
---

# Filter the Capability Map Honestly

## Purpose

Reduce scanning cost in the capability map through progressive enhancement, without hiding source
content, filtering the trust/gaps context, persisting state, or turning the generated file into an
application.

## What This Task Does

- Server-render normalized filter tokens on each capability row for capability name, definition,
  public ID, boundary, assessment availability/staleness, confidence flag, finding presence, and
  evidence lifecycle.
- Render search and closed allowlisted facet controls disabled by default.
- Add exactly one inline script that enables those controls, evaluates only the rendered tokens,
  toggles `hidden` on capability rows, and updates an `aria-live` `Showing N of M capabilities`
  disclosure.
- Keep banner, trust, hazards, comparison/refusal, gaps, proposals, and provenance outside the
  filter target.
- Preserve all rows and detail content in the source HTML and show a `<noscript>` explanation that
  all rows are visible.
- Amend the Direction A presentation contract narrowly: default overview remains script-free;
  opt-in cockpit mode permits exactly this one filtering-only script.

## Concretely

Before the script runs:

```html
<input type="search" disabled aria-controls="capability-map">
<p id="filter-count" aria-live="polite">Showing 31 of 31 capabilities</p>
<noscript>Filtering is unavailable; all capability rows are shown.</noscript>
```

The script may call `addEventListener`, read form values and `data-filter-*` attributes, assign the
row `hidden` property, remove control `disabled`, and update the count text. It may not call
`fetch`, `XMLHttpRequest`, `WebSocket`, clipboard APIs, storage APIs, cookies, history/URL APIs,
`eval`, timers, dynamic HTML parsing, or mutation outside capability rows/count/control state.

## Why This Matters

Filtering is the smallest interaction that materially reduces operator scanning. Server-rendered
source content and disabled-first controls avoid the failure mode where a blocked script yields an
empty or misleading page. A closed script contract prevents an apparently local artifact from
quietly acquiring network, persistence, or action authority.

## Acceptance Criteria

- [ ] Cockpit HTML contains exactly one inline `<script>` and no external script, inline event attribute, network reference, or additional executable block; default overview HTML still contains none.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_has_exactly_one_filtering_script_and_default_has_none`
- [ ] Before enhancement every capability row and detail body is present, controls are disabled, the disclosure says all rows are shown, and `<noscript>` explains the JS-off state.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_progressive_enhancement_keeps_full_source_content`
- [ ] The production script only enables controls, reads allowlisted rendered tokens, toggles capability-row `hidden`, and updates the disclosure count; forbidden APIs/tokens are absent.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_script_has_closed_filter_only_capability`
- [ ] Text and facet combinations produce deterministic AND semantics over capability rows and update `Showing N of M capabilities`.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_filters_rendered_rows_with_deterministic_and_semantics`
- [ ] The gaps panel, trust strip, hazards, comparison/refusal, proposals, and footer are never hidden or counted as filter targets.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_filter_never_hides_trust_or_gap_context`
- [ ] Keyboard focus, labels, disabled state, `aria-controls`, `aria-live`, and no-result announcement remain usable without colour-only meaning.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_filter_controls_are_accessible_and_honest`
- [ ] The implementation PR updates the Direction A contract to preserve the no-script default and document the one-script cockpit exception, without changing CKM authority.
  Verify: doc writeback at `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md :: Direction B amendment`
- [ ] The implementation PR posts JS-on, JS-off, zero-result, and gaps-unfiltered receipts to the parent.
  Verify: CKM-DB-04 delivery receipt on the Direction B parent issue

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Exercise text-only, each facet, combined facets, no-result, clear/reset, and JS-disabled cases
  through the generated artifact.
- Inspect the implementation script against the closed allowlist and forbidden API list.

## Restart / Durability Posture

Filter text/facets are deliberately in-memory DOM state and are never persisted. Reloading or
reopening the generated file shows all capability rows with controls returning to their default
empty state. No reviewed decision or proposal state is represented by filters, so this reset cannot
lose authority-bearing work.

## Out of Scope

- Sort, URL state, saved views, triage state, custom dimensions, or user-configured filters
- Filtering gaps, trust, hazards, comparisons, proposals, or source HTML generation
- Fetch, storage, cookies, clipboard, GitHub integration, or any write
- A second script for print, proposals, or disclosure expansion

## Related Docs

- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_HTML_PROJECTION.md`
- `app/builderops/ckm/overview_html.py`
- `tests/builderops/ckm/test_overview_html.py`

## Related GitHub Issues

Delivery history: child [#4084](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4084),
predecessor [#4083](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4083), and parent
[#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080) are closed. The planned cheapest
acceptable TCD route was **Terra/high** because the JavaScript was small but the security and
progressive-enhancement boundary required careful review.
