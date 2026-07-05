---
name: Normalize Transcript
description: Deterministic raw→normalized stage — rolling-cue dedup, timestamps, detected language, acquisition method, quality note
task_id: KA-03
source_anchor: "docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: normalized"
parent_capability: Knowledge Acquisition Phase 2 vertical slice
prerequisites: [KA-01]
depends_on: [ACQUIRE_YOUTUBE_CAPTIONS.md]
can_parallelize_with: [ASR_FALLBACK_PATH.md]
---

# Normalize Transcript

## Purpose

Turn any `raw` transcript record (caption VTT or ASR segments) into the one source-agnostic
normalized artifact all extractors consume. Deterministic, no LLM calls.

Caption-path parsing is VTT-only (`parse_caption_cues` matches VTT timestamp lines); the fetch
side (`youtube_plugin.py::_pick_track_url`, #2957) explicitly prefers a `vtt` track whenever one
is present so a caption-method raw record always carries a VTT-shaped `caption_body` in practice.
`json3`/`srv3` remain in the plugin's accepted-ext fallback list only as a last resort when no
`vtt` track exists at all; this stage does not parse either format today, so a caption record that
somehow lands here as `json3`/`srv3` still fails loud per the guard below.

## What This Task Does

- Implements the `normalize` stage per `REFINEMENT_PIPELINE_CONTRACT.md` §`normalized`: text
  segments with start/end times, detected language (marked as detected), speaker labels and
  chapter boundaries where available, `acquisition_method` propagated unchanged from the raw
  record, quality note.
- Auto-caption normalization: strip inline timing/styling tags, collapse consecutive duplicate
  lines, merge rolling cues sharing text into single segments with combined start/end (the yt-dlp
  #1734 pattern the spec names).
- Deterministic: same `raw` in → identical `normalized` out. Lineage stamps raw
  `content_identity` + stage version.

## Concretely

```
raw (captions_auto, 412 rolling cues) → normalized (208 segments, no duplicated lines,
language=en detected, acquisition_method=captions_auto)
```

## Why This Matters

Rolling-cue duplication silently doubles every line an extractor or chunker sees; a
non-deterministic normalizer breaks the replay invariant the whole pipeline is built on.

## Acceptance Criteria

- [ ] Rolling auto-caption fixture normalizes with zero consecutive duplicate lines and preserved
      timestamps.
      Verify: `tests/knowledge_acquisition/test_normalize.py::test_rolling_cue_dedup_preserves_timestamps`
- [ ] ASR-path raw records normalize through the same code path to the same schema.
      Verify: `tests/knowledge_acquisition/test_normalize.py::test_asr_and_caption_paths_share_schema`
- [ ] Determinism: normalizing the same raw record twice yields identical output.
      Verify: `tests/knowledge_acquisition/test_normalize.py::test_normalize_is_deterministic`
- [ ] Language is recorded as detected (never asserted), `acquisition_method` propagated
      unchanged.
      Verify: `tests/knowledge_acquisition/test_normalize.py::test_language_detected_and_method_propagated`

## How to Verify (Pre-Merge)

- `pytest tests/knowledge_acquisition/test_normalize.py -q` (pure fixtures, no network)
- `ruff check app tests`

## Out of Scope

Semantic processing of any kind; chunking/embedding (#2314 W3); translation; sentence
reconstruction beyond cue merging.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` §`normalized`, §Lineage and replay
- `docs/KNOWLEDGE_ACQUISITION/RESEARCH_2026-07.md` §3 (rolling-cue mechanics)

## Related GitHub Issues

One issue. TCD hint: Sonnet / medium (deterministic transform with fixture-driven tests).
