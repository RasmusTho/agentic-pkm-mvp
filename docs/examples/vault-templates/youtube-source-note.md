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
  requires_review: false

created: "{{date}}"
updated: "{{date}}"
---

## About

{{One-sentence description: what the video is and why it was saved.}}

## AI summary

<!-- [AI-suggested summary — non-authoritative. Do not promote into knowledge without review.] -->

> _AI summary goes here if generated. This is not human knowledge._

## Human takeaways

<!-- Add your own notes here as you watch. These are the first human-authored content in this note. -->

- {{What you understood, think, or want to remember.}}

## Candidate evergreen ideas

<!-- Ideas that might become evergreen notes after further review. These are drafts, not knowledge. -->

- [ ] {{Candidate claim or concept — to be written up as an evergreen note after review}}

## Related

- [[{{Literature note derived from this video}}]]
- [[{{Evergreen note promoted from this source}}]]
- [[{{Project or area link}}]]

---

_The YouTube video URL is the authoritative source. The AI summary above is non-authoritative.
Promotion into durable knowledge (evergreen or synthesis notes) requires human review and creates
a distinct artifact; this source note is retained as provenance._
