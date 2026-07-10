State: Shared skill contract. Canonical Builder System lifecycle truth matrix.

# Lifecycle Truth Matrix

The Builder Ops Vault is the active operational lifecycle surface. GitHub Issues and PRs are the
external task and delivery trail. The repository is the authority for code and durable docs.
GitHub Project v2 is an optional, deprecated read-only projection; it is never required for a
delivery and must not be read or mutated in the Builder System hot path.

| Delivery condition | Vault ticket / claim | GitHub Issue | PR |
| --- | --- | --- | --- |
| Not executable or dependency waiting | `Backlog` or `Blocked`; no active claim | `agent:blocked` or `agent:needs-human` when applicable | none or linked context |
| Executable and unclaimed | `Ready`; no active claim | open and `agent:ready` during transition | none |
| Active implementation | `In Progress`; active claim owned by worker | remove `agent:ready` after claim | draft or active PR if published |
| Review handoff | `Review`; claim remains until explicit release | open; no active-work label required | open, ready for review |
| Delivered terminal work | `Done`; no claim | closed with no `agent:*` labels | merged or closed |

## Binding rules

- When a matching Vault ticket exists, its folder, YAML `status`, and active claim are the pickup
  truth. Validate it with `builderops vault validate` before mutation.
- Claim atomically changes `Ready` to `In Progress`; then remove `agent:ready` through the REST
  label endpoint. If REST confirmation fails, release the Vault claim.
- Without a Vault ticket, use the documented dispatcher/GitHub-label fallback in `AGENTS.md`.
- `agent:ready` is an external transition qualifier, not a Project-status surrogate. Do not require
  a Project card or Project status to create, pick up, review, merge, or close work.
- Closed Issues must not retain active `agent:*` labels. A Vault record or projection never closes
  an Issue by itself.
