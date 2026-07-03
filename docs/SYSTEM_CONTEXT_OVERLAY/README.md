State: **Specification directory (pre-filing draft).** No parent feature issue or child issues
filed yet. Converts `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` §14 into bounded
tasks. Update this line and `PARENT_FEATURE_ISSUE.md` together once GitHub issues exist
(`.codex/skills/feature-breakdown/SKILL.md :: Real-life operating rules`).

# System Context Overlay — INCOSE / ISO-15288 Context-Layer Vocabulary

Specification directory converting the structural audit
`docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` (§14 backlog SBI-1..SBI-8, SBI-6
deliberately unallocated) into bounded, independently mergeable tasks. The audit is the analysis;
**this directory is the specification**; GitHub issues created from it are the execution contracts.

## What this overlay is

A vocabulary and classification **layer over the existing architecture**, not a redesign. It:

- Names the Yggdrasil System of Interest (SoI) boundary, and the enabling-system /
  COTS-in-deployed-configuration / external-system distinction, in ISO/IEC/IEEE 15288 terms.
- Resolves dual-listing contradictions (Ollama, Postgres, Docker/Colima) with a classification
  rule, not a rewrite of `docs/ARCHITECTURE.md`'s runtime wiring.
- Adds a crosswalk between the two existing structural taxonomies (8-subsystem spine,
  8-macrodomain / 14-boundary SBS) — a table of rows, not a new decomposition.
- Adds a thin requirements (SRS-axis) index over docs that already exist.
- **Renames nothing, restructures nothing, and grants no new authority.** Every extend-classified
  item in audit §13 attaches a term or a reference table to the current architecture; it does not
  move an owner-doc boundary.

Source audit: `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md`. Read §13
(SBS-reconciliation classification: conform / extend / reshape) and §14 (this backlog table)
before picking up any task below — they are binding on scope.

## SBS classification

**Boundary / Builder-adjacent docs work**, classified per
`docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work Classification`.
No task in this directory changes runtime code, authority rules, or shipped behavior. SBI-1
through SBI-5 and SBI-7 are `Extend` or `Conform` per audit §13 — documentation-and-index work
routed through the architecture spine (`docs/architecture/`, `docs/boundaries/`, `docs/GLOSSARY.md`,
`docs/DOCS_INDEX.md`). SBI-8 is the one `Reshape` item and is **owner-gated**, not agent-executable
(see its task file).

## Scope boundaries

- **Advisory → executable.** The audit is advisory (`docs/audits/...` doc role); this directory
  is what makes its `Extend`/`Conform` findings executable as bounded doc changes.
- **Reshapes stay owner-gated.** Per audit §13, "No reshape is enacted by this audit." SBI-8 carries
  the two reshape-routed items (SoS spine-doc rename, `DESIGN_PRINCIPLES.md` §9 rewording) and is
  the only task in this directory that is `agent:needs-human` / owner-decision material, never
  `agent:ready`.
- **No parallel research hub.** SBI tasks hang off this audit and epic #2778 directly; they do not
  create a second backlog surface. SBI-1's overlay vocabulary is an input to #2785 (Architectural
  Constitution, runs last in #2778) — extend that epic's input list, do not duplicate principles
  work here.
- **No competing SBS.** Nothing here changes `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` boundary
  definitions, dependency rules, or the register's ownership claims — only its cross-references and
  self-reported anchors (SBI-3, SBI-4).

## Task index

| Task | task_id | Depends on | Audit anchor | Verify: (kernel) |
| --- | --- | --- | --- | --- |
| [DEFINE_SYSTEM_CONTEXT_OVERLAY](DEFINE_SYSTEM_CONTEXT_OVERLAY.md) | SBI-1 | — | §1, §2, §3, §4, §5, §9, §13, §14 | overlay doc exists w/ five sections; `docs/GLOSSARY.md` has a System-of-Systems entry; `docs/DOCS_INDEX.md` row present; spine doc links the overlay note |
| [CLASSIFY_DEPLOYED_INFRASTRUCTURE](CLASSIFY_DEPLOYED_INFRASTRUCTURE.md) | SBI-2 | SBI-1 | §2, §14 | every `docker-compose.yaml` service + every `DEPLOYMENT_AND_ENVIRONMENTS.md:28-67` host process has exactly one classification row; Ollama's two bindings both classified |
| [CROSSWALK_SPINE_TO_SBS](CROSSWALK_SPINE_TO_SBS.md) | SBI-3 | SBI-1 | §4, §14 | all 8 spine subsystem names appear as row labels in `SBS_CURRENT_TO_TARGET_MAPPING.md` mapping to SBS codes; Capability row names both CAO and RCA |
| [FIX_REGISTER_AND_CHARTER_HYGIENE](FIX_REGISTER_AND_CHARTER_HYGIENE.md) | SBI-4 | — | §6 (C1,C2,C3,C4,C6,C7), §14 | `SBS_BOUNDARY_REGISTER.md:33` no longer anchors SIP to an embeddings module; grep for `app/llm/adapter.py` in docs returns only superseded-marked references; one contract name for MEM in charter+schema+SBS |
| [INDEX_REQUIREMENTS_COVERAGE](INDEX_REQUIREMENTS_COVERAGE.md) | SBI-5 | SBI-1 | §8, §14 | index doc exists with 20 rows; `DOCS_INDEX.md` has rows for `schemas/README.md` + `ops/host-setup/README.md`; a sentence in an owned doc records the deliberate scale-budget absence |
| [COMPLETE_PENDING_BOUNDARY_CHARTERS](COMPLETE_PENDING_BOUNDARY_CHARTERS.md) | SBI-7 | — | §6, §14 | `docs/boundaries/EBF.md`, `HIX.md`, `DRI.md` exist; `docs/boundaries/README.md` shows 14/14; traceability-matrix pending note removed |
| [ROUTE_RESHAPE_DECISIONS_TO_OWNER](ROUTE_RESHAPE_DECISIONS_TO_OWNER.md) | SBI-8 | SBI-1 (Q2/Q4 answered) | §3, §9, §13, §14, §15 (Q2, Q4) | an ADR (or explicit owner decline) exists for each reshape item |

SBI-6 is intentionally absent from this table (see "SBI-6" below); the ID gap is preserved so
cross-references to the audit's numbering stay stable.

## Dependency order

SBI-1 first (it defines the vocabulary everything else cites). SBI-2, SBI-3, SBI-5, and SBI-8's
prerequisite question all depend on SBI-1. SBI-4 and SBI-7 have no dependency on SBI-1 or on each
other and may run in parallel with SBI-1 and with each other. SBI-8 additionally requires owner
answers to Q2/Q4 (audit §15) before an ADR can be drafted — it is not blocked on the other tasks
finishing, only on the owner decision.

Flat order: SBI-1 → {SBI-2, SBI-3, SBI-5} while {SBI-4, SBI-7} run in parallel → SBI-8 (owner-gated,
independent timing).

## Sequencing constraints (from audit §14 reconciliation notes)

- **SBI-2 vs #2655 (deployment epic).** Sequence SBI-2 after deployment epic #2655 S5/S7 lands, or
  explicitly re-verify the classification rows against the surviving topology if S5/S7 has not
  landed yet — #2655 is about to replace every deployment unit SBI-2 would cite
  (`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Implementation slices`, S2-S7).
- **SBI-2 vs #2825.** #2825 (the `docs/ARCHITECTURE.md` `context_dimensions` owner-gap issue) edits
  the same `docs/ARCHITECTURE.md :: System Context (Current)` region. Treat #2825 as a sibling, not
  a duplicate: sequence SBI-2 after #2825, or bundle review with it, to avoid double-editing one
  section in parallel.
- **SBI-5 absorbs Wave-B.** The deferred `schemas/README.md` + `ops/host-setup/README.md`
  `docs/DOCS_INDEX.md` row-adds from `docs/audits/DOC_STALENESS_CONSOLIDATION_2026-07-02.md`
  ("Deferred" section) are SRS-adjacent index work; SBI-5 absorbs them instead of a second Wave-B
  pass colliding with the SRS index pass.
- **SBI-8 reshape enactment.** `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` owns enactment of
  any reshape decision that results from Q2/Q4. SBI-8 produces the ADR / owner decision record; it
  does not itself rename or reword anything.
- **#2778 / #2785.** SBI-1's overlay vocabulary is input to #2785 (Architectural Constitution, the
  epic's last task). Extend #2785's input list; do not open a parallel principles-drafting thread
  here.

## SBI-6 (deliberately unallocated)

Per audit §5 / §12 (RQ6), the FBS / function-ID-register question resolved to "do nothing" at the
skeptic gate: `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` already is the functional-allocation view, and a
synthetic function-ID register would contradict the human-first-naming stance and create a
rot-prone parallel registry. The only surviving action is a one-sentence pointer, which SBI-1 folds
in (its fifth section names `HUMAN_FLOW_TO_RUNTIME_MAP.md` as the functional-allocation view). SBI-6
is not a task file in this directory. The ID gap in the SBI sequence is kept so review-thread
references to "SBI-1..8" stay stable.

## Cross-Task Invariants / Interaction Safety

SBI-2, SBI-3, and SBI-5 all read the vocabulary SBI-1 defines but write to disjoint files
(`docs/ARCHITECTURE.md` region, `SBS_CURRENT_TO_TARGET_MAPPING.md`, a new SRS index doc
respectively) — no shared-state race exists between them once SBI-1 has merged. The seams that do
matter:

1. **SBI-1 must land before any task that cites its vocabulary claims the citation resolves**
   (per Dependency order above). SBI-2/SBI-3/SBI-5/SBI-8 all reference terms or the glossary entry
   SBI-1 creates (SoI, enabling system, COTS-in-deployed-configuration). If a downstream task is
   picked up before SBI-1 merges, it must not silently invent its own wording — it stays
   `agent:blocked` until SBI-1's `Verify:` targets are green on `main`.
2. **SBI-2 and #2825 write the same doc region** — see "SBI-2 vs #2825" under Sequencing
   constraints above.
3. **SBI-4's register fixes must not race a concurrent register edit.** `SBS_BOUNDARY_REGISTER.md`
   is a shared file; if another in-flight PR touches the same rows (C1/C2 anchors), the later PR
   rebases onto the first rather than reintroducing the fixed anchor.
4. **SBI-8 is a decision record, not a merge gate for the others.** None of SBI-1..5/7 are blocked
   waiting on SBI-8's owner decision; SBI-8 only blocks the two specific reshape items it names
   (spine-doc rename, `DESIGN_PRINCIPLES.md` §9 reword).
5. **No task in this directory may claim an owner doc's authority changed.** Every task here is
   `Extend` or `Conform` per audit §13 (SBI-8's ADR excepted, which records rather than enacts a
   decision) — a task PR that starts reading like it moves boundary ownership has drifted outside
   this directory's contract and should stop and flag rather than widen scope silently.

## Relationship to GitHub issues

- Parent feature issue: not yet filed. See `PARENT_FEATURE_ISSUE.md` for the draft.
- One issue per task file below, in dependency order, once filed.
- SBI-8 is filed as `agent:needs-human` / owner-decision, never `agent:ready` — it is decision
  material for the owner, not a pickup-able implementation task.

## Related docs

- Audit source: `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md`
- Epic #2778 (Fable research week) and its child #2785 (Architectural Constitution)
- `docs/architecture/SBS_OPERATING_MODEL.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`,
  `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`,
  `docs/architecture/SBS_BOUNDARY_REGISTER.md`, `docs/architecture/SBS_TRANSITION_DEBT.md`
- `docs/boundaries/README.md`, `docs/architecture/traceability-matrix.md`, `docs/GLOSSARY.md`,
  `docs/ARCHITECTURE.md`, `docs/DOCS_INDEX.md`
- Companion thread: `FABLE5_PROMPT_INFRA_DOMAIN_AND_MCP_TOPOLOGY.md` (owns the dual-role
  infrastructure stance and MCP topology question — SBI-1 names and links, decides nothing)
- Sibling issue: #2825 (`docs/ARCHITECTURE.md` `context_dimensions` owner-gap)
- Sibling audit: `docs/audits/DOC_STALENESS_CONSOLIDATION_2026-07-02.md` (Wave-B deferred rows,
  absorbed by SBI-5)
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md` (owns reshape enactment for SBI-8)
