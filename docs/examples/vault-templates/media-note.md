---
artifact_class: media_note
artifact_type: "{{subtype}}"   # personal_photo | project_evidence_photo | reference_image | screenshot | scan | receipt | manual | contract
lifecycle: durable
work_relation: remember        # remember | capture | orient | decide
area: "{{area}}"
project: "{{project}}"         # omit if not project-specific

provenance:
  source_kind: own_photo       # own_photo | own_screenshot | own_scan | pdf | web_article | ...
  source_file: "{{/absolute/or/relative/path/to/original}}"
  original_captured_at: "{{ISO-8601 datetime}}"
  source_url: "{{url}}"        # for reference_image only; omit otherwise

ai_caption: "{{AI-generated caption — non-authoritative}}"    # [AI-suggested, non-authoritative]
human_caption: "{{Human-authored caption}}"

authority:
  human_authored: true
  ai_generated_fields:
    - ai_caption
  source_authoritative: false   # authority belongs to the original file, not this note
  system_authoritative: false

privacy: private                # private | review-required | internal
review_state: unreviewed        # unreviewed | reviewed

created: "{{date}}"
updated: "{{date}}"
---

## Context

{{Human-written context: what this media captures, why it matters, what decision or project it relates to.}}

## Related

- [[{{Project or area link}}]]
- [[{{Decision record if applicable}}]]

---

_The `source_file` path points to the authoritative original. The AI caption above is a draft label;
the human caption carries the actual meaning. Authority belongs to the original file, not this note._
