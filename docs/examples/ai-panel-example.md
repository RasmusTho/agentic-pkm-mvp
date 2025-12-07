State: Aligned (v4.10, with known debt — panel dispatch is flag-gated).
# AI panel example note

Example note that the current PanelAgent can parse. Headings remain in Swedish (`AI-instruktion`, `AI-åtgärder`, `AI-logg`) because the parser keys on them; fences are recommended.

```markdown
---
uuid: 123e4567-panel-demo
title: Panel demo note
---

%% AI:Start %%
## AI-instruktion
Please verify this note and promote it if ready.

## AI-åtgärder
- [ ] Promote this note
- [x] Re-classify as Concept

## AI-logg
- 2025-12-07 10:00 – Action: "Re-classify as Concept"
%% AI:End %%
```

When a checkbox is newly checked, PanelAgent:
1) Parses the panel, strips it from indexing, and detects the new action.
2) Enriches it with panel-action mappings (`docs/settings/panel-actions.md` or vault overrides).
3) Emits an `OutboxEvent` (`source=panel.agent`) if `PANEL_EVENTS_ENABLE` is on; otherwise returns the intent without dispatching.
4) Removes one-shot actions and appends a log entry.
