---
name: Match Evidence to Open Questions
description: New ingest (Heimdal captures, KAP candidates, new/edited notes) matched against open questions via fenced LLM association producing candidate evidence links with provenance; deterministic threshold gate on what attaches; the evidence artifact itself is never written to
task_id: SQ-03
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 3. Standing questions
parent_capability: Standing Questions
prerequisites: [SQ-01]
depends_on: [STORE_QUESTION_NOTES_AND_PROJECTION.md]
can_parallelize_with: [Register Questions Friction-Free]
---

# Match Evidence to Open Questions

## Purpose

A registered question is inert without evidence flowing to it. This task is the operational meaning of
"the system matches new evidence against it over time": every new artifact from the existing ingest
paths — Heimdal captures, KAP candidates, new/edited notes — is checked against every currently `open`
question, and a qualifying match becomes a provenance-cited evidence link, attached with a deterministic
gate on top of an LLM's semantic judgment.

## What This Task Does

1. **Sources consumed (existing paths only, no new egress)**: Heimdal captures (observation-log
   cursor, same read path as the Episode Resolution Engine — `app/heimdal/publish.py`), KAP candidates
   (`knowledge_acquisition.stage.completed` outbox topic), and new/edited vault notes
   (`ingest.vault.changed` / `ingest.object.created` outbox topics). This task adds **no** new
   acquisition source — it is a consumer of what already flows.
2. **Scope discipline**: matching only ever considers open questions and artifacts in the **same
   scope** — same-scope-only by construction, mirroring the Connect capability's own posture
   (`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: 1.2`, "Scope is hard"). A
   cross-scope match is excluded content-free (no `CrossScopeFlow` grant class exists for this
   relation — cross-scope question/evidence sharing is capability-level out of scope entirely, per
   the README).
3. **Fenced LLM association**: for each (open question, candidate artifact) pair passing a cheap
   deterministic prefilter (same scope, artifact not already linked to this question), a fenced
   completion — the model sees only the question's `text` and the artifact's relevant span, nothing
   else — judges relatedness via the shared schema-constrained-completion utility
   (`app/components/llm/constrained.py::constrained_completion`), returning a structured
   `{"related": bool, "confidence_class": ..., "relation_label": ..., "supporting_span": "..."}`
   object, following the same normalized decision-surface shape Connect uses (observed span / relation
   / confidence, `docs/PANEL_AGENT.md :: Normalized Decision-Surface Proposal Format`). A
   schema-validation failure or degraded backend yields no link — never a fabricated one.
4. **Deterministic threshold gate (RQ-SQ2)**: only a `related: true` judgment whose
   `confidence_class` clears the named, single-sourced, provisional threshold constant actually
   attaches. The LLM does the semantic judgment; the gate is deterministic code, per the repo's
   standing "LLM cognition, deterministic gate" posture.
5. **Write discipline — the evidence artifact is never touched.** A qualifying match appends one
   entry to the Question note's system-owned `evidence` list (via the SQ-01 guarded seam,
   action `standing_questions.append_evidence`) — `artifact_ref`, `source_stream`, `matched_at`,
   `confidence_class`, `provenance_ref`, `quoted_span` (verbatim, never paraphrased — mirrors
   `CitationChecker` discipline). The candidate/capture/note the evidence came from is read-only
   throughout; no frontmatter, no body, no metadata bundle on the artifact side is ever mutated by this
   task. This is the one deliberate asymmetry against the Episode Resolution Engine's `episode_ref`
   pattern (ERE-05 stamps the *artifact's* bundle) — here only the question side gains state.
6. **Idempotency**: `(question_id, artifact_ref)` is the fold key; re-running the matching tick over
   already-evaluated pairs never duplicates an evidence entry. A later, stronger-evidence pass over
   the *same* pair may still add a second distinct entry only if it carries a materially different
   `quoted_span`/basis — never a silent duplicate of an identical basis.

## Concretely

```
$ python -m app.cli questions match-evidence --json
{"evaluated_pairs": 14, "attached": 2, "below_threshold": 5, "excluded_cross_scope": 1}
$ python -m app.cli questions show sq-... --json
{"evidence": [{"artifact_ref": "vault://notes/...", "source_stream": "vault.activity",
  "confidence_class": "high", "quoted_span": "...", "matched_at": "..."}]}
```

## Why This Matters

If matching writes into the evidence artifacts themselves, Standing Questions silently becomes a
second authoring surface over captures/candidates/notes that were never meant to carry
question-tracking metadata — polluting artifacts that other capabilities (KAP, retrieval, Episode
assignment) already own. If the threshold gate is soft or the LLM judgment alone decides attachment,
either the evidence trail floods with weak coincidences (making the eventual candidate answer
untrustworthy) or a real match is silently missed with no legible reason.

## Acceptance Criteria

- [ ] AC1: a fixture artifact clearly relevant to an open question's text attaches as an evidence link
      with provenance and a verbatim quoted span; a clearly irrelevant fixture artifact does not.
      Verify: `tests/standing_questions/test_evidence_matching.py::test_relevant_artifact_attaches_irrelevant_does_not`
- [ ] AC2: a same-content-but-different-scope fixture artifact is excluded content-free (no link, no
      leaked reasoning about the other scope). Verify:
      `tests/standing_questions/test_evidence_matching.py::test_cross_scope_artifact_excluded_content_free`
- [ ] AC3 (enforcement): the evidence write path never mutates the source artifact — asserted at the
      production matching entrypoint (artifact file/record hash before and after the tick is
      identical). Verify:
      `tests/standing_questions/test_evidence_matching.py::test_matching_never_writes_to_source_artifact`
- [ ] AC4: a below-threshold LLM judgment (`related: true` but `confidence_class` under the RQ-SQ2
      floor) does not attach; the threshold constant is named, single-sourced, and documented as
      provisional. Verify:
      `tests/standing_questions/test_evidence_matching.py::test_below_threshold_judgment_does_not_attach`
      and doc writeback at `docs/STANDING_QUESTIONS/README.md :: Provisional thresholds (RQ-SQ1,
      RQ-SQ2)`
- [ ] AC5: a schema-validation failure or degraded-backend fixture on the association call yields no
      link — never a fabricated or default-attached one. Verify:
      `tests/standing_questions/test_evidence_matching.py::test_degraded_association_never_fabricates_link`
- [ ] AC6: matching is idempotent per `(question_id, artifact_ref)` — re-ticking over already-evaluated
      pairs does not duplicate identical-basis entries. Verify:
      `tests/standing_questions/test_evidence_matching.py::test_matching_idempotent_per_pair`
- [ ] AC7: matching only ever evaluates `open` questions — a fixture `answered`/`closed` question
      receives no new evidence entries even against a clearly matching artifact. Verify:
      `tests/standing_questions/test_evidence_matching.py::test_matching_skips_non_open_questions`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/standing_questions/test_evidence_matching.py
pytest -q -m "not pg"          # full suite: shared ingest-consumer paths
```

## Out of Scope

Answer drafting/refresh triggering (SQ-04); companion UI evidence-trail display (SQ-05); question
registration (SQ-02); building any new acquisition source (this task consumes existing streams only);
duplicate/near-duplicate *question* detection (SQ-01/SQ-02 concern, not this task's).

## Related Docs

- `docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md` (the closest analog — read for
  contrast: that task *does* stamp the artifact; this one deliberately does not)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: 1.2` (the scope/candidate-only
  discipline this task's LLM association mirrors)
- `docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md` (the schema-constrained +
  `UNKNOWN` pattern the association call follows)
- [STORE_QUESTION_NOTES_AND_PROJECTION](STORE_QUESTION_NOTES_AND_PROJECTION.md) (the `evidence` field
  this task writes to)

## Related GitHub Issues

One issue: `[Standing Questions] match-evidence-to-open-questions: LLM-associated, provenance-cited
evidence attachment with a deterministic threshold gate`. Blocked until SQ-01 merges. TCD hint:
Sonnet / high effort — multi-source consumption + LLM association + provenance correctness is
pattern-following (mirrors ERE-05's assignment shape) rather than architecture-novel, but the
never-write-the-artifact enforcement AC (AC3) carries real blast radius if it regresses, so it sits
above default Sonnet/medium.
