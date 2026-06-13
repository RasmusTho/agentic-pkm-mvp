State: Filed. The authoritative parent feature / validation hub is GitHub issue **#1959** (reshaped from the original "invoke guarded recall" issue after a 2026-06-13 pre-implementation scoping finding). Part of v6.1 delivery hub #1956.

# Parent Feature Issue — Recall Runtime Activation

GitHub: **#1959** — validation hub (blocked) while child slices are outstanding; not a direct pickup.

## Child slices (execution order)

1. **#1970** — `RETRIEVE_RELEVANT_PROMOTED_MEMORY` (RECALL_RUNTIME-01) — `agent:ready`.
2. **#1971** — `WIRE_RECALL_INTO_ASK` (RECALL_RUNTIME-02) — `agent:blocked` on #1970; flips the anti-dormancy guard green.
3. **#1972** — `SURFACE_RECALL_IN_ANSWER` (RECALL_RUNTIME-03) — `agent:needs-human` until the surfacing treatment (A/B/C) is ratified; carries parent-closure + owner-doc promotion.

## Validation / acceptance

Each delivered child posts a validation receipt to #1959. Close #1959 after a real ASK run recalls
relevant promoted memory with a receipt (read-only), the anti-dormancy guard passes, and the surfacing
treatment is delivered + owner-doc promoted.
