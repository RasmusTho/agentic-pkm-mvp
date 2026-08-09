---
name: builder-inbox
description: "Read and validate the bounded Builder Thread inbox or health snapshot without writing reminders, dispositions, reviews, or external effects."
---

# Builder Inbox

Use this Builder System skill only when the owner explicitly requests inbox triage or a configured
automation invokes it. It is separate from learning-retrospective, PR/code review, and delivery
closure. Read _shared/BUILDER_THREAD_CONTRACT.md completely first.

## Commands

Read one named recipient inbox:

    scripts/builderops_cli.sh builderops builder-inbox list \
      --recipient <named-id> --limit <1..100> --json

Validate all Builder Thread artifacts and derive health:

    scripts/builderops_cli.sh builderops builder-inbox health --json

Both commands require BUILDEROPS_VAULT_ROOT and the pinned BUILDEROPS_VAULT_ID.

## Review Contract

- Entry files are the only source; no saved projection is trusted.
- Review is read-only and idempotent. The same validated artifact set yields the same snapshot hash
  and no mutation.
- Do not add reminder entries, review receipts, recursive review triggers, or learning signals.
- Do not reply, close, archive, quarantine, promote, or create external work unless a separate
  user/task authorization invokes the owning workflow.
- A conflict, wrong identity, partial artifact, privacy incident, or hash failure is a typed
  unhealthy result, never an empty inbox.
- Thread age or silence never implies approval, delivery, or permission to archive.

## Output

Lead with vault ID, snapshot hash, counts, truncation, and typed health. List only bounded summaries:
thread ID, subject, state, safe source refs, last activity, and pending contribution hashes. Never
print contribution bodies, rejected material, or absolute/private paths.
