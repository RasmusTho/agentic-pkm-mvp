# Workflows to Evaluate

This is the heart of the review. Instead of grading screens one by one, walk each **journey**
end to end and judge it on the two axes from `REVIEW_BRIEF.md`:

- **Axis A — Intuitiveness:** would the user know what's happening, where they are, and what to
  do next, without stopping to decode the UI?
- **Axis B — Implementation quality:** is the function actually built well — states complete,
  hierarchy correct, copy precise, affordances reachable, the right things emphasised?

For each journey: give a verdict per axis (Works / Friction / Broken), cite the specific
screenshots, and name the single highest-leverage change.

---

## J1 — First arrival & getting in

**Goal:** a user opens the Companion and gets to a usable state — whether it's their first time,
a return after weeks, or the vault isn't connected yet.

**Walk:** `entry_01_first_contact` → `entry_02_cold_21d` → `entry_10_no_vault` →
`entry_11_vault_picker` → (System Map as the backstop: `overlay_07_system_map`).

**Questions:**
- Is the way *in* unambiguous on first contact, with no history to lean on? Is there exactly one
  obvious next action, or does the calm/anti-dashboard posture tip into "empty and unclear"?
- After 21 days away (E2) the UI deliberately shows the *same* calm posture as a brand-new user
  (no re-entry overlay). Is that right, or does a 3-week returner need *some* "here's where you
  were" without it becoming a dashboard?
- no_vault (E10) vs the picker (E11): does the user understand the difference between "the
  runtime is down" and "no vault selected," and does each tell them what to *do*?
- Does the System Map genuinely function as the discoverability backstop that justifies how
  quiet the rest of the UI is?

---

## J2 — Read & navigate a note

**Goal:** open a note, read long-form, move to a related note.

**Walk:** `shell_01_active_anchor` → `overlay_05_vault_browser` → back to shell.

**Questions:**
- Is the note body unmistakably primary? Do the left outline rail and right Panel rail visibly
  defer to it, or do all three compete?
- Is the topbar legible and complete, or does it overload the top edge? (See OBSERVED_ISSUES #1:
  the right cluster is clipped at ≤~1440 — judge the *design* of that bar, not just the bug.)
- Is the vault browser a good primary navigator (filters, inspector, list density), or does it
  feel like a secondary utility bolted into the overlay layer?
- Does the read-only pill + "Edit" affordance make the read/write boundary clear?

---

## J3 — Capture a thought mid-flow

**Goal:** while reading, jot something to the vault inbox without losing the thread.

**Walk:** `shell_01_active_anchor` → `overlay_02_capture_modal` → (governed append) → back.

**Questions:**
- Is capture reachable in one gesture, and does it return you exactly where you were?
- Does the modal feel light enough to use mid-thought, or heavy enough that you'd avoid it?
- Is it clear the capture is *governed* (goes through the write pipeline), and is that
  reassuring or friction?

---

## J4 — Resume after time away (the re-entry mist ladder)

**Goal:** come back after a gap and recover what you were thinking, proportional to how long
you were gone. **This is the system's signature feature — judge it hardest.**

**Walk (the ladder):** `entry_03_no_mist` → `entry_04_thread_fade` → `entry_05_soft_mist` →
`entry_06_full_mist` → `entry_07_long_mist`; plus the off-nominal decorations
`entry_08_degraded_full_mist` and `entry_09_stale_leave_point`.

**Questions:**
- Does the *gradient* read as intended — a smooth increase from "no cue" to "full re-entry
  card," each step proportional to the gap? Or are the steps lumpy / hard to tell apart?
- At `full_mist` (E6): is the re-entry card a genuine "pick up the thread" affordance, or a
  changelog? Are resume vs dismiss both clearly available and clearly different?
- At `long_mist` (E7): card + delta strip + whisper column is the densest entry state. Does it
  stay calm, or does 7-days-away become the wall-of-information the philosophy forbids?
- Degraded (E8) and stale (E9): do these feel like honest, low-anxiety "held" states, or like
  something went wrong?

---

## J5 — See and act on what the agent suggests (body-edit vs governed lanes)

**Goal:** understand and respond to two *different* kinds of agent output, and never confuse
them.

**Walk:** `shell_02_staged_suggestion` (ungoverned body edit) vs `shell_03_panel_proposals`
(governed actions) and the palette form `overlay_01_command_palette`.

**Questions:**
- Can the user instantly tell a **body suggestion** (apply/discard, no record) from a **governed
  proposal** (apply → vault change → receipt)? The two lanes are intentionally asymmetric — is
  that asymmetry *legible*, or does it read as inconsistency?
- Apply / Discard / Defer on proposals: are three verbs the right set? Is "Defer" understood?
- Is the rail vs palette (O1) a helpful "same actions, faster surface," or a confusing
  duplicate path?

---

## J6 — Govern the agent: act, get a receipt, review history, handle blocks

**Goal:** direct an agent action and stay in control — including seeing the record and
understanding refusals.

**Walk:** `shell_03_panel_proposals` → `shell_04_governed_receipt` →
`overlay_06_receipts_history` → `shell_05_panel_blocked` → `overlay_03_memory_review`.

**Questions:**
- After acting (S4): is it obvious *that the vault changed* and *that a receipt exists*? Is the
  receipt pill enough, or does the user have to hunt?
- Receipts history (O6): is this a trustworthy "what has the agent done to my vault" ledger? Is
  it discoverable enough given how central trust is here?
- Blocked (S5): does a WriteGuard hold explain *why* and *what now*, without feeling like an
  error or a dead end?
- Memory review (O3): the governed accept/reject/revise vs non-terminal defer — is the
  decision boundary clear? *(Note: live queue is empty in capture; judge structure + copy, flag
  the populated state for live UAT.)*

---

## J7 — Configure & understand the system

**Goal:** adjust preferences and understand system status without leaving the calm surface.

**Walk:** `overlay_04_settings_drawer` → `overlay_08_guidance_layer` →
`overlay_07_system_map`.

**Questions:**
- Settings (O4): are these *clearly* render-only, never-touch-the-vault preferences? Is the
  grouping (Display / Listening / Behaviour / Connection) scannable and at the right altitude?
- Guidance layer (O8): off-by-default teaching callouts for an expert-but-intermittent user —
  right call? Is the ⓘ toggle discoverable, and do the callouts help or clutter?
- System map (O7): does it actually let the user find every surface and understand how they
  relate — earning the quietness of the rest of the UI?

---

## Cross-cutting passes (apply to every journey)

- **Visual hierarchy & calm:** across all states, does the note/primary act stay dominant, or do
  chips, pills, labels, and rails accrete into noise?
- **State completeness:** empty / loading / degraded / blocked / stale — are they all designed,
  consistent, and non-alarming? (E8, E9, S5, O3 are the test cases.)
- **Reachability:** are all the affordances the journeys rely on actually reachable at common
  laptop widths? (Tie to OBSERVED_ISSUES #1.)
- **Responsive integrity:** do the journeys survive the narrow layout (R1, R2), or do critical
  affordances get display-gated away?
- **Consistency of the overlay grammar:** do all overlays open/dismiss/title/scrim the same way,
  or do some feel like one-offs?
