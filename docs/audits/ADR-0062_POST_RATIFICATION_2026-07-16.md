State: Advisory post-ratification audit snapshot, 2026-07-16. Evidence baseline: `origin/main` at `b9cd600c` plus live GitHub state the same day. Subordinate to owner docs and ADRs; ADR-0062 remains the accepted decision — this audit tests its coherence, factual grounding, enactment chain, and ratification process, and proposes bounded repairs.
Doc role: Reference (architecture audit)
Authority: Evidence and synthesis only. ADR-0062 owns the target decision; ADR-0010 owns the authority seam; GitHub Issues own implementation work.
Owner: BuilderOps governance / Architecture spine
Temporal class: Point-in-time audit; refresh rather than silently treating live-state claims as current.

# ADR-0062 post-ratification audit — 2026-07-16

## 1. Question and method

ADR-0062 (BuilderOps as an ecosystem-wide API-first enabling system) was accepted and merged on
2026-07-15 via PR #3691. This audit answers: **does the accepted decision hold — internally, against
the ADR stack, against code reality, and against its own enactment chain — and was the ratification
process sound?**

Six passes, three delegated to independent read-only reviewers and three run by the synthesizing
reviewer:

1. internal coherence of the accepted text;
2. consistency against the ADR/governance stack (ADR-0010, -0043/-0044, -0050, -0057, SBS operating
   model, process map, dependent docs);
3. factual claims verified against `origin/main` code with `file:line` evidence plus live GitHub
   issue/PR state;
4. enactment gap: ADR ↔ `docs/BUILDEROPS_CONTROL_PLANE/` spec fidelity, BCP-01..07 issue-chain
   reality, sequencing soundness, launch-gate hardness;
5. reversibility and gates around the near-irreversible steps; and
6. adversarial pass on the load-bearing arguments and the ratification process itself.

Baseline discipline: all repo evidence read from a detached `origin/main` worktree, not local
branches. This audit does not reopen the owner decision; where a finding implies a decision, it is
handed to the owner as a bounded option, not relitigated here.

## 2. What holds (verified clean)

- **Context section is factually true today.** All six current-state claims in the ADR's Context
  verified TRUE against `origin/main` with evidence: Product FastAPI mounts BuilderOps
  (`app/api/app.py:93-95,276-277`); startup bootstraps it (`scripts/start_full_system.sh:847-881` →
  `app/ops/builderops_startup.py`); CWD-relative SQLite default (`app/builderops/config.py:9-10`);
  separate dispatcher SQLite/JSONL authority (`app/dispatcher/config.py:11-13`); file-first
  model-inquiry/epic-run state (`app/builderops/model_inquiry.py`, `epic_run_state.py:19`); no auth
  on BuilderOps mutations (`app/api/routes/builderops.py` — in fact the app has no auth middleware at
  all, so the gap is total, not BuilderOps-specific); non-atomic dispatcher DB+JSONL writes
  (`app/dispatcher/store.py:742-760`) and no outbox in either tree.
- **The BCP chain is real, explicit, and acyclic.** Hub #3788; BCP-01→#3792, BCP-02→#3790,
  BCP-03→#3789, BCP-04→#3791, BCP-05→#3603, BCP-06→#3793, BCP-07→#3690. Dependency graph agrees
  across README, PARENT_FEATURE_ISSUE, and per-doc `depends_on`. BCP-01 is correctly the first
  mover and already in progress (PR #3852).
- **The launch gate is a hard content gate at the spec layer.** Restore-through-watermark without
  the Demerzel host secret store is a named test in BCP-02 AC, re-required in BCP-06 AC, and
  structurally unreachable out of order via `depends_on`. Caveat: enforcement is AC-checklist
  discipline, not a GitHub-required check (see F9).
- **No new SQLite re-entrenchment since the ADR merged** (30 commits on `app/builderops` +
  `app/dispatcher` reviewed; only pre-existing writers continue, which is expected pre-cutover) —
  with one large exception, F1.
- **ADR→spec fidelity is unusually high.** D1–D6 map fully into BCP docs, near-verbatim in the
  atomicity/fail-closed/tombstone language. `docs/adr/INDEX.md` and `docs/DOCS_INDEX.md` rows are
  accurate.
- **D1/D7 are pure target-state, correctly.** Zero `RepoRef` in code; today's `--repo` flags carry
  silent single-repo defaults (`app/builderops/cli.py:1334`); `LearningSignal` has no
  `repo`/`stack`/`task_class` fields (`app/builderops/models.py:209-220`). Nothing in the ADR
  falsely claims these exist; noted here to prevent anyone reading D1/D7 as partially built.

## 3. Ranked findings

### F1 — Blocker: ADR-0057 (Kvasir/CKM) contradicts D3 in live code, unacknowledged

ADR-0057 OD-K4 pins the Capability Evidence Graph to "the existing BuilderOps store substrate
(`app/builderops/store.py` + `runtime/builderops/*.sqlite3`)" and `app/builderops/ckm/store.py`
actively writes production BuilderOps receipts through `SqliteBuilderOpsStore` — the exact store D3
retires ("production paths contain no SQLite authority"). CKM delivery is ongoing on that substrate
(merges as recent as 2026-07-15, backlog #3138 with open children). ADR-0062 contains zero mentions
of CKM, Kvasir, or ADR-0057; the D6 cutover inventory enumerates "BuilderOps, dispatcher,
model-inquiry, and epic-run" stores and omits CKM/CEG tables entirely.

Consequence if unrepaired: the ecosystem keeps building new canonical state on the retired substrate
while the migration plan does not know it exists — a guaranteed second migration or silent data
orphaning at BCP-06.

Repair (bounded): a short ADR-0062 amendment (or ADR-0057 delta) naming CKM/CEG as a D6 migration
source; add CKM tables to BCP-03's inventory scope; an explicit owner call on CKM build posture
until cutover (keep building on SQLite as a migration source vs. pause schema growth).

### F2 — Blocker (mitigated during audit): PR #3695 could merge the superseded design mechanically

PR #3695 implements the host-stable-SQLite target that the 2026-07-15 owner revision explicitly
superseded. It sat open, `mergeable: true`, guarded only by an advisory "do not merge" comment —
while branch protection requires only `Unit tests (not pg)` and **no approving review**
(`reviews: null`, verified via the protection API). One click would have landed the retired design
ahead of BCP-03/BCP-06.

Mitigated 2026-07-16 during this audit: #3695 converted to draft with an explanatory comment. It
remains preserved as migration-inventory evidence per ADR-0062 Consequences. Residual repair:
close-or-repurpose decision lands with BCP-03.

### F3 — Major: the ratified decision received less independent scrutiny than the superseded draft

The 2026-07-14 multi-model consensus (three converging independent drafts plus a cross-model debate)
reviewed the **draft** decision: host-stable SQLite, vault-authoritative control plane. The
2026-07-15 revision replaced that with PostgreSQL authority, LSN/recovery-watermark gating, and
API-only access — materially stronger machinery — after the independent review had concluded. The
recorded self-review-bias caveat was previously defused by independent convergence; that defusal
does not transfer to the accepted text. Additionally, the evidence audit
(`BUILDEROPS_CONTROL_PLANE_2026-07-15.md`) recommends "Accept the revised ADR-0062" and was
co-authored and co-merged **in the same PR** as the ADR it validates — circular evidence at the
moment of ratification.

This does not invalidate the decision (the owner ruled with the T2-trigger rationale in view). It
means D2/D3's strongest requirements carry no independent review receipt. Repair options: a cheap
targeted re-inquiry scoped only to the 07-15 deltas (watermark regime, API-only fail-closed,
Postgres-vs-alternatives), or an explicit owner risk-acceptance note recorded in the ADR.

### F4 — Major: D3's uniform watermark gate carries an unstated availability consequence and an
internal tension with D6

D3 requires every authority-bearing success response — including lease claims — to wait for the
independent recovery watermark (off-host encrypted target). Two problems:

1. **Unstated consequence.** The Consequences section never states the operational corollary: the
   entire builder control plane fails closed whenever the off-host durability target is unreachable
   (internet outage, target outage). For a single-operator system this is a real availability
   posture change that the owner should see stated, not infer.
2. **D3↔D6 proportionality tension.** D6 already declares leases epoch-scoped and non-migratable
   (tombstoned at cutover, fresh fencing epoch). If leases may die wholesale by design, requiring
   each lease acquisition to be independently durable off-host before ack protects state the
   architecture itself treats as disposable. Most guarded state is furthermore reconstructible from
   GitHub, which D1 keeps authoritative for delivery. The irreplaceable residue (TCD history,
   learning signals, receipts of effects GitHub also records) is small relative to the latency and
   fail-closed cost applied uniformly.

Repair (owner decision, bounded): either a proportionality carve-out — external-effect-bearing
transitions and receipts wait for the watermark; ephemeral coordination (leases, heartbeats) needs
only local durability — or explicit acceptance of the uniform gate with the availability consequence
added to the ADR's Consequences. Related: the BCP docs say "synchronous" WAL durability in several
places (`POSTGRES_TRANSACTION_KERNEL.md:31`, `INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md:44,79,107`,
`README.md:136`) — a strengthening the ADR text never commits to and the owner never explicitly
ratified; resolve it in the same decision.

### F5 — Major: D5's GitHub-enforced fence has no verified mechanism on this repository

D5 requires the merge effect to be conditional on a protected-base/manifest fence "through a
GitHub-enforced conditional merge/ruleset or merge-queue path," failing closed otherwise. Verified
today: branch protection requires one status check and no reviews; no merge queue; GitHub has no
native primitive that conditions a merge on an arbitrary delivery-manifest blob OID. Unless a
concrete mechanism is designed (ruleset + required check that revalidates the fence, a queue-based
revalidation, or an explicitly documented compensating check), BCP-05's migration of the delivered
#3620 orchestration hits the fail-closed branch immediately — deadening the currently working merge
path — or the invariant gets waived informally. Repair: a bounded design task ("name the GitHub
mechanism that enforces or approximates the D5 fence on this plan/repo, or specify the compensating
revalidation") sequenced before BCP-05 starts.

### F6 — Major: interim supersession breadcrumbs are absent from every affected current-truth doc

BCP-07 (#3690) correctly owns the post-cutover rewrite, but for the entire BCP-01..06 build period
(weeks), at least eight surfaces present the retired topology as unflagged current truth, including
mandatory agent first-context: `docs/architecture/SBS_OPERATING_MODEL.md` §3,
`docs/development/BUILDER_SYSTEM_PROCESS_MAP.md:195-205` (last-reviewed the same day as the ADR, no
cross-reference), `docs/AGENT_ISSUE_DISPATCHER.md:278-287,528,812` ("SQLite is the lock authority"),
`docs/ARCHITECTURE.md:783-822`, `docs/STATUS.md:272-285`, `docs/security/API_SECURITY_MATRIX.md:41-47`,
`docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md:17-25`, and
`docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md:43-47` (instructs the exact bootstrap the ADR's Context
cites as the violation). ADR-0010's own State line still describes the co-located implementation
with no pointer to ADR-0062. Repair: one-line "current topology; supersession accepted via ADR-0062,
enactment tracked in #3690/BCP-07" banner per doc — a single cheap docs-lane PR, no content rewrite.

### F7 — Major: `AGENTS.md` is missing from BCP-07's enactment scope

BCP-07's enforceable `Verify:` anchor list names the SBS operating model, process map,
`BUILDEROPS_VAULT_BOUNDARY.md`, `BUILDEROPS_VAULT_STORE.md`, `AGENT_ISSUE_DISPATCHER.md`, and
deployment docs — but not `AGENTS.md`, whose "Dispatcher policy" and "BuilderOps Vault workflow
boundary" sections (`AGENTS.md:81-89,340`) describe the superseded operational model and are cited
as a live source anchor by BCP-04 (`API_ONLY_CLIENT_CUTOVER.md:53`). `BUILDEROPS_VAULT_OBJECT_MODEL.md`
has the same gap one tier down (prose mention, absent from the Verify list). If BCP-07 executes
literally against its named list, both go stale with no task responsible. Repair: extend BCP-07's
doc enumeration (two lines).

### F8 — Minor findings

- **D7 TCD priors hierarchy unoperationalized.** The global→stack→repo prior fallback appears once
  across all BCP docs (`API_ONLY_CLIENT_CUTOVER.md:24`); the only named test covers isolation, not
  the fallback mechanism.
- **D5 fence decomposed.** The ADR defines one atomic 5-tuple fence; BCP-05 scatters the five
  elements across separate ACs — an implementer can satisfy each independently without ever binding
  one fence object, which is the race the fence exists to close.
- **D7's reconcile-against-GitHub-before-successor clause** has no dedicated `Verify:` target in
  BCP-03 (every sibling tombstone requirement has one).
- **Stale gate line:** `docs/BUILDEROPS_CONTROL_PLANE/README.md:1` still frames PR #3691 as a future
  gate; it merged 2026-07-15.
- **Missing citations:** ADR-0062 claims ecosystem-wide authority without citing ADR-0044 (SoS
  ratification) or ADR-0050 (cross-repo governance) — substance is consistent, sourcing is absent.
  Note: the Yggdrasil SoS ADR is **ADR-0044**; ADR-0043 is the Norse name register (naming half
  superseded by 0044).
- **"T2 trigger" refers to the superseded draft's trigger taxonomy** — glossed inline but undefined
  in any surviving document.
- **Terminology bridge missing:** "BuilderOps Vault" (ADR-0010 lineage) vs. "control plane"
  (ADR-0062) equivalence is never stated anywhere; a reader must infer it.

### F9 — Note: gate enforcement is workflow-discipline, not mechanics

The BCP sequencing and launch gates are enforced by `agent:blocked` labels and AC-checklist
discipline under the verification-and-closure workflow — consistent with this repo's settled
"merge gate ≠ branch protection" posture, and F2 shows the failure mode when an artifact sits
*outside* the labeled chain. No repair proposed beyond F2's; recorded so the enforcement layer is
named honestly.

## 4. Proposed repair set (for owner triage; nothing filed yet)

| # | Source | Shape | Lane |
|---|--------|-------|------|
| R1 | F1 | ADR-0062 amendment naming CKM/CEG as D6 migration source + BCP-03 inventory extension + owner call on CKM build posture until cutover | Governance/docs |
| R2 | F6+F7+F8 | One docs PR: supersession banners on the eight affected docs + ADR-0010 forward pointer + BCP-07 doc-list extension (`AGENTS.md`, `BUILDEROPS_VAULT_OBJECT_MODEL.md`) + README gate-line fix + ADR-0044/0050 citations | Docs authoring |
| R3 | F5 | Bounded design task: name the GitHub mechanism (or compensating revalidation) for the D5 fence; sequence before BCP-05 | Governance |
| R4 | F4 | Owner decision: watermark proportionality carve-out vs. explicit uniform-gate acceptance; ratify or strike the spec-layer "synchronous" strengthening; add the availability consequence to ADR Consequences | Owner |
| R5 | F3 | Optional: targeted re-inquiry scoped to the 07-15 deltas, or a recorded owner risk-acceptance | Owner |
| R6 | F2 | Already executed (draft conversion); close-or-repurpose #3695 with BCP-03 | Done/BCP-03 |

## 5. SBS reconciliation

- **Conforms:** this audit is advisory evidence under the Builder System; it changes no authority,
  contract, or runtime behavior.
- **Extends:** nothing.
- **Reshapes:** nothing — findings that imply reshaping (F1, F4, F5) are routed to ADR/owner-decision
  surfaces per the CES/ADR rule, not enacted here.
