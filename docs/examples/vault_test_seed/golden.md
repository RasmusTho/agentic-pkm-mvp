# Golden Vault Test Seed

This directory contains deterministic test data for Quality Wave Phase B (golden vault + seeded snapshots).

## Vault Structure

```
vault_test_seed/
├── golden.md                    (this file)
├── expected_outcomes.json       (snapshot of expected counts)
├── Note_1.md                    (simple note)
├── Note_2.md                    (note with links)
├── 2_Cards/
│   └── Concept.md              (card-type note)
└── Workbench/
    └── Draft.md                (inbox note for promotion tests)
```

## Expected Behavior

When this vault is ingested:
- All notes get UUIDs assigned (or use frontmatter uuid)
- Objects are created with canonical fields (uuid, title, origin, source_ref, trust, review_state)
- Embeddings are generated for all notes
- Relations are indexed (links between notes)
- Promotion tests verify that Draft.md can be moved to 2_Cards/

## Reproducibility

The golden vault is designed to be:
- **Deterministic**: same input → same output, always
- **Minimal**: small enough to run in unit tests, large enough to verify integration
- **Representative**: covers notes, cards, links, and promotion scenarios
- **Idempotent**: running ingest twice on the same vault yields identical state

## Usage

In Phase B tests:
1. Load golden vault from this directory
2. Ingest into a fresh store backend
3. Assert metrics match expected_outcomes.json
4. Snapshot the ingest time and embedding counts
5. Use as baseline for metamorphic and cold-rebuild tests

In Phase C tests (metamorphic runs):
- Run same golden vault with different parameters
- Assert output is stable across parameter changes

In Phase D tests (cold rebuild):
- Start with empty DB
- Run full ingest on golden vault
- Assert rebuilt state matches expected_outcomes.json
