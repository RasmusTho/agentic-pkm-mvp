# Open questions — System Entry Point

Each question is triaged into one of:

- **resolve-before-promotion** — blocks Crossing B; must be answered before this package becomes a normalized spec.
- **resolve-in-normalized-spec** — does not block promotion; the normalized-spec author settles it.
- **defer-to-implementation-issue** — settled when the bounded issue is written, not before.

**No `resolve-before-promotion` question blocks this package's Crossing B** — see Q1–Q3 resolutions below. Q15–Q16 are `resolve-before-promotion` but **scoped only to the Context lane / place band**, which ship as explicit placeholders; they do not gate the entry-point, shell, settings, read-back, capture, or receipts surfaces. The context lane should be promoted to a normalized spec separately, after Q15–Q16 are answered.

---

## Resolved before promotion (Crossing-B blockers, now closed)

### Q1. Does the unifying shell violate `DESIGN_BRIEF.md`'s "don't extract a shell yet"?
**Resolved.** The brief gates shell extraction on a second UI-bound surface existing. `COMPANION_UI_STATE_MAP.md` lists multiple shipped/dev-staging surfaces (orientation, active-note workspace, Vault Browser, Panel), so the precondition is met. The newer state-map and `SYSTEM_OVERVIEW.md` posture govern. The shell is presented as guidance, not as a contradiction of the brief. *(Triage: resolved; normalized spec should retire the stale brief sentence.)*

### Q2. Does the entry point assert any unshipped runtime behavior?
**Resolved.** The only endpoint it consumes as shipped is `GET /api/companion/orientation`, which is shipped per `WORKSPACE_ORIENTATION_CONTRACT.md` and `COMPANION_UI_STATE_MAP.md`. Everything else (the entry-point state enum, shell composition, Panel/Canvas/memory wiring) is framed as a proposal in `implementation-contracts.md`. No current-behavior claim is made without an in-folder owner-doc citation.

### Q3. Does any surface re-classify runtime or collapse Chat/Panel/Automation?
**Resolved.** Verified against `authority-boundaries.md`: the entry point renders server-declared class/posture/authority and never infers them; Chat (rail), Panel (palette), and Automation (named, separate lane) stay distinct; all durable mutations route through the governed pipeline (simulated).

---

## Resolve in the normalized spec

### Q4. Where does the system map "live" in production — a discoverable overlay, a first-run-only view, or both?
The prototype exposes it as an always-available overlay from the topbar and from cold-start states. Whether production keeps it always-available or surfaces it primarily on first contact is a spec decision. *(resolve-in-normalized-spec)*

### Q5. Default re-entry shape per gap, and the exact display-budget count.
`CONTINUITY_AND_DECAY.md` fixes the latency-ladder shapes; the orientation contract's FA-5 budget is parametric. The spec should fix the default `items_per_orientation_moment` and the soft-mist (15m–2h) treatment, which the prototype does not render. *(resolve-in-normalized-spec)*

### Q6. Posture: is the current posture ever server-declared, or always user-chosen in the shell?
`ATTENTION_MODEL.md` / `COGNITIVE_MODES.md` say cognitive mode is server-declared and UI-rendered, but the prototype lets the user switch posture locally as an emphasis control. The spec must reconcile "server declares cognitive mode" with "user shifts posture emphasis" — likely two distinct concepts that share a name. *(resolve-in-normalized-spec)*

### Q7. Palette reconciliation.
The design-system guide (warm/parchment/gold) and `colors_and_type.css` (cool blue-black/cyan) disagree. The spec should pick one and update the losing source. The prototype follows the CSS. *(resolve-in-normalized-spec)*

### Q8. Re-anchoring scope on `vault.pick`.
Opening a note from the Vault Browser re-forms the shell. The spec should confirm whether this re-issues orientation, only fetches the artifact workspace (`GET /api/companion/workspace?note_path`), or both, and what happens to an open Chat rail / staged suggestion across the re-anchor. *(resolve-in-normalized-spec)*

### Q9. Stale leave-point resume affordance.
`WORKSPACE_ORIENTATION_CONTRACT.md` defines `leave_point.status: stale | artifact_missing | degraded`. The prototype renders the present/absent/degraded cases; the precise resume affordance when the leave-point is stale (regenerate vs. open-anyway vs. block) needs spec copy aligned with `BLOCKED_AND_STALE_STATE_SPEC.md`. *(resolve-in-normalized-spec)*

---

## Defer to implementation issue

### Q10. Foreground ambient refresh.
ADR-0011 permits a default-off, client-initiated foreground refresh based on `meta.freshness` / `meta.stale_after`. Whether the entry point opts in, and the refresh cadence, is an implementation choice gated on `COMPANION_ORIENTATION_AMBIENT_REFRESH`. The design forbids it becoming a notification/urgency feed. *(defer-to-implementation-issue)*

### Q11. Narrow/portrait bottom-sheet snap points.
`OVERLAY_GRAMMAR.md` mentions a 3-snap-point bottom sheet. The prototype shows a single open state. Snap behavior and gesture handling are implementation detail. *(defer-to-implementation-issue)*

### Q12. Command-surface input grammar.
The Panel palette shows a command input and proposal list, but the actual command grammar (free text, slash-commands, fuzzy match) is not specified here. *(defer-to-implementation-issue)*

### Q13. Off-palette Panel staging shell migration.
`companion-app/panel_visual_shell.html` uses an ad-hoc theme. Migrating it onto the canonical tokens is mechanical and belongs to an implementation issue, not this design. *(defer-to-implementation-issue)*

### Q14. Keyboard map beyond `⌘K` / `Esc`.
The prototype wires `⌘K` (command surface), `⌘N` (capture), and `Esc` (dismiss overlay). A fuller keyboard model for an expert keyboard-first user is deferred. *(defer-to-implementation-issue)*

---

## Added in v2 (settings, read-back, context lane, capture, receipts)

### Q15. Agenda / calendar source for the Context lane. **(resolve-before-promotion of the context lane only)**
The time bands (previous / current / next) need a source. No owner-doc grounds a calendar integration, so the lane ships as a **placeholder**. Before the *context lane* is promoted (independently of the rest of this package), the spec must decide: real calendar integration vs. a manual agenda/daily note in the vault vs. both, and how agenda signals map to `resurface.candidates[].why_now`. **This does not block the settings/read-back/capture/receipts surfaces or the entry-point/shell core**, which are grounded. *(resolve-before-promotion — scoped to the context lane)*

### Q16. Location source + privacy posture. **(resolve-before-promotion of the place band only)**
Location focus is off by default and ships as a placeholder. Before promotion of the *place band*, the spec must decide the source (opt-in device location vs. manual place tags), the local-first privacy guarantees, and where place tags live in the vault. Same scoping as Q15 — does not block the grounded surfaces. *(resolve-before-promotion — scoped to the place band)*

### Q17. Capture target + governed write path.
Capture appends to "the vault inbox" via the governed path. The spec should confirm the inbox note convention, the exact governed write (does it reuse `queue_review`, a new bounded action, or a deterministic append?), and that captures never acquire app-owned task semantics (states, due dates). *(resolve-in-normalized-spec)*

### Q18. Quiet-hours / interruption semantics.
Settings exposes a quiet-hours control and the design states the context lane *never pushes*. The spec should define what quiet-hours actually dampens (ambient salience intensity only) and confirm it can never become a notification scheduler. *(resolve-in-normalized-spec)*

### Q19. Settings storage home.
`DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md` pins preference state to `WORKSPACE_STATE_CONTRACT.md`'s local-state home, never the vault. The spec should confirm the storage home and the per-surface-override + reset-to-canonical behavior. *(resolve-in-normalized-spec)*

### Q20. Read-back scope.
The prototype reads the document body. The spec should confirm what is read-back-eligible (body only? resurfaced cards? proposals?) and that mixed-language / missing-provider warnings surface before playback per `LOCAL_FIRST_TTS_CONTRACT.md`. *(defer-to-implementation-issue)*

---

## Added in v3 (entry-point unreachable / remote-access flow — design review for #2123)

Source: Claude Design full-flow review of #2123 (2026-06-17). The bounded #2123 fix (classify HTTP 503 `runtime_unavailable` and render the designed "Vault unreachable" state, suppress the setup form) proceeds independently; the questions below are the flow-level deltas surfaced by that review and are explicitly **not** Crossing-B blockers.

### Q21. "Service down" vs. "wrong device" are the same 503 to the UI but different problems to the human.
**Resolved.** The disambiguation shipped in #2129/#2124 (commit `daa804d8`). `_render_error_section` now renders `_render_wrong_device_state(...)` when the contract/runtime is unavailable **and** the page origin is remote (`_is_remote_page_origin`), instead of the plain "Vault unreachable" card — `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` — with coverage in `tests/companion_ui/test_workspace_vault_unreachable_banner.py` (`test_remote_origin_renders_wrong_device_state`, `test_form_suppressed_on_remote_wrong_device`). The remaining open thread is the durable proxy fix, tracked separately as Q22. *(Triage: resolved; normalized spec should reference the shipped wrong-device state rather than restating "UI cannot distinguish.")*

### Q22. Should the UI server proxy API calls so remote access works transparently?
Root-cause option behind Q21: rather than the browser calling the API origin directly, the companion UI server could proxy `/api/companion/*` to the runtime so a single reachable origin serves both. This removes the wrong-device failure mode entirely and is the durable fix; it is an architecture decision (UI↔runtime boundary), not a visual one, so it routes to an owner-doc/runtime issue rather than this design package. *(defer-to-implementation-issue — runtime/architecture)*

### Q23. Technical provenance is opt-in, not headline.
The raw API JSON (`trace_id`, `contract_version`, `error_kind`) must never be the headline of an error state. The headline is human-readable ("Can't connect right now"); the provenance line and trace ID belong in an expandable "Details" disclosure. Applies to every entry-point error state, not only the 503. *(defer-to-implementation-issue — folds into the #2123 render)*

### Q24. Setup-form suppression generalizes beyond the 503.
The vault-setup form is a false affordance whenever the runtime cannot process it: it must be suppressed in both the unreachable (503) and degraded-without-vault cases, and the operator/power-user surface (role selector, handoff/asset/template folders, settings flags) belongs in Settings, not on the first-contact entry screen. The entry point should ask one question — "where is your vault" — via a file picker, not a raw text input plus a wall of config. *(resolve-in-normalized-spec)*
