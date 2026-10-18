# System-wide credential handling review prompt

Review and update credential routing across every Yggdrasil repository, runtime environment and
agent tool identified by current authority. Never paste keys, tokens, recovery codes, private keys,
or environment files containing secrets. Use secret-management and secret-routing, and obey each
credential owner's current contract.

Produce a short normative architecture principle and a value-free table with one row per credential,
consumer, physical host (or explicit missing binding), and channel. Include: purpose, owner,
consumer, host/channel, store/binding, minimum scope/allowed callers, agent invocation without raw
value, lifecycle owner and evidence status. Use implementerad, live-kvalificerad, väntande, or
enbart specificerad. Agent/model/task/repository/machine identity alone grants no secret access.
Prefer a server/host-local consumer. State the exact approved process boundary and residual risk
when an authorized process necessarily receives the raw value.

1. Read current repository instructions, SECURITY.md :: System-wide credential access, routing and
   the selected consumer owner docs. Use current Issues, PRs, receipts, Builder Vault and memory
   only where they can change routing or evidence. Resolve stale statements against current authority.
2. Inspect references/declarations in source, config, bootstrap, CI, host handoffs, tools and approved
   value-free log/receipt/note metadata. Never fetch, output, copy, fingerprint or transmit values to
   prove absence. Explicitly list unreviewed surfaces and unavailable safe projections.
3. Separate runtime use, store reads/writes and break-glass. Identify missing owners, ambiguous grants,
   unused-copy references and stale claims without asserting live presence or absence from source alone.
4. Keep existing stores/interfaces. Where implemented for the selected consumer, use
   scripts/secrets route <channel> --consumer <consumer> for local BWS metadata only. It verifies no
   access. Refusal is a gap, never authority for a value-reading alternative.
5. Update existing owner docs, skills and index within the explicit mandate. Executable changes need
   a bounded Issue with Verify targets. Provisioning, grants, rotation, revocation, deployment,
   provider contact and external changes require both task authority and the owner procedure.
6. Stop affected operations for missing ownership, authority or binding. Add no store, broker,
   access fallback, account or credential reuse. State the exact blocker and smallest allowed step.
7. Reuse tools and evidence; avoid paid dependencies, duplicate review and repeated confirmations.
   Ask only for a genuine owner choice, missing authority or an effect requiring an answer. Never
   weaken a security boundary to save time or tokens.

Return the principle, full value-free route table, actual changes and status evidence, unresolved
bounded Issues or exact blockers, and the lowest-cost next step with its owner-decision requirement.
Never claim system completion while a requested repository, owner, consumer, host or environment
remains unreviewed. Never place secret material in reports, logs, memory, Builder Vault, Issues,
PRs or receipts.
