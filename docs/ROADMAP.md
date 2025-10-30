# Roadmap — SoT v4.3.1 → v4.4 → v5.0

_Tracks strategic releases and planned features._

---

## v4.3.1 — Obsidian-First (Delivered)
- Promotion Agent wrapper + interval worker ✓
- Settings schema validated ✓
- Smoke tests in CI ✓

---

## v4.4 — Observability & Conflict Resolution (Active)
**Goal:** ship semantic merge, automated hygiene, and richer tracing without breaking promotion flows.
- Promotion Agent thin wrapper + event pipeline (maintain cadence)
- MergeResolverAgent rollout:
  - [x] Local semantic merge agent with tests (`merge_note_from_blobs`)
  - [ ] Expose agent as CLI (`make merge-dryrun`) that prints merged note + status + reason
  - [ ] Register deterministic merge driver for `.md` in git (optional local dev step)
  - [ ] CI smoke includes merge driver roundtrip once CLI lands
- NoteHygieneAgent rollout:
  - [x] Hygiene classification implemented and tested
  - [ ] Integrate hygiene step post-merge to clean empty/garbage notes and emit `cleanup.*` events
  - [ ] Add hygiene assertions to smoke
- Observability expansion (trace_id propagation, Jaeger export, event log tooling)

---

## v4.5 — Governance & Authoring UX
- Block-aware diff and selective HYBRID merges
- Merge→Reviewer→Projector policy integration
- Golden fixtures and QAS guards in CI

---

## v4.6 — Optimization & Learning
- Token budget / locus prompting (optional)
- Post-merge critique → adaptive scoring
- Reinforcement of merge heuristics from feedback

---

## v5.0 — Reasoning Alpha
- Symbolic layer (triples / claims / rules / provenance)
- Reasoner + SHACL validation
- First neurosymbolic loop between AMG and reasoning layer
