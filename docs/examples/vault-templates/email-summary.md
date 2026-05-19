---
artifact_class: email_summary
lifecycle: active
work_relation: orient
area: "{{area}}"
project: "{{project}}"      # omit if not project-specific

provenance:
  source_kind: email_thread
  provider: gmail            # gmail | outlook | fastmail | ...
  thread_id: "{{thread id or subject}}"
  thread_url: "{{url to thread if available}}"

participants: []             # [AI-suggested, non-authoritative]
contains_action: true
contains_decision: false
contains_reference: false

authority:
  source_authoritative: false   # the email thread in the provider is authoritative
  summary_authoritative: false
  ai_generated: true
  requires_review: true

review_state: unreviewed        # unreviewed | reviewed

created: "{{date}}"
updated: "{{date}}"
---

## Summary

<!-- [AI-suggested summary — non-authoritative until reviewed] -->
{{One-paragraph summary of the thread.}}

## Action items

- [ ] {{Action — owner — due date}}

## Decisions noted

> _Decisions extracted here are AI-suggested candidates. Each must be explicitly reviewed and, if
> confirmed, promoted into a separate [[decision record]] artifact._

- {{Candidate decision}}

## References

- {{External document, file, or note referenced in the thread}}

## Related

- [[{{Project or area link}}]]

---

_The email thread in {{provider}} is the authoritative record. This note is a non-authoritative
companion summary. Do not treat extracted actions or decisions as confirmed without human review.
When a decision is confirmed, create a separate [[decision-record]] artifact._
