---
name: Acquire YouTube Captions
description: Caption-first fetch for one explicit YouTube URL — metadata + captions into an immutable raw record with dedup identity
task_id: KA-01
source_anchor: docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Transcript acquisition
parent_capability: Knowledge Acquisition Phase 2 vertical slice
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Acquire YouTube Captions

## Purpose

The plugin `fetch` operation for one explicit URL: acquire metadata and captions caption-first and
persist them as the immutable `raw` record every later stage replays from. This is the platform's
first egress surface and the only YouTube-shaped code in the slice.

## What This Task Does

- Implements the `youtube_url` source plugin's required `fetch(item_ref)` per
  `SOURCE_PLUGIN_CONTRACT.md`: one yt-dlp invocation retrieves metadata (title, channel + id,
  publish date, duration, description, chapters, tags, language, thumbnail ref) and caption
  tracks (`--write-subs --write-auto-subs --skip-download`), original-language only, manual track
  preferred over auto-captions, with the PO-token provider plugin declared as a local dependency.
- Persists the `raw` record via StorePort with `content_identity` (content hash), full provenance
  (`source_kind: youtube_url`, url, creator, published, acquisition timestamp/method, plugin
  version), and immutability (a changed source yields a new record, never an overwrite).
- Dedup: re-fetching an unchanged item is a traced no-op keyed on
  `(source_kind, item_ref, content_identity)`.
- Egress posture and politeness sleeps exactly as declared in `YOUTUBE_SOURCE_SPEC.md` §Plugin
  identity. No captions available is a **normal outcome** recorded on the raw record (KA-02
  consumes it), not an error.

## Concretely

```
$ python -m app.cli acquire "https://www.youtube.com/watch?v=<id>"
raw_record_id=… content_identity=sha256:… acquisition_method=captions_manual language=en
$ python -m app.cli acquire "https://www.youtube.com/watch?v=<id>"   # same URL again
dedup: unchanged content_identity — no-op (trace emitted)
```

(Entry-point naming is illustrative; the implementing issue picks the real CLI/API surface.)

## Why This Matters

Every downstream stage's replay guarantee rests on this record's immutability and identity. If
dedup or `content_identity` is wrong, the vault fills with duplicates or replay diverges; if the
translated-track exclusion is missed, acquisition hits the 429-prone endpoint.

## Acceptance Criteria

- [ ] Explicit URL accepted; metadata + captions acquired caption-first with manual-track
      preference observable in `acquisition_method`.
      Verify: `tests/knowledge_acquisition/test_youtube_fetch.py::test_manual_track_preferred_over_auto` (yt-dlp stubbed with fixture caption tracks)
- [ ] Auto-translated caption tracks are never requested.
      Verify: `tests/knowledge_acquisition/test_youtube_fetch.py::test_translated_tracks_excluded` (asserts requested sub-langs against the stubbed invocation)
- [ ] `raw` record immutable with `content_identity`; re-running the same URL is a traced no-op.
      Verify: `tests/knowledge_acquisition/test_raw_record.py::test_refetch_unchanged_is_traced_noop`
- [ ] Changed upstream content yields a new `raw` record; the prior record is untouched.
      Verify: `tests/knowledge_acquisition/test_raw_record.py::test_changed_content_new_record`
- [ ] Captionless video produces a raw record marked captionless (normal outcome, no exception).
      Verify: `tests/knowledge_acquisition/test_youtube_fetch.py::test_captionless_is_normal_outcome`

## How to Verify (Pre-Merge)

- `pytest tests/knowledge_acquisition/test_youtube_fetch.py tests/knowledge_acquisition/test_raw_record.py -q` (all network stubbed; CI-safe)
- One manual receipt against a real URL from the dev machine (paste CLI output in the PR body) —
  network egress stays out of CI.
- `ruff check app tests`

## Out of Scope

ASR fallback (KA-02), normalization (KA-03), discovery/playlists/subscriptions (Phase 4), cookies
or private lists, any vault write.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md` (operation + identity semantics)
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md` (mechanism decisions + research grounding)
- `docs/KNOWLEDGE_ACQUISITION/RESEARCH_2026-07.md` §3 (PO-token facts; re-verify if stale)

## Related GitHub Issues

One issue. TCD hint: Sonnet / high (external-API surface, stubbing strategy matters).
