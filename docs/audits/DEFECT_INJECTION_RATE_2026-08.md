State: Advisory measurement audit snapshot, 2026-08-04. Repository baseline: `origin/main` at `52c377588054f056b6b3717db05a4fe9a3fb5c7a`; issue corpus fetched live from the GitHub REST API the same day. Subordinate to owner docs, accepted ADRs, and executable GitHub Issues. Governing Issue: #4619.
Doc role: Reference (delivery-measurement audit)
Authority: Evidence and synthesis only. Measurement and analysis; no remediation, no process change, no label backfill. Findings that warrant action become separate bounded issues.
Owner: Builder System governance / delivery measurement
Temporal class: snapshot
Review cadence: none (dated snapshot, fully rebuildable from the GitHub API)
Source of truth: GitHub REST API issue corpus as of 2026-08-04; repo git history for gate arrival dates
Last reviewed: 2026-08-04
Last verified against: live GitHub REST corpus (2,179 issues, 2,451 PRs) fetched 2026-08-04; `origin/main` `52c377588054f056b6b3717db05a4fe9a3fb5c7a`

# Defect-rate spike 2026-W29..W31 — detection versus injection audit, 2026-08

## 1. Question

The share of newly created issues carrying `type:bug` moved from an 8–19% band (2026-W20..W23)
to a sustained 48–59% (2026-W29..W31). Issue #4619 names three competing readings that are all
consistent with the aggregate and have opposite remedies:

1. **Real quality regression** — the delivery machine ships more defects per unit of work.
2. **Improved detection** — gates that went live in the window find pre-existing defects.
3. **Classification drift** — `type:bug` is applied to work earlier waves filed as `type:task`.

This audit separates the three readings by surface, filing path, gate cross-reference, and a
bounded classification-drift sample. It is measurement only.

## Method

All figures derive from one corpus fetch plus local aggregation; no per-week or per-label
re-querying. Anyone can reproduce every number from these exact commands.

**Corpus (one paginated REST query, ~47 pages):**

```bash
gh api --paginate \
  "repos/RasmusTho/agentic-pkm-mvp/issues?state=all&per_page=100&sort=created&direction=desc" \
  > issues_raw.json
```

The `/issues` endpoint returns issues and pull requests; entries carrying a `pull_request` key
are excluded. Result at 2026-08-04: 2,179 issues (numbers 55..4629, all unique), 2,451 PRs.
Every issue is authored by the single owner login `RasmusTho` (agents file through the owner's
token), so "creating actor" below is necessarily heuristic over body shape, not over the author
field.

**Aggregation (Python 3 stdlib over `issues_raw.json`):**

- Week: ISO week of `created_at` (UTC), `datetime.isocalendar()`.
- Bug: `"type:bug"` present in the issue's label set.
- Spike cohort: bugs created 2026-W29..W31 (n=292). Baseline cohort: bugs created
  2026-W20..W23 (n=48).

```python
import json, datetime
issues = [d for d in json.load(open("issues_raw.json")) if "pull_request" not in d]
def week(iso):
    y, w, _ = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).isocalendar()
    return f"{y}-W{w:02d}"
bugs = [i for i in issues if "type:bug" in {l["name"] for l in i["labels"]}]
```

**Heuristic classifiers** (regex over title+body; first match wins in the stated priority
order) are quoted in full in the sections that use them, with their limits. Gate arrival dates
come from `git log` on `origin/main` (commands quoted in section "Detection versus injection").

**Classification-drift sample:** n=40 drawn from the 292-issue spike cohort with
`random.seed(4619)`, stratified proportionally by week (21 from W29, 4 from W30, 15 from W31),
sampling from each week's cohort sorted by issue number. Each sampled issue was read in full
and classified by one reviewer against the `type:bug` definition in force during W20–W23
(details and per-issue table in "Classification drift"). Sampled claims are reported as sample
estimates with binomial uncertainty, never as a census.

**Re-verified aggregate series.** The issue-body table in #4619 reproduces exactly from this
corpus:

| Week | New issues | `type:bug` | Bug share |
|---|---|---|---|
| 2026-W20 | 98 | 8 | 8% |
| 2026-W21 | 100 | 10 | 10% |
| 2026-W22 | 93 | 10 | 11% |
| 2026-W23 | 104 | 20 | 19% |
| 2026-W24 | 133 | 41 | 31% |
| 2026-W25 | 205 | 73 | 36% |
| 2026-W26 | 127 | 12 | 9% |
| 2026-W27 | 211 | 39 | 18% |
| 2026-W28 | 252 | 43 | 17% |
| 2026-W29 | 259 | 152 | 59% |
| 2026-W30 | 61 | 29 | 48% |
| 2026-W31 | 218 | 111 | 51% |
| 2026-W32 (partial, through 08-04) | 16 | 15 | 94% |

Of the 292 spike-cohort bugs, 267 (91%) were already closed by 2026-08-04.

## Breakdown by surface

### By `area:*` label

The `area:*` axis is unusable as a census instrument in this corpus: label coverage is too low
to carry any conclusion. That absence is itself a finding and is reported instead of being
worked around silently.

| Cohort | With any `area:*` | Without | Labels present |
|---|---|---|---|
| Spike bugs (W29–31, n=292) | 11 (4%) | 281 (96%) | `area:runtime` 11 |
| Baseline bugs (W20–23, n=48) | 6 (13%) | 42 (88%) | `area:companion-ui` 6 |

### By lane

Lane labels only began appearing on bugs in W24 (0/48 baseline bugs carry any lane label), so
the lane axis describes the spike cohort but supports no baseline comparison. Where a lane
label exists in the spike cohort, it is overwhelmingly `lane:governance`:

| Cohort | `lane:governance` | `lane:core-runtime` | No lane label |
|---|---|---|---|
| Spike bugs (n=292) | 107 (37%) | 5 (2%) | 180 (62%) |
| Baseline bugs (n=48) | 0 | 0 | 48 (100%) |

Per week: W29 74 governance / 1 core-runtime / 77 none; W30 6 / 1 / 22; W31 27 / 3 / 81.

### By subject surface (path-mention heuristic)

Because the label axes are so sparse, the audit adds a content-based surface split: an issue
body mentioning builder-machinery paths (`scripts/`, `.codex/`, `.github/`, `app/dispatcher`,
`app/builderops`, `tests/governance`, `tests/properties`, `docs/development`) counts as
`builder`; product paths (`app/heimdal|settings|components|llm|agent_memory|standing_questions|
api|watcher|vault|outbox|hybrid|tts|ckm|health`, `companion-ui`) count as `product`; both →
`both`; neither → `neither`. This is a mention heuristic, not an ownership census, and
misclassifies issues that discuss a surface without pathing it.

| Cohort | builder only | both | product only | neither |
|---|---|---|---|---|
| Spike bugs (n=292) | 182 (62%) | 63 (22%) | 14 (5%) | 33 (11%) |
| Baseline bugs (n=48) | 8 (17%) | 16 (33%) | 10 (21%) | 14 (29%) |

Per week, product-only bug counts stay flat and low across the spike (W29: 7, W30: 0, W31: 7)
while builder-only counts explode (W29: 103, W30: 17, W31: 62). The contrast with the earlier
W25 bump is sharp: W25's 73 bugs were 51 product-only (the companion/runtime wave); the
W29–W31 spike is concentrated in Builder System machinery.

### By creating actor

Login census: 2,179/2,179 issues are authored by the owner login. Human-vs-agent separation
therefore rests on body shape: bodies with the canonical contract sections (`## Context` +
`## Acceptance Criteria`) are classed agent- or skill-filed; within those, bodies carrying
agent work-context markers (SHAs, worktrees, session/model names, dispatcher/lease vocabulary)
are classed `agent (marked)`; short marker-free freeform bodies (<400 chars) are classed
`likely by hand`. Limits: an agent can write a terse body and the owner can write a canonical
one; the classes measure filing form, not identity.

| Cohort | agent (marked) | canonical (unmarked) | freeform | terse by hand |
|---|---|---|---|---|
| Spike bugs (n=292) | 229 (78%) | 58 (20%) | 4 (1%) | 1 (0%) |
| Baseline bugs (n=48) | 24 (50%) | 18 (38%) | 6 (13%) | 0 |
| Spike all issues (n=538) | 421 (78%) | 108 (20%) | 8 (1%) | 1 (0%) |
| Baseline all issues (n=395) | 140 (35%) | 199 (50%) | 56 (14%) | 0 |

Agent-shaped filing dominates both cohorts; the spike cohort is near-fully agent-marked. The
canonical `bug:`/`bug(` title (the bug-to-issue skill's canonical form) covers 258/292 (88%)
of spike bugs versus 22/48 (46%) at baseline — the filing mechanism itself changed between the
two windows.

### By filing path

Priority-ordered first-match classifier over title+body (an issue matching several patterns is
counted once, at the highest-priority match): 1 registry (`KD-<hex>` / known-defects registry),
2 review (review thread/round/finding, independent review, `discussion_r<id>`, rejected
closure), 3 CI (`actions/runs`, CI run/job ids, CI gate/failure vocabulary), 4 validation
baseline ("while validating", full-suite / `pytest -q -m "not pg"` / mypy-baseline /
origin/main-fails vocabulary), 5 audit pass, 6 runtime ops (pilot/deploy/lease/crash-loop),
7 canonical-other (bug-to-issue shape, no origin marker), 8 by-hand/terse.

| Filing path | Spike bugs (n=292) | Baseline bugs (n=48) |
|---|---|---|
| Review rounds | 114 (39%) | 12 (25%) |
| Validation-baseline failure | 51 (17%) | 6 (13%) |
| CI-failure intake | 35 (12%) | 0 |
| Runtime/ops observation | 21 (7%) | 1 (2%) |
| Known-defects registry (#4172) | 5 (2%) | 0 |
| Audit pass | 3 (1%) | 0 |
| bug-to-issue canonical, no origin marker | 63 (22%) | 28 (58%) |
| By hand / terse | 0 | 1 (2%) |

Review rounds are the single largest filing path in the spike, and 34 spike bugs carry the
distinctive pre-merge pattern "independent review of PR #N at exact head `<sha>`" — findings
on work that had not merged (or had just merged) being minted as individual `type:bug` issues.
The verification-spine delivery alone (#3603 / PR #3620 / #3773 / BCP-05) is referenced by 70
of the 292 spike bugs (24%); in W29, 60 of 152 bugs reference PR #3620. Removing that one
cluster lowers W29's bug share from 59% to ≈46% ((152−60)/(259−60)).

## Detection versus injection

### Gates that went live in or just before the window

Arrival dates from `git log --format="%h %ad %s" --date=short` on `origin/main` (property lane:
`git log --diff-filter=A -- tests/properties/`; registry: `git log -- .codex/skills/bug-to-issue/SKILL.md`):

| Gate | Live from | Week |
|---|---|---|
| Correctness-kernel audit + T1–T15 wave (`docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md`) | 2026-07-02 | W27 |
| Property lane P-1..P-7 bootstrap (#2923, #2938, #2941, #2943, #2946) | 2026-07-05 | W27 |
| Census enforcement extension (ERE-05, #3180) | 2026-07-12 | W28 |
| Full-suite collection restored → mandated `pytest -q -m "not pg"` runs actually execute the whole suite (#3941) | W29 | W29 |
| Known-defects registry intake (#4161 → registry #4172) | 2026-07-27 | W31 |

### Census-level cross-reference

Non-exclusive mention counts over the spike cohort (these count references, not causal
attribution; `mypy`/`pytest` strings also appear in boilerplate validation sections and are
excluded here for that reason):

| Signal | Spike bugs (n=292) | Baseline bugs (n=48) |
|---|---|---|
| Verification machinery (`app/dispatcher/verification*`, `vrun-`, receipts, CAS) | 138 (47%) | 9 (19%) |
| Verification-spine cluster (#3603/#3620/#3773/BCP-05) | 70 (24%) | 0 |
| Property lane / census / guard-at-seam | 12 (4%) | 0 |
| Readiness/PR-governance validators | 25 (9%) | 0 |
| CI harness (`scripts/ci/`, `sitecustomize`, harness gates) | 7 (2%) | 0 |
| Known-defects registry / `KD-` ids | 5 (2%) | 0 |

The registry intake could not have contributed before W31 (live 2026-07-27) and its direct
contribution is bounded at 5 issues — it does not explain the rise. The property lane predates
the spike by two weeks; its direct census signal is small (12 mentions, of which the sampled
instances are census-bookkeeping breakage, e.g. #3703, #4096). The dominant correlates are the
verification-spine construction itself and the restored full-suite mandate.

### Sample-based vintage attribution

Each of the 40 sampled bugs (selection rule in "Method") was assigned one exclusive vintage
class from its own evidence text:

| Vintage class | n/40 | Share | Extrapolated /292 |
|---|---|---|---|
| A. Defect in new builder machinery delivered W27+ (verification spine, selectors, readiness validators, deployment guards, CKM tooling) | 19 | 47.5% | ≈139 |
| B. Regression injected by recent (W24+) delivery work outside that machinery | 9 | 22.5% | ≈66 |
| C. Pre-existing defect newly surfaced by a gate/audit in force since W27+ (detection) | 10 | 25% | ≈73 |
| D. Process/bookkeeping artifact, no code defect | 2 | 5% | ≈15 |

95% binomial interval on the detection share (10/40): roughly 13%–41%. Per-issue assignments
are in the table under "Classification drift".

**Reading of the split.** Detection of pre-existing defects (C) accounts for about a quarter
of the spike cohort — real, but not the majority. The sampled detection instances are
dominated by the restored full-suite run (#3941: order-dependent test pollution #3946, import
instability #3976, docker-less hard-fails #3945), long-standing latent defects surfaced by
verification-trust work (#4366, #4186, #4064, #4322), and formal-model/audit passes (#4546).
Injection (A+B ≈ 70%) is real but has a decisive qualifier: two-thirds of it is class A —
defects in the *newly built Builder System machinery itself*, found mostly by intensive
pre-merge independent review of that same machinery (the #3620 review rounds alone minted ~60
issues in W29) and largely closed again quickly (91% of the cohort closed by 2026-08-04).
Product-only injection stays at 14/292 (5%) versus 10/48 (21%) at baseline; in absolute terms
product-only bugs run ~7/week in the spike versus 51 in W25 alone. The spike is not evidence
that the shipped product got worse; it tracks the construction and adversarial review of new
builder machinery.

## Classification drift

**Definition in force during W20–W23.** The bug-to-issue skill as of 2026-05-14
(`git show 672f0d205:.codex/skills/bug-to-issue/SKILL.md`) scoped `type:bug` to "a defect,
regression, crash, or contract mismatch" identified during "analysis, testing, review, or
runtime observation", with repro steps and observed/expected results, and explicitly excluded
"routine repair, reconciliation, or bookkeeping churn". The shared taxonomy
(`.codex/skills/_shared/LABEL_TAXONOMY.md`, extracted 2026-06-11) compresses this to
"confirmed defect or regression" versus `type:task` "default for bounded implementation or
maintenance work". Each sampled issue was judged against that older definition: would the
W20–W23 intake have labeled this `type:bug`?

**Sample:** n=40 of 292 (13.7%), seed 4619, proportional week strata 21/4/15, one reviewer.

| Verdict against W20–W23 definition | n/40 | Share |
|---|---|---|
| Bug-consistent (confirmed defect/regression/crash/contract mismatch) | 32 | 80% |
| Task-like under the old definition (coverage gap, missing enforcement, completion bookkeeping, census churn) | 4 | 10% |
| Borderline (defect only relative to a new invariant/mandate, works-as-coded gap, robustness) | 4 | 10% |

Clear drift instances: #3807 (missing test coverage, "no reproduced production defect" in its
own text), #4155 (missing enforcement in a validator — an enhancement), #4222 (completion/
owner-doc promotion bookkeeping), #4096 (stale census entry — the class the old skill
explicitly excluded as bookkeeping churn). Borderline: #3656 (requirements conflict), #3945
(tests hard-fail instead of skipping on docker-less machines), #4098 (works-as-coded bound
blocking an acceptance path), #4546 (seam guardless only relative to the new formal-model
invariant).

**Magnitude check.** Even attributing the full drift+borderline share (20%, ≈58/292) to
relabeling, the W29–W31 bug share only falls from ~54% to ~43% — still far above the 8–19%
baseline band. Classification drift is real and measurable but is a minor contributor; it
cannot carry the spike.

**Per-issue sample classifications** (vintage classes as defined above; origin = filing-path
evidence in the issue's own text):

| Issue | Week | Old-definition verdict | Vintage | Origin |
|---|---|---|---|---|
| #3562 | W29 | bug-consistent (contract mismatch) | B | review (unresolved comment on merged #3535) |
| #3610 | W29 | bug-consistent | A | delivery-run observation |
| #3621 | W29 | bug-consistent (baseline regression) | B | validation baseline |
| #3656 | W29 | borderline (requirements conflict) | B | independent verification |
| #3671 | W29 | bug-consistent (regression after merge) | B | validation baseline |
| #3703 | W29 | bug-consistent (gate false positive) | A | validation baseline (property census) |
| #3713 | W29 | bug-consistent | A | pre-merge review (#3620) |
| #3723 | W29 | bug-consistent | A | pre-merge review (#3620) |
| #3726 | W29 | bug-consistent | A | pre-merge review (#3620) |
| #3740 | W29 | bug-consistent | A | pre-merge review (#3620) |
| #3751 | W29 | bug-consistent | A | pre-merge review (#3620) |
| #3760 | W29 | bug-consistent | A | pre-merge review (#3620) |
| #3762 | W29 | bug-consistent (CI-blocking literal) | B | CI + lint gate |
| #3768 | W29 | bug-consistent (invariant violation) | A | pre-merge review (#3620) |
| #3770 | W29 | bug-consistent (credential boundary) | A | pre-merge review (#3620) |
| #3807 | W29 | task-like (coverage gap, no defect) | A | post-merge review rejection |
| #3935 | W29 | bug-consistent | B | CI + full suite |
| #3945 | W29 | borderline (env robustness) | C | full-suite mandate (#3941) |
| #3946 | W29 | bug-consistent (order-dependent pollution, pre-existing on main) | C | full-suite mandate (#3941) |
| #3976 | W29 | bug-consistent (import-order defect, pre-existing) | C | full-suite validation |
| #3999 | W29 | bug-consistent (nondeterministic harness) | B | full-suite gate |
| #4064 | W30 | bug-consistent (recurrence of #2377 class) | C | CI observation on unrelated PR |
| #4066 | W30 | bug-consistent (selector false green ×3) | A | independent review root-cause |
| #4096 | W30 | task-like (census bookkeeping) | D | validation baseline (property census) |
| #4098 | W30 | borderline (works-as-coded bound) | A | acceptance replay |
| #4140 | W31 | bug-consistent (selector blocks CI) | A | CI failure |
| #4155 | W31 | task-like (missing enforcement) | A | LearningSignal follow-up |
| #4186 | W31 | bug-consistent (harness trust, pre-existing) | C | review threads on #4208 |
| #4204 | W31 | bug-consistent (over-acceptance) | B | final review round on PR #4136 |
| #4222 | W31 | task-like (completion bookkeeping) | D | parent acceptance audit |
| #4271 | W31 | bug-consistent (receipts undiagnosable) | A | pilot ops run |
| #4279 | W31 | bug-consistent (false-healthy board) | B | runtime observation, dev channel |
| #4281 | W31 | bug-consistent (required check self-skips green) | C | gate inspection |
| #4322 | W31 | bug-consistent (race, deferred review thread) | C | review backlog promotion |
| #4344 | W31 | bug-consistent (validator rejects real paths) | A | gate friction during filing |
| #4363 | W31 | bug-consistent (standing data-loss trap, incident precedent) | C | ops review after #4282 incident |
| #4366 | W31 | bug-consistent (harmful side effects proven, pre-existing since PR #20) | C | verification-trust work |
| #4534 | W31 | bug-consistent (ENOENT on resume) | A | ops resume failure |
| #4538 | W31 | bug-consistent (guard observes own subshells) | A | deployment ops |
| #4546 | W31 | borderline (guardless seam vs new invariant) | C | formal-model audit (F-D) |

## Verdict

**The evidence supports a composite of reading 2 (improved detection, broadly construed) and
a scoped form of reading 1 (injection confined to newly built Builder System machinery), with
reading 3 (classification drift) real but minor.**

- **Reading 2 — supported, in two forms.** Directly: ~25% of the sampled cohort (95% CI
  ~13–41%) are pre-existing defects surfaced by gates newly in force — above all the restored
  full-suite mandate (#3941), verification-trust work, and formal-model/audit passes; the
  named new gates themselves (property lane, registry) contribute little directly (12 and 5
  census mentions). Indirectly and larger: the review regime changed. Independent review
  rounds now mint one `type:bug` issue per finding, including 34+ findings at exact pre-merge
  heads — defects that in the W20–W23 regime would have been review comments fixed in-PR and
  never counted. The `type:bug` creation rate stopped measuring "shipped defects" and started
  measuring "findings the verification machine writes down".
- **Reading 1 — supported only for the Builder System's new machinery, rejected for the
  product.** ~47.5% of the sample are defects in machinery built W27+ (verification spine,
  selectors, validators, deployment guards); the #3603/#3620 cluster alone accounts for ~24%
  of the spike cohort. That is genuine injection — new code carrying defects — but it is
  concentrated in new builder surfaces, found overwhelmingly by the same wave's own review and
  gates, and 91% of the cohort was closed by the audit date. Product-only bugs run at 5% of
  the spike cohort (~7/week absolute, versus 51 in W25 alone). There is no evidence the
  shipped product's defect rate rose.
- **Reading 3 — measurable, minor.** 10% clear + 10% borderline drift in the sample; removing
  all of it leaves the spike share at ~43%, still ~3× the baseline band. Contributing
  process changes are visible (canonical `bug:` titling 46%→88%, review-finding minting,
  intake paths that did not exist at baseline), but they overlap with the detection reading
  more than with silent relabeling of task-like work.

**Residual uncertainty, named:**

- Actor and filing-path classes are regex/shape heuristics over a single shared author login;
  they measure filing form, not identity, and misclassification is uncorrected.
- The surface split is a path-mention heuristic; 33 spike bugs (11%) match no path pattern.
- Vintage and drift verdicts come from one reviewer over a 13.7% sample; the binomial
  intervals above are the honest width. W30 contributes only 4 sampled issues.
- The `area:*` axis (96% uncovered) and the baseline lane axis (100% uncovered) cannot
  support the breakdowns the issue ideally wanted; the label-coverage gap is itself part of
  the measurement result.
- #4607 (CI-failure dedupe by prose rather than step identity, fixed by #4628 on 2026-08-04)
  means some CI-intake bugs in the window may be duplicates of one underlying failure; this
  audit did not quantify that inflation.
- "Detection" and "injection" are not exclusive at the cohort level: a defect injected by W29
  machinery and caught by W29 review is both. The vintage classes resolve this per issue, but
  the aggregate shares depend on that classification discipline.

**Scope note.** This audit is advisory measurement only. It recommends no remediation, changes
no labels, alters no skill or intake path, and backfills nothing. Any action motivated by
these findings must be filed as separate bounded issues.
