---
scope_id: scope:general/retrieval-eval
sphere: general
source_role: human_note
authority_state: draft
evidence_role: background
sensitivity: public
synthetic: true
lang: en
topic: index_rebuild
---

# Reindexing after an embedding identity change

Swapping the model or the vector width invalidates every stored vector at once.
The source text is untouched, but the vectors belong to the identity that produced
them, so a store holding two identities ranks badly and silently instead of
failing loudly.

The discipline I follow: pause writes, rebuild the whole store from the canonical
text, then run a strict health pass that refuses to go green while two identities
still coexist. Traffic goes back on only after that.

The part that always surprises me is duration. Raising the per-document character
budget means fewer splits and better vectors, but each call costs more, so the
rebuild window stretches. I re-measure before promising anyone a time box.
