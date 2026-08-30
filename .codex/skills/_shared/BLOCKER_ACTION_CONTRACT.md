State: Shared contract. Canonical next-action receipt for non-active Issues.

# Blocker Action Contract

Use this contract whenever a workflow creates, repairs, blocks, escalates, verifies, or closes an
Issue. Lifecycle state and action subtype are separate: labels are routing metadata, while the
Issue comment is durable evidence. This contract does not make Project, Cockpit, or a watcher an
authority and does not authorize pickup of blocked work.

```yaml
receipt: blocker_action.v1
action: action:repair-contract
owner: builder|owner|external:<name>
next_action: concise executable next action
unblocks_when: observable condition
dependency_refs: []
review_at: null
last_verified_at: RFC3339 timestamp
```

`owner` is exactly `builder`, `owner`, or `external:<name>`, where `<name>` is a non-empty lowercase
identifier matching `[a-z0-9][a-z0-9._-]*`. Consumers reject every other value rather than projecting
unverified action evidence.

Open `agent:blocked` uses exactly one blocked `action:*`; open `agent:needs-human` uses exactly
one human `action:*`. Before `agent:ready`, re-read the evidence, remove the action label, and do
not infer a cause from a legacy coarse state. On terminal closure remove every `action:*` label.
