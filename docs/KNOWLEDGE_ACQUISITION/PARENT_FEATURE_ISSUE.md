State: **Filed.** Parent feature issue **#2795** (validation hub, `agent:blocked` pending kernel-backlog sequencing); children **#2796–#2801** filed 2026-07-02 in dependency order. KA-01 (#2796) delivered via PR #2928 (2026-07-04); KA-02 (#2797) delivered via PR #2931 (captionless ASR fallback); KA-03 (#2798) delivered via PR #2932 (deterministic normalize stage); KA-04 (#2799) delivered (open extraction registry + `summary` extractor); KA-05 (#2800) delivered (candidate assembly + governed `youtube_source_note` writeback, this PR). KA-06 (#2801) remains `agent:blocked` on its own unmet prerequisites.
Doc role: Parent-issue mirror (GitHub issue #2795 is the authoritative backlog/validation surface)
Authority: None — this file mirrors the filed parent issue so the spec directory is self-describing; the live issue governs.

# Parent Feature Issue — Phase 2 Vertical Slice

GitHub issue **#2795**: `[Knowledge Acquisition] Phase 2 vertical slice: one YouTube URL end-to-end`.

One explicit YouTube URL through the whole platform, replayably: caption-first fetch → immutable
raw record → deterministic normalization → one schema-gated extractor → candidate
`youtube_source_note` with mandated posture markers → stage events + no-egress replay. If this
slice holds, the platform contracts are proven before any breadth is built.

## Children (dependency order)

| Task | Spec file | Issue |
| --- | --- | --- |
| KA-01 | `ACQUIRE_YOUTUBE_CAPTIONS.md` | #2796 |
| KA-02 | `ASR_FALLBACK_PATH.md` | #2797 (after KA-01; parallel with KA-03) |
| KA-03 | `NORMALIZE_TRANSCRIPT.md` | #2798 (after KA-01; parallel with KA-02) |
| KA-04 | `EXTRACTION_REGISTRY_AND_SUMMARY_EXTRACTOR.md` | #2799 (after KA-03) |
| KA-05 | `CANDIDATE_WRITEBACK.md` | #2800 (after KA-04) |
| KA-06 | `REPLAY_AND_STAGE_EVENTS.md` | #2801 (after KA-05; final child, parent-closure handoff) |

## Sequencing and gates

- KA-01 (#2796) delivered via PR #2928; KA-02 (#2797) delivered via PR #2931; KA-03 (#2798)
  delivered via PR #2932; KA-04 (#2799) delivered (open extraction registry + `summary`
  extractor); KA-05 (#2800) delivered (candidate writeback, this PR). KA-06 (#2801) remains
  `agent:blocked` until its own prerequisite (KA-05 — now clear) is reflected upstream.
- Integration-fabric class decision #2794: resolved (Acquisition source, class 11) by the same
  docs PR that filed this issue set.
- Review-posture vocabulary: posture-not-token pending #2793.
- Validation evidence (child receipts, replay receipt, real-URL operator receipt) accumulates on
  #2795; owner-doc promotion happens once at parent closure.
