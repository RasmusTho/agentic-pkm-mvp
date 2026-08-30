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

## Receipt-only recovery

When the open Issue's lifecycle and exactly one compatible action label are already valid but its
latest context-bound receipt is absent, invalid, or names a different action, maintenance may append
one successor `blocker_action.v1` receipt. It must re-read live labels and comments before the
write, leave labels untouched, read back and parse the exact created comment, then re-read terminal
lifecycle/action context. A valid current receipt is a no-op; historical invalid comments remain
immutable evidence. The recovery neither infers an underlying blocker cause nor makes the Issue
pickup eligible.
Read the complete paginated Issue-comment stream. The newest comment carrying the receipt marker is
the governing candidate: a malformed newer marker is invalid evidence and must trigger repair rather
than being hidden by an older valid receipt.
