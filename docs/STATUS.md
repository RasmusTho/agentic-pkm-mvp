State: SoT v5.5 Reality-MVP baseline locked (watcher auto-run gate, panel action provenance, and concurrency guard); v5.6 delivery line closed; v6.0 seams baseline shipped at capability-seam level (closed capability spec directories plus minimal orientation/resurfacing/commitment-domain/context-dimensions runtimes and read-only Chat cognition scaffold); broader v6.0 runtime consumption is deferred as v6.1+. Post-v5.6 follow-ups are tracked separately for LangGraph/Reasoning expansion, Orchestrator V2 hardening, A2A/MCP lifecycle cleanup, and local verification hardening. Contextualization Layer docs/spec package (#1093–#1097) delivered 2026-05-19 (life-wide taxonomy, context activation semantics, metadata contract update, media artifact contract, ingestion/triage policy, vault templates, vault audit runbook — docs-only, no runtime behavior changed). Agent Memory runtime slices for candidate/review/promotion/recall explanation/authority guard plus companion-note-aware handling are shipped (#1079/#1080/#1081/#1082/#1083/#1085), and the Durable Memory and Recall chain is shipped (#1904–#1908): vault-scoped review decision receipts survive restart, the review queue reconciles terminal decisions, promoted semantic memory materializes as an agent-promoted vault artifact through WriteGuard plus receipt, guarded recall emits recall receipts without persisting activation as authority, and Companion can surface materialized-memory provenance/posture. Companion UI: substantial dev/staging-shell capability now shipped to main. The vault Markdown renderer covers §6 typography, callouts, tables, images (real-image fixture verified), and resolved/diagnostic wikilinks, with client-rendered Mermaid that fails gracefully (#1335 umbrella: #1334/#1338/#1340/#1341; #1332 Markdown/editor UAT: Mermaid #1344/PR #1433, wikilink resolver #1345/PR #1432, image fixture #1347/PR #1430, task/code retest #1348). The shell is an adaptive single-shell workspace with one left context panel, a canonical Vault Browser, single-shell scroll ownership, and rail/folder-density compaction (#1395 corrective: #1397/#1398/#1399/#1400/#1401 plus hardening #1417/#1418/#1419/#1425/#1427). Body-edit is wired through `active_note_body_update` with writeguard and an unsaved-edit signal, behind a fixed-height edit composer (#1346/PR #1434, #1416/PR #1429). The governance endpoint stub was replaced with a real CanvasPanelPipeline; the Panel correction path and source-backed read-mode checkbox projection are implemented. Note-independent workspace orientation is now shipped through a contract, API, re-entry UI, leave-point cursor, and MemoryCandidate intent ADR/runtime seam (#1457/#1460/#1461/#1463/#1464/#1466). This remains dev/staging-shell and v6.1 orientation work; broader production Companion UI hardening and packaging remain issue-first.
Doc role: Core SoT
Authority: Current operational snapshot for the active baseline; subordinate to concept contracts for normative semantics, but authoritative for current runtime status and rollout posture.
Owner: Runtime / current-state SoT
Temporal class: operational
Review cadence: weekly
Source of truth: mixed
Last reviewed: 2026-07-30
Last verified against: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/DOCS_INDEX.md, docs/OPERATIONS.md, docs/HUMAN-FLOWS.md, docs/CONTEXTUAL_RELEVANCE_ENGINE/README.md, docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md, docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md, docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md, docs/CKM_COCKPIT_DIRECTION_B/README.md, docs/BUILDEROPS_CONTROL_PLANE/DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md, app/agent_memory/provisional_recall.py, app/agents/ask/graph.py, app/relevance/evaluator.py, app/relevance/materialization.py, app/relevance/attention_loop.py, app/relevance/now_surface.py, app/instance/filesystem_identity.py, app/instance/vault_registry.py, app/dispatcher/verification_api.py, app/dispatcher/verification_runtime.py, scripts/select_pr_tests.py, companion-ui/companion-app/companion_ui/workspace/now_surface.py, tests/agent_memory/test_provisional_memory_recall.py, tests/agent_memory/test_provisional_memory_call_sites.py, tests/relevance/test_vault_native_moments.py, tests/relevance/test_attention_loop_runtime.py, merged PRs #1948/#1977/#2092/#2097/#2098/#2115/#2119/#2127/#2128/#2129/#2131/#2133/#2135/#2137/#2140/#2142/#2636/#2642/#2643/#2645/#2656/#2678/#2686/#2689/#2692/#3730/#4224/#4244/#4420/#4424, issue #3720, PRs #3743/#4416, closed parent issue #4080, live issue #3603, and current repo state at `origin/main` `f0bafe6e79f3cc1a087b2c2fcbe40450c8302da2` on 2026-07-30

Status snapshot now includes SoT baseline + release-line fields and intent/event counters (`promote.intent.created`, `panel.intent.executed`, `watcher.run`, ingest runs by plane). Code still exposes `sot_forward_line_version` / `feature_line_version` as the v5.6 release-line marker, but GitHub issue truth treats v5.6 as delivered rather than active. `watcher_runs` now counts watcher audit events from the registry watcher as well as the legacy snapshot watcher, while runtime health still relies on heartbeat + tick logs.

Concept anchors: layering, portability, archive exposure, trust semantics, event compatibility, and config-as-product are now defined as concept contracts under `docs/CONCEPTS/` and are considered the canonical statements of intent. This status document describes operational snapshots and may lag those contracts.

Roadmap reset note: `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md` is the accepted strategic reset
input for sequencing, not a runtime-promotion document. This status file remains the current-state
owner doc. Capabilities should be read as shipped only when code plus tests or operator evidence are
present and any owner-doc promotion gate has been satisfied.

Target SBS status note: `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` is adopted as target-state architecture for long-horizon subsystem boundaries and change-impact reasoning. It is not fully implemented. Current implementation may contain transition debt tracked through `docs/architecture/SBS_TRANSITION_DEBT.md`; operationalization is tracked through `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`, `docs/ROADMAP.md`, tracking issue #2337, and delivery issue set #2355. Current shipped behavior remains owned by this file and `docs/ARCHITECTURE.md`.

Integrated Runtime v1 release line: #1874 closed as completed 2026-06-12 (all 7 children #1851/#1875-#1880 delivered via PRs #1882-#1888), integrating already-shipped capabilities through route parity, readiness matrix, Panel staging persistence, golden-path UAT, and negative-safety UAT gates.

Contextual Relevance Engine posture: CRE-01 and CRE-02 are delivered concept-contract slices;
CRE-03 is shipped as the vault-native pull runtime slice, and CRE-04 is shipped for governed
in-app proactive reach-out decisions. The shipped CRE surface computes vault-native moments from
local vault data, materializes them as non-authoritative moment artifacts with receipts, records a
reach-out or deliberate suppression receipt per candidate on the governed relevance tick, and exposes
Companion "now" / glance projections plus threshold-cleared in-app nudges. It does not read external
connectors or emit OS/system notifications; external source integration and OS-push delivery remain
deferred follow-ons.

Commitment surfacing posture: the commitment-surfacing validation line has delivered its durable
read-side vertical slice. Commitments can persist as vault-backed system artifacts, the Companion
workspace state exposes active commitments from that durable source as a read-only projection, and
the Companion UI renders next-action, waiting, and review-return commitments with provenance-aware
read-only treatment. This does not ship commitment mutation, reminders, automatic closure, or
CRE-driven commitment reach-out.

Security review note: the security architecture spine (`docs/SECURITY_ARCHITECTURE.md` plus its
trust-boundary, data-flow, API-matrix, and STRIDE-lite companions) is now the review-routing owner
for security framing. The recent security hardening PRs (#1581-#1586/#1591) add review inputs and
targeted path/error-detail fixes; they do not change the local-first runtime exposure model or
promote public internet readiness.

2026-06-28/29 delivery wave writeback:
- Companion UI NAV-2/NAV-3 shipped (#2636, #2642, #2643, #2645): direct bottom-bar launchers for History, Memory, and Search now participate in browser history, the System Map route stays in history sync, and overlays are deep-linkable via `?overlay=<id>`.
- Observability Stabilization epic #2597 delivered its 11 child slices on 2026-06-28 (cb239a3f): honest health signals, one real alert path, silent audit lie stopped, and running commit observable. AC1-AC4 and AC7 still await operator test-deploy ack, and #2597 remains open and not closed.
- Prod promotion model fix (#2656): AC1 and AC3 are done, while AC2 remains operator-gated pending operator receipt and sibling-doc reconciliation.
- Delivery wave follow-on receipts: GraphQL exhaustion fix #2686, watcher settings receipts #2678, nested-vault boundary enforcement #2689, and deployment environment-separation spec #2692 are merged and reflected in the current shipped baseline.

2026-08-02 fix writeback:
- `semanticmd` merge driver no longer routes repository documentation (#4505): `.gitattributes`
  narrows `merge=semanticmd` off `docs/**`, `/README.md`, `/AGENTS.md`, `/CLAUDE.md`,
  `/CONTRIBUTING.md`, `/THIRD_PARTY_NOTICES.md`, and `.codex/**` back to git's built-in text merge,
  and `app/agents/merge_resolver/agent.py::merge_note_from_blobs` now refuses `status=resolved`
  when neither side of a merge carries vault-note `uuid:` frontmatter identity and the bodies
  diverge, forcing a real conflict instead of silently discarding one side's committed content.
  Vault-note merging under `vault/**` is unchanged. See
  `docs/development/SEMANTIC_MARKDOWN_MERGE_DRIVER.md`.
- `semanticmd` merge driver now honours git's merge-driver file contract (#4496):
  `app/cli/merge_driver.py` writes the resolved merge result to git's `%A` path instead of only
  printing it to stdout (which git never reads), so a clean auto-merge no longer silently keeps
  OURS while reporting success. `MERGE_STATUS`/`MERGE_REASON` diagnostics moved to stderr and can no
  longer land inside merged markdown. Non-resolved outcomes (`conflict`/`prompted`) still leave `%A`
  untouched for git's normal conflict handling. See
  `docs/development/SEMANTIC_MARKDOWN_MERGE_DRIVER.md`.

## Health spine
- HealthContract + WriteGuard + incident logging now form the deterministic spine for startup readiness; this snapshot is the baseline for initial go-live visibility.
- `POST /ingest` now asserts `DEFAULT_WRITE_GUARD.assert_writes_allowed("ingest.object_create")` at the seam before any I/O, fail-closed like the other named WriteGuard seams (owner-decided epic #2778 F-D, `docs/architecture/formal-model.md :: 7. Divergences`); previously this seam was guardless.

## Runtime verification
- `/api/health` reports watcher and worker heartbeat freshness plus the runtime DB/LLM probes so operators see deterministic health signals.
- `scripts/start_full_system.sh` and `scripts/gap_test_alpha.sh` drive the registry watcher → DB outbox → worker → index → `/api/ask` chain, emit `watcher.run` audit rows plus `index.embedding.created` / `index.embedding.failed` (legacy alias: `index.object.embedded`), and log diagnostics when sources are missing.
- The worker heartbeat probe in `scripts/start_full_system.sh` reads the worker's heartbeat file through the container boundary (`docker compose exec`, `scripts/lib/worker_heartbeat_probe.sh`), matching the pre-existing watcher heartbeat probe. `/app/tmp` (and `/app/tmp-test`) is always the `runtime-tmp` Docker-managed named volume in every channel, never a host bind mount, so a host-path read could never observe a healthy worker's heartbeat — this previously failed `make prod-start-full` against a fully healthy pinned-image prod stack (#4361). The same startup path now never silently builds over an `APP_IMAGE_TAG` pin: pinned-image mode (`COMPOSE_FILE` without the `docker-compose.app-bind.yml` overlay) pulls the pin and fails loud on a pull miss unless `APP_BUILD_OVERRIDE=1` is explicitly set (`scripts/lib/pinned_image_guard.sh`), mirroring the existing `scripts/deploy_channel.sh` pull-only contract.
- `/api/orientation` now provides a minimal read-only orientation runtime seam that returns a situational frame without a query term; explanation remains bounded to `leave_point`, `open_items`, and `notable_change` derived from runtime signals.
- Leave-point cursor lookup now applies scope filtering at the DB boundary and uses a wider corrupt-row recovery candidate window; this is hardening of the existing read-only orientation seam, not a new mutation surface or semantic authority.
- Workspace orientation and Companion UI repair hardening keeps placeholder "no unresolved" text out of returned open loops, requires independent signal categories before emitting MemoryCandidate handoff intents, preserves non-UTC authored timestamp offsets in Vault Browser metadata, exposes previous-page cursor metadata for Vault Browser navigation, renders structured leave-point fields (`logical_ref`/`artifact_uuid`/`captured_at`), and keeps direct note-save paths and proxied runtime error details bounded to the active vault/runtime response.
- Heimdal entity-review application folds the append-only, human-authored decision history for each
  still-pending queue entry before mutating the register: a pre-application `undo` restores an
  undecided pending state, while an already-applied merge or reject remains an idempotent no-op for
  later undo. The bounded contract and authority details remain owned by
  `docs/MIMER_IPAD_THINKING_CANVAS/SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md`.
- Governed media ingress with durable receipts is shipped (CDLM-01, #4384):
  `POST /api/heimdal/capture/media` acknowledges a capture only after the original is durably in the
  encrypted raw store **and** the `heimdal.capture.media.admitted` outbox event is committed, so a
  2xx is a durable-acceptance receipt rather than transport success; a failed event commit returns
  `500 not_acknowledged` and writes no receipt. Admission is idempotent on
  `(capture_id, content_sha256)`, and `GET /api/heimdal/capture/receipts?capture_id=…` answers
  `admitted` or `unknown` so a client can distinguish a lost response from a capture that never
  arrived. Watched-folder admissions are receipted through the same seam (content-hash keyed) but
  gain no receipt-gated retention — that stays an outbox-lane property owned by CDLM-03. This slice
  ships no session/segment ledger, no ASR or derivation, no streaming/resumable upload, no auth
  keys, and no public ingress: both routes refuse peers outside loopback/LAN/tailnet. **Key
  provisioning is delivered (#4422):** the api process is a declared consumer of
  `heimdal.raw-store-key` (`heimdal-api-ingress` in `config/secrets/host_secret_contract.json`,
  dev/test/prod); the governed deploy wrapper bootstraps its secret layer for every `up` that
  includes the api service (degrade-visibly — a missing Keychain item or contract never fails the
  deploy; a Keychain item that resolves to a *malformed* value does fail it, since the bootstrap is
  fail-closed on validation, and #4489 extended that to the optional `github.token` declared for the
  same consumer — tracked as `KD-4489-malformed-declared-secret-aborts-channel-deploy` on #4172) and
  the `api` Compose service consumes it via its own env-file handle. **`heimdal-capture-watch`'s
  own provisioning is now channel-independent too (#4362):** the `HOST_SECRET_RUNTIME_ENV_FILE`
  env-file layer that delivers `HEIMDAL_RAW_STORE_KEY` to that service lives in the base Compose
  file (previously only the dev overlay carried it, so `test`/`prod` deploys never received the
  key through the generated runtime env at all), the deploy wrapper's bootstrap gate now fires
  for that service on every channel (previously dev-only), and `scripts/export_runtime_env.sh`
  forwards an operator-set `HEIMDAL_CAPTURE_WATCH_DIR`/`HEIMDAL_RAW_READ_ALLOWLIST` into the
  generated runtime env instead of requiring an ad-hoc shell export at compose time; the test
  channel gets a hardcoded test-scoped watch dir the same way the `WATCHER_STATE_DIR`-family
  paths already are. The supervised CLI entrypoint (no `--once`) also no longer exits on a
  startup config error — it retries in place so the container stays resident long enough for the
  independent Compose healthcheck to actually observe and report a config-missing failure as
  `unhealthy`, instead of racing a `restart: unless-stopped` crash-loop that hid behind a stale
  `healthy` status. An api startup preflight detects a missing
  `HEIMDAL_RAW_STORE_KEY` before first use, logs it loudly, and reports the media and screen
  ingress lanes `unavailable` on `/api/status` while every other API function keeps serving; the
  request-time named 500 `raw_store_key_unavailable` / `not_acknowledged` contract is unchanged.
  The one remaining operator step is placing the actual key material into the Keychain item for
  the `heimdal-api-ingress` consumer per channel (`{channel}:heimdal-api-ingress:heimdal.raw-store-key`
  under service `yggdrasil.host-secrets`). **The lane now admits under its own consent grant
  (#4492):** `device+adapter:v1-media-ingress` (`grant-media-capture-v1`, seeded by migration
  `a9f3c2d7b6e1`), whose descriptive `capture_profile.modalities` names all four admitted kinds —
  audio, image, video, document — per the owner ruling of 2026-07-30 on #4172, instead of borrowing
  the voice-memo lane's speech-only `self_record` grant. The two grants revoke independently and the
  watched-folder lane keeps admitting under the voice-memo grant; `capture_profile` stays
  descriptive (no modality enforcement). The same startup preflight also resolves this grant and
  reports `media_ingress` `unavailable` when it is absent, with detail `media_consent_grant_missing`
  when the ledger is readable but no active grant covers the scope (most often a database that has
  not yet run `a9f3c2d7b6e1` — the ledger table itself belongs to `c4f7a1b2d9e3`; also a revoked or
  expired grant), or `media_consent_ledger_unreadable:<ErrorClass>` when the ledger cannot be
  queried at all (table absent because `c4f7a1b2d9e3` never ran, or the database is unreachable).
  Operator note: on a deployment whose voice-memo grant was revoked (which used to stop media
  ingress too), applying the migration seeds an active media-capture grant and media ingress
  resumes; revoke `grant-media-capture-v1` as well to keep it stopped — programmatic today, since
  no CLI or route grants or revokes. Contract detail
  is owned by `docs/EVENTS.md :: Heimdal governed media ingress + durable receipts` and
  `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md`; the callable
  client contract is promoted in `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.4–§4.5.
- The meeting session/segment ledger is shipped (CDLM-02, #4385): `POST /api/heimdal/meeting/session`
  and `POST /api/heimdal/meeting/{session_id}/close` are idempotent by client-minted identity and
  never fork or re-open a session; every governed media admission carrying `(session_id, session_seq)`
  lands exactly one ledger row per pair referencing its CDLM-01 receipt, with a different content
  hash for an existing pair failing closed (original preserved, conflict recorded once per logical
  conflict, surfaced as needs-attention). `GET /api/heimdal/meeting/{session_id}/segments` names the
  received and missing sequence numbers before and after close, and `complete` flips only when the
  ledger covers the declared count. A late admission into a closed session updates the ledger and
  emits `heimdal.meeting.segment.late_admitted` (the CDLM-06/08 re-derive trigger) without
  re-opening. Ledger state is durable — migration `a7c2e9f4b1d3` for Postgres/PDM, a file-backed
  SQLite lane for dev/test — so a hub restart rebuilds nothing from memory. The
  `HEIMDAL_RAW_STORE_KEY` posture above (provisioning delivered, key material an operator Keychain
  step) bounds live use of the admission-fed segment path the same way it bounds CDLM-01. Contract detail is owned by `docs/EVENTS.md` and
  `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS.md`.
- Live meeting projections are shipped (CDLM-06, #4386): every admitted meeting segment derives ASR
  exactly once per content hash through the shared engine seam (`app.media.transcribe.run_asr`),
  durably, so replays and hub restarts re-derive nothing; a failed derivation is per-segment
  needs-attention state, isolated from other segments, retried on resend, and never an admission
  failure. `GET /api/heimdal/meeting/{session_id}/projection` returns the sequence-ordered transcript
  with explicit gap markers, plus the `generic-default@1` analysis (summary, themes, provisional
  decisions, open questions, action candidates) as `derived_projection` blocks carrying
  `{revision, derived_from, template_id, engine}` provenance — projections, never canonical truth,
  with no person attribution anywhere. Re-derivation over an identical admitted set is convergent
  and mints no new revision; a late admission derives the next revision. The template precedence
  seam (user selection > permitted metadata > default) ships with `generic-default@1` as the only
  template; the analysis engine is deterministic in this slice (no LLM). Projection state is durable
  and rebuildable (migration `b8d3f0a5c2e4`; SQLite dev/test lane).
- Meeting block ownership is enforced mechanically (CDLM-07, #4387): every meeting-page block
  carries `{block_id, owner, type, provenance, created_at, revised_at}` in a durable registry, and
  every block mutation — user edits, analysis revisions, reconciliation, template re-render,
  finalization — passes one shared fail-closed guard (`app/heimdal/meeting_blocks.py::apply_block_write`).
  `user_note` blocks are writable only by the user's editor identity through
  `POST /api/heimdal/meeting/{session_id}/user-note` (idempotent by `(note_block_id, revision)`,
  acknowledged only after durable write plus the committed `heimdal.meeting.user_note.written`
  event); derived writers are confined to blocks their own provenance minted, cannot move, merge,
  reorder, or renumber anything else, and a forged editor-identity string from a derived context
  cannot pass because the writer kind is structural. Unknown or conflicting ownership refuses the
  write, preserves content byte-for-byte, and records a surfaceable refusal (needs-attention on the
  projection read). The pg migration `c9e4a1b6d3f5` adds a DB-level trigger rejecting user_note
  content changes without user-editor provenance. Editor identity is structural, not cryptographic,
  until client-contract F2.
- Meeting finalization is shipped (CDLM-08, #4388): closing a session (and every post-close
  late-segment reconciliation) consolidates the projections into three create-once Sources-zone
  artifacts through the governed write seam — the ordered transcript with explicit gap markers, the
  final `generic-default@1` analysis at draft standing with full provenance frontmatter (promotion
  to canonical knowledge stays a human act via the trust path), and the user's notes verbatim as a
  distinct human-provenance artifact never merged into derived output. Finalization is idempotent
  per `(session_id, ledger completeness state)`; a gapped close is legible as `needs_attention`
  with exact missing sequences in the receipt, the projection read, and note frontmatter; a late
  admission re-finalizes with lineage to the superseded state while old artifacts remain untouched.
  The `heimdal.meeting.finalized` event commits before the durable receipt that is the finalized
  acknowledgement (migration `d0f5b2c7e4a6`). Finalization writes its own block through the CDLM-07
  guard as a derived writer and is structurally refused any user-note mutation. The vault root
  resolves from `HEIMDAL_MEETING_VAULT_ROOT`; unconfigured is a named, honest skip.
- The first Bifrost product vertical is delivered across the Hub and native client (CDLM-01–10;
  parent #4383): iPhone/iPad capture of audio, image, receipt/document, and bounded video enters a
  disk-backed outbox under one stable capture identity; Watch audio relays through the phone into
  the same custody path. Originals remain until the Hub's durable receipt is persisted locally;
  reconnect queries receipts before resending unknowns. The iPad queue renders `pending locally`,
  `transferring`, `backend durably received`, `processing`, and `complete` / `needs attention`
  only from durable evidence and rebuilds after relaunch. Its live-meeting surface keeps the user's
  editor-owned notes structurally separate from revisable AI transcript/analysis blocks, resends
  ledger-missing segments, and presents the three final artifacts separately. Bifrost issues
  #57–#60 and Hub issues #4384–#4389 are closed; composed test-channel run
  `cdlm10-868e042e59` proves restart, duplicate replay, reconnect, gap legibility, and byte-identical
  note survival. This is shipped/test-channel truth, not a prod activation claim. Bifrost PR #56
  delivered the simulator journeys; physical locked-screen/call/Watch-haptic evidence remains the
  named operator-only receipt on bifrost#21 (`agent:needs-human`). Hub alone executes and journals
  entity merges; the iPad remains projection/approval only.
- The System Entry Point capability (#1782) is delivered. All twelve implementation children shipped: server-declared entry state (#1783/PR #1800), latency-ladder re-entry treatments (#1784/PR #1801), unified topbar/overlay host (#1785/PR #1802), the ⌘K Panel command palette (#1786/PR #1817), the system map overlay (#1787/PR #1846), the opt-in guidance layer (#1788/PR #1847), the settings drawer (#1789/PR #1834), governed capture append plus the ⌘N capture modal (#1790/PR #1799, #1791/PR #1816), memory review-queue endpoints plus drawer (#1792/PR #1798, #1793/PR #1818), and the read-only receipts history modal (#1794/PR #1833). The fixture-driven state-gallery validation harness (#1795, SEP-11; `tests/companion_ui/test_entry_state_gallery.py`) proves the composition: declared transitions render and undeclared transitions are rejected, cold/first-contact/no-vault render no re-entry overlay, the governed-vs-body-edit receipt asymmetry holds, no UI-derived authority classification renders, the display budget stays at or below the server caps, reduced-motion end-states are fully visible, and narrow mode preserves every critical affordance. The source-peek popover presentation and posture emphasis switch remain truthfully unshipped (declared overlay ids that do not mount); the context lane / place band stay parked under the gated decision issue #1796. Epic #1782 closure is performed by the delivery coordinator on the #1795 validation receipt.
- `app/resurfacing/runtime.py` now provides a minimal non-mutating resurfacing evaluator seam that
  does not require a query, derives relevance-change candidates from runtime status signals, emits
  explicit "why now" explanations with signal provenance, and exposes operator-visible receipt/status
  summaries without automatic writes.
- The interim GUI and Status service consume these heartbeats/events so the dashboard shows ingest health, counts, and incidents in one place.
- The local `test` bootstrap path is now treated as a first-class verification concern: parts of the path work today, but the repo-supported clean-state path is not yet fully self-contained end to end.
- `python -m app.cli sync-latency-harness` now defaults to provider-free `PANEL_AGENT_DECIDER=rule` for deterministic operator validation, emits progress before long-running watcher work, and fails within a bounded timeout instead of hanging indefinitely when a live LLM provider is unavailable.
- **Sync-latency harness — partial acceptance (2026-04-12, updated 2026-04-23):** iCloud transport chain validated end-to-end (MacBook → Mac mini via CloudDocs); server-side watcher detection confirmed; clean numeric latency measurement not yet captured. The allowlist blocker is now resolved for harness/operator runs via measurement mode (`WATCHER_MEASUREMENT_MODE=1`), which temporarily admits `ingest.summary.create` while preserving the default production-safe allowlist posture. Remaining blocker: Mac mini headless infrastructure gaps (Screen Sharing, auto-login recovery) tracked in #432. Follow-up timing receipt tracked in #433. Root cause of iCloud upload-queue blockage (`.git` dir inside vault) fixed by `.git.nosync` + symlink (Issue #421 closed).

## CI & Test Markers
- CI legs assert `docs/ARCHITECTURE.md` contains fitness guard statements, confirm CLI health smoke commands pass, and verify the worker logs show `worker starting`.
- CI no longer treats absent model-provider credentials as a passing live-provider check: the optional
  Panel LLM E2E job and credential-gated Codex docs-guardian path are removed. Reintroducing either
  requires a separately declared credential backend and explicit cost/egress posture; deterministic
  smoke, ADR-index, and docs-guard paths remain.
- The runbook uses affected-subsystem PR tests plus curated fitness gates before merges; the leased full non-PG/alpha-excluded suite is reserved for an explicit contract or cross-system blast-radius escalation.
- PR-unit test selection maps Heimdal/Mimer implementation, contract-doc, and test paths to the scoped `tests/heimdal` and `tests/knowledge_acquisition` suites; an unmapped changed surface fails selection before pytest rather than producing a false-green run.
- The instance-local multi-vault registry core lives in `app/instance/vault_registry.py` and is
  covered by the `vault` PR-unit suite through explicit ownership of `app/instance/**` and
  `tests/instance/**`. The registry stays `authority: dormant` until a deployment-time MVR-01C
  authority cutover runs; until then the legacy scalar app-local setting remains runtime authority.
  The **default-selection slice has shipped** (MVR-02, #3856): `default_vault_binding_id` is a
  durable, validated registry field, and `app/instance/default_vault.py` is the one fail-closed
  resolver (`override > session > instance default > explicit legacy bootstrap > no-vault`) plus the
  one service behind the authenticated default-vault API route and the headless CLI.
  The **versioned selection seam has shipped** (MVR-03, #3857): `active_context_set.v1`, the
  TTL-bound selection store and resolver, per-binding GOV authorization, and the production
  create/replace/inspect/clear endpoints — with the deployment-wrapper activation of its principal
  cutover still open under #4524.
  **Non-authoritative dimension grouping has shipped** (MVR-04, #3858): durable ordered membership
  over registered bindings in `app/instance/vault_dimensions.py`, administered through the
  authenticated `/api/instance/dimensions` route and the headless `dimension-*` CLI, with
  all-or-nothing member resolution that authorizes every member independently. A dimension grants
  no authority; it is a grouping convenience over bindings the caller could already name.
  **Request-scoped resolution has still not shipped**: the `X-Active-Context-*` HTTP carriers and
  binding-keyed persistence remain MVR-05 work, so nothing in the ordinary request path consumes the
  resolver yet. Unmapped changed surfaces continue to fail closed.

Validation posture note:
- blocking smoke/release gates are anchored to the active baseline in this document
- broader human-need acceptance scenarios may exist in the repo as non-blocking system-level TDD derived from `docs/HUMAN-FLOWS.md`
- failures in those broader scenarios indicate target-state gaps unless and until this status document promotes the capability into the claimed baseline

## Version framing consistency note

| Version framing | Role | Authoritative doc |
| --- | --- | --- |
| v5.5 (SoT baseline locked) | Current operational runtime; no new feature scope | `docs/ARCHITECTURE.md`, `docs/STATUS.md` |
| v5.6 (delivered/closed) | Historical delivery line; read as shipped invariants | `docs/ROADMAP.md#closed-v56-delivery-line`, `docs/STATUS.md#v56-closure` |
| v6.0 seams (baseline shipped) | Capability-seam baseline on top of v5.5/v5.6: closed capability spec dirs plus minimal orientation/resurfacing/commitment-domain/context-dimensions runtimes and read-only Chat cognition scaffold. Safe for production. | `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, capability spec dirs under `docs/FINDING_AND_REORIENTING/`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/`, `docs/SEPARATING_PERSISTENCE_SURFACES/`, `docs/COMMITMENT_AS_FIRST_CLASS/`, `docs/SCOPE_SPHERE_SITUATED_IDENTITY/` |
| v6.1+ (planned, post-seams) | Broader target-state runtime work the seams enable; not yet baseline | `docs/plans/V60_ARCHITECTURE_TARGET.md`, `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`, `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` |

Use `docs/ARCHITECTURE.md` for current-state runtime questions. Use `docs/ROADMAP.md` and the v6 plans for target-state design direction questions. Do not read v5.5 as an active work queue; new implementation work is sliced against v6 target-state docs.

Interaction-surface status: Panel is the shipped command-oriented mutation surface. A read-only Chat
cognition scaffold exists for planning/decomposition through the shared `ReasoningFacade`; it does
not execute tools, write notes, emit outbox mutations, or emit promotion/action intents. In
addition, a flag-gated canvas session slice exists for direct in-place note-body editing plus
governance routing (`CANVAS_ENABLED=1`; CLI/API session flow; body-only edits, frontmatter and
cross-note mutations rejected or routed through governance). This canvas slice is not part of the
SoT v5.5 baseline/default runtime posture, and broader canvas-Chat co-editing plus hybrid
Panel/Chat integration remain v6/non-baseline surfaces. The interaction authority split is still
governed by
`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md`,
`docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md`, and
`docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`.

## Baseline Definition (SoT v5.5)
- Environment posture: `dev`, `test`, and `prod` are now the explicit minimal environment model in the SoT. The governing contract lives in `docs/ENVIRONMENTS.md`. `dev` and `prod` are runtime-selected environments today; `test` is the current workflow-driven bootstrap and verification environment.
- Runtime environment selection: explicit environment model for `dev` and `prod` is now canonical in the config layer (`app.config.environment`, Issue #263). The default environment is `prod` (production-safe). Operators can select `PKM_ENVIRONMENT=dev` for development/diagnostic mode, or it defaults from `PKM_SETTINGS_PROFILE`: `lab` → `dev`, `operator` → `prod`. Environment is resolved at startup and stored in `InstanceSettings.environment` within the `SettingsBundle`. This provides one documented control surface for environment-specific behavior across the runtime. See `docs/ENVIRONMENTS.md` for full specification.
- Runtime watcher: registry watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`) is the default; legacy snapshot watchers are dev-only and require `PKM_SETTINGS_PROFILE=lab`.
- Runtime default: `scripts/start_full_system.sh` and `config/runtime.defaults.env` set `WATCHER_AUTO_EXEC=1` unless the operator already set a value; set `WATCHER_AUTO_EXEC=0` to run watchers in emit-only mode. Default-on does not bypass rollout discipline: once armed, any note with an AI panel fence is only a candidate, actions are still filtered through the allowlisted `watcher_settings.allowed_actions`, the only per-note opt-out is `ai_panel_auto_run: never` (nested form accepted), and manual CLI panel runs remain available. This default-on posture is intended to support autonomous proposals and low-risk action surfacing, not to force human-in-the-loop review for every trivial operation.
- Settings tiering (watcher controls): runtime defaults to `PKM_SETTINGS_PROFILE=operator` (which maps to `prod` environment); dev/lab-only watcher tuning env vars are applied only when `PKM_SETTINGS_PROFILE=lab` (which maps to `dev` environment).
- Storage baseline: `store_objects` is the canonical object table with a single writer path through the canonical `app/stores` providers (KERNEL-03, #2765/PR #2832): the legacy `app/store/object_store.py` and `app/store/vector_store.py` writer modules are deleted (an architecture guard test keeps them deleted), the best-effort legacy-`objects` backfill INSERT is removed (it had no production caller), store backend resolution fails loud on unknown/absent configuration instead of silently routing to volatile memory, and `index rebuild` reads via `ObjectStore` rather than separate memory/DB query branches.
- ASK warm-load boundary: `/api/ask` hydrates HybridStore through the canonical store interface (`list_objects`) instead of backend-specific `_objects`/raw SQL introspection.
- Orientation posture: `/api/orientation` is additive to ASK and not a full cognitive rollout; it is a bounded read-only runtime surface with no mutation intents.
- Resurfacing posture: `app/resurfacing/runtime.py` is additive and read-only; resurfacing outputs are
  candidate summaries plus provenance-bearing explanations/receipts, not mutation intents or artifact
  writes.
- DB outbox is canonical in runtime; JSONL (`INDEX_OUTBOX_PATH`) is audit only and should not be used as the worker queue.
- Required contracts: event compatibility/outbox envelope (`docs/EVENTS.md`), trust semantics, config-as-product, and PanelAgent wiring (`docs/PANEL_AGENT.md` + `docs/settings/panel-actions.md`).
- State-axis normalization posture: `maturity` is the canonical standing sink, `review_state` is the canonical review/mutation posture field, and legacy values such as `evergreen`, `processed`, `promoted`, `inbox`, and `logged` are compatibility-only inputs rather than preferred runtime outputs.
- Context enablement posture: the relation store now supports optional `sphere_membership`
  memberships as broader belonging metadata. This seam is additive only; operational scope still
  governs conservative runtime behavior and retrieval is not relation-driven by default.
- Retrieval capability seam: salience/staleness signal payload exists as an optional diagnostics
  seam and is emitted only on explicit opt-in. Runtime does not source staleness from persisted
  state-axis labels in artifact payload (`review_state`, `maturity`).
<!-- commitment-runtime-baseline -->
- Commitment-runtime baseline: bounded `next`/`waiting` commitment query surfacing is present in
  the domain layer; commitment state values remain distinct from note state axes; commitment-state
  transitions carry receipt-linkage metadata and are gated through the receipt-governed APPLY path
  — state mutations not on the APPLY path are rejected (PR #703, issue #694); and the commitment
  query surface consumes optional salience/staleness signals for priority surfacing (PR #705,
  issue #695). Verification: `tests/commitments/test_commitment_receipt_gate.py`,
  `tests/commitments/test_commitment_salience_queries.py`.
- Minimal concurrency guarantees: DedupTaskQueue + event_id dedup guard watcher runs, optimistic writes protect note updates, and the promotion consumer uses an EventDedupStore to skip duplicate intents (`docs/CONCURRENCY.md`, `app/promotion/consumer.py`).
- Settings compiler scope: panel action catalog, watcher settings, and outbox paths now compile with provenance (path/mtime/sha) via `vault/@Settings/watchers.md`, `docs/settings/panel-actions.md`, `python -m app.cli settings-validate`, and `python -m app.cli settings-explain`.
- Runtime-gating settings deltas from `settings/local.md` now route through the governed seam and emit `SettingsWriteReceipt`s when watcher-detected file edits change `enableVaultWatcher` or `enableAutoIndexing` (#2512).
- Operator enablement signals: `python -m app.cli settings-explain` surfaces watcher auto-exec state, allowlist validity, provenance, and write-guard context; `python -m app.cli status` exposes the same gate, watcher automation counters, last tick skips, last-run skip reasons, and panel-action/compiler provenance (source paths, mtimes, combined digest). Treat `allowlist`, `dedup/skipped_*`, `panel_skipped_policy`, and `writes_allowed` as the safe-to-enable checklist, not just the raw `WATCHER_AUTO_EXEC` value.
- Required tests: `ruff check app tests`, `mypy app`, governing `Verify:` targets, and focused affected-subsystem tests; add `python -m app.cli settings-validate --json` when settings/runtime contracts change. The host-leased repo-wide non-PG suite is required only when the governing contract names it or cross-system blast radius cannot be covered by focused tests (see `docs/TESTING.md :: Required baseline checks`).
- CI gate workflows: `.github/workflows/ci-smoke.yaml` is the enforced PR/push gate — smoke plus fitness-report summary parsing (including `CI SUMMARY GATES ok=<bool>`, exiting non-zero when `GATES.ok != true`), the subsystem-scoped not-pg unit-test lane with the repo-wide mypy gate, and the contract-validation job (import-linter, OpenAPI validation, YAML/JSON lint) gated by path filters so docs-only PRs stay light. `.github/workflows/integration-nightly.yaml` owns the heavy nightly lanes (full suite, PG contracts, k6 search load). The dispatch-only `ci.yml` and `ci-lite.yml` workflows were retired in #3892 after their live gates moved to those paths.

## v5.6 Closure and Post-v5.6 Follow-ups

GitHub issue/PR truth treats the v5.6 delivery line as closed, not as the active work queue. Direct v5.6 issues found in the current audit are closed, including PanelAgent/ReasoningFacade/runtime surface sync, Orchestrator V2 pilot slices, runbook alignment, Quality Wave / bounded PG verification, PanelAgent 2.0 Alpha acceptance, and low-risk sync validation parent #355.

Delivered v5.6 receipts include:
- PanelAgent decider hardening through the shared `ReasoningFacade` seam: Issue #230 / PR #236.
- ReasoningFacade + LangGraph rollout for the PanelAgent pilot agent pool: Issue #231 closed COMPLETED.
- Companion note + Note Context doc-sync correction: Issue #229 / PR #237.
- Vault-as-GUI settings provenance: Issue #238 / PR #254.
- CLI/docs runbook alignment: Issue #232 closed COMPLETED.
- Nightly deterministic Quality Wave acceptance harness and first bounded PG contracts lane: Issue #274 and Issue #285 closed.
- PanelAgent 2.0 Alpha real-vault acceptance: Issue #240 / PR #381.
- Low-risk autonomy + automated sync validation: parent Issue #355 closed COMPLETED with a final acceptance receipt on 2026-04-13; #432 and #433 remain follow-up/infra/statistical timing work, not blockers for #355 closure.

Post-v5.6 follow-up truth:
- This PR adds two target-state contract docs: `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` and `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`. It does not change runtime behavior.
- Orchestrator V2 remains flagged; checkpoint/resume has been hardened (Issue #444): `_save_checkpoint()` is now called at the configured interval (default every 3 steps), checkpoints are persisted in CheckpointStore, and resume-on-load is implemented to skip already-completed steps and restore execution state.
- Retry/backoff observability has shipped for the flagged V2 path (Issue #445 / PR #452), including retry events, backoff diagnostics, and terminal retry-exhausted tracking. The follow-up timeout discriminator mismatch where documented executor `tool_timeout` errors could retry in V2 was fixed by Issue #456 / PR #458.
- A2A in-process handler routing exists, the current traceability test passes, and parent lifecycle issue #359 is now closed.
- Local runtime health verification shipped via #334/#365; repo contract drift in `tests/ops/test_runtime_verify_contract.py` and docs-index validation drift were fixed by #441 / PR #439 as local verification hardening, not as active v5.6 feature work.
- v6 target-state audits opened current-state bugs for domain/zone handling (#435, #436, #437). The retrieval domain fallback fix shipped via #435 / PR #453, the ASK zone computation fix shipped via #436 / PR #454, domain validation and recording shipped via #437 / PR #460, and whitespace-only domain normalization shipped via PR #470.

## Agent Evolution Track

- ASK -> deprecated as the architectural center for the v6 direction; current v5.x runtime/API compatibility remains in place.
- Retrieval -> being refactored into a reusable capability layer rather than retained as a dedicated agent.
- PanelAgent -> primary interaction surface for mutation-capable flows.
- Chat -> canvas-shaped interaction now has a materially shipped bounded co-authoring surface behind `CANVAS_ENABLED` (session logs, body-scoped editing, governance routing), while the broader cognition path remains read-only and hybrid Panel/Chat mutation remains follow-up work under governed execution.
- Deep Agents -> planned only after v6.0 structural separation; not active in production mutation flows.
- Execution layer expansion -> research only.
- Governance -> active concern across policy, provenance, admissibility, approval, and auditability.

The system is not yet an autonomous agent system. All execution remains controlled and mediated.
High-level design rules for this direction now live in `docs/DESIGN_PRINCIPLES.md`; roadmap and architecture should stay aligned to that split.

## Status fields (baseline vs release line)
- `sot_baseline_version`: locked SoT v5.5 Reality-MVP baseline.
- `sot_forward_line_version` / `feature_line_version`: code-level release-line marker that still reports v5.6 on top of the v5.5 baseline; this is not proof that v5.6 remains the active issue queue.
- `active_features`: human-readable list of forward-line capabilities (PanelAgent runtime, watcher track, config-driven wiring).
- Counters (totals + 24h window): `panel_runs` (`panel.intent.executed`), `promote.intent.created`, `promotion_executed` (`promote.done`), `watcher_runs` (`watcher.run` from registry and legacy watcher ticks), and ingest run counts per plane. Registry watcher health is also tracked via heartbeat + tick logs.
- `integrated_runtime_v1`: informational release-readiness matrix for the Integrated Runtime v1 operator view. It names the v1 capabilities, tier, state, and reasons from existing probes/flags only; it does not affect health/readiness pass-fail, grant authority, emit events, or perform writes.

## Concurrency & Safety (v5.5 gate)
- DedupTaskQueue now guards watcher auto-runs and powers the `skipped_dedup` signal before releasing keys.
- Optimistic locking keeps note writes safe; stale writes surface recoverable warnings instead of corrupting vault files.
- Event idempotency (watcher events + promotion intents) leverages deterministic `event_id`s and an EventDedupStore so repeated `promote.intent.created` lines are no-ops (`docs/EVENTS.md`, `docs/CONCURRENCY.md`, `app/promotion/consumer.py`).

## Current Snapshot

- Runtime uses the registry watcher, DB outbox, worker, ASK API, and status/health surfaces as the canonical operational path.
- Context Bundles production runtime integration is shipped and closed: parent #1559 closed
  2026-06-04 after the read-only construction route (#1560), real retrieval emission (#1562),
  orientation/resurfacing consumption (#1563), governed write-proposal linkage (#1564), and the
  read-only receipt projection (#1565) merged, with owner docs promoted in #1566. The stable
  bundle addressing follow-up on the retrieval-backed route (#1576) closed 2026-06-05; no bounded
  Context Bundles items remain.
- The emitted ContextBundle consumption repair is shipped: retrieval-backed bundle queries record
  emitted bundles in a bounded process-local addressability registry, and the production
  orientation/resurfacing bundle routes resolve through that registry instead of reconstructing the
  synthetic construction envelope. This remains read-only, non-durable, and non-authoritative:
  `may_write` stays false and missing or evicted bundle ids fail honestly.
- Direct runtime repairs from PR #1573 keep retrieval-backed ContextBundle routes stable by
  preserving the requested bundle id in emitted bundles/receipts, and keep knowledge-compilation
  proposal builders aligned with canonical review posture by accepting `review_state: protected`
  sources alongside `reviewed` and `accepted` while still rejecting non-approved states.
<!-- memory-context-admissibility-default -->
- Memory/context admissibility default documented (#1598): the conservative admissibility posture
  is now recorded in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` and
  `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`. The shipped bounded seams (Agent Memory runtime
  slices #1079–#1085; Context Bundles production integration #1559) remain in place; this note
  distinguishes their bounded read-side/proposal posture from a broader memory/context influence
  policy that has not shipped. Memory/context may support read-side awareness, orientation, and
  resurfacing when provenance is visible. It may influence proposals only as cited support with
  review/provenance posture surfaced. It must not authorize mutation or override human-authored
  truth. Context Bundles keep `may_write=false` unless a later governed contract explicitly
  changes that posture. No new runtime enforcement was added by #1598; the constraint is normative
  and drives future follow-up implementation issues if concrete enforcement gaps are identified.
- Inbound context/memory admissibility contract authored (#2023, parent #2022): the **admit-by
  predicate** — what context/memory is eligible to *enter* a proposal, answer, or action — is now
  owned by `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`, the input-side analogue of the
  outbound `AuthorityFlags`. It defines four admission axes (sphere/scope, memory class,
  provenance/trust + review state, consuming authority) plus an inspectable
  admit/exclude-with-reason decision object, and **supersedes the documented-only #1598 default**
  for admit-by (the #1598 sections remain valid as the influence posture for already-admitted
  material). Reset Wave-5 deliverable; docs-only — runtime enforcement is Slice #2025 and no flag
  is flipped here.
- Expansion Activation Gate contract authored (#2024, parent #2022): the deterministic dormant→active
  flip rule is now owned as a section in `docs/EMERGENT_FEATURES_MODEL.md` ("Expansion Activation
  Gate"). It defines the gate inputs (admissibility compliance via #2023, authority class + #1881
  governance tier, loop precondition, reversibility & receipt, observability), the deterministic
  outcome (activatable / blocked-with-reason), and the principle that the gate stays deterministic
  even where the gated cognition is adaptive. It replaces the ad-hoc per-capability flags
  (`REASONING_ENABLE`, `CANVAS_ENABLED`) with one named contract that the #1956 activation waves cite.
  Docs-only — the gate function is Slice #2025. The first activation through that gate (ASK answer
  synthesis, Slice #2026) is now wired: `app/agents/ask/graph.py` admits the retrieved context through
  `app/activation/gate.py` at read-only authority and runs `run_reasoning(ASK_ANSWER)` on admit (see
  the Cognitive Expansion table below). Real synthesis on a given channel still depends on that
  channel's live (Ollama) provider; test-channel UAT gates prod promotion.
- Durable Memory and Recall is shipped through #1904-#1908, with the live review-accept wiring and
  audit residuals closed by #2014. Pending review candidates remain runtime-only; explicit review
  decisions persist as vault-scoped receipts/traces and reconcile the in-memory queue on
  intake/startup (re-intake of an already-decided candidate replaces any stale pending entry with the
  terminal decision). The companion review-accept endpoint now drives the governed materialization
  path directly: accepting a semantic candidate writes an agent-promoted vault artifact through
  WriteGuard, records the promotion receipt, and marks the stored decision terminal — promote-to-
  semantic decisions become terminal only after that durable write succeeds. Blocked materialization
  records a failed-attempt receipt and keeps the promotion actionable (the accept response reports the
  candidate as still pending materialization). Guarded recall now runs the authority guard and writes
  recall receipts, including the valid action-authorizing path which carries its recall receipt
  reference; activation state is not persisted as artifact authority. Guarded recall is invoked
  read-only in the ASK graph (#1970/#1971), and when it fires the ASK answer attributes the recalled
  memory with a "Recalled from: … · receipt &lt;id&gt;" footer keyed to the recall receipt (treatment A,
  #1972) plus a structured `recalled` provenance field on the response; no attribution is shown when
  recall did not fire.
- Provisional-memory recall now has a bounded production ASK seam (#3720): complete same-scope
  provisional Vault records may enter a read-only answer only after both inbound admissibility and
  outbound authority checks pass. The resulting context remains visibly provisional, low-trust,
  non-canonical, provenance-bearing, and usable only as read support or explicitly cited proposal
  support. It cannot become action-authorizing, set `may_write`, trigger APPLY, or mutate canonical
  Vault Markdown; malformed artifact identities and governed-execution attempts fail closed with
  content-free exclusion/recall receipts.
- The provisional-memory authority boundary is covered by a deterministic 16-case Swedish/English
  hard gate in the default eval scorecard (#3721). Its frozen-baseline compare path validates the
  complete canonical case proof (identity, enums, bilingual family coverage, authority semantics,
  categorical failures, and gate consistency) and fails closed on truncated or contradictory
  scorecards; the proof remains derived evidence and carries no memory authority.
- Runtime AgentState contract unification is shipped for the current ASK, generic graph, reasoning
  graph-builder, and PanelAgent state surfaces: `app/agents/runtime_state.py` defines the shared
  trace/authority/proposal/receipt linkage fields and the existing state classes now expose or adapt
  to that contract. This is runtime linkage only; it does not grant durable memory semantics or
  bypass WriteGuard/governance authority.
- BuilderOps Vault is shipped as a build-plane runtime: `app/builderops/` provides the store,
  schema, projections, promotion gateway, and boundary layer with CLI and API surfaces, covered by
  `tests/builderops/`, `tests/cli/test_builderops_cli.py`, and `tests/api/test_builderops_api.py`.
  BuilderOps also includes local dry-run epic coordination helpers for `deliver-issue-set`, including
  runtime-neutral Codex/Claude dispatch context packs, TCD launch-decision summaries, and
  claim/review/done lifecycle transition plans plus an explicit child-issue ready-repair batch
  planner, PR CI-monitor handoff records for locally validated PRs waiting on GitHub Actions, a
  read-only CI stall classifier for REST check-run payloads, a PR-body generator for local lane
  contract preflight before PR creation, a review-before-CI gate planner for docs/governance PR
  preparation, a parent epic delivery ledger renderer, and a lintable epic PR batching policy helper;
  these helpers emit local JSON/run-state coordination evidence or editable local text only and do
  not mutate GitHub, Projects, dispatcher leases, branches, worktrees, product/runtime behavior, or
  agent spawns unless a caller explicitly invokes the validator-gated ready-repair apply mode.
  Per `docs/adr/ADR-0010-builderops-vault-authority-boundary.md` it governs builder-operations
  material only; its records and generated projections are explicitly non-authoritative for
  product/runtime truth and never bypass repo authority gates. (ADR-0010's "not implemented" header
  predates this store/CLI/API delivery under the #1500-series follow-ups and is the stale surface to
  reconcile next.)
- The BCP-05 verification lane now has a repo-side BuilderOps API/PostgreSQL/outbox implementation
  under PR #4416. That code presence is not a delivery claim: issue #3603 and its installed-main
  Demerzel pilot receipt remain the authority for whether BCP-05 acceptance is complete. The
  review-only Codex child has no ambient GitHub mutation authority; scoped GitHub effects remain
  fenced to the host executor, with durable task/attempt/outbox/recovery state in the BuilderOps
  control plane rather than dispatcher SQLite.
- CKM Cockpit Direction B is an accepted BuilderOps presentation capability. Children #4081–#4086
  and completion #4222 are closed; PR #4224 supplied the terminal production-CLI proof, and parent
  #4080 independently accepted and closed the capability on 2026-07-28. Direction A remains the
  script-free default. The opt-in `ckm overview --cockpit` surface is supported and remains local,
  generated, deterministic, non-authoritative, network-free, and non-mutating.
- The visual Signboard at `/signboard` is served from the dispatcher store. `/api/signboard/board`
  builds every card from `store.list_tasks()` per request, derives its columns from
  `STATUS_COLUMNS`, and reads no files; a card move is a dispatcher write and nothing is exported
  afterwards. The response carries no filesystem `root`, `SIGNBOARD_ROOT` has no effect on it, and a
  missing or unreadable store returns HTTP 503 rather than an empty healthy board — the invariant
  that "no work" and "misconfigured" must not look alike now keys on the store, not on a resolved
  root (#4401). That retires the projection as a live read path and, with it, the root-resolution and
  drift defects filed as #4279, #4293, and #4370.
- The dispatcher's Signboard Markdown export (`app/dispatcher/signboard.py`,
  `python -m app.dispatcher export-signboard`) is now **legacy**: both it and `signboard-validate`
  announce themselves as `[LEGACY]` in `--help` and are kept working only for the builder hosts that
  still hold a board directory. Physically removing the exporter, prune, and lint is a separate
  follow-up. It preserves any human-authored `## Notes` content
  across re-export instead of overwriting it, and its export path defaults to
  `BuilderOpsVault/agent-delivery` under the currently active vault (resolved through the shipped
  `VaultManager` active-vault-selection mechanism) so no CLI/automation caller has to type a manual
  path (#3312). That default remains the single source for the export root, now consumed by the
  full-stack launcher bootstrap alone. `export-signboard --prune-absent` removes generated cards
  whose task id has left the dispatcher store, retaining any card that carries human-authored
  `## Notes` or `## Receipts` text (#4198). A board now also records which dispatcher store owns it:
  every export writes a `.signboard-store.json` stamp carrying that store's durable identity (minted
  into the store's own metadata, not derived from its path), and `--prune-absent` refuses non-zero,
  before writing or unlinking anything, unless the stamp matches the store the process resolved —
  the store resolves from the current working directory, so two checkouts on one host reached
  opposite verdicts about the same board and one of them deleted 404 live cards on 2026-07-29
  (#4370). `signboard-validate` reports a mismatch read-only as a `store_stamp_mismatch` finding.
  The projection remains read-only for coordination fields
  and has no write path for claim, lease, or lock state; dispatcher SQLite remains the authority for
  the legacy dispatcher/signboard claim lane per ADR-0010, while BCP-05 verification coordination
  is the separately bounded BuilderOps API/PostgreSQL lane described above. `default_signboard_root()`
  now distinguishes a dangling `lastActiveVaultRef` (`VaultContext.status == "missing"`, a
  previously-selected vault whose path no longer exists on disk) from a genuinely never-selected
  vault (`status == "none"`): the dangling case raises `DanglingActiveVaultReferenceError`, names the
  missing path, and no longer claims "no active vault is selected" — matching the same status split
  already established for `app/api/routes/companion.py`'s vault-selection-required responses (#4223).
- Canvas co-authoring is materially implemented behind `CANVAS_ENABLED`: `canvas open` / `edit` /
  `close`, `/api/canvas/sessions*`, session-log persistence, and governance-bearing mutation routing
  are shipped; broader Chat cognition and hybrid Panel/Chat mutation remain separate follow-up work.
- Agentic Canvas Co-Authoring (Phase 2, dev/staging, `CANVAS_ENABLED`) is now shipped: the canvas
  surface is no longer a write-pipe without an author. A write-capable co-authoring cognition
  (`app/chat/coauthoring_cognition.py`) turns a user intent plus the current note body into a
  generated body edit applied through the existing `CanvasWriter` via `POST /api/canvas/sessions/{id}/coauthor`;
  mock/degraded LLM responses are rejected (503) rather than written, and frontmatter/cross-note
  generations route through `GovernanceRouter` (409). The Companion UI shell exposes a server-gated
  co-authoring region (intent input, applied-edit render, undo) wired to `/coauthor` and
  `/edits/last`, reachable only when the runtime declares `guards.canvas_enabled`. Delivery:
  capability spec `docs/CANVAS_CHAT_SURFACE/` Phase 2; parent #1715, tasks #1716 (PR #1720) and
  #1717 (PR #1723), spec docs PR #1719. Core Runtime defaults and the read-only Chat scaffold are
  unchanged. A live operator browser demo of the open→intent→applied-edit→undo loop remains the
  optional end-to-end confirmation; in-process and CI (`companion-ui-browser-runtime`) validation passed.
- Chat→Panel Governance Handoff (Phase 3, dev/staging, `CANVAS_ENABLED`) is now shipped: a
  governance-bearing co-authoring intent is navigable end to end instead of dead-ending in the UI.
  The `/coauthor` governance-bearing path returns a structured `GovernanceHandoffRef` (HTTP 409 body:
  `status=routed_to_panel`, `intent_id`, `action_type`) and stages the Panel proposal with a
  proposal-scoped `StagedProposal.proposal_origin="canvas_coauthoring"` (distinct from vault-note
  `NoteRef.origin`). The Companion UI canvas region captures the handoff reference and exposes a
  read-only "view in Panel" affordance keyed to `intent_id`; the Panel rail (model + served HTML)
  surfaces the server-declared canvas-origin attribution; confirmation routes through the existing
  `POST /api/panel/confirm`; and the executed receipt is reflected back into the originating context
  (read-only, server-declared, correlated strictly by `intent_id`, never invented). Delivery:
  capability spec `docs/CANVAS_CHAT_SURFACE/` Phase 3; parent #1725, tasks #1726 (PR #1731), #1727
  (PR #1732), #1728 (PR #1734), spec docs PR #1729, and live `serve_dev_page` wiring through
  #1733 / PR #1736. Panel remains the primary command surface; receipts stay server-owned; Core
  Runtime defaults unchanged.
- Panel confirmation is now a bounded shipped runtime path: `POST /api/panel/confirm` confirms
  explicit panel actions through the governed confirmation path, preserves blocked/rejected receipts,
  and the runtime/client surface now includes `GET /api/artifacts/note` plus the companion-app
  real-note workspace shell and confirm-refresh flow for read-only artifact hydration after
  confirmation.
- Vault Browser `queue_review` now stages a pending Panel governance proposal through
  `POST /api/companion/vault-browser/actions/queue-review` when server-resolved artifact scope is
  available. This is only queue staging: durable execution and receipt-supporting records remain
  behind `POST /api/panel/confirm`.
- Pending Panel proposals and `POST /api/panel/confirm` idempotency keys now survive API restart via
  additive SQLite runtime state. Recovery is pending-only and executes nothing; if that backing is
  unavailable, the runtime falls back to memory-only staging and reports degraded Panel staging
  posture through `/api/status`.
- Companion UI operational loop (inspect → queue → confirm → receipt) is now a coherent, inspectable
  control surface over the existing shipped surfaces (#1603). The queue-review response names its
  loop position (`loop_stage: "queued_pending_confirmation"`), the Panel confirmation response exposes
  an explicit receipt-visibility posture (`receipt_visibility`: `durable_vault_visible` /
  `blocked_no_durable_receipt` / `none_rejected`), and the companion-app dev shell renders a
  derived, read-only operational-loop region showing receipt posture. This wires the existing surfaces
  into one loop; it does not bypass Panel confirmation, WriteGuard, or trust semantics, does not make
  the UI durable authority, and is bounded to the proven loop — broader Companion UI production
  packaging and full Chat mutation remain separate target-state work. The loop was verified on the
  live Niflheim dev runtime by a real-note UAT (#1604, 2026-06-06): the governed `queue_review`
  confirm/reject path executed end-to-end with durable receipts visible in the governance/receipt
  layer (orientation governance summary, `panel.receipts`). The UAT is bounded to that
  governance-handoff path; the in-note checkbox-projection path is separately verified for durable
  source-backed `- [x]` projection (#1621, 2026-06-06): see `docs/PANEL_AGENT.md` (In-note
  checkbox-projection receipt loop — #1621) for the narrowed fixture evidence. AI-status callout
  receipt visibility on that path is runtime-result specific, not a universal claim for every
  mapped/logged action. The two receipt paths are distinct: the `queue_review` +
  `POST /api/panel/confirm` path writes a durable receipt into the governance/receipt layer
  (`panel.receipts`, `receipt_visibility`); the `POST /api/panel/checkbox-projection` path writes a
  durable checked checkbox directly into the vault note Markdown and may also surface an AI-status
  callout when the invoked Panel runtime path emits one.
- Cognitive-load Phase 0 verification snapshot (#1638/#1657, 2026-06-07; fixed by #1698,
  2026-06-08): code inspection of
  `app/panel/checkbox_projection.py` confirms the source-backed checkbox-projection path validates
  `expected_content_hash`, resolves artifact identity, validates `expected_source_hash`, verifies
  option selectability, and calls `WriteGuard.assert_writes_allowed("panel.checkbox_projection")`
  before `write_note_from_absolute(...)`. The endpoint now narrows its response contract: a
  successful source-backed checkbox projection plus runtime invocation returns `status="projected"`
  when no response-level receipt/callout evidence is present, with `receipt=None`. It must not
  report `status="executed"` merely because the invoked runtime returned internal results; any future
  `executed` response must carry response-level receipt/callout evidence.
  Display/listening preference verification found no implemented preference write path; current TTS
  endpoints (`POST /api/companion/tts/plan`, `POST /api/companion/tts/synthesize`) are local-first
  speech planning/synthesis and not preference persistence. `WORKSPACE_STATE_CONTRACT.md` remains
  the storage-home owner for future local UI preference state. Orientation and resurfacing read
  paths remain read-side projections; context-bundle consumption explicitly keeps `may_write=false`.
  Runtime/UI fixing for #1690 remains gated by the issue pickup rule because the issue is labelled
  `agent:ready` but Project status is currently `Backlog`, not `Ready`.
<!-- authority-spine-diagnostic -->
- Authority spine diagnostic surfaced in health API (#1601): `/api/health` now includes an
  `authority_spine` key with bounded operator-visible posture strings (`write_guard`,
  `authority_non_upgrade`, `provenance_required_for_mutations`, `read_projection_isolation`).
  This is a diagnostic surface only — it does not grant or deny authority and must not be
  treated as a semantic authority source. See `docs/HEALTH.md#authority-spine-diagnostic`.
<!-- receipt-event-boundary -->
- Receipt/event boundary documented (#1600): `OutboxEvent` (operational trace) and `Receipt`
  (accountability record) are structurally distinct. For governed mutation paths (`POST
  /api/panel/confirm`), `ConfirmResponse` carries both a `Receipt` (with `action_taken`,
  `inverse_action`) and `events_emitted` (list of trace names); these surfaces must not be
  conflated. For read-only projection paths (orientation, resurfacing, vault browser reads),
  only operational traces are emitted and no receipt is returned. The boundary is asserted by
  `tests/runtime/test_receipt_event_boundary.py` and documented in `docs/EVENTS.md` and
  `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
- Runtime event envelopes emitted through the shared outbox helper now include `meta.instance_provenance` (`instance_id`, `instance_role`, `environment`) as backward-compatible operational metadata.
<!-- agent-state-spine-contract -->
- Agent-state spine contract verified (#1625): the shared runtime-state linkage spine (`trace_id`,
  `authority`, `authority_basis`, `proposal_id`, `receipt_event_id`) defined in
  `app/agents/runtime_state.py` is now formally documented and compliance-tested. All five active
  agent state surfaces (`AskAgentState`, `GraphAgentState`, `AgentStateBase`, `PanelAgentState`, `PilotAgentState`)
  satisfy the contract. A lightweight architecture compliance gate
  (`tests/architecture/test_agent_state_spine.py`) ensures future state classes surface any spine
  gap before reaching production. The spine is intentionally narrow: it standardises trace
  identity, authority posture, proposal linkage, and receipt linkage without granting durable
  memory or bypassing WriteGuard. See `docs/ARCHITECTURE.md#agent-state-spine-contract`.
- Panel mutation gating now enforces explicit trust-verb classification on mutation-capable panel actions: only admitted `APPLY` actions can emit promotion mutation intents; `SUGGEST` remains non-mutating unless promoted through the governed execution path.
- APPLY transition receipts (`promotion.transition.applied`) now include accountability fields (`verb`, `authority`, `basis`, `outcome`, `artifact_linkage`, `instance_provenance`) as backward-compatible payload extensions.
- Status summaries now expose instance provenance (`instance_id`, `instance_role`, `environment`) for runtime attribution; this does not change artifact identity or companion note identity semantics.
- Production-facing path is the active current-state default; lab/dev-only flows remain explicitly non-production.
- The local test stack can be started successfully against a separate test vault, and `uat-seed-vault-test` works.
- The repo-supported local bootstrap/UAT path is delivered end to end: tasks #331-#336 are closed and `make test-bootstrap` runs the resettable, reproducible, verified local test-vault flow (reset → init vault → start stack → verify → UAT assert) described in `docs/LOCAL_TEST_BOOTSTRAP/README.md`.
- Issue #240 has a real-vault Alpha acceptance receipt recorded in `docs/PANEL_AGENT.md` after the 2026-04-08 server-side soak; that specific PanelAgent 2.0 acceptance gate is no longer pending.
- iCloud sync transport chain is validated end-to-end (MacBook → Mac mini via CloudDocs); the `.git.nosync` + symlink fix (Issue #421) removed the root-cause CloudDocs upload-queue blocker. Parent feature #355 is closed COMPLETED with its final acceptance receipt posted on 2026-04-13; clean statistical timing measurement and Mac mini headless infrastructure hardening remain follow-up work in #432 and #433, not blockers for #355 closure.
- The current docs-first stabilization wave is making the intended supported path explicit before further implementation continues.
- Objective: a clean-state, repo-supported local test bootstrap path that is resettable, reproducible, verified, and acceptable as the canonical local verification flow.
- PanelAgent runtime V1 is part of the active baseline; planner pipeline and LangGraph expansion remain opt-in.
- Canvas co-authoring exists in the repo behind `CANVAS_ENABLED` with session logs, body-scoped co-authoring, and governance-intent routing. It is materially supported as a bounded human-facing surface, but it is still gated and is not part of the default production operator surface.
- Legacy snapshot watchers remain available only for lab/dev workflows and are not part of the runtime default.
- Eval suites remain opt-in diagnostics; they do not define baseline health by themselves.
- Full replica-aware behavior (conflict handling, distributed authority, sync transport semantics) remains post-baseline work.

## Forward-Line Tracking

| Area | Current baseline posture | Follow-up direction |
| --- | --- | --- |
| Watcher auto-exec | Guarded by dedup + optimistic writes + idempotency | Safe enablement only after gates and receipts prove stable behavior |
| LangGraph rollout | Active for ASK and PanelAgent-related flows; the shared `ReasoningFacade` seam is adopted for the PanelAgent pilot (Issue #231 delivered) | Expand in phases as additional agent pools (Promotion/Reviewer/Hygiene) migrate onto the shared `ReasoningFacade`; treat this as post-v5.6 adoption work rather than an open v5.6 blocker. |
| Orchestrator V2 pilot | Shipped/flagged: parallel execution + dependency-aware scheduling with `ORCHESTRATOR_VERSION=v2`; V1 is default. Coverage: flag contract, plan-graph scheduling, event/trace compat, compensation/rollback, retry metadata handling with structured observability (retry events, backoff diagnostics, terminal failure tracking), checkpoint/resume with configurable interval persistence (Issue #444), bounded per-tool timeout/SLA contract coverage from Issue #446 / PR #448, and optional plan-level timeout budgets via `plan_timeout_seconds` from Issue #540 / PR #555. Per-tool timeout via `tool_timeout_seconds` and optional plan-level timeout via `plan_timeout_seconds` are supported on both V1 and V2 (see `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md` for the complete contract). Delivery receipts include Issue #250 (pilot), Issue #251 (compensation), Issue #252 (checkpoint/retry handling), Issue #444 (checkpoint/resume hardening), Issue #445 (retry/backoff observability), Issue #446 (timeout/SLA contract), and Issue #540 (plan timeout budget). | Future slices: repo-wide A2A/runtime delivery SLA, and V2 adoption after stability signals. |

For detailed sequencing, version history, and roadmap ladder, use:
- `docs/ROADMAP.md`
- `docs/plans/V56_FORWARD_LINE.md`
- removed historical snapshots in git history

## GitHub delivery governance snapshot

Repo-side governance added:
- task Issue form
- blank Issue disablement
- PR template requiring Issue linkage
- governance workflow checking Issue shape and PR Issue linkage
- machine-readable GitHub governance contract in `.github/github-governance.yml`
- delivery feedback loop governance for learning capture, retrospective review, and post-merge owner-doc receipt enforcement

Platform-side governance applied:
- the exact delivery-control-plane labels now exist in the repository
- GitHub Project v2 `Agent Delivery Control Plane` now exists and is linked to `RasmusTho/agentic-pkm-mvp`
- Project field `Status` now uses `Backlog`, `Ready`, `In Progress`, `Review`, `Done`
- Project field `Agent State` now exists with `Idle`, `Running`, `Waiting`
- required views `Kanban` and `Agent Queue` are now present in the Project
- built-in Project lifecycle automation is now configured for issue/PR status transitions
- the active governance issues/PR were seeded into the project with initial state values
- local Agent Issue Dispatcher hot-path coordination is now active: agents use dispatcher
  `status` / `next` / `claim` / `heartbeat` / `complete` for operational pickup while GitHub
  Issues, labels, and PR state remain the durable lifecycle truth
- the verification-dispatch integration line now fails closed on exact-head, authoritative
  `github-actions` required-check evidence, preserves review/repair budgets across restart, and
  rejects ambiguous legacy active-plus-terminal authority chains. Host rollout remains disabled
  until the ordered `preflight` → `observe-only` → `pilot` → `limited-enable` → `enabled`
  evidence receipts have each been recorded; implementation merge alone is not enablement.

Observed before this change:
- existing Issues were present but not normalized to a strict machine-readable task contract
- recent PR practice showed inconsistent Issue-linking and branch naming conventions
- no dedicated repo workflow enforced the Issue/PR contract

Known remaining gaps: none — branch protection with required status checks (`smoke`, `smoke-docker`, `pr-contract`) was added to `stable` on 2026-05-10 (issue #844, PR #853).

Target delivery model:
- Issues = canonical task contract
- Issue/PR state + labels + CI = durable lifecycle truth
- Project = optional legacy projection
- agents = execution layer
- PR = implementation artifact
- CI = validation gate

## Documentation follow-up (2026-05-12)

The cognitive prosthesis documentation spine added on 2026-05-12 introduces:

- `docs/COGNITIVE_PROSTHESIS_CHARTER.md` — product thesis.
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — human-flow to runtime bridge.
- `docs/READING_PATHS.md` — practical reading paths.

These docs frame intent; they do not change runtime behavior and do not assert that all
target-state capabilities are implemented. The following companion docs are *recommended
follow-up PRs* — they are **not** delivered by the spine PR and should be authored later when
their owning surface needs the contract:

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — bounded, inspectable agent memory
  and its relationship to human-authored knowledge.
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` — what a context bundle is, how it is assembled,
  and what it must carry as provenance.
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md` — consolidating contract over vault layout,
  catalog projection, context/artifact dimensions, and persistence-surface separation; should
  reference rather than duplicate `docs/CONCEPTS/CATALOG_PROJECTION_PRINCIPLES.md`,
  `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`, and the
  `docs/SEPARATING_PERSISTENCE_SURFACES/` spec.
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — companion UI product spec defining the Find/Reorient/
  Resurface/Act product model while preserving Panel/Chat/Automation as the canonical authority
  surfaces.

These follow-ups are not implemented by the spine PR and should be picked up via the normal
docs-authoring or docs-to-issue path when scheduled.

Update (2026-05-12): `docs/COMPANION_UI_PRODUCT_SPEC.md` is now added in this docs-only PR.
It is a target-state product specification and does not change runtime behavior.

Update (2026-05-13): context bundle and agent memory work moved from contract-definition
only into docs-first feature-breakdown preparation via `docs/CONTEXT_BUNDLES/` and
`docs/AGENT_MEMORY/`. These directories defined bounded implementation-ready specs and local draft
parent feature issues.

Update (2026-05-13): Context Bundles now have filed GitHub backlog surfaces: parent feature issue
#894 plus the first two child implementation issues #895 (`CONTEXT-BUNDLES-01`) and #896
(`CONTEXT-BUNDLES-02`). No runtime behavior changed; implementation remains future work until
those issues are delivered and validated. Agent Memory has since shipped both its initial runtime
slices and the durable-memory/guarded-recall chain noted above. The bridge-map reference to the agent-memory
contract was corrected from a local stale "future" reference to the active
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` contract.

Update (2026-05-14): Issue #850 delivered v6.0 seam observability: `config/runtime.defaults.env`
now explicitly declares `CANVAS_ENABLED=0` (canvas seam deliberately gated until stable);
startup logs report v6.0 seam readiness at INFO level; `/api/health` and `/api/status` include
an informational `v6_0_seams` field surfacing `orientation`, `resurfacing`, `commitments`, and
`canvas` status. This field is informational only and does not affect health pass/fail.

Update (2026-05-14): `CONTEXT-BUNDLES-01` (#895) delivered by PR #931. Adds the minimal
`ContextBundle` pydantic schema (`app/context_bundles/schema.py`) covering identity, trigger,
intended use, scope, included/excluded items with per-item provenance and trust posture, distinct
authority flags, stale/expiry posture, and receipt linkage. No runtime behavior changed; the schema
is a typed contract surface only.

Update (2026-05-15): All remaining Context Bundles child slices delivered. `CONTEXT-BUNDLES-02`
(#896) delivered retrieval emission; `CONTEXT-BUNDLES-03` (#946, PR #950) orientation consumer;
`CONTEXT-BUNDLES-04` (#947, PR #951) resurfacing consumer with auditable `WhyNowSignal`;
`CONTEXT-BUNDLES-05` (#948, PR #952) write-proposal linkage enforcing `may_propose ≠ may_write`;
`CONTEXT-BUNDLES-06` (#949, PR #954) receipt recording. Parent feature #894 closed. All six slices
are typed-contract implementations (`app/context_bundles/`, `app/orientation/bundle_consumer.py`,
`app/resurfacing/bundle_consumer.py`, `app/writeback/bundle_proposal.py`,
`app/receipts/bundle_receipts.py`) with full test coverage. At that delivery point, no production
route wiring had shipped; runtime bundle emission in API routes was left to a separate future slice.

Update (2026-06-04): **Context Bundles production runtime integration shipped.** The typed-contract
building blocks are now wired into production runtime, delivered by the #1559 wave:

- a read-only construction route `GET /api/context-bundles/{bundle_id}` returning an inspectable
  bundle envelope — #1560 (PR #1569);
- real retrieval emission through the capability/ports layer (not the raw-cosine `/search` route),
  recording a creation receipt — #1562 (PR #1570);
- production orientation (`GET /api/orientation/bundle/{id}`) and resurfacing
  (`GET /api/resurfacing/bundle/{id}`) consumers that preserve provenance/exclusions and reject
  mis-scoped bundles — #1563 (PR #1571);
- bundle linkage through the governed write-proposal path with WriteGuard kept independent and
  authoritative — #1564 (PR #1572);
- a read-only bundle receipt projection over creation/consumption/stale traces — #1565 (PR #1574).

Across every surface, Context Bundles remain inspectable bridge objects, not canonical truth:
`may_write` stays false, no surface upgrades authority, no bundle content is promoted into
memory/knowledge, and WriteGuard/trust/policy gates are never bypassed. Parent feature #1559 closed
on delivery of #1566. See `docs/CONTEXT_BUNDLES_RUNTIME/` for the per-slice specs and receipts.

### Cognitive mediation alignment (2026-05-16)

`docs/CAPABILITY_CONTRACT_MODEL.md` now carries the 6.x cognitive mediation alignment vocabulary:
capability classes (orientation, proposal, retrieval, clarification, synthesis/review,
governance-bearing execution, repair/maintenance), the intent-space vs capability-space
distinction, proposal-only capability semantics, and a metadata vocabulary for catalog entries
(`authority_class`, `capability_class`, `risk_tier`, `reversibility`, `approval_envelope`,
`side_effect_class`, `provenance_required`). `docs/PANEL_AGENT.md` cross-references this taxonomy
under "Capability taxonomy alignment" without claiming new shipped runtime behavior.

Scope: architecture alignment only. No runtime change, no event-payload change, no catalog change.
The vocabulary is the language new cognitive-mediation catalog entries (tracked separately) are
expected to populate; existing entries remain valid without retroactive backfill. Delivers #981
under the PanelAgent / Cognitive Mediation program coordinated by #978.

Contextual Relevance Engine — vault-native pull path plus in-app reach-out runtime slices shipped
(#1924/#1958/#1964). The `app/relevance/` package computes "moments" deterministically from
vault-native inputs (today's daily note plus open-loop / near-deadline notes), materializes each as
the CRE-01 moment artifact in the vault system plane (`<system_folder>/moments/<id>.md`) through the
WriteGuard with provenance and an Act-tier receipt, and projects them read-only at a companion-UI
"now"/glance surface (`companion_ui/workspace/now_surface.py`). The pull path is wired into the
runtime as of #1958 (Wave 2 of v6.1 delivery hub #1956): a governed watcher tick
(`app/watcher/relevance_tick.py`) computes and materializes moments each tick, and
`GET /api/companion/now` surfaces them read-only at the companion-UI glance surface. The proactive
attention loop is wired into the same runtime tick as of #1964: after materializing moments,
`app/watcher/relevance_tick.py` invokes `app/relevance/attention_loop.py` to record a reach-out or
deliberate suppression receipt per candidate, and `GET /api/companion/now` can surface an in-app
nudge when a moment clears the current in-app threshold. Zero-tolerance contexts still suppress;
OS-push delivery, external connectors, and the emergent/learned pattern loop remain deferred
follow-ons. Capability boundary and acceptance live in `docs/CONTEXTUAL_RELEVANCE_ENGINE/` and the
parent validation hub #1921.

## Cognitive Expansion — activation status (2026-07-05)

This system pursues two classes of value (see `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2.1):
**Cognitive Maintenance** (preserve cognition) and **Cognitive Expansion** (improve cognition).
Maintenance is broadly live and test-backed. The Contextual Relevance Engine above is the first
Expansion-class surface activated end-to-end on the governed control model. Most other Expansion
surfaces are built and tested but deliberately **pre-positioned** — flag-gated or not yet consumed
by the running runtime — pending the one-vertical-loop proof and the context/memory admissibility
gate (`docs/ROADMAP.md`, `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md`). This table is current-state
truth, not a backlog.

| Expansion surface | Modules | Runtime status today | Activation precondition |
|---|---|---|---|
| Contextual Relevance Engine ("now" / reach-out) | `app/relevance/*`, `app/watcher/relevance_tick.py` | **live** (governed tick materializes vault-native moments + records reach-out/suppression receipts; read-only companion "now") | external connectors + OS-push deferred |
| Panel propose → confirm → execute | `app/agents/panel_agent/*`, `app/workers/outbox_worker.py`, `app/api/routes/panel.py` | **live**. Worker path: watcher → outbox `handle_panel_scan_requested` (`outbox_worker.py`) → `run_panel_note_execution` → `execute_panel_intent` (`app/agents/panel_agent/*`), executing intents directly (it does **not** go through `/api/panel/confirm`). `POST /api/panel/confirm` (`app/api/routes/panel.py`) is the separate explicit staged-proposal confirmation path. Staged-proposal decision support, not LLM synthesis | proven vertical loop |
| Resurfacing (why-now, runtime-signal) | `app/resurfacing/*` | **live** on companion workspace/orientation, but signal-derived (runtime status), distinct from the CRE vault-native moment path | semantic relevance source admitted under admissibility gate |
| Agent-memory review/promotion | `app/agent_memory/*` | **live** (companion review queue + posture projection) | — (Maintenance-adjacent) |
| ASK answer synthesis | `app/reasoning/*`, `app/agents/ask/*`, `app/activation/ask_synthesis.py` | **gated-active-via-contract** (#2026: `_answer_node` admits the retrieved context through the deterministic admissibility gate `app/activation/gate.py` at read-only authority; on admit it runs `run_reasoning(ASK_ANSWER)` + emits an activation receipt; on block/empty it serves the literal snippet — replaces the raw `REASONING_ENABLE` flag) | test-channel UAT with the live (Ollama) provider before prod promotion |
| Canvas / chat co-authoring cognition | `app/chat/*`, `app/api/routes/canvas.py` | **seam — gated off** (`CANVAS_ENABLED=0` in prod → 403) | proven vertical loop + write-authority receipts |
| Source Understanding lenses | `app/source_understanding/*` | **seam** (`/p0` route reachable, no runtime caller) | a consuming flow + admissibility |
| Planner / next-action | `app/planner/*`, `app/orchestrator/*` | **dormant** (orchestrator imported only by CLI/smoke, not the three runtime services) | proven loop + commitment surfacing |
| Commitment surfacing | `app/domain/commitments.py`, `app/commitments/*`, Companion workspace state/API/UI | **live read-side** (durable vault-backed commitment artifacts feed a read-only Companion projection; no mutation/transition affordance) | mutation, reminders, automatic closure, and CRE reach-out remain follow-ons |
| Knowledge compilation / cross-note synthesis | `app/knowledge_compilation/*`, `app/reasoning/multi.py`, `app/expansion/create.py`, `app/expansion/accept.py` | **gated-active-via-contract** (EXP-3, #2996: `run_create_pass` is the first runtime caller of both `run_multi_note_reasoning` and `proposal_builders.build_compilation_draft`, activated through `app/activation/gate.py` at `proposal` authority — the gate's second proof after ASK #2026. EXP-4, #2997: governed acceptance now lands the checked-checkbox path — `app.expansion.accept.accept_draft` is the ONLY path from a staged draft to a canonical note, WriteGuard-gated with a decision-token + acceptance receipt. Output kinds: `create.overview`, `create.answer_note`, and `create.digest` (EXP-5, #2998) all share the identical staged-draft lifecycle; digests are explicit-ask only, never auto-run from a moment. The shared `ReasoningOutput` result keeps runtime-owned `success` / `empty_output` / `provider_failure` / `missing_input` outcomes explicit; degraded runs never fabricate claims or inferences, and Create records that outcome separately from deterministic source collation.) | test-channel UAT with the live (Ollama) provider before prod promotion |
| Conversational Journaling draft (`journal_draft_proposal`) | `app/journaling/draft.py`, `app/activation/journal_draft.py` | **gated-active-via-contract** (JRNL-03/#3349: a guarded, serialized no-follow transaction stages one proposal per day under `<system_folder>/drafts/journal/`; every transcript/day-context source retains its actual review posture and must independently reach cited-proposal admission (`revised` stays read-only; rejected/unknown is excluded) before cognition or staging. UUID-addressable cognition consumes the runtime-owned explicit reasoning outcome and bounded degradation reason, never infers success from counts, and never fabricates claims or synthesis; deterministic cited collation remains visibly separate. The content-free activation receipt is embedded atomically with the draft. The canonical daily note is never written; accepted-entry follow-ups route to a separate addendum candidate.) | JRNL-04 owns explicit human acceptance/promotion; test-channel UAT before prod promotion |
| Connect — relationship surfacing (`connection_proposal`) | `app/expansion/connect.py`, `app/curation/findings.py`, `app/curation/proposal_writer.py` | **gated-active-via-contract** (EXP-1/#2994, EXP-2/#2995, EXP-5/#2998: `run_connect_pass` proposes `connect.related_unlinked`/`connect.thematic_link` findings and `find_cluster_emergence` proposes `connect.cluster_emergence` findings — all candidate-only, materialized as unchecked panel checkboxes via the G2 writer, never auto-applied. An accepted `connect.cluster_emergence` finding hands off to a `create.overview` request via `cluster_emergence_to_create_request`, still through the full staged-draft lifecycle) — moved dormant → gated-active as its EXP-6 (#2998) activation-gate record (`app/activation/expansion_records.py::evaluate_connection_proposal_activation`) went green | test-channel UAT before prod promotion |
| Create — synthesized outputs (`synthesis_note_proposal`) | `app/expansion/create.py`, `app/expansion/accept.py`, `app/activation/expansion_records.py` | **gated-active-via-contract** — moved dormant → gated-active as its EXP-6 (#2998) activation-gate record (`evaluate_synthesis_note_proposal_activation`) went green; a regressed precondition on either Expansion record yields blocked-with-reason, never a silent run (`expansion_requires_activation_record`) | test-channel UAT before prod promotion |

Definitions: **live** = consumed by a running service in normal operation; **seam** = built and
registered but flag-gated or uncalled; **dormant** = code plus tests exist, no runtime invocation.
The CRE shows the activation path working; closing the rest of the Maintenance/Expansion asymmetry
is the system's next major frontier, and the sequencing is intentional, not an oversight.
