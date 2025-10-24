# Tester (Given/When/Then)
## 4.1 Normalizer
Given: råfil sample.md utan frontmatter
When: Normalizer körs
Then: Core-6 i AMG (objects), audit normalize, idempotens

## 4.2 Classifier
Given: normaliserad anteckning
When: Classifier körs
Then: decisions: type, topic/*, trust; metadata.changed emit

## 4.3 Chunker
Given: rubriker + brödtext
When: heading_first, max_tokens=800, overlap=120
Then: chunks med offsets, inga brutna ord/meningar, deterministiskt

## 4.4 Deduper
Given: två likartade anteckningar
When: Deduper körs
Then: decisions.duplicate_of, relations(canonical), ingen onödig indexering

## 4.5 CitationChecker
Given: påståenden + citatmarkörer
When: körs
Then: decisions.missing_citations; blockera promotion vid trust∈[external,conflict] utan källor

## 4.6 Indexer
Given: chunkad anteckning
When: Indexer körs
Then: pgvector + bm25 uppdateras; relations rubrik/refs; ingest.index.ready, curation.review.request

## 4.7 Reviewer
Given: gates i maturity.yaml
When: Reviewer körs
Then: seed→note auto vid confidence≥0.7; annars feedback; audit motivering

## 4.8 SetEvaluator
Given: set-regler
When: körs efter promotion/metadata
Then: membership uppdateras; IN_SET-relationer

## 4.9 Projector
Given: AMG uppdaterad
When: Projector körs
Then: frontmatter uppdateras endast på whitelist; Core-6 orörd

## 4.10 E2E
Given: tre dokument i /ingest/raw
When: hela pipen körs
Then: objects=3, chunks>3, embeddings>0, relations finns, membership uppdaterad, trace komplett
