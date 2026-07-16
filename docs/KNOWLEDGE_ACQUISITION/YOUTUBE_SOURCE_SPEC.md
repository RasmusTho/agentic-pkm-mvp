State: Specification (docs-authoring; target-state framing). §Transcript acquisition and §Metadata are implemented for the explicit-URL `fetch` path (KA-01, #2796, `app/knowledge_acquisition/youtube_plugin.py`) — caption-first, manual-track preferred, original-language only, captionless as a normal outcome, immutable raw record with dedup. ASR fallback (§Transcript acquisition point 2) is implemented (KA-02, #2797): a captionless item now falls back to the existing `app/media/transcribe.py` faster-whisper chain and lands as a raw record differing only in `acquisition_method: asr` + quality note; ASR is never invoked when a usable caption track exists. §Writeback is implemented (KA-05, #2800, `app/knowledge_acquisition/candidate_writeback.py`): candidate assembly re-derives normalize + extraction in-process from `raw`, then writes the `youtube_source_note` through the governed `WriteGuard` call site with the mandated posture markers (`authority.requires_review: true` + `review_state: draft`, per #2793); the template extension shipped in the same PR. Stage events and no-egress replay are implemented (KA-06, #2801, `app/knowledge_acquisition/stage_events.py` + `replay.py`; `python -m app.cli acquire-replay`), completing the §Phase 2 vertical slice end to end — verified by the real-URL operator receipt on #2795 (2026-07-05), which also caught and fixed a caption-track-selection defect (#2957, PR #2958: `vtt` now explicitly preferred over `json3`/`srv3`). §Discovery remains not implemented (Phase 4). **§Discovery mechanism revised by owner directive 2026-07-16:** playlist-shaped sources (inbox/owned/private playlists, Liked Videos) move to OAuth `youtube.readonly` + Data API; Takeout + RSS stays for subscriptions; cookie-based access is banned outright — decision record and delivery plan in `docs/YOUTUBE_SOURCE_SYNC/README.md :: Decision record` (tasks YSS-01..YSS-11).
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
| `egress_posture` | youtube.com + googlevideo.com; auth: none (logged-out) for fetch/backfill; low volume (tens of items/week), politeness sleeps; PO-token provider plugin as a declared local dependency. Phase 4 discovery adds www.googleapis.com + accounts.google.com/oauth2.googleapis.com (OAuth 2.0 `youtube.readonly`, playlist-shaped sources only — `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Egress posture`) |
| `auth_degradation` | Everything in v1 works logged-out. Phase 4 playlist/Liked discovery requires OAuth `youtube.readonly` and is fully degradable: absent, expired, or revoked consent disables exactly those sources with a reason code, never the plugin. Cookie-based access is banned outright (2025–2026 posture: YouTube suspends accounts / bans IPs for logged-in automated access), so Watch Later and Watch History are unsupported — no cookie fallback exists. |

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

## Discovery (Phase 4 — mechanism revised 2026-07-16; delivery via `docs/YOUTUBE_SOURCE_SYNC/`)

Per `RESEARCH_2026-07.md` §Subscription discovery **as revised by the owner directive of
2026-07-16** (`docs/YOUTUBE_SOURCE_SYNC/README.md :: Decision record` — the directive supersedes
points 4–5 below as originally decided; points 1–3 conform unchanged):

1. **Bootstrap + periodic reconcile: Google Takeout** — `subscriptions.csv` (channel IDs/titles)
   and playlist CSVs (incl. Liked). Takeout is snapshot-grade: bootstrap and drift repair, not the
   live feed. Watch Later is absent from Takeout (removed 2020).
2. **Incremental: per-channel RSS/Atom feeds** — `videos.xml?playlist_id=UULF<channel>` (uploads,
   Shorts/live excluded) polled at relaxed cadence. No auth, no quota, ~15 most recent items per
   feed; the `discover` cursor is newest-published-seen per feed.
3. **Gap repair: yt-dlp `--flat-playlist`** logged-out, rare cadence (weekly/monthly), as
   `backfill` — catches anything past the RSS window. Convergent with what Pinchflat /
   TubeArchivist / ytdl-sub all landed on: cheap frequent incremental + rare full reconcile.
4. **YouTube Data API v3: used for playlist-shaped sources only** (revised 2026-07-16; the
   original "not used" ruling stands superseded for this point). The save-to-playlist ≤3-minute
   inbox UX, private playlists, and Liked Videos are unreachable any other sanctioned way. OAuth
   2.0 at exactly `youtube.readonly`, fully degradable per `auth_degradation`. Subscriptions stay
   off the API (points 1–3 above remain the subscription mechanism).
5. **Watch Later / Watch History: unsupported.** The Data API does not expose them, and cookies,
   scraping, and browser sessions are banned in the standard flow (revised 2026-07-16 — the
   former "optional cookie-based degradable capability" posture is removed). The supported
   alternative is the inbox playlist itself (*Save → inbox*).

Explicit URLs and public playlist URLs need none of this and are the v1 entry points.

## Writeback

The candidate stage writes a `youtube_source_note` companion artifact based on the shipped
template (`docs/examples/vault-templates/youtube-source-note.md`): metadata + provenance
frontmatter, `transcript_available`, AI summary section marked non-authoritative, extraction
results as suggestion content.

The slice **extends** the template frontmatter with the initial non-authoritative posture markers
triage policy §3 mandates for AI-generated content: `authority.requires_review: true` plus
`review_state: draft`. The shipped template carries no `review_state` field today and defaults
`requires_review` to `false`, so this is a template change delivered with the slice — not an
already-existing field. Vocabulary: resolved by the #2793 owner decision (2026-07-02) — the triage
policy's former `unreviewed`/`queued` tokens map to the canonical `draft`/`provisional` values
owned by `STATE_AXES_CONTRACT.md`. Human takeaways and any promotion remain human acts per triage
policy §4.3.

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
      non-authoritative posture markers (`requires_review: true` + `review_state: draft` — see
      §Writeback, including the template-frontmatter extension shipped in the same slice) and full
      provenance; triage state entry is `captured`; nothing advances triage automatically.
- [ ] Replay: deleting all derived levels and re-running from `raw` reproduces equivalent
      normalized/extracted/candidate artifacts without source egress (extractor model calls route per `docs/LLM_ROUTING.md`).
- [ ] Stage events appear on the outbox with the standard envelope and idempotency keys.

## Out of scope for this source spec

Podcast/RSS audio, Vimeo, local media archives (later plugins); translation of transcripts;
diarization improvements; embedding/indexing of the transcript (#2314); any UI.
