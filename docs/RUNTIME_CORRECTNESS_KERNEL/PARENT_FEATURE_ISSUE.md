State: **Pre-filing draft.** Updated with the live issue number in this same PR once the parent
feature issue is filed on GitHub.

# Parent Feature Issue — Runtime Correctness Kernel

Title shape: `feat: Runtime Correctness Kernel — single truth, replay-sound events, typed LLM boundaries`

Role: validation hub while KERNEL-01..15 children are outstanding (Backlog + `agent:blocked`; it is
never a direct pickup issue). Each delivered child posts a validation receipt here before the next
dependent child is picked up.

Body source of truth: `docs/RUNTIME_CORRECTNESS_KERNEL/README.md` — capability boundary, task
table, execution order, cross-task invariants, and capability acceptance criteria are maintained
there; the issue body mirrors them at filing time and records live validation evidence thereafter.

Closure condition: all capability acceptance criteria in the README verified on `main`, owner-doc
promotion PR merged, and every child closed. The final child (KERNEL-15) carries the parent-closure
handoff.
