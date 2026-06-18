# Design notes — Cold-start entry threshold

## The diagnosis (verified against code)

The entry surface violates the normative anti-dashboard rule of `SYSTEM_ENTRY_POINT_SPEC.md` on `cold_start`:

- The `"Re-entry snapshot"` h1, the telemetry meta row (`vault · channel · freshness · as_of · trace · watcher_runs_24h`), and the two-column orientation grid (leave-point / open-loops / notable-changes / governance / resurface) render **unconditionally** at `serve_dev_page.py:6377-6408`. There is no `entry_resolution.state` branch in the body — only the re-entry *shape* selector at `:5829`, which already correctly emits nothing for `cold_start`.
- Net effect on a true first contact: a `"Re-entry snapshot"` heading over **zero-filled collections** — the literal forbidden dashboard.
- The resolver is correct: `resolve_entry_state()` returns `cold_start` for `leave_point.status == "absent"`. The fix is a **render-layer recomposition**, not a state-machine change.

Two adjacent facts, both code-verified, shaped the design:

- **Capture is not mounted on the entry surface.** `capture` is mounted only on the workspace shell (`serve_dev_page.py:10454`); `overlay_host_overlays_html` (`:5896`) omits it, so the `⌘N` handler (`overlay_host.py:342`) silently no-ops on the entry surface today.
- **The duplication bug** (heading == body) is real but separate: the v1 `leave_point` contract has no top-level `label`, so `leave.get("label") or artifact.get("title")` always falls through to `title`, rendering the heading identical to the `_orientation_artifact_link` body (`:5138`/`:5140`; re-entry card `:5605-5611`; whisper lines). It lives on the *preserved* `orienting`/`shell_active` path and is filed as its own issue.

## The design round

Four divergent directions were designed and each adversarially critiqued across four lenses (spec-compliance · cognitive-soundness · implementability · human-meaning).

| Direction | Avg | Lens-fails | Outcome |
|---|---|---|---|
| **quiet-threshold** | 8.5 | 0 | **Recommended base** |
| **intent-led-modes** | 8.3 | 0 | Co-winner; verb-line grafted |
| resurface-invitation | 6.3 | 1 | Rejected on the door; subtractive half kept |
| document-as-door | 6.0 | 1 | Failed premise; recency insight grafted |

### Why the two winners, and why they are the same move

Quiet-threshold and intent-led-modes are structurally identical: gate the orientation grid behind `state in ('orienting','shell_active')` and render a near-empty threshold for `cold_start`/`no_vault`, with **no** change to the five states, the shape ladder, the cross-flags, the transitions, or the data-attributes. Quiet-threshold is chosen as the **base** because its inline governed capture field is a real continuity move — a commitment to future-self that seeds the next trajectory into the durable vault substrate — rather than navigation only.

### Grafts

- **From intent-led-modes — the verb-line.** Render the doors as an inline intent-verb sentence (*Find a note · Jot something down · See the map*) rather than static links, reframing the surface from "what can I open" to "where does my thinking want to go." Each verb maps 1:1 onto an already-declared intent; **zero new intents**. The deliberate omission of a "Reorient" verb (no trajectory to reorient into = forbidden false continuity) is the strongest single decision carried over. Enforced as prose, never a 2×2 grid.
- **From quiet-threshold — the capture field + vault chip.** The inline "leave a note for future-you" field reuses the shipped capture modal verbatim (no due-date, no checkbox, no app-task-state; a write is claimed only on the runtime `WriteReceipt`). The vault chip is the minimum-viable "which of my vaults am I in" identity signal for a multi-vault operator.
- **From document-as-door — recency as an honest Find fact (repaired).** Recency/mtime is an observable Find fact, **not** a continuity claim. Grafted as an *optional* server-declared "most-recently-edited" target that the Find verb may route to as a labeled "Open your most recent note" sub-affordance (`/workspace?note_path=…`, an enumerated `cold_start → shell_active` user action). Never auto-opened, never a `leave_point`, omitted when absent. Operator-adopted (see `open-questions.md` Q1).

### Rejections (grounded)

- **document-as-door fails outright.** `resolve_entry_state()` returns `shell_active` whenever `note_loaded == True`, so its central claim ("`cold_start` with a loaded document body") is impossible — a loaded body can never carry `data-entry-state=cold_start`. Auto-opening a chosen prior note on first contact is also a continuity gesture the system cannot back.
- **resurface-invitation's card region rejected on the door** on two grounds: (1) a multi-card content feed on the most-constrained state is the forbidden dashboard (its own top risk concedes this); (2) its "each card is a door" premise is broken in code — `_render_resurface_mode`'s source link is `data-source-link` with the URL as **inert** text (`serve_dev_page.py:3748-3749`, no click handler), while the renderer that actually routes is `_orientation_artifact_link` (`:5019`). Only the **subtractive** half (remove header / meta row / open-loops / notable-changes / governance grid / zero-count strip from `cold_start`) is kept. Resurface stays pull-only in the map and the shell rail.

## What moves off the door (→ pull-only surfaces)

The hard requirement, flagged by the spec-compliance lens: relocated telemetry must render as **read-only projection, counts-not-tiles, no zero-state** — never as live dashboard tiles, or the dashboard is re-created one layer deeper.

| Removed from `cold_start` | Lands at | Rendering rule |
|---|---|---|
| `"Re-entry snapshot"` h1 + meta row (`freshness`/`as_of`/`trace_id`) | System map entry-point node **and** topbar runtime-status disclosure | read-only projection; kept in both so an operator diagnostic is never stranded |
| Governance 3-cell grid (proposals / receipts / outcome) | Receipts surface + map governance node | read-only projection, not live tiles; no zero-state |
| Open-loops list/counts | Memory-review map node + the document's panel rail (once a note is open) | loops belong to a trajectory; legitimately none on first contact |
| Notable-changes list | `orienting` long-mist delta strip only | never manufactured for an empty `cold_start` |
| Resurface candidates | Resurface rail mode (shell) + mode-labelled map node | reached only by explicit pull, never unbidden on entry |
| `_reentry_counts` aggregate | full-mist / long-mist re-entry card in `orienting` | counts imply a trajectory `cold_start` cannot back |

## What is explicitly unchanged

- **`orienting`** keeps the full shape-driven mist ladder (`serve_dev_page.py:5829-5856`): `no_mist` / `thread_fade` / `soft_mist` / `full_mist` (the four fixed questions) / `long_mist` (+ delta strip + whisper column + memory drawer mount). The verb-line and inline capture do **not** render during `orienting` — the user's direction is already implied by their trajectory; declaring intent would compete with the re-entry treatment for the attention the spec reserves for the document. The two surfaces are mutually exclusive by entry state.
- **`shell_active`** stays the only state with a document body open. This is the structural reason document-as-door is rejected.
- The five states, transitions, shape ladder, cross-flag rules, and data-attribute vocabulary.
