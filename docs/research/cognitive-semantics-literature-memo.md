State: literature synthesis (research memo; non-normative).

# Cognitive Semantics Literature Memo

## Purpose

This memo summarizes relevant literature and practice traditions before further semantic or
ontological lock-in around:
- relevance and importance,
- context, domains, spheres, and roles,
- archive/cold/hot metaphors,
- and the relation between artifacts, commitments, identity, and long-term memory.

This is a research memo, not a source-of-truth contract.
Its role is to separate:
- what appears strongly supported in the literature,
- what is only partially supported,
- and what remains provisional repo language.

Read this before hardening terms in:
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/LAYERING_MODEL.md`
- `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`

## Questions this memo addresses

1. Is there a well-established field term that cleanly replaces `warm/cold` or `hot/cool`?
2. Is `domain` the right master concept for context, or is it too rigid?
3. Are the meanings we care about best modeled as artifact attributes, or as several different kinds
   of relations and projections?
4. Does the literature support a first-class archive/retention function beyond simple storage?

## Summary

The literature does **not** support one simple replacement term that cleanly captures all of the
following at once:
- mental nearness,
- self-relevance,
- actionability,
- long-horizon importance,
- integration into thinking,
- and contextual integrity.

Instead, the strongest cross-source conclusion is that these are different phenomena.

The literature most strongly supports at least these distinct semantic axes:
- `actionability / commitment proximity`
- `attentional salience / mental distance`
- `self-relevance / identity centrality`
- `temporal horizon / durability`
- `integration into thinking / writing`

It also supports the view that context is not always best modeled as one exclusive bucket.
Different traditions talk instead about:
- roles,
- areas of responsibility,
- life domains,
- contexts with their own norms,
- and overlapping personal archives or stores of information.

The literature does support a first-class long-horizon retention function, but not mainly as a
"cold storage tier".
What is supported is closer to:
- personal archives,
- digital belongings,
- keeping found things found,
- reminding and context of relevance,
- and external support for long-term memory and continuity.

## Findings by tradition

### 1. GTD organizes by commitments, horizons, and areas of responsibility

David Allen's GTD material does not describe one generic "importance" axis.
It distinguishes:
- runway/current actions,
- projects,
- areas of focus and accountability,
- goals,
- vision,
- and purpose/principles.

This is a commitment and alignment model.
It is most useful for:
- actionability,
- responsibility,
- review rhythm,
- and alignment across time horizons.

It also uses language like `areas of focus and accountability`, which is broader and more lived
than a technical folder/category concept.

Implication for this repo:
- GTD strongly supports a separate commitment layer.
- It does **not** justify using `archive` or `domain` as master semantics for all artifacts.

Sources:
- [Horizons of Focus](https://gettingthingsdone.com/insights/horizons-of-focus/)
- [The Levels of Your Work](https://gettingthingsdone.com/wp-content/uploads/2014/10/Levels_of_Your_Work.pdf)
- [The Altitude Map](https://gettingthingsdone.com/wp-content/uploads/2014/10/2016-Horizons-of-Focus.pdf)
- [Defining Your Areas of Focus](https://gettingthingsdone.com/2016/08/episode-20-defining-your-areas-of-focus/)

### 2. PARA organizes by actionability, not by identity-centrality or mental distance

Tiago Forte's PARA method organizes information by how it is likely to be used:
- Projects
- Areas
- Resources
- Archives

Official Forte material explicitly frames PARA as an actionable organization system.
`Archive` there means inactive material from the other categories.

This is valuable, but it should not be mistaken for a general theory of:
- personal significance,
- identity centrality,
- or long-horizon cognitive value.

Implication for this repo:
- PARA strongly supports `actionability` as its own axis.
- PARA's `Archive` should not automatically be imported as the canonical meaning of long-horizon
  retained material in a cognitive ontology.

Sources:
- [The PARA Method](https://fortelabs.com/para/)
- [The Box: Twyla Tharp on Project-Based Organizing](https://fortelabs.com/blog/the-box-twyla-tharp-on-project-based-organizing/)
- [Progressive Summarization: A Practical Technique for Designing Discoverable Notes](https://fortelabs.com/blog/progressive-summarization-a-practical-technique-for-designing-discoverable-notes/)

### 3. Zettelkasten/Ahrens emphasizes role in thinking and writing

Zettelkasten practice, especially in the Ahrens-influenced tradition, distinguishes notes by what
role they play in thinking and writing:
- fleeting capture,
- source/literature handling,
- permanent useful notes,
- project notes.

This supports a distinction between:
- raw capture,
- source-linked understanding,
- and durable integration into one's own thinking.

Implication for this repo:
- `integration into thinking` is a real axis.
- It should not be collapsed into either `review_state`, storage temperature, or simple access
  frequency.

Sources:
- [From Fleeting Notes to Project Notes](https://zettelkasten.de/posts/concepts-sohnke-ahrens-explained/)
- [All notes are malleable: Strive for permanently useful notes](https://zettelkasten.de/posts/literature-notes-vs-permanent-notes/)

### 4. LYT emphasizes navigation, overwhelm, and personally meaningful development

Linking Your Thinking contributes something different.
Its terminology is centered on:
- `Mental Squeeze Point`
- `MOCs / Maps of Content`
- `Idea Emergence`

In this tradition, higher-order notes help:
- gather,
- develop,
- and navigate ideas.

The striking part for this repo is that LYT explicitly talks about ideas gaining:
- richness,
- complexity,
- and personally meaningful value over time.

This is not the same as GTD actionability or PARA archive/inactive status.

Implication for this repo:
- `navigational centrality` and `personally meaningful development over time` are real phenomena.
- They support treating some meaning as human-artifact relation and thinking-support structure,
  not merely artifact storage class.

Sources:
- [LYT Glossary](https://blog.linkingyourthinking.com/notes/lyt-glossary)
- [MOCs (defn)](https://blog.linkingyourthinking.com/notes/mocs-%28defn%29)
- [Maps](https://blog.linkingyourthinking.com/maps/)
- [Idea Emergence (defn)](https://blog.linkingyourthinking.com/notes/idea-emergence-%28defn%29)
- [LYT FAQ](https://blog.linkingyourthinking.com/notes/lyt-faq)

### 5. Identity and context literature supports roles, salience, and multiple life domains

Identity theory and related work distinguish things such as:
- role identity,
- identity salience,
- identity prominence,
- and commitment.

Recent work also emphasizes identity development in context and multiple life domains.
This supports the intuition that what matters in one part of life may be shaped by:
- different responsibilities,
- different norms,
- different tones,
- and different stakes.

This literature is much closer to the user's concern about:
- different personas/ways of being,
- bounded overlap,
- and the need to prevent one life context from contaminating another.

Implication for this repo:
- `role identity` has stronger support than a generic invented `persona` term.
- `domain` may be too rigid if it implies MECE buckets.
- A model using overlapping `spheres`, `contexts`, and `situated role identity` is more
  literature-aligned than one flat exclusive domain taxonomy.

Sources:
- [Understanding identity development in context](https://www.frontiersin.org/articles/10.3389/fpsyg.2024.1467280/full)
- [Supporting the self-concept with memory](https://academic.oup.com/scan/article/10/12/1684/2502563)
- [Engagement in Social Roles in Multiple Life Domains](https://www.cambridge.org/core/books/abs/balanced-life/engagement-in-social-roles-in-multiple-life-domains/632E9349B075FFB9582F1753545242F1)

### 6. Contextual integrity supports context-specific norms rather than one global category model

Nissenbaum's contextual integrity work treats context as norm-bearing.
The relevant parameters include:
- contexts,
- actors,
- attributes,
- and transmission principles.

This is important here because it suggests that context is not just "which folder something is in".
Context also carries:
- expectations,
- appropriate flows,
- roles,
- and values.

Implication for this repo:
- boundaries should not be modeled only as technical scope filters.
- Any future replacement or narrowing of `domain` should preserve the idea that context governs
  what is appropriate, not merely what is stored where.

Sources:
- [Privacy as Contextual Integrity](https://digitalcommons.law.uw.edu/wlr/vol79/iss1/10/)
- [Privacy and Knowledge Commons](https://www.cambridge.org/core/product/identifier/9781108749978%23CN-bp-1/type/book_part)

### 7. PIM and personal archive work strongly supports long-horizon retention as a first-class function

Personal information management and personal archive research strongly supports the idea that
people need more than active notes.

The strongest recurring themes are:
- keeping found things found,
- reminding function,
- context of relevance,
- personal digital belongings,
- long-term access,
- preservation,
- and human memory augmentation.

This literature does not describe the problem mainly as "cold storage".
It describes a more complex problem:
- some things are worth keeping even when they are not active,
- people need to rediscover them later from partial memory,
- provenance and surrounding context matter,
- and personal materials can remain meaningful over years or decades.

Implication for this repo:
- the archive/retention function is not an implementation detail.
- it deserves first-class product and ontological treatment.
- but its meaning should not be reduced to a storage-temperature metaphor.

Sources:
- [Keeping Found Things Found on the Web](https://www.microsoft.com/en-us/research/publication/keeping-found-things-found-web/)
- [Keeping and Re-Finding Information On the Web](https://www.microsoft.com/en-us/research/publication/keeping-and-re-finding-information-on-the-web-what-do-people-do-and-what-do-they-need-to-do/)
- [Save Everything: Supporting Human Memory with a Personal Digital Lifetime Store](https://www.microsoft.com/en-us/research/publication/save-everything-supporting-human-memory-with-a-personal-digital-lifetime-store/)
- [The Long Term Fate of Our Digital Belongings](https://www.microsoft.com/en-us/research/wp-content/uploads/2006/05/Archiving2006-marshall.pdf)

## What the literature most strongly supports

### Supported with high confidence

- We should model several distinct axes, not one master "importance" field.
- `actionability` belongs close to commitments and GTD-like structures.
- `attentional salience` is situational, not stable artifact essence.
- `self-relevance / identity centrality` is relational and context-bound.
- `integration into thinking` is distinct from storage, retrieval, and review posture.
- A first-class long-horizon retention/archive function is justified.
- Role/context semantics matter and should not be flattened into one universal scope tag.

### Supported with medium confidence

- Overlapping `spheres` may fit human life better than exclusive `domains`.
- `situated role identity` is a more defensible term than `contextual persona`, but still narrower
  and less universally established than plain `role identity`.
- Some repo terms may best remain as operational working language rather than final ontology.

### Not supported strongly enough yet

- A single canonical replacement term for `warm/cold`.
- Treating `writing plane` / `retention plane` as clearly literature-backed field-standard terms.
- Treating `domain` as the final canonical human context concept without further refinement.

## Modeling implications for the repo

### 1. Do not collapse all meaning into artifact attributes

The literature supports at least four different modeling modes:
- artifact descriptors,
- human-artifact relations,
- situational projections,
- commitment relations.

Therefore not everything should be stored or discussed as if it were one flat artifact metadata
bundle.

### 2. Keep context language provisional

Current repo terms such as `domain`, `sphere`, and `context` should be treated carefully.
The literature supports the underlying phenomena more strongly than any one final repo label.

### 3. Keep archive/retention first-class, but avoid over-reading the metaphor

The system needs a first-class function for:
- preserving,
- rediscovering,
- citing,
- inspecting,
- extracting,
- and later materializing useful retained material.

But the final canonical term for that function should remain open until the repo is satisfied that
it captures:
- long-horizon value,
- self-relevance,
- mental distance,
- and heterogeneous material,
without reducing the idea to access frequency.

### 4. Treat current `writing` / `retention` language as working language

These terms can still be useful inside the repo as temporary coordination language.
But this memo does **not** recommend treating them as field-settled canonical semantics.

## Recommended posture after this memo

1. Keep `COGNITIVE_AXES_AND_SPHERES` as the upstream explanation of distinct axes.
2. Mark `writing plane` / `retention plane` as current repo working language rather than
   literature-settled canonical truth.
3. Keep `domain` as a narrow operational/boundary term if needed, but avoid treating it as the
   whole human context model.
4. Continue developing the archive/retention function, since that part is strongly supported.
5. Delay any stronger ontology lock-in until the repo decides whether its long-term model should be
   centered on:
   - `domain`,
   - `sphere`,
   - `context`,
   - `role identity`,
   - or an explicit combination of these.

## Open questions for later work

- Should the primary context concept be `sphere`, `context`, `domain`, or a layered combination?
- Should role identity remain ontological, or mostly explanatory?
- Which artifacts should count as central/primary human artifacts across decades?
- How should long-horizon retained material relate to source artifacts, primary human artifacts, and
  future materialization into writing artifacts?
- Do we need a separate concept for navigational centrality beyond current artifact and commitment
  models?
