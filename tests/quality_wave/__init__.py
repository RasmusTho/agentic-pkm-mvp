"""Quality Wave evaluation stack for v5.6 acceptance.

Quality Wave validates that the v5.6 forward line is ready via:
- Phase A: Event chain contracts (trace_id propagation, idempotency)
- Phase B: Golden vault + seeded snapshots (reproducibility)
- Phase C: Metamorphic runs (stability across parameter changes)
- Phase D: Cold rebuild coverage (lossless reconstruction)
- Phase E: Fitness gates (counter consistency, idempotence)
- Phase F: Scripted UAT harness (end-to-end acceptance)

All tests must PASS sequentially (A→B→C→D→E) before Phase F gates.
"""
