---
scope_id: scope:general/retrieval-eval
sphere: general
source_role: human_note
authority_state: draft
evidence_role: background
sensitivity: public
synthetic: true
lang: en
topic: watcher_backpressure
---

# Backpressure in the file watcher

The watcher picks up changes faster than the workers drain them. With no ceiling
the queue grows until memory runs out, and the changes I lose are exactly the ones
never written down anywhere else.

Adding workers did not fix it; a bound did. Once the queue crosses its ceiling the
watcher stops reading and lets the operating system buffer instead. It feels
slower, nothing is dropped, and recovery after a burst becomes predictable.

I log queue depth and per-cycle wait time. Without those two numbers I am guessing,
and every guess I have checked against the measurement was wrong.
