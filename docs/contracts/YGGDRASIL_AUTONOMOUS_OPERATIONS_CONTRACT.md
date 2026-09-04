State: Accepted target-state contract; no full runtime implementation is claimed. The owner accepted the operations-first v1/v2 direction on 2026-09-04. Current shipped truth remains in `docs/STATUS.md`, `docs/ARCHITECTURE.md`, and capability owner documents.
Doc role: Cross-surface Product/Runtime contract
Authority: Owns the common operation envelope, human/agent flow equivalence, autonomy boundary, adapter conformance, and parity acceptance rules. It does not take semantic ownership from the subsystem that owns an individual operation.
Owner subsystem: CES / Architecture for the cross-surface contract; EBF owns external protocol adapters.
Participating subsystems: HIX, GOV, EXE, WSP, HKA, SIP, PDM, DRI, RCA, OEF.
Temporal class: strategic
Review cadence: event-driven
Source of truth: target-state normative; implementation status is not authoritative here
Last reviewed: 2026-09-04

# Yggdrasil Autonomous Operations Contract

## Purpose

Make meaningful Yggdrasil domain behavior available to humans and bounded external agents without
creating separate GUI, HTTP, MCP, policy, filesystem, identity, receipt, or recovery models.

The system exposes a surface-independent operation contract. Human-facing GUI actions and agent-facing
MCP tools/resources are adapters over the same operation. Presentation behavior remains local to the
GUI. An MCP tool name is not an operation authority and a GUI control is not an implementation.

This contract serves the human need to delegate a bounded outcome once, observe what the system did,
and recover safely without confirming every individual file action. It serves the agent need to
discover typed capabilities, preflight work, execute within a grant, and receive legible terminal or
recoverable results.

## Accepted direction and current-state boundary

The accepted delivery direction is operations-first and flow-driven:

1. define one typed operation and its invariants;
2. implement or consolidate the system-owned semantic seam;
3. attach GUI/API and MCP adapters to that seam;
4. prove equivalent result and failure semantics;
5. repeat by bounded capability family.

ADR-0061 remains the external MCP v1 compatibility profile: Ask, Capture, Retrieve, Read Note, and
Health through a constituent-owned stdio sidecar over the governed HTTP API. That profile is not
capability parity. Broader autonomous operations are a versioned v2 expansion and must not silently
widen the v1 tool set or its authority.

Current runtime capabilities remain whatever their owner documents and production tests establish.
This contract does not claim a shared operations runtime, external MCP server, generic lifecycle
operations, safe batch execution, or the GUI additions below are shipped.

## Capability boundary

An operation is a typed query, proposal, or governed effect that is meaningful independently of a
surface. It owns no presentation, transport, storage backend, policy decision, or semantic meaning
outside the participating subsystem contract.

An operation MUST answer the applicable `CapabilityContract` fields and additionally declare:

- stable operation ID and semantic version;
- owning subsystem and implementation seam;
- input resource identity and selected context/vault binding;
- authority class: `read_only`, `proposal`, or `governed_effect`;
- side-effect and reversibility class;
- required delegation, policy decision, and preconditions;
- idempotency and concurrency posture;
- receipt and provenance posture;
- affected source and derived representations;
- convergence and recovery posture;
- GUI/API/MCP adapter availability and maturity;
- typed terminal and recoverable outcomes.

Transport schemas may narrow an operation but may never widen it. An adapter may translate names and
wire shapes only. It MUST preserve the operation's authority, validation, result, error, receipt,
provenance, temporal-validity, and recovery semantics.

## Operation envelope

Every invocation uses the logical `ygg.operation.v1` envelope. Its representation may differ by
language or transport, but the fields and meanings do not.

Required inputs:

- `operation_id` and `operation_version`;
- `request_id`, unique within the calling client and stable across retries;
- `actor`, `client`, and `surface` provenance;
- `active_context_ref` and, for vault work, an immutable selected-vault generation;
- typed targets expressed by stable resource identity;
- typed operation arguments;
- `mode`: `preview` or `execute` where preview is supported;
- delegation or human-intent evidence required by the authority class;
- expected resource version, create-once precondition, or explicit read-only posture;
- batch policy when more than one target is present.

Required outputs:

- the same `request_id`, operation identity/version, actor, surface, and context binding;
- one typed overall outcome and, for batches, one outcome per target;
- observed input versions and resulting versions where applicable;
- affected resource IDs and portable relative paths where disclosure is allowed;
- policy/decision, execution trace, and receipt references where applicable;
- source-of-truth effect state and derived-state convergence state separately;
- reversibility and recovery instructions;
- warnings without converting uncertainty into success.

No adapter may replace stable identity with a title, absolute path, screen row, list index, URL, or
tool-call position.

## Typed outcomes

Terminal outcomes are `succeeded`, `rejected`, `conflicted`, `not_found`, `invalid`, and
`not_supported`. Recoverable outcomes are `not_acknowledged`, `recovery_required`,
`convergence_pending`, and `degraded_read`.

`succeeded` is permitted only when the source-of-truth effect and every mandatory durable receipt
have reached their required terminal state. Projection lag may coexist with source success only as
an explicit `convergence_pending` field with a durable convergence obligation. Mutation-before-
receipt, unknown identity, ambiguous target, or unknown external outcome is never success.

Errors are typed and stable across direct invocation, GUI/API, and MCP. Transport errors may wrap a
domain outcome but may not erase it or map a recoverable unknown to success.

## Operation families and parity scope

The first parity program covers the following domain families. Each row is target scope, not a
shipped-capability claim.

| Family | Required domain behavior | Human surface obligation | Agent surface obligation |
| --- | --- | --- | --- |
| Discovery | list, read, search, related resources | browse, filter, inspect, provenance | resources/tools with equivalent filters and provenance |
| Creation | capture and create typed artifacts | intent entry, destination and result | typed create with create-once/idempotency |
| Editing | update body and allowed metadata | editor, preview/diff, conflict handling | expected-version update and typed conflict |
| Placement | move and rename without identity loss | target picker, preview, result | stable-ID move/rename with path preflight |
| Semantics | classify and set/remove tags through owner rules | legible current/proposed values | typed proposals/effects, never raw frontmatter bypass |
| Lifecycle | archive and restore through owner-native lifecycle | reason, impact, reversibility, recovery | governed lifecycle operation and receipt |
| Ordering | persist order only where an owner defines domain order | reorder affordance distinct from display sort | typed order mutation only for that owned field |
| Batch | safely apply one operation to bounded targets | multi-select, impact preview, one bounded confirmation | preflight, bounded execution, per-item outcomes |
| Context/runtime | select/init/reload context and governed settings where admitted | explicit system-control surface | exposed only under a separately declared authority grant |
| Observability | health, operation status, receipts, convergence and recovery | progress, history, conflict/recovery views | status/resources without authority gain |

Help text, menus, layout, rendering, playback controls, client-local filters, display sort, clipboard,
open-in-editor behavior, and other presentation details are not parity requirements.

Specialized Canvas, Panel, memory-review, briefing, TTS, and Ask actions remain owned by their
capability contracts. They enter this parity program only when a reusable domain operation exists;
their screen-specific interaction mechanics do not become MCP tools.

## Human flow

The common human flow is:

1. **Discover and select.** The GUI identifies resources by human-legible title/path while retaining
   stable system identity and provenance.
2. **State an outcome.** The human selects an action or describes a bounded goal.
3. **Inspect scope.** The GUI shows affected resources, boundary crossings, trust changes,
   reversibility, and material uncertainty.
4. **Delegate once.** The human confirms the bounded task or batch when the trust contract requires
   confirmation. The delegation names allowed operations, context/vault, target selector or explicit
   targets, limits, and expiry/revocation conditions.
5. **Execute and observe.** Progress distinguishes source effects, receipt persistence, and derived
   convergence.
6. **Review outcome.** Per-resource results, skipped/rejected items, conflicts, and receipts remain
   inspectable.
7. **Recover or correct.** The GUI offers resume, verify, retry, compensate, or restore only when the
   operation contract permits it.

Human confirmation is proportional. A valid bounded delegation can authorize many mechanical file
effects without per-file prompts. New semantic claims, trust upgrades, cross-domain moves,
irreversible loss, delegation expansion, or targets outside the approved selector still require the
owning human-intent gate. A client cannot manufacture or broaden delegation.

## Required GUI additions

The parity program MUST add human surfaces for any admitted domain operation that lacks a usable
human flow. At minimum the target GUI includes:

- create, move, rename, classify, tag, archive, and restore actions;
- multi-select and bounded batch execution;
- preview/diff and affected-resource inspection;
- delegation scope showing context/vault, operation set, selection rule, limits, and expiry;
- operation progress separating durable effect, receipt, and projection convergence;
- receipt/activity history with provenance and reversibility;
- conflict and recovery views for nonterminal or ambiguous outcomes;
- clear capability availability and unsupported/degraded states.

GUI parity does not mean one button per agent primitive. Humans must be able to initiate, scope,
monitor, understand, and recover the same domain outcome. Agents may use lower-level composable
operations when the same invariants and authority apply.

## Agent flow

The common mediated-agent flow is:

1. discover admitted operation/resource schemas and maturity;
2. bind the request to actor/client identity, active context/vault generation, and delegation;
3. list/read/search to resolve stable target identities;
4. submit preview/preflight for governed or batched effects;
5. execute with a stable request ID and expected versions/create-once constraints;
6. receive typed per-target outcomes, receipts, provenance, and convergence state;
7. observe status until terminal or recovery-required;
8. verify ambiguous outcomes before any retry;
9. stop fail-closed when identity, path, authority, version, integrity, or verification is unclear.

Mediated external agents use this contract. Direct-filesystem agents remain the separate observed-
write mode in `docs/AGENT-FLOWS.md`; the existence of v2 operations neither removes that mode nor
converts its OS-level writes into governed receipts.

## Autonomous delegation

A delegation is a bounded authority input, not a broad role or permanent client trust. It MUST bind:

- principal and client identity;
- active context and selected-vault generation;
- admitted operation IDs and maximum authority class;
- explicit targets or a deterministic target selector plus maximum count;
- allowed semantic, trust, lifecycle, and domain-boundary effects;
- time/turn/use limit and revocation trigger;
- batch/partial-success policy;
- required preview or confirmation conditions;
- policy version and receipt linkage.

The system re-evaluates policy and preconditions at execution time. Discovery of a tool, possession
of an MCP connection, a previous successful call, a filesystem path, or an agent's own plan never
constitutes delegation.

## Identity, path, and placement

Stable resource identity is independent of path. Move and rename preserve identity and provenance.
Delete or irreversible retirement creates an explicit terminal identity/lifecycle record when the
owner contract requires it.

Paths are canonical, portable vault-relative identifiers resolved under the immutable invocation
context. Absolute paths, traversal, symlink escape, nested-vault ambiguity, cross-context targets,
and unregistered roots fail before effects. A rename or move preflight checks source identity,
destination policy, collision posture, no-clobber semantics, and expected source/destination
versions. Suffix-on-collision is allowed only when the operation contract explicitly declares it
and returns the chosen destination.

## Concurrency, no-clobber, and idempotency

Every mutation declares one of:

- create once with fail-on-exists or contract-declared collision allocation;
- compare-and-swap against an expected resource version;
- append under an owner-defined atomic append contract;
- an owner-native transactional state transition with equivalent preconditions.

Mediated autonomous callers have no force-save or last-writer-wins bypass. The same `request_id` and
semantic input MUST converge on the same terminal result or recovery record. A changed semantic
request uses a new request ID. Crash recovery and retries re-read durable request/effect/receipt
state; they do not infer success from missing source paths or client timeout.

## Batch semantics

A batch is an envelope over one operation and a bounded deterministic target set. It is not a loop
hidden inside a transport adapter.

Before execution the system freezes target identities/versions, validates policy and paths, and
returns the execution/partial-success policy. The owning operation declares one of:

- atomic all-or-nothing;
- deterministic per-item execution with explicit independent terminal outcomes;
- staged execution with a durable recovery/compensation plan.

The system never calls a partially applied batch wholly successful. Restart resumes or reconciles
from durable per-item state. A GUI can request one confirmation for the frozen batch; an agent cannot
add targets after confirmation without a new delegation or human gate.

## Source, Store, index, and link convergence

Source-of-truth mutation and derived-state convergence are separate result dimensions. Successful
source mutation MUST durably enqueue or complete every required Store, index, backlink, relation,
and link-projection consequence. Consumers see `convergence_pending`, `degraded`, or
`rebuild_required` until those obligations settle.

Derived stores never become the only location of identity, provenance, user meaning, or recovery
authority. Rebuilding a projection from source plus durable receipts MUST reproduce the operation's
observable durable consequences or surface an owned exception.

## Receipts and provenance

Every governed effect carries the applicable PolicyDecision/DecisionToken and AuthorityReceipt
semantics. The durable record preserves:

- operation/request identity and version;
- actor, client, surface, delegation, and policy version;
- context/vault generation and stable targets;
- input and output versions;
- preconditions checked and boundary/trust deltas;
- effect and per-item outcome;
- source, Store, index, and link convergence obligations;
- reversal/recovery posture and causal trace.

Adapters may redact presentation but may not fabricate, discard, reinterpret, or treat receipt
observation as authority.

## Recovery

Every governed effect names restart behavior before implementation is admitted. Recovery detects
and reconciles partial batches, mutation-before-receipt, orphan receipts, staged conflict artifacts,
pending outbox work, identity/path drift, and derived-state mismatch.

Recovery is read/verify-first. It can resume, compensate, quarantine, request human correction, or
declare a terminal failure under the owning contract. It never performs a blind retry, silently
chooses an identity/path, upgrades trust, or reports success merely because an error disappeared.

## Adapter rules

### GUI and HTTP

The browser transports human intent. The server resolves identity, authority, validation, policy,
execution, and typed outcomes. A GUI route may compose presentation state, but domain mutation and
its preflight MUST call the owning operation. The GUI never re-derives authority from a response.

### MCP v1 compatibility profile

ADR-0061's five operations retain their exact boundary until separately superseded. The stdio
sidecar delegates to the governed HTTP surface and exposes no generic vault write, receipt-readback,
direct-filesystem fallback, hidden queue, network listener, or internal ToolProvider reuse.

### MCP v2 parity profile

Only contract-ready operations may be mapped. MCP discovery exposes operation version, schemas,
authority/side-effect class, preview support, and maturity. Tool/resource implementations delegate
to the same operation seam as GUI/API and add no policy, filesystem, retry, receipt, identity, or
recovery behavior of their own.

## Conformance and acceptance

Each implemented operation has one conformance corpus executed through:

1. direct application-operation invocation;
2. the production GUI/API adapter;
3. the external MCP adapter.

The corpus asserts equivalent target selection, authority result, validation, effect, typed outcome,
receipt/provenance, conflict, idempotency, and recovery behavior. Presentation payloads and transport
status may differ only where the adapter contract names the mapping.

Capability parity is accepted only when:

- every required family has an owned operation or an explicit `not_supported` disposition;
- human-flow scenarios cover delegation, preview, execution, observation, and recovery;
- agent-flow scenarios cover discovery, preflight, autonomous bounded execution, retry, and recovery;
- bypass tests show no GUI/API/MCP mutation path skips the owning operation;
- hostile path, collision, CAS, concurrency, partial-failure, restart, and batch suites pass;
- Store/index/link convergence and doctor probes pass;
- a real external MCP client completes the composed journey in an isolated runtime;
- current-state owner docs are promoted only after that evidence exists.

Tool discovery, unit tests with fakes, green HTTP tests, or a rendered GUI alone do not establish
parity.

## Invariants

The canonical enforcement rows live in `docs/testing/invariant-tests.md :: Autonomous operations
and cross-surface parity`. This contract owns their meaning; OEF owns the probe registry.

Minimum kernel:

- stable identity;
- canonical path and immutable context scope;
- bounded authority and policy re-evaluation;
- CAS/create-once/no-clobber;
- effect plus mandatory receipt terminality;
- idempotent verify-before-retry recovery.

Batch, derived-state convergence, and complete provenance are mandatory whenever those capabilities
are present.

## Transition plan

1. Contract and register the common envelope, flows, outcomes, and invariant probes.
2. Deliver direct-operation conformance support and the minimum invariant kernel.
3. Consolidate list/read/search, then capture/create/edit, behind owned operations.
4. Deliver identity-preserving move/rename.
5. Deliver classify/tag through semantic owners.
6. Deliver archive/restore by composing the Governed Archival Flow.
7. Deliver persistent ordering only where a domain owner defines it.
8. Deliver bounded batch and restart recovery.
9. For every vertical slice, attach/replace GUI/API and MCP adapters and run the same corpus.
10. Complete live external MCP and human-flow acceptance before promoting capability-complete truth.

Existing behavior is migrated incrementally. This contract does not require a new monolithic service,
registry, database, queue, or policy engine. Implementations SHOULD extract reusable semantics from
current owner seams and replace route-local duplication.

## Non-goals

- Mirroring every GUI detail into MCP.
- Treating HTTP route count or tool count as capability parity.
- Creating a parallel filesystem, policy, identity, transaction, receipt, or recovery model.
- Giving agents permanent unrestricted vault authority.
- Requiring per-file confirmation inside an already approved bounded batch.
- Treating display sorting as a persistent domain mutation.
- Replacing direct-filesystem agent participation.
- Claiming current implementation, external MCP runtime, or production readiness from this contract.

## Linked source-of-truth documents

- `docs/PROJECT_KERNEL.md`
- `docs/ARCHITECTURE.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/contracts/CAPABILITY_CONTRACT.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/EXECUTION_REQUEST.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/contracts/GOVERNED_ARCHIVAL_FLOW.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`
- `docs/AGENT-FLOWS.md`
- `docs/HUMAN-FLOWS.md`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`
- `docs/adr/ADR-0055-vault-multi-writer-consistency.md`
- `docs/adr/ADR-0061-mimer-mcp-client-adapter.md`
- `docs/testing/invariant-tests.md`
