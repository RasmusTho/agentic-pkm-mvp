State: Advisory audit snapshot (2026-08-31). Bound to `origin/main` and detached `HEAD` at `41b706be44fff71a85f4f4f87d8e39e91ab17fe9`, read at `2026-08-31T17:22:54Z`. Subordinate to owner contracts and live GitHub authority.
Doc role: Reference (architecture audit)
Authority: Evidence-based structural analysis only. This artifact creates no implementation, contract, issue, PR, merge, deployment, backup, restore, or destructive authority.
Owner: Architecture / CES boundary, with HKA, SIP, GOV, PDM, DRI, and BuilderOps owner contracts retaining their existing authority.
Temporal class: Point-in-time audit; refresh after owner-contract, runtime, or lifecycle changes.
Source of truth: Human-authored/accepted artifacts and governance receipts are durable; machine projections and operational state are classified below.

# Rebuildability and Recovery Authority Audit

## 1. Question and method

This audit answers whether the current system can lose or corrupt databases, indexes, embeddings,
queues, caches, projections, and other non-document material while retained human documents and
document-backed receipts remain the continuity source. It was triggered by the historical HKA
recovery proposal resurfacing.

The pass used four bounded, read-only evidence lanes against the same snapshot:

| Lane | Coverage | Primary anchors |
| --- | --- | --- |
| Authority | HKA, semantic authority, portability, runtime/durable boundary | `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`; `docs/SEMANTIC_AUTHORITY_MATRIX.md`; `docs/CONCEPTS/PORTABILITY_CONTRACT.md` |
| Derivation | Stores, indexes, embeddings, queues, rebuild declarations and tests | `app/stores/pg.py`; `docs/DB_SCHEMA.md`; `docs/EVENTS.md`; `tests/architecture/test_semantic_boundary_fitness.py` |
| Archival | HKA recovery, derivative disposition, raw-media exception, GAF status | `docs/contracts/GOVERNED_ARCHIVAL_FLOW.md`; `docs/GOVERNED_ARCHIVAL_FLOW/README.md`; `docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md` |
| Operations | Instance state, BuilderOps recovery state, backup/runbook claims, live issue/PR state | `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`; `app/instance/instance_state.py`; `app/builderops/control_plane/migrations/0002_recovery_state.sql`; Issues #5062/#5067/#5068; PR #5094 |

Evidence classes used here are **established** (directly stated by current owner docs/code/live
GitHub), **interpretation** (classification against the owner's rebuildability direction), and
**unknown** (requires an owner decision or live operational proof). No runtime host was modified or
treated as proof of deployment/recovery readiness.

## 2. Executive result

The semantic authority model is coherent and largely conforms to the stated direction:

- retained human knowledge artifacts and companion notes carry meaning;
- governance receipts are durable accountability records;
- Postgres rows, indexes, embeddings, retrieval/render caches, search/graph projections, and runtime
  state are not independent semantic authority; and
- a database representation must be reconstructible from the durable source set.

The main unresolved boundary is operational safety state. The current code and owner docs include
crash-recoverable journals, host ownership/lease state, protected instance-state backups, and a
BuilderOps recovery fence containing `recovery_id` and `restored_lsn`. These do not claim Product
meaning, but several are not demonstrably reconstructible after total loss from human documents
alone. They therefore cannot be silently relabeled as disposable, and they cannot be silently
promoted to a second source of truth.

The correct disposition is an owner decision about a narrow operational exception: either make each
such state rebuild-safe and fail closed after loss, or explicitly retain its recovery/accountability
record on a document-/receipt-backed surface. No implementation should begin from the historical
HKA recovery proposal until that boundary and the owner-native recovery profile are selected.

## 3. Anchored findings

### F1 — Established conformity: human documents and receipts are the continuity set

`MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` defines vault notes and companions as durable source
of meaning, receipts as durable governance records, and runtime/session state as non-authoritative;
its mirror table makes DB representations, vector indexes, retrieval caches, workspace/search/graph
projections rebuildable (`:: Canonical authority`, `:: Mirror types`, `:: Rebuild semantics`). The
semantic matrix repeats the same split: HKA, companions, receipts, and governance objects are not
rebuildable, while DB representations, embeddings, indexes, context bundles, and caches are
rebuildable (`docs/SEMANTIC_AUTHORITY_MATRIX.md:52-70,126-130`). Portability makes loss of a derived
artifact a rebuild problem, not a loss-of-meaning problem (`docs/CONCEPTS/PORTABILITY_CONTRACT.md:7-14,49-54`).

**Disposition:** conforming current-state contract. Preserve as the baseline; do not infer DB
authority from operational necessity.

### F2 — Established conformity with a required loss test: machine mirrors declare rebuild sources

The concrete Postgres object store, vector index, and relation index declare vault/object or
frontmatter-derived rebuild sources in `app/stores/pg.py` (`PgObjectStore.rebuild_source`,
`PgVectorIndex.rebuild_source`, and relation-index rebuild source). The architecture fitness test
requires concrete stores/indexes to declare `rebuild_source`
(`tests/architecture/test_semantic_boundary_fitness.py`). `docs/DB_SCHEMA.md` explicitly calls the
DB a representation layer whose state is rebuildable from vault notes and companions, while
`docs/EVENTS.md` requires consumers to rebuild projections from the append-only log.

This is not yet a complete total-loss proof. Runtime currently requires the DB and treats the DB
outbox as the canonical worker queue (`docs/OPERATIONS.md:169-173`); therefore “rebuildable” means
“reconstruct before readiness/use,” not “the process can continue with a silently empty or stale
projection.”

**Disposition:** conforming architecture with a missing cross-store loss/corruption proof. Add the
test kernel below before treating rebuildability as verified.

### F3 — Bounded receipt exception is already aligned, provided it remains document-backed

The decision-receipt design moves canonical decision accountability to a WriteGuard-gated,
append-only JSONL log under the vault system directory and keeps Postgres as a rebuildable query
projection (`docs/DECISION_RECEIPT_LOG/README.md:61-92`). Its backup consequence explicitly reduces
DB backup scope to genuinely DB-only operational content (`:: Backup consequence`, lines 94-98).
This is a durable receipt/document exception, not a non-document DB authority exception.

**Disposition:** justified and conforming. Preserve the distinction between retained receipt bytes
and the DB projection; do not broaden it into general DB backup authority.

### F4 — Bounded raw-evidence retention is a separate class, not a general recovery precedent

The archival material distinguishes retained human/source artifacts, rebuildable derivatives, and
governance evidence; GAF explicitly excludes embeddings, indexes, caches, and default derivative
archival (`docs/GOVERNED_ARCHIVAL_FLOW/README.md:171-178`; `docs/contracts/GOVERNED_ARCHIVAL_FLOW.md:44-57`).
Heimdal/raw-media retention and erasure have class-specific consent/retention authority and
all-representation evidence. That exception protects raw evidence and legal/consent outcomes; it
does not make a DB, queue, or index a retained source.

**Disposition:** justified class-specific exception. Keep separate from the rebuildability kernel.

### F5 — Owner-decision conflict resolved: instance-state journal, lease, and backup surfaces

The current MVR/deployment contract requires private instance state, a crash-recoverable
transaction journal, a host-global ownership ledger, durable deployment leases/fences, verified
registry/ledger/key backups, and an optional verified restore path
(`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:151-190`; `docs/MULTI_VAULT_RUNTIME/ESTABLISH_INSTANCE_VAULT_REGISTRY.md:307-329`).
The implementation has `InstanceStateBackup` and a narrow lost-lease recovery backup
(`app/instance/instance_state.py:548-645`). These records protect ownership, fencing, and
partial-failure safety rather than Product meaning, but the evidence does not show that their
recovery lineage can be reconstructed from retained human documents after total loss.

**Disposition:** the accepted owner decision in section 8 selects option (b): loss of these records
starts a new fenced, fail-closed epoch and re-derives only from current source, configuration, and
owner-native readback. Existing partial-failure safeguards remain in force until the bounded MVR
contract and implementation slices replace their restore assumptions; this audit does not weaken
them or claim that transition work has shipped.

### F6 — Contract/code tension: BuilderOps is rebuildable, but recovery metadata presupposes restore

Current BCP contracts state that BuilderOps operational state is rebuildable from repository,
attested images, configuration, and secret custody; backup/restore is deferred and never an
activation gate (`docs/BUILDEROPS_CONTROL_PLANE/AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md:1-22`; `docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md:16-24`).
The live migration still creates `builderops_recovery_state` with `recovery_id`, `restored_lsn`, a
reconciliation fence, and executor disablement, and the store uses that state after restoration
(`app/builderops/control_plane/migrations/0002_recovery_state.sql:1-19`; `app/builderops/control_plane/store.py:340-457`).

This is not evidence that BuilderOps DB is Product truth, nor that backup is an admission gate. It
is evidence that a restored/rebuilt authority needs explicit external-effect reconciliation and
that some recovery metadata cannot be inferred from a blank database without a defined bootstrap
receipt/readback.

**Disposition:** the accepted owner decision preserves the no-backup-gate rule and selects an
explicit fresh-bootstrap loss path: fresh DB seed, authority epoch/fence initialization, external
GitHub readback, and durable document-backed receipts for accountability. The bounded BuilderOps
slice must reconcile current restore-oriented metadata with that policy. No WAL/DR implementation
is implied or claimed as shipped by this audit.

### F7 — Low-risk documentation drift: audit JSONL backup wording

`docs/OPERATIONS.md:169-173,634-655` says `INDEX_OUTBOX_PATH` is audit/diagnostic-only and not the
worker queue, while `docs/DEPENDENCIES.md:61-63` says to add log rotation/backups for that path.
The latter can be read as a backup requirement despite the source-of-truth contract. The separate
nightly prod dump watcher is also explicitly an operational/observability surface, while the DB
snapshot contract says dumps are dev/test ergonomics or on-demand forensic material, not scheduled
DR (`docs/OPERATIONS.md:528-551,774-822`; `docs/OBSERVABILITY_STABILIZATION/README.md:25-29`).

**Disposition:** documentation reconciliation, not runtime recovery. Clarify that JSONL/dump
retention may preserve diagnostic evidence but never restores semantic authority, readiness, or
worker-queue truth. Do not expand it into a DB backup/restore program.

### F8 — Historical proposal resurfaced, but current authority supersedes it

The July BuilderOps audit proposed pre-import backup, continuous WAL, restore-through-watermark,
and BCP-INV-07 as a mandatory cutover gate (`docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md:113-120,139-170,196-218`).
The current BCP owner contract is amended by #5056 and explicitly says rebuildability is required,
backup/restore is deferred, and backup/restore evidence is not an activation gate. The historical
proposal is therefore obsolete target-state material, not a current recovery requirement.

**Disposition:** retire/supersede the historical proposal through the normal docs-governance lane
when authorized; do not implement WAL/backup solely because that audit resurfaced.

## 4. Minimal testable invariant kernel

These are audit recommendations, not promoted runtime contracts. `MUST` is a runtime fail-loud
property, `GATE` is a CI/validation property, and `DOCTOR` is a read-only reconciliation property.

### MUST

- **REBUILD-MUST-01 — Source authority survives mirror loss.** With retained human documents,
  companions, and document-backed receipts intact, loss or corruption of any DB, index, embedding,
  cache, projection, or queue cannot change semantic meaning or authority.
- **REBUILD-MUST-02 — Every derived state has a replay tuple.** A persisted derived record carries
  source identity, source generation/content identity, and recipe/transform version; missing or
  mismatched provenance refuses rebuild/use rather than becoming source authority.
- **REBUILD-MUST-03 — Rebuild is fail-closed.** An empty/corrupt derived store is reinitialized
  only from its declared durable source and recipe. Readiness/use remains blocked until the rebuild
  and integrity check complete; no silent memory or stale-mirror fallback is permitted.
- **REBUILD-MUST-04 — Operational safety state is classified.** A lease, journal, recovery fence,
  or ownership record is either document-/receipt-backed or explicitly rebuild-safe. If its lineage
  is missing, the system fences and requests reconciliation; it must not invent ownership or resume
  effects.
- **REBUILD-MUST-05 — Receipt authority is not projected backward.** A DB projection, queue, or
  backup dump can accelerate lookup or diagnosis but cannot originate semantic meaning, governance
  authority, or a terminal recovery claim.

### GATE

- **REBUILD-GATE-01 — Total-loss fixture.** Start with retained source docs/companions/receipts and
  empty stores; ingest, build projections/indexes/embeddings, and compare canonical identities and
  meaning-bearing fields with the pre-loss baseline.
- **REBUILD-GATE-02 — Corruption/refusal fixture.** Corrupt each derived store and remove or alter
  one source/recipe tuple; the doctor/readiness path produces a typed failure and never serves the
  corrupted representation as authority.
- **REBUILD-GATE-03 — Queue reconstruction fixture.** Rebuild an empty queue/projection from its
  retained append-only source or explicit source event log; verify duplicate/replay behavior and
  that no JSONL diagnostic line is treated as a canonical worker-queue row.
- **REBUILD-GATE-04 — Operational-loss fixture.** Remove instance/BuilderOps recovery metadata
  while preserving source docs and external authority; verify the selected owner policy (rebuild or
  retained receipt) and a fenced, readback-based reconciliation path. This gate remains undefined
  until F5/F6 owner decisions are made.

### DOCTOR

- **REBUILD-DOCTOR-01 — Inventory completeness.** Every durable non-document path is classified as
  derived, runtime/discardable, receipt/trace, or explicit operational exception with owner and
  rebuild/retention source.
- **REBUILD-DOCTOR-02 — Mirror consistency.** Detect missing source identity, stale generation,
  missing recipe, orphaned projection, index identity drift, and DB/source mismatch without mutating
  owner state.
- **REBUILD-DOCTOR-03 — No hidden authority.** Detect a projection, backup, queue, journal, or
  runtime record being used as the sole source for human meaning, governance accountability, or
  action authorization.

## 5. Explicit research-question answers

### RQ1 — What is authoritative and what is rebuildable?

Human-authored/accepted knowledge, companions, and governance receipts are the durable continuity
set. Machine DB representations, indexes, embeddings, caches, search/graph projections, and context
bundles are rebuildable support. Runtime/session/workflow/UI state is discardable unless a governed
transition makes a receipt or durable artifact. Instance ownership/lease/journal and BuilderOps
recovery metadata are operational safety state and remain unresolved exceptions, not semantic truth.

### RQ2 — Where do backup, restore, archive, or durable-journal requirements occur?

They occur in four distinct forms:

1. document-/receipt-backed durability for human meaning and governance decisions;
2. class-specific raw-evidence archival/retention;
3. MVR instance-state journals, leases, ownership ledgers, protected backups, and restore paths;
4. BuilderOps recovery fencing metadata plus operational forensic/diagnostic dump watchers.

The historical BCP WAL/DR plan is superseded. GAF's operation binding and staged recovery
descriptor are target-state contract material, not shipped generalized HKA recovery; they need an
owner-native profile and durable-state decision before #5067 can proceed.

### RQ3 — What conforms, is justified, or is drift/obsolete?

Conforming: HKA/source authority, document-backed receipts, rebuildable mirrors, and explicit
raw-evidence class separation. Justified but unresolved: MVR safety state and BuilderOps recovery
fence, because they protect partial failure and external-effect reconciliation. Drift: the
`INDEX_OUTBOX_PATH` backup wording and the boundary between nightly diagnostic dumps and no-scheduled-
DR language. Obsolete: the July BCP-INV-07 full-backup/WAL cutover proposal. Target-state, not
current truth: GAF HKA recovery/operation-journal implementation.

### RQ4 — What minimum invariants must be testable?

REBUILD-MUST-01..05, REBUILD-GATE-01..04, and REBUILD-DOCTOR-01..03 above. The essential proof is
not “a backup restored”; it is “source documents remained intact, derived state was lost, and the
system rebuilt or fenced truthfully without silently using a mirror.”

### RQ5 — What is the bounded dependency-ordered path?

1. Resolve the owner policy for MVR safety state, BuilderOps recovery metadata, and GAF operation
   binding/staged recovery descriptors. This is the only current decision gate.
2. Reconcile the owner documents and retire/supersede stale backup/WAL wording; clarify diagnostic
   dump and JSONL retention semantics. No runtime mutation is needed for the audit result.
3. Build the loss/corruption fixture and read-only doctor kernel against current producers,
   migrations, bootstrap, and projection rebuild paths.
4. Only after the operational boundary is explicit, decide whether any GAF/#5067 recovery slice is
   still needed. PR #5094's closed, unmerged head is not an implementation authority.
5. Re-run the audit at current head and promote only the smallest accepted invariants into their
   existing owner docs/tests. No new central registry, archive store, DB backup authority, or SBS
   subsystem is warranted by this audit.

## 6. SBS reconciliation

The result conforms to the existing SBS rather than reshaping it:

- HKA remains owner of durable human-authored/accepted knowledge and portable identity/provenance;
- SIP/DRI remain subordinate identity/derivation concerns;
- PDM owns physical persistence/recovery mechanics, not semantic meaning;
- GOV owns admissibility, policy, and receipts; and
- Builder System/BuilderOps operational records must not become Product HKA/MEM truth.

This matches `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` HKA/PDM boundary sections, the manual-review
rules in `docs/architecture/SBS_BOUNDARY_REGISTER.md`, and `docs/architecture/SBS_FITNESS_RULES.md`
rules against DRI non-rebuildability, hidden authority, and Builder System collapse. No new SBS
node or central archive authority is proposed.

## 7. Issue and PR reconciliation

- **#5062:** live parent remains open and `agent:blocked`/`action:repair-contract`; its GAF children
  are not a current general recovery authority.
- **#5067:** live HKA recovery task remains blocked on a source-authorized current-main contract,
  owner-native recovery/profile selection, durable operation/replay/readback strategy, and
  production HKA/VaultPort wiring. This audit confirms the blocker rather than repairing it.
- **#5068:** live issue is closed after the read-only derivative disposition/doctor delivery; its
  outcome supports, rather than weakens, the rule that derivatives cannot be last-copy authority.
- **PR #5094:** closed without merge at `015c34b57537d0de57f7c85bdf39e10b58f4e1f3`; it is preserved
  historical evidence, not current-main implementation truth.

No Issue, PR, label, Project, receipt, or external publication was created or changed by this audit.

## 8. Accepted decision and continuation

The owner accepted a **new fenced bootstrap epoch** for loss of operational safety lineage:

- retained human artifacts, companions, and document-backed governance receipts remain continuity
  authority;
- machine mirrors and coordination projections rebuild only from declared sources and recipes;
- loss of MVR ownership/journal or BuilderOps recovery lineage starts inactive, creates a new
  explicit epoch, reads owner-native or GitHub authority, reconciles, and activates only after
  convergence; and
- GAF operation bindings and staged recovery descriptors retain authority only when they remain
  explicit document-backed receipts for their governed operation. Their existence does not create
  a general database, queue, index, backup, or restore authority.

The accepted provenance is PromotionIntent `prom_20260831201315_5d56e3a3` and acceptance receipt
`receipt_20260831201333_74f589be`. Its governed delivery result references are shared epic #5258
and specification PR #5259; the PromotionIntent remains `accepted` until that PR merges and is then
eligible for the `promoted` transition with those exact references.

**Continuation:** publish the two bounded specifications, then deliver their serial child ledgers.
The first ready slice is DSP-01 / #5260. RSC-01 performs the owner-doc reconciliation before any
loss/corruption implementation. #5067/#5062 remain independently blocked, and this artifact does
not authorize backup/restore migration, live loss testing, deployment, or runtime changes outside
the filed child contracts.

## 9. Audit receipt

- Snapshot: `origin/main` = `41b706be44fff71a85f4f4f87d8e39e91ab17fe9`
- Worktree: detached, clean before authoring; unrelated changes preserved
- External reads: GitHub Issues #5062, #5067, #5068 and PR #5094; read-only
- Mutations: audit file and its `DOCS_INDEX.md` row only
- Validation status: `python3 scripts/docs_guard.py --language-only` OK; `tests/architecture/test_docs_index.py` 5 passed; `tests/architecture/test_semantic_boundary_fitness.py tests/architecture/test_sbs_fitness_rules.py` 9 passed with one pre-existing dependency deprecation warning
- `tcd_plan`: cheap read-only parallel evidence collection; no live host, DB, deployment, or external mutation; defer expensive proof until the owner decision resolves the operational-state classification
