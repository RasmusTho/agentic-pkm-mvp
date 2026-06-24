State: Target-state mapping; current implementation may contain transition debt.
Doc role: Mapping register
Authority: Maps current architecture concepts/docs/modules to target SBS owners. Does not claim current implementation matches target boundaries.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-24
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/ARCHITECTURE.md, docs/STATUS.md, docs/ENVIRONMENTS.md, docs/VAULT_OPTIONAL_RUNTIME/README.md

# SBS Current-To-Target Mapping

Use this map when changing an existing area and classifying target SBS impact. The target owner is the long-horizon control boundary, not proof that the code already has that module or enforcement.

| Current area | Target owner(s) | Notes | Transition risk |
|---|---|---|---|
| Current architecture baseline | HKA, GOV, PDM, DRI, RCA, MEM, CAO, EXE, OEF | `docs/ARCHITECTURE.md` owns shipped runtime wiring. SBS ownership is used for impact classification only. | Target-state wording can be misread as shipped behavior. |
| Current system-of-systems spine | CES practice, all target subsystems | `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` remains the current eight-subsystem bridge. | Current eight-subsystem map can hide target boundaries that split storage/projection/memory/sync/execution. |
| Human surface / UI | HIX, WSP, GOV, OEF | Obsidian, Panel, Chat/canvas, CLI, HTTP API, and Companion UI are interaction surfaces. | UI state can become authority if not routed through owner contracts. |
| Obsidian / vault interaction | HIX, EBF, HKA, WSP | Obsidian and vault files are current mechanisms and durable surface bindings. | Obsidian/vault can be treated as identity rather than adapter/source binding. |
| Vault model | WSP, HKA, EBF, PDM | Current vault-first runtime maps to ActiveContextSet, ArtifactContract, source binding, and store resolution. | `activeVault`/vault path may leak as a global architecture primitive. |
| Retrieval | RCA, DRI, EBF, OEF | Retrieval is a context-assembly capability over derived representations and source evidence. | Ranked evidence can be mistaken for accepted knowledge. |
| Embeddings | DRI, EBF, RCA, OEF | Embeddings are rebuildable derived representations behind provider adapters. | Provider/model fields can leak into core semantics. |
| Memory | MEM, GOV, HKA, SIP, RCA | Current memory surfaces map to inspectable MemoryRecord lifecycle plus governed promotion into HKA when needed. | Unreviewed memory can become hidden instruction or shadow knowledge. |
| Agents | CAO, RCA, MEM, GOV, EXE, OEF | Agents coordinate cognition and workflow; side effects route through EXE after GOV. | Agent runtime may absorb retrieval, memory, policy, or execution authority. |
| Tool execution | EXE, GOV, EBF, OEF | Tool/MCP/provider calls are external mechanisms and side effects after authorization. | Direct CAO/tool calls can bypass GOV/EXE. |
| Governance/write guards | GOV, HKA, EXE, OEF | Existing WriteGuard, receipts, APPLY gates, and policy surfaces map to GOV decisions and receipts. | Governance can be advisory only, or become a mechanism god-core. |
| Persistence/storage | PDM, HKA, GOV, MEM, DRI, SFC | Stores and migrations are PDM mechanics; state-owning subsystems own semantics. | Direct DSN/table construction outside PDM creates storage leak. |
| Runtime projection | DRI, PDM, OEF | DB/index/projection state is rebuildable unless explicitly classified otherwise. | Derived records can carry non-rebuildable meaning. |
| Watchers | EBF, SFC, DRI, OEF | Watchers are source observation adapters; delivery semantics must be explicit. | Events can be well-shaped but lack delivery, replay, or idempotency semantics. |
| Runtime lifecycle | WSP, EBF, EXE, PDM, OEF | Start/stop/idle/boot of long-lived runtime processes (watcher, worker) and their binding to the active vault. **WSP owns the lifecycle-binding authority** (should a process run, bound to which context — input is `ActiveContextSet`, not `activeVault`); the **mechanism** stays distributed: EBF watcher adapter attach/detach, EXE process start/stop/re-point as governed effects, PDM per-environment store/runtime-state lifecycle, OEF observes (no control loop). See `docs/SYSTEM_BREAKDOWN_STRUCTURE.md :: Runtime lifecycle ownership` (decision #2473). Current reality lives in ops scripts + `PKM_ENVIRONMENT` (`docs/ENVIRONMENTS.md :: Runtime Control Surface`) and the no-vault idle/boot posture (`docs/VAULT_OPTIONAL_RUNTIME/README.md`). | Process supervision falls between EBF/EXE/OEF and stays outside the SBS as ops-script-only (transition debt D13); lifecycle decisions can leak a scalar `activeVault` instead of consuming `ActiveContextSet` (D1). |
| Sync | SFC, WSP, GOV, PDM, HKA, SIP, OEF | Current single-node posture maps to SFC as a no-op/single-authoritative-node boundary. | Sync can be postponed until it resolves meaning through ad hoc rules. |
| Observability | OEF, GOV, CES practice | Health, traces, metrics, evals, and CI fitness map to OEF and stewardship. | OEF findings can mutate behavior without governance if control loops are introduced. |
| Docs / roadmap / issue processes | CES practice, OEF, all owners | ADRs, contracts, registers, roadmap, PR template, and issues are the stewardship surface. | Documentation can drift back into implementation structure without owner checks. |

## Mapping Rule

Do not claim target ownership as current implementation status. Use this map to decide which contract, register, debt item, or fitness rule a change must update.
