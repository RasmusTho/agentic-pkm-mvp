# SV/EN retrieval eval — G3-2 (#2985)

State: Eval note (measurement record). Not an owner doc, not a contract.
Authority: none. It reports numbers and states one recommendation; the G5 default flip is a separate
owner call recorded against ADR-0024/ADR-0059.
Owner: Retrieval spine
Temporal class: dated measurement — the numbers describe the run recorded in
`fixtures/sv_en_retrieval/scorecard.json`, not a standing property of the system.

Implements `docs/MIMER_CAPABILITY_HARDENING/RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md :: 2. G3` slice G3-2,
under owner ruling R2: the eval **validates and tunes** the BGE-M3 migration, it no longer gates it.

## What was measured

- **Corpus** — 20 synthetic documents under `fixtures/sv_en_retrieval/corpus/`, 10 Swedish and 10
  English, across 12 topics. Eight topics exist in both languages (the labelled topics); four are
  single-language distractors that deliberately share heavy surface vocabulary with a labelled topic
  (brewing/sourdough, post-office queueing/watcher backpressure, graph theory/note linking,
  coffee roasting/sleep). Modelled on the **shape** of a real bilingual personal vault, never on its
  content: nothing here comes from a real vault.
- **Query set** — 24 hand-labelled queries, 8 per class:
  - `sv_only` — Swedish query, gold is the Swedish document on that topic.
  - `en_only` — English query, gold is the English document on that topic.
  - `cross_lingual` — Swedish query, gold is **only** the English document on that topic. The
    same-topic Swedish document is a competitor, not gold. This makes `recall@1` a deliberately
    harsh number for every identity; `recall@3`/`@5` and MRR are the informative figures.
- **Path** — the live production entrypoint `app.retrieval.hybrid.scoped_hybrid_search`, the same one
  `hybrid_search` and the ASK path bind to. Nothing is re-implemented; the eval measures the shipped
  ranking, BM25 and all.
- **Identities** — `nomic-embed-text:latest` @768 (pre-migration snapshot) and `bge-m3:latest` @1024
  (shipped after H4/#2984, TEST+PROD cutover verified on #3124).
- **Runner** — `scripts/eval_sv_en_retrieval.py`, writing `fixtures/sv_en_retrieval/scorecard.json`.

Two comparisons, each holding one thing fixed:

| Comparison | Fixed | Varied |
| --- | --- | --- |
| Identity | fusion = `linear` (shipped default) | `nomic-embed-text`@768 → `bge-m3`@1024 |
| Fusion | identity = `bge-m3`@1024 (shipped) | `linear` → `rrf` |

## Retrieval quality

Recorded run: `run_date 2026-08-01`, Python 3.13 on macOS/arm64, local Ollama host.

| Run | class | recall@1 | recall@3 | recall@5 | MRR |
| --- | --- | --- | --- | --- | --- |
| `nomic/linear` | overall | 0.625 | 0.6667 | 0.6667 | **0.6458** |
| | sv_only | 0.875 | 1.0 | 1.0 | 0.9375 |
| | en_only | 1.0 | 1.0 | 1.0 | 1.0 |
| | cross_lingual | 0.0 | 0.0 | 0.0 | 0.0 |
| `bge_m3/linear` | overall | 0.625 | 0.9167 | 0.9583 | **0.7653** |
| | sv_only | 0.875 | 1.0 | 1.0 | 0.9167 |
| | en_only | 1.0 | 1.0 | 1.0 | 1.0 |
| | cross_lingual | 0.0 | 0.75 | 0.875 | 0.3792 |
| `bge_m3/rrf` | overall | 0.625 | 0.625 | 0.6667 | **0.6333** |
| | sv_only | 0.875 | 0.875 | 0.875 | 0.875 |
| | en_only | 1.0 | 1.0 | 1.0 | 1.0 |
| | cross_lingual | 0.0 | 0.0 | 0.125 | 0.025 |

**The migration bought exactly one thing, and it is a large thing.** Monolingually the two identities
are indistinguishable on this corpus — `en_only` is perfect under both, `sv_only` is perfect at k≥3
under both. Every point of the overall MRR gain (0.6458 → 0.7653) comes from the cross-lingual class,
where nomic scores a flat zero: on all eight cross-lingual queries it never returns the
other-language document *anywhere in the top 5*. BGE-M3 returns it at rank 2 on five of eight, rank 3
on one, rank 5 on one, and misses one (`bicycle_maintenance`).

That is the honest shape of the R2 inversion's answer: switching to BGE-M3 did not make Swedish or
English retrieval better, it made the vault **one** corpus instead of two that cannot see each other.
For a bilingual vault that is the whole point; for a monolingual one the migration would have been
close to free and close to pointless.

**Caveat on `recall@1`.** It is identical (0.625) across all three runs because it is dominated by the
cross-lingual class, where the same-language sibling legitimately outranks the gold. Read `recall@1`
here as "does the other-language document beat its same-language twin", which is not what a user
wants; `recall@3`/`@5` is the figure that reflects retrieval usefulness.

**Swedish BM25 tokenization gap (README decision 6, explore-only) is visible.** The one `sv_only`
miss at k=1 and the single cross-lingual miss both involve compound-heavy Swedish
(`pendlarcykeln`, `våtolja`, `sommarolja`). BM25 tokenizes these as opaque wholes, so the lexical arm
contributes nothing for a query using the uncompounded form. Nothing in this slice changes that; it
is recorded here as evidence for whenever that gap is picked up.

## Expansion quality — connect precision

Scored against E3's **real** finding shape, not a proxy: EXP-1 (#2994) is merged, so
`app/expansion/connect.py :: run_connect_pass` exists. It retrieves `retrieval_k=8` hits per seed
query, drops hits below `ConnectPassConfig.relatedness_floor = 0.55`, and proposes every unordered
pair among the survivors as a `connect.related_unlinked` finding. The eval reproduces exactly that
pair set over 16 seed queries and scores it against 8 hand-labelled SV/EN related pairs plus 8 hard
negatives.

| Run | proposed pairs | true positives | precision | recall | F1 | hard negatives surfaced |
| --- | --- | --- | --- | --- | --- | --- |
| `nomic/linear` | 32 | 1 / 8 | 0.0312 | 0.125 | 0.05 | 2 |
| `bge_m3/linear` | 8 | 1 / 8 | 0.125 | 0.125 | 0.125 | 1 |
| `bge_m3/rrf` | 90 | 3 / 8 | 0.0333 | 0.375 | 0.0612 | 4 |

**The finding that matters is not the precision number, it is what it exposes.** Under the shipped
configuration the Connect pass surfaces one of eight labelled cross-lingual pairs. It is not that
BGE-M3 cannot see the relationship — the retrieval section proves it ranks the other-language
document at position 2–3. The problem is that `relatedness_floor` is applied to the **fused** score,
which is BM25-dominated, and a cross-language document scores low lexically by construction. So the
floor filters out precisely the pairs the migration made findable.

Two consequences worth carrying forward as separate work (not filed by this slice, which is
explicitly measurement-only):

1. `relatedness_floor` gates on a fused score whose scale is a property of the fusion strategy, not
   of relatedness. It is not fusion-portable — see the RRF row: the same 0.55 admits 90 pairs instead
   of 8, an 11× flood, because RRF compresses scores into a narrow band. Any future fusion default
   flip silently re-tunes the Connect pass.
2. If cross-lingual connect findings are wanted, the floor needs to see the embedding similarity, not
   the fused score.

## G5 default-fusion recommendation

**Keep `linear` as the default. RRF does not meet its burden of proof.**

Per ADR-0024 the burden is on RRF: the current linear weights (`0.5·bm25 + 0.4·emb + 0.1·overlap`)
are a deliberate trust encoding, and adopting RRF as default is a new ADR, not a config flip. On this
corpus RRF does not clear that bar — it is worse on every axis that moved:

- Overall MRR **0.7653 → 0.6333** (linear → RRF), on the same identity, same corpus, same queries.
- Cross-lingual recall@3 **0.75 → 0.0**, recall@5 **0.875 → 0.125**, MRR **0.3792 → 0.025**. RRF
  destroys the entire benefit of the BGE-M3 migration. Seven of the eight cross-lingual golds that
  linear surfaces disappear from the top 5 completely.
- `sv_only` MRR **0.9167 → 0.875**; `en_only` is unchanged at 1.0. So there is no compensating gain
  anywhere.
- Connect precision **0.125 → 0.0333**, with hard negatives surfaced rising 1 → 4.

The mechanism is legible and is not a corpus artefact. RRF discards score *magnitude* and fuses on
rank alone. In cross-lingual retrieval the lexical arm ranks the same-language document top and the
cross-language document near the bottom or off the list, while the embedding arm ranks the
cross-language document high but with a moderate absolute score. Linear fusion lets that strong
normalized embedding score carry the document past a weak BM25 rank; RRF flattens the embedding
signal into a rank position and lets BM25's monolingual bias dominate. Trust weighting is doing real
work here, which is precisely ADR-0024's caution — and it is now testable rather than asserted.

Scope of the claim, stated plainly: this is a 20-document synthetic corpus with 24 queries. It is
strong enough to reject a default flip (rejecting needs only a clear absence of gain, and what is
present is a large regression) and **not** strong enough to conclude RRF is useless at vault scale. If
RRF is revisited, revisit it with a per-arm score-normalization fix rather than as a straight default
swap, and re-run this eval first.

Sizes (`RETRIEVAL_CANDIDATES_PER_MODE`, `RERANK_WINDOW`): this corpus is far below the scale where
the field's 500/100 numbers mean anything, so it produces no evidence for or against the 100/25
pre-eval defaults. No recommendation is made on sizes; that is not a finding, it is an absence of
one.

## Reproducing

Requires an Ollama host with both models pulled — the eval embeds under both identities, so it does
not run on a machine without ML deps:

```bash
ollama pull nomic-embed-text
ollama pull bge-m3
python3 scripts/eval_sv_en_retrieval.py --stamp <YYYY-MM-DD>
python3 -m pytest -q tests/evals/test_sv_en_retrieval_eval.py
```

The test module verifies fixture integrity and scorecard truth with no Ollama present (so CI checks
that the committed numbers actually describe the committed fixtures, and that this note's
recommendation follows its own numbers), and additionally re-derives the headline cross-lingual
finding from live embeddings when an embedding host is available.

## What this note does not do

- It does not implement the G5 fusion flip, the conditional rerank gate, or any size config. G5-1
  already shipped `fusion={linear|rrf}` dark behind `RetrievalTuning`; this note only recommends what
  the default should be.
- It does not change retrieval behaviour in any way.
- It is not an owner doc and carries no authority.
