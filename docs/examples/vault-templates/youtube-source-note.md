---
artifact_class: youtube_source_note
lifecycle: active              # active | durable | archived
work_relation: learn
area: "{{area}}"

provenance:
  source_kind: youtube_url
  url: "{{https://youtube.com/watch?v=...}}"
  creator: "{{channel name}}"
  published: "{{date}}"

watched_status: queued         # queued | watched | partially-watched | abandoned
transcript_available: false    # true if transcript has been imported

authority:
  source_authoritative: false  # the YouTube video is the source; this note is a companion
  ai_generated: false
  requires_review: false        # AI-generated notes MUST set this true (see review_state below)

# Canonical not-yet-reviewed posture (docs/CONCEPTS/STATE_AXES_CONTRACT.md;
# token mapping decided in #2793). Any note carrying AI-generated content that
# has not been human-reviewed MUST carry review_state: draft alongside
# authority.requires_review: true (INGESTION_AND_TRIAGE_POLICY.md §3).
review_state: draft            # draft | provisional | reviewed | protected | archived

created: "{{date}}"
updated: "{{date}}"
---

## Owner notes

### Takeaways

<!-- Add owner-authored takeaways here. -->

- {{What you understood, think, or want to remember.}}

### Open threads

<!-- Add owner-authored open threads here. -->

- {{Question or unresolved thread to revisit.}}

## Proposals (non-authoritative)

<!-- Generated module sections appear only below this wrapper and remain review material. -->

> _No proposal modules were produced._

## Evidence and lineage

- **Title:** {{video title}}
- **Source URL:** {{https://youtube.com/watch?v=...}}
- **Content identity:** {{sha256:...}}
- **Acquisition method:** {{captions_manual | captions_auto | asr}}
- **Transcript:** {{available; N normalized segments | unavailable}}
- **Coverage:** {{N/N normalized segments (100%; complete transcript) | 0 normalized segments; no transcript evidence}}

---

_The source URL remains authoritative. Generated proposals are non-authoritative review
material. Promotion into durable knowledge requires human review and creates a distinct
artifact; this source note remains provenance._
