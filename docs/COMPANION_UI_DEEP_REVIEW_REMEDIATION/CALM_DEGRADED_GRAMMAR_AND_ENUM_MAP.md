---
name: Calm Degraded Grammar and Enum Map
description: Define one degraded-copy grammar and a runtime-enum/internal-identifier → human-copy map applied before any token reaches a user-facing surface.
task_id: CUIDR-01
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 03 Cross-cutting / State completeness; 04 D3, C3
parent_capability: Companion UI Deep-Review Remediation
prerequisites: []
depends_on: []
can_parallelize_with: [Overlay Modal Frame Spec, Rail Ambient Until Active, Edge Job and Reachability, Front Door and Copy Hygiene]
---

# Calm Degraded Grammar and Enum Map

## Purpose

The Companion UI has a strong degraded-state voice ("Nothing was mutated", "Nothing was lost") that breaks in two specific spots: the vault browser surfaces the raw transport error `"Error: Failed to fetch"`, and the orientation surface leaks the runtime enum `resurfacing_source_unavailable` as a visible chip. This task closes both gaps by establishing one canonical grammar template and one humanising map so that every unavailable/error/degraded state reads from the same voice.

## What This Task Does

1. Defines a single degraded-copy grammar template as a reusable render helper (a Python function or module-level constant in the companion-ui render layer):

   ```
   "<what> unavailable — <why>. <nothing-clause>. <what to do>."
   ```

   where `<nothing-clause>` is one of "Nothing was lost", "Nothing was decided", or "Nothing was mutated" depending on the surface's write posture.

2. Defines a runtime-enum/internal-identifier → human-copy map (a dict or equivalent lookup) that is applied before any classified token is written into HTML. The map covers at minimum:

   | Runtime token / identifier | Human copy |
   |---|---|
   | `resurfacing_source_unavailable` | `Orientation source unavailable` |
   | `orientation_unavailable` | `Orientation unavailable` |
   | `lifecycle.move` | `Move note` |
   | `prop-move-1` *(and similar proposal IDs matching `prop-*`)* | *(suppress — not user-facing copy; use the proposal's `description` field)* |
   | `art-123` *(and similar artifact IDs matching `art-*`)* | *(suppress — not user-facing copy; use the artifact's label or title field)* |

3. Wires the grammar template into the two confirmed leak sites:
   - `serve_dev_page.py` vault-browser error path (line ~3316 — currently `_e(str(error))`)
   - `serve_dev_page.py` orientation degraded-reason chip path (line ~5501 — currently `_e(reason)`)

4. Enforces a **fail-closed fallback**: if the map has no entry for a token, the output is `"… unavailable — details withheld. Nothing was lost."` — the raw token is never passed through.

**Hard constraint (restated from the capability README):** This task changes presentation only. It must not move any classification — which state is degraded, stale, blocked, or unavailable — into the client. The humanised string is produced by the map; the underlying classified value still arrives from the runtime payload. The map is a display layer; it is not a state machine.

## Concretely

**Before (leaked):**

| Surface | What the user sees |
|---|---|
| Vault browser (O5), orientation fetch fails | `Error: Failed to fetch` |
| Orientation card (E8), degraded chip | `resurfacing_source_unavailable` |
| Orientation card (E8), degraded chip | `orientation_unavailable` |
| Rail proposal card | `lifecycle.move → Projects/` (raw action class in preview text) |
| Rail proposal card | `prop-move-1` visible in rendered output |

**After (mapped through grammar):**

| Surface | What the user sees |
|---|---|
| Vault browser (O5), orientation fetch fails | `Notes unavailable — connection failed. Nothing was lost. Refresh to retry.` |
| Orientation card (E8), degraded chip | `Orientation source unavailable` |
| Orientation card (E8), degraded chip | `Orientation unavailable` |
| Rail proposal card | Human copy from `description` field; action class suppressed |
| Rail proposal card | Proposal IDs suppressed; proposal `description` used instead |

Unknown / unmapped token (fail-closed):

| Input | Output |
|---|---|
| `some_new_runtime_token_not_in_map` | `… unavailable — details withheld. Nothing was lost.` |

## Why This Matters

The degraded voice — "Nothing was mutated / decided / lost" — is identified by the review as a genuine strength and a deliberate commitment (REVIEW_RESPONSE.txt §03, State completeness). Raw transport errors and raw runtime enums break that voice at the exact moments the user most needs calm: when a surface is unavailable or partial. Fixing this is the prerequisite for every downstream task (mist ladder, blocked recourse, front-door error) that must emit unavailable or held-state copy — they all share the same output path. The cost is low (a map lookup and a grammar helper); the upside is consistency across the full state vocabulary.

## Acceptance Criteria

- [ ] **Grammar definition.** A single degraded-grammar render helper (`calm_degraded(what, why, nothing_clause, what_to_do)` or equivalent) exists in the companion-ui render layer and is the only code path that emits unavailable/error copy on any user-facing surface. No surface may inline its own unavailable-state string literal.
  Verify: `tests/companion_ui/test_calm_degraded_grammar.py::test_grammar_helper_is_sole_unavailable_emitter` — static scan of the render module confirms no `"unavailable"` or `"Error:"` string literal outside the helper; the helper's output matches the template for all parametrised inputs.

- [ ] **C3 (review verbatim).** No raw runtime enum or internal identifier (e.g. `resurfacing_source_unavailable`, `prop-move-1`, `art-123`, `lifecycle.move`) is visible on any user-facing surface; each maps to human copy.
  Verify: `tests/companion_ui/test_calm_degraded_grammar.py::test_enum_map_covers_known_tokens` — parametrised over the confirmed leak tokens; each asserts that rendering the degraded + proposal fixtures produces no raw token in the HTML output, and that the humanised string is produced by the map function (not hardcoded in the template call-site). The classified value (`resurfacing_source_unavailable`, `lifecycle.move`, etc.) must still be present in the fixture payload passed to the renderer — confirming it arrives from the runtime, not derived in the template.

- [ ] **D3 (review verbatim).** No surface shows a raw transport error (`"Error: Failed to fetch"`); all unavailable states use the single calm grammar.
  Verify: `tests/companion_ui/test_calm_degraded_grammar.py::test_vault_browser_fetch_error_uses_calm_grammar` — renders the vault-browser error path (O5 fixture) with `vault_browser_error="Error: Failed to fetch"` and asserts: (a) the literal string `Error: Failed to fetch` does not appear in the HTML output; (b) the output matches the calm grammar template; (c) the `data-testid="workspace-vault-browser-state-error"` element is present (confirming the classified error state still arrives from the payload).

- [ ] **Fail-closed fallback.** If the enum map has no entry for a token, the output is `"… unavailable — details withheld. Nothing was lost."` — the raw token never appears in HTML.
  Verify: `tests/companion_ui/test_calm_degraded_grammar.py::test_enum_map_fail_closed_on_unknown_token` — passes a token not in the map; asserts the raw token is absent from the output and the fallback string is present.

## How to Verify (Pre-Merge)

```bash
# Run the full calm-grammar test suite (static, no runtime needed):
cd /Users/rasmusthornberg/code/agentic-pkm-mvp-cui-review
pytest tests/companion_ui/test_calm_degraded_grammar.py -v

# Also run the existing orientation/vault-browser tests to confirm no regressions:
pytest tests/companion_ui/test_orientation_ambient_refresh.py \
       tests/companion_ui/test_reentry_orientation_surface.py \
       tests/companion_ui/test_reentry_orientation_treatment.py \
       tests/companion_ui/test_vault_browser.py \
       -v

# Confirm no raw token leaks in a static render scan:
# The test_enum_map_covers_known_tokens parametrised case covers this;
# additionally grep the rendered HTML captured by the fixture to confirm
# resurfacing_source_unavailable, prop-move-1, art-123, lifecycle.move,
# and "Error: Failed to fetch" are all absent from output HTML.
```

CI: all of the above run under the `not pg` pytest gate (no database required). No live runtime is needed; all ACs are static.

## Out of Scope

- Does NOT change which states the runtime classifies as degraded, stale, blocked, or unavailable. Classification stays server-side.
- Does NOT change the orientation fetch logic, the WriteGuard rule, or the vault-browser data path — only the error display.
- Does NOT add new degraded states or extend the state machine.
- Does NOT handle the copy half of A3 (giving Blocked a plain-language reason + recourse) beyond establishing the grammar template that `BLOCKED_RECOURSE_AND_LANE_LABELING.md` will consume.
- Does NOT address the discoverability, layout, or navigation issues flagged by the review (those are B1–B4, D1–D2, E1–E2).

## Related Docs

- [REVIEW_RESPONSE.html](../../companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.html) — rendered design review; see §03 State completeness, §04 recommendations C3 and D3, §05 UAT rows C3 and D3.
- [README.md](README.md) — capability overview, execution order, and cross-task invariants (partial-failure rule restated in §Cross-Task Invariants).

## Related GitHub Issues

This spec maps to one child GitHub issue: **[Companion UI Deep-Review] calm-degraded-grammar — Wave 1; agent:ready**. Labels: `companion-ui`, `wave-1`, `agent:ready`, `Status=Ready`. The issue body should reference this file as its specification and cite CUIDR-01. It is a Wave-1 primitive; downstream tasks 6 (Mist Ladder) and 8 (Blocked Recourse) are blocked on it merging.
