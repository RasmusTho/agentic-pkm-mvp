State: Target-state contract stub; the real-tool append seam is implemented,
while broader execution routing is not fully implemented under this shape.
Doc role: Contract stub
Authority: Owns the EXE side-effect request seam after GOV authorization.
Owner subsystem: EXE - Capability Execution & Automation
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# ExecutionRequest

## Purpose

Separate cognitive planning from side-effecting execution by requiring authorized execution requests, previews/dry runs where possible, result reporting, and trace/receipt linkage.

## Inputs

- Requested side effect.
- Actor/principal.
- Resource target.
- DecisionToken reference for governed effects.
- ActiveContextSet reference.
- Tool/provider adapter reference.
- Dry-run/preview preference.

## Outputs

- Execution status.
- Preview or dry-run result.
- Effect result.
- Rollback result where possible.
- Execution receipt/trace linkage.

## Commands

- Preview.
- Dry run.
- Execute.
- Roll back where possible.
- Report result.
- Normalize external effect response.

## Queries

- What ran?
- Which DecisionToken authorized it?
- What failed?
- Which receipt/trace records apply?
- Is rollback available?

## Events

- `execution.requested`
- `execution.previewed`
- `execution.started`
- `execution.succeeded`
- `execution.failed`
- `execution.rollback_attempted`

## Invariants

- EXE knows how to execute; GOV decides whether execution is admissible.
- CAO does not perform unmanaged tool side effects.
- Authority-bearing durable effects require a DecisionToken reference that is
  bound to the actor, action, effect class, and target before EXE runs.
- Resource references use GOV's canonical form (including slash normalization)
  consistently when tokens and receipts are validated across retries.
- The serialized EXE/GOV note reference uses that canonical form, while the
  writer and recovery code retain the exact filesystem `Path` for access.
- A factual EXE effect receipt and the GOV AuthorityReceipt are distinct facts;
  success is withheld until both are durably recorded.
- Result linkage is visible to OEF and GOV.

## Allowed Producers

- CAO workflows.
- HIX human-command surfaces.
- Automation triggers under GOV policy.

## Allowed Consumers

- EXE runners, EBF tool/provider adapters, GOV receipts, OEF traces, HIX status surfaces.

## Forbidden Use

- Do not use ExecutionRequest to bypass policy.
- Do not let EXE decide semantic authority internally.
- Do not hide failed external side effects.

## Failure Modes

- Agent runtime performs side effects without EXE/GOV seam.
- Execution mechanism becomes authority.
- Rollback/preview posture is implied but not recorded.

## Transitional Implementation Notes

Existing tool/MCP/provider execution paths should be wrapped before widening autonomous or agent-triggered side effects.

A first transitional adapter lives in `app/execution/execution_request.py`: frozen
`ExecutionRequest` and `ExecutionResult` dataclasses plus `CONTRACT_VERSION`,
mirroring `app/governance/governed_write.py`. It reuses the `DecisionToken` type
from `app.governance.governed_write` rather than redefining it, so EXE and GOV
share one authorization vocabulary.

The first wrapped side effect is the real-vault `mcp.vault.append_note` write in
`app/orchestrator/executor.py` (`MockPlanExecutor._run_vault_append`, reached via
`_execute_tool_call` -> `_invoke_tool`). The wrapper is additive and lives behind
the existing real-tool gate (`_should_use_real_tool`), so mock/CI behavior and
tool policy are unchanged. The `ExecutionRequest`/`ExecutionResult` carry
`context.trace_id` (and `context.agent_id` as actor) so trace linkage rides the
already-emitted `mcp.tool_call.started` / `mcp.tool_call.finished` events.

The orchestrator real-tool `mcp.vault.append_note` path now obtains its
DecisionToken in the preceding GOV authority step, validates the binding again
at the EXE seam, and refuses to call the vault writer when the token is missing
or mismatched. The effect is assigned a stable identity. Its factual
`ExecutionResult` and distinct `AuthorityReceipt` are persisted through the
existing outbox before success is returned. Recovery replays an effect only
after resolving the same configured vault root used by the writer and parsing
the writer's line-delimited frontmatter format losslessly: delimiter substrings
inside a title and intentional leading blank body lines are preserved. It then
requires one note whose frontmatter metadata, title, tags, body, and `_mcp`
destination match the effect identity and request; arbitrary body text is not
proof. If a note carries the effect identity but its authorization, content, or
destination conflicts, recovery is indeterminate and refuses to call the
writer. The note also persists the original authorizing DecisionToken. A retry
may receive a fresh DecisionToken for the retry request, but the recovered
effect retains the original token for its `ExecutionResult` and
`AuthorityReceipt`; the retry token is recorded separately. If a known effect
path cannot be read or its frontmatter cannot be parsed, recovery is
indeterminate and refuses to call the writer rather than treating the evidence
as absent. The same fail-closed rule applies when `_mcp` inventory enumeration
fails, or when a retained positive path hint contains valid note metadata for a
different effect identity. An absent initial `_mcp` directory is treated as no
prior evidence so the first append can create it.
An unreadable or malformed existing outbox receipt is also indeterminate; retry
does not treat it as absent and cannot invoke the writer.
Any known authority event identified by the stable effect event ID or matching
effect identity must contain a succeeded EXE result, original token provenance,
and an applied AuthorityReceipt with complete, internally consistent linkage:
the request actor/resource and exact request arguments must match the current
effect, the EXE receipt reference and AuthorityReceipt source reference must
identify the same note path, and all AuthorityReceipt accountability fields
must be present and agree with the original token and EXE result. Missing or
mutated receipt identity, source reference, request binding, or note path is
indeterminate and refuses recovery. A valid receipt replays only the
notification stage.

A same-process guard serializes lookup and append for one effect. This is the
only concurrency guarantee in this slice. Cross-process cooperating-writer
serialization and anchored identity CAS remain owned by Issue #4659's whole
append transaction, and #4659 does not migrate this orchestrator consumer. If
the #3553 parent acceptance contract requires cross-process same-effect
exclusion for this consumer, that requirement needs a separately owned
consumer gate with an explicit owner and `Verify:` target. This slice adds no
durable lock, competing append journal, or global transaction, and does not
claim that broader guarantee.

The `decision_token` field remains optional on the generic dataclass so mock and
read-only execution requests can retain their additive shape. It is mandatory
for this authority-bearing real-tool path.

The former **Transitional DecisionToken gap** was the pre-enforcement state in
which this orchestrator path passed `None`; that historical state is no longer
the contract for real-tool effects.

## Open Questions

- Which side-effect classes require preview or dry-run before execution?
- Which rollback guarantees are practical versus best-effort diagnostics?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md`
- `docs/EVENTS.md`
