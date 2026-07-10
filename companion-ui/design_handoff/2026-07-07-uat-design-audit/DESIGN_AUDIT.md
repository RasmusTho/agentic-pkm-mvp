# Companion UI — design audit

**Audited:** 2026-07-07 live UAT captures (dev channel, real runtime, Chromium 1440×900 unless noted)
**Against:** the design intent in `CLAUDE_DESIGN_AUDIT_PROMPT.md` + `UAT_REPORT.md`, and the Yggdrasil design system.
**Evidence:** screenshots `01`–`23` (+ degraded `00a`/`00b`), referenced by number throughout.
**Method:** each of the 24 captures was viewed and cross-checked against `findings.json` / `findings2.json`.

Constraint honored: every recommendation stays inside the existing visual language (dark, quiet, typographic). No dashboards, badges, or notification systems are proposed. Where possible the fix **removes or merges** rather than adds.

---

## 0. TL;DR — the shape of the problem

The product's *ideas* are sound and, in several places, beautifully executed. The **System Map** (`13`), **Help** (`14`), **palette** (`18`) and the **re-entry hero** (`01`) all demonstrate the calm, typographic voice the brief asks for. The problem is not vision — it is **leakage**: three surfaces let internal runtime state escape into the user's field of view, and one surface (the panel rail) never rests.

Three themes account for ~80% of the friction:

1. **Posture leakage & contradiction** — the same runtime health is described four different ways, twice in raw machine language, once as a *false* "initialize your vault" call to action. This is trust-critical. (`00a`, `00b`, `17`, `19`, `23`)
2. **The panel rail never goes quiet** — the resting state is a five-idiom telemetry stack. It fights note-primacy on every note view. (`17`, `23`)
3. **Provenance is present but illegible** — receipts carry the right data (path, time, hash) in the wrong form (absolute iCloud paths, bare hashes, verb always "logged"). The trust feature can't answer "what changed, where, why?" (`19`)

Everything else is layout hygiene (bottom-right collision, empty left rail), copy decoding, and two shell-dependent overlay bugs.

---

## 1. Journey verdicts

Verdict scale: **Works** / **Friction** / **Broken**, per axis. *Intuitiveness* = can a returning expert-but-rusty user understand it. *Implementation quality* = does it behave and render correctly.

| Journey | Intuitiveness | Implementation | Evidence | Note |
|---|---|---|---|---|
| **J1 Arrival** | Friction | Broken (when degraded) | `01`, `00a`, `00b` | Hero is calm and correct. But the degraded path (`00a`/`00b`) shows a false "Initialize this vault" CTA and raw `[Errno -2]`. Trust-critical. |
| **J2 Read / navigate** | Friction | Friction | `17`, `03`, `23` | Note reads well and stays primary. Left outline rail is near-empty (`23`); right rail is loud (§2); vault browser uses emoji folder icons — a design-system violation (`03`). |
| **J3 Capture** | Works | Friction | `05`–`07` | Modal is clean, centered, writes correctly with an honest receipt ("written · Inbox/inbox.md"). But it **stays open** after save with the textarea re-focused — no exit cue (`07`). |
| **J4 Re-entry mist** | Works | Works (live state only) | `01`, `08` | The single live state ("Returning after a while") is exactly right in tone. Ladder E3–E9 not exercisable live — out of scope. One nit: the recency link points at last-*written* (`inbox`), not last-*worked-on*. |
| **J5 Palette / suggestion lanes** | Works | Friction | `18`, `09` | Palette copy is excellent and correctly distinguishes Panel from Chat (`18`). But ⌘K on the **orientation** surface does nothing (`09`) — overlay is shell-dependent (bug #4). Suggestion lanes idle / 0 proposals — not exercisable. |
| **J6 Governance: receipts / memory** | Friction | Broken (orientation) | `19`, `10`, `11`, `20` | Receipts render but are illegible (§3). Memory review is clean but empty. Receipts overlay **no-ops on the orientation surface** (`10`) while working in the shell (`19`). |
| **J7 Configure / understand** | Works | Friction | `12`, `13`, `14` | System Map and Help are the best surfaces in the product. But the Settings capture (`12`) shows the *orientation* screen, not a drawer — settings appears not to open from orientation, same shell-dependence as receipts. |

---

## 2. Calm audit — where the resting state leaks

The brief's core promise: *"the note being read is always primary; chrome, chips and rails must defer to it."* The single biggest violation is the **right panel rail at rest**.

### 2.1 The panel rail is telemetry, not calm (`17`, `23`) — worst offender

At rest, with zero proposals and nothing happening, the rail stacks **five different status idioms**, each demanding decoding:

- `PANEL · IDLE` + `No active Panel proposal` (boxed, cyan-outlined — reads as active/important, but says nothing)
- `ambient · peripheral`
- `Companion · active`
- `CANVAS — Disabled` + a 4-line paragraph explaining canvas is disabled by runtime config
- `PANEL — Panel ready · 0 proposals`
- `SUGGESTIONS — Suggestions are idle.`
- `FIND — unavailable` + 3-line explanation
- `REORIENT — 0 open loops · recall ▾`
- `RESURFACE — degraded` + a 5-line amber warning block
- `COMMITMENTS — No active commitments` + `commitments ok · 0 active · as of 2026-07-07T20:28:44+00:00`

That is **ten labelled status regions and ~40 words of machine prose to say "nothing is happening."** It reads like a monitoring dashboard — exactly what the brief forbids. The boxed, cyan-outlined "No active Panel proposal" is the loudest thing on the note view, drawing the eye *away* from the note.

**Fix (remove/merge):** collapse every idle lane to a single quiet line — label + one-word state, `--fg-3`, no box, no border, no explanatory paragraph. Expand a lane only when it has content (a proposal, a degraded state that is *actionable*). Target resting height: ~6 lines of dim text, no boxes. See mockup **Panel rail — at rest**.

### 2.2 Degraded state shouts at rest (`17`, `23`)

`RESURFACE degraded` renders a persistent 5-line amber block on a note the user is trying to read, for a condition they can't act on ("no candidate payload is actionable here"). Degradation belongs in **one** posture indicator (§3.1), not as a warning card homesteading the rail.

### 2.3 Absolute timestamps at rest

`commitments ok · 0 active · as of 2026-07-07T20:28:44+00:00` — a full ISO timestamp for an empty set. Relative time ("checked just now") or nothing at all. This is telemetry bleed.

**Calm verdict:** the rail is the one place the product breaks its own promise. Everything else rests acceptably (`01`, `08`, `12`, `16`).

---

## 3. Trust audit — do receipts, governance, posture earn trust?

### 3.1 Posture is described four times, and they contradict (`17`, `00a`, `00b`, `03`) — trust-critical

The same underlying runtime health surfaces as four independent, un-reconciled statements:

| Surface | Says | Screenshot |
|---|---|---|
| Topbar | `Niflheim · vault ok` (green dot) | `17` |
| Panel rail | `RESURFACE degraded — runtime reported degraded guard state`, `FIND unavailable` | `17` |
| Vault browser | `Niflheim/dev read-only fallback · filesystem index` | `03` |
| Governed capture | writes succeed, honest receipt | `07` |

Each is individually honest; **together they are incoherent.** A careful user cannot answer "is my vault OK right now?" — the topbar says yes, the rail says degraded, the browser says read-only, and writes work anyway. For a trust-critical, provenance-first product this is the most damaging finding after the false-initialize CTA.

Worse, when the API is actually unhealthy the entry surface (`00a`) claims the *live, initialized* vault "is not initialized yet — Initialize it to enable writes" with a prominent **Initialize this vault** button, and labels Niflheim generically as **"vault"** at `/app/vault`. Following that CTA on a degraded runtime invites the user to believe re-initialization is needed. And `00b` drops the mask entirely: `API ERROR — [Errno -2] Name or service not known — Retry`. Raw errno is never a user-facing state.

**Fix (single source of truth):** derive one posture value from the runtime guard state. Every surface subscribes to it; none describes degradation independently.
- Healthy → topbar `Niflheim · vault ok`, rail lanes quiet.
- Degraded → topbar shows the degraded posture; **one** calm line explains it in plain language ("Some features are paused while the vault reconnects."); the false Initialize CTA is impossible because posture, not a missing-vault heuristic, drives the copy.
- Never surface errno/DNS/guard-state strings. See mockups **Posture — one source of truth** and **Vault picker, corrected**.

### 3.2 Receipts are legible data in an illegible form (`19`) — worst governance offender

Every receipt row is:

```
logged
/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niflheim/settings/workflow.md   ← wraps 2 lines
2026-07-07T16:22:13.674198Z
9ee53fd2a8bb419baa80eac448b6fc5a                                                                     ← bare hash
```

Problems, in order of damage:
- **Verb is always "logged."** The ledger's whole job is to answer *what did the agent do* — appended? created? linked? "logged" answers nothing.
- **Absolute iCloud path** repeated verbatim on every row, wrapping over two lines. The meaningful part (`settings/workflow.md`) is buried mid-string after 80 characters of machine boilerplate.
- **Bare 32-char hash** with no label sits under every row as if it were content. It's an integrity handle; it belongs behind a disclosure.
- **No grouping.** Five writes from one governed run read as five unrelated events.

**Fix (Receipts v2):** verb + object first (`Appended to Inbox/inbox.md`), vault-relative paths, group rows by run with a run header, timestamp as relative + hover-for-absolute, hash collapsed behind a `⌄ integrity` disclosure. See mockup **Receipts v2**. This is the single highest-leverage change in the product.

### 3.3 What the trust model gets right (keep)

- **Two lanes stay visually distinct.** Body suggestions vs governed proposals are not confused anywhere in the captures.
- **Capture receipt is honest** (`07`): "written · Inbox/inbox.md" is exactly the right provenance grain — Receipts v2 should match *this*, not the other way around.
- **Memory guardrail copy is perfect** (`20`): "Unreviewed memory is not semantic authority." Terse, declarative, trustworthy. Model copy.
- **Read-only badge on the receipts overlay** (`19`) correctly signals the ledger can't be edited.

---

## 4. Hierarchy & layout

### 4.1 Bottom-right status collision (`21`, `22`, `23`) — renders at every width

A red/orange status string (`…disabled`, appears to belong to the channel / vault-settings area) renders **behind** the Map / History / Memory / Search / Settings / Help pill cluster at 1440, 1280 and 1024. Clipped and unreadable at every width tested. Two failures at once: (a) a status is allowed to collide with chrome, and (b) it's red — alarm color — for what looks like a benign disabled-feature note.

**Fix:** reserve a layout slot for that status so pills never overlap it, or move channel/vault-settings status into the Connection section of Settings. Downgrade from red unless it's genuinely an error. See mockup **Note shell chrome, corrected**.

### 4.2 The left outline rail spends width saying nothing (`23`, `15`)

At 1024 the left column is a mostly-empty dark strip holding a stray `|` caret and three dots — ~20% of the viewport width for no content. On a note with an outline it should hold the outline; on a note without one it should collapse, not sit empty.

**Fix:** collapse the outline rail to a thin gutter (or hide it) when the note has no headings; reclaim the width for the note.

### 4.3 Note-primacy holds where the rail is out of the way

At 768 (`16`) and on orientation (`01`, `12`) the note/hero is genuinely primary and calm. The primacy problem is *specifically* the right rail (§2) and the left-rail emptiness (§4.2) — not the core column.

### 4.4 Overlay grammar is consistent (keep)

Capture (`05`–`07`), palette (`18`), receipts (`19`), memory (`20`), System Map (`13`), Help (`14`) all share Esc/scrim dismiss, an ⓘ guidance toggle, and a close affordance. Good. The only break is *availability*: some overlays are shell-dependent (§5).

### 4.5 Marginalia input is clipped

"Leave a note for future-y[ou]" — the placeholder is cut off mid-word in every orientation capture (`01`, `04`, `08`, `12`, `16`). The input is too narrow for its own placeholder.

---

## 5. Bugs (verify, don't re-litigate — confirmed against captures)

| # | Bug | Evidence | Severity |
|---|---|---|---|
| B1 | Degraded runtime masquerades as "vault not initialized" with a false Initialize CTA; vault labeled generic "vault" @ `/app/vault` | `00a` | Critical (trust) |
| B2 | Raw `[Errno -2] Name or service not known` surfaced to user | `00b` | High (trust) |
| B3 | Bottom-right red status clipped behind pill cluster at all widths | `21`,`22`,`23` | High |
| B4 | `overlayHost.mount('receipts')` no-ops on orientation; works in shell | `10` vs `19` | High |
| B5 | Contradictory posture signals shown simultaneously | `17` | High (trust) |
| B6 | Settings appears not to open from orientation (capture shows orientation, not a drawer) | `12` | Medium |
| B7 | Capture modal stays open + textarea re-focused after successful save | `07` | Medium |
| B8 | Emoji folder icons (📥 📁 ⚙️) in vault browser + receipts paths — violates design-system "no emoji, ever" | `03`,`19` | Medium (brand) |

---

## 6. Copy audit — labels a returning user must decode

Rule applied: sentence case, plain verbs, no internal vocabulary, no telemetry. Proposed replacements are in the product's calm voice.

| Current | Where | Problem | Proposed |
|---|---|---|---|
| `PANEL · IDLE` | rail `17` | internal module + state idiom | *(collapse to one line)* `Suggestions — none` |
| `No active Panel proposal` | rail `17` | boxed, loud, says nothing | remove; implied by the line above |
| `ambient · peripheral` | rail `17` | pure jargon | remove |
| `Companion · active` | rail `17` | reassurance nobody asked for | remove |
| `REORIENT · 0 open loops · recall ▾` | rail `17` | 3 idioms in one line | `Recall — nothing open` |
| `RESURFACE degraded — runtime reported degraded guard state` | rail `17` | machine language, unactionable | fold into posture: `Resurfacing paused while the vault reconnects` |
| `FIND unavailable because no backend candidate payload is available yet` | rail `17` | "backend candidate payload" | `Search — nothing to suggest yet` |
| `commitments ok · 0 active · as of 2026-07-07T20:28:44+00:00` | rail `17` | ISO timestamp on empty set | `No commitments` |
| `logged` | receipts `19` | verb answers nothing | `Appended to` / `Created` / `Linked` |
| `/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niflheim/settings/workflow.md` | receipts `19` | absolute path, wraps | `settings/workflow.md` (vault-relative) |
| `Niflheim/dev read-only fallback · filesystem index` | browser `03` | internal fallback vocabulary | fold into posture; if degraded: `Browsing a read-only copy while the vault reconnects` |
| `The selected vault is not initialized yet. Initialize it…` | picker `00a` | false + destructive-feeling | driven by posture; healthy vault never shows this |
| `API ERROR — [Errno -2] Name or service not known` | entry `00b` | raw errno | `Can't reach the vault right now. Retrying…` |
| `Leave a note for future-y[ou]` | orientation | clipped placeholder | widen input; `Leave a note for future you` |

Copy that is already excellent and should be the model: System Map (`13`), Help (`14`), palette (`18`), memory guardrail (`20`), capture receipt (`07`), the re-entry hero (`01`).

---

## 7. Top 10 changes, ranked by leverage

Effort: **S** ≤ half-day · **M** ~1–3 days · **L** ~1 week+.

### 1. Posture: one source of truth — S/M · trust-critical
**Problem:** four surfaces describe runtime health independently and contradict (§3.1, B5); the degraded path invents a false "initialize" CTA (B1) and leaks errno (B2).
**Evidence:** `17`, `00a`, `00b`, `03`.
**Redesign:** one posture value from the guard state; all surfaces subscribe. Topbar chip is the single home for it. Degraded → one calm sentence, never errno, never a false CTA.
```
healthy   topbar:  ● Niflheim · vault ok        rail: (quiet)
degraded  topbar:  ◐ Niflheim · reconnecting    banner: "Some features are paused
                                                  while the vault reconnects."
```
**Effort:** S for the copy/routing, M if the guard-state plumbing is new.

### 2. Receipts v2 — M · highest single-surface leverage
**Problem:** legible data, illegible form — verb always "logged", absolute iCloud paths, bare hashes, no grouping (§3.2).
**Evidence:** `19`.
**Redesign:**
```
Run · governed capture · 2 min ago
  Appended to   Inbox/inbox.md            ⌄ integrity
  Linked        settings/workflow.md      ⌄ integrity
Run · vault sync · 14 min ago
  Created       Projects/…/README.md      ⌄ integrity
```
verb+object first, vault-relative, grouped by run, relative time (hover = absolute), hash behind disclosure.
**Effort:** M.

### 3. Panel rail resting state — M · biggest calm win
**Problem:** ten status regions + ~40 words to say "nothing is happening" (§2.1).
**Evidence:** `17`, `23`.
**Redesign:** each idle lane → one dim line (label + one word). No boxes, no paragraphs, no ISO timestamps. Lanes expand only on content.
```
Suggestions  none
Recall       nothing open
Search       nothing yet
Commitments  none
```
**Effort:** M.

### 4. Bottom-right status collision — S
**Problem:** red status clipped behind the pill cluster at every width (§4.1, B3).
**Evidence:** `21`,`22`,`23`.
**Redesign:** reserve a slot above the pills, or move the status into Settings › Connection. Downgrade from red unless it's a true error.
**Effort:** S.

### 5. Capture: close on save — S
**Problem:** modal stays open with textarea re-focused after save; no exit cue (§J3, B7).
**Evidence:** `07`.
**Redesign:** on successful write, auto-dismiss with a brief inline toast ("Captured to Inbox"), or show a single "Done" affordance. Keep the honest receipt.
**Effort:** S.

### 6. Fix shell-dependent overlays — M
**Problem:** receipts (and apparently settings) no-op on the orientation surface but work in the note shell (§J6/J7, B4, B6).
**Evidence:** `10` vs `19`; `12`.
**Redesign:** register the overlay host globally so ⌘K / Receipts / Settings behave identically on every surface.
**Effort:** M.

### 7. Left outline rail: collapse when empty — S
**Problem:** ~20% width for a stray caret and three dots (§4.2).
**Evidence:** `23`, `15`.
**Redesign:** show the outline when the note has headings; collapse to a gutter otherwise.
**Effort:** S.

### 8. Remove emoji from chrome — S · brand
**Problem:** 📥 📁 ⚙️ folder icons in the vault browser and receipts paths violate the design system's absolute "no emoji" rule (B8).
**Evidence:** `03`, `19`.
**Redesign:** replace with the design system's icon idiom (16px, stroke 1.5, `currentColor`).
**Effort:** S.

### 9. Recency link: last-worked-on, not last-written — S
**Problem:** "Open your most recent note" points at `inbox` (last write from the capture smoke test), not the note the user was actually thinking in (§J4).
**Evidence:** `04` (`inbox`) vs `01` (the real recent note).
**Redesign:** rank recency by last-*interacted*, excluding system/capture writes; show the note title, not the folder.
**Effort:** S.

### 10. Copy pass on the rail + degraded strings — S
**Problem:** internal vocabulary throughout the rail and degraded paths (§6).
**Evidence:** `17`, `00a`, `00b`, `03`.
**Redesign:** apply the §6 replacement table. Model the voice on System Map / Help / memory-guardrail copy, which are already right.
**Effort:** S.

---

## 8. Not covered live (needs fixtures / seeded state)

- Mist ladder E3–E9 (needs seeded leave/return timestamps) — design-handoff fixtures remain the reference.
- Populated suggestion / proposal lanes, blocked WriteGuard state, populated memory-review queue — runtime had 0 proposals / empty queue.
- Multi-device / LAN (Tailscale) pass.

---

## 9. Mockups

Hi-fi redesigns of the worst offenders, in the Yggdrasil visual language, are in `redesigns.html` (open it to compare before/after side by side on the canvas):

1. **Panel rail — at rest** (fixes §2, top-10 #3)
2. **Receipts v2** (fixes §3.2, top-10 #2)
3. **Posture — one source of truth** + **Vault picker, corrected** (fixes §3.1, top-10 #1)
4. **Note shell chrome, corrected** (fixes §4.1, top-10 #4)
