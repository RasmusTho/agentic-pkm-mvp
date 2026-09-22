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

**This chain's health is bound to the `yt-dlp` pin (#5611).** YouTube changes its anti-bot behaviour
continuously, and a stale release silently stops being able to fetch media: the pin sat at
`2026.3.17` for six months, selected the `android_vr` player client, and every ASR media download
failed with `HTTP 403` while all unit tests stayed green. Treat a stale pin as the first suspect
whenever this path starts returning `403`, and re-verify with a real acquisition rather than tests.

Acquisition receipt, 2026-09-22, from the dev runtime image: with `yt-dlp 2026.8.19`, this path's own
production entrypoint `app/media/transcribe.py :: download_audio` fetched 18,791,294 bytes for video
`aircAruvnKk`, where `yt-dlp 2026.3.17` returned `HTTP 403` from the same host and image. Measured in
isolation, neither a PO-token provider server nor a JavaScript runtime was required for that download
to succeed; only the version differed.

**On the declared PO-token provider:** `youtube_plugin._PO_TOKEN_PROVIDER_EXTRACTOR_ARGS` names
yt-dlp's HTTP provider (`youtubepot-bgutilhttp`), and the plugin package is installed in the image,
but **no provider server is deployed in any channel**. The hook is therefore inert today rather than
load-bearing — YouTube is not currently challenging this path for a token. Deploying a provider is a
future change to make on evidence, not a standing requirement; note that the server image must match
the installed plugin's major version, which `:latest` did not.

## What This Task Does

- Wires the captionless outcome to `transcribe_source()` (reuse, not rewrite; diarization hook and
  model cache stay as they are).
- The resulting `raw` record differs from a caption-path record **only** in
  `acquisition_method: asr` and its quality note; provenance, immutability, and dedup **semantics**
  (unchanged re-fetch → traced no-op; changed content → new record, prior untouched) are identical
  to the caption path.
- ASR runs only as fallback — never when a usable caption track exists (audio download engages the
  full media anti-bot machinery; see research memo §3).

**ASR-path identity (decided in #2931 review round 1).** The ASR-path `content_identity` is
metadata-bound: it hashes the stable acquired signals (title, description, duration) plus an `asr`
method discriminator, and is computed — with the dedup store check — *before* the ASR chain runs.
The transcript itself is excluded from the hash because beam-search ASR output is
non-deterministic; a content hash over it can never satisfy `SOURCE_PLUGIN_CONTRACT.md`'s "fetch
MUST be idempotent". Accepted bound: an upstream audio re-upload with byte-identical metadata is
not re-acquired (undetectable without downloading the audio). If captions later appear on the
video, the caption path computes a caption-based identity → a new record → correct quality
upgrade, with the prior ASR record left untouched.

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
