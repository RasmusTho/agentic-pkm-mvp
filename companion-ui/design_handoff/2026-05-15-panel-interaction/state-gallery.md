State: Handoff package governance doc — state gallery for the 2026-05-15 panel interaction design.

# State Gallery — Panel Interaction Design

**Package:** `companion-ui/design_handoff/2026-05-15-panel-interaction/`
**Crossing status:** A

This file describes every declared Panel UI state: what the vault Markdown looks like in Obsidian at that moment, and what the Companion UI renders. The vault/UI correspondence is the core design claim.

---

## State: `idle`

**When:** Panel fence is present in the active note; no active run; no pending proposals.

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder

## AI-logg
%% AI:End %%
```
_(AI status callout may be absent or show only past receipts.)_

**Companion UI:**
- Panel widget visible, showing the `AI-instruktion` text.
- `AI-åtgärder` section is empty — no proposal rows shown.
- A "Run" or equivalent affordance is available.
- Composer input (if present) is enabled.
- No indicators, no receipt strip.

**Notes:** The `AI-åtgärder` section may be empty because no proposals have been generated yet, or because prior proposals were confirmed/discarded and the panel is clean.

---

## State: `running`

**When:** A PanelAgent run has been triggered (by watcher, by explicit Companion UI action, or by CLI) and is in flight.

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder

## AI-logg
%% AI:End %%
```
_(No vault change yet during this state.)_

**Companion UI:**
- `PanelRunningIndicator` shown (animated; reuse of canvas `ThinkingIndicator` or panel-specific variant).
- All interaction affordances disabled — cannot confirm, discard, or re-run while running.
- Optional: "Cancel" affordance to abort the run.

**Notes:** The Companion UI must transition out of this state when the run completes — to `proposals-staged`, `no-match`, or `blocked`. Run detection method is an open question (see `open-questions.md` Q3).

---

## State: `proposals-staged`

**When:** PanelAgent ran and wrote unchecked proposals into `AI-åtgärder` (PA2-FREEFORM path or proposal-generation path).

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder
- [ ] Make this note evergreen
- [ ] Add missing frontmatter: `tags`, `domain`
- [ ] Summarize for review

## AI-logg
%% AI:End %%
```

**Companion UI:**
- Panel widget shows a list of `ProposalRow` components, one per unchecked checkbox.
- Each `ProposalRow` shows:
  - Proposal label (human-readable catalog action label)
  - Provenance badge: catalog action ID + cognition mode (`rule` / `llm`)
  - Confirm affordance (button or keyboard shortcut)
  - Discard affordance (button or keyboard shortcut)
- The human can select proposals individually; a "Confirm selected" affordance submits the selection.
- **No "confirm all" or "accept all" affordance** — each proposal requires individual selection.

**Key invariant:** These proposals have not executed. Showing them in the Companion UI is not execution.

---

## State: `confirming`

**When:** The human has selected one or more proposals and is reviewing before submitting.

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder
- [ ] Make this note evergreen
- [ ] Add missing frontmatter: `tags`, `domain`
- [ ] Summarize for review

## AI-logg
%% AI:End %%
```
_(No vault change yet — selected proposals are not yet confirmed.)_

**Companion UI:**
- Selected proposals highlighted.
- Non-selected proposals visible but dimmed.
- "Submit confirmation" and "Cancel" affordances shown prominently.
- Other actions disabled to prevent mid-confirmation changes.
- Provenance still visible on selected proposals.

**Notes:** This state is a UI-local staging step before the write-back API call. The vault does not change until the Companion UI sends the confirmed proposals to the runtime.

---

## State: `executing`

**When:** Confirmed proposals have been submitted to the runtime; execution is in flight.

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder
- [x] Make this note evergreen
- [ ] Add missing frontmatter: `tags`, `domain`
- [ ] Summarize for review

## AI-logg
%% AI:End %%
```
_(Confirmed proposals have been written back as checked checkboxes by the runtime. Execution of the checked actions is now in flight.)_

**Companion UI:**
- `PanelRunningIndicator` shown (or a distinct executing indicator).
- Confirmed proposals shown as locked/committed (not dismissible).
- Non-confirmed proposals remain visible but passive.
- All other actions disabled.

---

## State: `receipt-displayed`

**When:** Execution complete; AI status callout has been updated by the runtime; executed checkboxes have been removed from `AI-åtgärder`.

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder
- [ ] Add missing frontmatter: `tags`, `domain`
- [ ] Summarize for review

## AI-logg
%% AI:End %%

> [!info]- AI status
> - ✅ Make this note evergreen (2026-05-15 17:30)
```
_(Executed checkbox removed; AI status callout updated.)_

**Companion UI:**
- `PanelReceiptStrip` shown with `✅` entry for the executed proposal.
- The proposal list is updated — confirmed+executed proposals removed; remaining unchecked proposals still shown.
- Receipt transitions to `idle` after a brief display period (~1.5s), or on explicit dismiss.

---

## State: `no-match`

**When:** PanelAgent ran; the `AI-instruktion` did not match any catalog action; `AI-åtgärder` remains empty; the runtime wrote a `⚠️` entry into the AI status callout.

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder

## AI-logg
%% AI:End %%

> [!info]- AI status
> - ⚠️ No match for: "Diagnose this note and propose safe next actions."
```

**Companion UI:**
- `PanelNoMatchState` shown (not silence, not an empty proposal list).
- Content:
  - Instruction text echoed (so the human can read what was interpreted)
  - Reason surfaced: "No catalog match found" or more specific reason if available
  - Next-step affordance: edit instruction and re-run, or view the action catalog
- `PanelReceiptStrip` may show the `⚠️` entry.
- Acknowledge affordance returns to `idle`.

**This is the most critical state to design correctly.** The `no-match` state is not silence. When PanelAgent ran and found no match, the human must be able to read what happened without any ambiguity. The prod-UAT evidence on 2026-05-15 showed this state as invisible — the Companion UI exists precisely to make it legible.

---

## State: `blocked`

**When:** A write guard, policy gate, or runtime constraint prevented execution. The runtime wrote a `⚠️ Blocked: <reason>` entry into the AI status callout.

**Vault Markdown (Obsidian):**
```markdown
%% AI:Start %%
## AI-instruktion
Diagnose this note and propose safe next actions.

## AI-åtgärder
- [ ] Make this note evergreen

## AI-logg
%% AI:End %%

> [!info]- AI status
> - ⚠️ Blocked: write guard active (WATCHER_AUTO_EXEC=0)
```

**Companion UI:**
- `PanelBlockedState` shown.
- Content:
  - Block reason displayed (write guard, policy, or operator setting)
  - Recovery path: how to resolve the block (e.g., operator must enable `WATCHER_AUTO_EXEC=1`)
  - "View details" affordance for full block context
  - Acknowledge affordance returns to `idle` without executing
- Proposals may still be visible but all action affordances are disabled.

**Notes:** Blocked is a first-class state, not an error. The human should be able to understand why execution was blocked and what to do next, without needing to read runtime logs.

---

## Future states (named for extensibility; not in scope for this design)

### `clarifying`

PanelAgent needs clarification before generating proposals. Renders a clarification prompt in the Panel widget; human responds before proposals are generated.

### `plan-staged`

A multi-step plan is staged; human reviews the step sequence before committing. Individual steps may have per-step confirm/discard affordances.

### `partial-complete`

Some proposals executed successfully; others failed or were skipped. Receipt strip shows mixed `✅` / `⚠️` entries; partial receipt is distinct from full receipt.

### `capability-needed`

A proposed action requires a capability (e.g., a connected tool, an enabled feature flag) that is not currently available. Companion UI surfaces what is missing and how to enable it.

---

## Coverage check (maturity checklist)

| State | Vault side described? | Companion UI side described? |
|---|---|---|
| `idle` | ✓ | ✓ |
| `running` | ✓ | ✓ |
| `proposals-staged` | ✓ | ✓ |
| `confirming` | ✓ | ✓ |
| `executing` | ✓ | ✓ |
| `receipt-displayed` | ✓ | ✓ |
| `no-match` | ✓ | ✓ |
| `blocked` | ✓ | ✓ |

All declared states covered. ✓
