---
name: ASR Fallback Path
description: Captionless items fall back to the existing faster-whisper path and land as raw records differing only in acquisition_method
task_id: KA-02
source_anchor: "docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Transcript acquisition"
parent_capability: Knowledge Acquisition Phase 2 vertical slice
prerequisites: [KA-01]
depends_on: [ACQUIRE_YOUTUBE_CAPTIONS.md]
can_parallelize_with: [NORMALIZE_TRANSCRIPT.md]
---

# ASR Fallback Path

## Purpose

When KA-01 records a captionless item, transcribe it locally through the **existing**
`app/media/transcribe.py` chain (yt-dlp audio → ffmpeg → faster-whisper) and persist the result as
a `raw` record shaped identically to the caption path.

## What This Task Does

- Wires the captionless outcome to `transcribe_source()` (reuse, not rewrite; diarization hook and
  model cache stay as they are).
- The resulting `raw` record differs from a caption-path record **only** in
  `acquisition_method: asr` and its quality note; identity, provenance, immutability, and dedup
  semantics are byte-for-byte the same contract.
- ASR runs only as fallback — never when a usable caption track exists (audio download engages the
  full media anti-bot machinery; see research memo §3).

## Concretely

```
$ python -m app.cli acquire "<captionless URL>"
captions: none → asr fallback (faster-whisper base)
raw_record_id=… acquisition_method=asr language=sv
```

## Why This Matters

If the two paths produce differently-shaped records, every downstream stage forks on acquisition
method — exactly the divergence the normalized artifact exists to prevent.

## Acceptance Criteria

- [ ] Captionless item flows through `app.media.transcribe.transcribe_source` and produces a raw
      record with `acquisition_method: asr`.
      Verify: `tests/knowledge_acquisition/test_asr_fallback.py::test_captionless_falls_back_to_asr` (transcribe stubbed)
- [ ] Caption-path and ASR-path raw records validate against one schema, differing only in
      `acquisition_method` + quality note.
      Verify: `tests/knowledge_acquisition/test_asr_fallback.py::test_raw_record_shape_parity`
- [ ] ASR is never invoked when a usable caption track exists.
      Verify: `tests/knowledge_acquisition/test_asr_fallback.py::test_no_asr_when_captions_exist`

## How to Verify (Pre-Merge)

- `pytest tests/knowledge_acquisition/test_asr_fallback.py -q` (transcribe + network stubbed)
- `ruff check app tests`

## Out of Scope

Changes to `app/media/transcribe.py` internals; diarization or model upgrades; translation.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md` §Transcript acquisition
- `docs/INVENTORY.md` (existing transcribe chain)

## Related GitHub Issues

One issue. TCD hint: Sonnet / medium (bounded wiring around an existing asset).
