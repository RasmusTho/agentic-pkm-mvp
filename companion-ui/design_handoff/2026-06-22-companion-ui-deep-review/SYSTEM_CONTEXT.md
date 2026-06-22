# System Context — what the Companion UI is for

> Claude Design cannot open the repo. This file inlines everything needed to judge the UI
> against intent. Authoritative sources (for the implementer) are cited by path.

## The system in one paragraph

Yggdrasil is a **single-user cognitive prosthesis** built on a Markdown vault (Obsidian /
iCloud). An agentic runtime watches the vault, builds understanding, and proposes changes; the
human stays the author of record. The **Companion UI** is the human's window into that runtime:
it is where you re-enter your thinking after time away, read and make sense of notes, see what
the agent has noticed or proposes, and govern what the agent is allowed to do. It is **not** a
dashboard, not a chat app, and not a file manager — though it has to absorb pieces of all three
without becoming any of them.

## Who the user is

One person: a senior systems architect / product owner (the repo owner). Expert, thinks at the
system level, returns to the vault irregularly (minutes to weeks between sessions). He is the
*only* user, so the UI optimises for depth and trust over discoverability-for-newcomers. The
scarcest resource is his attention and his ability to **resume a train of thought** after an
interruption.

## The design philosophy the UI must serve

These are the intentions the review should judge against. (Owner docs:
`companion-ui/docs/COGNITIVE_PRINCIPLES.md`, `INTERACTION_PRINCIPLES.md`, `DESIGN_BRIEF.md`,
`OVERLAY_GRAMMAR.md`, `SYSTEM_ENTRY_POINT_SPEC.md`.)

1. **Anti-dashboard.** The front door must not greet the user with a wall of metrics, status
   tiles, or a governance console. On a cold return it should offer a calm way back in (the
   document + "see the map"), not a re-entry dashboard. Telemetry lives *behind* the System Map,
   never on the surface.
2. **The document is the primary surface.** Reading and sensemaking of long-form notes is the
   main act. Everything else (outline rail, Panel/agent rail, overlays) is secondary and must
   visibly defer to the note body.
3. **Calm / ambient re-entry.** When you return, the UI signals elapsed time and what changed
   through a graded "mist" ladder (from no cue at all, through a peripheral line, up to a
   re-entry card for long gaps) — proportional to how long you were gone. It should feel like
   picking up a thread, not reading a changelog.
4. **Server-authoritative classification.** The UI **never invents** authority, status, or
   classification. Entry state, trajectory, staleness, receipts, governance posture — all are
   declared by the runtime and rendered verbatim. The UI's job is faithful presentation, not
   judgement. (This is heavily enforced by tests; design proposals must not push classification
   into the client.)
5. **Governed action with receipts.** When the agent acts (move a note, add a tag, accept a
   memory), it goes through a governed pipeline and produces a **receipt**. Body-edit
   suggestions are a *separate, ungoverned* lane (apply/discard, no receipt). This asymmetry is
   intentional and must remain legible: the user should always be able to tell "did this change
   my vault, and is there a record?"
6. **One place to open things.** A single unified topbar + one overlay host. Every drawer/modal
   (command palette, capture, memory review, settings, vault browser, receipts, system map)
   opens into the same layer with the same dismiss grammar. (`OVERLAY_GRAMMAR.md`.)
7. **Quiet, legible states.** Empty / loading / degraded / blocked states are first-class and
   must inform without alarming. "Blocked" and "stale" present as held/guarded states, never as
   generic red errors. Degraded data is labelled, not hidden.

## The entry-state machine (front door)

The runtime resolves exactly one entry state before any HTML is emitted
(`docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md`):

- **boot** — handshake; never rendered to a page.
- **cold_start** — first contact, or returning after >14 days. **No re-entry overlay.** Offers
  the vault/document and "see the map" only.
- **orienting** — returning with a recoverable trajectory. Carries a **re-entry shape** on a
  latency ladder: `no_mist` (seconds) → `thread_fade` (minutes) → `soft_mist` (≤2h) →
  `full_mist` (hours–days, shows a re-entry card) → `long_mist` (7d+, card + delta strip +
  whisper column).
- **shell_active** — a document is open; the full working shell.
- **no_vault** — the runtime/vault is unreachable or no vault is selected; routes to a calm
  picker, never a fabricated success.

Cross-flags `degraded` (amber, false-affordance warning) and `stale` decorate
orienting/shell_active only.

## What "good" looks like here

A session should feel like: *open → instantly know where I am and what's changed → read →
optionally accept or direct the agent with full clarity about what will happen → leave a clean
thread for next time.* The review's job is to find where that loop breaks — in flow
(intuitiveness) or in build quality (implementation) — across the journeys in
`WORKFLOWS_TO_EVALUATE.md`.
