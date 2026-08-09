---
name: builder-thread
description: "Create, read, reply to, close, archive, or explicitly quarantine one attributed shared-non-sensitive Builder Thread through the executable BuilderOps file helper."
---

# Builder Thread

Use this Builder System skill for one durable question to a named recipient when a reply is expected
and the question is not already represented. Read _shared/BUILDER_THREAD_CONTRACT.md completely
before any live operation.

## Preconditions

- Use only a validated external BUILDEROPS_VAULT_ROOT.
- Require the client-pinned BUILDEROPS_VAULT_ID.
- Run the repository helper; never hand-author an envelope.
- Keep content shared_non_sensitive and authority-safe.
- Route monologic notes to AgentWorklog instead.

## Commands

Verify genesis during normal use:

    scripts/builderops_cli.sh builderops builder-thread init --json

Only for an explicitly authorized first adoption of the already-validated BuilderOps vault:

    scripts/builderops_cli.sh builderops builder-thread init --adopt-existing --json

Create a represented question:

    scripts/builderops_cli.sh builderops builder-thread create \
      --recipient <named-id> --subject <bounded-subject> --content <bounded-question> \
      --actor <named-id> --entry-id <caller-retained-uuidv4> \
      --source-ref <type:value> --json

Read/list:

    scripts/builderops_cli.sh builderops builder-thread read <thread-id> --json
    scripts/builderops_cli.sh builderops builder-thread list --json

Reply by exact parent hash:

    scripts/builderops_cli.sh builderops builder-thread reply <thread-id> \
      --recipient <named-id> --content <bounded-reply> --actor <named-id> \
      --parent-hash <sha256> --entry-id <caller-retained-uuidv4> \
      --source-ref <type:value> --json

Close or archive only by explicit authorization:

    scripts/builderops_cli.sh builderops builder-thread close <thread-id> \
      --actor <named-id> --reason <bounded-disposition> --json
    scripts/builderops_cli.sh builderops builder-thread archive <thread-id> \
      --actor <named-id> --json

Quarantine an exact structurally valid unsafe artifact without deleting it:

    scripts/builderops_cli.sh builderops builder-thread quarantine <thread-id> \
      --artifact-hash <sha256> --reason-code <allowed-code> --actor <named-id> --json

## Rules

Create only after the capture gate passes. Reply, close, archive, and quarantine are mutations and
require explicit task/user authorization; workflow discovery never authorizes them. An exact retry
may return the existing artifact. A typed refusal or conflict is terminal until the source problem
is resolved.

Retain the create/reply `--entry-id` with the calling task until readback succeeds. Reuse it only for
an exact semantic retry; the helper returns the already-installed entry even when the retry occurs
in a later UTC second, and rejects changed content under the same ID.

First adoption is also a mutation and requires explicit operator authorization. Never add
`--adopt-existing` merely because routine init reports an unattested root.

Never infer Issue/PR/promotion/delivery state from thread prose. Re-read the owning authority live
before any external action and then invoke its existing skill.

## Output

Return operation, vault ID, thread ID, contribution hash, derived state, safe source refs, snapshot
hash, and any typed refusal. Do not expose the absolute vault root or rejected content.
