# State gallery — System Entry Point

Every state of the entry point and the unified shell. Each is reachable in `prototype.html` via the prototype control deck (scenario segment, `degraded` / `narrow` toggles) and in-shell affordances. Authority classes follow `COMPANION_UI_STATE_MAP.md §Cognitive-load state extension`; the class is server-declared and the UI must not infer it locally.

## A. Entry-point states (cold load and re-entry)

### A1 — Boot / runtime handshake
- **Posture:** loading. **Class:** Projection.
- Wordmark + single pulsing dot. Message moves from "Reaching runtime…" to the request label `GET /api/companion/orientation`.
- Resolves to one of A2–A6. If the runtime aggregate cannot be reached, resolves to A6.
- Deck: any scenario, during the first ~1.3s after `replay entry`.

### A2 — Cold start · first contact
- **Mode:** Reorient. **Class:** Projection. **Posture:** empty.
- `leave_point.status: absent`, no open loops, no changes. "Nothing is open yet." Two calm affordances: *Browse the vault*, *System map*.
- **System MUST NOT** manufacture activity or show a re-entry overlay.
- Deck scenario: `First contact`.

### A3 — Cold start · cold trajectory (> 14 days)
- **Mode:** Reorient. **Class:** Projection. **Posture:** empty.
- "No re-entry overlay." Copy states that re-entry for cold trajectories is through the vault and search; the surface offers no continuity claim it cannot back.
- Deck scenario: `Cold · 21d`.

### A4 — Returning with trajectory · full mist (2h – 3d)
- **Mode:** Reorient. **Class:** Projection. **Posture:** Recovery.
- The four fixed re-entry questions, with the trajectory title and `warm` state pill. Peripheral warm tint + gravity well + caret echo. Unresolved shown as counts with an *inspect* affordance (routes to memory review). Provenance line: `source: leave_point + open_loops + notable_changes · authority_role: derived · read-only`.
- This is the canonical re-entry shape.
- Deck scenario: `Returning · 2h`.

### A5 — Returning with trajectory · long mist (3d – 14d)
- **Mode:** Reorient. **Class:** Projection. **Posture:** Recovery.
- A4 plus: trajectory state pill reads `dormant`; a **delta strip** lists what changed (vault edits, agent-found context, a decayed branch); a right-margin **whisper column** stages four named items in.
- Deck scenario: `Returning · 5d`.

### A6 — No vault / runtime unreachable
- **Mode:** all. **Class:** Projection (degraded). **Posture:** degraded.
- Alert glyph, "Vault unreachable", provenance `runtime_unavailable · /api/companion/orientation · 503`. Reassurance that the vault (durable truth) is unaffected. Affordances: *Retry connection*, *Open system map*.
- **System MUST NOT** present a fresh successful snapshot; request-level unavailability is its own state (`WORKSPACE_ORIENTATION_CONTRACT.md §Runtime Unavailable`).
- Deck scenario: `Vault offline`.

### A7 — Degraded / partial orientation (cross-state on A4/A5)
- **Mode:** Reorient. **Class:** Projection (partial). **Posture:** degraded.
- HTTP 200 degraded snapshot: an amber banner names the missing source (`resurfacing_source_unavailable`) and the surface stays calm. The re-entry card still renders the sources that resolved.
- **System MUST NOT** alarm or substitute a local default for the missing slice.
- Deck: `degraded` toggle on top of `Returning · 2h` / `Returning · 5d`.

## B. Unified shell states

### B1 — Shell active · document anchor (rail closed)
- **Mode:** Find / Reorient / Act. **Class:** Canonical (note body) over Projection (chrome). **Posture:** carried from entry (Recovery), switchable.
- Topbar (wordmark, anchor pill, posture pill, Vault / Command / Map icons, vault-status dot). Document column primary with EB Garamond title, frontmatter block, body. A collapsed `chat` tab sits at the right edge with an unread badge. Residual ambient layer (caret echo, marginalia) persists after re-entry.
- Reached by **Resume** from A4/A5, or by any "open" action from A2/A3/A6.

### B2 — Shell active · Chat rail open
- **Mode:** canvas. **Class:** Local UI (rail) over Canonical (anchor).
- Right margin rail: Hugin thread, source link, composer. Chat can propose into the document; it cannot commit. Document stays primary and visible.
- Reached by the `chat` tab or `rail.open`. Narrow viewport renders this as a bottom sheet.

### B3 — Staged suggestion in the document (Canvas suggestion flow)
- **Mode:** Act · body-edit. **Class:** Proposal.
- An amber staged block inside the body: label, proposed text, diff hint, *Apply to note* / *Discard* / *Source*.
- **System MUST NOT** pre-apply or present the proposal as committed truth.

### B4 — Suggestion applied (body-edit lane)
- **Mode:** Act · body-edit. **Class:** Canonical (the edit is now document body).
- Block turns vault-green; shows `applied · vault-canonical` and `+1 paragraph · written via canvas_writer · no receipt`.
- **System MUST NOT** generate a Panel/governance receipt for a body edit.

### B5 — Command surface (Panel) · proposals available
- **Mode:** Act · governed. **Class:** Proposal.
- Command palette overlay: callout stating Panel ≠ Chat; a command input; governed proposals each tagged `governed`; one proposal tagged `blocked`.
- **System MUST NOT** confirm-all, infer a proposal by position, or blur stage/apply.

### B6 — Command surface · executing → receipt
- **Mode:** Act. **Class:** Confirmation → Receipt.
- On confirm: a toast "Executing via governed path… (WriteGuard)" then a receipt toast "Receipt · … · success" (vault-green receipt pill semantics).
- **System MUST NOT** imply the projection performed the write; the runtime did, through the governed path.

### B7 — Command surface · blocked (WriteGuard)
- **Mode:** Act. **Class:** Proposal held by a guard (per `BLOCKED_AND_STALE_STATE_SPEC.md`).
- Confirming the cross-note proposal yields a calm amber "Blocked — WriteGuard denied (outside note allowlist)" outcome.
- **System MUST NOT** present this as a generic error or conflate it with a policy/stale-hash block.

### B8 — Vault Browser (Find) open
- **Mode:** Find. **Class:** Projection (read-only).
- Left drawer: read-only callout, search field, note rows, a governed `queue_review` affordance. Selecting a note re-anchors the shell.
- **System MUST NOT** reclassify a note's zone locally or read/write vault files directly.

### B9 — Memory candidate review (Reorient seam) open
- **Mode:** Reorient. **Class:** Proposal (candidate).
- Right drawer: callout ("Unreviewed memory is not semantic authority"), one candidate with why-now and provenance, Accept (governed) / Defer / Reject.
- **System MUST NOT** treat the candidate as memory truth or auto-promote it.

### B10 — Source peek (provenance overlay)
- **Mode:** Reorient. **Class:** Projection (read-only).
- Small popover anchored near the contribution: source path, indexed time, a short provenance statement. Dismisses to the anchor.

### B11 — Cognitive posture switch
- **Mode:** all. **Class:** Local UI emphasis (server-declared cognitive mode is not overridden).
- Centered overlay listing the five postures with descriptions; the active one is marked. Selecting one logs a `posture.transition` with a carry-forward set and re-renders the shell chrome.
- **System MUST NOT** drop the anchor, provenance, or unresolved tension across the transition.

### B12 — System map (total system entry point)
- **Mode:** all. **Class:** Projection.
- Large centered overlay: front-door callout, the entry-point center node, and the eight surface nodes, each with mode and a "reached → returns" relation. Clicking a node routes to that surface.

## C. Responsive / device states

### C1 — Narrow / portrait
- The shell constrains to a phone-width column. Chat becomes a **bottom sheet** instead of a side rail (`OVERLAY_GRAMMAR.md`). The whisper column is suppressed. Overlays narrow to fit. All critical affordances remain reachable.
- Deck: `narrow` toggle (replicates the portrait media query in-page).

## D. Loading / transient
- Boot (A1) is the only blocking load. Within the shell, governed actions show transient toasts ("Executing via governed path…") rather than blocking spinners; the document stays interactive. Re-anchoring on note select is near-instant in the prototype and labelled with the `GET /api/companion/workspace?note_path` it simulates.

## E. Guidance layer (cross-cutting)
- **Off (default).** Every surface is terse and evidence-only: provenance, authority tags, receipts, tooltips. This is the everyday state for the established user.
- **On.** An `ⓘ` toggle (topbar, each overlay head, re-entry card) reveals the explanatory `.callout.guidance` blocks describing each surface and the re-entry model. For newcomers and handoff review.
- **Class:** Local UI. Persists nothing; carries no authority. State lives on `data-guidance` at the root. Reachable from any state via the `ⓘ` affordance.

## F. Setup, ambient context, and capture surfaces

### F1 — Settings (Local UI)
- **Mode:** all. **Class:** Local UI. Right drawer.
- Sections: Display (theme / text size / spacing), Listening · local TTS (modality / speed), Companion behaviour (guidance default, quiet hours / interruption), Connection · local-first (runtime posture, vault-binding owned by runtime). `byte-unchanged` mode tag; reset-to-canonical.
- **System MUST NOT** write any preference to the vault, route it through a save/projection endpoint, or let a display preference change the canonical Markdown hash. A `local-only render` badge appears on the document whenever a display preference diverges.

### F2 — Read-back (local TTS)
- **Mode:** Listening. **Class:** Local UI. Small per-surface control → plan popover.
- A `Listen` affordance on the document opens a SpeechPlan popover: normalized text preview, locale, provider/voice, cache status, segment count, "fenced code skipped". A `Play` action synthesizes.
- **System MUST NOT** autoplay, read a cleaned/summarized version, or route read-back through a mutation endpoint (save / Panel confirm / workspace update). Read-back happens only after a human action.

### F3 — Context lane · time (Reorient)
- **Mode:** Reorient. **Class:** Projection (read-only salience). Right drawer.
- Three quiet bands — **previous** (just-ended meeting → its open loop), **now** (current anchor; nothing to surface), **next** (upcoming meeting → the related note + open loops) — each with a why-now and provenance.
- **System MUST NOT** present these as tasks, escalate to urgency, badge, or push. Salience, not urgency; resurfacing, not notification. **Placeholder:** no calendar source is grounded in an owner-doc.

### F4 — Context lane · place (Reorient)
- **Mode:** Reorient. **Class:** Projection (read-only). Band within the context lane.
- When location focus is **off** (default): an opt-in prompt, framed local-first with manual place tags. When **on**: a "near X" salience card pointing at a relevant vault note (e.g. a shopping list).
- **System MUST NOT** track location without opt-in or treat proximity as urgency. **Placeholder:** no location source is grounded in an owner-doc.

### F5 — Capture (→ vault inbox)
- **Mode:** Capture. **Class:** Proposal → governed write. Top modal (`⌘N`).
- A textarea + "Capture to inbox". Session captures list below. For "things to take care of" not tied to a meeting.
- **System MUST NOT** become an app-owned task list: no due dates, no states the app manages, no nagging. Captures are vault intake, surfaced later only by relevance.

### F6 — Receipts / history (read-only)
- **Mode:** Act / Reorient. **Class:** Receipt. Top modal.
- A read-only list of governed outcomes (success / logged / blocked) with id, path, and timestamp.
- **System MUST NOT** invent a receipt; receipts are runtime-produced. This is history, not a control surface.

---

See `edge-states.md` for degraded/empty/blocked/narrow detail that does not fit inline, and `implementation-contracts.md` for the state enum and transition table these states map to.
