State: Specification directory for a Builder System capability. Backlog filed; not yet implemented.
Doc role: Specification directory
Authority: Defines the BuilderOps pre-ticket model-inquiry capability and its task decomposition. BuilderOps Vault authority remains owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: ADR-0010, BuilderOps Vault contracts, and this directory for task shape.

# BuilderOps Model Inquiry

BuilderOps Model Inquiry turns one development question into a bounded, pre-ticket collaboration
between Fable and GPT/Codex. It stores the question, context packets, model turns, synthesis,
readiness outcome, and promotion evidence in the BuilderOps plane. It does not make a GitHub Issue
until the result is executable work.

The shared artifact vault is the dedicated iCloud Obsidian vault:

```text
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Yggdrasil BuilderOps/
```

This is a Yggdrasil-owned Builder System vault, separate from all human knowledge vaults. It holds
Markdown artifacts and the file-first queue. SQLite state, temporary provider credentials, and live
leases stay local to the machine that runs the worker. iCloud is not a lock service and must not host
the SQLite database or cross-device claims.

## Scope

- one command/API request creates an `inquiry_id` before any ticket or Issue exists;
- Fable and GPT/Codex receive structured context packets and review each other's artifacts;
- every model turn is traceable to its input artifacts, model identity, run, and content hash;
- a deterministic readiness gate decides `issue_ready`, `needs_input`, or `not_ready`;
- only an accepted promotion path may create a GitHub Issue through REST;
- desktop skills are thin launchers over the same BuilderOps command and state.

## Implementation Tasks

| Task | ID | Deliverable |
| --- | --- | --- |
| [External BuilderOps Vault Configuration](EXTERNAL_BUILDEROPS_VAULT_CONFIGURATION.md) | BMI-01 | Explicit shared artifact-root configuration with local-only SQLite and claims roots. |
| [Pre-Ticket Inquiry Records](PRE_TICKET_INQUIRY_RECORDS.md) | BMI-02 | Durable inquiry/run/turn records, CLI/API entrypoint, and trace query. |
| [Model Turn Adapters](MODEL_TURN_ADAPTERS.md) | BMI-03 | Structured command/API adapter contract, retries, and bounded adversarial loop. |
| [Desktop Skill Launchers](DESKTOP_SKILL_LAUNCHERS.md) | BMI-04 | Codex and Claude Desktop skill packages that invoke the shared inquiry command. |
| [Promotion And Traceability](PROMOTION_AND_TRACEABILITY.md) | BMI-05 | Readiness gate, PromotionIntent, Issue creation, and delivery lineage. |

## Execution Order

`BMI-01 -> BMI-02 -> BMI-03 -> BMI-04 -> BMI-05`

BMI-04 may be prepared after BMI-02, but cannot claim autonomous model collaboration until BMI-03
is delivered. No task is ready to make a Product/Runtime write.

## Cross-Task Invariants / Interaction Safety

1. **Vault separation.** Shared iCloud files are Builder System artifacts, never a Mimer human vault
   or Product/Runtime source of truth. SQLite and lease files are local-only.
2. **Artifact-first turns.** A model receives immutable input artifact IDs and content hashes; it
   never relies on a chat transcript as sole state.
3. **No silent promotion.** An inquiry may produce a synthesis but cannot create an Issue, PR, or
   owner-doc change without a recorded PromotionIntent and receipt.
4. **Bounded autonomy.** Provider refusal, malformed structured output, exhausted rounds, or
   unresolved blocking questions terminally record `needs_input` or `not_ready`; no model invents
   missing requirements to reach Issue-ready.
5. **Traceability survives partial failure.** Each completed turn is persisted before a successor
   call. A worker restart can resume from the latest committed turn without replaying an accepted
   provider call. Duplicate command retries use idempotency keys.

Partial failure examples:

- If iCloud is unavailable, new artifact writes fail closed; the local worker must not continue with
  an untraceable run.
- If a provider call succeeds but receipt persistence fails, the run remains incomplete and the
  provider output is not treated as an accepted turn.
- If the models reach their round limit without a common accepted artifact hash, the inquiry ends
  `not_ready` and produces no Issue.

## Capability Acceptance Criteria

- [ ] An operator can start and resume a pre-ticket inquiry from a BuilderOps command without
  copying model output between tools. Verify: `tests/builderops/test_model_inquiry_cli.py::test_start_and_resume_inquiry`.
- [ ] Each turn, synthesis, and readiness result can be traced to the source question and its input
  artifacts. Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_links_question_turns_and_synthesis`.
- [ ] Shared iCloud artifacts never place SQLite databases or live claim files in the synchronized
  vault. Verify: `tests/builderops/test_builderops_paths.py::test_shared_vault_keeps_sqlite_and_claims_local`.
- [ ] A GitHub Issue is created only after readiness and promotion evidence are recorded. Verify:
  `tests/builderops/test_model_inquiry_promotion.py::test_issue_promotion_requires_ready_receipt`.
- [ ] Desktop launcher instructions invoke the common BuilderOps command rather than a desktop-app
  automation protocol. Verify: doc writeback at `.codex/skills/start-model-inquiry/SKILL.md` and
  packaged Claude skill manifest.

## Relationship To GitHub Issues

Parent feature Issue: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288). It is the
validation hub for this capability. Child issues are #3289 (BMI-01), #3290 (BMI-02), #3291
(BMI-03), #3292 (BMI-04), and #3293 (BMI-05). They remain blocked until this specification PR is
merged, then become eligible in the listed dependency order.

## Validation / Acceptance Path

After BMI-05, run a dry-run inquiry with deterministic adapters, then a provider-enabled inquiry
with non-sensitive architecture input. Attach the run receipt, trace output, and any generated Issue
to the parent feature Issue. Promote BuilderOps owner-doc claims only after that validation.
