# CHANGELOG — Claude Design Package · 2026-05-14

## v2 · 2026-05-15 — Refinement pass

Focused tightening rather than redesign. The visual language, folder shape, and
authority-boundary architecture from v1 are unchanged.

### Added

- **New package 05 · Vault Action Layer / Agent Tool Authority.**
  Designs the 9-step action pipeline (`intent → classify → bound → policy → guard →
  idempotency → execute → receipt → event`), the 5-tier tool authority taxonomy (read-only,
  proposal, bounded write, governance-bearing, forbidden), the Obsidian/MCP-as-adapter
  boundary, and a concrete first action (`move_inbox_note_to_workbench`) with eight designed
  states. Linked to issue **#910**.
  - `companion-ui/design_handoff/2026-05-14-vault-action-layer/`

- **Root README · Implementation Intake Summary table.**
  Single table mapping each artifact to its repo issues, what may be implemented,
  what must not, architecture dependencies, and open questions. Designed so a repo
  maintainer can decide intake from a single read.

- **Root README · "What to import" / "What should become issues" / "What must remain
  design-only" lists.** Three short lists at the end of the README that complement the
  intake table.

### Tightened — Runtime Proof / Health Dashboard

- **New §03 · Three planes: evidence · status · action.** Names the three planes the
  dashboard renders and the invariant that they are never collapsed. Evidence = runtime
  values; status = posture the runtime declares; action = the single recommendation the
  operator explicitly triggers.
- **Explicit "no automatic repair" rule** with an anti-pattern callout. Every write-shaped
  affordance is the operator's explicit click; the dashboard never retries or escalates.
- **Receipt-link pattern.** Every dashboard number that represents *governed events*
  (proof runs, governance receipts, write-guard denials, dead-letters, watcher restarts)
  hovers/clicks to a receipt-id list. Numbers that are pure measurements (heartbeat ms,
  tick counts) do not link.
- Sections 04–10 renumbered to 05–11 to accommodate the new §03.
- All seven required states (watcher OOM, worker poison, stale heartbeat, proof not-yet-run,
  proof failed-but-actionable, healthy, write-guard active) confirmed already present in
  the v1 §05 state gallery (now §06).

### Tightened — Context Bundle Inspector

- **New §04 · Ranked candidates · compact mode · similarity is not authority.** Three
  refinements:
  - Visual distinction between **ranked candidates** (the retrieval list) and **selected
    context** (the bundle). Adds a faded ranked column rendered to the left of the included
    list, with included / excluded-visible / below-floor opacity tiers.
  - **Compact mode vs expanded provenance view** with a side-by-side mock and a per-concern
    table mapping which fields appear in which mode. Compact emits `bundle.expand` to
    transition; never auto-expands.
  - **Semantic similarity is not authority** invariant callout with concrete UI rules: a
    high-score artifact in a `may_write: false` bundle still shows no apply affordance;
    score is never rendered as a colour judgment.
- Sections 04–10 renumbered to 05–11 to accommodate the new §04.
- `may_write=false` default for retrieval bundles confirmed already present in v1 §03 and
  §05 state gallery.

### Tightened — Memory Candidate Review Queue

- **Persistent in-UI authority banner.** A gold mono banner now sits between the queue
  bar and the candidate list in the live prototype:
  *"Unreviewed memory is not semantic authority. Candidate-state items in this queue
  cannot be recalled into answers, orientation, or write proposals. Authority activates
  only on accept or promote."* Persistent, never collapsing, never animating.
- **New §04 · Queue posture &amp; anti-inbox mitigations.** Names nine explicit
  mitigations against queue anxiety: pull-not-push, defer-as-first-class,
  auto-archive-expired, pacing throttle on inferred candidates, default-action-by-confidence-band,
  opt-in batch mode, reject-preserves-trail, operational-only as first-class outcome,
  promote-is-rare-and-visible. Includes an anti-pattern callout against shell-level
  notifications.
- Sections 04–09 renumbered to 05–10 to accommodate the new §04.

### Tightened — Handoff Governance Pack

- No structural changes. The pack's role expanded (it now governs five sibling packages),
  but its content is unchanged from v1.

### Tightened — Claude Design Package index

- **New 5th package card** (vault action layer) added to `index.html` §01.
- **Implementation Intake Summary section** added to `index.html` §00, linking through to
  the canonical table in the root README.
- Summary stats updated: 5 packages, 45 UI states designed, 35 handoff docs.
- Dependencies diagram in §02 extended to include `VAULT_ACTION_LAYER_CONTRACT` (future
  owner-doc) and re-attributed read-only references.
- "What this feeds" table extended with row 05.

### Unchanged

- The shared design system (`colors_and_type.css`, `spec_chrome.css`) is unchanged.
- The authority-boundary architecture is unchanged: design proposes, does not promote;
  runtime truth lives downstream; gated execution honored everywhere.
- All four v1 prototypes' state galleries are unchanged — the brief's per-state requests
  (watcher OOM, worker poison, conflict state, promoted-to-Markdown, etc.) were already
  covered in v1.
- Owner-docs are unchanged. This package modifies none.

---

## v1 · 2026-05-14 — Initial release

Four governed handoff packages plus an index:

- Design Handoff Governance Pack
- Runtime Proof / Health Dashboard
- Context Bundle Inspector
- Memory Candidate Review Queue
