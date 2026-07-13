---
name: Respect Human Re-cut
description: Markdown-first re-cut — editing the Episode note IS the re-cut (merge/split/re-time/re-label/re-bind); the engine treats human edits as terminal for machine mutation and reconciles bindings
task_id: ERE-07
source_anchor: docs/adr/ADR-0051-episode-as-ontological-primitive.md :: Decision §5 (opt-out segmentation)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-04, ERE-05]
depends_on: [TWO_STREAM_SEGMENTATION_CORE.md, ASSIGN_EPISODE_REF_TO_ARTIFACTS.md]
can_parallelize_with: [Emit Closure and Derive Decay, Gate Cross-Scope Fusion]
---

# Respect Human Re-cut

## Purpose

ADR-0051 §5: proposals stand by default; the only human action is a **re-cut**. This task implements the human side markdown-first (dyslexia-friendly: no forms, no path-typing — you edit the note in Obsidian) and pins the safety invariant: **the engine never overwrites a human's cut**.

## What This Task Does

1. **Re-cut surface = the Episode note.** Editing `time`, `title`, `goal`, `space`, `protagonists`, splitting into two notes, or merging (deleting one + widening the other) *is* the re-cut. The vault watcher already emits the change; the ERE tick detects an operator-authored edit to an episode note and sets `segmentation: re-cut`.
2. **Acceptance-by-silence**: a `proposed` episode transitions to `accepted` when its first *post-proposal* human interaction elsewhere passes without a re-cut, or after a declared quiet window (named constant) — silence is acceptance, no notification, no approval loop (UI control-action boundary #2475: no approval loops for proportional writes).
3. **Terminality for machine mutation**: once `accepted` or `re-cut`, the engine may **append** (new bindings, closure flips per ERE-06) but never mutate the five dimensions or the cut itself. New evidence that would re-shape a re-cut episode becomes a *new proposed* episode (or a proposed child via `parent_episode`), never an edit to the human's cut. This resolves RQ2 conservatively: a re-cut re-describes; the machine responds with new proposals, not identity surgery.
4. **Binding reconciliation**: after a re-cut changes bounds, the next tick corrects affected `episode_ref` bindings (ERE-05's correction path): artifacts now out-of-bounds are unbound (back to `unbound` or re-bound to the sibling), all with provenance.
5. **Distinguishing writers**: engine-authored edits carry the write provenance of the ERE writer identity (per the multi-writer posture, ADR-0053/0056 line); an edit not authored by the engine is by definition an operator/agent re-cut. No heuristic content-diffing.
6. **Projection sync** (review fix, mirrors ERE-06's `app.episodes.closure._sync_projection_closed`): every relabel write echoes the note's full on-disk cut back through `write_episode_note`, so `app.episodes.assignment.read_candidate_episodes_for_scopes` / `app.episodes.closure.find_closable_episodes` (both readers of the `episodes` DB projection, not the vault note) would otherwise see a stale row after a re-cut. The relabel write path itself issues a targeted incremental `UPDATE` of every note-sourced column (`app.episodes.recut._sync_projection_row`) — never a full `rebuild_episodes_projection()` replay.
7. **Human body preservation**: the markdown body is part of the re-cut surface even though Episode semantics remain frontmatter-first. A body-only edit participates in the tracked baseline, becomes `segmentation: re-cut`, and every machine relabel carries a human-edited body through unchanged instead of regenerating the template over it. Generated canonical bodies remain free to refresh their derived labels/headings.
8. **Invalid is not deleted**: a canonical Episode-note path that still exists but is temporarily unreadable or schema-invalid is skipped for that tick without withdrawing bindings or forgetting its baseline. Merge-deletion withdrawal runs only when the tracked canonical path is actually absent; once a mid-edit note becomes valid again, its preserved baseline still detects and reconciles the human re-cut.

## Concretely

```
# Operator edits ep-2026-07-07-morning: changes time.end, removes one protagonist. Saves in Obsidian.
$ python -m app.cli episodes tick --json
{"recut_detected": ["ep-2026-07-07-morning"], "bindings_corrected": 3}
# Engine later gets new evidence overlapping this window → proposes ep-new, does NOT edit the re-cut note
```

## Why This Matters

Opt-out segmentation is only trustworthy if a human's correction is permanent. An engine that "fixes back" a re-cut destroys trust in the entire proposal posture and violates the proportional-governance deal that justified skipping the confirm gate.

## Acceptance Criteria

- [ ] AC1: an operator edit to a proposed episode note is detected and flips `segmentation: re-cut` (writer-identity based, not content-heuristic). Verify: `tests/episodes/test_recut.py::test_operator_edit_detected_as_recut`
- [ ] AC2 (enforcement): the engine's write path refuses to mutate dimensions/cut of an `accepted`/`re-cut` episode — asserted at the production write seam (attempted machine edit → rejected + logged, note untouched). Verify: `tests/episodes/test_recut.py::test_engine_cannot_overwrite_human_cut`
- [ ] AC3: new overlapping evidence after a re-cut yields a new proposed episode (or proposed child), never an edit of the re-cut note. Verify: `tests/episodes/test_recut.py::test_new_evidence_becomes_new_proposal_not_edit`
- [ ] AC4: re-cut bounds change triggers binding reconciliation with provenance (out-of-bounds artifacts unbound/re-bound). Verify: `tests/episodes/test_recut.py::test_recut_reconciles_bindings`
- [ ] AC5: acceptance-by-silence transitions `proposed → accepted` after the quiet window without any notification/approval surface. Verify: `tests/episodes/test_recut.py::test_silence_is_acceptance`
- [ ] AC6: split (one → two notes) and merge (widen + delete) fixture flows land in consistent state (no orphaned bindings, no dangling `parent_episode`). Verify: `tests/episodes/test_recut.py::test_split_and_merge_flows_consistent`
- [ ] AC7: a body-only human edit survives the quiet-window relabel path and is detected as a re-cut rather than overwritten by the generated body template. Verify: `tests/episodes/test_recut.py::test_body_only_human_edit_survives_quiet_window_relabel`
- [ ] AC8: an invalid-but-present Episode note neither triggers deletion withdrawal nor loses its tracked baseline; a later valid save is still detected against that baseline. Verify: `tests/episodes/test_recut.py::test_invalid_but_present_episode_note_does_not_trigger_deletion_withdrawal`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_recut.py
pytest -q -m "not pg"
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat   # vault write-path change
```

## Out of Scope

Any bespoke re-cut UI (markdown-first is the surface; a picker/visual surface is a future companion-UI concern); notification of proposals (silence-is-acceptance excludes it by design); RQ2's philosophical identity question beyond the conservative operational rule above.

## Related Docs

- [ADR-0051](../adr/ADR-0051-episode-as-ontological-primitive.md) §5; [ADR-0054](../adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) §4 (posture unchanged)
- `docs/testing/invariant-tests.md` §Vault multi-writer (ADR-0055) — writer identity/optimistic writes
- Proportional governance tiers (#1881); UI control-action boundary (#2475)

## Related GitHub Issues

One issue: `[Episode Resolution Engine] human-recut: markdown-first re-cut with engine-never-overwrites invariant`. Blocked until ERE-04/05 merge.
