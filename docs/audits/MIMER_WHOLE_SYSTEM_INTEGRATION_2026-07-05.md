State: Advisory audit snapshot (2026-07-05). Subordinate to `docs/DOCS_INDEX.md` and owner contracts. Live-system integration pass over the running dev channel; no specification directory — findings route to bounded issues directly (#2988–#2993) and to existing hubs (#2981, #2969, #2901, #2597).
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis of the RUNNING system; file:line anchors reflect `main` at 2026-07-05 (deaf17c4, pre-fix). Where this audit and an owner doc disagree, the owner doc wins; divergences route via issue.

# Mimer Whole-System Integration Audit — dev channel, live pass

Date: 2026-07-05
Basis: a real note driven through the full chain on the running `pkm-dev` stack (Mac mini/Demerzel, Colima), observed at every seam with logs, DB rows, outbox rows, HTTP responses, and container state — plus four parallel code explorers anchoring each observed break to source. Channels observed: `pkm-dev` (driven), `pkm-test` (observed read-only), `pkm-prod` (read-only, untouched).

Charter: individual parts pass their own tests; the question was whether the WHOLE chain holds:
`note create/edit → watcher → ingest → embed → index → retrieval → synthesis → surface (chat/companion UI) → decision receipt`.

Answer at audit time: **the chain did not hold warm.** It closed end-to-end only after an API restart, with three seams broken outright (note→watcher when layout drifts, warm retrieval freshness, companion-UI ask) and two more degraded (index truth vs vault reality, health observability). Every break was silent except the test-channel crash-loop — silence, not breakage, is the systemic finding.

## Method

1. Baseline health capture (`/api/health`, `/readyz`, `/api/status`, container states, ollama tags, DB counts).
2. Probe note with a globally unique marker written to the dev vault; every seam observed with evidence (outbox rows, `store_objects`/`store_vector_index` rows, worker/watcher logs, ask responses, receipt files).
3. Four parallel read-only code explorers (retrieval substrates; watcher gating/scope; heartbeat + index-health drift; receipts/surfaces) under the evidence-only contract — every claim anchored `file:line`.
4. Conflicts between explorer claims and live behavior re-read against the running containers (one explorer claim corrected this way; see G1 mechanism).

## Seam-by-seam scorecard (pre-fix, evidence per cell)

| Seam | Verdict | Evidence |
| --- | --- | --- |
| note → watcher | **FAIL (silent)** when vault layout drifts from configured scope; PASS (<1s) in scope | Probe at vault root ignored for 45s (zero new `outbox` rows); identical note under `📥 Inbox/` produced `panel.scan.requested` + `ingest.vault.changed` within 1s, both delivered <2.1s |
| watcher → outbox → ingest | PASS | `store_objects` row `76b027af…` created 13:21:24Z, same second as event delivery; worker log "healed uuid for inbox note" |
| ingest → embed → index | PASS | `store_vector_index` row for `76b027af…` at 13:21:25Z with correct identity (ollama / nomic-embed-text / 768 / normalize=t) |
| index → retrieval (warm) | **FAIL** | Unique-marker `/api/ask` query did NOT return the note containing the marker verbatim; after `docker restart pkm-dev-api-1` the same query returned it as top source |
| retrieval (`/search`) | **FAIL** | Two unrelated queries returned the identical 10 uuids in identical order, all titles empty |
| retrieval truth vs vault | **DEGRADED** | Ask sources dominated by vectors for files that no longer exist (`⚙️ System/companions/*.md`) and duplicate rows; `/api/health` `embedding_index`: 6 unembedded objects, 36 rows missing metadata, `rebuild_required` |
| synthesis | PASS | Grounded answer quoting the probe verbatim; `latency_ms` 47949 on ollama route |
| synthesis → receipt | PASS | `synthesis_receipt_id` persisted to `/app/runtime/activation/ask_synthesis_receipts.jsonl` |
| surface: companion UI chat | **FAIL** | `POST /api/operator/ask` → `{"error":"runtime_unavailable","message":"timed out"}` every time |
| decision receipt (chat path) | N/A by design | Chat/ask emits synthesis receipts only; decision receipts come from ingest-time governance agents (see G8) |
| health surface | **FAIL (false negative)** | `/api/health` watcher/worker "not running (no heartbeat)" while both containers logged live heartbeats |
| test channel (context) | **FAIL (loud)** | `pkm-test-watcher-1` restart-looping, exit 1 |

## Gap ledger (anchored)

| Gap | Defect | Anchors | Disposition |
| --- | --- | --- | --- |
| G1 | Watcher scope glob (`WATCHER_SCOPE_GLOB` → `📥 Inbox/*.md`) matched a nonexistent directory; registry ticked "healthy" matching zero files with no signal. Mechanism: `_resolve_scope_glob` env-first (`app/watcher/registry.py:73-87`), applied to specs at `:483,551`; no zero-match or missing-prefix validation anywhere in `registry.py`/`scope.py`; heartbeat reports `running` unconditionally (`app/watcher/heartbeat.py`) | `app/watcher/registry.py:73-87,109-128,483,551`; `app/watcher/scope.py:9-73` | **#2988** |
| G2 | `/api/ask` serves from an in-process `MemoryHybridStore` rebuilt once per process (`_REBUILT_FROM_DURABLE_INDEX`, `app/retrieval/hybrid.py:204,224-226`); no ingest path forces refresh — fresh notes invisible until restart. Violates the KERNEL-05 cache-of-durable-truth intent (`docs/RUNTIME_CORRECTNESS_KERNEL/RETRIEVAL_READS_DURABLE_INDEX.md:20-22`) | `app/retrieval/hybrid.py:203-247`; `app/api/app.py:179-202`; `app/api/routes/ask.py:19-41,112-113` | **#2981**, FIXED — PR #3003 (`611f7180`): `VectorIndex.generation()` + serving-path revalidation, ≥1s min-check interval; live warm re-proof passed |
| G3 | `GET /search` joins permanently-empty legacy `objects_embeddings` (created empty by bootstrap migration, no INSERT path in `app/`), swallows all errors (`except Exception: rows=[]`), falls back to query-independent `_recent_objects()` from legacy `objects` | `app/api/routes/search.py:36-63,78-101`; `app/alembic/versions/fe9a3607841f_bootstrap.py:36-41` | **#2989** |
| G4 | Watcher computes `VaultWatcherResult.deleted` every tick but nothing consumes it; purge machinery (`purge_object_vectors`, `INGEST_OBJECT_DELETED` tombstones) reachable only from app-initiated `delete_note` — filesystem deletes/renames leave ghost vectors forever | `app/watcher/vault_watcher.py:249-265,306-323,393`; `app/services/indexer.py:31-60`; `app/workers/outbox_worker.py:386,440-461`; `app/services/vault_sync.py:232-282` | **#2990** (prio:high) |
| G5 | `/api/health` watcher/worker liveness structurally false-negative: writer and reader resolve the identical absolute path (`config/runtime.defaults.env:23-25` → `/app/tmp/*.json`) but api/worker/watcher containers share no `/app/tmp` volume (each `mkdir -p /app/tmp`); `export_runtime_env.sh` rewrites paths only for the test channel | `app/cli/health.py:473-498`; `app/watcher/heartbeat.py:15-20`; `app/runtime/worker_heartbeat.py:11-20`; `docker-compose.yaml` service volumes; `scripts/export_runtime_env.sh:246-272` | **#2991**; feeds epic #2597 |
| G6 | `pkm-test-watcher-1` crash-loop: bound Bifröst vault has no `settings/vault.md` → `validate_vault`=`uninitialized` → `_IDLE_VAULT_STATUSES` flips `enable=False` (per #2005 idle contract) → CLI raises the misleading `WATCHER_ENABLE=1 required` and exits 1 → docker restart-loop. `WATCHER_ENABLE` itself is raw-env, NOT tier-gated (the adjacent `WATCHER_MAX_SCANNED_FILES_PER_TICK` tiering warning is a red herring) | `app/cli/watcher.py:61,100`; `app/watcher/registry.py:472-479,715-747`; `app/settings/tiering.py:16-51` | **#2992**; separately, the test vault needs operator initialization |
| G7 | Companion-UI ask proxy default timeout 2.0s vs ~50s real synthesis latency — chat surface always fails in dev | `companion-ui/.../serve_dev_page.py:159,176-189,15719-15760` | **#2993** |
| G8 | Decisions Postgres projection has zero production call sites (`rebuild_decisions_projection`/`doctor_decisions_projection` referenced only by tests); `decisions` table stale (13 rows, newest 2026-06-20). Canonical JSONL receipt log + projection design is #2969 (slices 1–3 merged); the *trigger* wiring is the open remainder | `app/jobs/decisions_projection.py:101-149,198-224`; `app/services/decisions.py:79-143`; emit sites `app/agents/{classifier,reviewer,set_evaluator}/agent.py` | tracked under **#2969**; no new issue |
| G9 (context) | Dev/test channels run bind-mounted working-tree code (`/Users/rasmus/workspace → /app` on the test watcher), not pinned images; cutover tracked by #2698 | `docker inspect pkm-test-watcher-1` mounts; `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` | existing **#2698**; noted, not re-filed |
| G10 | Token-dense chunks crash the ollama embedding runner (HTTP 500/EOF) inside the #2110 char budget (default 6000; one real 2000-char markdown chunk reproducibly fails while neighbors pass) → notes dead-letter permanently, pinning `embedding_index: rebuild_required`. This is the root cause of the baseline's 6 unembedded rows | `app/llm/embeddings.py:200-312`; `app/llm/embed_queue.py:119`; live bisect repro (budget 6000→4 fail, 2000→1 fail, 800→10/10 ok) | **#3045** |
| G11 | `/app/runtime` baked root-owned in the image while the service runs uid 501 → ask-synthesis receipt append `PermissionError` → every `/api/ask` 500s on every fresh api container (fail-loud is correct; the perms are the defect). A manual chown had masked this until redeploy | `app/activation/ask_synthesis.py:197` (symptom); Dockerfile /app/runtime ownership; compose api `user:` | **#3047** |

What demonstrably works (positive results worth keeping): watcher pickup latency <1s in scope; ingest/embed identity discipline (fresh rows carry provider/model/dim/normalize); synthesis grounding (verbatim quote of retrieved source); ask-synthesis receipt persistence; panel receipt-before-ack fail-loud (#2968, `app/panel/confirmation.py:577-632`); companion UI → API proxy wiring (`serve_dev_page.py:15719-15721`).

## Cross-system synthesis

Ranked by blast radius × silence:

1. **Silent-degradation pattern (G1, G3, G4, G5).** Four independent seams degrade with zero signal: a blind watcher reports healthy; a dead search endpoint returns plausible-looking filler; deleted notes persist as retrieval candidates; health reports live services dead. The system's failure posture is "keep looking normal", the exact inversion of the fail-loud contract (`AGENTS.md :: Required rules`). Fixes converge on one principle: *a component that observes nothing must say so*.
2. **Split-truth substrates (G2, G3, G8).** Three read paths served three different truths at audit time: `/search` read legacy `objects` (June truth), `/api/ask` read a boot-time snapshot (process-start truth), and `decisions` read a June projection. The durable stores were correct; every staleness lived in a derived/serving layer that lacked a freshness contract. G2's generation-token fix (PR #3003) is the template: derived layers must carry an explicit generation check against their durable source.
3. **Config/reality drift without preflight (G1, G6).** Both watcher failures are the same shape: configuration asserts a world (an Inbox dir; an initialized vault) that reality doesn't match, and the runtime neither heals nor reports — it no-ops (dev) or crash-loops with a wrong error (test). This is the `AGENTS.md` invariant→producers rule seen from the runtime side: a precondition without a preflight is a latent outage.
4. **Observability debt makes everything else invisible (G5 + `rebuild_required` fatigue).** Dev health was false-red on liveness and true-red on the index simultaneously; an operator cannot distinguish signal from noise, so red trains people to ignore red (epic #2597's thesis, confirmed live).

## Integration invariants (extend `docs/testing/invariant-tests.md`; no new registry)

| ID | Invariant | Category | Status |
| --- | --- | --- | --- |
| INT-W1 | A running watcher whose scope matched zero files this tick MUST surface that in its heartbeat/status; the health surface must be able to distinguish "watching, seeing files" from "watching, blind" | MUST | New (#2988) |
| INT-W2 | Watcher enable-off due to vault status idles the process; only explicit `WATCHER_ENABLE≠1` may exit; error text names the actual cause | MUST | Violated today (`app/cli/watcher.py:100`); #2992 |
| INT-W3 | A filesystem deletion observed by the watcher eventually removes the object's derived rows (tombstone path); vault reality and durable index converge | GATE | Violated today (`vault_watcher.py:393`); #2990 |
| INT-R1 | Every retrieval-serving substrate is a cache of the durable index with an explicit freshness/generation contract; a row upserted to `store_vector_index` becomes retrievable without process restart (bounded staleness) | GATE | Delivered by PR #3003 (`tests/invariants/test_retrieval_spine_invariants.py::test_retrieval_serves_durable_truth_fresh`) — keep |
| INT-R2 | No API read surface consumes the legacy `objects`/`objects_embeddings` tables | GATE | Violated today (`search.py:78-88`); #2989 |
| INT-R3 | Retrieval/serving failure surfaces as an error; no silent fallback to query-independent results | MUST | Violated today (`search.py:90-101`); #2989 |
| INT-H1 | `/api/health` liveness verdicts for watcher/worker reflect actual cross-container process state (no structurally unreachable heartbeat paths) | GATE (integrated-runtime UAT) | Violated today; #2991 |
| INT-S1 | The human chat surface's proxy timeout ≥ realistic synthesis latency for the configured route; health probes stay short | GATE | Violated today (`serve_dev_page.py:159`); #2993 |
| INT-D1 | The `decisions` projection is rebuilt/doctored by a wired production trigger, or the read path declares the projection advisory | DOCTOR | Open under #2969 |

Minimal kernel: INT-R1 + INT-W3 + INT-W1 carry the chain's correctness claim (what enters the vault becomes retrievable; what leaves the vault stops being retrievable; a blind ingester says so). The rest are defense in depth.

## SBS reconciliation

All findings **conform to** `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` boundaries as read: they are seam defects *between* existing subsystems (watcher/ingest, retrieval spine, health/observability, companion surface), not proposals to reshape subsystem boundaries. G2's fix extends the KERNEL-05 contract within its existing subsystem. No reshape is proposed; nothing here routes through the SBS stewardship channel.

## Fix receipts (updated through the pass)

- **#2981 / G2** — PR #3003 merged (`611f7180`): `VectorIndex.generation()` + serving-path revalidation.
- **#2992 / G6** — PR #3001 merged (`a96f3844`): watcher CLI idles on vault-idle, truthful error text.
- **#2993 / G7** — PR #3002 merged (`707bbffb`): dedicated `COMPANION_ASK_TIMEOUT_SECONDS` (120s) on the ask rewrite only.
- **#2991 / G5** — PR #3004 merged (`79e7515b`): shared `runtime-tmp` named volume; live-verified truthful liveness both directions. Follow-up #3010 filed for a pre-existing mirror-census gate failure discovered on main.
- **#2988 / G1** — PR #3007 merged (`d268aa5d`): heartbeat `scope_status` (`zero_match`/`missing_prefix`) degrades status; `docs/OBSERVABILITY.md` updated.
- **#2989 / G3** — PR #3009 merged (`95addf1c`): `/search` on the canonical substrate, fail-loud; transition-debt D15 closed.
- **#2990 / G4** — PR #3008 in repair at audit-close (unit-test failure); the only open fix.
- **#3045 / G10**, **#3047 / G11** — filed during the re-proof; dev unblocked operationally (index rebuilt 10/10 with a reduced chunk budget; runtime dir chown'd pending the durable fix).

## Closing warm-chain proof (2026-07-05, dev on merged main `cfbbc2d2`)

With zero restarts after note creation:

1. Note `Final Warm Proof 20260705T161654Z.md` (unique marker `kestrel-basalt-20260705T161654Z`) written to `📥 Inbox/` → watcher picked up, ingested, embedded (vector row confirmed) within ~45s.
2. `POST /api/ask` returned the note as TOP source with a grounded answer quoting the marker; synthesis receipt `4ed919dd9f734216adff9da055427115` persisted.
3. The same question through the companion UI proxy (`:8111/api/operator/ask`, rebuilt with #2993) returned the same grounded answer — the human chat surface works.
4. `/api/health`: `required_ok: true`, `embedding_index: ok` (first green health of the pass), watcher/worker liveness truthful (`runtime-tmp` shared volume verified in both directions).

The chain `note → watcher → ingest → embed → index → retrieval → synthesis → surface → receipt` holds warm on dev. Remaining open at audit close: #2990/PR #3008 (deletion reconciliation), #3045 (embed chunk bisect), #3047 (runtime perms), plus tracked items #2969 (decisions projection trigger), #2901 (dual writer), #2698 (pinned images), #2597 (observability epic).

## Research questions

- *RQ1: Does the whole chain hold warm on dev?* No at audit start (restart required); yes for the retrieval seam after PR #3003; full-chain warm proof pending remaining merges.
- *RQ2: Why do healthy parts compose into a broken whole?* Because the seams carry no contracts of their own: freshness (G2), truth-of-source (G3), convergence (G4), visibility (G1, G5) were all implicit. The invariant set above is the explicit version.
- *RQ3: Does the test channel reproduce dev failures?* Different failure, same class (G6 vs G1): config/reality drift without preflight. The watcher enable-gate itself is not tier-gated; the tiering warning in the crash logs is unrelated.
