State: Deprecated shared reference. No hot-path operations.

# GitHub Project v2 Status Operations

GitHub Project v2 is no longer a Builder System lifecycle authority. The active queue and claim
state live in Builder Ops Vault; GitHub Issues and PRs provide external traceability.

Do not use `gh api graphql`, `gh project`, or Project-v2 field mutations in normal Builder System
work. Do not add an Issue or PR to a Project as a delivery precondition.

An explicitly authorized cold-path reporting or migration task may read an existing Project
projection, but it must not change queue eligibility, claims, merge readiness, or closure truth.
Use `.codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md` and `AGENTS.md :: Vault and dispatcher
transition policy` instead.
