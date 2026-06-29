State: Delivered. The authoritative parent feature / validation hub, GitHub issue **#1959**, closed as completed on 2026-06-15 after child slices #1970-#1972 delivered and owner-doc promotion landed. Part of v6.1 delivery hub #1956.

# Parent Feature Issue — Recall Runtime Activation

GitHub: **#1959** — validation hub closed as completed (`Status=Done`); not a pickup surface.

## Child slices (execution order)

1. **#1970** — `RETRIEVE_RELEVANT_PROMOTED_MEMORY` (RECALL_RUNTIME-01) — closed/completed.
2. **#1971** — `WIRE_RECALL_INTO_ASK` (RECALL_RUNTIME-02) — closed/completed; flipped the anti-dormancy guard green.
3. **#1972** — `SURFACE_RECALL_IN_ANSWER` (RECALL_RUNTIME-03) — closed/completed; delivered the owner-ratified surfacing treatment and parent-closure + owner-doc promotion handoff.

## Validation / acceptance

Each delivered child posted a validation receipt to #1959. The hub closed after a real ASK run recalled
relevant promoted memory with a receipt (read-only), the anti-dormancy guard passed, and the surfacing
treatment plus owner-doc promotion landed.
