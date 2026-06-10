---
name: Memory Review Drawer
description: Review-queue read and decision endpoints over the existing memory-candidate seam (governed accept per ADR-0009) plus the right-drawer review UI
task_id: SEP-09
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Surface composition (NORMATIVE table)
parent_capability: system-entry-point
prerequisites: [SEP-03]
depends_on: [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md]
can_parallelize_with: [REENTRY_ORIENTATION_TREATMENT.md, CAPTURE_TO_VAULT_INBOX.md]
---

# Memory Review Drawer

## Purpose

Close the loop the orientation seam opened: orientation emits reference-only `MemoryCandidate` intents and a pending count (ADR-0009), but there is no Companion UI surface where promotion actually happens. "Unreviewed memory is not semantic authority" needs a place where review occurs — governed, explicit, pull-based.

## What This Task Does

This task specification maps to **two GitHub issues** (grandchildren), in order:

**(a) Runtime: review-queue read + decision endpoints.** A bounded read endpoint over the existing `agent_memory.review_queue` (candidate list with why-now reason, provenance `source_ref`, and authority posture — no raw candidate bodies beyond what the review boundary already admits), plus a governed **accept** decision path that promotes a candidate through the existing governed machinery per ADR-0009 and the agent-memory contract. Defer and reject are review-queue actions that do not perform durable semantic promotion. The runtime half has **no UI dependency** and may start in parallel with SEP-02/SEP-03.

**(b) UI: right-drawer review surface.** Mounted on the overlay host (`memory.open`), reached from the topbar and from the re-entry card's unresolved-inspect affordance. Renders: the "Unreviewed memory is not semantic authority" callout, the pending candidates with why-now and provenance, and three actions — **Accept (governed)**, **Defer**, **Reject**. Accept routes through the (a) decision endpoint and surfaces the runtime outcome; the UI never auto-promotes, never treats a candidate as memory truth, and never classifies candidate-worthiness locally.

## Concretely

```text
orientation: memory.pending_candidate_count = 2 → re-entry inspect → memory.open
drawer: candidate + why_now + source_ref + authority tag
Accept → governed decision → outcome rendered from runtime response
Defer / Reject → queue action; no durable semantic promotion; no invented receipt
```

## Why This Matters

Without a governed review surface, pending candidates either rot (the seam emits intents nobody can act on) or get promoted by a back door. This drawer is the only admissible place where candidate → memory promotion is decided.

## Acceptance Criteria

- [ ] The read endpoint lists pending candidates with why-now, provenance, and authority posture, exposing no inadmissible raw content.
  Verify: `tests/api/test_memory_review_queue_api.py::test_review_queue_read_is_bounded_and_provenance_bearing`
- [ ] Accept routes through the governed decision path and the promotion outcome comes from the runtime, per ADR-0009.
  Verify: `tests/api/test_memory_review_queue_api.py::test_accept_is_governed_decision`
- [ ] Defer and reject perform review-queue actions only — no durable semantic promotion, no invented receipt.
  Verify: `tests/api/test_memory_review_queue_api.py::test_defer_and_reject_do_not_promote`
- [ ] The drawer renders candidates with the not-semantic-authority callout and the three actions; Accept surfaces the runtime outcome.
  Verify: `tests/companion_ui/test_memory_review_drawer.py::test_drawer_renders_candidates_and_governed_accept`
- [ ] The UI never classifies candidate-worthiness locally and never renders a candidate as accepted memory before the runtime says so.
  Verify: `tests/companion_ui/test_memory_review_drawer.py::test_no_local_classification_or_premature_promotion`
- [ ] The drawer is reachable from the re-entry inspect affordance and dismisses to the anchor.
  Verify: `tests/companion_ui/test_memory_review_drawer.py::test_reachable_from_reentry_and_dismisses_to_anchor`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_memory_review_queue_api.py tests/api/test_orientation_memory_seam.py` (issue a)
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_memory_review_drawer.py` (issue b)
- `ruff check app tests`

## Out of Scope

- Changing the orientation seam (ADR-0009 intent emission stays as shipped).
- Memory recall, memory editing, or memory browsing surfaces.
- Auto-promotion, batch-accept, or any persistent review banner/inbox pressure.
- The 2026-05-14 memory-candidate-review design package's full queue console — this is the bounded drawer the entry-point composition needs.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Intent vocabulary (`memory.*`)
- `docs/adr/ADR-0009-orientation-memory-candidate-intent.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` §`memory`, §Mutation Intents

## Related GitHub Issues

Create **two** issues: `[SystemEntryPoint] memory-review-endpoints: queue read + governed accept` (runtime; no UI dependency) and `[SystemEntryPoint] memory-review-drawer: right-drawer review UI` (depends on the endpoints issue and SEP-03).
