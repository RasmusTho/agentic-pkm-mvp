---
name: Define Chat Artifact Durability
description: Close D-4 (runtime-semantics.md class 19) by giving the existing chat-session artifact class formal identity/mutation/canonicality/GC semantics, an explicit SBS ownership statement, and a registered note-relation type — without reopening the artifact-vs-provenance split already decided in DEFINE_CANVAS_COEDITING_MODEL.md
task_id: CANVAS-DURABLE-01
source_anchor: docs/architecture/runtime-semantics.md :: Divergences :: D-4
parent_capability: Canvas Chat Surface (Phase 5)
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Specification draft. Docs-only. Docs-authoring lane (no governing Issue required for this task per `AGENTS.md :: Docs authoring lane`; the follow-on implementation task is Issue-first).
Doc role: Spec (contract extension)
Authority: Specifies an extension of `docs/CONCEPTS/RELATION_TAXONOMY.md` (one new relation type) and `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` (the missing session/chat row) — **not yet landed in those owner docs as of this spec PR**; the actual table edits are this task's own deliverable, tracked as GitHub issue #2806, and are not complete until that issue merges. Until then, `RELATION_TAXONOMY.md` and `SBS_CURRENT_TO_TARGET_MAPPING.md` remain the current, unextended source of truth — a reader following those files directly will not yet find `chat_for`/`has_chats` or the session/chat row. Does not override `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` — see Reconciliation below.
Owner: v6.0 architecture owner
Last reviewed: 2026-07-02

# Define Chat Artifact Durability

## Purpose

Epic #2778 ratified D-4: "chat becomes its own artifact class... a chat is an artifact in its own
right, carrying a relationship to the note it belongs to... one note may have several chats attached
to it (note 1 : N chats)." PR #2803 (merged 2026-07-02) landed that ratification in
`docs/architecture/runtime-semantics.md`, which now states class 19's ratified home directly:
"a new artifact class, HKA-owned like class 1/3, related 1:N to its parent vault note via SIP" — an
independent confirmation of the SBS classification this task states below, arrived at before that PR
was read. `docs/architecture/runtime-semantics.md` class 19 records the gap this closes:
session/chat history is "not persisted at all (no table, no file)... lost on restart."

That framing is only half true. The canvas chat-session artifact already exists and already persists
(`vault/.chats/<note-slug>/<timestamp>-<label>.md`, `type: chat-session`, per
`DEFINE_CANVAS_COEDITING_MODEL.md`) — but it was never given the treatment every other durable HKA
artifact in this system has: WriteGuard-gated writes, a stated identity/canonicality/GC posture, and
a registered relation to the note it belongs to. This task closes that gap by extending the existing
contract, not by inventing a new one.

## What This Task Does

1. **States the five-question classification** for the chat-session artifact class, using the
   `docs/architecture/runtime-semantics.md` framework (identity, mutation, canonicality, replayability,
   GC), and records it as the closing entry for D-4.
2. **States explicit SBS conformance** — conforms/extends/reshapes, per the binding SBS-reconciliation
   rule (`.codex/skills/architecture-research/SKILL.md`).
3. **Adds one row** to `docs/CONCEPTS/RELATION_TAXONOMY.md`'s canonical relation table: `chat_for`
   (chat → note) and its inverse `has_chats` (note → chat), following the exact attribute-legend
   format already used by `companion_for`/`has_companion`.
4. **Adds the missing row** to `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` for session/chat
   history (today absent — confirmed by direct read, no existing row covers it).
5. **Names the schema completion**: the `type: chat-session` frontmatter (already SoT per
   `DEFINE_CANVAS_COEDITING_MODEL.md`) gains one new durable field, `note_uuid` (nullable on read, for
   pre-upgrade compatibility — see Task 2), alongside the existing human-legible `note: "[[title]]"`
   wikilink — the durable, rename-safe half of the relationship, mirroring the note-uuid +
   companion-note pattern already used everywhere else in this system
   (`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`). `DEFINE_CANVAS_COEDITING_MODEL.md` explicitly deferred
   "the exact session-log schema beyond the minimum fields" to a later slice — this is that slice.
6. **States the GC posture**: chat-session artifacts follow the owner-ratified D-6 posture (cold
   storage / tiering, not deletion) rather than the older "soft-deleted after a retention window"
   language in `DEFINE_CANVAS_COEDITING_MODEL.md` §Retention and Reversibility. That section is now
   superseded on the deletion mechanism specifically; the per-note disposition-follows-note-lifecycle
   principle is unaffected.

## Concretely

Before this task, a reader following the owner tables directly finds no trace of the chat artifact:

```
$ grep -n "chat_for\|has_chats" docs/CONCEPTS/RELATION_TAXONOMY.md
(no matches)
$ grep -n -i "session/chat\|chat.session" docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md
(no matches)
```

After this task merges, both resolve:

```
$ grep -n "chat_for\|has_chats" docs/CONCEPTS/RELATION_TAXONOMY.md
NN:| `chat_for` | Chat artifact belongs to this note (chat → note) | ... | frontmatter | ... |
NN:| `has_chats` | Inverse of `chat_for` (note → chat) | ... | frontmatter | ... |
$ grep -n -i "session/chat\|chat.session" docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md
NN:| Chat-session artifact | HKA (artifact), SIP (relation) | ... |
```

`docs/architecture/runtime-semantics.md` row 19 and its D-4 Divergences entry (already synced by
this same PR, see the review-fix commit) point at this file's classification table as the
canonical detail rather than restating it — a reader following either doc lands on one answer, not
two drifting ones.

## SBS Classification (binding statement)

Per the owner's SBS-reconciliation rule, every structural claim below states conform/extend/reshape
explicitly. **No reshape is proposed anywhere in this task.**

- **HKA (the artifact itself) — conforms, extends the artifact-class roster.** HKA's charter already
  covers "durable human-authored and human-accepted artifacts" and already carries one agent-maintained,
  own-artefact precedent in the companion-note family: commitment artifacts
  (`app/services/commitment_persistence.py`, `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`). The
  chat-session artifact fits that same shape — system-authored, vault-resident, companion-note-family,
  WriteGuard-gated. No change to the HKA boundary charter or contract is required
  (`docs/architecture/SBS_BOUNDARY_REGISTER.md` HKA row: charter yes, contract yes, enforced manual
  review now — unchanged). This adds one more artifact class under an existing, unmodified boundary.
- **SIP (the note-relationship) — conforms, extends the relation taxonomy.**
  `docs/CONCEPTS/RELATION_TAXONOMY.md` is an explicitly open, extensible table by design ("others are
  named here so that future link semantics have a contract to attach to rather than being smuggled
  into generic links"). Adding `chat_for`/`has_chats` is the intended extension mechanism, not a
  boundary change. Persistence is `frontmatter` (the durable `note_uuid` field), matching the existing
  `task_for`/`part_of` pattern — **no RelationIndex/`store_objects` registration is added** (see
  Out of Scope; this mirrors the commitment-artifact precedent, which is also frontmatter-only and
  glob-read, never ingested as a `store_objects` row).
- **No boundary is reshaped.** `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` Part 4's forbidden-dependency rule
  ("HIX directly writes HKA... is forbidden") is not violated by the *current* code
  (`app/chat/session_log.py` writes raw files, bypassing WriteGuard and any HKA-owned write seam) —
  it is actively curing a latent instance of that forbidden pattern. See
  `PERSIST_CHAT_ARTIFACT_THROUGH_WRITEGUARD.md` (this phase's Task 2).

## Reconciliation with DEFINE_CANVAS_COEDITING_MODEL.md (binding — read before implementing)

`DEFINE_CANVAS_COEDITING_MODEL.md` is the binding SoT for the canvas co-editing posture and states:
"The note: artifact... The session log: provenance... Not the full LLM response body — that is noise,
not provenance." It also rejects long-lived per-note chats explicitly so the chat log never becomes
"the document the user needs to consult" in place of the note.

D-4's "chat is an artifact in its own right" does **not** reopen that decision. Two distinct claims
must not be collapsed:

1. **Content authority** — which artifact is the durable source of truth for the *note's meaning*.
   This remains the note, unconditionally. Nothing in this task changes it.
2. **Governance status of the chat-session file itself** — whether the chat-session artifact is
   written, identified, and garbage-collected the way every other durable HKA artifact in this system
   is (WriteGuard-gated, KnowledgePort-routed, identity-stated, GC-stated), versus today's ungoverned
   raw file write. This is what D-4 closes, and what "artifact in its own right" means here: the
   chat-session file graduates from ungoverned exhaust to a governed HKA artifact class — the same
   status commitments already have — without becoming authoritative over the note's content.

Where the two documents differ is corrected in favor of the more specific, more recently ratified
decision: the `note: "[[title]]"`-only relationship becomes `note: "[[title]]"` + `note_uuid`
(rename-safe durable reference), and the retention mechanism moves from soft-delete to D-6's
cold-storage posture. Everything else in `DEFINE_CANVAS_COEDITING_MODEL.md` — the co-editing posture,
the authority split, the one-to-many cardinality, the `.chats/` location, the `type: chat-session`
classification field, the rejection of long-lived per-note chats — stands unmodified.

## Chat-Session Artifact Classification (closes D-4)

| # | Question | Answer |
|---|---|---|
| Identity | `session_id` (already assigned, UUID, `session_log.py:38`) + durable `note_uuid` reference (new field, this task) |
| Mutation | Append-only during an active session (turns), one terminal write on close; WriteGuard-gated. Authorized by user presence during the session, same as content co-authoring (`DEFINE_CANVAS_COEDITING_MODEL.md`'s Carve-out) — not a system-autonomous write; the canvas surface is the sole *code path* that performs the write, not an independent *authorizer*. See Task 2. |
| Canonicality | **canonical** for its own content (the intent-trail is not derivable from anything else); **not** canonical for, and never promoted to, the note's content |
| Replayable from | none — it IS the primary source of its own intent-trail; the note's content is never reconstructed from it |
| GC | D-6 posture: retained, tiered to cold storage as it ages past active relevance; never silently deleted; per-note disposition follows the note's own lifecycle (soft-delete/archive), consistent with `DEFINE_CANVAS_COEDITING_MODEL.md`'s per-note-disposition principle |

## Why This Matters

Without a stated identity/canonicality/GC posture, the chat-session artifact sits in the same
undefined space class 4 (`store_objects`) sat in before this research pass: alive in the vault,
invisible to WriteGuard, with no answer to "what happens on note rename" or "what happens on note
delete." A future implementer either (a) treats it as disposable exhaust and deletes it carelessly,
losing real user-visible intent-trail history, or (b) promotes it to note-content authority by
accident, recreating the exact "chat log becomes the document" failure mode
`DEFINE_CANVAS_COEDITING_MODEL.md` was written to prevent. Naming the classification now, before the
persistence-hardening implementation task, makes both failure modes structurally harder — the same
reasoning `DEFINE_CANVAS_COEDITING_MODEL.md` used for the co-editing posture itself.

## Acceptance Criteria

- [ ] `docs/CONCEPTS/RELATION_TAXONOMY.md`'s canonical relation table gains `chat_for` and `has_chats`
      rows with the full attribute set (authorship/authority/gov-bearing/rebuildable/persistence/
      retrieval/projection), consistent with the existing `companion_for`/`has_companion` pattern.
      Verify: doc presence — `docs/CONCEPTS/RELATION_TAXONOMY.md :: Canonical relation table` contains
      both rows.
- [ ] `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` gains a row for session/chat history naming
      HKA (artifact) and SIP (relation) as target owners, closing the gap this task's grounding pass
      confirmed (no existing row covers session/chat history).
      Verify: doc presence — `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` contains a
      session/chat-history row.
- [ ] This document states the five-question classification table above, consistent with the ratified
      class-19 entry in `docs/architecture/runtime-semantics.md` (PR #2803, merged 2026-07-02: "HKA-owned
      like class 1/3, related 1:N to its parent vault note via SIP").
      Verify: doc presence — this file's `## Chat-Session Artifact Classification` section.
- [ ] The Reconciliation section explicitly distinguishes content authority (unchanged: the note) from
      chat-artifact governance status (elevated), and states no reshape of
      `DEFINE_CANVAS_COEDITING_MODEL.md`'s artifact-vs-provenance split.
      Verify: doc presence — this file's `## Reconciliation` section.

## How to Verify (Pre-Merge)

All four ACs above are doc-presence checks; no test suite applies (docs-authoring lane, no code
change). Verify each on the PR's head SHA:

- `grep -n "chat_for\|has_chats" docs/CONCEPTS/RELATION_TAXONOMY.md` — both rows present, each
  carrying the full authorship/authority/gov-bearing/rebuildable/persistence/retrieval/projection
  attribute set (compare column-by-column against the `companion_for`/`has_companion` rows in the
  same table).
- `grep -n -i "session/chat\|chat.session" docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` —
  the new row is present and names HKA and SIP as target owners.
- Read this file's `## Chat-Session Artifact Classification` section and confirm it states all five
  columns (Identity, Mutation, Canonicality, Replayable from, GC).
- Read this file's `## Reconciliation` section and confirm it states, in so many words, that content
  authority stays with the note and only the chat artifact's governance status is elevated.
- Read `docs/architecture/runtime-semantics.md` row 19 and its D-4 Divergences entry and confirm
  neither still reads "not persisted at all" / "no table, no vault artifact" (the staleness this PR
  also corrects) and that both point at this file for the detailed classification rather than
  restating it.

## Out of Scope

- Implementing the WriteGuard-gated write path (Task 2, `PERSIST_CHAT_ARTIFACT_THROUGH_WRITEGUARD.md`).
- RelationIndex / `store_objects` registration for the `chat_for` relation. The commitment-artifact
  precedent is frontmatter-only and glob-read, never ingested as a `store_objects` row; this task
  follows that precedent rather than adding new ingest/embedding surface area. If a future need for
  graph-traversable chat↔note edges emerges, it is a separate, explicitly-scoped DRI task.
- Implementing D-6's cold-storage tiering mechanism. D-6 states the tiering mechanism itself is "a
  later design, not scoped now" (owner ratification, epic #2778) — this task only states that chat
  artifacts inherit that posture once it exists; it does not build a chat-specific GC mechanism ahead
  of the system-wide one.
- Reopening or re-ratifying D-4 in `docs/architecture/runtime-semantics.md` — PR #2803 (merged
  2026-07-02) already landed that ratification. This spec PR does carry one narrow, same-repo
  **fix-doc** correction (per that file's own fix-code/fix-doc/needs-owner-decision taxonomy): PR
  #2803 updated the Divergences prose and SBS-mapping bullet to say D-4 is ratified, but left the
  classification table's row 19 and the Divergences heading still reading "not persisted at all... no
  table, no vault artifact" — an internal contradiction within that single file, not a new decision.
  This task's classification syncs that row/heading to match the ratified text already present lower
  in the same file. The ratification's substance is unchanged.
- Editing `DEFINE_CANVAS_COEDITING_MODEL.md`'s co-editing posture, authority split, cardinality, or
  `.chats/` location/classification conventions — all stand unmodified.
- The `.canvas-sessions/` JSON pointer store (`app/chat/session_store.py`). That is active-session
  bookkeeping (which session is currently open, for CLI cross-process resume) — not the durable chat
  artifact. It stays out of WriteGuard scope; it is disposable local cache, reconstructible by scanning
  `.chats/` for the session's log file.

## Related Docs

- `docs/architecture/runtime-semantics.md` (class 19, D-4 — the divergence this task closes)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` (binding co-editing SoT — not reopened)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/CHAT_FAMILY_TAXONOMY.md`
- `docs/CONCEPTS/RELATION_TAXONOMY.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` (own-artefact precedent)
- `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`, `docs/architecture/SBS_BOUNDARY_REGISTER.md`
- `app/services/commitment_persistence.py` (structural precedent for Task 2)
- `app/chat/session_log.py`, `app/chat/session_store.py` (current implementation this task formalizes)

## Related GitHub Issues

Filed as #2806 (`agent:ready`), for tracking alongside Task 2 (#2807) even though this task did not
strictly require a governing Issue per `AGENTS.md :: Docs authoring lane`. Parent feature issue: #2805.
