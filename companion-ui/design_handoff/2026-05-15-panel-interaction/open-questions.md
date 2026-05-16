State: Handoff package governance doc — open questions for the 2026-05-15 panel interaction design. All questions triaged; no crossing-B-blocking items confirmed resolved yet.

# Open Questions — Panel Interaction Design

**Package:** `companion-ui/design_handoff/2026-05-15-panel-interaction/`
**Crossing status:** A

Triage categories (per `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md §Maturity checklist`):
- **Resolve-before-promotion** — must be resolved before this package can reach Crossing B.
- **Resolve-in-normalized-spec** — can proceed to Crossing B with proposed defaults; normalized spec must nail down the answer.
- **Defer-to-implementation-issue** — safe to leave open until a bounded implementation issue takes it up.

---

## Q1 — Panel surface placement

**Question:** Is the Panel widget rendered inline with the active note (appearing when a panel fence is detected), or as a persistent sidebar/overlay?

**Proposed default:** Inline with the active note — Panel widget appears when a panel fence is detected in the active document, rendered in relation to the note content, not as a persistent sidebar that exists for notes without a panel fence.

**Why it matters:** Determines whether the Panel surface is an overlay (per `companion-ui/docs/OVERLAY_GRAMMAR.md`) or an in-document affordance. Affects how multi-panel notes are handled and how the Panel widget is dismissed or collapsed.

**Triage:** Resolve-in-normalized-spec.

**Owner doc:** `companion-ui/docs/OVERLAY_GRAMMAR.md` and the normalized spec for this package.

---

## Q2 — Companion UI → vault confirmation write-back path

**Question:** When the human confirms a proposal in Companion UI, what is the exact write-back sequence?

**Option A (checkbox + re-run):** Companion UI checks the vault checkbox for the confirmed proposal (via `PATCH /api/notes/{id}` or equivalent) and triggers a new PanelAgent run. Confirmation happens through the normal watcher/CLI run path.

**Option B (dedicated confirm endpoint):** A dedicated API endpoint (e.g., `POST /api/panel/confirm`) marks the proposal as confirmed and triggers execution without requiring a separate note-save + watcher cycle.

**Proposed default:** Option B — a dedicated confirm endpoint is cleaner and avoids the race between writing the checkbox and triggering execution. However, this endpoint does not yet exist in the runtime, and creating it is a non-trivial implementation decision.

**Why it matters:** This is a blocking implementation dependency. Without a confirmed write-back contract, the Companion UI cannot implement the `confirming → executing` transition safely. The normalized spec must address this.

**Related invariant:** Whatever path is chosen, the vault must end up with the same artifact as if the human had checked the checkbox in Obsidian and run PanelAgent from the CLI. The vault is the source of truth.

**Triage:** Resolve-in-normalized-spec. **This is a primary normalized-spec deliverable.**

**Owner doc:** Normalized spec (`companion-ui/docs/PANEL_INTERACTION_SPEC.md`, pending) and runtime API docs.

---

## Q3 — How Companion UI detects panel run state

**Question:** How does Companion UI know when a watcher-triggered or explicitly triggered PanelAgent run has started and completed on the active note?

**Option A (polling):** Companion UI polls `/api/status` or a panel-state endpoint while the Panel widget is visible, on a short interval (~500ms).

**Option B (event subscription):** Companion UI subscribes to a server-sent event (SSE) or WebSocket stream and receives run-state transitions.

**Option C (panel-state endpoint):** A dedicated `/api/panel/state?note_uuid=...` endpoint returns the current panel state for the active note; Companion UI polls this while Panel widget is visible.

**Proposed default:** Option A (polling) — short-poll on active-note panel state while Panel widget is visible. This aligns with the existing polling posture of the Companion UI and does not require a new transport mechanism.

**Why it matters:** If the Companion UI cannot detect run state, it cannot transition from `running` → `proposals-staged` or `running` → `no-match` without a manual refresh. The `running` state would be invisible to the user.

**Triage:** Resolve-in-normalized-spec.

**Owner doc:** Normalized spec and runtime transport contract.

---

## Q4 — Multi-panel notes presentation

**Question:** A vault note may contain multiple AI panel fences. How does Companion UI present them?

**Option A (list):** All panel fences are rendered as a list of Panel widgets in document order, each with its own state.

**Option B (tabs):** Panel fences are presented as tabs; one active at a time.

**Option C (single active):** Only the panel with the most recent activity is shown as active; others collapsed.

**Proposed default:** Option A — a list in document order, each Panel widget with its own state. This preserves the vault-native multi-panel structure and avoids imposing an artificial active/inactive distinction.

**Why it matters:** Multi-panel notes are not a rare edge case. The design must not silently break for notes with multiple fences.

**Triage:** Resolve-in-normalized-spec.

**Owner doc:** Normalized spec.

---

## Q5 — Proposal provenance depth

**Question:** How much provenance does a proposal row show at a glance vs. on expand?

**Proposed default:**
- **Always visible:** catalog action label (human-readable name) + cognition mode badge (`rule` / `llm`).
- **On expand:** catalog action ID (machine ID, e.g., `promote.evergreen`), `llm_hint` text, confidence signal if available.

**Why it matters:** The `authority-boundaries.md` invariant states "provenance visible at confirmation time, not only in the audit log." The always-visible level must be sufficient for the human to understand the proposal's origin before confirming.

**Triage:** Resolve-in-normalized-spec.

**Owner doc:** This design and the normalized spec.

---

## Q6 — No-match and blocked state representation: vault side

**Question:** The AI status callout receives `⚠️ No match for: "..."` and `⚠️ Blocked: <reason>` entries when these states occur. Is the current callout format sufficient, or does the runtime need to emit richer structured data for the Companion UI to render the full no-match/blocked state?

**Proposed default:** The current callout format (`⚠️ No match for: "..."`) is sufficient for the vault-native surface. The Companion UI renders its `no-match` / `blocked` states from the runtime event payload (`panel.intent.executed` with `actions: []` and a reason field), not by parsing the callout text. The runtime must include a reason field in the event payload.

**Why it matters:** If the Companion UI parses callout text to derive state, it creates a brittle dependency on vault Markdown formatting. If it relies on event payload, the payload must include the reason.

**Open sub-question:** Does `panel.intent.executed` currently include a `no_match_reason` or `block_reason` field? If not, this is a runtime extension that must go through the events/owner-doc pipeline. **This must be confirmed during the normalized spec.**

**Triage:** Resolve-in-normalized-spec.

**Owner doc:** `docs/PANEL_AGENT.md §Event payload`, normalized spec.

---

## Q7 — Whether an internal runtime projection mechanism is needed

**Question:** Should the runtime emit a `<!-- companion:panel:run ... -->` HTML comment or equivalent structured projection into the vault note to communicate panel run state to the Companion UI?

**Context:** Some design patterns use inline annotations in the rendered document to carry state from the server to the UI client. This would be a vault write, which means it must go through the note writer / write guard path.

**Proposed default:** No. The Companion UI should derive panel run state from the runtime event stream or polling (see Q3), not from vault content mutations. Injecting runtime projection content into vault notes would contaminate the vault-native surface and violate the principle that vault artifacts remain readable in Obsidian with or without Companion UI running.

**Governing invariant:** The current vault-native panel syntax is the stable communication envelope. It is not being extended with runtime-projection annotations. See `authority-boundaries.md §On HTML comment run blocks`.

**Resolution:** This question is answered by policy: **no HTML comment run block is accepted as a vault communication channel**. If a future SoT decision reverses this, it requires an explicit owner-doc PR.

**Triage:** Resolved — no internal projection mechanism via vault content mutations. No further action needed.

---

## Q8 — Companion UI write-back and idempotency

**Question:** If the human confirms a proposal in Companion UI and the network call fails or is retried, what prevents double-execution?

**Proposed default:** Idempotency is owned by the runtime (write guard + `executed_action_ids` tracking per `docs/PANEL_AGENT.md §Runtime V1`). The Companion UI must present errors visibly and allow manual retry; it must not implement its own idempotency layer.

**Triage:** Defer-to-implementation-issue.

**Owner doc:** `docs/PANEL_AGENT.md §Runtime V1`, normalized spec.

---

## Summary table

| # | Question | Triage | Crossing-B blocking? |
|---|---|---|---|
| Q1 | Panel surface placement (inline vs. sidebar) | Resolve-in-normalized-spec | No |
| Q2 | Companion UI → vault confirmation write-back path | Resolve-in-normalized-spec | No (needed for implementation, not Crossing B) |
| Q3 | How Companion UI detects panel run state | Resolve-in-normalized-spec | No |
| Q4 | Multi-panel notes presentation | Resolve-in-normalized-spec | No |
| Q5 | Proposal provenance depth | Resolve-in-normalized-spec | No |
| Q6 | No-match/blocked vault representation and event payload | Resolve-in-normalized-spec | No |
| Q7 | Internal runtime projection mechanism | **Resolved** — no HTML comment run block | N/A |
| Q8 | Confirmation idempotency ownership | Defer-to-implementation-issue | No |

**No crossing-B-blocking open questions** — Crossing B requires human review to confirm this assessment and sign off.
