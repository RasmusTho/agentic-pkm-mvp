State: Advisory capability and acceptance inventory snapshot, 2026-08-28. Repository baseline: `origin/main` at `a252490dc57ad3e45bb6687d6d9b928d7b0b56aa`.
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
class, and the existing Issue that owns each material gap. No new Issue is created here: the live
backlog already owns the relevant bounded work, and creating a parallel capability-evidence epic
would duplicate #4710, #4741, #4748, #4749, #4826, #4169, #3788, or #4375.

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

The audit below records coverage of the scenario definition itself. A missing executable scenario
is a coverage gap even when the capability has a detailed prose contract or a related unit test.

### Human-facing scenarios

| Scenario matrix row | Scenario/prose | Executable scenario + test posture | Primary proof frame | Coverage disposition |
| --- | --- | --- | --- | --- |
| 1 | Capture a fleeting thought | No explicit validation posture or minimum executable scenario in the matrix | Capture contract + isolated vault/system UAT | Gap: add bounded scenario and owner route |
| 2 | Return after interruption and recover orientation | Defined; `partial`; non-blocking acceptance → nightly; minimum scenario exists | Retrieval/context bundle + human-need UAT | Covered at scenario-definition level; implementation remains partial |
| 2A | Use archive material without forcing it into notes | Defined; `partial`; non-blocking acceptance → nightly; minimum scenario exists | Archive/acquisition integration + provenance UAT | Covered at scenario-definition level; broader connector coverage remains open |
| 3 | Move from source material to durable understanding | No explicit validation posture or minimum executable scenario in the matrix | Source lineage + promotion/review tests | Gap: add scenario and acceptance path |
| 4 | Keep commitments trustworthy over time | Defined; `future`; non-blocking acceptance; minimum scenario exists | Commitment/state transition + human review | Covered as future scenario; no shipped claim |
| 5 | Develop a creative fragment without premature closure | No explicit validation posture or minimum executable scenario in the matrix | Candidate/draft lifecycle + human review | Gap: add scenario and acceptance path |
| 6 | Maintain a hobby or RPG world across time | No explicit validation posture or minimum executable scenario in the matrix | Context/scope separation + domain UAT | Gap: add scenario and acceptance path |
| 7 | Understand what the system did and whether to trust it | Defined; `partial`; release gate for baseline actions, otherwise non-blocking; minimum scenario exists | Governed action/receipt + browser/readability proof | Covered at scenario-definition level; composed proof remains incomplete |
| 7A | Decide whether watcher automation is safe to enable | Defined; `baseline`; release gate; minimum scenario exists | Settings/status/write-guard operator proof | Covered and release-gated for the bounded baseline |
| 8 | Use the system across multiple domains without losing meaning | No explicit validation posture or minimum executable scenario in the matrix | Context/sphere separation + cross-scope UAT | Gap: add scenario and acceptance path |
| 9 | Evolve the system without early lock-in | No explicit validation posture or minimum executable scenario in the matrix | Capability contract/replacement and migration proof | Gap: add scenario and acceptance path |
| 10 | Work across devices while keeping local artifacts primary | No explicit validation posture or minimum executable scenario in the matrix | Device/client contract + local-first recovery proof | Gap: add scenario and owner route; likely cross-repo |
| 11 | Preserve contextual integrity with real overlap | No explicit validation posture or minimum executable scenario in the matrix | Scope/sphere identity and isolation tests | Gap: add scenario and acceptance path |
| 12 | Keep central artifacts understandable if the system changes or dies | No explicit validation posture or minimum executable scenario in the matrix | Artifact portability/readability + rebuild/restore proof | Gap: add scenario and acceptance path |

### Direct human-agent scenarios

Rows A–G have a defined need, acceptance signal, and failure posture, but the matrix explicitly
marks them `future` and does not give each row a test posture or minimum executable scenario.
They therefore require a separate direct-filesystem validation track; mediated-agent scenarios reuse
the human rows above and must not be counted twice.

| Rows | Capability surface | Minimum proof that must be added before implementation can be claimed | Coverage disposition |
| --- | --- | --- | --- |
| A–C | Declared project/draft/synthesis roots | Disposable roots, plain-Markdown output, provenance/standing checks, no out-of-root writes, and human review/promotion observation | Gap: scenario-specific contract and tests absent from the matrix |
| D–E | Observation/classification and stale synthesis | External-agent file-change fixture, classification projection, staleness signal, proposal-not-apply assertion, restart/rebuild check | Gap: scenario-specific contract and tests absent from the matrix |
| F | Contradictory agent outputs | Two attributed outputs, side-by-side conflict projection, explicit reversible consolidation decision | Gap: scenario-specific contract and tests absent from the matrix |
| G | Human promotion into canonical knowledge | Explicit promotion action, citation preservation, origin trace, governed receipt, owner acceptance observation | Gap: scenario-specific contract and tests absent from the matrix |

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

The first implementation action after this audit is therefore not to create a new ledger. It is to
materialize the missing scenario-level validation contracts in the owning capability specs, then
route only executable gaps through `docs-to-issue` or `feature-breakdown`. Existing Issues remain
the owners where they already cover the gap; a new Issue is justified only after the live duplicate
check proves that no owner exists.

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
| Human-need scenario execution | `docs/plans/HUMAN_NEED_UAT_STRATEGY.md`, scenario matrix, existing UAT tests | Mixed baseline/partial/future | Add or advance scenario-specific UAT only under the owning capability Issue; avoid a catch-all epic. |

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
- BCP/TIA, DDO and Episode work remain distinct high-risk/target-state tracks. They must be tested
  with their own authority and recovery evidence and must not be reported as one delivered
  “capability layer”.
- No new Issue, runtime change, owner-doc promotion, `ready-to-try`, `owner-tried`, or
  `owner-accepted` claim is authorized by this audit.

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
