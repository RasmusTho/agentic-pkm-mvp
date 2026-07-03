State: Non-authoritative pre-Fable planning queue; use only as planning context, not executable backlog truth.

# Codex Delegation Queue - Integrated Runtime v1

Status: pre-Fable delegation queue. These are bounded repo-near tasks that are cheaper and more deterministic for Codex than for Fable. Do not treat this as a final implementation backlog until the Integrated Runtime v1 parent scope is accepted.

## Immediate tasks before Fable

### CDQ-01 Post-merge owner-doc watchdog receipt for PR #1858

Reason: The PR bot requested `$post-merge-owner-doc` for PR #1858. This is a delivery feedback-loop action, not a Fable task.

Codex prompt:

```text
Run the repository's post-merge owner-doc workflow for PR #1858.
Post the resulting receipt comment to PR #1858.
Do not modify product docs unless the skill reports owner-doc drift requiring a follow-up.
```

### CDQ-02 Prepare Fable input excerpts

Reason: Fable should receive a compact evidence packet, not the entire repo.

Codex prompt:

```text
Create a temporary Fable input bundle from current main. Include:
- docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK.md
- docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK_ERRATA.md
- concise excerpts from docs/STATUS.md, docs/ARCHITECTURE.md, docs/ROADMAP.md
- concise excerpts from companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md
- issue bodies for #1782, #1795, #1851, #1699, #1702
- current state summaries for those issues
Do not create a PR unless asked. Keep the bundle concise and ASCII-only.
```

### CDQ-03 Re-check Companion UI route parity candidates

Reason: Route parity is the most concrete integration failure mode and should be kept repo-factual.

Codex prompt:

```text
On current main, inspect served Companion UI route/proxy allowlists and active controls.
Produce a concise report of active controls that call same-origin endpoints not allowed by serve_dev_page / production page routing.
Classify each as:
- live-routed
- missing proxy route
- hidden/disabled
- dev-only/experimental
Focus on Panel confirm, Vault Browser queue-review, vault-related, Canvas session/edit/undo/close/governance, TTS status, Capture, Memory Review, Receipts History.
Do not implement fixes.
```

### CDQ-04 Verify process-memory and persistence assumptions

Reason: Fable needs clarity on what must persist for v1.

Codex prompt:

```text
Inspect current main for process-memory-backed state used by candidate v1 capabilities.
Report persistence posture for:
- Panel proposals
- Panel idempotency state
- Canvas sessions and edit history
- Memory Review queue
- bundle receipts / emitted bundle registry
- TTS cache/status
- BuilderOps store
Classify as durable, process-local, file-backed, DB-backed, or derived/read-only.
Do not implement changes.
```

## Tasks after Fable synthesis

### CDQ-05 Normalize Fable output into repo issue specs

Reason: Fable output should be converted into repo style and checked against owner docs before issues are created.

Codex prompt:

```text
Take the accepted Fable Integrated Runtime v1 synthesis and convert it into repo-ready docs under docs/INTEGRATED_RUNTIME_V1/.
Create:
- README.md or update the existing README.md
- PARENT_FEATURE_ISSUE.md
- one markdown spec per accepted child issue
Preserve source anchors, constraints, acceptance criteria, and suggested validation.
Do not create GitHub issues unless asked.
```

### CDQ-06 Create GitHub parent and child issues from accepted specs

Reason: GitHub Issues are the execution contracts.

Codex prompt:

```text
Create the accepted Integrated Runtime v1 parent issue and the approved first wave of child issues.
Use the repo's canonical issue style.
Apply labels according to project governance.
Do not mark child issues agent:ready unless their dependencies and Project state are correct.
```

### CDQ-07 Implement first bounded child: route parity repair

Reason: Route parity is likely an early, high-leverage implementation slice.

Codex prompt:

```text
Pick up only the accepted route parity child issue.
Add failing tests first for active controls whose same-origin routes are missing or whose UI should be disabled/hidden.
Implement the smallest route/disable/hide changes needed.
Run focused Companion UI tests and ruff.
Post validation receipt to the parent.
```

### CDQ-08 Implement readiness matrix slice

Reason: Operator readiness is a productization gate and a natural low-risk slice.

Codex prompt:

```text
Pick up only the accepted readiness matrix child issue.
Expose a read-only Integrated Runtime v1 capability matrix through status/API and/or Companion UI as specified.
Do not grant authority or create new writes.
Run focused API/status tests and Companion UI render tests.
Post validation receipt to the parent.
```

## Fable validation questions Codex should not solve

- Should Capture be core v1 or optional?
- Should Memory Review be core v1 before durable queue/restart semantics are proven?
- Should TTS/read-back be accessibility core or optional local capability?
- Should Canvas/Chat co-authoring remain experimental or be promoted into v1?
- Is local-only UI acceptable as v1 production/operator use, or must auth/TLS/reverse-proxy hardening gate the label?
- How should proportional governance tiers be designed?

## Guardrails for Codex tasks

- Do not weaken WriteGuard.
- Do not invent receipts.
- Do not conflate events and receipts.
- Do not promote runtime projections into canonical truth.
- Do not treat BuilderOps as product/runtime authority.
- Do not add hidden writes.
- Do not change v1 scope by implementation side effect.
- Do not solve proportional governance inside integration tasks.
