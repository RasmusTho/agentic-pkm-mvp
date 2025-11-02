# Next Steps — Sprint Bridge v4.4 → v4.5

_Tactical actions to complete active release._

---

## Objectives
1. **Activate LLM judging** (default off in tests).  
2. **Integrate semanticmd merge driver** into CI.  
3. **Implement ASK microflow** (export → review → apply).  
4. **Add merge fixtures and schema lint** to CI.  
5. **Track Hygiene archive events in Jaeger.**

---

## Definition of Done
- CI runs merge + hygiene tests deterministically.  
- Manual ASK flows log `merge.resolved` or `merge.prompt`.  
- Events and spans visible in Jaeger.  

---

## Preview v4.5
- Block-aware diff and fine-grained HYBRID merges.  
- Merge critique + learning feedback.  
- Promotion policy integration (Projector hook).  
- ADR for semantic governance flows.  
