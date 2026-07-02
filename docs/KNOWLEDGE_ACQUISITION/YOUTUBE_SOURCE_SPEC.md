State: Specification (docs-authoring; target-state framing). Not implemented; first source instance and Phase 2 vertical-slice definition.
Doc role: Source instance specification
Authority: Instantiates `SOURCE_PLUGIN_CONTRACT.md` for YouTube. Mechanism choices are grounded in `RESEARCH_2026-07.md` (mid-2026 verification). The triage flow for the resulting artifacts is owned by `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` §4.3; the artifact class by `LIFE_WIDE_ARTIFACT_TAXONOMY.md` (`youtube_source_note`).

# YouTube Source Specification

First implementation of the source plugin contract. Also the platform's proving workload: the
Phase 2 vertical slice below is the TCD milestone that must pass before any breadth (subscriptions,
scheduling, more sources) is built.

## Plugin identity

| Field | Value |
| --- | --- |
| `source_kind` | `youtube_url` — the value the existing `provenance.source_kind` vocabulary already uses (`ARTIFACT_METADATA_CONTRACT.md`, triage policy §4.3, the shipped template); no second identifier is introduced |
| `capabilities` | `captions` (v1); `discover`, `backfill` (Phase 4); `media` (audio, fallback path only). `fetch` is the required operation, not a capability |
| `egress_posture` | youtube.com + googlevideo.com; auth: none (logged-out); low volume (tens of items/week), politeness sleeps; PO-token provider plugin as a declared local dependency |
| `auth_degradation` | Everything in v1 works logged-out. Cookie-based private lists (Watch Later, Liked) are a Phase 4 *optional, degradable* capability with explicit operator opt-in — 2025–2026 posture: YouTube suspends accounts / bans IPs for logged-in automated access, so absence of cookies disables only that capability. |

## Transcript acquisition (caption-first, decided)

Per `RESEARCH_2026-07.md` §Caption acquisition — the 2026-controlling fact is that YouTube now
enforces PO tokens on the subtitle endpoint (`exp=xpe`, since ~May 2025), which only yt-dlp's
provider framework survives transparently:

1. **Primary: yt-dlp captions** — `--write-subs --write-auto-subs --skip-download`, original
   language(s) only (`sv`/`en`; auto-*translated* tracks are 429-prone and banned from the chain),
   with the `bgutil-ytdlp-pot-provider` plugin. Prefer the **manual** track over auto-captions
   when both exist. Politeness: `--sleep-requests` / `--sleep-subtitles` at low single-digit
   seconds.
2. **Fallback: ASR** — audio via yt-dlp, then the existing local faster-whisper path
   (`app/media/transcribe.py` is the reusable asset; see research memo §Existing assets). Used
   when no caption track exists or the caption track is unusable. Audio download engages the full
   media anti-bot machinery — another reason it is the fallback, not the default.
3. `youtube-transcript-api` is **not** in the chain: it cannot generate PO tokens
   (`PoTokenRequired`, open upstream with no workaround), so it fails on an unpredictable subset
   of videos where yt-dlp succeeds. Revisit only if upstream adds token support.
4. Commercial transcript APIs: excluded (cloud dependency for something achievable locally).

Auto-caption normalization (the rolling-cue problem — every line duplicated across overlapping
cues) is part of the `normalize` stage: strip inline timing/styling tags, collapse consecutive
duplicates, merge cues sharing text into single segments with combined start/end. The normalized
transcript records `acquisition_method: captions_manual | captions_auto | asr` — this source's
declared acquisition-method vocabulary per `REFINEMENT_PIPELINE_CONTRACT.md` §`normalized` — so downstream
consumers can weigh quality (manual > ASR > auto-captions, per the research memo).

## Metadata

Fetched with (not before) captions via the same yt-dlp call: title, channel + channel ID, publish
date, duration, description, chapters, tags, language, thumbnail reference. Metadata lands in the
`raw` record and drives the early rejection filters (language, duration, duplicate, ignored
channel) defined in the pipeline contract.

## Discovery (Phase 4 — decided mechanism, deferred implementation)

Per `RESEARCH_2026-07.md` §Subscription discovery, the hybrid with zero OAuth coupling:

1. **Bootstrap + periodic reconcile: Google Takeout** — `subscriptions.csv` (channel IDs/titles)
   and playlist CSVs (incl. Liked). Takeout is snapshot-grade: bootstrap and drift repair, not the
   live feed. Watch Later is absent from Takeout (removed 2020).
2. **Incremental: per-channel RSS/Atom feeds** — `videos.xml?playlist_id=UULF<channel>` (uploads,
   Shorts/live excluded) polled at relaxed cadence. No auth, no quota, ~15 most recent items per
   feed; the `discover` cursor is newest-published-seen per feed.
3. **Gap repair: yt-dlp `--flat-playlist`** logged-out, rare cadence (weekly/monthly), as
   `backfill` — catches anything past the RSS window. Convergent with what Pinchflat /
   TubeArchivist / ytdl-sub all landed on: cheap frequent incremental + rare full reconcile.
4. **YouTube Data API v3: not used.** Its only unique value over this stack is near-real-time
   Liked sync; it costs an OAuth consent flow + Google Cloud project upkeep, and it cannot read
   Watch Later at all (dead since 2016). Contradicts minimal-auth local-first posture.
5. **Watch Later**: reachable only via cookies (posture above). The in-system alternative — an
   explicit "queue for acquisition" action on the user's side — is preferred.

Explicit URLs and public playlist URLs need none of this and are the v1 entry points.

## Writeback

The candidate stage writes a `youtube_source_note` companion artifact based on the shipped
template (`docs/examples/vault-templates/youtube-source-note.md`): metadata + provenance
frontmatter, `transcript_available`, AI summary section marked non-authoritative, extraction
results as suggestion content.

The slice **extends** the template frontmatter with the initial non-authoritative posture markers
triage policy §3 mandates for AI-generated content: `authority.requires_review: true` plus an
explicit unreviewed review posture. The shipped template carries no `review_state` field today and
defaults `requires_review` to `false`, so this is a template change delivered with the slice — not
an already-existing field. Vocabulary caveat: the triage policy expresses the posture as
`review_state: unreviewed`, while `STATE_AXES_CONTRACT.md`'s canonical `review_state` set is
`draft / provisional / reviewed / protected / archived`; that reconciliation is a pre-existing item
between those two owner docs (tracked as issue #2793) — this spec mandates the *posture*, not
a specific token. Human takeaways and any promotion remain human acts per triage policy §4.3.

Raw and normalized artifacts are machine-side records, not vault notes; the note references them
via provenance. **Raw retention:** `raw` records are retained as rebuildable machine-side records
for as long as their companion artifact exists — the replay acceptance criterion depends on them.
Discard follows the machine-mirror rules: safe to delete and re-acquire, never silently.

## Phase 2 vertical slice (TCD milestone)

One explicit URL, end to end, nothing more — no discovery, no scheduling, no UI, one extractor.

Acceptance criteria (each needs a concrete `Verify:` target when issues are filed):

- [ ] Explicit YouTube URL accepted; metadata + captions acquired caption-first (manual-track
      preference observable in `acquisition_method`).
- [ ] A caption-less item falls back to ASR through the existing faster-whisper path; the
      resulting artifact differs only in `acquisition_method` and quality note.
- [ ] `raw` record immutable with `content_identity`; re-running the same URL is a traced no-op
      (dedup), not a duplicate.
- [ ] `normalized` transcript: deduplicated rolling cues, timestamps preserved, language detected
      and marked as detected.
- [ ] One extractor (e.g. `summary`) produces schema-valid output registered per the extraction
      registry; schema mismatch fails loudly.
- [ ] Candidate written back as a `youtube_source_note` companion artifact with the mandated
      non-authoritative posture markers (`requires_review: true` + unreviewed posture — see
      §Writeback, including the template-frontmatter extension shipped in the same slice) and full
      provenance; triage state entry is `captured`; nothing advances triage automatically.
- [ ] Replay: deleting all derived levels and re-running from `raw` reproduces equivalent
      normalized/extracted/candidate artifacts without network egress.
- [ ] Stage events appear on the outbox with the standard envelope and idempotency keys.

## Out of scope for this source spec

Podcast/RSS audio, Vimeo, local media archives (later plugins); translation of transcripts;
diarization improvements; embedding/indexing of the transcript (#2314); any UI.
