# System Overview — SoT v4.2

Why
Turn unstructured notes into trusted, retrievable knowledge with provenance and promotion gates.

How
1. Normalize file → Core-6 and raw text
2. Classify object → type and labels
3. Chunk text → semantic chunks
4. Dedupe objects → near-duplicate collapse
5. Check citations → trust surface
6. Index chunks → embeddings in pgvector
7. Reviewer (next)
8. SetEvaluator (next)
9. Projector (next)

Contracts

Object payload.core6
id, type, title, created, updated, origin

Agent Output Envelope
event, object_id, trace_id, meta

Decisions
duplicate_of: canonical_id and score
missing_citations: count
type: value

Retrieval Modes
vector, bm25, hybrid

Trust and Promotion
Reviewer blocks when trust is low or citations missing
