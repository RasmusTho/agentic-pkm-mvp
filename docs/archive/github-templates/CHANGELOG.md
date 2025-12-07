# Changelog

## v4.6 — Retrieval Quality & Reasoning Prep (in progress)
- Cross-encoder providers (`ce_local`, `ce_http`) behind `RERANK_ENABLE`, with graceful fallback to `mock_ce`; golden-set evaluation compares ce_local vs baseline and CI prints `EVAL P@10` / `nDCG@10`.
- RelationIndex v1 gains `has_any()` plus the Promotion orphan gate (default block) with audited overrides via `PROMOTION_ALLOW_ORPHANS` + `PROMOTION_ORPHAN_OVERRIDE_REASON`; CI reports relation coverage.
- Diarization hook wired into transcription with providers (`none|mock|external`) behind `DIARIZE_ENABLE`, feeding speaker-aware chunking.
- Golden set evaluation pipeline (`data/golden/*`) produces Precision@k and nDCG@k metrics in CI; doc integrity + PR/issue templates keep contracts enforced.

### v4.6-A — Cross-Encoder Quality Lift
- Expanded `data/golden/corpus.jsonl`, `judgments.json`, and `relations.json` to 16 deterministic queries (10 candidates each, 2–3 graded relevances) so ce_local can be validated offline.
- Rebuilt `ce_local` with normalized tokens, capped term-frequency + IDF-like weighting, exact n-gram bonuses, and original-score tie-breakers; scoring stays deterministic and O(n·|query|).
- Hardened `python -m app.fitness.report` to require ΔnDCG@10 ≥ +0.01 **or** ΔP@10 ≥ +0.005 whenever `RERANK_PROVIDER=ce_local`, while still printing the four CI summary lines.
- Added provider-selection + deterministic-order tests, ensuring flags-off paths equal baseline ordering and ce_http never runs during CI.
- Updated ARCHITECTURE/ROADMAP/STATUS to capture the ce_local heuristic matrix, SoT v4.6-A acceptance criteria, and the latest CI snapshot (ΔnDCG@10=+0.070, relation coverage 81.82%).

### v4.6-B — Relation Coverage Lift
- Introduced deterministic relation extraction (`app.stores.relation_index.extract_semantic_relations`) that scans frontmatter keys, tag prefixes, and markdown headings (“See also”, “Derived from”, etc.) for the supported relation types `{supports, extends, contradicts, derived_from}`.
- `prepare_relations_for_promotion()` now runs during promotion, registers links via the RelationIndex, emits `relation.added` / `relation.missing` audit entries, and honors `PROMOTION_REQUIRE_RELATIONS=1` for blocking missing relations before promotion.
- The golden relations corpus (`data/golden/relations.json`) tracks typed targets for every promoted doc, yielding 100 % coverage + validity, and `app.fitness.report` prints a fifth summary line `CI SUMMARY RELATIONS coverage=<%> validity=<%> target=95%` while failing CI if coverage < 95 %.
- Added regression tests for relation extraction, promotion integration, and fitness metrics so coverage and audits stay deterministic in memory-mode CI.

### v4.6-C — Diarization-aware Chunking
- `speaker_aware_chunks()` aligns spans with diarization metadata (`speaker,start,end`) so transcripts split on speaker changes or character budgets, while `ingest_and_chunk()` preserves the legacy behavior when `DIARIZE_ENABLE=0`.
- Chunk payloads now carry speaker + timing metadata end-to-end (pipeline → indexing helpers) and `text.chunk.created` audit events record `speaker_count` whenever diarization is enabled.
- `data/golden/diarization_sample.jsonl`, `app/fitness/chunks.py`, and new pytest coverage keep chunk p95 metrics deterministic; `python -m app.fitness.report` prints the sixth summary line `CI SUMMARY DIARIZATION chunk_p95=<val> speaker_avg=<val> flag=on` and fails if diarized p95 regresses by >5 %.

### v4.6-D — CI Gates & Summary Hardening
- Baselines for latency, eval, relations, and diarization live in `ops/quality/baselines.yaml`; `THRESHOLDS_PATH` and `GATE_STRICT=1` allow overrides while keeping CI offline.
- `app.fitness.report` now parses its own summary lines, enforces the baselines (latency ≤ baseline × tolerance, rerank deltas ≥ configured mins, relation coverage/validity ≥95 %, diarization p95 ratio ≤0.95), emits `CI SUMMARY GATES ok=<bool> reasons=<codes>`, and exits non-zero on regression.
- `.github/workflows/ci-smoke.yaml` tees the report into `tmp/ci_summary.log`, runs a verification step that requires all seven lines and `ok=true`, and the PR template calls out the requirement to paste the summary/gates lines plus declare flags used.

## v4.7 — Reasoning Layer & Reflexive Agents (in progress)

### v4.7-A — LLM Reasoning Layer v1
- Introduced `app/reasoning` (schema, provider, store, prompts) plus `data/golden/reasoning_samples.jsonl`; `REASONING_ENABLE=1` triggers the pipeline hook to call a reasoner (mock in CI, Ollama locally), validate JSON, store claims/evidence/inferences, and audit reasoning events.
- `app/fitness/reasoning.py` feeds the golden samples through the mock reasoner, emits `CI SUMMARY REASONING claims_avg=<v> inferences_avg=<v> conflicts=<n> flag=<on|off>`, and new gates (driven by `ops/quality/baselines.yaml`) require non-zero inferences with conflicts capped at baseline.
- New tests cover the mock provider, pipeline hook, fitness metrics, and CI verifier; docs/README detail baselines + overrides (`THRESHOLDS_PATH`, `GATE_STRICT=1`), and the CI workflow now enforces the eight-line summary contract.

## v4.5B — Fitness & Hook Readiness
- QAS-003/QAS-010 latency checks implemented in `app.fitness.metrics` and executed via GitHub smoke workflow.
- Hybrid rerank hook integration completed with adapter and provider matrix.
- Chunking + dedup pipeline codified with deterministic chunk policy and shared deduper helpers.
- Docs/STATUS updated with CI measurement notes; ROADMAP reflects delivered P1 (rerank) + P2 (chunk/dedup).

## v4.5A — Stable baseline
Date: 2025-11-11

Highlights:
- Deterministic CI in memory mode (no Postgres dependency).
- `audit_log()` graceful fallback to in-memory ring buffer with optional JSONL sink.
- LLM retry helper with bounded backoff for local Ollama calls; instant deterministic mock.
- Batch-friendly embeddings and hybrid retrieval build via `embed_batches`.
- Memory `VectorIndex` JSONL persistence (`INDEX_PERSIST_PATH`, gated load via `INDEX_PERSIST_LOAD`).
- Pluggable `RerankerProvider` with deterministic `mock_ce` and inert default.
- Optional rerank hook `apply_optional_rerank()` behind `RERANK_ENABLE` and `RERANK_TOP_K`.
- Docs synced: Architecture, Roadmap, Status, and Mermaid diagram exportability.
- CI: smoke workflow runs `pytest -q -m "not pg"` and seeds a persisted index file.

Upgrade notes:
- No schema changes. Memory-first remains default for CI.
- To enable rerank locally: set `RERANK_ENABLE=1` and `RERANK_PROVIDER=mock_ce`.
- Persist index during local runs by setting `INDEX_PERSIST_PATH=tmp/index.jsonl`.
