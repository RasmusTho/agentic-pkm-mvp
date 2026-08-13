---
name: Review Accept Journal
description: Zero-typing visual review surface (accept / edit-then-accept / dismiss) for the staged journal draft; acceptance promotes it to the day's canonical journal note through the governed write path and the engine never overwrites it thereafter
task_id: JRNL-04
source_anchor: docs/PANEL_AGENT.md :: AI-åtgärder
parent_capability: Conversational Journaling
prerequisites: [JRNL-03]
depends_on: [DRAFT_JOURNAL_ENTRY.md]
can_parallelize_with: []
---

# Review Accept Journal

## Purpose

JRNL-03 stages a candidate; nobody has looked at it yet. This task is the review moment where the owner turns a machine-authored-but-unowned draft into his own journal entry — with zero typing required to accept, following the same dyslexia-friendly, visual-pick discipline that governs every human-facing surface in this system (`docs/HUMAN-FLOWS.md` §0).

## What This Task Does

1. **Zero-typing accept.** The staged draft (JRNL-03) carries an in-note Panel `AI-åtgärder` acceptance checkbox (`docs/PANEL_AGENT.md`), the same convention already demonstrated in this repo's UAT fixture (`docs/examples/vault_test_seed/reflection-journal.md`). Checking the box is the entire acceptance action — no form, no typed confirmation.
2. **Edit-then-accept.** The owner may edit the draft's body directly in Obsidian before checking accept; the edited text is authoritative — acceptance promotes whatever text exists in the note at the moment of acceptance, not a cached pre-edit version (mirrors `EXPANSION_CONNECT_AND_CREATE.md` §2.2's "human edits are authoritative; acceptance covers the edited text"). Editing is optional, never required — zero-typing acceptance of the draft as-is remains the default path.
3. **Dismiss.** An unchecked "dismiss" affordance (or leaving the draft unaccepted past its staleness window) declines the candidate. Dismissal is recorded through the shared declined-proposal ledger mechanism (`EXPANSION_CONNECT_AND_CREATE.md` §3) rather than a new per-capability decline store — reuse, not reinvention.
4. **Acceptance promotes through the governed write path.** Checking accept moves/promotes the staged draft to the day's canonical journal note (recommended default `vault/1_Calendar/Daily/YYYY-MM-DD.md`, matching the vault's existing `1_Calendar/Daily` folder convention; the destination is correctable by the owner via the checkbox label, same pattern as Create's own destination hint) through `WriteGuard`, stamping `authority_state: accepted`, `accepted_by: human`, `accepted_at`, and `acceptance_receipt_id` (the same frontmatter fields `docs/FRONTMATTER.md` already defines for Create's acceptance path) while preserving `derived_by: conversation` and the full `sources` list permanently. An `journal.entry.accepted` receipt links draft → final note → sources.
5. **The engine never overwrites an accepted entry.** Once promoted, no task in this capability may mutate the accepted note's body. A later same-day reflection session (JRNL-02 → JRNL-03 run again) produces only an **addendum candidate**, reviewed and accepted independently by this same task — acceptance of an addendum **appends** to the existing entry rather than replacing it; the append variant's checkbox label states plainly that it will append to the already-accepted entry, so the tap itself is the informed confirmation for that higher-trust variant (a modify-existing-note action, `ask-you` tier per `EXPANSION_CONNECT_AND_CREATE.md` §2.4's ratified table — satisfied structurally by the explicit checkbox tap).
6. **Acceptance intent survives a blocked write path.** If WriteGuard is unhealthy/blocked at the moment of promotion, the checked box itself is already durable (it lives in the staged draft file, on disk, independent of promotion succeeding). The review surface must show an honest **"accepted, pending materialization"** state — distinct from both "not yet reviewed" and "fully materialized" — and a retry path re-attempts promotion without requiring the owner to re-click; the acceptance intent is never silently dropped.
7. **Every action is a tap/click affordance.** Accept, dismiss, and expand/read all require zero typing; only the optional edit-before-accept step introduces free text, and it is never required.

The canonical production registry watcher invokes
`app.journaling.review.process_journal_reviews_tick` on every cycle. It scans the vault-durable
journal candidate queue, processes checked actions, and automatically retries them; a checked
accept blocked by WriteGuard is rediscovered by a later healthy watcher tick without another tap.
`python -m app.cli journaling review-tick` exposes the same deterministic processor for an explicit
operator run, while `journaling review-status` projects one date without mutation. Authority
receipts use a dedicated `journal-review-outbox.jsonl` under the watcher state directory in
production (or `JOURNAL_REVIEW_OUTBOX_PATH` when configured), separate from the runtime index audit
log. Standalone callers default to `runtime/journal-review-outbox.jsonl` and must provision its
parent directory durably.

## Concretely

```
Companion surface, tonight's staged draft:
  [Read] shows the full first-person draft, provenance markers visible per clause
  [Accept] — tap → promotes to vault/1_Calendar/Daily/2026-07-07.md, receipt recorded
  [Dismiss] — tap → declined-ledger entry recorded, draft archived
```

WriteGuard blocked at the moment of the accept tap:

```
Owner taps [Accept]. WriteGuard is unhealthy.
Surface shows: "Accepted — waiting to save" (not "not yet reviewed", not silently nothing).
Next healthy tick retries promotion automatically; owner is not asked to tap again.
```

Second session, same evening, after acceptance:

```
JRNL-03 stages an addendum candidate for 2026-07-07.
Review surface shows: "Add to tonight's entry?" — tap [Accept] appends; tap [Dismiss] declines the addendum.
The original accepted entry's body is untouched either way.
```

## Why This Matters

If acceptance required typing, this surface would fail the owner it is built for. If a blocked write path could silently swallow a tap, the owner would eventually stop trusting that his acceptance "took" — the same class of trust failure `docs/DAILY_BRIEFING/README.md`'s fail-legible discipline and `docs/COMMITMENT_SURFACING/README.md`'s CI-2 both guard against, applied here to an acceptance action instead of a read. If the engine could ever overwrite an already-accepted entry, journaling would stop being a durable, owned record — it would become just another machine-editable surface, defeating the entire "ghost-writer drafts, owner owns" contract this capability exists to deliver.

## Acceptance Criteria

- [ ] AC1: accepting a staged draft requires zero typing — a single tap/click checkbox action promotes the entry. Verify: `tests/journaling/test_review_accept_journal.py::test_accept_requires_no_typing`
- [ ] AC2: editing the draft's body before accepting promotes the edited text, not a pre-edit cached version. Verify: `tests/journaling/test_review_accept_journal.py::test_edit_then_accept_promotes_edited_text`
- [ ] AC3: dismissing a draft records the decline through the shared declined-proposal ledger and does not promote anything. Verify: `tests/journaling/test_review_accept_journal.py::test_dismiss_records_declined_ledger_entry`
- [ ] AC4 (enforcement): acceptance promotes the entry through the governed write path (WriteGuard asserted at the production promotion seam), stamping `authority_state: accepted`, `accepted_by`, `accepted_at`, `acceptance_receipt_id`, and preserving `derived_by`/`sources` permanently. Verify: `tests/journaling/test_review_accept_journal.py::test_acceptance_asserts_guard_and_stamps_receipt_fields`
- [ ] AC5 (enforcement): once an entry is accepted, no code path in this capability can mutate its body; a later same-day draft is routed as a distinct addendum candidate instead. Verify: `tests/journaling/test_review_accept_journal.py::test_engine_cannot_overwrite_accepted_entry`
- [ ] AC6: when WriteGuard is blocked at the moment of an accept tap, the review surface shows an "accepted, pending materialization" state distinct from "not yet reviewed" and "fully materialized," and a later healthy retry completes promotion without requiring the owner to re-tap. Verify: `tests/journaling/test_review_accept_journal.py::test_blocked_write_path_preserves_acceptance_intent_and_retries`
- [ ] AC7: accepting an addendum candidate appends to the existing accepted entry rather than replacing any part of it. Verify: `tests/journaling/test_review_accept_journal.py::test_addendum_acceptance_appends_not_replaces`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/journaling/test_review_accept_journal.py
pytest -q tests/companion_ui -k journal
pytest -q -m "not pg"
```

If the companion UI renders via the pure `render_index_html` path, render to static HTML and visually confirm the three-state distinction (not-yet-reviewed / accepted-pending-materialization / fully materialized), per the companion UI local UAT pattern.

## Out of Scope

Assembling day context (JRNL-01), leading the conversation (JRNL-02), and generating the draft (JRNL-03) — this task only reviews and promotes; any bespoke editing UI beyond "edit the note in Obsidian" (markdown-first is the surface, matching `docs/EPISODE_RESOLUTION_ENGINE/RESPECT_HUMAN_RECUT.md`'s posture); mood/sentiment analytics on the accepted entry; multi-day rollups; a full settings-UI surface for the staleness/expiry window (code-level constant until the Settings Spine lands).

## Restart / Durability Posture

The staged draft, the checked/unchecked state of its acceptance checkbox, and any already-accepted journal note are all vault-durable — a restart at any point (before, during, or after a tap) loses none of this. JRNL-03 and JRNL-04 share one per-day lifecycle lock across the primary candidate, addendum candidate, canonical transition, and receipt-bound candidate retirement, so draft regeneration cannot erase checked intent or stage an addendum while primary acceptance is still reconciling. Canonical publication is atomic-or-absent; deterministic canonical/addendum evidence reconciles a receipt interrupted after publication; the receipt is atomically replaced, fsynced, reread, and proven before the candidate is conditionally moved from its visible queue name to a receipt-bound, scanner-inert archive. The archive is retained as recovery evidence instead of being unlinked through a replacement race. A restart therefore resumes from the checked or receipt-bound queue item and never requires a second owner action.

## Related Docs

- `docs/CONVERSATIONAL_JOURNALING/README.md` (capability spec, cross-task invariants — never-overwrite, addendum)
- `docs/CONVERSATIONAL_JOURNALING/DRAFT_JOURNAL_ENTRY.md` (the staged draft this task reviews)
- `docs/PANEL_AGENT.md` (`AI-åtgärder` checkbox mechanism, Normalized Decision-Surface Proposal Format)
- `docs/examples/vault_test_seed/reflection-journal.md` (existing UAT fixture for the in-note review-surface convention)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2.3–2.4 (staging → governed acceptance precedent, declined-proposal ledger §3)
- `docs/FRONTMATTER.md` (acceptance frontmatter fields: `accepted_by`, `accepted_at`, `acceptance_receipt_id`, `decision_token_ref`)
- `docs/COMMITMENT_SURFACING/RENDER_COMMITMENTS_IN_PANEL_UI.md` (read-only/fail-legible render precedent)
- `docs/HUMAN-FLOWS.md` §0 (zero-typing, visual-pick interface posture)

## Related GitHub Issues

One issue: `[Conversational Journaling] review-accept-journal: zero-typing accept/edit/dismiss, governed promotion, never-overwrite invariant`. `agent:blocked` until JRNL-03 merges.
