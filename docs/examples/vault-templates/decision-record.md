---
artifact_class: decision_record
lifecycle: durable
work_relation: decide
area: "{{area}}"
project: "{{project}}"      # omit if not project-specific
decided_on: "{{date}}"
decided_by: "{{human | initials}}"

authority:
  human_authored: true
  ai_generated: false
  governance_bearing: true   # this record carries governance semantics
  requires_review: false     # decision is already logged by the human

created: "{{date}}"
updated: "{{date}}"
---

# {{Decision: short imperative statement of what was decided}}

## Status

`decided` — {{date}}

## Context

{{What situation or problem prompted this decision? What constraints were in play?}}

## Options considered

### Option A: {{Name}}

{{Description. Pros and cons.}}

### Option B: {{Name}}

{{Description. Pros and cons.}}

### Option C (chosen): {{Name}}

{{Description. Why this was chosen.}}

## Decision

{{Clear statement of what was decided, in plain language.}}

## Rationale

{{Why this option was chosen over the alternatives.}}

## Consequences

{{What follows from this decision. What is now easier, harder, or irreversible.}}

## Follow-up

- [ ] {{Action that follows from this decision}}

---

_Decision records are `durable` and governance-bearing. Once logged, they are append-only:
add new decisions or supersede with a new record rather than editing the original.
AI may suggest drafts but MUST NOT silently mutate a logged decision._
