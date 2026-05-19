---
artifact_class: reflection_note
artifact_type: weekly_review
lifecycle: durable
work_relation: remember
week: "{{YYYY-WNN}}"           # e.g. 2026-W21
period: "{{YYYY-MM-DD}} – {{YYYY-MM-DD}}"

authority:
  human_authored: true
  ai_generated: false

privacy: private               # weekly reviews are personal; adjust if shared

created: "{{date}}"
---

# Weekly review — {{period}}

## How did the week go?

{{Free-form reflection. What happened, how it felt, what stood out.}}

## Wins

- {{Something that went well}}

## Friction or challenges

- {{Something that was hard, slow, or frustrating}}

## Commitments honored / missed

- {{Commitment met or missed, briefly}}

## Projects — brief status

| Project | Status | Next action |
| --- | --- | --- |
| {{Project}} | {{on track / delayed / blocked}} | {{next step}} |

## Inbox review

- Processed inbox? Yes / No
- Outstanding captures to triage: {{count or list}}

## Reflections

{{Anything worth thinking about further. Not conclusions — observations.}}

## Candidate evergreen ideas

<!-- Things that surfaced this week that might become durable knowledge.
     These are drafts — write them up as evergreen notes separately if they hold up. -->

- [ ] {{Candidate idea}}

## Next week — intentions (not commitments)

- {{What you intend to focus on or try}}

---

_Weekly reviews are `durable` reflection artifacts. They are authoritative for the user's own
reflection at that time. Insights that hold up over time MAY be promoted into evergreen notes
via separate review. AI MUST NOT rewrite or summarize a completed weekly review._
