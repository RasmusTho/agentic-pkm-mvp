---
artifact_class: source_note
artifact_type: book
lifecycle: durable             # durable as a reference anchor
work_relation: learn

title: "{{Book Title}}"
author: "{{Author Name}}"
published: "{{year}}"
isbn: "{{isbn}}"               # optional

provenance:
  source_kind: book

reading_status: to-read        # to-read | reading | read | abandoned

authority:
  source_authoritative: false  # the published book holds authority; this note is a representation
  human_authored: true
  ai_generated: false

created: "{{date}}"
updated: "{{date}}"
---

## About

{{One-sentence summary of the book's main subject and why you're reading it.}}

## Key themes

- {{Theme or question the book addresses}}

## Notes while reading

→ See linked [[literature notes]] for chapter-by-chapter paraphrases.

## Human takeaways

<!-- What you now understand or claim, in your own words. These are yours, not the author's.
     Consider promoting strong insights into separate evergreen notes. -->

- {{Your own insight or claim, not a paraphrase of the author}}

## Literature notes derived

- [[{{literature-note-title}}]]

## Evergreen notes promoted

- [[{{evergreen-note-title}}]]

---

_The published book holds source authority. This note is a controlled representation.
Literature notes capture what the author says; evergreen notes capture what you now claim.
Do not collapse these layers._
