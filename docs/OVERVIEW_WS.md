# Walking Skeleton (WS) — Overview
This repo follows the Canvas “AI-assisterat Second Brain — Konsoliderad grund”, Section 29.
Scope: single node, few users. Minimal pipeline:
Ingestion: Ingestor → Normalizer → Classifier → Chunker → Indexer.
Retrieval: QueryRouter → (BM25 + pgvector later) → AnswerComposer.
Curation: Minimal reviewer flow.
Observability: jsonl logs + trace_id; per-object audit file.

Non-goals in WS: Latent-Watcher, A/B, advanced scorecards, autoscaling, sharding, DLQ-UI.

See data/context/*.yaml for policies and routing. See golden/* for the golden set.
