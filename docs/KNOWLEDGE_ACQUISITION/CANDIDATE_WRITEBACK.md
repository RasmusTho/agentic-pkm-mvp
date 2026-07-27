---
name: Candidate Writeback
description: Assemble the candidate and write an authority-banded youtube_source_note companion artifact through governed vault mechanics
task_id: KA-05
source_anchor: "docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback"
parent_capability: Knowledge Acquisition Phase 2 vertical slice
prerequisites: [KA-04]
depends_on: [EXTRACTION_REGISTRY_AND_SUMMARY_EXTRACTOR.md]
can_parallelize_with: []
---

# Candidate Writeback

## Purpose

The pipeline's terminal stage: bundle the extraction(s) into a candidate and write the
`youtube_source_note` companion artifact into the vault through the governed write path. The
pipeline ends here; triage is human territory.

## What This Task Does

- Candidate assembly per `REFINEMENT_PIPELINE_CONTRACT.md` §`candidate`.
- Writes the note based on the shipped template with metadata + provenance frontmatter,
  `transcript_available`, owner-authored takeaways/open threads, one explicit
  `Proposals (non-authoritative)` wrapper, and deterministic evidence/lineage — through
  WriteGuard/governed vault-write mechanics (mechanical durable, non-authority-bearing write).
- Composes the delivered `summary@2` result through a pure proposal-section seam. Empty optional
  modules are omitted; a no-proposals marker replaces empty module headings.
- Parses generated Markdown before assembly and fails closed when visible prose falsely claims the
  note owner's belief, decision, takeaway, or approval, or when a visible heading impersonates one
  of the three authority bands. Invisible link destinations and valid reference definitions are not
  prose; visible link labels, code, image alt text, and Obsidian wikilink aliases are. The declared
  English families cover present, past, and present-perfect forms of `approve`, `believe`, and
  `decide` for both `you` and `the note owner`, plus `approved by you` and singular/plural
  `your takeaway(s)`. The corresponding direct Swedish families cover `du` plus the explicit
  `notägaren` / `notens ägare` / `anteckningsägaren` / `anteckningens ägare` forms, including
  singular/plural `slutsats(er)`. This is an authority lint, not a general style or claims-quality
  policy.
- Builds the lint projection with Unicode NFKC/case folding, removes the Unicode
  `Default_Ignorable_Code_Point` property before exact token-sequence matching, and expands the
  declared English present-perfect contractions. Every Unicode `Bidi_Control` character fails
  closed on frontmatter, proposal titles/content, evidence, and the final rendered artifact.
  Legitimate RTL prose and benign joiners such as emoji ZWJ remain renderable; Unicode confusable
  detection and semantic paraphrase classification are outside this exact declared lint.
- Constrains registered module titles to one line, rejects reserved or owner-attributing visible
  title text, escapes raw HTML in all title/evidence fields, and flattens evidence fields to one
  line. Source-controlled title, URL, and lineage values therefore cannot create raw-HTML or
  Markdown sibling bands.
- **Template extension shipped here**: adds the mandated posture markers
  (`authority.requires_review: true` + `review_state: draft`) to the template and the written
  note — token mapping per the #2793 owner decision (2026-07-02), cited in the spec's Writeback
  section.
- Never advances triage state; never touches any existing artifact's governance-bearing metadata.

## Concretely

```
candidate(raw=…, extractions=[summary@2]) → vault: Sources/<title>.md
frontmatter: artifact_class=youtube_source_note, requires_review=true, provenance{…},
transcript_available=true
body: Owner notes{Takeaways, Open threads}
      / Proposals (non-authoritative){Summary when present}
      / Evidence and lineage{source URL, content identity, acquisition method,
                             transcript status, deterministic coverage}
```

## Why This Matters

This is the only place the platform touches human-visible surfaces. A note written without posture
markers masquerades as reviewed knowledge; a write outside WriteGuard bypasses the vault-write
invariant ("WriteGuard gates all vault writes"). The explicit authority bands make the same
boundary visible inside the note: generated prose cannot occupy or impersonate the owner band.

## Acceptance Criteria

- [ ] Candidate note written through the governed vault-write path (enforced at the production
      call site — the writeback stage has no direct filesystem write).
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_write_goes_through_writeguard_callsite`
- [ ] Note carries the mandated posture markers, full provenance, and the template shape (incl.
      the extension delivered in this task); template file updated in the same PR.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_note_shape_and_posture_markers` + doc diff on `docs/examples/vault-templates/youtube-source-note.md`
- [ ] The written note enters the triage workflow at its initial state `captured`
      (`REFINEMENT_PIPELINE_CONTRACT.md` §`candidate`; slice AC6), and no triage advancement or
      mutation of any existing artifact occurs.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_triage_entry_is_captured_no_advancement` + `tests/knowledge_acquisition/test_candidate_writeback.py::test_no_existing_artifact_mutation`
- [ ] A candidate whose note write is blocked (WriteGuard denial fixture) is **not terminal**: the
      failure is item-scoped, loud, and the candidate remains re-runnable.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_blocked_write_is_loud_and_retryable`
- [ ] First-write-wins reruns preserve the owner-authored band byte-for-byte.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_preserves_human_authored_band_on_rerun`
- [ ] Generated module output appears beneath exactly one proposal wrapper, and absent modules emit
      no empty headings.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_composer_wraps_proposals_and_omits_absent_modules`
- [ ] Banned owner-authority phrasing fails closed before rendering.
      Verify: `tests/knowledge_acquisition/test_note_renderer.py::test_renderer_rejects_banned_generated_phrasing`
- [ ] Candidate completion is reported only after note materialization succeeds.
      Verify: `tests/knowledge_acquisition/test_candidate_writeback.py::test_candidate_is_terminal_only_after_note_materialization`

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_candidate_writeback.py tests/knowledge_acquisition/test_note_renderer.py` (temp vault fixture / pure renderer)
- Because this touches the vault-write path (shared/hot-path adjacent): run the full
  `pytest -q -m "not pg"` suite before PR, not targeted tests only.
- `ruff check app tests`

## Out of Scope

Human review UX; promotion; note updates on re-acquisition; claims, durable extraction or transcript
storage, new content modules, and the unresolved atomic-create bug tracked separately by #4132.

## Restart / Durability Posture

The note is durable (vault). Candidate assembly state is derived and re-runnable from `raw`; a
crash between candidate assembly and note write loses nothing durable — replay reproduces the
candidate, and the write retries idempotently (same note path, same content identity). Once the
candidate note exists, later attempts return `already_exists` before rendering or writing. The
entire file — including owner-authored takeaways and open threads — therefore remains byte-identical.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md` §Writeback
- `docs/YOUTUBE_SOURCE_NOTE_V2/COMPOSE_REVIEW_REQUIRED_PROPOSAL_NOTE.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` §3, §4.3

## Related GitHub Issues

One issue. TCD hint: Sonnet / high (vault-write invariant + partial-failure semantics; full
not-pg suite mandatory).
