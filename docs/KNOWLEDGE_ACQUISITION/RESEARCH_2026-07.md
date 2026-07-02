State: Research memo (Phase 0, 2026-07-02). Non-normative context for the contracts in this directory; findings verified against primary sources at research time and expected to age — mechanism choices cite this memo, but the contracts do not depend on its details.
Doc role: Research / decision record input
Authority: None (advisory). Decisions grounded here are normative only where a contract or source spec in this directory states them.

# Knowledge Acquisition — Phase 0 Research Memo (2026-07)

Scope: (1) validate the 2026 ecosystem consensus for YouTube ingestion, (2) gap analysis against
existing repo assets, (3) settle the two genuinely open mechanism questions — caption acquisition
and subscription discovery — with primary-source verification (GitHub issues, maintainer docs,
OSS-tool wikis; mid-2026 state).

## 1. Ecosystem consensus (validated)

The open-source consensus architecture is: discovery → metadata-first triage → caption-first
transcript (ASR only as fallback) → normalization → LLM extraction → embeddings/knowledge store.
Points that held up under verification:

- **yt-dlp is the de facto ingestion standard** (metadata, captions, playlists, channels, audio)
  and — decisively in 2026 — the only mainstream local tool that survives YouTube's PO-token
  enforcement transparently (§3).
- **Caption-first beats transcribe-everything**: faster, free, and manual (creator) captions beat
  ASR; but note the quality ordering is *manual captions > local ASR > auto-captions* — YouTube
  auto-captions still lack reliable punctuation/segmentation, so "captions are usually more
  accurate than ASR" is only true for manual tracks.
- **faster-whisper is the default local ASR engine**; whisper.cpp for CPU/edge. (This repo already
  made that bet — §2.)
- **Multi-product extraction** (summary + claims + entities + tasks…) has replaced single-summary
  output in serious pipelines.
- **Commercial unified APIs** (hosted transcript/ingestion services) proliferated mainly as an
  escape hatch for cloud-IP blocking — a problem a residential local-first deployment does not
  have. Excluded: cloud dependency for locally-achievable capability.
- One widely-copied community idea does **not** transfer: the single "raw → evergreen" refinement
  ladder collapses machine processing depth into human knowledge standing. This repo already
  separates those axes (triage state / lifecycle / maturity / review_state); see
  `REFINEMENT_PIPELINE_CONTRACT.md` §Axis disambiguation.

## 2. Existing assets and gap analysis

Current shipped reality (verified in-repo 2026-07-02):

| Asset | State |
| --- | --- |
| `app/media/transcribe.py` | **Works, reusable.** yt-dlp audio download → ffmpeg 16 kHz mono → faster-whisper (model cache, diarization hook) → outbox record (`kind=transcript`) with trace id. Already the recommended fallback engine — the "old design uses outdated plain Whisper" assumption is false. |
| CLI `transcribe`, `pipe` | Working entry points (`app/cli/__init__.py`); `pipe` = normalize → classify → optional transcribe. |
| Dependencies | Current: `yt-dlp==2026.3.17`, `faster-whisper==1.0.3` (`requirements.txt`). |
| `youtube_source_note` | Artifact class + triage flow already specified (`INGESTION_AND_TRIAGE_POLICY.md` §4.3) + vault template shipped. |
| Governance | Promotion, authority, AI boundaries fully contracted; nothing to invent. |

Genuine gaps (= the platform work):

1. **No caption path at all** — the only transcript route is audio + ASR (the expensive fallback
   as the only path).
2. **No discovery/sync** — no subscriptions, playlists, incremental cursor, or dedup identity.
3. **No normalized transcript artifact** — flat text + segments today; no acquisition-method
   field, no rolling-cue dedup, no quality note.
4. **No extraction stage** — transcript goes to the outbox and stops; no structured extraction,
   no candidate production into the triage flow.
5. **No source abstraction** — `transcribe_source()` is a function, not a plugin behind a
   contract; nothing reusable for podcasts/PDFs.

## 3. Caption acquisition (decided — see `YOUTUBE_SOURCE_SPEC.md`)

The controlling 2026 fact: since ~May 2025 YouTube enforces **PO tokens on the subtitle endpoint**
(caption URLs carry `exp=xpe`; timedtext returns empty 200 without a token — yt-dlp #13075).
Consequences, verified against upstream issues:

- **yt-dlp + `bgutil-ytdlp-pot-provider`** handles `subs`-context tokens transparently (PR
  #13234); vtt/srt are the stable output formats; json3 richest but has had extractor bugs.
  Reliable at tens-of-videos/week from a residential IP, logged out.
- **`youtube-transcript-api` can no longer be the backbone**: no PO-token support
  (`PoTokenRequired`, upstream #592, open with no workaround as of v1.2.4 / 2026-04). Its
  blocking story otherwise targets cloud IPs (built-in rotating-proxy support is the tell), which
  is not this deployment.
- **Auto-*translated* subtitle tracks are 429-prone** (yt-dlp #13770/#13831, unresolved as of
  2026-01); original-language manual and auto tracks are unaffected. Therefore: original-language
  tracks only, never the translation endpoint.
- **Auto-caption normalization is mandatory**: rolling cues duplicate every line across
  overlapping cues; strip tags → collapse duplicates → merge (yt-dlp #1734 pattern).
- **Cookies are not needed** for public captions at this volume; 2025–2026 guidance (yt-dlp wiki,
  Pinchflat wiki) actively warns that logged-in automated access risks account suspension/IP
  bans. If ever needed: private-window export, never third-party extensions.
- Quality: manual captions > faster-whisper ASR > auto-captions (punctuation/segmentation);
  ASR fallback also requires audio download, which engages the full media anti-bot machinery —
  both facts argue caption-first with ASR as terminal fallback.

Decision: **yt-dlp captions (manual preferred, auto accepted, original-language only, PO-token
plugin) → ASR fallback via the existing faster-whisper path. youtube-transcript-api excluded.**

Primary sources: yt-dlp issues #13075, #13234, #13770/#13831, #1734; yt-dlp PO-Token Guide;
jdepoix/youtube-transcript-api #592; Brainicism/bgutil-ytdlp-pot-provider; equalentry.com caption
quality testing.

## 4. Subscription discovery (decided — see `YOUTUBE_SOURCE_SPEC.md`)

Verified option comparison:

| Mechanism | Auth | Coverage | Limits / risk |
| --- | --- | --- | --- |
| Per-channel RSS (`videos.xml?channel_id=` / `playlist_id=UULF…`) | none | recent uploads per channel; public playlists (unordered) | ~15 newest items, no backfill; negligible ban risk; no deprecation signal |
| Google Takeout | login per export (no OAuth app) | full subscription list w/ channel IDs (`subscriptions.csv`); playlists + Liked as CSVs; history as JSON | snapshot-grade; schedulable every 2 months; **no Watch Later** (removed 2020); occasional incomplete exports |
| Data API v3 | OAuth 2.0 + GCP project upkeep | subscriptions, playlists, Liked | quota trivially sufficient (1-unit list calls), but **cannot read Watch Later** (dead since 2016); heaviest coupling |
| yt-dlp + browser cookies | session cookies | everything incl. **Watch Later** (only option) | highest risk: 2025–2026 account-suspension/IP-ban warnings from yt-dlp and Pinchflat maintainers |

What the mature OSS tools converged on (Pinchflat, TubeArchivist, ytdl-sub): **cheap frequent
incremental poll (RSS or API) + rare expensive full reconcile (yt-dlp flat-playlist)**, with
scan-cadence guards (TubeArchivist refuses >1 channel-rescan/hour) to avoid blocks.

Decision: **Takeout bootstrap/reconcile + RSS incremental (UULF uploads feeds) + rare logged-out
yt-dlp backfill. No Data API. Watch Later only as an optional cookie-based degradable capability —
preferred alternative is an in-system acquisition queue.**

Primary sources: Pinchflat wiki (FAQ, YouTube-Cookies), TubeArchivist settings docs, ytdl-sub
automation docs, Google Data API quota docs, Takeout subscription-export format guides.

## 5. Aging expectations

The PO-token regime, RSS feed behavior, and Takeout export shape are all unilateral Google
surfaces; re-verify this memo's §3–§4 mechanics before Phase 4 (discovery) implementation if more
than ~2 quarters have passed. The contracts in this directory are deliberately
mechanism-agnostic so such drift lands in `YOUTUBE_SOURCE_SPEC.md` and this memo only.
