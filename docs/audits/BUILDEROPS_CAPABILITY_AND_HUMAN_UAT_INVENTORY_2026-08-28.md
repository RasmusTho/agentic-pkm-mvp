State: Advisory capability and acceptance inventory snapshot, 2026-08-28. Repository baseline: `origin/main` at `48e540d0c96cbecc5fb83fb3efc24c01a7062992`.
Doc role: Reference (point-in-time inventory and reporting plan)
Authority: Current-state claims remain owned by `docs/STATUS.md`, `docs/ARCHITECTURE.md`, capability specifications, contracts, GitHub Issues, Git, CI, and acceptance receipts. This audit creates no runtime, lifecycle, or owner-acceptance authority.
Owner: Builder System governance
Temporal class: advisory snapshot
Review cadence: event-driven after a material human-flow, capability, devUI, UAT, or BuilderOps authority change
Source of truth: `docs/DOCS_INDEX.md` for routing; cited owner documents and live delivery/acceptance evidence for facts

# BuilderOps capability and human-UAT inventory

## 1. Executive summary

The repository already contains most of the mechanism needed to prove high-level capabilities. The
material is distributed by authority class rather than missing from the repository: human need is
defined in `docs/HUMAN-FLOWS.md`, capability meaning in `docs/CAPABILITY_CONTRACT_MODEL.md`, runtime
allocation in `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`, scenario posture in
`docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`, evidence composition in the devUI/CKM/Cockpit surfaces,
and delivery truth in GitHub, Git, CI, and receipts.

The real gap is reporting continuity, not another master registry. A capability needs one explicit
join for human outcome → capability → implementation → slice evidence → feature validation → human
acceptance. The join must preserve independent facts and must not turn a merge, green test, deployed
SHA, or `agent:ready` label into owner acceptance.

This snapshot therefore records the existing inventory, the correct test method for each evidence
class, and the existing Issue that owns each material gap. The initial audit deliberately created
no Issue; after the scenario-definition and evidence-mapping passes, two bounded gaps with no
existing owner were promoted into #5144 and #5145. A parallel capability-evidence epic would still
duplicate #4710, #4741, #4748, #4749, #4826, #4169, #3788, or #4375.

## 2. Existing inventory and how it fits

| Existing mechanism | What it already proves or frames | Correct reporting role | Current limitation |
| --- | --- | --- | --- |
| `docs/HUMAN-FLOWS.md` | Eight human loops and user-visible outcomes | Human need and acceptance source | It is broader than the shipped runtime; newer loops are not automatically delivered. |
| `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` | Capability, surface, SBS, contract, debt, and verification routing per loop | Traceability aid for issue/spec design | Derivative map; it never overrides owner docs or proves implementation. |
| `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` | Human-first scenarios, acceptance signals, failure modes, and implementation/test posture | Feature-validation and UAT scenario source | Plan surface; it is not runtime or storage authority. |
| `docs/CAPABILITY_CONTRACT_MODEL.md` | Capability identity, inputs/outputs, callers, authority, side effects, provenance, fallback, observability, maturity, replacement | Capability specification checklist | Target framing; no universal runtime registry or scalar maturity is implied. |
| `app/builderops/devui_soi_evidence.py` + `tests/builderops/test_devui_soi_evidence_view.py` + immutable fixture | Read-time SoI evidence vector, denominator rules, source-state withdrawal, target/current separation, explicit linkage, no persistence | Slice-level proof of evidence composition | It is a pure composer over a supplied manifest, not a whole-system inventory or owner-outcome writer. |
| Issue #4710 / `docs/DEVUI_SOI_EVIDENCE_VIEW/` | Delivered proof contract and fixture for the SoI Evidence View v0 | Closed implementation receipt and proof baseline | No UI, whole-SoI denominator, owner-tried, or owner-accepted authority is delivered. |
| `app/builderops/devui_overview.py`, `app/builderops/devui_composition.py`, Cockpit and CKM tests | Read-time owner-facing projections, independent provider state, source-owned candidates and limitations | Owner orientation and BuilderOps evidence projection | Projections do not own task lifecycle, authority, or acceptance. |
| `tests/quality_wave/test_uat_harness.py` and `make test-bootstrap` | Seed → observe → panel → promotion → consumer → rerun, idempotency, machine-readable UAT reporting | Baseline system/UAT harness evidence | Harness success is not human acceptance and does not cover every human loop. |
| `tests/e2e/test_human_need_uat.py` | Human-need system-level TDD for return-after-interruption and archive reuse | Non-blocking acceptance pressure | The two scenarios are intentionally `xfail`; they show partial/future posture, not a baseline regression. |
| `tests/companion_ui/test_cockpit_journeys.py` | Browser journeys for Cockpit states, accessibility, layout, print, empty/refused/degraded states | Playwright/browser evidence for rendered BuilderOps behavior | It proves Cockpit journeys, not the missing connected Overview → Focus journey. |
| `.github/workflows/browser-runtime.yml` + Stage A specs | Exact-node browser proof contract and post-merge browser lane | Deterministic UI/accessibility receipt path | `tests/companion_ui/test_devui_overview_journeys.py` is absent on this baseline; #4748 owns the exact-SHA proof after its dependencies. |
| CKM seed/assessment/gap/projection tests | Provenance, freshness, assessment dimensions, gap detection, and projection non-authority | Capability evidence inputs and diagnostic projection | CKM cannot choose Issues, mutate lifecycle, or replace human acceptance. |
| BCP/TIA specs and parent Issues #3788/#4375 | PostgreSQL authority, cutover, temporal-intention and recovery target contracts | Future/high-risk capability validation backlog | These are not delivered runtime capabilities; browser UAT is insufficient proof. |

## 3. Evidence model to use in reporting

Report the following as independent fields, never as a single maturity score:

1. `documented` — the human outcome and intended capability have an authoritative source.
2. `specified` — the capability contract, boundary, invariants, and acceptance path are explicit.
3. `implemented` — the relevant runtime or Builder System mechanism exists in code/configuration.
4. `slice_verified` — the governing Issue's `Verify:` targets pass at an exact candidate SHA.
5. `capability_validated` — the wider feature/parent validation path proves the composed outcome.
6. `ready_to_try` — an owning delivery source explicitly says the result is ready for evaluation.
7. `owner_tried` — the owner genuinely exercised the receipt-backed result.
8. `owner_accepted` — the owner explicitly accepted the bounded result through the authorized path.

The first five can be evidenced by repository and delivery artifacts. The last three cannot be
inferred from CI, merge, deployment, or a browser screenshot. The SoI Evidence View already models
the same principle through source-owned identities, named denominators, independent source-state
axes, and explicit withdrawal of unsupported claims.

## 4. Human-flow inventory and test posture

| Human flow | Current posture | Minimum useful proof | Correct owner / issue route |
| --- | --- | --- | --- |
| Capture → clarify → place | Baseline for bounded vault-first capture; broader low-friction outcome remains wider than one runtime path | Contract/unit tests plus isolated test-vault system/UAT flow; inspect provenance and governed writes | Human-flow and capture owner docs; do not route through devUI evidence alone |
| Retrieve → orient → act | Retrieval baseline; orientation/resurfacing human outcome is partial | Retrieval/context-bundle contract tests, source attribution, then non-blocking human-need UAT for restart orientation | `docs/FINDING_AND_REORIENTING/`; scenario matrix §2; no smoke promotion until status claims it |
| Source → interpret → stabilize | Partial: bounded source/archive paths exist, broader archive-as-first-class use is acceptance work | Source-lineage/unit/integration tests, provenance checks, and archive UAT without forced note conversion | Archive/knowledge-acquisition owners; related bounded archival issues, not a new global UAT epic |
| Intent → propose → decide → execute → receipt | Partial/target-state across existing governed writes and DDO | Contract/API tests for authority and receipts; integration/recovery tests for delivery; browser only for owner-visible read/preview | #4163/#4169 for deterministic delivery bridge; #3788 for independent control-plane authority |
| Review → reclassify → promote/archive | Partial across state axes, commitment and archival paths | State-transition and WriteGuard tests, exact receipts, then bounded test-channel or owner walkthrough | Relevant capability spec and existing archival/commitment Issues; acceptance must remain explicit |
| Remember → recall → explain → correct | Partial: recall attribution and receipt-backed memory paths exist | ASK/retrieval attribution tests, correction/promotion authority tests, and human readability acceptance | Memory and retrieval owners; never treat recalled material as hidden authority |
| Live → observe → attribute → episode → close → recede | Future/partial: discrete capture exists, end-to-end Episode loop is not shipped | Observation/event contract tests, episode resolution and lifecycle tests, then non-blocking composed UAT | Episode Resolution Engine parent #3175; no current-state claim until its acceptance path closes |
| Encounter → acquire → refine → triage → keep/discard | Partial: bounded YouTube/source acquisition exists; broader connector/triage loop remains open | Connector/lineage tests, safe staging/triage integration tests, then source-specific UAT | Knowledge-acquisition/YouTube owners (#4107/#4119); source identity and disposition remain separate |

The posture labels follow `docs/plans/HUMAN_NEED_UAT_STRATEGY.md`: `baseline`, `partial`, and
`future` describe implementation truth, while `smoke`, `nightly`, `non-blocking acceptance`, and
`release gate` describe test gating. A `partial` scenario may be valuable UAT without being a smoke
failure; a `baseline` scenario becomes a release gate only when current-state owner docs claim it.

## 5. Full validation-coverage audit

The scenario matrix is broader than the eight canonical loops: it contains fourteen human-facing
scenarios (including 2A and 7A) and seven direct human-agent scenarios. Coverage means that every
row has all of the following, or an explicit `unsupported`/`N/A` reason:

1. a stable human-outcome source anchor;
2. an implementation posture owned by the current-state docs;
3. a minimum executable scenario;
4. a named proof layer (unit/API/data/browser/system);
5. a bounded UAT observation and disposition path;
6. a GitHub/spec owner for executable gaps; and
7. a separate owner-tried/owner-accepted receipt path.

The audit below records coverage of the scenario definition itself separately from implementation
and acceptance coverage. The scenario-definition pass is complete after PR #5141: every row now
has a posture, test posture, observable signals, and a minimum executable scenario. This does not
mean that the corresponding runtime, composed proof, or human acceptance exists.

### Human-facing scenarios

| Scenario matrix row | Scenario/prose | Executable scenario + test posture | Primary proof frame | Coverage disposition |
| --- | --- | --- | --- | --- |
| 1 | Capture a fleeting thought | Defined; `partial`; non-blocking acceptance → nightly; minimum scenario exists | Capture contract + isolated vault/system UAT | Covered at scenario-definition level; broader low-friction outcome remains partial |
| 2 | Return after interruption and recover orientation | Defined; `partial`; non-blocking acceptance → nightly; minimum scenario exists | Retrieval/context bundle + human-need UAT | Covered at scenario-definition level; implementation remains partial |
| 2A | Use archive material without forcing it into notes | Defined; `partial`; non-blocking acceptance → nightly; minimum scenario exists | Archive/acquisition integration + provenance UAT | Covered at scenario-definition level; broader connector coverage remains open |
| 3 | Move from source material to durable understanding | Defined; `partial`; non-blocking acceptance → nightly; minimum scenario exists | Source lineage + promotion/review tests | Covered at scenario-definition level; composed understanding remains partial |
| 4 | Keep commitments trustworthy over time | Defined; `future`; non-blocking acceptance; minimum scenario exists | Commitment/state transition + human review | Covered as future scenario; no shipped claim |
| 5 | Develop a creative fragment without premature closure | Defined; `future`; non-blocking acceptance; minimum scenario exists | Candidate/draft lifecycle + human review | Covered as future scenario; no shipped claim |
| 6 | Maintain a hobby or RPG world across time | Defined; `future`; non-blocking acceptance; minimum scenario exists | Context/scope separation + domain UAT | Covered as future scenario; no shipped claim |
| 7 | Understand what the system did and whether to trust it | Defined; `partial`; release gate for baseline actions, otherwise non-blocking; minimum scenario exists | Governed action/receipt + browser/readability proof | Covered at scenario-definition level; composed proof remains incomplete |
| 7A | Decide whether watcher automation is safe to enable | Defined; `baseline`; release gate; minimum scenario exists | Settings/status/write-guard operator proof | Slice verified by #5145 / PR #5148; composed capability and owner acceptance remain unsupported |
| 8 | Use the system across multiple domains without losing meaning | Defined; `future`; non-blocking acceptance; minimum scenario exists | Context/sphere separation + cross-scope UAT | Covered as future scenario; no shipped claim |
| 9 | Evolve the system without early lock-in | Defined; `future`; non-blocking acceptance; minimum scenario exists | Capability contract/replacement and migration proof | Covered as future scenario; no shipped claim |
| 10 | Work across devices while keeping local artifacts primary | Defined; `future`; non-blocking acceptance; minimum scenario exists | Device/client contract + local-first recovery proof | Covered as future scenario; likely cross-repo owner still required |
| 11 | Preserve contextual integrity with real overlap | Defined; `future`; non-blocking acceptance; minimum scenario exists | Scope/sphere identity and isolation tests | Covered as future scenario; no shipped claim |
| 12 | Keep central artifacts understandable if the system changes or dies | Defined; `partial`; non-blocking acceptance → nightly; minimum scenario exists | Artifact portability/readability + rebuild/restore proof | Slice verified by #5144 / PR #5147; composed capability and owner acceptance remain unsupported |

### Direct human-agent scenarios

Rows A–G have a defined need, acceptance signal, failure posture, test posture, and minimum
executable scenario after PR #5141. The matrix explicitly marks them `future`, so they still
require a separate direct-filesystem validation track; mediated-agent scenarios reuse the human
rows above and must not be counted twice.

| Rows | Capability surface | Minimum proof that must be added before implementation can be claimed | Coverage disposition |
| --- | --- | --- | --- |
| A–C | Declared project/draft/synthesis roots | Disposable roots, plain-Markdown output, provenance/standing checks, no out-of-root writes, and human review/promotion observation | Covered at scenario-definition level; contract/tests remain future |
| D–E | Observation/classification and stale synthesis | External-agent file-change fixture, classification projection, staleness signal, proposal-not-apply assertion, restart/rebuild check | Covered at scenario-definition level; contract/tests remain future |
| F | Contradictory agent outputs | Two attributed outputs, side-by-side conflict projection, explicit reversible consolidation decision | Covered at scenario-definition level; contract/tests remain future |
| G | Human promotion into canonical knowledge | Explicit promotion action, citation preservation, origin trace, governed receipt, owner acceptance observation | Covered at scenario-definition level; governed promotion and owner acceptance remain future |

### Read-only evidence mapping at `a710f325`

The following mapping was independently inspected against the exact baseline above. It is a
reporting receipt, not a claim that the gaps are resolved; tests were not rerun during this
mapping pass. “Existing proof” names evidence that already exists, while “remaining gap” names the
smallest missing composed or human-acceptance proof.

| Row | Best existing owner / implementation posture | Existing proof | Existing Issue / parent | Remaining validation gap |
| --- | --- | --- | --- | --- |
| 1 Capture | `SYSTEM_ENTRY_POINT`, `HEIMDAL_CAPTURE_CLIENT`; partial | Capture API/writer and Companion capture-modal tests | #3026, #3191; cross-repo client issue | Real incomplete capture → later retrieval/clarification in an isolated vault, with standing/provenance and unrelated-write negative proof |
| 2 Orientation | `FINDING_AND_REORIENTING`, Context Bundles; partial | Orientation/context-bundle/API/UI tests; opt-in human UAT is non-strict `xfail` | #392 and #1559 closed | Real ingest/index plus visible active/waiting/background distinctions and explanatory restart usefulness |
| 2A Archive | Governed Archival Flow, Knowledge Acquisition; partial | Retained-source adapter and in-memory archive UAT | #5062 and #5069; #5066 closed | Real external PDF/email/file ingest → retrieval/preview/citation, with no warm-note materialization |
| 3 Source understanding | Knowledge Acquisition and source-understanding seams; partial | Source-understanding, acquisition, and compilation unit/contract tests | #2980, #4826 | User path from source → uncertain interpretation → revisit → explicit durable promotion with bidirectional provenance |
| 4 Commitments | Commitment-as-First-Class / Commitment Surfacing; future scenario | Read-side commitment/domain/persistence/receipt/API/UI tests | #646, #688, #1960 closed | Composed review, renegotiation, deferral, and waiting-state UAT that restores trust |
| 5 Creative | Creative Process Contract; future | No row-specific executable proof | No matching executable Issue found | Fragment/candidate/unfinished relation with provisional standing, revisit/recombination, reversible revision, and no canonical promotion |
| 6 RPG world | Creative Process and contextualization contracts; future | Anti-confusion evaluation only | #2551 adjacent/closed | Two-session UAT preserving canonical/provisional/exploratory lore, reusable preparation, attribution, and return orientation |
| 7 Trust action | Interaction Surfaces & Authority / trust semantics; partial | WriteGuard/receipt tests, quality-wave harness, Cockpit browser journeys | #4741, #4748, #4749; DDO #4163; control plane #3788; TIA #4375 | One real full-stack human-visible action/receipt/correction observation; BuilderOps exact-SHA Overview journey and owner pilot remain separate |
| 7A Watcher enablement | Safe-enablement flow; baseline | Settings/status/watcher/allowlist tests and quality-wave harness | #232 closed; validation slice #5145 | One joined emit-only + armed receipt proving settings/status agreement, allowlist provenance, write guard, and skip reasons |
| 8 Multiple domains | User Needs and Scope/Sphere/Situated Identity; future | Context-dimension threading and anti-contamination tests | #645 and #2551 closed | Cross-domain UAT across work/private/learning/creative/RPG packs with explicit shared participation and no unrequested exposure |
| 9 Evolution | Capability Contract Model; future product scenario | CKM query/assessment/projection tests | #3138 and #3775 closed | Replacement/rebuild UAT proving artifacts, meaning, provenance, and degraded transitional use survive |
| 10 Devices | Instance, Device & Replica Contract; future | Sync tests and bounded capture/live-meeting channel receipts | #3026, #3191; cross-repo client issue | General primary/satellite continuity, offline divergence, eventual reconciliation, remote-authority negative proof, and physical-device UAT |
| 11 Context integrity | Scope/Sphere/Situated Identity and CrossScopeFlow; future | Scope/context tests and anti-contamination eval; invariant boundary is expected-failure | #2539, #645, #2551 closed | Overlap UAT proving default separation, shared participation, explicit reusable allowance, reason/provenance, and reversibility |
| 12 Survivability | Artifact Contract; partial | Cold-rebuild and quality-wave rebuild tests | #2345 closed; validation slice #5144 | Support-free copied-root inspection proving human intelligibility after runtime/index loss |
| A-B Direct roots | `AGENT-FLOWS` direct filesystem mode; future | No row-specific boundary/UAT proof | No matching row-specific Issue | Declared project/draft roots, Markdown-only edits, standing, attribution, aging/promotion boundaries, and zero out-of-root writes |
| C Direct synthesis | `AGENT-FLOWS` compilation obligations; future | Mediated compilation tests only | #2980, #4826 adjacent | Declared synthesis-root run with bidirectional citations, navigability, challengeable standing, and source preservation |
| D Observation | `AGENT-FLOWS` observation/classification boundary; future | Generic watcher/ingest only | No matching row-specific Issue | External write → ingest/index → zone/provenance receipt, without mediation claim or silent trust upgrade |
| E Recompilation | `AGENT-FLOWS` compilation and temporal validity; future | No direct scenario proof; CKM staleness is BuilderOps-only | No matching row-specific Issue | Real source/time drift detection, proposal-not-auto-apply over touched content, fresh recompilation, and restart/rebuild proof |
| F Contradictions | `AGENT-FLOWS` contradiction triage; future | Read-only contradiction primitive and citation/triage tests | #3543 closed | Two attributed outputs side by side, no silent merge, and explicit reversible human consolidation |
| G Promotion | `AGENT-FLOWS` plus trust-semantics boundary; future | Generic promotion/activation tests, not direct-agent origin proof | #2980, #4826 adjacent | Explicit human trust-delta promotion preserving citations/origin history; location move alone must not promote authority |

### Exact receipts for the first bounded validation slices

The original read-only mapping identified #5144 and #5145 as unresolved gaps. Both slices have
since been delivered on the exact heads below. These receipts upgrade only `slice_verified`; they
do not upgrade `capability_validated`, `ready_to_try`, `owner_tried`, or `owner_accepted`.

| Slice | Exact implementation receipt | Verification receipt | Remaining authority gap |
| --- | --- | --- | --- |
| Row 12 support-free survivability | #5144 / PR #5147; implementation head `9e72564fead3430a5ecdd15e4f3a97dd444ac911`; merge `7c2e357b8da73767f512079b3857d0b821927b7c` | Cold-rebuild suite: 11 passed; selector suite: 99 passed; required CI green | No composed survivability/UAT walkthrough or owner observation/acceptance |
| Row 7A watcher safe enablement | #5145 / PR #5148; implementation head `bffae72f03854cbc9b5b6a08e6421243168dabfc`; merge `c3e4ca1888655f5b818e7280bf4078385dd890df` | Exact-head Unit tests (not pg) and smoke green; required CI green | No owner enablement decision or separate composed capability acceptance |

### Coverage-to-framework mapping

The gaps above should be filled by existing frames, in this order:

| Need | Existing frame to reuse | Boundary |
| --- | --- | --- |
| Human outcome and scenario semantics | `docs/HUMAN-FLOWS.md` + `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` | No implementation claim by itself |
| Capability contract and reusable function | `docs/CAPABILITY_CONTRACT_MODEL.md` + local capability README/spec | No universal runtime registry implied |
| Evidence and maturity inputs | CKM/Kvasir and its provenance/freshness contracts | Projection-only; cannot choose Issues or accept work |
| BuilderOps owner orientation | Cockpit/devUI read-time compositions | Read-only; no lifecycle or owner-acceptance authority |
| Deterministic product/system verification | Existing unit/API/PG/invariant/recovery suites | Must use the owning capability's authority boundary |
| Browser and interaction verification | Existing Playwright harness and post-merge browser lane | Proves rendered interaction, not persistence or authority |
| Human UAT and acceptance | `HUMAN_NEED_UAT_STRATEGY.md`, parent Issue evidence, owner receipt | Cannot be inferred from CI, merge, deployment, or screenshot |
| Delivery truth | Issue → PR → exact SHA → CI/review → merge → receipt workflow | Separate from product acceptance |

The scenario-level validation contracts are now materialized in the owning plan surface by PR
#5141. The next action is to reconcile each row against its capability specification, current
implementation, executable proof, and human-acceptance owner. Route only executable gaps through
`docs-to-issue` or `feature-breakdown`; existing Issues remain the owners where they already cover
the gap, and a new Issue is justified only after a live duplicate check proves that no owner exists.

## 6. Test strategy by evidence class

| Claim to prove | Primary mechanism | What it must show | What it cannot show |
| --- | --- | --- | --- |
| Pure capability contract and falsification rules | Unit/contract tests | Cross-field invariants, target/current separation, provenance and fail-closed behavior | Real user usefulness or deployment identity |
| Read-only API/projection | API and integration tests | Auth/admission, source-state preservation, no writes, exact response contract | Human acceptance or visual usability |
| Data/authority/recovery | PostgreSQL, concurrency, migration, restart and host/recovery drills | Canonical writer, idempotency, crash boundary, restore/cutover and credential custody | A browser journey alone |
| Rendered owner surface | Playwright/browser runtime | Real gateway, server-owned navigation, selector/ARIA contract, state matrix, no egress/effects, accessibility/layout/print/JS-off | Production acceptance, source authority, or owner acceptance |
| Human-need outcome | Seeded/scripted system flow plus explicit owner walkthrough | The user-visible outcome, reconstruction burden, provenance comprehension and explicit disposition | That a green CI run equals acceptance |
| Delivery and operational truth | Exact SHA, PR/review/CI/merge, deployment and health receipts | Candidate identity, verification and channel/deployed identity | That the owner tried or accepted it |

For browser work, use the real packaged gateway and same-origin APIs. Do not substitute intercepted
responses, raw JSON as visual state, browser-built target URLs, or local fixtures for a connected
runtime proof. For BCP/TIA and other authority-bearing work, browser evidence is supplemental only;
the primary proof is API/PostgreSQL/concurrency/recovery/cutover evidence.

## 7. Existing backlog ownership and disposition

| Work surface | Existing owner | Live posture at snapshot | Disposition |
| --- | --- | --- | --- |
| SoI Evidence View proof composer/fixture | #4710 | Closed and delivered | Reuse as the evidence-vector baseline; do not reopen or duplicate. |
| Connected devUI Overview → Focus | Parent #4741; proof #4748; owner pilot #4749 | Open and blocked | Continue serially after #4833/#4835/#4836/#4857 prerequisites; browser proof and pilot are separate receipts. |
| Connect → Create → Accept test-channel UAT | #4826 under #2980 | Open and blocked | Implement/run the isolated no-mock test-channel UAT and explicit human checkbox; do not fold into generic SoI evidence. |
| CKM-governed delivery initiation and receipt projection | #4169 under #4163 | Open and blocked | Treat as BuilderOps delivery bridge; require exact request/preview/receipt and no lifecycle mutation. |
| Independent BuilderOps control plane | #3788 | Open and blocked | Require API/PostgreSQL, migration, concurrency, recovery and cutover receipts; not a browser-only feature. |
| Temporal-intention authority | #4375 | Open and blocked | Preserve opaque-first and single-writer boundary; do not treat target spec as shipped runtime. |
| Human-need scenario execution | `docs/plans/HUMAN_NEED_UAT_STRATEGY.md`, scenario matrix, existing UAT tests | Mixed baseline/partial/future | #5144 and #5145 are the first two slice-verified validation receipts; advance composed scenario/UAT only under the owning capability Issue; avoid a catch-all epic. |

## 8. Reporting template for a capability or parent Issue

Every parent validation hub or capability receipt should report one row per capability with:

```text
Human outcome:
Capability / source owner:
Implementation posture: baseline | partial | future
Test posture: smoke | nightly | non-blocking acceptance | release gate
documented: <source + revision>
specified: <spec/contract + revision>
implemented: <exact code/config revision>
slice_verified: <Issue, PR, exact SHA, Verify targets>
capability_validated: <parent receipt / composed scenario>
ready_to_try: <explicit owning receipt, or unsupported>
owner_tried: <genuine owner observation, or unsupported>
owner_accepted: <genuine authorized acknowledgement, or unsupported>
limitations / refused / unavailable / unknown:
next legal action and owning Issue:
```

The evidence spine belongs on the parent Issue after child delivery; stable owner docs change only
when accepted support truth changes. CKM, Cockpit, devUI and generated projections may render this
information at read time, but GitHub/CI/receipts and the authorized owner path remain the authority.

## 9. Immediate conclusions

- The repository already has a coherent capability/UAT strategy and several strong proof mechanisms.
- The highest-value missing proof is not another taxonomy; it is composed, exact-SHA capability
  validation followed by a separate genuine owner trial/acceptance receipt.
- The connected Overview browser proof is already owned by #4748; the missing journey module is a
  concrete dependency gap, not permission to create a duplicate Issue.
- The two current human-need UAT `xfail` cases should remain non-blocking until their capabilities
  are claimed in current-state owner docs.
- Scenario-definition coverage is now complete for all fourteen human-facing rows and direct-agent
  rows A–G; implementation, composed validation, and owner-trial coverage are still incomplete.
- BCP/TIA, DDO and Episode work remain distinct high-risk/target-state tracks. They must be tested
  with their own authority and recovery evidence and must not be reported as one delivered
  “capability layer”.
- #5144 and #5145 are bounded validation Issues created after the audit mapping found no existing
  owner. Their exact PR/merge/test receipts now prove two slices only; they do not authorize a
  runtime capability claim, owner-doc promotion, `ready_to_try`, `owner_tried`, or `owner_accepted`
  status.

## Sources

- `docs/HUMAN-FLOWS.md`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`
- `docs/plans/HUMAN_NEED_UAT_STRATEGY.md`
- `docs/TESTING.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/DEVUI.md`
- `docs/DEVUI_SOI_EVIDENCE_VIEW/README.md`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/BUILDEROPS_COCKPIT/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `app/builderops/devui_soi_evidence.py`
- `tests/builderops/test_devui_soi_evidence_view.py`
- `tests/quality_wave/test_uat_harness.py`
- `tests/e2e/test_human_need_uat.py`
- `tests/companion_ui/test_cockpit_journeys.py`
- `.github/workflows/browser-runtime.yml`
- live GitHub Issues #4710, #4741, #4748, #4749, #4826, #4169, #3788, and #4375 (read 2026-08-28)
