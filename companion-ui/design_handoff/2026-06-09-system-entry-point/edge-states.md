# Edge states — System Entry Point

Degraded, empty, loading, blocked, stale, and narrow detail that supplements `state-gallery.md`. All of these are reachable in `prototype.html`.

## Empty / cold

| State | Treatment | Must not |
|---|---|---|
| First contact (no history) | "Nothing is open yet." One calm way in (Browse the vault / System map). `leave_point.status: absent`. | Manufacture activity; show a re-entry overlay; greet with engagement copy. |
| Cold trajectory (> 14 days) | "No re-entry overlay." Re-entry routed to vault + search. The document is ambient context only. | Claim to reconstruct continuity it cannot back. |
| Empty open-loops / changes within an otherwise-warm return | Slice simply omitted from the re-entry card; the card shrinks. | Pad with placeholder rows or zero-state filler. |

## Loading

- **Boot (`A1`)** is the only blocking load: a single pulsing dot and the request label. It resolves within ~1.3s in the prototype (simulated).
- In-shell governed actions show a transient toast ("Executing via governed path… · WriteGuard") rather than a blocking spinner; the document stays interactive.
- Re-anchoring on note select is labelled with the `GET /api/companion/workspace?note_path` it stands in for.

## Degraded — partial orientation (HTTP 200)

- One or more sources failed to resolve; the snapshot still returns 200 with `meta.degraded_reasons`. An amber banner names the missing source (e.g. `resurfacing_source_unavailable`) and the rest of the re-entry card renders normally.
- The vault-status dot in the shell turns amber ("vault · degraded read").
- **Must not:** alarm, block the whole entrance, or substitute a confident local default for the missing slice. Degradation is calm and explicit.
- Reachable via the deck `degraded` toggle on `Returning · 2h` / `Returning · 5d`.

## No vault — runtime unreachable (HTTP 503)

- Distinct from degraded: the runtime aggregate itself is unreachable. Alert glyph, "Vault unreachable", provenance `runtime_unavailable · /api/companion/orientation · 503`, and reassurance that the vault (durable truth) is unaffected because the companion is only a client.
- Affordances: *Retry connection* (re-boots), *Open system map* (lets a newcomer still understand the system offline).
- **Must not:** represent request-level unavailability as a successful fresh snapshot (`WORKSPACE_ORIENTATION_CONTRACT.md §Runtime Unavailable`).

## Blocked — governed action denied

- Confirming the cross-note Panel proposal (writing a linked note outside the active note's allowlist) returns a calm amber **blocked** outcome: "WriteGuard denied (outside note allowlist)."
- Presented as a guard-held Proposal state per `BLOCKED_AND_STALE_STATE_SPEC.md`, with a reason and an implied path forward — never a generic error dialog, never conflated with a stale-hash block.
- **Must not:** present as success, hide the reason, or retry silently.

## Stale — leave-point or source hash mismatch

- `WORKSPACE_ORIENTATION_CONTRACT.md` defines `leave_point.status: stale | artifact_missing | degraded`. When stale, the re-entry card still renders but the resume affordance is qualified (the precise copy is an open question, Q9). A content-hash mismatch on a proposal marks it stale rather than confirmable.
- **Must not:** confirm against a stale hash; silently resume into a moved/missing artifact.

## Narrow / portrait

- The shell constrains to a phone-width column. Chat becomes a **bottom sheet** (single open state in the prototype; 3 snap points deferred — Q11) rather than a side rail.
- The long-mist **whisper column is suppressed** (no room); its content collapses into the re-entry card.
- Overlays (command, map, posture) narrow to fit; the topbar wordmark hides to preserve room for the anchor and controls.
- All critical affordances remain reachable: resume, open vault, command surface, posture, map, and the chat bottom sheet.
- Reachable via the deck `narrow` toggle (replicates the portrait media query in-page).

## Reduced motion / non-animating contexts

- Every visible end-state is the base style; entrance motion is additive only. Under `prefers-reduced-motion: reduce`, in print, or in a non-animating/offscreen render, all content (re-entry card, shell, overlays, toasts) is fully visible without depending on an animation having run. The infinite "breath" cues (caret echo, agent thinking dot) rest at a visible frame.

## Interruption integrity

- Per `ATTENTION_MODEL.md`, an interruption must preserve at least one recoverable anchor. The residual ambient layer after re-entry (caret echo at the stop point, marginalia dots) is that anchor; it persists in the shell after the mist dissolves. Overlay dismissal never erases unresolved cognitive tension (the staged suggestion and open-loop counts survive).

## New-surface degraded states (v2)

- **Context lane · no agenda source.** Because calendar/location are placeholders, the lane degrades to: time bands sourced from a manual agenda note if present, otherwise an empty, honest state ("nothing scheduled nearby") — never fabricated meetings. The place band defaults **off** with an opt-in prompt.
- **Location off / declined.** Default state. The place band shows the opt-in affordance, not a tracked location. Declining is a first-class, non-nagging state.
- **TTS provider unavailable.** Per `LOCAL_FIRST_TTS_CONTRACT.md`, a missing local provider/model is reported in the plan as unavailable — the read-back surface shows the warning and offers no audio, and does **not** fall back to browser/cloud TTS.
- **Settings on a degraded runtime.** Display/listening preferences remain fully usable (they are Local UI and need no runtime); only the connection posture reflects the degraded/unreachable state.
- **Capture while runtime unreachable.** The capture composer still accepts input; the governed append is queued/deferred and the UI states it is not yet written — it never claims a write it cannot back, and never silently drops the text.
