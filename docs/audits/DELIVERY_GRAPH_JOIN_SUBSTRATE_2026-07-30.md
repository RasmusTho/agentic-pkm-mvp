State: Advisory audit snapshot, 2026-07-30. Subordinate to `docs/DOCS_INDEX.md` and every owner
contract it cites; owner docs win on disagreement. Anchors reflect `origin/main` @ `168edbe2` at the
audit date (the working branch's delta touched only the Signboard read path and is noted where
relevant). Produced as the design substrate for the BuilderOps cockpit
(`ui_kits/builderops-cockpit/` in the Yggdrasil Design System project); no executable specification
directory exists yet — backlog conversion routes through `feature-breakdown`.
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis. Every claim carries a `file:line` anchor into main,
a named test/doc, or a named live-GitHub observation; claims without anchors were dropped.

# Delivery-graph join substrate — what a read-time cockpit join can actually stand on

## Charter

The owner needs one surface that shows the whole delivery graph: an intention fans out to one or
more capabilities, a capability to one or more epics, an epic to slices, a slice to a PR, a PR to
evidence, receipts, promotion, and finally owner acceptance. The cockpit is chartered as a
**read-time join over the existing planes, owning none of them**
(`~/Desktop/ckm-cockpit-omtag-2026-07-30.md`, section 7 — external design brief, advisory).

This audit answers four research questions with anchored evidence:

- **RQ1** — which join keys connect adjacent graph levels today, per pair: machine-readable,
  prose, or absent?
- **RQ2** — where does 1→N branching occur, and is it enumerable in both directions?
- **RQ3** — which portion of the graph is renderable today without new writers, and what is the
  minimal artifact set that completes it?
- **RQ4** — what freshness/coverage metadata exists per plane, for the requirement that an empty
  view is a dated positive claim?

Method: five parallel evidence-only explorers (GitHub linkage, docs/spec plane,
dispatcher/BuilderOps, CKM, receipts/verification), coordinator synthesis. One explorer conflict
(whether dispatcher `sync_state` carries labels/URL) was resolved by re-reading the code; the
resolution is finding F9.

## Findings, ranked by blast radius × silence of failure

**F1 — The only CI-enforced machine edge in the whole graph is PR↔issue.**
`Governing-Issue: #<id>` (exactly one) plus closing keywords are regex-parsed
(`app/dispatcher/verification_contract.py:166-186,211-242`) and CI-blocking
(`.github/workflows/issue-pr-governance.yml:618`). Everything above the slice level — parent→child,
child→parent, capability→epic, need→capability — is prose. The graph's single load-bearing machine
edge sits three levels below where the owner enters it.

**F2 — Parent↔child issue edges are prose in both directions, with inconsistent schemas.**
Parent→child: `## Implementation Tasks` tables whose column names differ between live parents
(`Issue` on #4163 vs `GitHub work item` on #3788 — live observations). Child→parent: an ad hoc
`Parent: **#N**` body line (live #4401), unnamed in `ISSUE_CONTRACT.md` and unchecked by
`scripts/validate_issue_readiness.py:31-41`. A strict machine shape exists in code —
`app/builderops/epic_delivery_ledger.py:9-56` renders an HTML-comment-delimited
`builderops:epic-delivery-ledger v1` block with `issue_number, pr_number, head_sha, merge_sha,
ci_state` per child — but nothing posts it (`app/builderops/cli.py:1865-1867`: "without GitHub
writes"). The graph's fan-out is therefore not reliably enumerable in either direction.

**F3 — The needs layer has no keys at all, and intention has no object.**
`docs/HUMAN-FLOWS.md:230-262` lists the canonical human loops unnumbered;
`docs/CONCEPTS/USER_NEEDS_MODEL.md:54-256` numbers its 14 needs with plain headers, no stable IDs.
Only `docs/CONCEPTS/USER_SITUATION_MODEL.md:99-415` carries stable IDs (A1…E1). No machine-readable
needs register exists anywhere; consequently the edge need→capability cannot be expressed, let
alone joined. Upstream of needs, "intention" has no artifact and no system of record at all — the
graph's root is unrepresented (external brief, section 7; confirmed by absence in this pass).

**F4 — The verification/receipts plane and the task plane never share a database key.**
`verification_runs` is keyed `(repository, pr_number, head_sha, stage)`
(`app/dispatcher/schema.py:271-294`) with no issue column; verified-merge receipts bind PR number,
head SHA, run_id and the authenticated issue *set* (`app/dispatcher/verified_merge.py:51-66,
905-916`). Joining receipts to issues therefore always transits the PR-body regex edge (F1). It
works — but the entire receipts plane hangs off one prose-derived edge.

**F5 — CKM is the closest existing join substrate, and it is a shadow.**
CKM artifacts already carry the cross-plane keys: `github:issue:<n>` / `github:pull:<n>`
(`app/builderops/ckm/ingest_github.py:59,79`), repo-relative paths and `git:<sha>`
(`ingest_repo.py:54-71,216,226`). Direct capability→issue edges exist via the matrix linker
(`linkers.py:250-276`), sourced from the hand-authored `docs/architecture/traceability-matrix.md`.
Capabilities are machine-registered with stable keys, parent links and SBS anchors
(`app/builderops/ckm/seed/capabilities.yaml`; `models.py:143-155`). But CKM is projection-only by
ADR-0057, rebuildable, and its capability→issue coverage is bounded by matrix rows and spec-path
references — it mirrors the graph, it does not carry it.

**F6 — The graph's *shape* lives in the docs plane; its *state* lives in GitHub; the join between
them is populated in one exemplar out of three.**
54 specification directories match `docs/*/PARENT_FEATURE_ISSUE.md`; 410 task docs carry
machine-readable frontmatter (`task_id`, `source_anchor`, `depends_on`, `prerequisites`) — the
richest dependency DAG anywhere in the system. The `github_issue:` frontmatter field that would
join a task doc to its filed issue is populated throughout `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/`
but absent in `docs/CKM_DESIGN_AGENT_INTEGRATION/` and `docs/BUILDEROPS_CONTROL_PLANE/`, where
issue numbers live only in `State:` prose. The best-structured plane and the authoritative plane
are connected by a field that exists but is usually empty.

**F7 — Owner acceptance has no receipt contract.**
The only concrete shape is `docs/runbooks/prod_acceptance_receipt.example.json` (prod go-live
scope); elsewhere "UAT receipt" is an ad hoc issue-comment convention (e.g.
`docs/CAPABILITY_KNOWLEDGE_MODEL/README.md:86`). The IR-v1 UAT job
(`.github/workflows/harness-selfverify.yml:49-71`) runs on cron/dispatch/path-filter only and
persists no receipt. The graph's terminal rung — the owner having used the thing — has neither
artifact nor contract. (ADR-0065 governs adjacent temporal-intention dispositions and gates its
writer on BCP-06/#3793; it does not define acceptance.)

**F8 — `task_id` derivation is implemented twice, independently.**
`app/dispatcher/sync_github.py:339` and `scripts/issue_pickup_claim.sh:107` both spell
`github-<owner>--<repo>-issue-<N>` with no shared source. Either edited alone silently splits the
dispatcher plane's join key.

**F9 — Signboard card metadata is structurally empty in production.**
`normalize_github_issue` reads GitHub labels only to derive priority/status and discards them;
`SyncState` carries `last_pull_at, source_version, sync_result, sync_note` — no labels, no URL
(`app/dispatcher/sync_github.py:341-375`, `models.py:67-79`). The board's label chips and
`github_url` links render only from hand-seeded test data. Any cockpit design assuming labels/links
on cards inherits silently empty fields.

**F10 — Freshness metadata exists per plane but is heterogeneous, and no unified claim exists.**
Dispatcher: `_sync_meta_<provider>` pseudo-task (`sync_github.py:386-461`). CKM: per-source
watermarks (`store.py:1588-1617`; sources enumerated in `ingest_repo.py:243-274`,
`ingest_github.py:126-177`) plus a `SnapshotManifest` with digests (`contracts.py:220-274`).
Deploys: `ops/deployments/<channel>-latest.json` with `recorded_at`
(`scripts/deploy_channel.sh:800-889`). Docs: `DocsFreshnessRecord` fields
(`app/builderops/models.py:275-293`). GitHub itself: nothing local — liveness is the API call.
"Empty as a dated positive claim" is satisfiable per plane; nothing composes the claim across
planes.

Smaller divergences inherited from explorers, recorded without ranking: `type:epic` on live #4163
is outside `LABEL_TAXONOMY.md:10-21`; `Tracked by: #N` is demoted to secondary
(`docs/development/DEV_WORKFLOW.md:406-407`) yet remains the only doc→issue marker in use;
`epic_run_state.py:660-677` uses schema-less best-effort key matching where its sibling
`epic_delivery_ledger.py:18-27` has a strict dataclass; `stable`'s stronger required checks are
inert while `stable` is dormant (`docs/RELEASE_CHANNELS/README.md:206-208`); the PR-lane marker
exclusions live in `scripts/select_pr_tests.py:20-22`, not in `ci-smoke.yaml` itself.

## RQ1 — Join keys per level pair

| Edge | Key | Class | Anchor |
|---|---|---|---|
| intention → need | — | **absent** (neither end has an object/ID) | F3 |
| need → capability | — | **absent** (needs have no IDs) | F3 |
| capability → SBS home | `boundary_ref` + `seed_source` (YAML) | machine | `capabilities.yaml`; `seed.py:33-37` |
| capability → epic/spec-dir | `State:` prose in spec dir; no issue ref in `capabilities.yaml` | prose | F6 |
| capability → issue (direct) | matrix-linker edges from traceability rows | machine, matrix-bounded | `linkers.py:250-276` |
| spec task doc → slice issue | `github_issue:` frontmatter | machine **in shape**, unpopulated in 2/3 exemplars | F6 |
| epic issue → child issues | `Implementation Tasks` prose table (schema varies) | prose | F2 |
| child issue → epic issue | `Parent: **#N**` ad hoc line | prose | F2 |
| slice issue → dispatcher task | deterministic `task_id`; `issue:<N>` lease resource | machine | `sync_github.py:339`; `leases.py:180` |
| slice issue → PR | `Governing-Issue`/`Fixes` lines | **machine + CI-enforced** | F1 |
| PR → verification runs | `(repository, pr_number, head_sha)` | machine | `schema.py:271-294` |
| PR → verified-merge receipts | PR#, head SHA, run_id, issue set | machine | `verified_merge.py:905-916` |
| merge → promotion/channel | commit SHA (pin files, receipt filenames) | machine | `deploy_channel.sh:110-120,835-864` |
| promotion → owner acceptance | — | **absent** (no contract) | F7 |
| capability/artifact → CKM | `github:issue:N`, `github:pull:N`, path, `git:<sha>` | machine (shadow) | F5 |
| anything → usage/consumers | — | **absent** (never measured) | external brief §7 |

## RQ2 — Branching and bidirectional enumeration

Branching is real at three points: intention→capabilities (unrepresented), capability→epics
(spec dirs; enumerable *downward* from a spec dir's task files with `depends_on`/`prerequisites`,
not upward from GitHub), epic→slices (prose tables downward, ad hoc line upward). The docs plane
holds the richest, machine-readable branch structure (410 frontmatter DAG nodes); GitHub — the
delivery authority — holds the poorest. **The shape of the graph and the state of the graph live
on different planes, joined by a mostly-empty field.** Only the slice→PR→SHA spine is enumerable
in both directions with machine keys.

## RQ3 — Renderable today; minimal completion set

Renderable now, read-time, no new writers: capabilities (`capabilities.yaml`) → spec dirs (54) →
task docs (410, dependency DAG) → issues where `github_issue:` or matrix rows provide the key →
dispatcher tasks (derived `task_id`, leases, events) → PRs (Governing-Issue via GitHub API) →
checks/verification (PR#+SHA) → verified-merge receipts → deploy receipts (SHA). That is the whole
*middle* of the graph. Degradations to render honestly rather than hide: unpopulated
`github_issue:` fields, prose-only parent tables, empty labels/URL (F9).

Minimal completion set, in dependency order:
1. **Stable IDs on the needs layer** (docs edit; Product-owned docs — owner call).
2. **Intention object** (new; natural home the owner's plane/vault; ties to ADR-0065's
   temporal-intention family rather than a new substrate).
3. **Machine parent↔child edge**: post the existing `epic_delivery_ledger` block, or make
   `validate_issue_readiness` require the `Parent:` line — code exists for the former.
4. **`github_issue:` population as a filing-time invariant** (feature-breakdown emits it; backfill
   the two exemplar dirs).
5. **Owner-acceptance receipt contract** (F7; generalize the prod example; pairs with the
   "prövat en gång, pinnat därefter" mechanism in the external brief).
6. **Usage/consumer edge** (import/call-graph derived; a CKM linker family or standalone doctor).

## RQ4 — Freshness per plane

See F10 for anchors. Composition gap: the cockpit requirement "0 items as of 09:41, all sources
fresh" needs a per-source `last_successful_read` row the join computes at render time from each
plane's own watermark — no plane needs a new writer for this, but the GitHub plane's liveness
exists only as the API call itself, so the join layer (natural home: the ADR-0062 BuilderOps API
service) must surface its own last-read instant per source. This is presentation state, not
authority; ADR-0065's boundary (no cockpit-local durable truth) is compatible.

## Invariants

| ID | Statement | Category | Status |
|---|---|---|---|
| INV-DG-1 | Every implementation PR carries exactly one `Governing-Issue` | GATE | Exists — keep (`issue-pr-governance.yml:618`) |
| INV-DG-2 | `task_id` derivation has exactly one implementation | MUST | **Violated today** (`sync_github.py:339` vs `issue_pickup_claim.sh:107`) |
| INV-DG-3 | Every child slice body carries a machine-parseable parent reference | GATE | New (convention exists, unchecked) |
| INV-DG-4 | A parent epic's child set is enumerable from a structured ledger, not prose tables | DOCTOR | New (renderer exists unposted, `epic_delivery_ledger.py`) |
| INV-DG-5 | A filed task doc carries its `github_issue:` key | GATE | **Violated today** (2 of 3 exemplar dirs empty) |
| INV-DG-6 | Every joined view names per-source last-successful-read; an empty view is a dated claim | DOCTOR | New (per-plane substrate exists, F10) |
| INV-DG-7 | Owner acceptance is a receipt naming issue set, SHA and date | MUST (future writer) | New (no contract, F7) |

Minimal kernel: **INV-DG-1, INV-DG-2, INV-DG-6** — with these three, a read-time join is correct
about what it shows and honest about what it cannot see. The rest widen coverage.

## SBS reconciliation

All findings **conform to** `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` and `docs/architecture/SBS_*`:
this is Builder System analysis of existing boundaries, proposing no reshape. Two items **extend**
Product-owned surfaces and route through their owners rather than this audit: stable IDs on
`docs/CONCEPTS/USER_NEEDS_MODEL.md`/`docs/HUMAN-FLOWS.md` (completion item 1), and any intention
object touching the vault plane (completion item 2, ADR-0065-adjacent). No claim reshapes SBS.

## Backlog handoff (reconciled; nothing filed by this audit)

Dependency-ordered; each names its reconciliation target so no parallel hub is created:

1. **Single-source `task_id`** (INV-DG-2) — bounded direct repair; no existing issue found.
2. **Post the epic delivery ledger** (INV-DG-4) — extends `deliver-issue-set`/
   `verification-and-closure` flows; renderer exists; reconcile against #4163's child-ledger AC
   rather than a new mechanism.
3. **Parent-line readiness check** (INV-DG-3) — extends `validate_issue_readiness.py` +
   `ISSUE_CONTRACT.md`; governance lane.
4. **`github_issue:` filing-time invariant + backfill** (INV-DG-5) — extends `feature-breakdown`.
5. **Needs-layer stable IDs** — docs-authoring on Product-owned concept docs; owner decision.
6. **Owner-acceptance receipt contract** (INV-DG-7) — owner-gated; generalizes
   `prod_acceptance_receipt.example.json`; coordinate with ADR-0065 family, do not fork it.
7. **Cockpit read-time join contract ("attention item")** — upstream design input to #4169's
   `DeliveryRunView`/console; explicitly **not** a duplicate of #4169, which owns
   initiation/approval; the join contract owns only reading and freshness.
8. **Usage/consumer edge** — coordinate with the CKM linker-precision workstream; new linker
   family or standalone doctor.

Conversion to a specification directory and issues routes through `feature-breakdown` with the
owner's prioritization; this audit files nothing.
