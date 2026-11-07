# Builder System modular execution research — 2026-11-07

State: Advisory audit snapshot, 2026-11-07; no executable specification or activation. Subordinate to `docs/DOCS_INDEX.md` and owner contracts.
Doc role: Reference (audit snapshot).
Authority: Evidence-based structural analysis; repository anchors refer to default-branch main `6594291e350179e9d336f1e3a8ada17f8a84119e`, retrieved 2026-11-07 14:43 UTC and rechecked at 15:35 UTC. Live owner contracts and current GitHub state win over this snapshot. This is Builder System research, not Product/Runtime authority.

## Charter and evidence

Can an owner use one governed surface to direct and observe multiple native coding-agent families, while preserving delivery authority and recovery? Which smallest composition deserves a real trial? Scope: owner admission and projection, protected execution and session carriers, effect recovery, and total development cost. It does not authorize production, a new framework, backlog changes, or model/provider activation.

Evidence includes BuilderOps worklog `awl_20261107144628_daa8a70b` and non-promotable observation receipts `receipt_20261107144823_01795458`, `receipt_20261107152402_70c85eb2`, `receipt_20261107152907_371f5fed`, `receipt_20261107153113_1766916d`, and `receipt_20261107153320_7ef7e4e8`. These record experiments, not deployed-system receipts. Live issue readback on 2026-11-07 found [#5181](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5181), [#6146](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6146), [#5399](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5399), [#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168), and [#3604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3604) open and blocked. Their live bodies and owner contracts remain authoritative. Separate private qualification activity under #5181/#6146 must not be duplicated.

The research `tcd_plan` used bounded read-only evidence and small disposable experiments; no broad synthetic benchmark. Coordinator/explorer overlap, repeated context, input/output tokens, total wall time, operator time and dollar cost were not measured; no speedup or efficiency inference is justified. The observations below carry their own narrower times and provider-reported usage. The worklog and receipts preserve run identities and limitations; this audit does not assert parallel-agent coverage or a comparative baseline.

## Findings, ranked by systemic impact

1. **Authority and execution are separate seams.** The repository exposes authenticated issue-delivery preview and start endpoints (`app/builderops/control_plane/service.py:1258`, `:1278`); admission is not itself proof of a worker launch. The process map describes protected execution and scoped lifecycle authority (`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:371`, `:390`). `ClaudeCarrierAdapter` is explicitly a compatibility contract without a live launcher (`app/builderops/execution_routing.py:301`); Claude references are non-operational (`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:49`). A carrier must not acquire lifecycle or merge authority by being able to run a process. **Disposition:** retain as a proposed correctness requirement; no promotion.
2. **Unknown outcomes can duplicate effects.** A local controller restart recovered one running Codex process and one recorded launch after SIGKILL, but the insertion-before-process-creation crash window remained unknown (`receipt_20261107152907_371f5fed`). A retry must reconcile evidence rather than assume absence. Existing #4168 addresses fenced delivery effects and unknown starts; #3604 owns post-merge recovery. Their full mechanisms are not automatically prerequisites for every separately admitted read-only carrier. **Disposition:** retain for existing issue reconciliation; no new queue or authority.
3. **The observed UI is a projection, not proof of control or health.** At 14:45 UTC the BOB-1 loopback overview returned 200; DevUI source label `1295c0aade00cc4ef7462bc09b2f0f451a9d7424`, API/worker `ac8baeb41c7a2ab00421d18d9840f054654b26d0`. The read-only Overview and Builder System Control exposed limitations and unavailable verification/deployment receipts; Control was not a command interface. Source labels are diagnostics, not a qualification receipt. iPad access, owner identity and end-to-end control were not tested. `docs/architecture/SBS_OPERATING_MODEL.md:67` assigns the intended owner experience to `docs/DEVUI.md`. **Disposition:** retain as an evidence gap under #5181/#5399.
4. **Existing delivery demonstrates a real but manually coordinated path.** The worklog records #4893 / [PR #6129](https://github.com/RasmusTho/agentic-pkm-mvp/pull/6129) closing on 2026-10-17 with claim, review, validation, manual full-path coordination and exact closure. This historical example is neither autonomous end-to-end qualification nor evidence for the separate #6146 executor dry run. **Disposition:** retain as historical baseline, not a throughput comparison.

## Capability map

Categories below apply to the stated observation and environment, not the entire product. Every
live observation is from 2026-11-07; repository claims are bound to the snapshot SHA above.

| Capability | Classification and source | Manual step or next decisive check |
| --- | --- | --- |
| Mac-to-BOB-1 access and component liveness | **Works now, verified:** the existing SSH alias and loopback health returned; four named containers reported healthy at 14:45 UTC (`receipt_20261107144823_01795458`). | Recheck authenticated, source-bound readiness before any host operation; liveness does not prove authority or deployment. |
| Owner overview and governance lens | **Works now, limited:** the local browser displayed both read-only pages and source limitations. Verification and deployment receipts were unavailable (`receipt_20261107153320_7ef7e4e8`). | Keep the local forward available; verify the actual iPad route and truthful action, decision and trial data. |
| Current complete Dev System | **Unknown:** the listener explicitly denied complete-health proof; no fresh complete qualification or deployment receipt was established (#5181). | Run the separately governed component and host qualification for the selected candidate. |
| Authenticated admission / protected delivery | **Implemented, not live-verified here:** source endpoints and protected executor composition exist; `/start` admission is not a worker launch (`app/builderops/control_plane/service.py:1258`, `app/builderops/cli.py:2615`). | Exercise an approved, narrowly scoped command and read its actual outcome through its owning boundary. |
| Two agent families | **Works now, pilot only:** native Codex and Claude responded through a temporary local controller and a Herdr Core proxy; Claude resumed one native session (`receipt_20261107152402_70c85eb2`, `receipt_20261107152907_371f5fed`, `receipt_20261107153113_1766916d`). | Provide a governed Claude carrier and prove real containment, session identity and owner-facing operation. |
| Continuous owner control | **Missing from the observed read-only surface:** live start, pause, resume, cancel and prioritization were not available or proved there. | Define supported semantics at the existing protected operation boundary and verify through the real owner surface. |
| Delivery and exact closure | **Worked previously:** #4893 / PR #6129 used a dispatcher claim, explicit review, validation and manual full-path coordination on 2026-10-17. | Trace an authorized current task through actual launch, delivery, review, closure and readback. |
| Failure recovery | **Pilot only:** one lost-response retry and one controller-kill point succeeded; the pre-launch ambiguity and durable real effects remain unknown. | Exercise before-start, lost-start, running reattachment and terminal-result loss against real authority without duplicating effects. |
| Owner acceptance | **Unknown / not performed:** no owner iPad trial or acceptance was observed. | The owner tests the exact deployed candidate and records acceptance or rejection separately. |

## Candidate comparison and research answers

**A — provisional first candidate:** reuse the existing authenticated owner admission, protected executor, isolation, receipt and GitHub authority, with native Codex and a proposed explicitly governed Claude carrier. This minimizes new layers but still requires a carrier contract, event/status mapping, Linux containment, owner-flow verification and recovery. The existing compatibility adapter does not authorize Claude execution.

**B — optional session component:** keep the same owner and execution authority while adding [Herdr Core](https://github.com/herdrdev/herdr-core) as a terminal/session wrapper. Its local session and restart affordances may be useful; it introduces another process and protocol, and does not itself supply admission, identity, effect reconciliation, native agent semantics or owner UI. The isolated bridge below is not an integrated native adapter. Prefer B only if a concrete session need and comparative evidence justify its integration and maintenance costs.

[Herder](https://github.com/herder-sh/herder) is a distinct project with a daemon, pairing/approval and device/app model; version/help were exercised, not an actual agent session, enrolled device or account integration. [OpenHands SDK](https://github.com/OpenHands/software-agent-sdk) is a programmable agent runtime, not evidence that existing native Claude and Codex harnesses and authentication will be preserved. Its full integration is deferred until the earlier candidates fail or a material requirement changes. AgenticOps is a functional reference; source and licensing sufficiency were not established. Herdr Core and Herder report Apache-2.0; OpenHands SDK reports MIT; licenses alone do not establish operational suitability.

**RQ outcomes:** A is the lowest-complexity hypothesis, not a proven TCD winner. Two native families can answer a temporary local command, but the real owner-to-contained-worker-to-receipt path remains open. No trial proves safe replay of real effects, pause/cancel/priority, iPad operation, or production qualification. A more ambitious orchestration layer is not supported by the available evidence.

## Bounded experiments and limitations

- Temporary local bearer listener and SQLite, tools disabled/read-only: unauthorized request returned 401. After deliberately losing each response, retrying the same ID started no new process; Claude completed in 2.03 s and Codex in 5.89 s, with one scheduled launch each and matching answers. Claude reported input 2, cache-create 2608, cache-read 1688, output 22 tokens; Codex usage was not captured. This is one process and local identity, not durable exactly-once effects or an iPad trial (`receipt_20261107152402_70c85eb2`).
- After owner login, Claude recalled a marker across two native calls in the same session (2.29 s and 2.20 s); persistent CLI session storage was used. No side effects were tested. The controller SIGKILL trial described above covered one failure point only. Initial setup failures and the untested pre-launch crash window are recorded in `receipt_20261107152907_371f5fed`.
- Herder v0.18.0 and herdr-core v0.1.18 version/help ran in isolated disposable environments. The initial Core PTY attempt was denied; a later narrower sandbox allowed a Core proxy to use an outside fixed-task broker for two real read-only CLI responses (Claude 1.79 s, Codex 6.57 s). A separate dummy terminal retained transcript across Core restart. This does not prove native integration, interactive continuation, bridge crash recovery, real delivery or owner authentication (`receipt_20261107153113_1766916d`). Publisher checksum matching is not independent authenticity proof. No permanent service was installed.

## Cost of development and unknowns

| Dimension | Evidence and decision-relevant unknown |
| --- | --- |
| Owner time | Manual delivery exists; comparison of owner interventions and iPad usability is unmeasured. |
| Rework | Both candidates need carrier and recovery work; integration and upgrade rework is unknown. |
| Hidden defects | Identity, containment, event semantics and lost-start effects remain unproven in both. |
| Delay | Short synthetic timings above do not estimate a real delivery or qualification schedule. |
| Model and context | Only the cited Claude usage is available; repeated context, other tokens and total spend are unknown. |
| Tools and operations | A adds adapters; B adds a supervisor/protocol and ongoing maintenance. Neither has measured operational cost. |
| Verification and review | Real fault injection, exact effect readback, security and owner acceptance are still required; comparative effort is unknown. |

No precise monetary estimate or efficiency ranking follows from these observations.

## Proposed invariants and SBS reconciliation

These are advisory candidates, not additions to the registry. Existing registry semantics remain in `docs/testing/invariant-tests.md`; promotion requires the normal authority path.

| Finding → invariant | Category and present posture | SBS mapping |
| --- | --- | --- |
| 1 → authenticated admission and protected executor alone grant scoped effects; carrier output is data | MUST; partial existing enforcement, Claude integration new | Conforms to Builder enabling boundary (`docs/architecture/SBS_OPERATING_MODEL.md:73`); no Product subsystem change. |
| 2 → unknown start/effect stays unresolved until authoritative readback; replay cannot duplicate a proven effect | MUST; partial existing contracts, real carrier recovery unproved | Extends Builder execution/reconciliation evidence; no SBS reshape. |
| 3 → UI labels stale, unavailable and unverified evidence without implying success | DOCTOR; observed limitations, end-to-end owner flow unproved | Conforms to DevUI owner boundary (`docs/architecture/SBS_OPERATING_MODEL.md:67`). |
| 1–2 → cross-carrier fault and authority tests block unsafe integration | GATE; proposed tests, not a claim of current coverage | Extends Builder fitness practice; CES stewards contracts, not the Builder runtime (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:125`). |

The first two are the proposed minimal correctness kernel; projection and tests add defense in depth. No SBS reshaping is proposed.

## Small, reconciled next sequence

1. Preserve #5181/#6146 ownership and their environment and qualification gates for the effects they govern; do not infer executor qualification from source labels or component probes. Independent source and isolated component work can proceed without claiming those gates passed.
2. Under #5399, check the current admitted owner path and reconcile any carrier scope against existing issues before proposing a bounded issue. A separate Claude carrier would require explicit authority, containment and test contract; this audit creates none.
3. Test a real, contained, low-risk owner command through the chosen path with durable identity, status and receipt readback. Inject lost response and process restart around both sides of launch; leave ambiguous outcomes pending until reconciled. Verify the owner route including iPad separately, without activation by implication.
4. Reconcile effect fencing with #4168 and post-merge recovery with #3604, keeping their existing scope and dependencies. Compare A and optional B using actual operator time, failure recovery and maintenance evidence before selecting a permanent session supervisor.

The user's requested research-to-planning crossing was accepted through PromotionIntent
`prom_20261107153603_f1c37d71` and receipt `receipt_20261107153612_d7693808`. It authorizes only
reconciled specification/backlog planning; it does not itself change a contract, activate a carrier,
grant credentials, deploy a host, or record owner acceptance. This audit remains advisory.
