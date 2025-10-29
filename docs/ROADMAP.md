# Roadmap — SoT v4.3.1 → v4.4 → v5.0

_Tracks strategic releases and planned features._

---

## v4.3.1 — Obsidian-First (Delivered)
- Promotion Agent wrapper + interval worker ✓  
- Settings schema validated ✓  
- Smoke tests in CI ✓  

---

## v4.4 — Semantic Merge & Hygiene (Active)
**Goal:** resolve semantic conflicts and automate note cleanup.  
- MergeResolverAgent (LLM + heuristics).  
- NoteHygieneAgent (archive / salvage / keep).  
- Event log + CLI tools (events & prompts).  
- Git merge-driver for `.md /.mdx`.  
- CI adds merge fixtures + schema lint.  

---

## v4.5 — Governance & Authoring UX
- Block-aware diff and selective HYBRID merges.  
- Merge→Reviewer→Projector policy integration.  
- Golden fixtures and QAS guards in CI.  

---

## v4.6 — Optimization & Learning
- Token budget / locus prompting (optional).  
- Post-merge critique → adaptive scoring.  
- Reinforcement of merge heuristics from feedback.  

---

## v5.0 — Reasoning Alpha
- Symbolic layer (triples / claims / rules / provenance).  
- Reasoner + SHACL validation.  
- First neurosymbolic loop between AMG and reasoning layer.  
