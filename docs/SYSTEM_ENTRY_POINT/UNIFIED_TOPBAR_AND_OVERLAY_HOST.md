---
name: Unified Topbar and Overlay Host
description: Topbar consolidation (wordmark, anchor pill, posture pill, surface icons, vault-status dot) plus the shared overlay host with Esc/dismiss-to-anchor and the keyboard map
task_id: SEP-03
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Overlay-grammar rule (NORMATIVE)
parent_capability: system-entry-point
prerequisites: [SEP-01]
depends_on: [ENTRY_STATE_MACHINE.md]
can_parallelize_with: [REENTRY_ORIENTATION_TREATMENT.md, CAPTURE_TO_VAULT_INBOX.md, MEMORY_REVIEW_DRAWER.md]
---

# Unified Topbar and Overlay Host

## Purpose

Give every new surface one place to mount and one rule to obey: overlays open over the document anchor and dismiss back to it with no route reset. Consolidate the shipped header strip into the spec's topbar.

## What This Task Does

- **Topbar**: evolves the shipped workspace header (`data-region="workspace-header"`) into the spec's topbar: wordmark, **anchor pill** (`data-region="document-anchor"`, current note identity), **posture pill** (local posture emphasis, `data-posture-emphasis`; rendering only — the switch overlay may land with this task or with the host's first occupants), surface icons (vault / command / map / settings / capture / receipts / help), and the **vault-status dot** (coarse derived posture only; detailed health stays with `/api/status`).
- **Shared overlay host**: a single overlay layer in the shell that mounts command palette, system map, settings drawer, memory drawer, capture modal, receipts modal, source peek, and posture switch. The host enforces: `Esc` dismisses topmost overlay (`overlay.dismiss`); dismissal returns to the document anchor with no route reset and no data loss; staged suggestions and open-loop counts survive open/dismiss cycles; only declared overlays can mount.
- **Keyboard map**: `⌘K` → `cmd.open`, `⌘N` → `capture.open`, `Esc` → `overlay.dismiss`. The map is inert for overlays whose tasks have not landed (no dead affordances: icons/shortcuts for unshipped surfaces are absent until their task ships).
- Existing left pane (vault browser) and right rail (Panel/agent rail) keep their shipped layout behavior; the narrow-mode modal behavior of the left pane is treated as an overlay-host occupant for the dismiss rule.

## Concretely

```text
⌘K → overlay host mounts the command palette; Esc → back to anchor, scroll preserved
open settings → drawer over the anchor; document column remains visible and primary
[data-rail="open"] survives an overlay open/dismiss cycle
```

## Why This Matters

Without a shared host, each overlay re-implements dismissal and routing, and route resets creep in — exactly the context-fragmentation failure `ATTENTION_MODEL.md` names. The host makes the overlay-grammar rule structurally enforceable and testable once.

## Acceptance Criteria

- [ ] The topbar renders wordmark, anchor pill, posture pill, surface icons for shipped surfaces only, and the vault-status dot.
  Verify: `tests/companion_ui/test_overlay_host.py::test_topbar_renders_declared_regions`
- [ ] Every mounted overlay dismisses to the document anchor with no route reset (URL, scroll ownership, and anchor identity preserved).
  Verify: `tests/companion_ui/test_overlay_host.py::test_overlay_dismiss_returns_to_anchor_without_route_reset`
- [ ] `Esc` dismisses the topmost overlay; `⌘K` and `⌘N` route to their declared intents.
  Verify: `tests/companion_ui/test_overlay_host.py::test_keyboard_map_routes_declared_intents`
- [ ] Staged suggestions and open-loop counts survive an overlay open/dismiss cycle (no erased tension).
  Verify: `tests/companion_ui/test_overlay_host.py::test_overlay_cycle_preserves_staged_state`
- [ ] Undeclared overlay ids cannot mount on the host.
  Verify: `tests/companion_ui/test_overlay_host.py::test_undeclared_overlays_rejected`
- [ ] The vault-status dot renders only a coarse derived posture and exposes no detailed health slices.
  Verify: `tests/companion_ui/test_overlay_host.py::test_vault_status_dot_is_coarse_posture_only`
- [ ] Narrow mode keeps every critical affordance reachable; the shipped responsive collapse keeps passing.
  Verify: `tests/companion_ui/test_workspace_responsive.py` (existing suite stays green) and `tests/companion_ui/test_overlay_host.py::test_narrow_mode_preserves_critical_affordances`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_overlay_host.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_workspace_layout.py tests/companion_ui/test_workspace_responsive.py`
- `ruff check app tests`

## Out of Scope

- The individual overlay surfaces themselves (SEP-04, SEP-05, SEP-07, SEP-08b, SEP-09b, SEP-10).
- Replacing the 3-column workspace with a drawer layout — the shipped layout is settled.
- A fuller keyboard model beyond ⌘K/⌘N/Esc (package Q14, deferred).
- The chat rail occupant (canvas-chat lane).

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Overlay-grammar rule, §Keyboard map
- `companion-ui/docs/OVERLAY_GRAMMAR.md`
- `companion-ui/docs/ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md` (#1395 layout)

## Related GitHub Issues

Filed as **#1785** (`[SystemEntryPoint] unified-topbar-overlay-host: shared overlay substrate + keyboard map`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies.
