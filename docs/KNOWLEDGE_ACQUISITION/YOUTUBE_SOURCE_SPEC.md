State: Partially implemented source specification. The explicit-URL fetch/refinement/writeback path is delivered by KA-01..06, including evidence-derived transcript availability, anchored synthesis and claims bound to retained transcript segments, deterministic coverage/confidence reporting, and authority-banded review-required proposal rendering. Pragmatic discovery V1 is delivered by #3915/#3920: one OAuth account, one ordinary owned playlist selected as Inbox, explicit manual sync, sanitized status, and review-required draft candidates. Liked Videos, multi-playlist product sync, scheduling, subscriptions/RSS/Takeout, backfill, analytics, broad CLI/UI, and full-media work remain target state and are not shipped claims.
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
| `capabilities` | `captions`; narrow `discover` for the single configured Inbox; `backfill` and broader discovery remain deferred. `media` is audio fallback for explicit acquisition only. `fetch` is the required operation, not a capability. |
| `egress_posture` | youtube.com + googlevideo.com; auth: none (logged-out) for fetch/backfill; low volume (tens of items/week), politeness sleeps; PO-token provider plugin as a declared local dependency. Phase 4 discovery adds www.googleapis.com + accounts.google.com/oauth2.googleapis.com (OAuth 2.0 `youtube.readonly`, playlist-shaped sources only — `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Egress posture`) |
| `auth_degradation` | Explicit-URL acquisition works logged-out. Inbox discovery requires OAuth `youtube.readonly` and degrades with a sanitized reason when consent is absent, expired, or revoked. Liked Videos and other product sources are not V1. Cookie-based access is banned; Watch Later and Watch History remain unsupported. |

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

## Discovery (Inbox V1 shipped; broader Phase 4 target state)

The shipped V1 uses point 4 only for one ordinary owned playlist selected as Inbox. Points 1–3,
Liked Videos, other playlists, and scheduled operation remain deferred target state. The broader
mechanism record below is retained for future re-contracting, not as a shipped claim:

1. **Bootstrap + periodic reconcile: Google Takeout** — `subscriptions.csv` (channel IDs/titles)
   and playlist CSVs (incl. Liked). Takeout is snapshot-grade: bootstrap and drift repair, not the
   live feed. Watch Later is absent from Takeout (removed 2020).
2. **Incremental: per-channel RSS/Atom feeds** — `videos.xml?playlist_id=UULF<channel>` (uploads,
   Shorts/live excluded) polled at relaxed cadence. No auth, no quota, ~15 most recent items per
   feed; the `discover` cursor is newest-published-seen per feed.
3. **Gap repair: yt-dlp `--flat-playlist`** logged-out, rare cadence (weekly/monthly), as
   `backfill` — catches anything past the RSS window. Convergent with what Pinchflat /
   TubeArchivist / ytdl-sub all landed on: cheap frequent incremental + rare full reconcile.
4. **YouTube Data API v3:** shipped for the one manual Inbox route with OAuth 2.0 at exactly
   `youtube.readonly`, fully degradable per `auth_degradation`. Its broader use for private,
   multi-playlist, or Liked Videos discovery remains deferred. Subscriptions stay off the API.
5. **Watch Later / Watch History: unsupported.** The Data API does not expose them, and cookies,
   scraping, and browser sessions are banned in the standard flow (revised 2026-07-16 — the
   former "optional cookie-based degradable capability" posture is removed). The supported
   alternative is the inbox playlist itself (*Save → inbox*).

Explicit URLs and the configured OAuth Inbox are the shipped entry points. Public-playlist product
discovery remains deferred even where the underlying fetch path can acquire an explicit URL.

## Writeback

The candidate stage writes a `youtube_source_note` companion artifact based on the shipped
template (`docs/examples/vault-templates/youtube-source-note.md`). Metadata, provenance, and
`transcript_available` remain in frontmatter. The body has exactly three authority bands:
owner-authored takeaways/open threads, one `Proposals (non-authoritative)` wrapper for registered
extraction output, and deterministic evidence/lineage. Production acquisition renders anchored
`synthesis@1` and `claims@1` modules; explicit legacy `summary@2` policies remain supported.
Generated content never enters
the owner band, and first-write-wins replay leaves every byte of an existing note unchanged.

Every runtime candidate carrying generated content receives the initial non-authoritative posture
markers mandated by triage policy §3: `authority.requires_review: true` plus
`review_state: draft`. The checked-in template documents that posture and its authority bands; the
runtime writer, rather than a template default, owns the generated candidate values. Vocabulary was
resolved by the #2793 owner decision (2026-07-02): the triage policy's former
`unreviewed`/`queued` tokens map to the canonical `draft`/`provisional` values owned by
`STATE_AXES_CONTRACT.md`. Human takeaways and any promotion remain human acts per triage policy
§4.3.

Raw and normalized artifacts are machine-side records, not vault notes; the note references them
via provenance. **Raw retention:** `raw` records are retained as rebuildable machine-side records
for as long as their companion artifact exists — the replay acceptance criterion depends on them.
Discard follows the machine-mirror rules: safe to delete and re-acquire, never silently.

### YouTube Source Note v2 truth-surface correction

The shipped candidate writeback now corrects the three confirmed V1 truth defects:

- `transcript_available` is derived from usable normalized segments; a valid empty ASR result
  renders `false` and does not run transcript-dependent summary extraction. Captionless acquisition
  remains a loud normalization failure.
- anchored synthesis shows schema-validated model confidence plus deterministic evidence
  confidence derived from referenced transcript segments.
- synthesis and claims input contains every normalized segment; coverage counts unique referenced
  transcript segments, and unsupported anchorless output is omitted before rendering.

The delivered YSNV2-03 renderer replaces the fixed About/Summary/Takeaways body with the three
authority bands above. It fails closed when visible generated Markdown claims the owner's belief,
decision, takeaway, or approval; impersonates a reserved band; contains a Unicode bidi control; or
uses an active Obsidian embed that could materialize unvalidated content. This is a finite
authority lint, not a semantic claims-quality classifier.

Process-local extraction results, the single delivered `summary@2` module, and title-bearing
candidate paths remain V1 limitations or deliberate choices, not retroactive defects. They may
change only through the bounded YouTube Source Note v2 child contracts. Those contracts preserve
immutable raw evidence, first-write-wins candidate notes, and the rule that a candidate is terminal
only after its note has materialized. Re-extraction or upgrade must create a versioned proposal
companion rather than overwrite the original candidate or human-authored content. These bounded
deliveries do not ship the later v2 modules, change title-bearing paths or persistence, alter
D1–D6, or introduce ProfileAgent behavior.

The portable-source-bundle delivery adds a derived, rebuildable vault transcript and `source.json`
under the YouTube attachment root (`Sources/YouTube/_attachments` by default). The stable
`yt-<video-id>` folder contains immutable content-identity/stage-version members, so a later
acquisition cannot retarget prior candidate evidence. Its manifest carries the resolved
metadata-bundle envelope (including object-form `scope_binding`); replay still reads only
machine-side raw evidence. New candidates link the transcript, while an existing candidate receives
that link only in its D5 versioned proposal companion.

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
- [x] Anchored `synthesis` and `claims` extractors produce schema-valid output registered per the
      extraction registry; language and anchor violations fail loudly.
- [ ] Candidate written back as a `youtube_source_note` companion artifact with the mandated
      non-authoritative posture markers (`requires_review: true` + `review_state: draft` — see
      §Writeback, including the template-frontmatter extension shipped in the same slice) and full
      provenance; triage state entry is `captured`; nothing advances triage automatically.
- [ ] Replay: deleting all derived levels and re-running from `raw` reproduces equivalent
      normalized/extracted/candidate artifacts without source egress (extractor model calls route per `docs/LLM_ROUTING.md`).
- [ ] Stage events appear on the outbox with the standard envelope and idempotency keys.

## Out of scope for this source spec

Podcast/RSS audio, Vimeo, local media archives (later plugins); translation of transcripts;
diarization improvements; embedding/indexing of the transcript (#2314); any UI.
