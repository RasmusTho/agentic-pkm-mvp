# Arbetsplan (Codex-synkbar)

## Status per steg
- Normalizer: done
- Classifier: done
- Chunker: done
- Deduper: done
- CitationChecker: done
- Indexer: done
- Reviewer: todo
- SetEvaluator: todo
- Projector: todo
- E2E: done

## Att göra idag
1) Reviewer: skriva tester för gates + implementera (seed→note vid confidence ≥ 0.7, blockera vid low trust eller missing_citations)
2) SetEvaluator: skriva tester för set:latent initialt + medlemskap och IN_SET-relationer
3) Projector: skriva tester för whitelist-projektion till frontmatter (Core-6 orört) + implementera
4) Uppdatera E2E: inkludera Reviewer→SetEvaluator→Projector i röktestet och verifiera audit/trace

## Noteringar
- Körordning (TDD): Reviewer → SetEvaluator → Projector → E2E
- Loggning: jsonl, inkludera trace_id i alla rader
- Databas: idempotenta writes (UPSERT) för decisions/membership/audit
