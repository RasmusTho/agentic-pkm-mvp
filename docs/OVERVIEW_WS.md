# Walking Skeleton (WS) — Overview
This repo follows the Canvas “AI-assisterat Second Brain — Konsoliderad grund”, Section 29.
Scope (v4.3): single node, few users, Obsidian vault connectivity.
Pipeline overview:
- **Ingestion**: Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer.
- **Promotion**: Reviewer → SetEvaluator → Projector (writes published sets and feeds export).
- **Export**: `scripts/export_objects.py` mirrors promoted notes back into the vault.
- **Backfill**: `make backfill` keeps historical items aligned with promotion/export rules.
- **Retrieval**: QueryRouter → (BM25 + pgvector) → AnswerComposer.
Observability: JSONL logs, audit table, episodic memory snapshots, and diagnostic SQL views (`view_objects_*`).

Non-goals in WS: Latent-Watcher, A/B, advanced scorecards, autoscaling, sharding, DLQ-UI.

See data/context/*.yaml for policies and routing. See golden/* for the golden set.
