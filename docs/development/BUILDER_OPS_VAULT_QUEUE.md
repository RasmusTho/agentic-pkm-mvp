State: Active Builder System queue contract (MVP file-first adoption).
Doc role: Operational contract for the separate Builder Ops Vault active queue.
Authority: Builder System governance; Product/Runtime docs remain authoritative for runtime behavior.
Temporal class: operational

# Builder Ops Vault Queue

## Decision

The Builder System is moving active operational status out of GitHub Project v2 and into a separate
Builder Ops Vault. GitHub Issues and PRs remain the external traceability and publication trail.
GitHub Project v2 is deprecated for hot-path automation and may exist only as an optional/read-only
projection during transition.

The vault file contract is the API:

- one ticket is one Markdown file;
- ticket metadata lives in flat YAML frontmatter;
- status is represented by both folder and YAML `status`, and both must match;
- transient claims live in `.builderops/claims/*.json`;
- `.builderops/locks/*.lock` serializes same-host mutations only; iCloud-synchronized claim files
  are advisory across devices and do not provide distributed-lock semantics;
- Signboard, Obsidian, Plane, or a future Kvasir view are replaceable UIs over the same files;
- Codex and Claude operate against the file contract or `builderops vault` CLI, not against Signboard
  as an application.

## Authority Model

| Surface | Role |
| --- | --- |
| GitHub Issues/PRs | External intake, PR history, public delivery trace |
| Builder Ops Vault | Active operational truth for status, queue, notes, and claims |
| Signboard or similar UI | Human kanban view over vault files |
| `builderops vault` CLI | File-contract mutation and validation surface |
| Product repo | Durable code, owner docs, and stable promoted decisions only |

Authority rule:

- For active delivery, the vault wins.
- For public traceability, GitHub Issues/PRs win.
- For code truth, the repo wins.

## Minimal Layout

```text
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps/
  AGENTS.md
  agent-delivery/
    Backlog/
    Ready/
    In Progress/
    Review/
    Blocked/
    Done/
  .builderops/
    claims/
    locks/
    receipts/
```

## Minimal Ticket Schema

```yaml
id: ticket-2686
title: GraphQL exhaustion fix
status: Ready
github_issue: 2686
github_pr: ""
priority: high
agent_state: Idle
owner: ""
labels: [agent:ready]
updated_at: 2026-07-09T19:30:00Z
```

Do not add dependencies, milestones, estimates, or full historical mirrors in the MVP. Receipts belong
in the ticket body only for meaningful transitions: claim, blocked, review requested, review
passed/failed, done, GitHub sync, and stale-claim takeover. Heartbeats stay in claim files or runtime
logs.

## CLI

Bootstrap:

```bash
python3 -m app.builderops builderops vault init "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" --json
```

Initial hot-path commands:

```bash
python3 -m app.builderops builderops vault validate "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" --json
python3 -m app.builderops builderops vault next "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" --json
python3 -m app.builderops builderops vault claim "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" ticket-2686 --agent codex --json
python3 -m app.builderops builderops vault renew "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" ticket-2686 --agent codex --json
python3 -m app.builderops builderops vault move "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" ticket-2686 "Review" --actor codex --json
python3 -m app.builderops builderops vault note "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" ticket-2686 "review requested" --actor codex --json
python3 -m app.builderops builderops vault release "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" ticket-2686 --agent codex --json
```

One-time transition import from the existing dispatcher store is dry-run by default and never
overwrites an existing vault ticket or imports active dispatcher work:

```bash
python3 -m app.builderops builderops vault import-dispatcher "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" --json
python3 -m app.builderops builderops vault import-dispatcher "$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps" --apply --json
```

`claim` serializes same-host writers on `.builderops/locks/<ticket-id>.lock`, creates
`.builderops/claims/<ticket-id>.json` with a positive TTL, and atomically moves the ticket from
`Ready` to `In Progress`. A second active claim fails. Stale claims may be taken over only with
`--takeover-stale`, and the ticket receives a receipt. `move` and `note` use the same per-ticket lock
and reject an actor that does not own an active claim. Moving to `Backlog`, `Ready`, `Blocked`, or
`Done` releases the claim and clears the transient owner; `Review` keeps the claim until explicit
`release` so the delivery agent can complete the review handoff without a race.

Long-running work renews the lease with `renew`; renewal is quota-free, writes only the claim file,
requires the active owner, and refuses to resurrect an already expired claim.

The one-active-claim invariant is enforced for agents using the same mounted vault on one host.
Cross-device iCloud conflicts are fail-loud validation findings, not proof of global exclusivity;
global/distributed locking remains out of scope.

`next` is local and quota-free. It selects unclaimed `Ready` tickets by priority
(`critical`, `high`, `medium`/`med`, `low`) and then by stable path order.

## GraphQL And Project v2 Policy

GraphQL is forbidden in the Builder System hot path. GitHub Project v2 automation is deprecated in
the hot path. Do not use:

- `gh api graphql`
- `gh project`
- Project v2 field mutations
- GraphQL-backed PR/check polling such as `gh pr checks`

GitHub sync must be REST-only in the MVP:

- GitHub -> vault: issues, labels, title, linked PR, issue state;
- vault -> GitHub: transition receipts/comments, labels, and issue closure via REST;
- not MVP: full two-way sync, full comment mirroring, full Project sync, or GraphQL review-thread
  resolution.

## Adoption Order

1. Create the vault and `AGENTS.md` contract.
2. Spike Signboard disk behavior against 10-20 active tickets.
3. Use `builderops vault validate/next/claim/move/note/release`.
4. Use the idempotent dispatcher import to seed transition tickets; add REST-only incremental GitHub
   issue import after the file contract has survived local operation.
5. Productize in Kvasir only after the file contract is proven.

Temporary operations data must not be committed to the product repo. Stable decisions and durable
builder workflow contracts are promoted through normal repo PRs.
