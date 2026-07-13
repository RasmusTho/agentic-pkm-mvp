State: Current Builder System control-plane contract.
Doc role: Governance / operations contract.
Authority: Defines the logical dispatcher coordination boundary and its observable receipts.

# Builder Control Plane

## Logical Boundary

The dispatcher SQLite store is the logical control plane for local queue, lease, heartbeat, and
control-mode coordination. GitHub Issues, PRs, and CI remain durable delivery authority. Signboard,
Projects, and BuilderOps Vault artifacts are projections or advisory records, never lease locks.

## Enforcement Boundary

The control-plane module records revisioned mode receipts and exposes health, backup, and isolated
restore checks. It does not enforce a runtime deployment mode, create a fallback queue, or turn a
Vault or board into a distributed lock. Callers must continue to use the existing dispatcher claim,
lease, receipt, and workspace-preflight flows.

## State Transitions

Modes are `normal`, `degraded`, and `recovery`. A transition is conditional on the revision read by
the caller and fails loudly on stale state, an invalid edge, or unsuitable health evidence. The only
edges are `normal -> degraded`, `degraded -> recovery`, and `recovery -> normal`; `degraded` requires
unhealthy dispatcher observations and return to `normal` requires healthy observations.

## Recovery Tools

`health` checks database integrity, immediate-write availability, and JSONL parseability. `backup`
uses SQLite's online backup API. `restore` writes only to a separate empty state root and verifies the
restored database. These are operational tools, not deployment automation.
