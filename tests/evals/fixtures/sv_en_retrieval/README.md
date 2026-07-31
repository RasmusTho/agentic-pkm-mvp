# SV/EN retrieval eval fixture set

Hand-labelled fixture set for the SV/EN retrieval eval, slice G3-2
([#2985](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2985)), specified in
`docs/MIMER_CAPABILITY_HARDENING/RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md :: 2. G3`.

This set extends the eval-fixture culture established by the anti-contamination corpus in the parent
directory ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)) — synthetic content,
canonical frontmatter metadata, labels committed next to the documents they describe. It is a
**sibling** set, not part of that corpus: it answers a different question (bilingual retrieval
quality), and `tests/evals/_helpers.py :: GROUPS` deliberately does not include it, so the
anti-contamination integrity tests are unaffected.

## Contents

| File | What it is |
| --- | --- |
| `corpus/*.md` | 20 synthetic notes, 10 Swedish and 10 English, across 12 topics |
| `queries.json` | 24 hand-labelled queries — 8 SV-only, 8 EN-only, 8 cross-lingual |
| `connect_pairs.json` | 8 labelled SV/EN related pairs, 8 hard negatives, 16 connect seed queries |
| `scorecard.json` | The recorded run, produced by `scripts/eval_sv_en_retrieval.py` |

Read the numbers and the G5 recommendation in `tests/evals/SV_EN_RETRIEVAL_EVAL_G3_2.md`.
The harness lives in `tests/evals/sv_en_retrieval.py`; the checks in
`tests/evals/test_sv_en_retrieval_eval.py`.

## Content rule

**Niflheim-style, never Niflheim content.** Every document here is hand-authored and synthetic. No
personal, client, work, or vault material may be committed to this directory — the corpus imitates
the *shape* of a bilingual personal knowledge vault (a builder's working notes mixed with hobby and
admin notes), not its contents. `test_corpus_is_synthetic_and_canonically_tagged` enforces the
`synthetic: true` marker and rejects email-like identifiers; the rest is authorial discipline.

## Why the corpus is built the way it is

- **Eight topics exist in both languages.** A cross-lingual gold label is only meaningful when the
  same subject is genuinely present in the other language. The SV and EN documents on a topic are
  *not translations of each other* — they are independent notes on the same subject, so lexical
  overlap across the language boundary is low and BM25 cannot fake a cross-lingual hit.
- **Four topics are single-language distractors** (`brewing`, `everyday_queueing`, `graph_theory`,
  `coffee_roasting`). Each shares heavy surface vocabulary with a labelled topic — fermentation
  temperature and volume with sourdough; queue depth, ceiling and wait time with watcher
  backpressure; graphs, edges, neighbourhoods and hops with note linking; caffeine with sleep. Without
  them, recall is high for trivial reasons.
- **Hard negatives are labelled explicitly** in `connect_pairs.json`. A connect-precision number
  scored only against random negatives flatters every embedding identity.

## Cross-lingual gold, and why `recall@1` looks harsh

For a `cross_lingual` query the gold set is **only** the other-language document. The same-topic
document in the query's own language is a competitor, not gold. So `recall@1` measures "does the
other-language document outrank its same-language twin", which is not what a user wants from
retrieval; `recall@3` / `recall@5` and MRR are the figures that reflect usefulness. This is a
deliberate labelling choice, restated in the eval note so the number is never read as a failure it is
not.

## Regenerating the scorecard

The eval embeds under both identities, so it needs an Ollama host with both models pulled. The
owner's laptop deliberately carries no ML deps — run this on the mac mini (test channel) or any
Ollama host:

```bash
ollama pull nomic-embed-text
ollama pull bge-m3
python3 scripts/eval_sv_en_retrieval.py --stamp <YYYY-MM-DD>
```

Changing anything in `corpus/`, `queries.json`, or `connect_pairs.json` invalidates
`scorecard.json`; regenerate it in the same change, or
`test_committed_scorecard_matches_committed_fixtures` will fail — which is the point.
