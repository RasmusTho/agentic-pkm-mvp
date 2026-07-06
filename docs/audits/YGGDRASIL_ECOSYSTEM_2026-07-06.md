State: Advisory audit snapshot (2026-07-06). Subordinate to `docs/DOCS_INDEX.md` and owner contracts. Whole-ecosystem pass over five surfaces (Yggdrasil topology, Heimdal, Mimer, Bifrost, Builder System/SBS); no specification directory — the primary output is one owner decision point (§9) plus a reconciled backlog (§10). No issues are filed by this pass.
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis; hub anchors reflect `origin/main` at `3d02ca7b` (2026-07-06); Bifrost anchors reflect `RasmusTho/bifrost` at `978999c`. Where this audit and an owner doc disagree, the owner doc wins; divergences route via issue, never silent resolution. Builder System work producing an advisory Product-analysis artifact; this audit changes no authority and enacts no reshape.

# Yggdrasil Ecosystem Audit — five surfaces, one system

**Date:** 2026-07-06
**Charter:** Epic B's first implementation wave (B1, `bifrost#1`) adds a third live writer (the iPhone shell) against the same iCloud vault the Mac runtime and Obsidian already write. Surface the multi-writer consistency question — and anything like it — deliberately, while the blast radius is one thin client.
**Method:** architecture-research pass (`.codex/skills/architecture-research/SKILL.md`). Six parallel read-only evidence explorers (Yggdrasil/ADR claims; Heimdal shipped code; Mimer contract reality + Epic B threads; Bifrost repo + bifrost#1; SBS/skills cross-repo census; vault write-path mechanics) under the evidence-only contract; central synthesis; every load-bearing anchor re-verified by the coordinator against the worktree before commit.
**tcd_plan:** coordinator = Fable/xhigh (architecture synthesis, high defect cost per `AGENTS.md :: Total Cost of Development`); five explorers Sonnet (anchored evidence collection, coordinator-verifiable), one explorer Opus (vault write-path crux — hidden-invariant risk). Fan-out rationale: five independent evidence surfaces plus one crux, no shared mutable state, read-only.

## Executive summary

Ranked by systemic impact (blast radius × silence of failure):

1. **Multi-writer vault consistency is UNDESIGNED (RQ1).** No ADR, contract, invariant, or issue governs concurrent writes to the same vault note from more than one live writer. The general write primitive is a blind in-place overwrite; today's behavior for a human-vs-runtime collision is silent last-write-wins on the canonical human-authority store. B1's own issue text forbids inventing the model client-side and mandates escalation — this audit is that escalation (§2, §9).
2. **The "Mimer client contract" that Epic B consumes does not exist as an artifact.** #3020/#3023/`bifrost#1` cite it by name; no file, schema, or spec in the hub defines it, and the design-of-record is an uncommitted file on the operator's Desktop. What actually exists for a client is vault markdown itself — which lands the client interface exactly on the undesigned surface of finding 1 (§3).
3. **Cross-repo governance is asserted by ADR-0050 but not written back into the Builder System.** The SBS operating model is repo-silent, its own source-of-truth-matrix rule was not followed when ADR-0050 landed, D11/D12 don't contemplate a second repo, and the delivery skills are repo-implicit (`gh` without `--repo`) up to hardcoded-slug breakage. The whole adaptation layer lives hand-authored inside Bifrost, invisible from the hub (§4).
4. **Contract quality is inverted across the Heimdal→Mimer→client chain.** The machine-to-machine seam (Heimdal observation events) is versioned and schema-tested; the human/client-facing seams (`_heimdal/**` control notes, client API) are implicit conventions or unversioned routes. Drift risk is highest exactly where B1 attaches (§3).
5. **ADR aspirational residue is bounded and mostly self-declared** — but a few claims read as shipped and are not: Epic A's closure says "the full ingestion vertical is live" while the capture adapter has no runtime driver on main (open PR #3095); ADR-0046's enforcement hook doesn't exist; ADR-0045's tiers have no code enforcement; Heimdal's charter docs still self-describe as "no runtime behavior" beneath ~8.9k lines of shipped code (§5, §6).

What demonstrably works and should be named as such: Heimdal's write discipline (every vault write routes through the governed port + WriteGuard, no divergent path found), versioned+tested Heimdal event schemas, Bifrost's scaffolding honesty (every gap self-declared, escalate-don't-invent clauses in B1), and the ecosystem naming/topology reconciliation (ADR-0044 + GLOSSARY are coherent; Yggdrasil = apex, Mimer + Heimdal + private-bindings = constituents, Bifrost = client-surface repo, not a constituent).

## §1 The holistic map (as evidenced, not as narrated)

**Yggdrasil** is doctrinal, not code: the ecosystem apex/whole (`docs/GLOSSARY.md:26`, ADR-0044 §"acknowledged SoS"). No runtime component claims to be it. **Mimer** is the shipped system (`app/`, plus `mimer_runtime/` — which is a test-time conformance harness: "no real vault, no durable mutation, no WriteGuard write path", `mimer_runtime/__init__.py:1-14`, never imported by `app/`). **Heimdal** is shipped code: `app/heimdal/` (24 modules), 5 append-only DB tables via migrations, versioned `heimdal.*.v1` event schemas, all vault writes through the governed port (E2 write-site census; e.g. `app/heimdal/capture_note.py:331`, `app/heimdal/entity_register.py:294-297`). **Hugin/Munin** are reserved names only (`docs/GLOSSARY.md:29`). **Private-bindings** is deliberately extra-repo (ADR-0044). **Bifrost** (`RasmusTho/bifrost`, private, HEAD `978999c`) is 12 files of governance scaffolding — AGENTS.md routing authority to hub ADRs, mirrored `_shared/` contracts, honest self-deactivating Swift CI (`bifrost:.github/workflows/ci.yml:71-89`, 0 runs ever) — and zero Swift code. `bifrost#1` (B1) is claimed, no PR exists. **Federation** is vocabulary, not mechanism: SFC is a single-node no-op stub (`app/sfc/replication_envelope.py:38-39`, ADR-0020), and MCP topology is explicitly Deferred (ADR-0047) with the silent-fallback `except Exception: pass` residual live at `app/orchestrator/mcp_tool_provider.py:41,79,123,162`.

The **live writer set against one iCloud vault** today: (1) the Mac runtime (≈11 writer call sites over four filesystem primitives — §2), (2) the human via Obsidian, (3) iCloud sync itself as a transport that can materialize conflict artifacts, and — the moment B1's write path lands — (4) the iPhone shell, writing `_heimdal/**` and vault notes "read/write" (`bifrost#1` AC3). B3 later adds Watch-originated capture files into the same vault (Model 1 transport, `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md:36-42`).

## §2 RQ1 — multi-writer vault consistency: **UNDESIGNED**

**Verdict: undesigned.** Not "partially designed": no decision exists, and the one real mechanism is narrow, un-generalized, and never framed as the answer to this question. Stated per the evidence contract:

**What exists (verified):**

- The central write primitive is a blind in-place overwrite: `FsVaultAdapter.write_note` = `target.write_text(...)` (`app/knowledge/adapters.py:29-33`); `append_note` = `open("a")` (`:35-40`). No temp-file+`os.replace`, no fsync, no lock, no stale-check. Verified zero hits for `os.replace|tempfile|fsync|fcntl|flock|O_EXCL` in the knowledge port and its callers.
- One genuine compare-and-swap exists: `OptimisticWriteGuard.write_if_unchanged` (sha256 CAS, `app/components/concurrency.py:118-131`) — used **only** by the panel-watcher/outbox-worker/note-update rewrite family (`app/watcher/registry.py:291-300`, `app/watcher/vault_watcher.py:711-718`, `app/workers/outbox_worker.py:684-687`, `app/services/note_update.py:54,109`), with a TOCTOU window between read (`:126`) and write (`:130`). The general port that memory/Heimdal/capture/MCP writes flow through has no CAS.
- `WriteGuard` is a **health-state** gate (blocks writes in unhealthy/safe-mode states, `app/write_guard.py:52-70`), not a concurrency mechanism. It is asserted at the overwrite port seams (`app/knowledge/write_ops.py:71,111`) but **not** at `append_note_relative` (`:118-127`), which is reached live by the capture API, inbox, and Heimdal interest-steering.
- The watcher detects changes by mtime+content-hash polling (`app/watcher/registry.py:934-945`) with **no writer provenance and no self-write suppression** beyond byte-identical-hash skip: a third writer's files echo through ingest exactly like human edits.
- iCloud conflict artifacts are unhandled: the only scan filter is `filename.endswith(".md")` (`app/vault/manager.py:241`), so a `Note (conflicted copy).md` would be ingested as an ordinary note; zero hits for `icloud|conflicted copy|NSFile` across `app/watcher/ app/vault/ app/ingest/`.

**What does not exist (searches run and verified):**

- No governing decision. ADR index scanned in full; every adjacent hit is other-scoped: ADR-0019/GOVERNED_WRITE_PROTOCOL = write *authority*; ADR-0020 = SFC declared single-node no-op; ADR-0025 = semantic precedence of human truth; ADR-0031 = authority-changing sync conflicts need governance (semantic tier, no file mechanism); D13/D14 = vault *binding* split-brain (which vault a process points at — a different problem); ADR-0014 = path injection.
- The `sync_preserves_boundaries` invariant ("sync never resolves a semantic conflict by last-writer-wins") is `schema_enforced` in part + `xfail_runtime_skeleton`, waiting on "a future SFC runtime" (`docs/testing/invariant-tests.md:287-299`). It states the principle for future federation; nothing enforces it for today's iCloud multi-writer reality.
- `docs/contracts/REPLICATION_ENVELOPE.md` names conflict staging as *target-state vocabulary* ("single-node / no-op … stages a placeholder", `:1,99`); no code classifies or stages a real conflict.
- No issue frames it. #2901 ("dual writer") is the Postgres store-writer duplication, not the vault. Searches for `vault conflict`, `concurrent write`, `icloud`, `multi-writer`, `conflicted copy` across issues: zero on-topic hits.
- The Fable-5 audit (`docs/research/yggdrasil-fable5-audit.md:105,162`) names "per-file advisory locking" as a cross-cutting, **unscheduled** gap — an observation, not a decision.

**Consequence today:** for every writer outside the panel-watcher family, a collision between any two of {runtime, Obsidian human, iCloud sync, future B1 client} on the same note is resolved by silent last-write-wins, on the store the whole doctrine treats as canonical human authority. The failure is silent by construction — nothing detects, logs, or surfaces it.

**What a decision would need to cover** (scope only — this audit does not design the answer, per charter):

1. The **writer inventory and write-primitive semantics** — whether vault writes must be atomic (temp+rename), stale-detecting (CAS generalized beyond the panel family), both, or explicitly neither-with-recorded-acceptance; and whether the `append_note_relative` guard gap closes as part of it.
2. **Conflict posture** — detect-and-refuse vs detect-and-stage (relationship to REPLICATION_ENVELOPE/GOV vocabulary must be stated: adopt, defer, or declare out-of-scope) vs accepted last-write-wins per note class.
3. **iCloud transport semantics** — conflicted-copy artifacts: detected/surfaced/quarantined, or explicitly accepted as ordinary notes; `.icloud` dataless placeholders on a device that hasn't materialized files.
4. **Writer provenance / echo** — whether ingest needs to distinguish runtime/human/client writes at all, or byte-hash idempotence is declared sufficient.
5. **The client write mechanism for Bifrost** — direct file I/O (which iOS API class) vs hub API; today it is specified nowhere in either repo.
6. **Note-class differentiation** — whether `_heimdal/**` control notes, capture/inbox appends, companion notes, and human prose notes get one rule or several (append-only surfaces have materially easier concurrency than rewritten surfaces).
7. **Enforcement** — which invariant(s) from §7 become MUST/GATE/DOCTOR, so the decision doesn't rot as prose.

## §3 RQ2 — contract boundaries: Heimdal → Mimer → Bifrost-clients

| Interface | Form | Versioned? | Tested? | Verdict |
|---|---|---|---|---|
| Heimdal observation publish → Mimer projector | JSON Schema per topic + cursor consumption | Yes (`schemas/events/heimdal.observation.published.v1.schema.json`) | Yes (`tests/heimdal/test_event_schemas.py:110-151`; validate-before-insert in `app/heimdal/publish.py`) | **Real, versioned, testable contract** |
| Heimdal → vault (capture notes, entity register, candidate projection) | Governed port writes, WriteGuard-asserted at every site | Port API is the contract; no shape version | Unit-tested per module | Real mechanism; note *shapes* implicit |
| `_heimdal/**` control surface (settings/interests/consent/attention/entities) — **the exact surface B1 renders read/write** | Markdown notes; schema exists only as an in-process Python registry (`app/heimdal/settings_notes.py:187-219`) | No published schema artifact | In-repo tests only | **Implicit markdown-shape convention** |
| Note shapes generally (frontmatter Core-6, companion note, metadata bundle, context envelope) | Canonical docs + JSON Schemas | Yes for metadata-bundle/context-envelope (`schemas/*.schema.json`); docs-canonical for frontmatter/companion | Partially | Best-documented layer; `episode_ref` ratified (ADR-0051) but schema/runtime wiring deliberately open |
| Hub HTTP API (what a client might call) | 21 route files, mounted at bare `/api` (ingest/search unprefixed — `app/api/app.py:213-241`) | **No** path/header versioning; `api/openapi.yaml` documents 2 of ~21 route modules (`/ingest`, `/search` only) | In-process TestClient regression tests; no consumer-publishable contract | **Unversioned internal surface** |
| "Mimer client contract" (named by #3020/#3023/`bifrost#1`) | — | — | — | **No artifact exists.** Design-of-record = `~/Desktop/heimdal-ux-design/APP_TOPOLOGY_AND_PLATFORMS.md`, operator-local, uncommitted |
| Auth for a remote client | Static `X-API-Key` or loopback/trusted-proxy (`app/auth.py:14-92`) | — | tested | No per-device identity/session model; gap unmentioned in Epic B bodies |

**Where drift risk is highest:** precisely at B1's attachment point. The machine seam Heimdal→Mimer is the strongest contract in the ecosystem; the client seam is the weakest — an unversioned in-process note-shape registry plus a named-but-nonexistent client contract whose real definition lives outside version control. A hub-side change to `settings_notes.py` shapes would break a shipped iPhone client with no schema diff, no version bump, and no CI signal in either repo.

## §4 RQ3 — cross-repo governance load

ADR-0050 is internally consistent and shipped as scaffolding (E4 verified every operative claim against the Bifrost repo). The strain is that **nothing on the hub side was written back**:

- `docs/architecture/SBS_OPERATING_MODEL.md` §3 defines the Builder System entirely by function, never by repo; §2's own rule ("if a new SBS concern appears, add a row here naming exactly one owner doc", `:66`) was not followed for the new cross-repo concern. `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` and the boundary register: zero Bifrost/cross-repo mentions.
- `docs/architecture/SBS_TRANSITION_DEBT.md` D11/D12 (CES overload; builder-learning capture) are the two rows conceptually closest to this strain and neither contemplates a second repo; ADR-0050 landed without reducing a row, adding a row, or stating no-debt-effect — violating the register rule (`SBS_OPERATING_MODEL.md:344-351`).
- **Skill census** (all 26 skills + `_shared`): only `learning-to-issue` threads `--repo` through every `gh` call. `issue-to-code`/`publish-pr`/`issue-maintenance-change-control` are repo-implicit (cwd-remote-dependent; `publish-pr` at least derives `$REPO` from the remote). Hard breakage: `automation-maintenance` keys on the literal `RasmusTho/agentic-pkm-mvp` slug and an absolute local path; `capture-learning`/`learning-retrospective` require the hub's Python BuilderOps CLI (`python -m app.cli builderops …`) — **builder learning from Bifrost work currently has no capture path at all**; `docs-authoring`'s lane allow-list is a literal hub path list; the five promotion skills are Docker/Postgres-substrate-specific with no analog for an App Store/TestFlight release; `feature-breakdown` states "creates issues in the shared repo" (singular) (`.codex/skills/feature-breakdown/SKILL.md :: Publication discipline`).
- Bifrost has **no equivalent** of the hub's surface-allowlist/PR-contract gate (`issue-pr-governance.yml`), import-linter, or Project-board sync — neither reimplemented nor explicitly waived; its own CI has never executed (0 runs).
- Coordination overload point: **CES/ADR authority spans both repos by decision, but every CES surface (ADR index, DOCS_INDEX, invariant registry, debt register) is hub-only with no defined route for a Bifrost-side concern.** ADR-0050 points classification at the operating model, which doesn't answer the question it's pointed at.

**Sustainability through B2/B3:** survivable for B1 (one issue, one implementer, owner = the same human on both repos) because the adaptation is carried in the operator's head and Bifrost's hand-authored mirror files. It degrades with each wave: mirrored `_shared/` files drift silently (no census/gate covers them), learning signals from Swift work are already being dropped, and any parallel-agent delivery against Bifrost inherits the repo-implicit `gh` hazard. This is D11/D12-shaped debt that the register doesn't yet name.

## §5 RQ4 — ADR-0043/0044/0049/0050: load-bearing vs aspirational

Condensed to claims that matter for Epic B (full claim tables in the explorer evidence, coordinator-verified):

| ADR | Load-bearing (backed by artifact) | Aspirational / open (no artifact or explicitly deferred) |
|---|---|---|
| 0043 | Heimdal=sensor retained; observability=OEF (no alias) | Munin/Hugin split — formally superseded by 0044 (both docs remain, header-marked) |
| 0044 | Apex/constituent model (GLOSSARY reconciled); `mimer_runtime` rename **already enacted** (PRs #3011/#3015) though the ADR text still reads "deferred"; SoS-spans-repos precedent (private-bindings) | Entity-register/substrate *contract docs* (OD-5/OD-9) — code exists (`app/heimdal/entity_register.py`), doc-level contract does not |
| 0049 | Heimdal pipeline shipped as code (capture→raw store→ASR→attribution→publish→projection), Posture A consent fields, markdown-first surface | "All sources" (voice-memo only today); **no runtime driver calls `run_watch_cycle`** on main — open PR #3095; Topology C apps (now Epic B's job); device-telemetry bend |
| 0050 | Bifrost repo + inherited governance scaffolding (all §Consequences claims verified in-repo); tracking stays in hub | Spelling enactment #3060 open in code (`heimdall_root`, `app/settings/models.py:336`); hub-side Builder System writeback absent (§4); Bifrost CI never executed |
| 0045/0046/0047 (context) | Operative rules recorded; ADR-0047 correctly self-labels Deferred | 0045 tiers: no code/CI enforcement (follow-up #2891); 0046: `scripts/public_seam_lint.py` does not exist; 0047 residual: silent MCP fallback live in code |

Adjacent doc-truth divergences (each dual-anchored by explorers, spot-verified): Heimdal charter docs self-declare "Draft … no runtime behavior" (`docs/HEIMDAL/README.md:1`, dated 2026-07-04) under ~8.9k lines of shipped code; Epic A #3019 closure states "the full ingestion vertical is live on main" while the capture adapter is a library with no scheduled caller (PR #3095's own body states this); hub #3023 still carries the "separate app repo — owner to confirm" hedge that ADR-0050 resolved; `docs/foundation/00-yggdrasil-doctrine.md` filename vs its own "Mimer Doctrine" content.

## §6 Gap ledger — ranked by what each blocks

| # | Gap | Status | Blocks |
|---|---|---|---|
| G1 | Multi-writer vault consistency (§2) | **Undesigned**; no owning artifact; B1's escalate-clause has nowhere to point | **B1 write path** (its own issue text forbids proceeding), B2, B3, and current two-writer reality (human+runtime collide today) |
| G2 | Mimer client contract nonexistent; design-of-record uncommitted on Desktop (§3) | Undesigned as an artifact; violates issue-self-sufficiency posture (ACs verify against a file agents can't read) | B1 verification honesty; B2/B3 directly |
| G3 | `_heimdal/**` note shapes = in-process convention at the exact client seam (§3) | Partially designed (code registry, no published schema) | B1→B3 drift risk; grows with every hub-side Heimdal change |
| G4 | Cross-repo Builder System writeback absent: repo-silent operating model, D11/D12 unamended, repo-implicit skills, no Bifrost learning-capture path (§4) | Undesigned (debt unnamed in the register) | Sustainable B2/B3 delivery; general ecosystem health |
| G5 | Heimdal capture runtime driver missing vs closure claim | Known & tracked — open PR #3095; the *closure-comment overclaim* is the residual | Heimdal value delivery; trust in closure receipts |
| G6 | Client auth model absent (static key/loopback only) | Undesigned for remote devices; unmentioned in Epic B | Only API-consuming client slices (moot for pure file-I/O clients — depends on G1's mechanism ruling) |
| G7 | Doc-truth hygiene batch: Heimdal charter headers, ADR-0044 "deferred" wording, #3023 stale hedge, #3060 code spelling, stale `api/openapi.yaml` | Drift, individually small | General health; reader trust in State: headers |

## §7 Invariant extraction (extends `docs/testing/invariant-tests.md`; no competing registry)

| ID | Invariant | Category | Status |
|---|---|---|---|
| INV-VW1 | A runtime writer must not silently overwrite a vault note that changed since it was read (stale-write rejection at the write primitive) | MUST (target; exact mechanism is G1's owner decision) | **Violated today** for the general port (`app/knowledge/adapters.py:29-33`); exists narrowly (`OptimisticWriteGuard`, panel family) |
| INV-VW2 | Every vault write seam asserts the WriteGuard | GATE | **Violated today**: `append_note_relative` (`app/knowledge/write_ops.py:118-127`); enforceable now, independent of G1 |
| INV-VW3 | iCloud conflict artifacts (conflicted-copy notes) are detected and surfaced, never silently ingested as ordinary notes | DOCTOR (posture decided in G1) | New; today absent (`app/vault/manager.py:241`) |
| INV-CB1 | Every contract a sibling-repo client consumes exists as a versioned artifact in the hub; an issue body or operator-local file is not a contract carrier | DOCTOR | **Violated today** ("Mimer client contract", G2; `_heimdal/**` shapes, G3) |
| INV-XR1 | Every repo the Builder System develops has a named owner-doc row in the `SBS_OPERATING_MODEL.md` §2 matrix, and cross-repo debt is carried as register rows | DOCTOR | **Violated today** (§4; register rule `SBS_OPERATING_MODEL.md:344-351`) |

Minimal kernel: **INV-VW1 + INV-CB1** carry this audit's claims (writes to the canonical store are collision-safe or loudly refused; what clients consume is a committed, versioned artifact). VW2 is existing-discipline repair; VW3/XR1 are defense in depth.

## §8 SBS reconciliation (binding)

| Claim / output | Classification vs `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` + `docs/architecture/SBS_*` |
|---|---|
| G1 verdict + decision-scope list (§2) | **Conform** — names a gap at the WSP/HKA/EBF/SFC seam; decides nothing. The decision itself is owner/CES-routed (ADR-class); adjacent rows D7/D13/D14 are referenced, not modified |
| Contract-boundary findings (§3) | **Conform** — seam evidence within existing boundaries (EBF/HKA/HIX) |
| Cross-repo writeback gap (§4) | **Extend (proposed, routed)** — asks the operating model/debt register to name a concern their own rules require them to carry; the actual row additions are follow-up work, not enacted here |
| ADR claim audit (§5) + doc-truth divergences | **Conform** — divergence reporting per the register/charter framework |
| Invariants (§7) | **Extend** — new candidate rows for the existing registry; INV-VW1's mechanism is explicitly deferred to the G1 owner decision |

No reshape is proposed or enacted by this audit.

## §9 Recommendation and the decision point (owner)

**Answer to the chartered question: yes — the vault-consistency question needs an owner ruling of ADR class, and it is needed before B1's write path merges, not just before B2.** B1 as contracted cannot deliver its write-enabled acceptance criteria without it: `bifrost#1` itself says "consistency model must be respected, not redesigned here" and "if it turns out undesigned, stop and escalate to the hub" — it is undesigned (§2), so the escalate-clause has now fired. B2/B3 inherit the same surface (B3 adds Watch-originated files via iCloud).

The decision is one problem with the seven cover-items of §2. Options, with consequences:

- **Option 1 — ADR now (recommended).** One architecture session over §2's cover list before any Bifrost write code exists. Consequence: B1 proceeds honestly; one ruling covers B2/B3 and also today's already-live human-vs-runtime silent LWW; the blast radius argument in this pass's charter ("while it's one thin client") is exactly why now is cheap. Cost: days of decision latency on B1's write slice; B1's read-only/scaffolding half (shell, vault pick, rendering) is not blocked meanwhile.
- **Option 2 — explicit interim posture, ADR before B2.** A recorded hub-side owner ruling (not a comment buried in `bifrost#1`) that names the accepted risk (silent last-write-wins on collision), constrains B1's write scope for the interim as the owner sees fit, and books the ADR before B2 starts. Consequence: B1 fully unblocked fastest; risk window is real but recorded and bounded to one client; the ADR work is deferred, not avoided.
- **Option 3 — proceed silently.** Rejected: contradicts `bifrost#1`'s own contract text and the fail-loud doctrine; leaves the current two-writer collision behavior unowned as well.

This audit deliberately does not choose the consistency *mechanism* (locking vs CAS-generalization vs atomic-replace vs per-note-class postures) — that is the ruling's content, per the pass charter.

## §10 Reconciled backlog handoff (no issues filed by this pass)

Reconciliation notes first: D13/D14 (vault *binding*) and #2143 (multi-vault registry) are adjacent, not duplicates — the G1 decision should cite them and stay note-level. #2901 stays DB-scoped. REPLICATION_ENVELOPE/D7 owns the future-federation conflict vocabulary; the G1 ruling must state its relationship to it, not fork it. #3060 (spelling), #3095 (capture runtime wiring), #2891 (ADR-0045 enactment), #2890 (ecosystem doc reconciliation) already exist — extend, don't re-file. The Fable-5 audit's "per-file advisory locking" line and `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md` are inputs to T1. Epic B #3020: T1/T2 gate the write-facing halves of #3023/#3024/#3026.

| ID | Task | Depends on | Verify: |
|---|---|---|---|
| T1 | **Owner ruling (ADR-class): multi-writer vault consistency** — decide §2's seven cover-items; record chosen option from §9 | — (owner) | An ADR (or recorded Option-2 interim posture) exists covering the seven items; `bifrost#1`'s escalate-clause can cite it; INV-VW1/VW3 rows added to the registry with their decided categories |
| T2 | Materialize the client contract: commit the surfaces B1 consumes (`_heimdal/**` note-shape schema or published equivalent of the `settings_notes.py` registry, vault-note contract pointers, write-mechanism rule from T1); move the design-of-record off the operator Desktop into the hub | T1 (write half) | Every Source Anchor in `bifrost#1`/#3023 resolves to a committed artifact; "Mimer client contract" greps to a real file |
| T3 | Close the `append_note_relative` guard gap (INV-VW2) | — (independent of T1) | Seam asserts WriteGuard like `write_note_relative` (`write_ops.py:110-111` pattern); regression test |
| T4 | Cross-repo Builder System writeback: §2-matrix row + §3 repo-scope statement in `SBS_OPERATING_MODEL.md`; new debt row(s) for cross-repo learning-capture and skill repo-parametrization (per the register rule); decide mirrored-`_shared` drift posture | — | Matrix names an owner doc for cross-repo scope; debt register carries the rows; D11/D12 texts reference them |
| T5 | Skill repo-parametrization slices (priority: `gh --repo` in issue-maintenance/issue-to-code; `feature-breakdown` "shared repo" wording; a learning-capture path usable from Bifrost) | T4 (classification) | The named skill lines carry explicit repo targets or a stated single-repo precondition |
| T6 | Doc-truth hygiene batch (G7): Heimdal charter `State:` headers, ADR-0044 enacted-rename note, #3023 stale hedge edit, `api/openapi.yaml` staleness disposition; add closure-caveat to #3019 re the #3095 wiring gap | — | Each named header/body reflects shipped reality; #3019 thread carries the caveat |

Handoff: T1 is an owner decision, not decomposition — it routes to the owner directly. T2–T6 route through `feature-breakdown`/`docs-to-issue` after T1 lands (or immediately for T3/T4/T6, which are T1-independent).

## §11 Owner rulings (2026-07-06, post-audit)

The owner ruled the §9 decision the same day. Recorded here so the audit is not read as an open question:

- **Vault write model → interim posture, not ADR-first (§9 Option 2 chosen over the recommended Option 1).** Concurrent same-note writes stay silent-last-write-wins for now; the full multi-writer vault-consistency model is a dedicated ADR gated on **B2**. Recorded in **`docs/adr/ADR-0053-interim-vault-multiwriter-posture.md`**; full decision tracked at **#3114** (the seven cover-items of §2). T1 is therefore *split*: interim (done, ADR-0053) + full (deferred to #3114).
- **B1 write scope → unconstrained.** The iPhone shell may read/write any note from day one, including human prose notes — the full risk window is accepted for the B1 wave and owned in ADR-0053.
- **Client contract (T2) → commit the design-of-record as-is.** The owner's `APP_TOPOLOGY_AND_PLATFORMS.md` is committed at **`docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md`** (topology/platform design B1 is verified against). Note this is the *topology* contract; the machine-facing note-shape contract (G3) remains open T2 work.

Unchanged: T3 (append-guard, INV-VW2), T4/T5 (cross-repo Builder writeback), T6 (doc-truth batch) remain decision-independent follow-ups.
