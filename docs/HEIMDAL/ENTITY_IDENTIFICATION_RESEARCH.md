State: Research survey (advisory), 2026-07-05. **This document is NOT a specification.** It surveys how others solve entity identification and recommends an approach to inform a *future* Heimdal/Mimer entity-identification design. It defines no contract, no schema, and no runtime behaviour; nothing here is binding until enacted through a proper spec + ADR.
Doc role: Research reference (advisory) — background reading, not a design of record
Authority: None — advisory only. Subordinate to any future entity-identification spec/ADR. Claims no shipped reality.
Owner: Architecture / Mimer knowledge layer (Rasmus)
Temporal class: reference
Review cadence: event-driven (revisit when the entity-identification design work begins)
Source of truth: this survey + the cited external sources (see §Sources)

# Entity Identification — Research Notes (how others do it, and a recommended approach)

> ⚠️ **This is research, not a spec.** It exists only to inform a later design decision. Read it for the landscape and the recommendation — treat nothing here as decided or contractual. The actual entity-identification *specification* will be a separate, clearly-labelled document. Owner decisions captured so far are marked inline (✅).

Scope: how to recognize entity **mentions** ("Anna", "Northvolt", "the Heimdal project") in transcribed text and resolve them to canonical entities in a **markdown-first, file-per-entity register owned by Mimer**, with a **graph DB as a derived index**. Priors: local-first/privacy, agent-proposes/human-confirms, streaming/incremental, entity kinds = people/orgs/projects (extensible).

---

## 1. Executive summary

The problem decomposes into a well-studied 5-stage pipeline: **NER → candidate generation → disambiguation/linking → coreference → resolution/merge.** The academic state-of-the-art has converged on an **LLM-assisted, schema-flexible** version of this, cleanly captured by the **EDC framework (Extract–Define–Canonicalize, EMNLP 2024)** — which is *exactly* our mentions→canonical→merge flow. Real products already prove the shape: **Reflect** ships an LLM feature that detects entities in freeform text and inserts `[[backlinks]]`; **Tana** auto-tags entities and *avoids creating duplicates for the same entity* (i.e. built-in entity resolution). Crucially, **no major PKM tool (Obsidian, Logseq, Roam) auto-links from plain text natively** — auto-linking exists only as plugins that present an **approval list before inserting links**, which happens to match our agent-proposes/human-confirms principle precisely.

For our constraints the recommended core is **local-first**: a small local NER model (**GLiNER**, zero-shot arbitrary types) or a **local LLM** for extraction, then **embedding-retrieval-over-the-register (RAG)** for candidate generation, then a **local-LLM rerank** for disambiguation, then **provisional→canonical→human-confirmed-merge** for resolution. The markdown notes stay canonical; the **graph DB is a derived, rebuildable index** — and the research suggests **deferring the graph DB** until relationship queries justify it (external graph-DB sync repeatedly proved "more complexity than value" for personal-scale graphs).

**Biggest trade-off:** local-only (privacy-honest, good-enough at personal scale) vs cloud-LLM (higher accuracy, breaks the local-first posture). Recommendation leans local, with cloud reserved as an optional quality path for *non-sensitive public* content (e.g. YouTube).

---

## 2. The pipeline, stage by stage (SOTA per stage)

### Stage 1 — Mention extraction (NER)
Recognize spans that name entities, with a type.
- **spaCy** — fast, fully local, per-language models (incl. Swedish); rigid built-in label set (PERSON/ORG/GPE…). Good baseline, weak on custom types like "project".
- **GLiNER** (2024) — generalist **zero-shot** NER; small (~0.3–0.9B), runs on CPU/local; arbitrary labels via a prompt ("person", "organization", "project", "product"). Best fit for local-first + custom entity kinds. [https://github.com/urchade/GLiNER]
- **LLM few-shot NER with structured output** — a local LLM (Qwen2.5, Llama 3.x via Ollama) or a cloud model extracts typed mentions + can do light coref in the same pass. Most flexible; costs latency and risks hallucinated spans. The literature frames this as the current shift "from rule-based/statistical pipelines to language-driven generative frameworks" (LLM-KG-construction survey, arXiv 2510.20345).

### Stage 2 — Candidate generation
Given a mention, retrieve plausible existing entities from the register.
- **Alias/lexical**: exact + fuzzy match on entity name and `aliases` (Obsidian already models `aliases:` in frontmatter and matches them in "unlinked mentions"). [https://help.obsidian.md/aliases]
- **Dense retrieval**: embed the mention-in-context, retrieve top-k entity notes by vector similarity — i.e. **RAG over the entity register**. This is the scalable, typo/paraphrase-robust path and reuses existing embedding infra.
- Classic EL systems bake this in: **BLINK** (bi-encoder retrieve + cross-encoder rerank), **ReFinED** (efficient single-pass EL with entity typing + descriptions, Wikidata-scale).

### Stage 3 — Disambiguation / linking
Pick the right candidate (or "new"/"ambiguous").
- Classic: cross-encoder rerank over (mention-context, candidate-description).
- **SOTA for personal scale: local-LLM rerank** — "which of these candidate entities does this mention refer to, given the context — or is it new?" Cheap and high-quality when candidate sets are small (personal KB = hundreds–thousands, not millions). Returns entity id + confidence, or new, or ambiguous.
- Linking target is a choice: **private KB only** vs **public KB (Wikidata/OpenAlex)**. An Obsidian "Entity Linker" plugin links selected text to Wikidata/Wikipedia/OpenAlex — evidence the public-enrichment path is real but optional.

### Stage 4 — Coreference resolution
Tie pronouns/aliases to the same entity.
- **Within-episode** (one memo/video): fastcoref/LingMess, maverick-coref, or the extraction LLM in the same pass.
- **Cross-episode**: handled by Stage 3 linking against the register (each new sighting links to the canonical entity). This is how PKG "population" is framed in the Stavanger PKG survey (arXiv 2304.09572).

### Stage 5 — Resolution / merge (canonicalization)
- **Match** (high confidence) → link mention to canonical entity note.
- **No match** → create a **provisional** entity note (stub).
- **Ambiguous / low confidence** → queue for **human confirmation** (agent-proposes/human-confirms).
- **Dedup**: periodic LLM-assisted detection that two notes are the same real entity → propose merge → human confirms → merge by **redirect/alias** (append-only correction, never destructive). This is exactly **EDC's Canonicalize** phase (arXiv/EMNLP 2024, https://aclanthology.org/2024.emnlp-main.548/) and matches **Tana's** "auto-tagging avoids duplicate tags for the same entity."

---

## 3. Tool / method comparison

| Method / tool | Stage | Local-runnable? | Notes |
|---|---|---|---|
| spaCy | NER, coref | ✅ | Fast, Swedish model; rigid labels |
| **GLiNER** | NER | ✅ (CPU) | Zero-shot arbitrary types — strong local fit |
| Local LLM (Qwen/Llama via Ollama) | NER, disambig, merge | ✅ (GPU/ANE helps) | Flexible; one-pass extract+coref; hallucination risk |
| Cloud LLM (Claude/GPT) | NER, disambig, merge | ❌ | Higher accuracy; breaks local-first |
| BLINK / ReFinED | candidate+link | ✅ (models local, KB large) | Built for Wikidata-scale, heavier than needed |
| Embedding retrieval (existing infra) | candidate gen | ✅ | RAG over register — recommended |
| fastcoref / maverick-coref | coref | ✅ | Within-doc coref |
| dedupe / Splink | resolution | ✅ | Classic record-linkage; LLM now competitive |
| **obsidiantools** | md→graph | ✅ | Parse vault → networkx (frontmatter/wikilinks/backlinks) |
| **remark-wiki-link** (npm family) | md parsing | ✅ | Durable parsing primitive (PortalJS/Flowershow/BrainDB use it) |
| MegaMem / Kwipu / engraph | md→graph index | ✅ | 2026-era Obsidian→graph/RAG; small projects; incremental file-watch |
| Neo4j Obsidian plugin | md→graph | — | **Abandoned**, author rewrote as in-app "Juggl" (dropped Neo4j) — signal that external graph-DB sync is often more cost than value |

**Product proof-points:** Reflect ("Decorate my writing with backlinks" — LLM entity detection → auto `[[links]]`, "if it starts with a capital letter, backlink it"); Tana (typed **supertags** + AI **Autotag** with dedup; schema-driven field autocomplete links to existing entity); Capacities (auto-tag but **won't auto-create** new entities — vocabulary control); Obsidian **Note Linker** (regex/WASM match of existing titles → **approval list before inserting** wikilinks); Mem ("Heads Up" real-time semantic surfacing, embedding-based, not explicit NER).

**Academic anchors:** PKG survey + PKG API (Stavanger/Balog, arXiv 2304.09572 / 2402.07540); **EDC** (Zhang & Soh, EMNLP 2024); **A-MEM** agentic Zettelkasten memory (arXiv 2502.12110); LLM-KG-construction survey (arXiv 2510.20345).

---

## 4. Decision axes (trade-offs — for the owner, not pre-decided)

1. **Local-only vs cloud-LLM.** Local (GLiNER + local LLM + embedding RAG) is good enough at personal scale and honors the privacy line already set for ASR. Cloud raises accuracy but breaks local-first. *Lean: local; cloud optional for non-sensitive public content.*
2. **Private-KB vs public-KB link.** ✅ **OWNER-DECIDED 2026-07-05: public-KB (Wikidata/OpenAlex) enrichment is IN scope.** The private register stays the source of truth; public entities (companies like Northvolt, well-known people/places) are *enriched* by linking out to Wikidata for extra metadata — the external link never overrides the private note.
3. **Fully automatic vs agent-proposes/human-confirms.** Every real PKM auto-linker uses an approval step; matches your steering principle. *Lean: auto-link only high-confidence; queue the rest for one-gesture confirm.*
4. **Entity scope.** Start people/org/project; GLiNER/LLM make adding concept/place/event trivial. *Lean: start narrow, widen freely.*
5. **Graph DB now vs deferred.** ✅ **OWNER-DECIDED 2026-07-05: defer the graph DB — markdown + a lightweight rebuildable index first.** Start with the parsing primitives (obsidiantools/remark-wiki-link/SQLite); add Kuzu/Neo4j only when relationship queries actually demand it. (Evidence backed this: external graph-DB sync repeatedly proved more complexity than value early on — the Neo4j Obsidian plugin was abandoned in favour of an in-app derived graph. Confirmed gap: no mature Kuzu+markdown sync tool exists, so a custom pipeline composes the primitives itself.)

---

## 5. Recommended approach for OUR constraints

A local-first EDC pipeline, split across the Heimdal/Mimer seam already decided (Heimdal emits mentions; Mimer resolves):

1. **Heimdal (capture side):** run **GLiNER** (or a local LLM) on the transcript → emit typed **mentions** (surface form, type, span, context sentence, confidence) on its event. No register access; no canonical identity. *(Confirms owner ruling: Heimdal emits mentions.)*
2. **Mimer (resolution side):**
   - **Candidate gen:** embedding retrieval over the entity-note register (+ alias/fuzzy match on names & `aliases:`).
   - **Disambiguation:** local-LLM rerank → matched entity id + confidence | new | ambiguous.
   - **Coref:** within-episode via the extractor; cross-episode via the link step.
   - **Resolution:** high-confidence → link; no match → **provisional entity note**; ambiguous → **human-confirm queue**; periodic **LLM merge proposals** → human-confirmed **redirect/alias** (append-only).
3. **Register:** one **`.md` per entity** — frontmatter (`id`, `type`, `aliases`, `state: provisional|canonical`, `provenance`, `created`); body = human notes + backlinks. **Markdown is canonical.**
4. **Graph:** a **derived index** rebuilt from the notes (parse frontmatter + wikilinks). Start lightweight (in-memory/SQLite, engraph-style "index is derived and fully rebuildable"); promote to Kuzu/Neo4j only when relationship queries justify it. Treat it as a **CQRS read-model** (an analogy we're borrowing — not a PKM term-of-art).

This reuses the system's existing embedding infra, honors local-first + human-confirmable + streaming, and lands squarely on a published, peer-reviewed pipeline (EDC) with working product precedents (Reflect, Tana, Note Linker).

---

## 6. Open questions for the owner

- **Graph DB now or deferred?** ✅ **Decided (2026-07-05): deferred** — markdown + a lightweight rebuildable index first.
- **Public-KB (Wikidata) enrichment?** ✅ **Decided (2026-07-05): yes, in scope** — private register stays source of truth; Wikidata enriches public entities.
- **Local model choice — GLiNER vs local LLM:** ✅ **Decided (2026-07-05): run a small bake-off** (a head-to-head comparison — run both on a few real voice memos, keep whichever extracts entities better) once real memos exist.
- **Auto-link confidence threshold** + how much lands in the human-confirm queue — still open; ties directly to the staged **attention-calibration** work (input 5, §9-k).
- **NER placement confirm:** extraction runs Heimdal-side (per the mentions ruling); candidate-gen/linking/merge run Mimer-side. To confirm when the design starts.

## 7. Additional deep grounding (from the sub-searches) + three sharpened design insights

**NER, concretely.** spaCy `en_core_web_trf` ≈ 90 F1 on OntoNotes but locked to a fixed schema (poor for "project"/custom types). **GLiNER** (NAACL 2024, arXiv 2311.08526, **Apache-2.0**, CPU/INT8-runnable) does zero-shot arbitrary types and *beats zero-shot ChatGPT* on NER benchmarks; its bidirectional-encoder parallel extraction is structurally faster than LLM token-by-token decoding. **GLiNER2** (2025, arXiv 2507.18546) unifies NER + classification + structured extraction in one pass. Local-LLM throughput is fine for this (M2 ≈ 18 tok/s on Llama-3.1-8B; small Qwen ≈ 55 tok/s) but public accuracy benchmarks for 8B-class local LLMs on NER are thin — favor GLiNER as the primary extractor, LLM for the reasoning-heavy stages (disambiguation, coref).

**Insight 1 — structural-first, LLM-for-gaps.** Our register already encodes entities as **wikilinks + frontmatter**; those are deterministic, free, hallucination-proof edges. Parse them first (obsidiantools / remark-wiki-link), and run NER/LLM **only on prose with no explicit link** (graphify's proposed "structural pre-extraction pass", GH issue #295). Don't NER everything.

**Insight 2 — candidate-constrained linking is precedented AND there's a production reference pipeline (correction to my first-pass claim).** I initially guessed "feed the LLM the candidate list" was an unclaimed gap. It is NOT: **ChatEL** (arXiv 2402.14858) frames entity linking as *multiple-choice QA over a KB-generated candidate list* (+~2% F1 vs free-generation over 10 datasets) — the direct academic precedent. And **Graphiti/Zep** (arXiv 2501.13956, source-verified) is a production system implementing almost exactly our recommended pipeline: exact-name collapse → **embedding candidate search (top-15, min cosine 0.6)** → deterministic MinHash/LSH fuzzy (0.9), and only *then* an **LLM last-resort with a structured candidate list** `{id,name,type,description}`. **iText2KG** (arXiv 2409.03284) and **LightRAG**/**KGGen** are further incremental references. This *strengthens* confidence — our design is a proven shape, not speculation. Contrast: **GraphRAG merges by exact `(title,type)` string match** (source-verified) with *no* resolution — maintainers confirm none ships (#113/#401/#778), producing the "Sherlock / Mr. Holmes / Holmes" fragmentation (#401) and a same-title/different-type over-merge bug (#1718). Neo4j LLM Graph Builder does dedup as **post-hoc batch cleanup with a human review tab** (edit-distance <3 OR cosine >0.97). Guardrails that matter: **candidate-constrained + structured/constrained decoding** (JSON-schema FSM), **PromptNER-style justify-against-type** (arXiv 2305.15444), and awareness that LLMs are **non-deterministic even at temp=0** (arXiv 2408.04667 — why "Apple Inc." vs "Apple" recurs), so **resolution must be deterministic-first, LLM-last-resort** (the Graphiti ordering).

**Insight 3 — "provisional entity" has a KG-native name: NIL clustering (correction).** I initially said the KG world had no term for it and pointed only to MDM. The KG-native pattern is **NIL clustering** from **TAC KBP** (since 2011): a mention that links to nothing gets a **NIL id** and future NIL mentions of the same unknown entity cluster under it, promotable later — functionally our provisional→canonical flow. **NASTyLinker** (ESWC 2023, arXiv 2303.04426) is a modern NIL-aware incremental implementation. For **reversible merge with preserved history**, the strongest precedents are **Wikidata** (merge = **redirect**, never delete; full edit history retained; documented undo/split) and **Reltio/Informatica MDM** (explicit **Unmerge APIs** + a queryable **merge-tree/lineage**; loser crosswalks preserved). Negative cases to avoid: **Salesforce/Dynamics merges are effectively irreversible** — which is exactly why we choose append-only/event-sourced merges. Formal **incremental/streaming ER** (Gruenheid/Dong/Srivastava VLDB 2014, ~4× vs batch; survey arXiv 1905.06397; streaming Bayesian record linkage arXiv 2307.07005) already solves "resolve against a growing register without full re-scan," and new evidence can *fix prior linkage errors* (matches our correction-as-new-event).

**HITL is evidence-backed, not just principle.** A 2025 peer-reviewed study (Information Processing & Management) on a 41M-statement KG found **fully-automated LLM validation raised precision +12% but LOST net F1**, while **hybrid human-in-the-loop gained net +5% F1** — direct support for agent-proposes/human-confirms. And a concrete UX precedent: **score-banded routing** recurs across Reltio (≥0.9 auto-merge, 0.6–0.9 human review with candidates side-by-side + matching attributes highlighted), Salesforce (~0.8), Dynamics (>0.9) — a ready template for our auto-link-vs-confirm-queue threshold (ties to attention-calibration, input 5).

**Net:** the §5 recommendation stands and is now *strongly* grounded — **GLiNER (structural-first, LLM-for-gaps)** for extraction; **embedding-RAG candidate gen → deterministic-fuzzy → LLM-rerank-against-candidates** for linking (the exact Graphiti/Zep + ChatEL shape); **NIL-cluster provisional → confidence-banded human-confirm → Wikidata/Reltio-style reversible redirect-merge with append-only lineage** for resolution; incremental-ER for the streaming story. Closest end-to-end references to study: **Graphiti/Zep** (temporal KG agent memory) and **Mem0**.

## Sources (primary/notable)
GLiNER https://github.com/urchade/GLiNER · EDC (EMNLP 2024) https://aclanthology.org/2024.emnlp-main.548/ · PKG survey https://arxiv.org/abs/2304.09572 · PKG API https://arxiv.org/abs/2402.07540 · A-MEM https://arxiv.org/abs/2502.12110 · LLM-KG-construction survey https://arxiv.org/abs/2510.20345 · Reflect backlinks https://reflect.app/blog/automatically-add-backlinks-using-ai · Tana supertags https://tana.inc/docs/supertags · Obsidian aliases/backlinks https://help.obsidian.md/aliases · Obsidian Note Linker https://github.com/AlexW00/obsidian-note-linker · obsidiantools https://github.com/mfarragher/obsidiantools · remark-wiki-link https://www.npmjs.com/package/remark-wiki-link · CQRS read-model https://martinfowler.com/bliki/CQRS.html
