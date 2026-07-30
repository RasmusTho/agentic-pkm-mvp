State: BMI-01 through BMI-05 are implemented; parent end-to-end acceptance remains pending. The
configured remote host owns its subscription session and host-specific launcher settings. Under
ADR-0064's 2026-07-30 owner-cost ruling, that subscription-backed session is the sanctioned
operational auth for host-local Builder model inquiry. The provider-free intent, declared
provider-API adapters, and high-reasoning policy remain versioned for any future metered path, but
their API-key identifiers are intentionally unprovisioned and currently fail closed as
`credential_unavailable`. The Model Inquiry subscription exception is never a CKM source or
fallback.
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

The shared artifact vault is configured per machine through `BUILDEROPS_VAULT_ROOT`. The current
deployment uses a dedicated iCloud Obsidian vault owned by Yggdrasil, separate from all human
knowledge vaults. It holds Markdown artifacts, queue files, receipts, transient worker state, and
TTL-based advisory claim signals. SQLite state, authoritative dispatcher leases, and temporary
provider credentials stay local to the machine that runs the worker. iCloud is not a lock service;
its advisory claim files never guarantee exclusive ownership.

## Scope

- one command/API request creates an `inquiry_id` before any ticket or Issue exists;
- Fable and GPT/Codex receive structured context packets and review each other's artifacts;
- every model turn is traceable to its input artifacts, model identity, run, and content hash;
- a deterministic readiness gate decides `issue_ready`, `needs_input`, or `not_ready`;
- only an accepted promotion path may create a GitHub Issue through REST;
- desktop skills transfer one question to the configured remote-host launcher, which owns the same
  BuilderOps command and state while using the sanctioned host-local subscription-backed session.
  The separate declared provider-API mechanism remains fail-closed while its metered credentials are
  intentionally unprovisioned.

## Implementation Tasks

| Task | ID | Deliverable |
| --- | --- | --- |
| [External BuilderOps Vault Configuration](EXTERNAL_BUILDEROPS_VAULT_CONFIGURATION.md) | BMI-01 | Explicit shared artifact-root configuration with local SQLite and shared advisory claims. |
| [Pre-Ticket Inquiry Records](PRE_TICKET_INQUIRY_RECORDS.md) | BMI-02 | Durable inquiry/run/turn records, CLI/API entrypoint, and trace query. |
| [Model Turn Adapters](MODEL_TURN_ADAPTERS.md) | BMI-03 | Structured command/API adapter contract, retries, and bounded adversarial loop. |
| [Desktop Skill Launchers](DESKTOP_SKILL_LAUNCHERS.md) | BMI-04 | Codex and Claude Desktop skill packages that delegate to the configured remote-host inquiry launcher. |
| [Promotion And Traceability](PROMOTION_AND_TRACEABILITY.md) | BMI-05 | Readiness gate, PromotionIntent, Issue creation, and delivery lineage. |

BMI-02 stores its durable record graph under
`$BUILDEROPS_VAULT_ROOT/model-inquiries/<inquiry_id>/`. The CLI and HTTP routes share one service;
`resume` only returns a restart plan until BMI-03 supplies bounded provider execution.

BMI-03 adds `builderops inquiry run`. Its `--dry-run` mode is deterministic and read-only;
provider-enabled mode uses explicit per-role adapters, strict response validation, durable terminal
receipts, and no provider fallback.

BMI-04 adds Codex and portable Claude bridge skills that transfer the question to a configured
remote-host launcher. The configured remote host owns the BuilderOps command, configured role
adapters, subscription session, and durable artifacts; its authentication and launcher-path settings
remain outside Git. The current host-local operational path uses the sanctioned subscription-backed
session under the owner-cost ruling. The versioned provider-API path remains a separate mechanism:
it submits provider-free intent, resolves distinct targets through the Builder census, and requires
explicit `xhigh` reasoning, but intentionally absent metered credentials produce a durable typed
`credential_unavailable` receipt before any adapter call. That failure does not select a subscription
or cross-provider fallback. The explicit Model Inquiry subscription exception is confined to this
host-local capability and cannot execute CKM semantic association.
BMI-05 adds the structured Issue proposal, readiness receipt, file-first
PromotionIntent, REST-only Issue crossing, crash reconciliation marker, and append-only delivery
references.

## Execution Order

`BMI-01 -> BMI-02 -> BMI-03 -> BMI-04 -> BMI-05`

BMI-04 may be prepared after BMI-02, but cannot claim autonomous model collaboration until BMI-03
is delivered. No task is ready to make a Product/Runtime write.

## Cross-Task Invariants / Interaction Safety

1. **Vault separation.** Shared iCloud files are Builder System artifacts, never a Mimer human vault
   or Product/Runtime source of truth. SQLite, provider credentials, and authoritative dispatcher
   leases are local-only; vault claim files are shared TTL advisory signals only.
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

- [x] An operator can start and resume a pre-ticket inquiry from a BuilderOps command without
  copying model output between tools. Verify: `tests/builderops/test_model_inquiry_cli.py::test_start_and_resume_inquiry`.
- [x] Each turn, synthesis, and readiness result can be traced to the source question and its input
  artifacts. Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_links_question_turns_and_synthesis`.
- [x] Shared iCloud artifacts never place SQLite databases or provider credentials in the
  synchronized vault, and claim files remain explicitly advisory. Verify:
  `tests/builderops/test_builderops_paths.py::test_shared_vault_bootstrap_creates_advisory_claims_but_never_sqlite`.
- [x] A GitHub Issue is created only after readiness and promotion evidence are recorded. Verify:
  `tests/builderops/test_model_inquiry_promotion.py::test_issue_promotion_requires_ready_receipt`.
- [x] Desktop launcher instructions transfer the question to the configured remote-host launcher rather
  than starting local BuilderOps or automating a desktop app. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] A terminal adapter failure produces a secret-safe diagnostic receipt and one desktop-launch
  JSON result without fallback or retry. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_local_launcher_emits_terminal_provider_error_json`.

## Relationship To GitHub Issues

Parent feature Issue: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288). It is the
validation hub for this capability. Child issues are #3289 (BMI-01), #3290 (BMI-02), #3291
(BMI-03), #3292 (BMI-04), and #3293 (BMI-05). They remain blocked until this specification PR is
merged, then become eligible in the listed dependency order.

## Validation / Acceptance Path

After BMI-05, run the deterministic dry-run and the repo-verifiable contract checks. Under the
ADR-0064 owner-cost ruling, parent acceptance does not request a metered provider-API inquiry,
provision API keys, or retire the sanctioned subscription bridge. Ordinary host-local inquiries
continue through the sanctioned subscription-backed session; that operational path is Model
Inquiry-only and never a CKM credential source or fallback. Promote BuilderOps owner-doc claims only
after the remaining parent validation is satisfied.
