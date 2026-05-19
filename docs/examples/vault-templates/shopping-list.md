---
artifact_class: shopping_list
lifecycle: ephemeral
work_relation: execute
area: "{{area}}"             # home | outdoor_life | work | ...
store: "{{store name}}"      # optional
trip_date: "{{date}}"        # optional

authority:
  human_authored: true
  ai_generated: false
  governance_bearing: false
  agent_editable: true       # checking items off is agent-editable under explicit instruction

created: "{{date}}"
---

# Shopping — {{store or occasion}}

## Items

- [ ] {{Item}}
- [ ] {{Item — quantity or variant}}
- [ ] {{Item}}

## Notes

{{Any constraints, preferences, or substitutions.}}

---

_Shopping lists are `ephemeral` and operational. They do not become durable knowledge.
When fulfilled, archive or discard this note.
Patterns observed across many lists MAY be promoted into a reference note via explicit human review,
but the list itself is not retained as knowledge._
