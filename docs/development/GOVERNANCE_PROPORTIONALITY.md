State: Development reference. Governance proportionality contract.
Doc role: Governance contract
Authority: Defines how much governance machinery each risk tier requires. Skills and CI reference this contract instead of carrying uniform requirements.
Owner: Builder-agent governance
Temporal class: durable

# Governance Proportionality

This repository is intentionally single-operator. Every gate, receipt, and report section is paid for twice: once by an agent burning context to produce it, once by one human reading it. The governing goal is cost-effectiveness — keep the safety properties (fail-closed promotion, truthful lifecycle state, delivery traceability) while cutting per-change overhead for low-risk work.

Proportionality applies to *reporting and PR-body machinery* **and to delivery-chain depth** — the independent review gate, merge mechanics, and repair budgets (`AGENTS.md :: Proportional delivery`). It never applies to authoritative lifecycle truth: Issue labels, Issue/PR state, CI, and merge evidence must stay truthful at every tier. Project Status is optional projection repair.

## Risk tiers

Three tiers. When in doubt, classify up. A PR that mixes tiers takes the highest tier it touches.

### Tier 1 — low risk

**Classification:** docs-only changes; skill/governance text under `.codex/skills/**`, `AGENTS.md`, and `.github` governance surfaces; comment-level fixes. No product/runtime behavior, contracts, or shipped reality change.

**Deterministic CI classifier:** the PR body carries `- [x] Docs authoring lane` or `- [x] Governance lane` and the diff satisfies that lane. Existing lane checkboxes declare the tier; issue-backed code cannot self-declare Tier 1 to bypass traceability.

**Required machinery:**

- lane classifier in the PR body (the checkbox above)
- truthful authoritative lifecycle state (labels, Issue/PR state, CI) — mandatory at every tier
- An **issue-free** Tier 1 PR may omit `## BuilderOps Routing` when nothing was routed: absence
  means `none`. Issue authority requires concrete routing even with a Tier 1 checkbox. A present
  but unfilled section still fails CI.
- output format: a short human summary (2–4 sentences) plus a receipt line; no multi-section report
- validation: lightweight docs/governance checks appropriate to the touched surfaces; no full code/test smoke by default
- delivery depth: light path — declare `Final-Review-Rounds: 0` and merge plainly on green required checks; no independent review round, no verified-merge ceremony; approved bounded multi-Issue work uses the same native merge

### Tier 2 — standard

**Classification:** bounded code slices, tests, owner-doc writeback — the everyday implementation lane.

**Required machinery (the current contract):**

- exactly one `Governing-Issue: #<id>` plus at least one closing-keyword line for fully delivered
  work (the identities match in the normal single-Issue case)
- `## BuilderOps Routing` section with concrete `Records/projections/receipts:` and `Reason:` lines
- every Acceptance Criterion's `Verify:` target resolved before merge
- standard receipts (delivery receipt, post-merge owner-doc check)
- repo-standard validation gates (`ruff check app tests` and the relevant test suites when `app/` or `tests/` changed)
- delivery depth: native merge with current-head checks and self-verified coverage. An explicit
  independent review uses `Final-Review-Rounds: 1` without requiring body neutralization or a phase
  ledger. Approved multi-Issue work validates every closing child and keeps an unclosed parent open.

### Tier 3 — high risk

**Classification:** migrations, release channels, prod mutations, `stable` pointer moves, Core Runtime <-> Agentic Lab boundary moves.

**Required machinery:** one independent current-head review (`Final-Review-Rounds: 1`) and checks
covering the actual risk. P0/P1 repairs require a fresh clean review. Native PR merge is separate
from release authority: promotion plans, channel isolation, operator acknowledgment and live
verification still apply when deploying. Dispatched executors, already-started authenticated merge
attempts, and contracts explicitly requiring independent closure retain the fenced full path.
Native delivery with a nonempty closing set requires the repository's live default branch as
the PR base, because GitHub closing keywords do not close Issues on other branches. Route such
non-default-base deliveries to the full path before merge, with explicit authenticated closure.

## Evidence reuse and stop rule

Collect evidence once per relevant candidate/input set and consume it across implementation,
publication and closure. A stage transition, a new agent, or a request for a summary is not an
invalidation event. Resolve `Suggested Validation` from existing applicable results before running
commands. Preserve the command, outcome, tested candidate, environment and artifact link in the
existing PR Validation section or CI artifact; do not introduce another schema or ledger.

Rerun only evidence affected by changed code, tests, dependencies, configuration, fixtures,
contract/ACs, selection or execution environment. Required GitHub checks remain current-head; the
base-drift rule below is the only cross-head local reuse exception. Missing or ambiguous dependency
information requires the affected check, not a fabricated pass. Live deployment/health evidence
remains bound to its environment and observation time.

Each additional check must name the unresolved failure mode and the delivery decision its result
can change. Stop validating when AC coverage, relevant CI, required review and authority are
satisfied. Do not add a full suite, second clean review, per-AC fresh test, or post-merge doc re-audit
solely for reassurance. Existing tests may cover multiple ACs. Bug fixes should reproduce the
regression where practical; behavior-preserving refactors may retain passing coverage.

Keep successful output to the result and artifact link. Read failed-node details first, complete
logs only for diagnosis. Reuse the PR's validation summary in the delivery receipt; do not copy
structured artifacts or repeated AC tables into comments and chat. Executor protocol receipts stay
in their required durable location until that consumer contract is separately changed.

## Implementation and evaluation

The 2026-09-19 simplification replaces routine full-path merge with native session-owned delivery,
separates review depth from merge mechanics, reuses validation and owner-doc assessments, and drops
unrelated product gates from text-only CI. The existing selector remains the single source for
check selection; contract coverage stays conservative for unclassified docs. No new queue, evidence
registry, or runtime executor authority is added.

For the routine-route evaluation, count the actual mandatory sections from startup through normal
delivery and the mandatory `klart` closeout; do not make the total fit by excluding closeout. On the
current candidate, the section-scoped inventory is approximately 6,974 whitespace-delimited words:

| Mandatory route | Sections counted | Words |
| --- | --- | ---: |
| Shared startup | README `BuilderOps workflow checkpoints` and `Workflow continuation` | 936 |
| Coordinator | `deliver-issue-set` `First Context To Load`, `Coordinator Buffer Contract`, `Delivery Procedure`, `Workflow continuation` | 869 |
| Issue worker | `issue-to-code` `Read scope`, `Pre-implementation classification`, `Canonical workflow`, `BuilderOps routing`, `Implementation workflow`, `PR handoff`, `Workflow continuation` | 2,715 |
| Publication | `publish-pr` entry, supported path, publication workflow, handoff, continuation | 1,033 |
| Verification | `verification-and-closure` routing, inputs, validation, review, native merge, continuation | 1,058 |
| Closeout | `klart` assessment and continuation | 363 |

The counts use the repository's section-scoped read rule and a deterministic word-count script; they
exclude conditional recovery, retrospective, `pr-integration`, full-path executor, and parent-closure
sections when their triggers are absent. The route is about 1,974 words above the 5,000-word planning
goal even after removing duplicated coordinator handoff text. That excess is reported rather than
hidden; a later reduction must delete genuine duplicate contract text while preserving lifecycle,
current-head CI, executor/in-flight, and owner-gate protections. No new ledger or scheduler is added
for this measurement.

Issue #5857 records the bounded twenty-delivery evaluation below using existing CI and delivery
records. A 50% routine-token reduction remains a hypothesis, not a shipped result or an acceptance
blocker. Any new permanent check must replace an existing check or name a review date; retain
protections that demonstrate unique failure detection.

### Twenty-delivery evaluation (#5857, 2026-10-13)

**Decision:** continue native session-owned delivery and affected-test selection. This sample does
not demonstrate a 50% lead-time or cost reduction. For #5858, remove only demonstrably redundant
legacy branches, duplicate instructions or artifacts whose callers are proven migrated/absent;
retain protected executor/in-flight and release controls. Native review/dispatch separation already
ships in #5836. The inventory below identifies remaining compatibility consumers, not permission to
delete the whole full-path implementation. This evaluation performs no retirement.

The exposure cutoff is #5862, merge `ed9df9fe916d3c86d66b89f54ae5e938ed53cec7` at
2026-10-09T05:47:04Z, after #5851/#5853/#5854 delivered. Sort accepted `main` PRs by
`merged_at`, then PR number. An ordinary delivery is Tier 1 text or bounded Tier 2 tests, tooling,
configuration or derived-read/presentation work, without a changed protected deployment,
credential, durable-authority or concurrency mechanism. Requested independent review alone does
not change eligibility. Its accepted-head CI Smoke proof must also be after the cutoff. The first
20 qualify between #5897 and #6015; the bounded prefix has 66 merges, with 45 risk/environment
exclusions and one exposure exclusion. #5792 merged after cutoff but its accepted-head CI ran on
2026-10-05, so it cannot measure the consolidated changes.

The prior cohort selects the nearest preceding eligible deliveries within the same three artifact
strata: five Tier 1 text, nine Tier 2 test/CI, six Tier 2 implementation/configuration changes.
It spans 2026-09-28 through 2026-10-09. Core implementation and its immediate preparation
(#5834/#5836/#5867/#5871/#5873/#5877/#5884/#5862), plus infrastructure preparation
#5875/#5880, are excluded. #5833/#5830 is retained as a matching hermetic-fixture correction
already named in #5850's first wave. This is a **partially improved pre-core comparison**, not an
untreated control: September native delivery and parts of the October rollout already existed.
Neither cohort authorizes or claims live environment acceptance. Text has no executable effect;
test/CI uses local development and hosted Linux proof; implementation/configuration has mock/offline
or repository proof for dev/test/Product consumers. #5911 covers dev/test/prod configuration
without channel movement; #5738's managed DevUI deployment remains deferred. Risk tier, artifact
mix and proof environment are matched at this level, not exact task size, test targets, review
requests, runner load or model choice. There are nine positive final-review declarations after
cutoff and zero before, another important confounder.

Risk/environment exclusions before the twentieth delivery are:
#5889/#5860/#5891/#5893/#5874/#5895/#5899/#5903/#5904/#5908/#5906/#5909/#5913/#5914/
#5916/#5917/#5919/#5920/#5926/#5929/#5931/#5924/#5936/#5928/#5938/#5824/#5939/#5941/
#5946/#5947/#5949/#5951/#5957/#5956/#5965/#5966/#5952/#5978/#5995/#5999/#6000/#6005/
#6006/#6010/#6012. Their deployment/channel, credential/external transport, persistence/provenance,
protected read/authority, concurrency or live-capture mechanism is outside the ordinary cohort.
The exclusions use the full PR bodies and accepted-main changed paths, not review-round count.

#### Observable results and limits

Durations below are minutes; every source-table duration is exact integer seconds. Medians use
all available rows without trimming or imputation. Ready time is the latest `agent:ready` label
addition before merge on the governing Issue, not active working time; missing Issue/readiness is
unknown. PR-open time is a separate proxy and never substitutes for readiness. Long queue age in
old backlog Issues is retained. Only **CI Smoke** is measured: browser, evidence-pack, dispatch,
nightly/post-merge and local checks are not included in CI totals.

| Measure | Pre-core | Post-core | Interpretation |
| --- | ---: | ---: | --- |
| Ready-label to accepted merge, median | 33.93 (14/20) | 40.05 (17/20) | Different observable subsets; no causal saving claim |
| PR opened to accepted merge, median | 10.35 | 19.89 | Integration elapsed-time proxy, not ready time or labour |
| Accepted CI Smoke attempt feedback, median | 4.28 | 5.14 | Attempt start to last newly executed job completion |
| Initial CI Smoke scheduling delay, median | 0.058 | 0.050 | First new job start minus attempt start; pure runner queue is unknown |
| New-job execution span, median | 4.22 | 5.08 | Wall-clock span; includes overlap, not CPU or billed minutes |
| Accepted proof's summed job durations, median | 7.95 | 8.76 | Parallel runner-job proxy, including applicable reused proof |
| All observed CI Smoke job durations, total | 279.90 | 329.00 | Deduplicate reused attempt jobs; excludes other workflows and local proof |
| CI Smoke attempts / failed / cancelled / all-skipped | 29 / 2 / 2 / 2 | 32 / 5 / 1 / 4 | Attempts are not repair rounds; categories may overlap |
| PRs with one CI Smoke attempt | 14/20 | 13/20 | Single-attempt proxy, not first-pass overall acceptance |
| Accepted CI Smoke feedback <=10 minutes | 18/20 | 15/20 | Five post-core exceptions: #5911/#5945/#5981/#5982/#6009 |
| Additional observed CI Smoke heads | 6 | 8 | Revalidation/coordination proxy, not context reloads |
| Documented CI failure-to-correction cycles | 2 | 5 | Lower bound; commit and failed-step evidence below |

The strata reveal different results rather than a universal cost score:

| Risk / artifact / proof environment | n per cohort | PR-open median, pre -> post | CI Smoke feedback median, pre -> post | All-job total, pre -> post | Failed attempts, pre -> post |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tier 1 text / no executable effect | 5 | 9.35 -> 21.08 | 6.13 -> 6.42 | 57.67 -> 85.58 | 0 -> 4 |
| Tier 2 tests/CI / local and hosted Linux | 9 | 12.25 -> 10.35 | 3.85 -> 4.57 | 96.43 -> 89.88 | 1 -> 0 |
| Tier 2 implementation/configuration / repo, mock or offline proof | 6 | 11.68 -> 31.94 | 4.13 -> 18.17 | 125.80 -> 153.53 | 1 -> 1 |

Attributed pre-merge repairs are #5780's selector ownership and #5748's property-census pin;
post-core they are #5981's stale Model Inquiry expectations, #6004/#6001/#6015's INV-EF1
public-seam documentation matches/register entries, and #5998's temporal owner-doc omission.
These account for seven failed CI Smoke attempts with a subsequent correction. Successful extra
runs, same-head event runs and cancellations must not be recast as additional repairs. Four
post-core failures are text-governance friction, so the evidence supports targeted callsite cleanup
and bounded docs/gate diagnosis, not weakening correctness checks.

There were zero Issue reopen events within a common 24-hour follow-up for the 17 post-core and
15 pre-core governing Issues inspected. One attributable escaped completeness gap is documented
in pre-core #5827: #5830/#5833 repaired the remaining default host-controller dependency despite
#5827's accepted host-independent-fixture claim, within 24 hours. This was a residual dependency,
not evidence that #5827 introduced it. No corresponding post-core gap is identified by the
inspected PR/Issue receipts. Total escaped defects/incidents remain unknown: these sources are
not a complete incident census, and unequal longer follow-up must not be treated as a zero-defect
comparison.

Total delivery tokens, billing, active human labour, owner intervention count, context reloads and
coordination/control-call counts are **unknown**. GitHub actor names do not distinguish agents
from the owner, and review declarations, commit count, quota notices and elapsed time cannot fill
those fields. The sole numeric accessible usage in this sample is a source-bound advisory Jev
batch for #6009: 3,259 input / 667 output tokens, recorded in
[the merged-content receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6007#issuecomment-6115845124).
It is partial advisory telemetry, not the PR's total tokens or money. #5752's takeover after a
usage-limit cutoff is attributable recovery/coordination evidence; #6015's accepted writer
policy and #5738's earlier owner reprioritization are decision references, not measured human
intervention or active-time totals.

#### Reproducible source rows

`X`, `T`, `C` mean Tier 1 text, Tier 2 test/CI, Tier 2 implementation/configuration respectively,
with the proof environments above. `?` is unknown. `R` = ready-label-to-merge seconds; `O` =
PR-open-to-merge seconds; `F` = accepted-attempt feedback seconds; `Q` = initial scheduling
seconds; `J` = all observed, deduplicated CI Smoke job seconds; `A/f/c/e` = attempts / failed /
cancelled / all-skipped. `H` counts distinct CI Smoke heads. Run identities are `id/attempt-count`;
`A:` marks the accepted-head successful attempt. All listed PRs have merged `main` and all accepted
proof jobs actually executed successfully. Read the full head and merge identities from the PR
and the accepted run; abbreviated policy declarations are not the acceptance evidence.

Post-core, in accepted-merge order:

| PR | Class | CI Smoke run identities | R | O | F | Q | J | A/f/c/e | H |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| [#5897](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5897) | T | A:37951666261/1 | 1267 | 844 | 274 | 4 | 556 | 1/0/0/0 | 1 |
| [#5900](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5900) | C | A:37970267699/1 | 73572 | 613 | 463 | 3 | 775 | 1/0/0/0 | 1 |
| [#5911](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5911) | C | A:38004937971/1 | 2579 | 1998 | 1392 | 3 | 1613 | 1/0/0/0 | 1 |
| [#5935](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5935) | T | A:38058348590/1 | 15990 | 677 | 204 | 3 | 425 | 1/0/0/0 | 1 |
| [#5945](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5945) | T | A:38086068432/1 | 1560 | 796 | 676 | 3 | 939 | 1/0/0/0 | 1 |
| [#5960](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5960) | T | 38128031174/1; 38130579651/1; A:38130583502/1 | 4891 | 3079 | 295 | 3 | 1264 | 3/0/0/1 | 2 |
| [#5970](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5970) | T | A:38140839748/1 | 979 | 324 | 232 | 3 | 409 | 1/0/0/0 | 1 |
| [#5972](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5972) | T | A:38141842924/1 | 912 | 447 | 314 | 4 | 536 | 1/0/0/0 | 1 |
| [#5974](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5974) | T | A:38143170996/1 | 1023 | 337 | 204 | 3 | 358 | 1/0/0/0 | 1 |
| [#5976](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5976) | T | A:38144615639/1 | 1176 | 621 | 221 | 4 | 401 | 1/0/0/0 | 1 |
| [#5979](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5979) | X | 38149261433/1; A:38149899895/1 | ? | 1128 | 393 | 4 | 969 | 2/0/0/0 | 2 |
| [#5981](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5981) | C | 38150083705/1; A:38151753049/1; 38151757027/1 | ? | 2433 | 788 | 3 | 2105 | 3/1/0/1 | 2 |
| [#5982](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5982) | C | A:38151176408/1 | 3196 | 1835 | 1654 | 3 | 1908 | 1/0/0/0 | 1 |
| [#5984](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5984) | C | A:38152668932/1 | 2403 | 1358 | 270 | 3 | 505 | 1/0/0/0 | 1 |
| [#5990](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5990) | T | A:38167663094/1 | 718 | 305 | 275 | 3 | 505 | 1/0/0/0 | 1 |
| [#6004](https://github.com/RasmusTho/agentic-pkm-mvp/pull/6004) | X | 38172159338/1; 38172764327/1; A:38173004648/1 | ? | 1259 | 385 | 20 | 1310 | 3/1/1/0 | 3 |
| [#6001](https://github.com/RasmusTho/agentic-pkm-mvp/pull/6001) | X | 38171691996/1; A:38172768528/1 | 5953 | 2946 | 426 | 4 | 1045 | 2/1/0/0 | 2 |
| [#6009](https://github.com/RasmusTho/agentic-pkm-mvp/pull/6009) | C | A:38181173799/1 | 4993 | 2275 | 2126 | 10 | 2306 | 1/0/0/0 | 1 |
| [#5998](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5998) | X | 38169920321/1; A:38179560602/1; 38211688851/1 | 37615 | 37431 | 303 | 3 | 968 | 3/1/0/1 | 2 |
| [#6015](https://github.com/RasmusTho/agentic-pkm-mvp/pull/6015) | X | 38210426339/1; 38211395925/1; A:38211395758/1 | 1839 | 1265 | 284 | 2 | 843 | 3/1/0/1 | 2 |

Matched pre-core sources (newest first within each stratum):

| PR | Class | CI Smoke run identities | R | O | F | Q | J | A/f/c/e | H |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| [#5837](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5837) | X | A:37745497663/1 | ? | 561 | 350 | 4 | 498 | 1/0/0/0 | 1 |
| [#5806](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5806) | X | A:37572064064/1 | ? | 403 | 369 | 4 | 521 | 1/0/0/0 | 1 |
| [#5804](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5804) | X | 37440952472/1; 37441987895/1; A:37443202861/1 | ? | 1612 | 368 | 3 | 1391 | 3/0/0/0 | 3 |
| [#5800](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5800) | X | A:37418342411/1 | ? | 550 | 408 | 3 | 561 | 1/0/0/0 | 1 |
| [#5793](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5793) | X | A:37271024548/1 | ? | 617 | 340 | 3 | 489 | 1/0/0/0 | 1 |
| [#5833](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5833) | T | A:37730479431/1 | 807 | 381 | 206 | 4 | 405 | 1/0/0/0 | 1 |
| [#5827](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5827) | T | A:37684863561/1 | 564 | 298 | 263 | 4 | 480 | 1/0/0/0 | 1 |
| [#5789](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5789) | T | A:37240649772/1 | 2113 | 735 | 181 | 3 | 405 | 1/0/0/0 | 1 |
| [#5787](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5787) | T | A:37239412466/1 | 762 | 361 | 231 | 3 | 445 | 1/0/0/0 | 1 |
| [#5782](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5782) | T | A:37235914912/1 | 660 | 332 | 226 | 4 | 444 | 1/0/0/0 | 1 |
| [#5780](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5780) | T | 37233295123/1; A:37233805780/1; 37233825054/1 | 3430 | 1289 | 678 | 3 | 1199 | 3/1/0/1 | 2 |
| [#5737](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5737) | T | A:36709990302/1 | 183718 | 1173 | 199 | 3 | 362 | 1/0/0/0 | 1 |
| [#5711](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5711) | T | 36427189395/1; A:36428883656/1 | ? | 1553 | 567 | 4 | 1586 | 2/0/0/0 | 2 |
| [#5697](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5697) | T | A:36361837745/1 | 1958 | 818 | 242 | 3 | 460 | 1/0/0/0 | 1 |
| [#5879](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5879) | C | A:37868131108/1 | 914 | 302 | 255 | 3 | 434 | 1/0/0/0 | 1 |
| [#5779](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5779) | C | A:37231738268/1 | 1517 | 777 | 234 | 3 | 431 | 1/0/0/0 | 1 |
| [#5774](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5774) | C | A:37194223811/1 | 9768 | 285 | 222 | 4 | 474 | 1/0/0/0 | 1 |
| [#5752](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5752) | C | A:36881403901/1; 36934031126/1 | 307142 | 25966 | 241 | 4 | 469 | 2/0/0/1 | 1 |
| [#5748](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5748) | C | 36878741037/1; A:36879470291/1 | 280615 | 625 | 258 | 4 | 1105 | 2/1/0/0 | 2 |
| [#5738](https://github.com/RasmusTho/agentic-pkm-mvp/pull/5738) | C | 36724192146/1; A:36724259403/2 | 169050 | 7060 | 1590 | 6 | 4635 | 3/0/2/0 | 2 |

Rebuild each row from GitHub REST, retaining the PR-open/merge interval for all-run selection:

```bash
gh api repos/RasmusTho/agentic-pkm-mvp/pulls/5897
gh api 'repos/RasmusTho/agentic-pkm-mvp/actions/workflows/ci-smoke.yaml/runs?event=pull_request&branch=HEAD_REF&per_page=100'
gh api repos/RasmusTho/agentic-pkm-mvp/actions/runs/37951666261
gh api 'repos/RasmusTho/agentic-pkm-mvp/actions/runs/37951666261/attempts/1/jobs?per_page=100'
gh api 'repos/RasmusTho/agentic-pkm-mvp/issues/5896/events?per_page=100' --paginate
git diff-tree --no-commit-id --name-only -r MERGE_SHA^ MERGE_SHA
```

Substitute the source row's PR, its `head.ref`, run/attempt and `Governing-Issue`; paginate any
truncated result. Select the earliest successful CI Smoke run on the PR's accepted `head.sha`.
For feedback/scheduling/execution, exclude jobs whose `started_at` predates that attempt's
`run_started_at`. In #5738, run 36724259403 attempt 2 reuses four prior jobs; its new PG job,
not those old timestamps, defines attempt scheduling/execution. For total `J`, deduplicate each
`(job name, started_at, completed_at)` across attempts before summing completed, non-skipped job
durations; retained old proof must not be charged twice. Failures/cancellations come from each
attempt's jobs, not only the run's latest conclusion. Medians are the middle value (or mean of
the middle two), then divided by 60. The tables are a finite evaluation snapshot, not an ongoing
ledger or new report schema.

#### Finite retirement inventory for #5858

This is a source/caller inventory at `be8bebde4f26d70150bbfa1c27e0ca7015cef4f5`, not proof that
an installed host consumer is unused. No whole route is proven unconsumed by these 40 PRs.
Retirement must refresh the finite callers and preserve in-flight ownership before modifying them.

| Artifact / concrete consumer | Native versus full-path responsibility | #5858 recommendation / retained protection |
| --- | --- | --- |
| `.codex/skills/publish-pr/SKILL.md`; `scripts/publication.py` and `app/builderops/publication.py` | Bounded native Tier 1/2, review rounds 0/1; issue-free docs/governance, resumed linear candidates, explicitly bound existing PR and batches of <=10 closing Issues | Keep exact repo/base/branch/path/scope authority and collision checks. `publish-pr/FULL_PATH.md` retains actual unsupported/protected cases, merge-history ambiguity and nonstandard lanes, not all reviewed or existing native PRs |
| `.codex/skills/verification-and-closure/SKILL.md`; `scripts/closure.py` subset | Native expected-head merge with exact Issue readback; explicit review depth is independent of executor ownership | Keep this as the session-owned router; remove stale references that send every reviewed native PR into executor mechanics |
| `.codex/skills/verification-and-closure/FULL_PATH.md`; dispatcher merge/recovery consumers and phase helpers | Authenticated body fencing, phase recovery, exact external-effect attribution; review sections also support independent native review | Keep executor/in-flight/refusal recovery and protected review/severity rules. #5909 is recent positive implementation evidence of recovery use, not an obsolete route |
| `docs/development/PR_ESCALATION_PATHS.md` | Conditional CI failure, merge-ref, drift, dependency, owner-doc and review repair | Keep the triggered repairs; reconcile stale light/full terminology only where it contradicts the native router |
| `scripts/build_verification_dispatch_request.py::build_request`; workflow imports/CLI | Current-head/Issue/closing authority; automatic round 1 is suppressed, while explicit `--executor-request`/canary construction and legacy automatic round 2 remain supported | Retain existing native suppression and explicit executor admission/provenance. Audit legacy automatic round-2 callers before retirement; a compatibility producer with unknown host adoption is not demonstrated unused |
| `.github/workflows/verification-dispatch-request.yml::build-request` | CI Smoke completion invokes the producer; `rounds == 2` selects legacy automatic closing-link GraphQL/request generation; native 0/1 stops before those effects | Preserve the native 0/1 short circuit. Round-2 compatibility is a possible migration target only after concrete consumer/in-flight proof; artifact upload does not transfer executor ownership |
| `app/dispatcher/verification_consumer.py`, `verification_dispatch.py`, `verification_contract.py`, `verification_merge.py`, `store.py`; dispatcher CLI enqueue/consume entrypoints | Consume authenticated artifact requests, validate versions/scope and own fenced executor effects | Live code consumers exist; preserve dispatched and already-started attempts, compatible request admission and recovery. Host installation/adoption is unknown in this sample |
| `.github/workflows/post-merge-docs-classifier.yml` imports `app.dispatcher.verified_merge.resolve_post_merge_issue_authority`; `post-merge-owner-doc-watchdog.yml` uses verified-merge history/phase classification | Native and fenced post-merge authority/owner-doc consumers share the compatibility resolver | Keep these direct consumers and exact closure attribution; any retired helper must update both workflows and their regressions. Native merge does not make verified-merge classification unused |
| `tests/governance/test_verification_dispatch_request.py`, `test_verification_dispatch_workflow.py`, `tests/architecture/test_pr_hot_path_governance.py` | Production-callsite and routing regression consumers | Update the relevant tests with the changed callers; prove native review remains native and explicit executor/in-flight work still fails closed |
| `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md` verification-dispatch producer/workflow rows; `PR_HOT_PATH.md` | Owner/reference descriptions of the producer, caller and merge path | Reconcile only the retirement slice's actual shipped routing; retain this point-in-time evaluation and the unknown measurements |

#5836 (publication commit `642756f55560b64a725ee757985a47801cd6478d`) already expanded
native publication and suppressed automatic round-1 dispatch; its producer/workflow tests cover
that short circuit. Nine post-core ordinary PRs declare independent review without selecting
executor ownership; they are not nine executor runs or a measured dispatch-cost saving. The
remaining automatic round-2 branch is an explicit legacy compatibility consumer, and verified-merge
helpers still have direct native post-merge consumers. #5858 should refresh these finite callers,
remove only demonstrated migrated/absent use, and record named retention triggers or a concrete
migration follow-up when no route can be safely removed. Keep every unique correctness, authority,
credential, durability, current-head and closure protection; measurement uncertainty is not
permission to remove it.

## Delivery budgets and stop-loss

Every delivery carries a default budget of **2 CI-repair rounds per failure mechanism** (the separate
P0/P1 review-repair loop uses evidence-based convergence owned by `verification-and-closure`, not a
numeric attempt budget). When
the budget is spent, stop grinding: ship the smallest passing subset of the change, or hand the
work back with a one-paragraph stop report and a `LearningSignal` naming the artifact that made it
expensive. A handback requires the stop-loss assessment below; budget exhaustion first triggers
the applicable shrink/replan or capability-escalation path, not automatic abandonment. Budgets are
never rebound to a new mechanism key to reset accounting. Light (Tier 1/2)
deliveries run without sub-agent fan-out. Repeated failure on a bounded change is evidence the
solution is too big — shrink the solution before escalating capability.

For every Builder workflow, a stop-loss permits suspending unfinished work only when continued
execution is unsafe, unauthorized, or demonstrably non-convergent after the applicable bounded
diagnosis, repair, and capability-escalation process. It includes an unresolved authority/scope
boundary, required operator acknowledgment not yet given, or indispensable infrastructure still
unavailable after authorized recovery. Explicit user stop or limited scope is separately sufficient;
do not describe a completed analysis-only task as blocked delivery.

Ordinary CI/review waits, queue acceptance, first failures, repairable conflicts, missing optional
projection, and publication success are not stop-loss. A missing executor manifest requires diagnosis
and authorized recovery, not automatic credential provisioning or bypass. Preserve separate P0/P1
convergence rules; never merge a partial contract or waive verification to avoid leaving a PR open.

Before stopping, record the exact step and artifact/PR head, failed gate and evidence, attempts and
remaining budget, why no safe authorized continuation exists, preserved work/owner, and one next
recovery action in the existing task/Issue/PR receipt. Reuse `blocker_action.v1` when its lifecycle
applies and the existing lifecycle handoff receipt for an actual owner transfer; add no new schema.
Technical stop-loss alone does not create `agent:needs-human`. Invoke `owner-decision-brief` only for
a genuine owner decision. Once the condition clears, `resume-work` continues the suspended chain.

## Post-validation base-drift evidence reuse

Branch freshness does not make byte-identical validation evidence false. When `origin/main`
advances after expensive local validation but before the first push, rebase as required by the
branch-truth gate and carry that evidence forward only when every condition below is proven:

- the rebased delivery patch has the same stable patch ID as the validated patch;
- every delivery-owned file blob is byte-identical to the validated patch;
- the incoming base commits do not overlap delivery-owned paths and a changed-surface review finds
  no semantic effect on dependencies, contracts, runtime configuration, schemas, migrations,
  generated inputs, test selection, CI/build tooling, or the validation command itself;
- no repair, scope change, conflict resolution, or delivery-owned edit occurred during the rebase;
- the rebased head passes the bounded `Verify:` targets and cheap integration/contract checks that
  can detect interaction with the incoming base; and
- the publication receipt records the validated SHA, rebased SHA, stable patch ID, incoming commit
  range, overlap result, checks rerun, and the expensive validation carried forward.

Any unresolved relevance question fails closed and reruns the affected validation. A code,
dependency, configuration, schema, migration, test-selection, CI/build-tooling, or contract change
that can affect the delivery is relevant even when filenames do not overlap.

This rule replaces unconditional full-suite repetition for irrelevant base-only SHA changes. It
does not carry forward GitHub CI, live-environment proof, mergeability, or a required final review:
those remain bound to the current PR head. It also never carries evidence across a repair commit,
scope change, conflict resolution, or changed delivery blob.

## Right-size default

The default solution is the most boring one that satisfies the acceptance criteria. A new gate,
receipt, ledger, registry, config surface, abstraction layer, or enterprise-grade pattern (high
availability, multi-tenancy, pluggable providers, defense-in-depth beyond the single-operator
trust model) requires an explicit demand in the governing contract — never default posture. "A
simpler mechanism satisfies the contract" is a valid blocking review finding at any tier. A new
permanent governance mechanism must name what it replaces or carry an explicit review-by date.
Product-side scale posture is owned by `docs/DESIGN_PRINCIPLES.md`.

## What proportionality never relaxes

- Lifecycle truth: labels and Issue/PR state stay accurate at every tier; Project projection repair is optional and cold-path.
- The fail-closed release-channel promotion chain.
- `Verify:` targets on issue-backed acceptance criteria.
- Branch-truth gates at the publication boundary.
- Required CI checks green on the current head SHA before any merge, at every tier.
- Required independent reviews run on the current head SHA; only eligible pre-publication expensive
  validation may use the base-drift evidence-reuse rule above.

## CI enforcement

`.github/workflows/issue-pr-governance.yml` (`pr-contract` job) treats absent `## BuilderOps Routing`
as `none` only for a docs-authoring/governance lane with no Issue authority. Issue-backed PRs require
concrete routing and traceability; their checkbox cannot bypass those guards. The same job accepts
`Final-Review-Rounds: 0` (light path), `1` (one independent review), or `2` (backward-compatible
authenticated declaration for already-started deliveries). This contract owns delivery-depth
meaning; new deliveries never select `2` from risk or convergence classification.

## Output formats

The everyday skills (`publish-pr`, `issue-to-code`, `verification-and-closure`, `deliver-issue-set`, `issue-maintenance-change-control`) lead their reports with a **Summary for the human** — 2–4 sentences covering what was done, what remains, and what needs a decision — before any receipt blocks, and include further sections only when they have content.
