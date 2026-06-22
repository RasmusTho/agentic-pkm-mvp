# Surface Inventory

Every captured surface, what triggers it, the journey it belongs to (see
`WORKFLOWS_TO_EVALUATE.md`), the governing spec, and any observation already noted during
capture. Screenshots are in `img/`. All desktop captures are 1440×900 @2x unless noted.

## Entry / orientation states (the front door)

| # | Screenshot | Surface / state | Trigger (runtime-declared) | Journey | Spec | Pre-noted observation |
|---|---|---|---|---|---|---|
| E1 | `entry_01_first_contact.png` | **cold_start — first contact** | No prior leave point | J1 | ENTRY_STATE_MACHINE | Anti-dashboard posture; vault entry + "see the map" only. Judge: is the way *in* obvious? |
| E2 | `entry_02_cold_21d.png` | **cold_start — returning >14d** | Gap 21 days | J1 | REENTRY_ORIENTATION_TREATMENT | Same calm posture as first contact even though there *is* history — intended. Does it feel right after 3 weeks away? |
| E3 | `entry_03_no_mist.png` | **orienting — no_mist** | Gap ~30s | J4 | REENTRY_ORIENTATION_TREATMENT | Should look essentially like an uninterrupted session (no re-entry cue). |
| E4 | `entry_04_thread_fade.png` | **orienting — thread_fade** | Gap ~5min | J4 | REENTRY_ORIENTATION_TREATMENT | Rail fade only; subtle. Is the cue perceptible without being noise? |
| E5 | `entry_05_soft_mist.png` | **orienting — soft_mist** | Gap ~1h | J4 | REENTRY_ORIENTATION_TREATMENT | Peripheral line + caret echo. |
| E6 | `entry_06_full_mist.png` | **orienting — full_mist (re-entry card)** | Gap ~1 day | J4 | REENTRY_ORIENTATION_TREATMENT | The full re-entry card with resume/dismiss. Core resumption moment — judge hard. |
| E7 | `entry_07_long_mist.png` | **orienting — long_mist** | Gap 7 days | J4 | REENTRY_ORIENTATION_TREATMENT | Card + delta strip + whisper column. Most information-dense entry state — does it stay calm? |
| E8 | `entry_08_degraded_full_mist.png` | **orienting + degraded** | full_mist + source unavailable | J4 | ENTRY_STATE_MACHINE | Amber degraded banner. Informative not alarming? |
| E9 | `entry_09_stale_leave_point.png` | **orienting + stale leave point** | Leave point stale | J4 | REENTRY_ORIENTATION_TREATMENT | "Nothing was mutated" guard copy; presents as held state, not error. |
| E10 | `entry_10_no_vault.png` | **no_vault — runtime unreachable** | Orientation 503 | J1/J7 | ENTRY_STATE_MACHINE | Calm threshold + retry. Does it explain *what to do* vs just "unavailable"? |
| E11 | `entry_11_vault_picker.png` | **no_vault — vault selection picker** | `vault_selection_required` | J1 | (Option-2, #2309) | One-click "Open <vault>" + open/recent/init below. First-run / vault-switch path. |

## Shell / document states (the working surface)

| # | Screenshot | Surface / state | Trigger | Journey | Spec | Pre-noted observation |
|---|---|---|---|---|---|---|
| S1 | `shell_01_active_anchor.png` | **shell_active — base** | Document open | J2 | SYSTEM_ENTRY_POINT_SPEC | The reading surface + outline rail (left) + Panel/agent rail (right) + topbar. **Topbar right cluster clipped & overlapped by Panel rail — see OBSERVED_ISSUES #1.** |
| S2 | `shell_02_staged_suggestion.png` | **body-edit: staged suggestion** | Agent stages a body suggestion | J5 | CANVAS_SUGGESTION_FLOW | Ungoverned lane: apply/discard, **no receipt**. Is the "this won't be recorded" distinction legible? |
| S3 | `shell_03_panel_proposals.png` | **Panel proposals staged** | Agent proposes governed actions | J5/J6 | PANEL_COMMAND_PALETTE | Move/tag proposals with Apply/Discard/Defer in the right rail. |
| S4 | `shell_04_governed_receipt.png` | **governed action → receipt** | Proposal executed | J6 | RECEIPTS_HISTORY_SURFACE | Receipt pill rendered from runtime projection. Can the user tell their vault changed *and* there's a record? |
| S5 | `shell_05_panel_blocked.png` | **Panel blocked (WriteGuard)** | Write guard holds the action | J6 | OVERLAY_GRAMMAR | Presents as guard-held, not a red error. Is the reason + recourse clear? |

## Overlays / drawers / modals (the one overlay host)

All opened on the shell via `overlayHost.mount(...)`. Spec: `OVERLAY_GRAMMAR.md` +
`UNIFIED_TOPBAR_AND_OVERLAY_HOST.md`.

| # | Screenshot | Overlay | Open intent | Journey | Pre-noted observation |
|---|---|---|---|---|---|
| O1 | `overlay_01_command_palette.png` | **Panel command palette (⌘K)** | `cmd.open` | J6 | "Chat — a faster presentation of the same governed proposals." Filter + per-proposal Apply/Discard/Defer. |
| O2 | `overlay_02_capture_modal.png` | **Capture to inbox** | `capture.open` (⌘N) | J3 | Quick capture → governed vault append. Does it feel frictionless enough to actually use mid-thought? |
| O3 | `overlay_03_memory_review.png` | **Memory review drawer** | `memory.open` | J6 | Shows degraded/empty fallback ("Review queue unavailable") — **no live runtime**; populated state needs live UAT. |
| O4 | `overlay_04_settings_drawer.png` | **Settings (Local UI prefs)** | `settings.open` | J7 | Display/Listening/Behaviour/Connection. Render-only prefs; never touches the vault. Scannable? |
| O5 | `overlay_05_vault_browser.png` | **Vault browser** | `vault.open` | J2 | Note list + filters + inspector. Primary navigation between notes. |
| O6 | `overlay_06_receipts_history.png` | **Receipts history** | `receipts.open` | J6 | Read-only ledger of governed outcomes. The "what has the agent done to my vault" record. |
| O7 | `overlay_07_system_map.png` | **System map** | `map.open` | J1/all | "Every surface, one index." The discoverability backstop for a deliberately quiet UI. Judge whether it carries that load. |
| O8 | `overlay_08_guidance_layer.png` | **Guidance layer (ⓘ)** | `guidance.toggle` | all | Off by default; reveals server-rendered callouts. Teaching layer for an expert-but-intermittent user. |

## Responsive

| # | Screenshot | What | Note |
|---|---|---|---|
| R1 | `narrow_shell_01_active_anchor.png` | Shell at 430px | Rail → bottom-sheet triggers; vault browser becomes modal fallback. Does the reading surface survive? |
| R2 | `narrow_entry_07_long_mist.png` | long_mist at 430px | Whisper column suppressed; collapses into the card. |

## Evidence (supporting OBSERVED_ISSUES)

| Screenshot | Shows |
|---|---|
| `evidence_topbar_1280.png` | Topbar at 1280px — right surface-icon cluster truncated/overlapped by Panel rail. |
| `evidence_topbar_1920.png` | Topbar at 1920px — same content fits cleanly. Confirms the issue is non-responsive overflow, not missing markup. |
