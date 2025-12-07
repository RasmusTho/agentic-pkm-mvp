State: Partially outdated relative to SoT v4.10; placeholders only.
# Scorecards (diagnostic)

These scorecards are draft targets, not enforced in Reality-MVP.

ingestion_quality:
  frontmatter_core6_complete: true
  chunk_semantics_ok: true

retrieval_answering:
  faithfulness: ">= 0.8"
  provenance: ">= 0.8"

Notes:
- No automated scoring or CI gate consumes these values today.
- Keep as references for future quality/eval work; align with `docs/QUALITY.md` and fitness/eval suites when activating.
