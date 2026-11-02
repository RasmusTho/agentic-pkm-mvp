State: SoT v5.5 Reality-MVP baseline locked; v5.6 delivery line closed; this is the top-level operations entrypoint for the current runtime while v6.0 seams are shipped in bounded form and broader v6.1+ consumption remains planned. The Product Runtime placement contract uses TARS-hosted Linux guests for dev, test and prod; the Mac mini provides control, client and model-execution services. The infrastructure repository's current-status view owns dated physical host and service observations; environment and deployment contracts remain separate.
Doc role: Core SoT
Authority: Top-level operator guidance for the current runtime; delegates specialized operational detail to linked companion docs but remains the main operational entrypoint.
Owner: Runtime / operator playbook
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-10-30 (#6479 fixed operations acceptance entrypoint and pending deployed-proof boundary; source only; prior #6447/#6384/#5337 evidence retained)
Current infrastructure observation reference: 2026-10-21, `yggdrasil-infra/CURRENT_STATUS.md`; this is not a new deployment, release or functional-acceptance receipt.
Infrastructure reference review: 2026-10-21; other sections retain their individual verification dates.
Local Colima startup entry reviewed 2026-10-24 against scripts/start_full_system.sh, tests/ops/test_colima_runtime_readiness.py and the isolated/default runtime receipts on Issue #4899; no TARS verification or placement change.
BWS child-runtime repository evidence: requirements-bws-deploy.txt; scripts/install_bws_deploy_runtime.sh; tests/deploy/test_deploy_channel.py::test_bws_runtime_setup_covers_mandatory_browser_smoke and tests/deploy/test_deploy_channel_script.py::test_managed_deploy_child_uses_declared_supervisor_interpreter; Issue #5905 / PR #5906 (repository validation only; no live host installation or channel acceptance).
Native web entry repository evidence (2026-10-12): app/ops/postgres_deploy_linux.py::LinuxEffects.qualify_web, app/ops/native_web_acceptance_runner.py::NativeWebRunner, and tests/ops/test_native_web_acceptance.py; runtime pilot qualification remains with #2443/#3314.
Native journaling entry repository evidence (2026-10-14): app/ops/postgres_deploy_linux.py::LinuxEffects.qualify_journaling, app/ops/native_journaling_acceptance_runner.py::NativeJournalingRunner, and tests/ops/test_native_journaling_acceptance.py; actual-image/provider TEST acceptance remains with #3347.
Native authority-cutover repository evidence (2026-10-14): app/ops/postgres_deploy.py::DeployPlan, app/ops/postgres_deploy_linux.py::DeploymentSupervisor and tests/deploy/test_postgres_deploy_authority_cutover.py; live nonprod qualification remains with #3367.
TEST dormant-ownership section reviewed and verified against repository-only #5937 evidence (2026-10-16): app/instance/legacy_owner_recovery.py::initialize_dormant_ownership and tests/ops/test_dormant_ownership_initialization.py; no live authority, channel or service verification.
Current-state source admission section last verified against repository-only #6316 evidence (2026-10-24): app/ops/native_source_admission.py, app/ops/postgres_deploy_linux.py::LinuxEffects.persist_source_identity and tests/ops/test_native_source_diagnostic_admission.py; actual source and same-candidate DEV/TEST acceptance remain with #3347/#6300.
BWS source-install recovery repository evidence (2026-10-26): `app/ops/bws_installation_transaction.py`, `app/ops/bws_installation_admission.py`, `app/ops/bws_installation_lifecycle.py`, and `tests/ops/test_bws_installation_transaction.py`; Issue #6342. Synthetic temporary-file and injected-port proof only; no native host or service verification, and same-image DEV/TEST acceptance remains with #3347.
BWS host-admin target-scope repository evidence (2026-10-28): `app/ops/postgres_deploy_host.py::_configured_deploy_admin`, `app/ops/bws_secret_admin.py::BwsSecretAdmin._session/read`, `tests/deploy/test_host_deploy_metadata.py`, and `tests/ops/test_secret_admin.py`; Issue #6384. DEV/TEST uses selected-project metadata and filters organization-scoped secret identifiers before any value GET while generic parity and full admin routes remain. Synthetic provider tests only; no live BWS, service, or channel verification.
Last verified against: scripts/postmerge_channel_bug.py::advance_channel_ref, .github/workflows/postmerge-channel-bug.yml and tests/deploy/test_postmerge_dev_test.py::test_channel_refs_advance_only_on_green_verdicts / ::test_dev_hold_pins_ref_and_records_candidates (#6226 repository-only ref/hold proof); scripts/postmerge_dev_test.py and tests/deploy/test_postmerge_dev_test.py::test_test_promotion_requires_passing_dev_heavy_verdict (#6227 repository-only dev-heavy gate evidence); requirements-bws-deploy.txt (host SDK closure), scripts/install_postmerge_controller.py, scripts/postmerge_controller.py, scripts/postmerge_dev_test.py, scripts/dev_delivery_liveness.py and tests/deploy/test_postmerge_dev_test.py::test_controller_runs_from_pinned_tooling / ::test_controller_self_check_fails_loud (#6225 repository-only pinned tooling and startup proof); scripts/postmerge_dev_test.py::engage_pause and tests/deploy/test_postmerge_dev_test.py::test_kill_switch_pauses_until_expiry (#6224 repository-only pause evidence); scripts/dev_delivery_liveness.py and tests/governance/test_dev_delivery_liveness_workflow.py (#6222 repository-only liveness evidence); scripts/postmerge_dev_test.py, scripts/postmerge_channel_bug.py and tests/deploy/test_postmerge_dev_test.py (#6223 repository-only rolling channel-bug evidence); scripts/companion_ui_postdeploy_smoke.sh::preflight and tests/companion_ui/test_gateway_postdeploy_smoke.py::test_collection_preflight_classifies_captured_output_without_pipe_race (#6079 repository-only evidence), docs/MIMER_VOICE_LOOP/CARRY_SESSION_FOLLOWUP_CONTEXT.md, app/api/routes/ask.py::ask_voice, app/chat/voice_session.py::VoiceSessions, tests/voice/test_session_transcript.py::test_only_write_is_appendonly_transcript (VOICE-04 repository evidence), docs/STATUS.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/HEALTH.md, docs/INFRASTRUCTURE.md, docs/ENVIRONMENTS.md, docs/OBSERVABILITY.md, docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md, docs/ASK_PROVENANCE_MANIFEST/README.md, docs/CONTEXTUAL_RELEVANCE_ENGINE/README.md, docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md, docs/KARAKEEP_MIMER_ACQUISITION/README.md, docs/KARAKEEP_MIMER_ACQUISITION/DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md, docs/KARAKEEP_MIMER_ACQUISITION/PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md, config/secrets/host_secret_contract.json, app/release_channels/ordinary_boot.py, app/ops/test_channel_bootstrap.py, app/agent_memory/ask_provenance_manifest.py, app/relevance/now_surface.py, app/instance/runtime.py, app/instance/ownership_ledger.py, app/ops/postgres_deploy_linux.py, app/ops/native_source_bootstrap.py, scripts/deploy_channel.sh, tests/deploy/test_deploy_channel_script.py::test_native_deploy_rebuilds_source_projection_before_health_gate, tests/deploy/test_deploy_channel_script.py::test_native_api_source_selector_refuses_before_source_write, tests/deploy/test_deploy_channel_script.py::test_native_source_unbound_api_preserves_idle_without_source_write, tests/deploy/test_deploy_channel_script.py::test_native_source_projection_prepares_ollama_before_stopping_services, tests/deploy/test_deploy_channel_script.py::test_native_source_projection_refuses_unavailable_ollama_before_stopping_services, tests/deploy/test_deploy_channel_script.py::test_native_source_projection_preserves_selected_embedding_identity, Issue #6069 candidate containing origin/main 8ec709f (repository-only; no live channel verification), tests/ops/test_ci_workflow.py::test_not_pg_steps_have_room_for_selected_coverage, scripts/instance_state_writer_inventory.py, scripts/lib/instance_ownership_host_state.sh, scripts/lib/instance_state_deployment.sh, scripts/start_full_system.sh, scripts/verify_runtime_stack.sh, tests/ops/test_instance_state_volume_contract.py, tests/ops/test_mvr05_mixed_version_fence.py, tests/ops/test_instance_state_writer_inventory.py, Issue #5823 / PR #5825, Issue #5442 / PR #5450, Issue #5511 / PR #5513, Issue #5885 / PR #5887 and Issue #5888 (repository-only; no live host verification), merged PRs #1948/#1977/#2115/#2127/#2128/#2129/#2131/#2135/#2140/#2142, and current repo state on 2026-10-14
TypeSafe credential boundary evidence: config/secrets/host_secret_contract.json; tests/ops/test_host_secret_contract.py::test_typesafe_key_uses_non_prod_project_and_marr_only_consumer, tests/ops/test_secret_admin.py::test_typesafe_import_targets_non_prod_and_rejects_other_channels, and tests/architecture/test_typesafe_runtime_boundary.py::test_runtime_key_stays_on_marr_and_callers_keep_separate_policy; Issue #5808 follows Issue #5801 / PR #5803 on 2026-10-07. Repository-only fake/injected-source evidence; no live BWS permission or host/provider verification.
TypeSafe Builder CKM repository evidence: app/builderops/ckm/judgment.py, app/model_access/ckm_judgment_executor.py, tests/builderops/ckm/test_semantic_typesafe.py, and Issue #5768 on 2026-10-05; fake-provider proofs only, with runtime disabled and no live host or provider verification.
TypeSafe DEV actual-consumer evidence: the [2026-10-21 Product receipt and external cleanup](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6288#issuecomment-6309809365) and [preserved Builder receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5764#issuecomment-6203507688) verify the separate synthetic calls. Both allowances are consumed, temporary listeners/processes are absent, and ordinary routes remain disabled; broader #5667 and TEST/PROD activation keep their separate gates.
# Operations Playbook

Use this document as the operator-facing starting point for runtime operations.

Specialized companion documents:
- `docs/HEALTH.md` - health CLI behavior and runtime health contract
- `docs/OBSERVABILITY.md` - runtime observability signals, counters, and span/log contracts
- `docs/INFRASTRUCTURE.md` - application Compose fallback and local observability reference
- [yggdrasil-infra current status](https://github.com/RasmusTho/yggdrasil-infra/blob/main/CURRENT_STATUS.md) - dated Macs, TARS/VMs, Docker engines, network, storage and related-service observations; Builder Vault carries the operational handoff and private evidence locator
- `docs/SECURITY_ARCHITECTURE.md` - security review routing, threat-model tiers, and security invariants
- `docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md` - target ownership boundary for the
  ecosystem operational platform; this playbook remains the current operator entrypoint and runbook
  router

Reading order:
1. Start here for runtime expectations, core checks, and escalation paths.
2. Follow `docs/HEALTH.md` when verifying readiness or diagnosing degraded state.
3. Follow `docs/OBSERVABILITY.md` for interpreting telemetry and counters.
4. Use `docs/INFRASTRUCTURE.md` when you need Docker/runtime topology, local startup flow, or the local monitoring stack.
5. Use `docs/runbooks/` only for task-specific walkthroughs after you have identified the affected runtime surface.
6. Use `docs/ENVIRONMENTS.md` when the question is whether behavior belongs to `dev`, `test`, `prod`, or a boundary between them.
7. Use the parallel-stack recipe in `docs/ENVIRONMENTS.md` when you need to run `dev`, `test`, and `prod` Compose stacks simultaneously on one machine.
8. Use `docs/RELEASE_CHANNELS/README.md` plus the promotion skills when the question is stable/dev channel promotion, rollback, or prod-checkout pinning; use `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` for the physical deploy sequence, including authenticated legacy-ledger convergence before the MVR-05 floor.
9. Use `docs/SECURITY_ARCHITECTURE.md` and `docs/security/API_SECURITY_MATRIX.md` before changing
   API exposure, auth/rate-limit posture, external provider/tool execution, or mutation-capable
   route behavior.
10. Use `docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md` when deciding whether a host,
    Docker/Colima, Compose, channel-topology, lifecycle-wrapper, platform-health, or runbook change
    belongs to the operational platform rather than to a Product/Runtime or Builder System owner.

CLI note:
- `python -m app.cli --help` and `python -m app.cli <command> --help` remain the authoritative command discovery surface because the CLI evolves faster than the docs.
- Runtime verification note: `make verify-runtime` is the authoritative local operator check for the live Docker stack because it verifies service health plus in-container CLI health, rather than the host shell environment.
- Canvas note: `python -m app.cli canvas ...` and `/api/canvas/*` now exist as bounded session surfaces behind `CANVAS_ENABLED`; they are materially supported for bounded co-authoring, but still not part of the default production operator surface.

### Fixed autonomous-operations acceptance

The operations acceptance entrypoint is `tests/operations/live_operations_acceptance.py`;
[Automated Technical Acceptance](TESTING.md#automated-technical-acceptance) owns its exact TEST/DEV
commands, native prerequisites, fixed inventory and original-evidence handling. It consumes current
native candidate/principal/binding authority, qualifies the separately installed SDK/browser, and
narrows finite Product effects through existing owners. It performs no deployment, restoration,
principal provisioning or restart. A missing environment or separately authorized backend/WSP
restart leaves the required scenario blocked. Temporary fixture proof and delivery of #6479 do not
establish deployed acceptance; the qualified same-candidate TEST/short DEV outcome and post-acceptance
owner-doc/State promotion remain on #5340/#5329.

### Native source-persistence failure receipts

Supervised DEV/TEST source persistence records only fixed, content-free failure stages for worker
context, lock/guard, writer stop, worker transport/quiescence/receipt validation, producer-receipt
publication, writer restoration, and exact-owner lock retirement. Do not treat one of these reasons as
source eligibility or deployment acceptance. A valid producer receipt remains unchanged in its
producer entry; a later cleanup failure is recorded separately in the final terminal and permits only
the exact same-ID cleanup route. Child output, exception text, source identity or paths, environment
or mount values, and credentials must never be copied into receipts or operator notes. See
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` for the detailed stage and cleanup contract.

For intact protected authority with a retained stopped writer, use the explicit DEV/TEST
current-state flow in the [deployment procedure](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#deploy-procedure):
fresh read-only diagnosis, separately authorized ordinary registry persistence, exact prior-running-set
restoration and full eligible readback, then separately authorized ordinary deployment. Source
operations do not start the retained watcher or adopt missing historical ownership; default persistence
still requires all required writers running. Malformed retained operation entries are refused, not
replaced. An authenticated never-admitted proof consumes only its exact sent operation ID and is not
a producer attempt, successful admission or permission to replay. These are repository-supported
operations, not live source qualification or closure of #3347/#6300.

The exact supportable source-identity repair module is an inert DEV library, not an operator CLI or
standing recovery route. A separately governed native owner must supply one reviewed 23+26 private
batch whose revision, image, selection, target-set digest, and physical vault identity match fresh
host authority inside one owned fence. The library performs no discovery, producer allocation,
controller load, deployment, inference, or promotion. Do not replay partial/indeterminate outcomes;
reconcile only against retained exact hashes. Rollback is permitted only for a validated batch
member whose current bytes equal its admitted candidate and must run under the same pre/post fence.
No raw path, UUID, content, or exception text belongs in its public count-only receipt.

The repository also supports one new, single-use DEV/TEST BWS source-installation transaction through
`app.ops.bws_installation_transaction`. Its direct `rpc dev|test` caller must come from the exact
clean candidate checkout. It binds a fresh operation reservation, the complete current writer/caller
census, source roots, unit configuration, and old/new generations; it records old on-disk state but
does not infer which source bytes a legacy service loaded. The fixed candidate launcher is installed
first, the exact old process is stopped and verified, and only then are remaining source and JSON
files replaced through the same prepared handle. Success requires final exact-generation checks and
a redacted terminal receipt. If installation fails after stop and the old runtime cannot be
qualified, the transaction leaves the service stopped and its owner unresolved. It never adopts or
replays an earlier operation, retries an unknown outcome, or routes to PROD. This repository support
does not authorize a live call or prove DEV/TEST acceptance; #3347 remains the owner gate. See the
[detailed deployment contract](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#native-source-preflight-and-recovery).
The fixed full-source path also checks combined application/control inventory, prospective additions
against the existing directory-entry ceiling, and the current process's descriptor headroom for
retained preparation, apply, authenticated compensation, the complete installed-inventory recheck,
and the bounded service-configuration control-root projection while the handle remains open before
service or backup effects. Only the verified one-shot source CLI may temporarily raise its own soft
limit to the finite derived minimum within its unchanged existing hard cap. Unknown/inadequate hard
capacity, an ineligible/shared process or failed resource admission refuses. Original limits are
restored after owned descriptor cleanup; uncertain cleanup/restoration terminates the dedicated CLI
before unrelated work. No unit, hard, parent/other-process or persistent resource setting changes.
The generic 192-entry limit
and 190-module provenance limit remain separate. This is repository support, not live host capacity
or DEV/TEST acceptance evidence; see the detailed contract for the finite source and descriptor
budgets.

#### BWS source-installation refusal diagnostics

A caught `refused_before_backup` receipt includes the finite `prebackup_gate` diagnostic. Its base
values are `channel_lock_entry`, `channel_owner_check`, `caller_census`, `current_writer_snapshot`,
`authority_cutover`, `candidate_verification`, `old_disk_state`, `owner_launcher_profile`,
`backup_roots`, `source_manifest`, `descriptor_capacity`, `descriptor_capacity_unknown`,
`descriptor_capacity_insufficient`, `descriptor_capacity_ineligible`,
`descriptor_capacity_admission_refused`, `candidate_profile`, `old_kernel_qualification`,
`qualified_writer_snapshot`, and `generation_qualification`, plus the explicit OLD-kernel stage/family
combinations in the table below. The diagnostic contains no exception
text or operation input; it identifies the producer gate for that caught refusal. The
`authority_cutover` value names a real current-writer predicate after the bound plan is read, but
does not establish that it caused any previously observed refusal. Legacy receipts without this
field remain valid. Descriptor-specific gates separate unknown metadata, qualified inadequate
capacity, ineligible process context and failed resource admission without numeric values; the
legacy `descriptor_capacity` gate and Source19's inner predicate remain unclassified. The
`refused_before_backup` status and null generation and backup fields retain
their existing meanings.

OLD-kernel refusals retain the coarse `old_kernel_qualification` fallback. Supported
new refusals use `old_kernel_initial_<family>` for service setup, retained-runtime
entry and the first qualification, or `old_kernel_empty_control_<family>` for the
final empty-control configuration revalidation immediately before prepare/backup.
The closed families are:

| Family | Public guard meaning | Supported stages |
| --- | --- | --- |
| `setup` | Fixed DEV/TEST unit selection or qualification call shape | `initial` |
| `retained_runtime` | Registered runtime metadata, retained FD or its ownership/close contract | `initial`, `empty_control` |
| `unit_properties` | Read-only bus transport, typed response shape or required unit/configuration properties | `initial`, `empty_control` |
| `root_control` | Application/control projection, root identity, loader inventory, control hints or final configuration equality | `initial`, `empty_control` |
| `launcher` | Public launcher content/identity, proposed launcher payload or start topology | `initial`, `empty_control` |
| `service_process` | Active/running state, job/control/main PID, unit-process census or root/start/cwd/runtime/argv/main-task identity | `initial` |
| `cleanup_contract` | Required cleanup command tuple and execution contract | `initial`, `empty_control` |

These are explicit finite allowlisted gate values, not private predicate values.
Only the lifecycle's supported refusal type and allowlisted family can refine the
coarse gate at those two transaction sites; unknown, malformed, unsupported or
foreign exception classifications retain `old_kernel_qualification`. No exception
text, argv, transport output, path, environment value, PID/start token, root identity
or credential enters this diagnostic. Existing receipts with no diagnostic or the
coarse gate remain readable and immutable. A classified refusal still has null old,
new and backup hashes and cannot reach prepare, backup, stop or apply. All original
guards, their invocation order and retained-runtime cleanup remain binding.

At the initial `Unit_DropInPaths` selector, the finite first-failed categories are
`cardinality`, `allowed_parent`, `basename_length`, and `basename_grammar`. The
selector uses the already-read property and checks cardinality before element shape,
then allowed parent, basename length, and basename grammar. Empty selection and a
valid singleton retain their existing behavior. The public diagnostic contains only
the category; it does not disclose a count, path, property value, exception, digest,
or other private input. Cardinality now refuses above the fixed bound of four;
duplicate paths/basenames use the coarse selection refusal. Prebackup refusal/effect
boundaries remain unchanged. Legacy absent, coarse, value, and `selection` receipts remain
valid. Source26's public result identifies the selector family but leaves its actual
failed predicate unknown; it establishes neither a source defect nor native
acceptance.

The captured-empty control-PATH configuration supports the finite preserved PATH-only
drop-in profile documented in [Native source preflight and recovery](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#native-source-preflight-and-recovery):
up to four ordered protected `.conf` files in the fixed instance/template `/etc` unit
directories, each with bounded two-line syntax and exact agreement with the sole typed
loaded PATH assignment. Empty/singleton behavior is preserved. The entire vector is
validated before content reads, rejects duplicate paths/names and aliased identities,
and shares one 4096-byte accepted /4097-byte returned-content budget per walk,
including failures. Complete Environment bytes/order remain bound. Null output streams,
UMask 0077, canonical encrypted-credential metadata and empty plain credentials are
checked without credential payload/file reads; pending reload refuses. The six loaded-property
checks retain their existing coarse/family diagnostics and disclose no selected path, content,
metadata, effective value, digest or backend exception.

The complete preserved file/ancestor/mount vector is disjoint from application, control,
launcher, backup and all staging/restoration effect parents, remains bound through
same-handle compensation, and never authorizes configuration/control writes. Changed
selection, content, lookup/mount edges or named effective settings refuse or retain
phase-appropriate uncertainty. Legacy OLD still remains `compensated_stopped` without
independent loaded-source restart proof. This proves named effective invariants under
the existing trusted root/systemd and externally admitted window; it does not prove
historical loaded-unit bytes. `NeedDaemonReload=false` is supplementary, and BWS caller
reservation does not exclude arbitrary root writers or external manager reloads.
Repository support does not qualify actual private input or authorize native/parent
acceptance. Unsupported formats retain their refusal boundary.

Initial retained-PATH refusals additionally use
`old_kernel_initial_root_control__<mode>__<side>__<role>__<guard>` in that existing
optional field. `path_environment` means the PATH branch was reached before
selection; `path_absent` and `path_selected` mean the original complete selector
returned empty or nonempty. Neither reports a count or input identity. Side is
`old` or `proposed` only for `path_hints/launcher_hint`, otherwise `unknown`.
These combinations are **initial-only**; final empty-control and later phases keep
their family/phase outcomes. The original discovery vocabulary is unchanged.

The following is the complete added finite vocabulary. Each guard names the
first original atom, or the original operation whose cause remains UNKNOWN:

| Source role | Exact guard symbols | Minimum decision or explicit residual |
| --- | --- | --- |
| `loaded_slots` (`path_environment`); `parsed_slots` (`path_selected`) | `path_population`, `non_path_hint`, `hint_bound`, `path_absolute`, `path_backslash`, `path_nul`, `path_canonical`, `component_bound`, `misleading_hint`, `slot_absent`, `duplicate_components` | Requalify respectively the sole-PATH population, other control hint, 16-component bound, absolute form, forbidden backslash/NUL, canonical components, 32-component path bound, misleading root substring, control-slot presence or uniqueness. Which empty/dot/parent component failed is UNKNOWN; no second inspection. Branch/typing/regex-excluded rows are defensive, not claimed reachable initial failures. |
| `path_hints` (`path_environment`) | `environment_files`; `launcher_hint` (separate `old`/`proposed`) | Requalify the named unsupported hint source before DropInPaths; no unit edit/removal is authorized. |
| `config_footprint` | `population`, `application`, `launcher_parent`, `construction_unknown` | Requalify the manifest footprint population, application binding or launcher-parent binding respectively. Malformed/unexpected construction is UNKNOWN at this fixed config site. |
| `binding` | `construction_unknown`, `slots_changed`, `selection_changed`; `loaded_assignment` (`path_selected`); `branch_changed` (`path_environment`) | Unknown initial construction; saved slot drift; complete selection drift; disk/loaded sole-PATH disagreement; or departure from the supported branch. Each requires its named binding to be requalified. A fresh initial service starts without a saved binding. |
| `ancestor`, `control_root`, `application_root`, `launcher_root`, `backup_root`, `effect_parent`, `selected_parent`, `slot_descent`, `slot_census`; also `retained_directory`, `current_directory`, `fresh_directory` | `directory_fstat_unknown`, `directory_type`, `directory_mode`, `directory_owner`, `directory_inheritable_unknown`, `directory_inheritable` | At the static caller role, distinguish unavailable fstat, required directory type, writable-mode predicate, accepted owner pair, unavailable inheritance query and inheritable FD. Requalify that invariant; unavailable operations have UNKNOWN OS cause. No metadata value is disclosed. |
| The first nine directory roles above | `directory_absolute`, `directory_component_bound`, `directory_canonical`, `descriptor_bound`, `open_unknown`, `mount_crossing` | Requalify representation/bounds, descriptor capacity, unavailable no-follow open, or same-mount proof respectively. No alternative lookup or retry is implied. Ancestor is the original recursive ancestry, not an inferred private path. |
| `selected_input`, `content_input`, `retained_input`, `current_input`, `fresh_input` (`path_selected`) | `file_fstat_unknown`, `file_type`, `file_link`, `file_owner`, `file_mode`, `file_size_positive`, `file_size_bound`, `file_inheritable_unknown`, `file_inheritable`, `file_access_unknown`, `file_access` | Requalify the selected file's regular type, single link, exact owner, original forbidden mode mask, positive size, per-file ceiling, noninheritance or read-only access as named; query failures retain UNKNOWN cause. The original mode mask is one predicate, not a guessed individual bit. |
| Every directory/file identity role above | `mount_platform`, `mount_libc_unknown`, `mount_buffer_unknown`, `mount_statx_unknown`, `mount_statx`, `mount_unpack_unknown`, `mount_mask`, `mount_identity` | Qualify supported Linux; or diagnose the fixed libc/buffer/call/unpack operation; or requalify statx success, requested mask or nonzero mount identity. Native cause/errno/mount value is UNKNOWN. No fallback metadata source is used. |
| `retained` | `retained_version` | Previously held version changed; which member differs is UNKNOWN. Preserve refusal and requalify the complete retained proof. |
| `footprint` | `tuple_type`, `population`, `member_mapping` | Requalify the manifest producer's exact tuple, population or mapping shape. Real NativePorts constructs the complete three-root tuple; malformed shapes remain direct defensive guards. |
| `roots` | `equal`, `above`, `recorded_identity`; historical `below` remains readable | Distinguish root equality, the earlier root below the current root, or recorded root identity disagreement. Requalify disjointness or bound root proof; the differing identity member/cause is UNKNOWN. |
| `roots_application_control`, `roots_launcher_control`, `roots_launcher_application`, `roots_backup_control`, `roots_backup_application`, `roots_backup_launcher` | `below` only | The current schema root is below the earlier compared schema root, in the original control/application/launcher/backup order. Requalify disjointness; the public pair alone establishes no safe topology remedy. |
| `effect_parents` | `tuple_type`, `empty`, `bound`, `member_type`, `duplicate`, `outside_effect` | Requalify the producer's exact tuple, nonempty coverage, bound, string members, uniqueness or confinement to application/launcher effects. No subset can be adopted. |
| `selected_parent` (`path_selected`) | `equal`, `below`, `above`, `identity_alias` | Distinguish each protected-root relationship from directory identity alias. Requalify footprint disjointness or lookup identity, without exposing a path. |
| `selected_file` (`path_selected`) | `descriptor_bound`, `open_unknown`, `mount_crossing`, `identity_alias`, `aggregate_size` | Distinguish capacity, unavailable file open, mount crossing, file alias and whole-vector declared-size overflow. Directory alias, per-file size and aggregate size have different decisions. |
| `selected_content` (`path_selected`) | `pread_unknown`, `returned_length`, `post_read_version`, `grammar`, `assignment_disagreement` | Requalify unavailable bounded read, length proof, post-read version, supported two-line syntax, or agreement across all selected assignments. A regex refusal has UNKNOWN internal syntax reason; a version comparison has UNKNOWN changed member. No classifier is run afterward. |
| `loader_app`, `loader_scripts` | `stat_unknown`, `present` | Diagnose unavailable no-follow stat, or requalify the named captured-empty loader slot. Missing remains successful absence. Presence establishes neither type/content nor safe removal. |
| `slot_descent` | `stat_unknown`, `not_directory` | Diagnose the unavailable edge or requalify unsupported lookup topology. A missing edge still stops descent successfully. |
| `slot_census` | `before_fstat_unknown`, `scandir_open_unknown`, `scandir_iteration_unknown`, `scandir_exit_unknown`, `entry_stat_unknown`, `entry_bound`, `entry_owner`, `entry_mode`, `entry_type`, `entry_executable`, `entry_link`, `after_fstat_unknown`, `directory_time_drift` | Unknown operations stay separate at their fixed sites. Other guards separately require bounded direct population, exact owner, nonwritable mode, supported directory/regular type, nonexecutable regular file, single link or stable directory times. Which timestamp changed is UNKNOWN. Direct subdirectories are still accepted without recursion/content reads. |
| `absent_edge` | `stat_unknown`, `appeared` | Diagnose unavailable repeat stat, or requalify an edge that appeared. Absence remains success; no entry type/content is inferred. |
| `current_edge`; `fresh_edge` | `stat_unknown`, `held_version`, `edge_identity`; `open_unknown`, `version` | Separately requalify current namespace availability, held proof, device/inode edge binding, fresh-open availability or fresh-view agreement. Different recorded members remain UNKNOWN. Fresh FDs retain their original finally-close. |
| `snapshot`; `walk` | `disagreement`; `unexpected_unknown` | Complete saved snapshot drift, or an otherwise unexpected operation at the fixed revalidation boundary. Preserve refusal/uncertainty and requalify; the changed field or native cause is UNKNOWN. |

The six `roots_<current>_<earlier>` roles are selected only after the original
`current.startswith(earlier + '/')` predicate has failed disjointness. They admit
exactly twelve combinations: `path_absent` or `path_selected`, side `unknown`,
guard `below`, at INITIAL only. There is no additional path read, predicate,
classification or later-pair inspection. `equal`, `above`, `recorded_identity`,
original discovery and final empty-control/later-phase exports are unchanged.
Pairs among the fixed control/launcher/backup roots are defensive under their
mutually disjoint production constants; synthetic coverage of all six is not a
claim that every pair can reach this initial branch through prior gates.
The lower installation manifest still independently requires disjoint roots.
The verified candidate Source RPC runs the candidate producer and finite readers
before installation; a refusal leaves the installed OLD validator/source intact.
Legacy `roots/below` receipts remain readable and reconciliation returns them
unchanged. Source28's historical role pair and safe compatibility remedy remain
UNKNOWN; this source support grants no native read/retry, installation, DEV/TEST
admission, capture or parent closure.

Unless narrowed above, walk roles use `path_absent` or `path_selected`; all sides
are `unknown`. Symbols never include an index, native path/count/content/digest,
mode/owner value, environment, argv, exception/type/errno or stack information.
The same original call supplies the diagnostic: no extra OS read, predicate,
parser, census or walk is introduced. Whole-vector metadata still precedes any
content, with the unchanged 4096 accepted /4097 returned-byte budget including
failures. Full typed Environment order, six loaded-property checks, FD envelopes,
source/target C/D and exact Git launcher binding, generation/compensation and
original-handle rules remain mandatory.

Actual owned closes are attempted once; replacement FDs are never closed and
sticky retained/transient close uncertainty overrides an earlier diagnostic.
Existing unresolved assembled paths retain fatal exit 78, no outer stdout/terminal
response and their owner. Transient PATH-close uncertainty publishes no terminal
receipt. The original retained-runtime-close path can retain one inner
`old_kernel_initial_retained_runtime` fallback with null generation/backup fields;
that record does not override the outer failure or establish a completed operation.
An `__provenance_unavailable` suffix still means scoped
early executed-source comparison was unavailable; no suffix is not final caller,
loaded-source or FULL proof. Unknown/foreign/subclass/missing/malformed metadata
keeps the existing family/coarse fallback and legacy absent-field receipts remain
readable.

This source support does not identify Source27's native failure site, cause or
profile fit. Source27 remains one closed initial refusal with no backup/stop or
installation; it proves no later PATH or loaded check passed. Changed source bytes
need their natural matched image and a separately applicable native decision.
Same-image DEV, TEST and parent acceptance remain separate and open; these symbols
authorize no native observation, repair, replay or subsequent operation.

Initial unit-property diagnostics additionally use
`old_kernel_initial_unit_properties__<site>__<kind>` from the **original** read or
predicate. Kinds are `backend` (unavailable/failed bounded transport), `decode`
(invalid JSON, including duplicate keys), `signature` (unexpected bus type),
`shape` (existing envelope/method/object/Environment/EnvironmentFiles shape check),
and `value` (an existing required-value predicate). Sites are the fixed
`Manager_GetUnit` and `Manager_GetUnitProcesses`; `Unit_` plus `Id`, `LoadState`,
`OnFailure`, `OnSuccess`, `TriggeredBy`, `ActiveState`, `SubState`, `Job`,
`DropInPaths`, or `JoinsNamespaceOf`; and `Service_` plus `Type`, `User`, `Group`,
`KillMode`, `Restart`, `ExecCondition`, `ExecStartPre`, `ExecStartPost`, `ExecStop`,
`ExecReload`, `ExecStart`, `ExecStopPost`, `Environment`, `EnvironmentFiles`,
`ControlPID`, `MainPID`, `RootDirectory`, `RootImage`, `WorkingDirectory`,
`BindPaths`, `BindReadOnlyPaths`, `TemporaryFileSystem`, `ReadOnlyPaths`,
`ReadWritePaths`, `InaccessiblePaths`, `PassEnvironment`, `ExtensionDirectories`,
`MountImages`, `ExtensionImages`, `PAMName`, `UnsetEnvironment`, `ExecSearchPath`,
`PrivateMounts`, `PrivateTmp`, `PrivateDevices`, `PrivateUsers`, `DynamicUser`,
`ProtectHome`, or `ProtectSystem`. `Service_ExecStopPost_final` identifies the
last cleanup read after process qualification. Only baseline and PATH required
configuration predicates admit `value`; launcher, cleanup, process and root
semantic refusals keep their existing families. These are source symbols, never
observed property values. Existing read ordering, compound-read ordering and exact Environment/PATH bytes
remain unchanged; the preserved-input branch adds its finite typed reads. Backend/typing labels
do not establish the native cause; value mismatch grants no configuration repair
authority. Exact supported exception type and complete allowlisted combinations
are required; invalid metadata falls back to the existing family/coarse result.
Final empty-control diagnostics, legacy absent/coarse/family/root-control receipts,
and sticky close uncertainty retain their contracts, including no uncertain-close
retry. Source23 remains historically `old_kernel_initial_unit_properties` with
its inner cause UNKNOWN. This source-only change requires a newly matched image
for any separately authorized later operation; it grants no native retry,
installation, DEV-heavy, TEST or parent acceptance.

For the captured-empty PATH branch, `Unit_DropInPaths__selection` means the
original selector rejected the existing selection grammar. `shape` also covers
the original list/element representation checks; `unsupported` means the original
property read refused without a supported read classification. Transport,
decode and signature failures retain their existing kinds. No selected path,
entry count, property value or exception text is exported. The historical
`Unit_DropInPaths__value` spelling remains readable; Source25's recorded value
classification leaves its actual private cause UNKNOWN.

An initial OLD diagnostic uses the existing source-loader origins and executed-byte
hashes compared with the already computed verified-candidate manifest. This check
adds no native read and does not move the later full caller-source verification.
If that early binding is unavailable, the finite initial gate keeps its cause and
adds `__provenance_unavailable`; its source-specific attribution is unverified.
Missing or mismatched loader metadata and a missing candidate binding cannot claim
verified source provenance. Legacy diagnostics without the suffix remain readable
and do not retrospectively prove that this comparison ran. All later source,
resource-close, first-failure and effect gates remain mandatory. This source-only
support grants no native retry, installation or DEV/TEST acceptance.

Root/control refinements use the existing field, with the complete closed spelling
`old_kernel_<stage>_root_control__<mode>__<side>__<role>__<guard>`. Stage is
`initial` or `empty_control`. Mode is `captured_empty`, `anchored_discovery`, or
`unknown` before selection. Side is `old`, `proposed`, or `unknown` when no
launcher side applies. The OLD and proposed launchers use the **same typed unit
settings**. `old` names the currently read public launcher, not proof of loaded
OLD process bytes. Roles and guards below are source symbols, never paths or
observed values. Unsupported combinations retain the family/coarse fallback.

| Static role | Closed guards | Repair decision or remaining uncertainty |
| --- | --- | --- |
| `application`, `control`, `expected_empty` | `mapping_type`, `fields` | Repair the producer's projection shape; no filesystem cause is established. |
| Same projection roles | `path_type`, `path_absolute`, `path_canonical`, `path_backslash`, `path_nul` | Repair that exact path representation constraint at its producer, without disclosing the path. Canonical excludes empty, dot and parent components. |
| Same projection roles | `device_type`, `inode_type`, `uid_type`, `gid_type`, `mode_type` | Repair the named field's exact integer representation; booleans are refused. |
| Same projection roles | `device_range`, `inode_range` | Requalify the invalid nonnegative-device or positive-inode observation respectively; no identity value is exported. |
| Same projection roles | `uid`, `gid`, `mode` | Requalify the named owner/group/permitted-mode constraint separately. The label does not authorize changing permissions or ownership. |
| `roots` | `separation`, `fixed_subtree`, `empty_fixed_root` | Resolve application/control aliasing, control outside its fixed subtree, or captured-empty control away from its exact fixed root respectively. |
| `discovery` | `decode_unknown`, `environment_unknown`, `environment_files_unknown` | Unexpected initial launcher decoding, Environment construction, or EnvironmentFiles-path construction; mode has not been selected. Cause remains UNKNOWN. |
| `discovery` | `empty_decode_unknown`, `empty_environment_unknown`, `empty_environment_files_unknown`, `candidates_unknown`, `control_parts_unknown` | Unexpected operation at the named fixed construction site after mode selection. Diagnose that site under separate authority; no failed private predicate is guessed. |
| `hints` | `launcher_hint`, `environment_hint`, `environment_files_hint` | Captured-empty topology requires absence of a control-root reference in that exact source. No new hint format is accepted. |
| `hints` | `candidate_count` | Bound the anchored-discovery hint population before traversing it. |
| `fixed_origin`, `fixed_ancestor`, `fixed_root`, `candidate`, `anchor_app`, `anchor_ops`, `reopen_origin`, `reopen_ancestor`, `reopen_root` | `open_unknown`, `fstat_unknown`, `inheritable_unknown` | The no-follow open, descriptor metadata read, or inheritance query failed at this static directory role; exact native cause remains UNKNOWN. Reopen roles occur only in captured-empty mode. |
| Same directory roles | `directory_type`, `owner_pair`, `directory_mode`, `inheritable` | Requalify that role's directory type, accepted ownership pair, allowed mode, or noninheritable FD respectively. Ancestor/candidate descent permits the existing ancestor mode; fixed roots and loader directories retain their narrower modes. |
| `anchor_app`, `anchor_ops` | `stat_unknown`, `loader_symlink` | Unknown loader-slot stat, or explicitly rejected loader-directory symlink, for the named public package role. Missing/non-directory slots retain the intentional false return. |
| `anchor_file` | `stat_unknown`, `file_type`, `uid`, `gid`, `file_mode`, `link_count` | Unknown anchor-file stat or the exact regular-file/owner/group/exact-mode/single-link predicate to requalify. |
| `candidate_projection`, `fixed_projection`, `reopen_projection` | `fstat_unknown`, `directory_type`, `construction_unknown` | Unknown projection metadata read, non-directory projection, or unexpected projection construction. Fixed/reopen projections apply only to captured-empty mode. |
| `candidate` | `components_unknown`, `component_count`, `components_canonical`, `stat_unknown`, `symlink` | Unknown component construction, excessive component count, noncanonical component, unknown no-follow traversal stat, or explicit candidate symlink respectively. Missing tails/non-directory breaks remain accepted discovery behaviour. |
| `anchor_root` | `fstat_unknown`, `directory_mode` | Unknown selected-anchor metadata read or disallowed anchored-root mode, after its loader anchor passed. |
| `empty_root` | `identity`, `anchored_root_present`, `reopen_identity` | Requalify captured/current fixed-root identity, unexpected anchored topology, or final reopened/current identity respectively. These are different recovery decisions. |
| `app_slot`, `scripts_slot` | `stat_unknown`, `present` | Unknown no-follow slot stat, or a present slot that violates captured-empty inventory, distinguished by package. |
| `anchored_roots` | `no_anchor`, `multiple_anchors` | Restore one authenticated anchor, or resolve ambiguous distinct anchored identities. Exactly one remains successful. |
| `comparison` | `identity` | The discovered projection disagrees with the captured control projection for the named OLD/proposed side. Reconcile that side's topology and captured identity; matching launcher text is insufficient. |
| `revalidation` | `phase`, `empty_required`, `contract_missing`, `configuration` | Final prebackup revalidation requires qualified phase, captured-empty mode, the saved contract, and equality with the repeated configuration respectively, in that order. |
| `discovery_close` | `close_unknown` | At least one owned discovery descriptor close was uncertain. This **overrides an earlier guard**; every remaining owned close is still attempted once. It does not identify a filesystem defect or authorize retrying a close. |

Each attempt reports the first failed atom in the original short-circuit order,
except the existing close-uncertainty dominance. It does not discover later latent
violations or continue after refusal. Unknown operations name a fixed site only.
No additional filesystem/transport read, raw error, frame, input, identity, path,
argv, environment value or numeric owner/mode enters this receipt. The finite
consumer rejects unknown labels and refinements on non-prebackup statuses;
legacy absent-field, coarse and family receipts remain valid and immutable.

The public snapshot/manifest pipeline produces exact projection dictionaries and
canonical paths from authenticated roots and kernel integer metadata. Its earlier
no-follow root/identity/manifest guards refuse invalid owners, modes and
changed identities; lifecycle still refuses application/control aliasing. The typed bus and public launcher readers similarly exclude
malformed input/subclass behaviours before discovery. Final revalidation phase,
mode and saved-contract preconditions follow from successful qualification;
captured-empty discovery returns the already compared captured projection. Their
defensive guards remain present and have direct negative tests; synthetic tests
do not claim those shapes can arise from validated producers. The assembled
DEV/TEST source-RPC matrix retains actual snapshot/inventory/manifest, clean Git
checkout/launcher and finite receipt readers, substituting only external ports.

Historical Source20 retains its coarse unknown classification. Source21's
`old_kernel_initial_root_control` identifies only that family; its exact inner
predicate, native values and captured-empty/anchored mode remain UNKNOWN. These
new bytes cannot retroactively classify either result, replay a consumed attempt,
allocate Source22, or establish native readiness or DEV/TEST acceptance. The
canonical request still binds clean caller/Git candidate C to immutable image D
whose OCI revision is C; changed diagnostic bytes require a newly matched C/D
before any separately authorized native decision.


##### Planned retained PATH-input vector

The [selected target contract](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#planned-retained-path-input-vector)
was implemented and source-verified by [#6502](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6502):
at most four ordered, fully retained inputs in the existing PATH-only profile, with
identical decoded loaded PATH and one aggregate content budget. The heading retains
the selected target's existing anchor. Empty/singleton behavior remains compatible.
Production-path source proof covers the whole vector, all three descriptor-admission
branches and actual retained-count subtraction, generation/original-handle restoration
and sticky original-close uncertainty. Existing
value-free diagnostic and provenance rules remain mandatory. Actual native fit is
unknown. Exact-image delivery, native DEV/TEST qualification and parent acceptance
remain separate. Source delivery authorizes no observer, configuration change or
installation and does not close #6170, #5850 or #6207.

### #6300 fixed-selection reconciliation (historical, count-only)

The accepted V7 summary is the fixed selection of 651 items: 12 persisted, 544 missing, 95 invalid,
0 ambiguous, and 0 producer errors. Its qualified summary SHA-256 is
`72c7899ef09adb4151a4d78feb014e3bb612abe148f738a5670949d4dfa26360`. This is historical aggregate
evidence, not a new source read, current eligibility, source/deployment acceptance, or permission to
replay or broaden the selection. The [V7 receipt history](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6300#issuecomment-6330659322)
retains the exact receipt lineage. The [#3347 accepted V5 receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3347#issuecomment-6384608390)
leaves source/deployment eligibility unassessed, admits no DEV candidate, and sets the remaining
native-observation allowance to zero; this reconciliation does not change that boundary.

| Historical class | Count | Static disposition and bounded route |
|---|---:|---|
| Snapshot/parse | 55 | Unsupported unless checked-in code establishes a specific registered parser/owner class. The accepted split is 54 non-title mapping-value cases and 1 `ParserOther`; a title preview proves no semantic rewrite authority. |
| Malformed explicit UUID | 17 | Unsupported unless source, provenance, or companion identity authority was already established. Product/database identity alone never grants admission. |
| Companion `source_ref` conflict | 23 | Non-admitted until a separately authorized gate proves unique same-UUID, canonical-body-hash, and source-claim continuity. The inert proposal changes only the companion locator, content hash, and bounded history; source bytes, UUID, and unrelated companion fields remain unchanged. |
| Read-only-derived artifacts | 26 (25 historical, 1 current Daily Briefing) | Use only the registered composer’s identity-only migration, preserving the stored schema and section order through exact-version compare-and-swap with retained-original recovery. Generic registry repair refuses these; damaged, unreadable, unowned, profile-bound, or stale artifacts remain excluded. |
| Other missing cases | 518 (504 ordinary no-identity, 14 companion-absent) | Deferred while any unsupported or conflicting class remains; the fixed selection is ineligible. |

The previously exact-hash-reviewed inert proposal receipts remain unchanged: [supportable companion/composer proposals](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6300#issuecomment-6328572614),
[parser and identity refinement](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6300#issuecomment-6329905079),
and [static authority partition](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6300#issuecomment-6330819033).
They are repair design evidence only; no source or host predicate in this table is claimed to have
passed a live observation.

### Mimer voice sessions (VOICE-04)

`POST /api/ask/voice` returns a `session_id` when a question turn opens a transcript
on an initialized selected vault. Pass that id for follow-ups; `end_session=true`
closes the transcript and retires the live context. Context and pointers are
process-local: restart, another API worker, a changed vault/scope or an already
closed id returns `409 voice_session_context_lost`. Start a new session and
restate the missing context; the durable transcript is never replayed as live memory.

A process-local window on the actual shared vault manager keeps selection stable
through context lookup, ASK retrieval and transcript create/append/close. A
concurrent legacy select or lazy selection load waits for those effects; derived
TTS runs after release. This is not a persistent lease or cross-worker recovery.

Voice persistence uses the existing guarded `SessionLogWriter` only under
`.chats/voice/`, with per-turn UTC timestamps. It creates no human-note anchor,
UUID repair or `.canvas-sessions` pointer. Logging refusal/failure preserves the
grounded answer and reports `session_error: session_transcript_unavailable`,
independently of TTS degradation. Capture-intent suggestions perform no write.
See [the client contract](contracts/MIMER_CLIENT_CONTRACT.md#43-post-apiaskvoice)
and [the session owner spec](MIMER_VOICE_LOOP/CARRY_SESSION_FOLLOWUP_CONTEXT.md)
for semantics and production-path verification. These are repository contracts;
parent #3335 retains qualified TARS TEST voice/UI acceptance, and ERE
`chat.sessions` consumption remains planned.

### Heimdal raw-store capacity receipt

Use `python -m app.cli heimdal capacity --vault-root <vault>` to inspect an
aggregate-only capacity receipt for Heimdal's encrypted raw store. The command
reports counts and encrypted-byte totals for the first seven hot days,
archive-eligible records within the configured retention bound, and expired
records. It requires `_heimdal/settings.md` to declare a valid
`retention_window_days`; missing policy fails loud. It neither reads raw
payloads nor performs archive, retention, or storage lifecycle work.

### Heimdal time-spend projection (SCREEN-05)

Use `python -m app.cli heimdal time-spend [--week YYYY-Www]` to print the JSON
time-spend rollup over screen span observations (by app/project/scope/day/week),
and `python -m app.cli heimdal time-spend --rebuild --vault-root <vault>
[--week YYYY-Www]` to deterministically re-fold the observation stream from
event zero and (re)write the weekly markdown projection note(s) at
`heimdal/time-spend/YYYY-Www.md`. The note is a derived, rebuildable projection
(`requires_review`, never authority): rebuilding overwrites only its own prior
projection and refuses to touch any other note at the path. A missing store
backend fails loud (`STORE_BACKEND=memory` or a Postgres DSN is required).

### ERE screen-span ingestion (SCREEN-04)

The registry-driven Episode Resolution Engine tick consumes already-published
screen spans from Heimdal's observation log through its own modality-filtered,
monotone consumer cursor. Each admitted span becomes a normalized signal; the
`heimdal_gated` registry class describes the existing publish-side consent
gate. ERE registration does not start capture or grant consent, and the
adapter requires a nonempty grant reference without resolving or changing the
grant. On retry, exact scope/provenance already recorded by a validated
canonical Episode note or current open state is skipped before segmentation;
malformed canonical note evidence stops the tick before cursor advancement.
See `docs/EPISODE_RESOLUTION_ENGINE/README.md` for the owner contract.

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.
- App-version bumps and git tags are separate from stable-channel promotion. When moving the `stable`
  ref, rehearsing rollback, or validating prod after a promotion, use
  `docs/RELEASE_CHANNELS/README.md` plus `prepare-promotion`, `execute-promotion`,
  `verify-promotion`, and `rollback-promotion`. For the full operator acceptance procedure
  (preflight, smoke test, soak, rollback rehearsal, and receipt), use
  `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`. Treat release channels as an operator-governed
  capability with outstanding feature acceptance, not as a fully accepted baseline workflow.

  Normal production promotion uses protected `stable` authority (#6228): the exact current green
  TEST source C and immutable image D, a signed functional PASS, and explicit approval of the
  concrete plan. `make deploy-prod SHA=<C> IMAGE_DIGEST=<D> PROMOTION_PLAN=<absolute-path>` and the
  native host adapter enforce admission before effects. Protected merge M is authority evidence;
  the running version remains C/D. The operator's read context must supply full required stable
  protection and Actions evidence on the execution host; controller credentials do not imply
  those production permissions. Ordinary restart and governed previous-good rollback retain their
  contracts. Repository support establishes no running-prod or cutover observation.

### Read-only ordinary-boot doctor (STARTUP-03)

Run `python -m app.release_channels.ordinary_boot doctor --help` for the explicit manifest,
Compose, observed-dependency, operation-id, and terminal-journal inputs. The doctor resolves one
exact prod promotion-mode manifest and emits `ORDINARY_BOOT_PASS` only when every required
dependency is compatible; a declared optional LLM may instead remain visibly
`degraded_unavailable`. A missing or incompatible required dependency emits
`PRE_MUTATION_FAILURE` with `writers_permitted=false`. Manifest and dependency snapshots are JSON;
Compose is read through the canonical YAML model (JSON is also accepted). With a valid operation
handle and journal target, a missing, malformed, or unreadable input still emits exactly one durable
`PRE_MUTATION_FAILURE` rather than returning without a terminal row.

The command writes only its terminal journal. It does not pull or build an image, migrate schema,
change a pin, bootstrap BuilderOps, provision Ollama, ingest or index data, restructure a vault,
activate a channel, or start a writer. An identical operation-id replay must reproduce the same
result and re-establish file plus directory durability; a changed derived terminal result or corrupt
journal state fails closed. Use a generated opaque non-secret operation id in the
`ob-<32 lowercase hex characters>` format and an absolute `.jsonl` journal path under a real,
same-user-owned parent that is not group- or world-writable. That parent is the checked trust
boundary; symlink, hardlink, FIFO, and named-path replacement targets are refused. This is
compatibility evidence for a separate caller, not permission to skip the canonical prod startup,
promotion, activation, or live-host acceptance workflows.

### Forward-only migration floor: `objects` binding key (MVR-05A1, #4560)

Alembic revision `d1e8a0c5f37b` takes ownership of `objects` and `agent_memories`, changes the
`objects` primary key from `(id)` to `(vault_binding_id, id)`, and scopes `objects_uuid_idx` to
`UNIQUE (vault_binding_id, uuid)`. The same change **deletes** `app/db/migrations_obsidian.sql` and
`scripts/run_migration.py`. Operator consequences:

- **A stale database is now refused at startup, not silently reshaped.** The vault-sync seam runs
  `app/db/db.py::assert_objects_schema` alongside the existing `file_state` preflight, so a database
  that never ran `alembic upgrade head` fails with a message naming that command instead of an
  opaque `UndefinedColumn` part-way through a watcher tick. Before #4560 the runtime bootstrap
  reshaped `objects` on every process boot, which is why the stale state used to be survivable.
- **Migration authority is unchanged and is now the only authority.** `scripts/run_migrations.sh`
  (`alembic upgrade head`) applies it, and the compose `migrate` one-shot still gates every runtime
  container. What changed is that application processes no longer issue any schema statements at
  startup: before #4560 the first `conn_rw()` of every process replayed the bootstrap SQL, which
  dropped and re-added `objects_pkey` unconditionally. Existing rows in both tables are adopted in
  place and attributed to the `legacy-compatibility-binding` sentinel; nothing is recreated, moved,
  or dropped.
- **The migration refuses rather than repairs three states.** It stops with an explicit hint if an
  inbound foreign key still references `objects` (run the #3510 cutover first), if the database
  holds duplicate `(vault_binding_id, uuid)` rows (reconcile them first — `app/objects/identity.py`
  already refuses to resolve a duplicated `objects.uuid`), or if a single-column unique index on
  `uuid` or on `id` survives under some other name (drop it with `DROP INDEX`, or
  `ALTER TABLE public.objects DROP CONSTRAINT` if it backs a constraint — either one re-imposes the
  exact constraint the rekey removes). All three refusals are atomic and leave every row untouched.
- **The revision is forward-only** per `docs/RELEASE_CHANNELS/README.md :: Rollback posture`. Rolling
  the `stable` ref back to a pre-#4560 image has two possible outcomes, both measured:
  - on a **single-binding** database the old image starts and its startup bootstrap **silently
    restores `PRIMARY KEY (id)`**. Rows survive, and `objects_uuid_idx` stays binding-scoped because
    `CREATE UNIQUE INDEX IF NOT EXISTS` matches on name — which means the old image's
    `on conflict (uuid)` upsert fallback raises `InvalidColumnReference`. Its primary
    `on conflict (id)` path works again once the key is restored, so vault-sync ingest continues.
    Re-run `alembic upgrade head` on a post-#4560 image before creating a second vault binding.
  - on a database that already holds **two bindings for one artifact UUID** the old image cannot
    start: `conn_rw()` raises `UniqueViolation: could not create unique index "objects_pkey"` and
    the schema is left untouched. Roll forward rather than back.

### Forward-only migration floor: `file_state` binding key (MVR-05A0, #4543)

Alembic revision `c7f4b1a83d29` takes ownership of the vault-sync `file_state` table (previously
created at runtime by the legacy bootstrap SQL, deleted by #4560) and changes its primary key from
`path` to `(vault_binding_id, path)`. Operator consequences:

- **Migration authority is unchanged.** `scripts/run_migrations.sh` (`alembic upgrade head`) applies
  it. Existing rows are adopted in place and attributed to the `legacy-compatibility-binding`
  sentinel; nothing is recreated, moved, or dropped.
- **The revision is forward-only** per `docs/RELEASE_CHANNELS/README.md :: Rollback posture`. Rolling
  the `stable` ref back to a pre-#4543 image leaves the database on the new key. That image's
  `file_state` **upserts** then fail loudly — `ON CONFLICT (path)` has no unique index on `path`
  alone to match, so Postgres raises `InvalidColumnReference`. Its reads and its path/uuid deletes
  still execute and stay correct while only one binding exists, which is the only state a rolled-back
  image can be in. Expect vault-sync **ingest to stop loudly**, not to corrupt. Roll forward rather
  than back.
- The constraint rebuild takes a brief `ACCESS EXCLUSIVE` lock on `file_state`. Apply it through the
  normal `migrate` one-shot, which runtime containers already gate on, rather than against a live
  writer.
- **`FileStateSchemaMissingError` means the migration has not run.** A vault-sync producer refuses
  to touch the table when it is absent, still carries the old `path`-only key, or has a stray unique
  index on `path` alone. It fails *before* any effect, so no partial write is left behind — run
  `scripts/run_migrations.sh` and restart. The adapter and API paths propagate the error with its
  `alembic upgrade head` hint intact; the watcher's deletion-reconciliation path
  (`app/watcher/vault_watcher.py`) catches broad exceptions and reports only
  `Warning: unable to reconcile deletion for <path>` plus an incremented error count, so on that path
  check the schema explicitly rather than expecting the hint.
- Schema truth for the table is `docs/DB_SCHEMA.md :: file_state`.

## Runtime prerequisites (registry watcher)
- `DATABASE_URL` or `DB_DSN` is required in runtime; startup must fail fast if missing.
- DB outbox is canonical in runtime; the worker consumes the DB outbox.
- JSONL outbox (`INDEX_OUTBOX_PATH`) is audit/diagnostic only and must not be used as the worker queue.
- Registry watcher is the single runtime watcher (`configs/watchers.yaml` + `python -m app.cli watcher run`). Legacy snapshot watchers are dev-only.

The operations playbook follows the [RSC-01 continuity classification](REBUILDABLE_SYSTEM_CONTINUITY/README.md#rsc-01-continuity-classification).
Retained human artifacts, companions, and document-backed governance receipts remain continuity
authority; machine mirrors are rebuildable; operational journals, leases, ownership records, and
fences are safety state. Diagnostic JSONL/dumps and optional backups are evidence/ergonomics only:
they are never the worker queue, readiness, semantic authority, or a mandatory restore proof. If
operational lineage is missing, the supported target posture is a new fenced bootstrap epoch with
writers inactive until owner-native readback and convergence. Total-loss recovery is not claimed as
shipped runtime capability here.

Companion continuity files in the configured `<system_folder>/companions/` and legacy
`_system/companions/` locations are excluded from source publication and deletion effects by the
registry, retained snapshot/targeted ingest paths, and queued worker consumers. Restore a
companion-contaminated citation locator by reingesting its genuine source in the same bound vault;
retain the companion files. The [companion owner contract](CONCEPTS/COMPANION_NOTE_CONTRACT.md#location-convention)
defines the boundary and recovery behavior. This is repository behavior, not a live-channel
deployment or verification receipt.

For a retained DEV v1 ownership record whose old container ancestor inode chain is unavailable,
operators can use the explicit, stopped-window [DEV legacy-owner re-attestation](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#explicit-dev-legacy-owner-re-attestation)
command. It requires a fresh authority decision and verified private recovery evidence; normal
startup remains fail-closed and activation remains a separate deployment step. Missing or
inconsistent registry backup artifacts are refused without being repaired during admission.

For a retained populated dormant TEST registry with both protected ownership artifacts absent,
the explicit [TEST dormant ownership preparation](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#explicit-test-dormant-ownership-preparation)
seam requires a separately acknowledged new epoch and a qualified native stopped window. It leaves
the registry dormant and writers fenced; ordinary startup still refuses the missing pair. Repository
support and isolated fixtures do not authorize a live invocation, B47 retry or activation.

## Environment posture

This document is primarily the `prod` operator entrypoint.

Environment contract:
- `dev`, `test`, and `prod` are defined in `docs/ENVIRONMENTS.md`.
- Production operation means the runtime is acting against the operator's real vault and its production-facing runtime surfaces.
- The local `test` bootstrap path is the isolated verification posture, not production operation.
- Lab/dev-only flows, fixture vaults, legacy watcher paths, and reset-heavy workflows are not production operation even when they use the same codebase.

Operator rule:
- if a task depends on looser safety assumptions, mock providers, fixture stores, or lab-only tuning, treat it as `dev`
- if a task touches the real vault, production stores, or normal runtime startup/verification surfaces, treat it as `prod`

Current runtime path:
1. The registry watcher scans the vault, emits DB outbox events, and appends `watcher.run` audit rows so status can count runtime ticks.
2. The worker consumes DB outbox rows and performs ingest/index, panel scan, and promotion work, preserving bounded retries for transient missing or unstable notes before giving up.
3. Health, status, and metrics confirm whether that path is healthy.

## Heimdal screen derivation: host-local model precondition

The screen derivation stage (`app/heimdal/screen_derivation.py`, SCREEN-02) refuses to send a raw
screen frame to any endpoint it cannot prove is inside this host's trust boundary (HEIM-12: zero
raw-class egress). Two operator-visible consequences:

- **Endpoint.** The stage reads `OLLAMA_BASE_URL` / `OLLAMA_HOST` / `OLLAMA_URL` and accepts only a
  loopback address, or a hostname listed in `HEIMDAL_SCREEN_VISION_HOST_LOCAL_HOSTS`. A
  container-network service name is not loopback, so the compose stack declares it explicitly
  (`docker-compose.prod.yml` sets `HEIMDAL_SCREEN_VISION_HOST_LOCAL_HOSTS: ollama`). Setting that
  variable is an operator assertion that the named host really is inside this machine's boundary.
  Without it the stage refuses loudly rather than degrading — that refusal is the feature.
- **Model.** The route resolves to the census-declared local vision model `ollama/llava:7b`
  (`docs/settings/models/providers.yaml`). `scripts/cold_boot.sh` does **not** pull it, so the first
  derivation run on a fresh host fails loud until `ollama pull llava:7b` has run.

The stage has no tick driver yet (SCREEN-06 owns the control surface), so neither precondition
affects the current runtime path until a caller exists.

## Canonical Local Test Bootstrap

The repo-supported local runtime verification path is the local `test` bootstrap golden path.

Use this path when you need a clean-state, repeatable verification run rather than flexible `dev` exploration:

1. reset runtime state
2. initialize a clean test vault
3. seed the UAT notes
4. start the local stack against that vault
5. verify health/status
6. run scripted UAT

Canonical command:

```bash
make test-bootstrap
```

Expanded command path:

```bash
make test-vault-init
VAULT_ROOT="$(pwd)/vault-test" scripts/start_full_system.sh
VAULT_ROOT="$(pwd)/vault-test" bash scripts/verify_runtime_stack.sh
VAULT_ROOT="$(pwd)/vault-test" python -m app.cli uat-run-vault-test --vault-root "$(pwd)/vault-test" --assert
```

Operational intent:
- this is the intended repo-supported path for local runtime verification
- `dev` remains the flexible local environment for exploration and debugging
- `test` is the isolated verification environment that should be resettable and reproducible
- the bootstrap path is itself part of the productized verification contract, not just setup glue
- startup, deterministic `make verify-runtime`, and scripted UAT/idempotence slices are shipped, so treat this path as the supported local verification lane while broader bootstrap hardening stays bounded to explicit follow-up slices

TEST startup has two fail-closed Compose modes. With no selected vault, the universal TEST overlay
keeps the watcher disabled and its vault path empty. With an explicit TEST vault, startup composes
the selected-vault mount and then the TEST-only activation overlay, which binds the watcher to the
same in-container `/app/vault` target regardless of inherited parent-shell watcher values.

Fresh TEST bootstrap also supplies `LLM_PROVIDER=mock` when no explicit
`TEST_LLM_PROVIDER` is configured. Before the MVR-05 instance-state deployment fence runs,
`scripts/start_full_system.sh` starts only the `db` service and waits for its in-container
`pg_isready` probe; a failed start or readiness timeout records a fail-closed startup reason and
does not enter the fence. The fence and the later runtime startup remain unchanged after that
precondition. Its bind-mounted quiescence and owner-inventory readers tolerate only a bounded
visibility window for transiently truncated host projections, and a fresh registry may be
materialized only from the authenticated owner receipt and matching ownership-ledger state.
For an established schema-v1 ledger with retired bindings, MVR-05 admission also requires
host-captured identity evidence for each retired root, correlated to the channel registry's
tombstone or transfer lineage. A missing or replaced retired root blocks admission before ledger or
registry changes; see the deployment procedure for the full proof and retry behavior.

Use `docs/runbooks/UAT_PANEL_WATCHER.md` for the detailed walkthrough and `docs/runbooks/RUNBOOK_RESET_TO_ZERO.md` when you need the full reset semantics.

When the issue is startup topology or Compose wiring, switch to `docs/INFRASTRUCTURE.md`.
When the issue is signal interpretation, switch to `docs/OBSERVABILITY.md`.
When the issue is health semantics or degraded-state rules, switch to `docs/HEALTH.md`.

For the nightly `k6-search` validation producer, use the disposable PG16/pgvector database,
canonical migrations, assert-only bootstrap and generated binding-aware fixture described in
[`DEV_WORKFLOW.md :: CI / validation expectations`](development/DEV_WORKFLOW.md#ci--validation-expectations).
Its local equivalent requires an isolated localhost API and the real seeded-result warm-up before
the five-VU, ten-second load run; status, result, error and p95 latency thresholds must all pass.

## ASK provenance shadow operations

The ASK provenance manifest is an opt-in read-side experiment, not a canonical
audit store. It is disabled unless `ASK_PROVENANCE_MANIFEST_ENABLED=1` and a
local `ASK_PROVENANCE_PRIVACY_KEY` is present. Its JSONL file must remain below
the fixed repo-local `runtime/agent_memory` root; resolved path/root symlinks
and escapes fail closed, so it cannot be relocated into a vault or index
surface.

Enabled capture is dispatched after the answer through a bounded queue to one
daemon worker. File locks, atomic replacement, retention, and fsync therefore
do not extend ASK response latency or create unbounded worker threads. Records
expire after 14 days, are capped at 256 entries, and startup pruning plus an
hourly per-path janitor removes expired records even if no later ASK occurs. An
expired, malformed, inaccessible, or identity-incomplete record is not
comparable and must yield `indeterminate`. Capture/janitor failure is logged
locally and never changes the ASK response or authorizes a write.

## Watcher Operations

Use this section only when the issue is specifically about watcher deployment, config, or execution mode.

### Watcher entrypoint classification

Entrypoints are explicitly classified by environment per `docs/ENVIRONMENTS.md`:

**Production-facing entrypoint:**
- `python -m app.cli watcher run` — canonical production registry watcher (prod/dev)
  - Multi-spec watcher registry loop, artifact path and state separation by environment
  - Supports both `prod` and `dev` environments via `PKM_ENVIRONMENT` or profile-based inference
  - This is the entrypoint for the current production baseline

**Dev-only legacy entrypoints (require `PKM_ENVIRONMENT=dev` or `PKM_SETTINGS_PROFILE=lab`):**
- `python -m app.cli vault-watcher-run` — single-shot snapshot watcher (historical implementation)
- `python -m app.cli vault-watcher-daemon` — snapshot daemon (historical implementation)
- `python -m app.cli runtime-loop` — watcher → panel → promotion loop (historical test path)

The legacy entrypoints are retained for lab/dev workflows but should not be used for production operation. Use `watcher run` for all production-facing and standard dev runtimes.

Watcher auto-exec enablement rule:
- Treat `python -m app.cli settings-explain` plus `python -m app.cli status` as the canonical enablement check.
- `WATCHER_AUTO_EXEC=1` is necessary to arm panel auto-exec, but it is not sufficient on its own to prove rollout safety.
- Before enabling auto-exec for a wider runtime scope, confirm the effective allowlist, recent skip counters, and write-guard/provenance context are coherent across both CLI surfaces.
- When the question is release or merge readiness rather than a live local diagnosis, corroborate the operator view with the enforced CI summary line (`CI SUMMARY GATES ok=<bool>`).
- `python -m app.cli settings-validate` is the schema validation gate for repo-shipped panel action catalog/wiring and watcher settings. It rejects invalid panel action ids, missing required panel fields, malformed watcher `auto_run` values, and unknown watcher allowlist action ids.
- The same governed seam now covers watcher-detected `settings/local.md` deltas for runtime-gating keys, so direct value edits to `enableVaultWatcher` / `enableAutoIndexing` emit `SettingsWriteReceipt`s, and deleting either key from frontmatter emits the same governed file-surface receipt without reintroducing the key (#2512). The registry keeps `settings/local.md` state shared across watcher specs, so a single human edit still yields one receipt per changed runtime-gating setting.
- This validation path does not widen runtime authority: watcher auto-exec remains guarded by `WATCHER_AUTO_EXEC`, allowlist policy, and per-note `ai_panel_auto_run: never` opt-out.
- Sync-latency measurement mode is operator-scoped: keep `vault/@Settings/watchers.md` allowlist at default (`promote.evergreen`) and run harness/measurement sessions with `WATCHER_MEASUREMENT_MODE=1`. This temporarily appends `ingest.summary.create` during the run and returns to the default posture after the process exits.

### Docker-first deployment
1. Set `VAULT_ROOT` to your local vault path:
   `export VAULT_ROOT="/Users/you/PKM - Alpha"`
2. On macOS/iCloud-backed vaults, set container UID/GID mapping so watcher and worker can write UUID heals back into the vault:
   - `export LOCAL_UID=$(id -u)`
   - `export LOCAL_GID=$(id -g)`
   - recreate services after changes: `docker compose up -d --force-recreate watcher worker api`
3. Start the watcher service:
   ```bash
   docker compose up -d watcher
   ```
4. Follow logs:
   ```bash
   docker compose logs -f watcher
   ```

### Host fallback
- Run the registry watcher directly:
  ```bash
  WATCHER_ENABLE=1 WATCHER_VAULT_PATH="/path/to/vault" python -m app.cli watcher run
  ```
- Single-tick safety run:
  ```bash
  python -m app.cli watcher run --max-ticks 1
  ```
- The legacy snapshot watcher remains lab-only and is not part of runtime/start-system flows. Do not use it for current runtime operation.

### Key watcher env and defaults
- `WATCHER_ENABLE=1` arms the registry watcher.
- `WATCHER_VAULT_PATH` points at the vault root.
- `WATCHER_SCOPE_GLOB` overrides scan scope (default `**/*.md`).
- `VAULT_INBOX_DIR_REL` overrides inbox folder behavior when needed.
- `WATCHER_STATE_DIR` stores registry watcher state.
- `WATCHER_HEARTBEAT_PATH` and `WATCHER_TICK_LOG_PATH` control watcher health/tick outputs.
- `WATCHER_AUTO_EXEC=1` arms panel auto-exec; per-note opt-out remains `ai_panel_auto_run: never`.
- `PANEL_PROACTIVE_ASSIST=0|1` controls proactive panel creation.
- `WATCHER_STOP_FILE` pauses scanning when present.
- `WATCHER_MAX_SCANNED_FILES_PER_TICK`, `WATCHER_MAX_BYTES_READ_PER_TICK`, and `WATCHER_MAX_ELAPSED_MS_PER_TICK` bound each registry tick. A boundary reports `catch-up` and resumes from the durable deterministic cursor on the next tick; do not raise these limits merely to fit a large vault into one tick.
- Registry checkpoint JSON stays bounded to cursor/counter metadata. Per-file observations are stored in an adjacent SQLite sidecar under `WATCHER_STATE_DIR`; deletion reconciliation and stale observation pruning run only after a clean full scan generation drains.

### Watcher caveats
- No-vault startup stops the existing watcher before recording `no_lifecycle` and fails without acknowledgement if stop fails. Traversal errors prevent rebind acknowledgement; a durable `drained` receipt remains non-terminal until a fresh resumed old-root scan succeeds and its observations are receipted.
- The registry watcher remains polling-based; each observation generation walks the configured scope incrementally across bounded ticks. No OS file-event hooks are used.
- Paths with spaces are supported; wrap vault paths in quotes.
- When using iCloud/Obsidian sync, keep scopes conservative and rely on debounce/backoff guardrails.
- Do not use the legacy snapshot watcher for runtime start-system flows.
- Do not treat lab/dev-only watcher paths as production equivalents.

## Obsidian sync runtime

Current runtime model:
- Obsidian vault changes flow through the registry watcher into ingest/update events, then into the DB outbox and worker/indexer path
- runtime-side note writes must stay narrow: agreed frontmatter updates, AI panel mutations, inbox/log artifacts, and explicit maintenance writes
- `app/knowledge/write_ops.py` is the shared vault-write boundary for runtime/services; deeper transport details stay behind the knowledge-port abstractions

Operational rules:
- never treat note body rewrites as a normal sync action
- rename or move events should update canonical path state without forcing re-embedding when body content is unchanged
- delete propagation should emit explicit delete semantics only when the removed path was the UUID's last active file-state reference
- settings hot-reload should apply policy changes without restart, while invalid settings payloads should fail closed and preserve the previous active policy

Companion docs:
- `docs/HUMAN-FLOWS.md` for human-facing vault behavior constraints
- `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` for the note-write abstraction and adapter contract
- `docs/runbooks/UAT_PANEL_WATCHER.md` for a watcher/panel walkthrough

## Runtime Compose Stack

The separate BuilderOps component window #6347 (status 2026-10-26) qualified bob-1 monitoring and
retired only the old Mac `builderops-control-plane` API/worker/DB containers. Their restart
policies are disabled and original PostgreSQL volume/history retained, including the failed
old PR #5350 distinction. No import/replay or unrelated helper lifecycle change occurred; see
the [runtime receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6347#issuecomment-6405523126). The app runtime stack below retains its own lifecycle.

- Canonical runtime compose stack: `db`, `api`, `watcher`, `worker`.
- `docker-compose.yaml` starts FastAPI (`api`), `worker`, `watcher`, and Postgres for local development.
- Ensure `.env` contains the desired secrets before running `docker compose up --build`.
- Postgres data lives in the `postgres-data` volume; `docker compose down -v` wipes it.
- The API container runs `scripts/start_api.sh` (migrations + `uvicorn`).
- The worker runs `python -m app.workers.outbox_worker` (consumes DB outbox).
- The watcher runs `python -m app.cli watcher run` (registry loop; emits `ingest.vault.changed` / `panel.scan.requested` DB outbox events and appends `watcher.run` audit rows to the JSONL event log).
- Governed channel deploys run the `migrate` service as an explicit one-shot step before recreating
  long-lived services. When HAR-02's legacy raw-evidence backfill is present, that exact invocation
  is wrapped with the declared `heimdal-raw-migrate` consumer from the existing shared raw-store-key
  domain. The trusted migration receipt selects this gate only for HAR-02's exact revision; unrelated
  inventories perform no raw-key lookup. A value-free resolution preflight runs after migration
  inventory/dry-run but before deploy mutation; the exact one-shot wrapper resolves again immediately
  before Alembic and delivers only a temporary migrate-specific handle. An absent key is allowed for
  this consumer so HAR-02 can decide under its source-table lock: an empty table needs no key, while
  rows without a valid key roll back the migration before legacy schema or bytes change. Present
  malformed or domain-divergent material still fails before migration, and configured capture-watch
  continues to require the key. Diagnostics remain value-free. This wiring does not create, rotate,
  read back, or otherwise mutate host secret material.
- The repository's Linux BWS deploy path keeps its systemd supervisor root-owned for BWS and Docker
  control while host-global instance-ownership state stays owned by the configured runtime UID/GID;
  see [Deployment and environments](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#root-owned-image-bake-vs-host-uid-remapped-runtime-user-2991-3047)
  for the canonical path, ownership, and receipt contract.
- Native Linux BWS activation runs a fixed source-only API one-shot after migrations and before
  normal service recreation, using the existing source-backed producer in the same target,
  selected vault, PostgreSQL credentials delivered through files and transient API consumer
  context. The selected API command validates the PostgreSQL backend through the `app.objects`
  backend facade before its API migration step without constructing a StorePort; StorePort
  resolution waits until a selected vault root needs Product readiness, and an absent root stays
  idle without StorePort construction or a SourceAction. Normal producers stay stopped; an
  already-ready Product avoids full replay. Strict source counters, fresh Product
  readiness and strict vector/index diagnosis remain required. Only proven owned-producer
  quiescence permits compensation or terminal same-ID reconciliation. See the [Deploy procedure](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#deploy-procedure)
  for candidate-image support, bounded waiting and pending-state limits. Issue #5918's executable
  repository tests establish this support; live channel qualification remains separate.
- Before migration writer drain, Linux BWS deploy resolves the target image's selected Product
  embedding identity. If Ollama is selected, it prepares that exact channel model and probes the
  Product embedding client with fixed non-vault text; failure occurs before normal app-service stop
  and follows the documented pin/marker compensation path. Repository tests establish this support;
  live channel qualification remains separate. See the [Deploy procedure](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#deploy-procedure)
  for the exact sequence.
- If an existing-secrets-only Linux BWS deployment remains pending after worker loss, first use
  its exact plan and ID with the same-ID terminal recovery procedure in [Deployment and
  environments](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#linux-channel-secret-provisioning). If
  its terminal result is absent and the current channel ID differs, the mismatch proves no ordering
  or outcome. The narrow DEV/TEST unknown-fence path requires the original plan, existing host and
  channel locks, ended worker/thread, quiescent owned one-offs, and a durable exact-ID replay fence.
  Its host projection stays `unknown`; it is not deployment acceptance, success, failure, rollback,
  or proof of no effects. If any predicate is missing, leave the host operation pending and report
  its value-free `missing_predicate`. The change does not install or restart the VM supervisor; a
  live call requires the approved source-installation path to load this implementation first. A
  later deployment is a separate new operation and retains the regular candidate, migration,
  backup, and health gates.
- Explicit manual nonprod MVR-01C authority cutover uses the immutable native request described in
  [Multi-vault instance-state rollout boundary](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#multi-vault-instance-state-rollout-boundary).
  Supply the already-qualified binding/source/ownership-state inputs under the existing mandate;
  unresolved ownership state refuses without repair. This route has no automatic or PROD cutover.
  Interrupted authority cutover retains its request and admission lock as pending: service health
  or quiescence cannot establish terminal completion or authorize same-ID failed reconciliation.
- Physical automatic and explicit previous-good recreation retains existing valid Model Access
  path references through the four-key allowlist. Missing or invalid optional input keeps legacy
  empty bindings; see [Rollback posture](RELEASE_CHANNELS/README.md#rollback-posture) for the
  configuration and modern-caller limits.
- A failed supervised deploy child reports only an allowlisted advisory gate stage and the finite
  class defined in the [Deploy procedure](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#deploy-procedure)
  directly to the existing native journal socket, retaining `unknown`/`command_failed` for absent
  or ambiguous markers. One nonblocking datagram carries only the finite message and fixed priority
  and identifier; both raw service streams remain null. An unavailable or full socket loses only
  the advisory diagnostic. This diagnostic does not establish a terminal result or live
  channel acceptance; use the same-ID reconciliation procedure above.
- Before a Linux BWS deployment, operator setup must qualify the complete isolated host runtime,
  including Python helpers, Chromium headless payload, exact browser-smoke collection and tuning
  imports. Follow [Linux channel secret provisioning](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#linux-channel-secret-provisioning)
  for the setup/runtime binding and infrastructure-owned OS prerequisites. The offline collection
  preflight accepts exit 0 or exit 5 with its intentional `SKIPPED` marker, checking captured output
  without a short-circuiting pipe; missing-marker and other-error outcomes still refuse setup.
  Repository regression checks cover this classification without establishing live host or channel
  qualification. Missing dependencies or an unavailable browser refuse setup before launcher
  replacement; application-image selection,
  credential/grant and migration authority remain with their existing operator gates.
- Fixed native `qualify-web` uses an already committed dev/test operation/image and its exact
  native lock/resource admission. Disposable baked API/UI services bootstrap canonical sources
  and the memory queue in the actual API process, then run Daily8 before Deep13 with the original
  reports, finite effects and guarded source/version lineage. Existing PG and long-lived channel
  health evidence remain separate. Missing wrappers or unqualified browser, local voice, model or
  source prerequisites yield attributable refusal; repository checks provide code evidence while
  actual parent scenario qualification remains pending. Follow the fixed invocation and cleanup
  contract in [Build-once / promote model](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#build-once--promote-model)
  and [Automated Technical Acceptance](TESTING.md#automated-technical-acceptance).
- Fixed TEST-only `qualify-journaling test <committed-operation-uuid>` independently consumes the
  shipped Conversational Journaling journey from the exact admitted image, canonical disposable
  sources and original Product provider. Its `native-journaling.v1` evidence cannot replace
  Daily/Deep, PG or long-lived channel health. Exact owned relay/resource cleanup and atomic
  no-overwrite evidence are required; unknown cleanup preserves same-operation admission.
  The shared lock binds its fixed qualifier profile; cross-profile or generic recovery cannot
  retire unknown cleanup. Retry the owning qualifier, not the other journey.
  Follow the same linked deployment/testing contracts above. Repository delivery of #6050 is
  not actual TEST PASS or parent #3347 acceptance.
- Fixed `qualify-heavy dev <committed-operation-uuid>` (admitted by the installed launcher's action allowlist from #6205) runs the post-merge heavy test targets
  (`postmerge-heavy.v1`, #6158) for the committed DEV candidate. The repository controller (#6227)
  calls it after native DEV/PG acceptance and dispatches the bounded verdict to
  `post-merge-heavy-tests.yml`. Only a passing exact DEV verdict permits TEST promotion. Red candidates
  are held without replay while later builds continue; interrupted heavy runs and uncertain dispatches
  are not replayed on restart. It takes no channel lock, and its operation-owned container and work tree
  are removed after every completed run. Legacy TEST receipts remain readable. Manual qualification
  does not grant controller promotion authority. Live activation stays #6170/#3347. See
  [Post-merge heavy tests](development/TEST_STRATEGY_HOT_PATH.md#post-merge-heavy-tests).
- DEV/TEST heavy and native PG acceptance support an optional verified container memory policy.
  With no policy, they run without these memory caps and report that isolation is inactive. Choose
  values only after coordinated measurement; see the [deployment policy contract](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#ci-deployment-automation-posture-1).
- GitHub-visible DEV delivery liveness (#6222) runs in `dev-delivery-liveness.yml` on a schedule.
  Inspect the checker JSON `reason` and its signal workflow runs: the default missed-progress
  deadline is six hours, and the controller activity window is two hours. A fresh terminal DEV
  verdict records activity even when deployment failed; later progress retires skipped older builds.
  The [CI deployment automation posture](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#ci-deployment-automation-posture-1)
  owns the signal admission and recovery limits. Repository proof does not release the controller
  or establish live channel acceptance; those operator gates remain with #6170 and #3347.
- Native dev/test rolling channel-bug repository support (#6223) follows the
  [CI deployment automation posture](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#ci-deployment-automation-posture-1).
  Its main-only Actions writer opens or updates red bugs and closes them on later green evidence,
  while subsequent candidates continue. Live activation and channel qualification remain with #6170/#3347.
- Green channel-ref repository support (#6226) uses the existing trusted-main verdict workflow's
  separate ref job. It advances only `dev`/`test` by non-force fast-forward; test requires an exact
  retained dev-green receipt. A linked owner Issue pins dev after the workflow confirms `held`,
  while later candidates and deployments continue. Follow the
  [deployment owner's hold format, activation readback and workflow-rerun recovery](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#ci-deployment-automation-posture-1).
  The host client keeps Contents read. Repository proof does not activate the host or move live refs;
  #6170/#3347 retain those operator gates.
- Pinned post-merge controller tooling (#6225) is installed as a reviewed-SHA source snapshot and
  private isolated Python runtime under the existing postmerge state directory. The LaunchAgent uses
  isolated Python startup and a fixed pin; neither its imports nor the native host child imports use
  a candidate checkout or ambient Python configuration. Startup checks the runtime identity and real
  controller/native imports and unauthenticated SDK construction before polling. The SDK closure
  reuses the existing BWS manifest pins and is copied and hashed inside the installation. A failed
  check exits 78 and snapshots existing checkpoint order without changing it before dispatching a
  failed heartbeat. A fresh DEV verdict cannot mask that failure; later actual controller activity
  supersedes it, with active-pause and expiry behavior preserved. Invalid checkpoint state, clock admission
  refusal or unavailable transport uses the bounded log and scheduled missing/stale-heartbeat path. Select a fresh reviewed tooling SHA to
  upgrade or recover a broken pin; candidate deployment never refreshes it. Follow the linked deployment
  posture for installation. Repository support does not activate the host (#6170) or accept a
  release (#3347).
- Controller pause repository support (#6224) uses the existing private checkpoint and lock. Only an
  explicit linked-Issue pause with a future expiry is supported; the liveness check reports
  `paused (#N, until T)` and work resumes automatically at expiry. Follow the
  [deployment owner's command and authority](deployment/DEPLOYMENT_AND_ENVIRONMENTS.md#ci-deployment-automation-posture).
  Keep the LaunchAgent loaded; live host changes require owner OK on #6224, and existing #6170/#3347
  activation/qualification gates remain.
- Legacy dev stacks may include agent/redis containers; they are not part of the runtime start-system path.
- `scripts/start_full_system.sh` is the supported startup wrapper. It now auto-probes Ollama reachability from inside the containerized runtime and persists the selected Docker-reachable endpoint into `tmp/runtime.env` before declaring startup healthy.
- Local Colima startup verifies its explicit resource profile, context/socket binding, persistent
  substrate, containerd readiness and exact durable container inventory before BuilderOps helpers,
  flight recording or Compose can run. Disk refusal still runs first. Use the
  [Colima startup procedure](runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md#colima-persistent-substrate-readiness)
  for installation, cold-start authorization and recovery; Product channels retain their TARS placement.
- When `LLM_PROVIDER=ollama`, startup tries the configured endpoint first, then Docker-safe candidates such as `host.docker.internal`, before failing the run.
- Companion UI channel launchers (`make dev-ui`, `make test-ui`, `make prod-ui`) bind the browser
  UI to `127.0.0.1` by default. Set `CUI_BIND_LAN=1` to explicitly opt a channel into a
  `0.0.0.0` bind for trusted LAN/Tailscale UAT. Public internet exposure remains unsupported.
- The Companion UI proxy pins `/api/companion/*` to the same runtime origin so browser UAT does not
  cross providers or devices accidentally. Runtime-unreachable and wrong-device states are distinct
  operator-visible failures rather than generic vault setup prompts.
- Companion TTS remains a local-first runtime surface with configured voices for Markdown
  read-back. Ollama embedding identity and any selected remote endpoint are governed by
  [the environment topology contract](ENVIRONMENTS.md#prod-ollama-topology); this playbook does not
  establish a Tailscale prerequisite for the Model Access text route.
- The accepted Model Access route uses VLAN mTLS to the loopback-bound Mac mini Codex CLI
  executor. See [the dated infrastructure status](https://github.com/RasmusTho/yggdrasil-infra/blob/main/CURRENT_STATUS.md)
  for installed and observed services. A merged adapter or running listener does not establish
  persistent Product routing, inference qualification or release acceptance.
- For the explicit `openai_api` evaluation transport, the executor may start through
  `scripts/start_model_access_executor.sh` as the dev-only `model-access-executor` Keychain consumer
  of `openai.api-key` (#6386). Switching the launchd job to that launcher and the owner's one-time
  Keychain store are separate operator steps; until both happen that transport reports
  `credential_unavailable`.
- The repository resolves the MARR-only `typesafe.api-key` binding from the exact
  `dev/typesafe.api-key` identity in the existing `non-prod` BWS project through the existing
  read-only `non-prod-reader` account (#5801 / #5808). Its BWS reader token remains a
  separate Mac Keychain bootstrap credential. The #5667 receipts #6114638077 and #6114787299 verify
  the current entitlement, existing reader scopes, exact MARR binding, and accepted Demerzel normal
  writer with its same-user residual. Product and Builder callers receive no
  provider key; Linux reader identities retain accepted store-level access to the existing projects,
  while the application code-level MARR grant remains the sole runtime binding. Codex and Claude
  receive no code-level provider-key grant. Fake-backed repository proofs do not establish the broader
  integrated channel deployment/runtime acceptance, which remains open under #5667. Product/Builder
  actual-consumer DEV receipts are now verified separately on #5764, as linked above. Both
  allowances are consumed; the historical Builder call and used MARR check were not repeated.
  Ordinary route activation remains separately gated. Follow `docs/LOCAL_SECRET_PROVISIONING/README.md`
  (`Declared identifier contract`) and `docs/TYPESAFE_SYSTEM_ONE/README.md`
  (`Data and Credential Boundary`) for the details.
- Builder CKM association has repository support through its own authenticated
  `/v1/ckm-judgment` MARR operation and pinned Builder profile. The preserved actual-consumer DEV
  receipt above verifies its completed call, with a below-floor result and zero candidate or
  confirmed edges. Derived evidence remains candidate-only under the existing explicit confirmation
  and rebuild rules. `docs/TYPESAFE_SYSTEM_ONE/MIGRATE_BUILDER_CKM_ASSOCIATION.md :: Development Acceptance Gate`
  retains the acceptance contract; ordinary runtime activation remains separately gated.
- Governed channel deploys obtain `TTS_ENABLED` and `TTS_HOST_ROOT` only from the selected generated
  runtime-env snapshot. The canonical exporter publishes that file atomically; deploy preflight
  fail-closes unreadable, malformed, duplicate, or invalid enabled configuration before migration,
  pin, or Compose mutation. Long-form bind semantics refuse to create a root that disappears after
  validation, and governed Compose output is reduced to validated internal IDs or fixed redacted
  status. Rollback bypasses this deploy-only check and clears stale caller selectors before using
  the tracked disabled fallback, so recovery remains available. The detailed contract and
  provisioning steps
  live in `companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md` and
  `docs/runbooks/RUNBOOK_TTS_PROVISIONING.md`.
- Runtime-env regeneration retains the explicitly supplied binding set described in that TTS
  runbook through ordinary Compose env-file syntax and the existing defaults loaders, including
  literal dollars, quotes and backslashes. Empty or whitespace-only capture selectors remain
  unconfigured in both deployment preflights, matching the capture runtime's stripped-empty rule;
  their input values are preserved. Configuration preservation does not establish model-backed
  qualification or current runtime health.

### BuilderOps Issue-delivery repository support

Issue #5586 adds repository-side `fca-issue-delivery.v2` support for the bounded Bifrost
consumer, with an independently pinned trusted hub workflow, separate hub tracking Issue,
and exact per-target protected policies and credential generations; hub-only v1 is unchanged.
The owning contract is [FCA-ID-SECOND](BUILDER_FACTORY_ACCEPTANCE/README.md#fca-id-second--bounded-bifrost-documentation-delivery-target).
Issue #5587 adds repository-side [FCA-09-BIFROST](builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md#fca-09-bifrost--non-image-documentation-candidate-target)
candidate/readiness support: protected finite documentation profiles, complete candidate diff,
exact blob bytes, addressed-owner access and expiring source evidence feed the existing authenticated
human-outcome transaction and independent readback. Last verified against (this paragraph only):
Issue #5587's production service/PostgreSQL owner-fact and Issue-delivery readback checks.
This support does not activate a host, issue grants, deploy a transport, or establish live M2
completion. Live documentation source/profile preparation, managed UI/host activation, a real pilot
and explicit human trial/acceptance remain separately gated. Repository-only review: 2026-09-17, Issues #5586/#5587;
the live-runtime verification date and unrelated operational claims above are unchanged.

Issue #5405 adds repository-only production-composed hub/Bifrost admission, read and launch
conformance, including refusal of borrowed policy/credentials and disconnected-owner replay.
The [FCA-06 procedure](BUILDER_FACTORY_ACCEPTANCE/QUALIFY_SECOND_CONSUMER_REPOSITORY.md)
and its validated `builder_second_consumer_pilot_plan.v1` remain explicitly incomplete: concrete
host transport/bootstrap and candidate preparation/stage/commit, authenticated M2 UI, exact
consumer preparation, selected-operation stop/recovery/rollback proof before Start, and actual
result/readback and human trial/acceptance are unproved parent-owned prerequisites. Unsupported
launcher stop and deployment rollback are not operation recovery evidence. Repository-only
review (this entry only): 2026-09-18, Issue #5405, composed PostgreSQL conformance and plan-validator
checks; no live-runtime verification or unrelated operational metadata is updated.

Issue #5593 adds dormant repository-side `fca-issue-delivery.v3` content-to-candidate preparation:
the real protected host path observes quiescence, captures immutable documentation bytes, crosses
the existing durable fence, and independently reads back exact local Git effects. Authenticated
native-task CAS retains candidate references and the physical destination, including unknown and
missing-reference states; it never releases candidate-only work as delivered. The managed source
reader preserves this lineage without delivery/trial facts. This implements the repository producer,
not the live qualification still required above: no host installation, policy/grant/credential change,
remote continuation/transport, recovery control action, live Start or human acceptance is supplied.
See [FCA-ID-HOST-CANDIDATE](BUILDER_FACTORY_ACCEPTANCE/README.md#fca-id-host-candidate--protected-candidate-and-continuation-contract).
Repository-only proof does not update the live-runtime verification date or close parent #5399.

### DevUI GitHub token rotation on BOB-1

Use `scripts/secrets devui rotate` from an up-to-date checkout on Demerzel to
replace DevUI's dedicated GitHub credential through Bitwarden and hidden local
terminal input. The fixed `bob-1-builder-system` SSH handoff needs no VM password
and verifies reads inside the actual DevUI container. Preserve the existing
read-only token settings; this binding does not update `shared/github.token`.
The [DevUI secret procedure](CLOUD_SECRET_PROVISIONING/README.md#bob-1-devui-github-token)
owns interpreter setup, preflight, exact paths, durable receipts, and recovery.

### BuilderOps cockpit live GitHub plane (#4484)
- The cockpit's `github-live` source reads GitHub REST from **inside the `api` container** via the
  `gh` CLI, which the runtime image installs (`Dockerfile`, runtime-stage apt layer) alongside
  `ffmpeg`/`espeak-ng`. Before #4484 the binary was absent, so the plane refused on every channel
  regardless of configuration.
- The plane is opt-in per channel. `docker-compose.dev.yml :: api` and
  `docker-compose.prod.yml :: api` bind
  `COCKPIT_GITHUB_REPO=RasmusTho/agentic-pkm-mvp`; `test` deliberately leaves it unset and renders
  the source as *not enabled* rather than broken. The prod entry is committed configuration only;
  it is not evidence that a particular revision is deployed.
- The token is host-supplied, never committed. Provision it as the **Keychain item** for the declared
  optional identifier `github.token` under consumer `heimdal-api-ingress` (#4489) — do not hand-write
  an env file: on a governed `scripts/deploy_channel.sh` run the layer's file is bootstrap-owned and
  rebuilt from declared identifiers only, so a hand-written value is discarded. The bootstrap then
  materializes `GITHUB_TOKEN` onto `HOST_SECRET_RUNTIME_ENV_FILE_API`, the same layer that delivers
  `HEIMDAL_RAW_STORE_KEY`. A repo-scoped read-only token suffices — the plane issues GET requests
  only and persists nothing.
- Because `github.token` is declared `optional`, a host with no token still deploys normally and the
  Heimdal ingress lanes are unaffected; the plane simply refuses.
- **A token that is present but malformed fails the whole channel deploy.** Fail-closed here is
  deliberate — a present-but-wrong credential is a misconfiguration, not an opt-out — but the cost is
  that `docker compose` never runs, so no service starts, not just the cockpit. The error names the
  logical id (`github.token`), never the value. Fix the Keychain item and re-run. The same has always
  been true of a malformed `heimdal.raw-store-key`; tracked as deferred defect `KD-4489-malformed-declared-secret-aborts-channel-deploy` on #4172.
- Note the coupling: this layer is only materialized when `heimdal.raw-store-key` also resolves, so
  provisioning the GitHub token alone is not sufficient on the governed deploy path. Identifier and
  account derivation: `docs/LOCAL_SECRET_PROVISIONING/README.md :: Declared identifier contract`.
- On Demerzel only, after the corresponding commit is available, run
  `python3 scripts/check_prod_devui_focus_prerequisites.py`. Its stdout is one JSON object containing
  only the non-secret repository identity plus separate presence booleans for `github.token` and
  `heimdal.raw-store-key`; exit 0 requires the exact repository and both values. Do not run it on a
  laptop or copy ambient credential material into a receipt. The command is read-only and does not
  provision, install, rotate, deploy, restart, or validate a credential by echoing it.
- The committed repository binding is not deployment or credential-presence evidence. Only a
  separately governed Demerzel preflight and deployment verification can establish those facts.
- Check it with `curl -s localhost:18001/api/cockpit/registry | jq '.sources[] |
  select(.name=="github-live")'`. Full path and rationale:
  `docs/BUILDEROPS_COCKPIT/GITHUB_LIVE_PLANE.md :: What makes that command answer fresh (#4484)`.

### Prepared BuilderOps Linux health probe

Issue #6336 adds a plan-only bob-1 monitoring path, distinct from the Product
`test`/`prod` probe installer. The prepared probe checks the qualified engine/project,
authenticated loopback readiness and expected schema/epoch, explicit worker freshness,
database container health (including local disk/WAL guardrails), and outbox degradation.
It reuses the shared notification adapter through the dedicated admitted encrypted host
credential and private invocation-only handoff, retaining engine/epoch-bound outage state.
As of 2026-10-26, the separately authorized #6347 window has installed and enabled this component
and qualified one down/repeat/recovery drill with the exact worker restored healthy.
This component result does not establish global client/authority cutover; see the
[deployment owner contract](BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md#prepared-linux-builderops-monitoring).
Backup/restore is not a readiness gate, and bob-1 power-off detection requires an
outside observer.

### BuilderOps VM102 failure-domain preflight

The repository-side BuilderOps deploy wrapper reads the configured project listings before any
Docker pull, Compose mutation, readiness probe, or Tailscale action. It refuses closed-loop
operation when `builderops-control-plane` is present in both the dedicated `builderops-engine`
context and the Product context, and it also refuses malformed or incomplete listings. The
preflight records a redacted `builderops_vm_rebuild_activation_refusal.v1` envelope with
`mutation_performed: false`; it does not select a winner, stop a stack, or remove a competing
writer. The refusal envelope is deliberately distinct from the successful
`builderops_vm_rebuild_activation.v1` receipt and is defined by
`config/platform/builderops_vm_rebuild_activation_refusal.v1.schema.json`. The contract is implemented by `scripts/lib/builderops_compose.sh` and
`scripts/deploy_builderops.sh`, with the receipt shape defined in
`docs/BUILDEROPS_CONTROL_PLANE/README.md`.

The successful activation receipt is admitted only with a matching
`component_inventory_digest` and exactly one inventory-receipt source reference. Its
`observed_at` must be within the 24-hour evidence window and no more than five minutes ahead of
the verifier clock. Re-entry also validates the inherited lock descriptor itself; an unrelated
open descriptor for the same lock path cannot authorize deployment mutation.

This repository-side guard is not VM102 activation or health evidence. Live activation,
single-writer proof, deploy, health, and owner read-back remain separate receipt-gated operations
under #5056 and #5181.

Before a BuilderOps pin, database, or service mutation, the deploy wrapper must successfully
restart `builderops-loopback-forwarder.service`. API/worker recreation invalidates the cached
container address, so the wrapper restarts that fixed service again before authenticated readiness
polling. A missing or failed restart is fail-closed; the wrapper does not poll readiness or claim a
restored release from an unrefreshed private loopback boundary.

BuilderOps post-effect verification reads its successful deployment receipt and selected pin
through authenticated status. Compose mounts the pin directory read-only so atomic pin replacement
withdraws admission immediately. The deploy wrapper records the directory, basename and receipt
location in the selected pin for later service-manager restarts. The active metadata pin is published
readable by the non-root API (0644), with directory traversal enabled. The rollback pin stays
private (0600) to satisfy the existing unattended rollback custody gate; secret custody is unchanged.
Missing, stale or mismatched
readback refuses the consumer; this repository mechanism does not establish live activation.
The owning contract is [verified issue-set merge and exact closure](AGENT_ISSUE_DISPATCHER.md#current-state-honesty).

### Builder Thread serialized writer

Builder Thread is retired under #5128. There is no service, endpoint, client,
startup command, environment contract, inbox projection, or supported operator
procedure to configure or run.

Route delivery questions and review discussion through GitHub Issues and PR
comments, normative content through repository docs, and builder-operational
material through typed BuilderOps records. Retained Builder Thread v1 artifacts
remain inert: operations must not read, inspect, parse, migrate, repair, project,
log, archive, or delete their content. Historical audit and recovery documents
are evidence only and provide no reactivation or fallback authority.

### Karakeep managed source service (KMA-02)
- `docker-compose.karakeep.yml` is the repo-owned Compose manifest for the self-hosted Karakeep
  read-later source (Heimdal's external source dependency; ADR-0049 §1). It pins the
  `karakeep`/`meilisearch` images, declares the durable `karakeep-data` / `karakeep-meilisearch-data`
  volumes, health-checks both services, and binds to loopback only — there is no public ingress.
- `scripts/karakeep-deploy <dev|test> --revision <installed-control-checkout-SHA>` operates the
  exact existing `ygg-dev` or `ygg-test` role through authenticated SSH and the root-only encrypted
  BWS reader supervisor. The existing controller qualification and a current redacted #3367
  operations receipt bind private host/config inputs outside Git. Demerzel is the controller;
  local Compose on the Mac mini is not TEST deployment. Production is refused before lookup/SSH.
- Finite dev/test BWS consumers are `karakeep-service-web` (session/search tokens),
  `karakeep-service-search` (search token), `heimdal-karakeep-fetch` (issuer-created API key), and
  `karakeep-account-setup` (account password only). `scripts/secrets prepare-karakeep <channel>`
  creates absent service keys through the normal writer and preserves existing credentials.
  Service startup does not require the account password or API key. Account/API-key issuance
  remains subsequent authorized operational work; Mimer receives no source token or endpoint.
- Projects/volumes are isolated as `karakeep-dev` and `karakeep-test`. Separate root-owned
  mode-0600 handles under `/run/yggdrasil/karakeep/<channel>` deliver only each service's credentials;
  boot/restart rehydrates through the existing reader and VM channel lock. The template is reference
  only; do not create persistent ordinary credential env files. Never print unfiltered Docker
  inspection or rendered Compose configuration.
- The governed unit admits Docker-daemon/VM startup; containers use crash-only `on-failure`,
  not daemon auto-start. Missing reader keys or pending journals therefore cannot be bypassed by
  retained container environments. Actual container restart policy is part of topology preflight.
- Activating/unknown receipts retain pending admission and the VM channel lock. Reruns reconcile
  the same request and require authoritative terminal plus health evidence; a timeout or healthy
  container cannot authorize a duplicate deployment or report success.
- A deployment sent after read-only preflight may race with boot admission. Known pre-effect
  refusal is durable in the same DeployJournal's finite refusal namespace; exact-ID status returns
  `aborted` without replacing installation/boot proof, borrowing their lock, or replaying effects.
- Backup / update / rollback steps (and their verification checks) live in
  `docs/KARAKEEP_MIMER_ACQUISITION/DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md :: Restart / Durability Posture`.
  They may be used only after the exact host/private route is qualified. Archive/restore and version
  upgrades require separate maintenance authority and remain outside this implementation slice.
- `app.heimdal.karakeep_service.assert_fetch_ready` is the fail-loud gate: Heimdal acquisition is
  refused when a required config reference is absent or service health is red, while Mimer replay of
  already-published evidence is unaffected.
- `scripts/karakeep-acquire test` and `scripts/karakeep-project test` admit separate fixed
  TEST Product-image children through the existing root-only supervisor. The producer alone
  receives the finite `heimdal-karakeep-fetch` grant over stdin; generic BWS launch remains denied.
  Mimer receives no source key/endpoint and replays independently. Actual admission requires
  matching installed control/selected Product-image SHA, existing TEST PG/store/vault and active
  initialized binding authority, qualified mounts and per-constituent process locks. The worker
  refuses nested code/interpreter/dependency overlays and uses a fixed `/app` workdir and image
  interpreter with user-site imports disabled. Producer admission checks its log/schema without
  Mimer's cursor; the consumer alone checks that cursor. A started SSH invocation with lost or
  invalid acknowledgement reports `pending`; a received valid refusal remains `refused`.
  The worker
  endpoint comes from observed execution-namespace topology, never the Mac's saved forwarding URL.
  Missing topology/binding refuses without repair. Outcomes are `complete`, `partial`, `blocked`,
  `gated`, `failed`, `refused`, `overlap` or `pending`; loss after work admission is not completion.
  Restart deliberately rescans source page one and reconstructs full published lineage; Mimer
  retains its existing durable-prefix acknowledgement and first-write-wins candidates.
  Main owns post-merge runtime qualification and explicit service re-admission when the installed
  control revision changes. The full separate live acceptance procedure remains in
  `docs/KARAKEEP_MIMER_ACQUISITION/PROVE_AND_ACCEPT_KARAKEEP_TO_MIMER.md :: How to Verify (Pre-Merge)`.
- Scope note: repository support does not prove a live installation. TEST installation is separate
  from KMA-06 acceptance. The live
  acquisition pipeline (Heimdal fetch → published evidence → Mimer candidates) is not accepted as
  shipped until the parent Karakeep acquisition feature (#3367) completes its acceptance slice.

### YouTube Inbox discovery scheduling (YSS-06)

The existing watcher loop can schedule discovery for the supported one-account Inbox when both
accepted YouTube runtime gates are enabled. Manual Inbox sync shares its scheduler lease;
acquisition remains the separate operator-invoked drain, and no background media worker is added.
Use the [operator runbook](YOUTUBE_SOURCE_SYNC/OPERATOR_RUNBOOK.md) for setup and commands, and the
[YSS-06 contract](YOUTUBE_SOURCE_SYNC/SCHEDULE_AND_OPERATE_CONTINUOUS_SYNC.md) for pause, lease,
backoff, recovery, and cooperative deadline limits. This repository support is not live-provider
acceptance and does not reopen the deferred subscription, backfill, or broad CLI/UI slices.

Detailed startup, local topology, and recovery procedures live in `docs/INFRASTRUCTURE.md`.
Task-specific operator walkthroughs live in `docs/runbooks/`.

## Auth & Rate Limiting
- Refer to `docs/SECURITY.md` for implementation guidance (API key dependency + `slowapi` limiter).
- Use `docs/SECURITY_ARCHITECTURE.md` for security review routing and
  `docs/security/API_SECURITY_MATRIX.md` for route-by-route exposure and mutation classification.
- Store the API key in environment or secret manager; rotate by updating deployments and monitoring logs for legacy usage.

## Observability
- Logs: a JSON formatter is available via `app/observability.setup_logging()`, but it is **not called at startup**, so logs are **not JSON-formatted by default**. Until a startup hook calls `setup_logging()`, logs are plain text; do not assume structured JSON when wiring a logging stack (CloudWatch, ELK, etc.).
- Version: `GET /version` returns the running git SHA and build time (`OBSSTAB-05`); `/api/health` also carries a `version` field. Use it to confirm which commit is actually deployed during an incident.
- Metrics: enable `METRICS_ENABLED=1` to expose Prometheus metrics under `/metrics` using `prometheus-fastapi-instrumentator` (secure access appropriately).
- Runtime signals and interpretation live in `docs/OBSERVABILITY.md`.
- Local Prometheus+Grafana recipe lives in `docs/INFRASTRUCTURE.md` (Docker Compose).

## Prod probe and push alert (scheduled backstop)

`ops/host-setup/mac-mini/prod_probe.py` is the shared probe entrypoint. The supported production
host is TARS Linux: `config/systemd/yggdrasil-host-probe@.service` runs it every 60 seconds with
explicit environment, endpoint, heartbeat path, and state path. The probe checks `/readyz`,
`/api/health` `required_ok` (not top-level `ok`), and worker-heartbeat staleness. It sends one
down alert on the first outage transition and one recovery signal on the first healthy run; both
messages carry the same correlation ID. Alerts include source system, environment, severity, UTC
timestamp, and remediation URL.

The source template leads with `DEV hälsoproblem`, `TEST hälsoproblem`, or `PROD hälsoproblem`, not a
claim of total outage. It names failed required checks from the finite health-producer mapping
and mandatory runtime database, worker and model components. Optional failures are excluded;
watcher requirement is producer-local and is not inferred from a failed watcher observation.
Unknown or malformed cause metadata yields plain Swedish uncertainty in the human text;
`UNKNOWN` is reserved for technical metadata. Raw health details,
errors, paths and arbitrary keys never become notification text. Templates are deterministic;
there is no language-model call or inferred cause, impact or repair claim. Broader impact remains
unknown in plain Swedish (`impact: UNKNOWN` in the footer); recovery says only that the monitored readiness, required health and heartbeat checks
are green, using the same incident correlation.

Messages include Swedish local date/time in `Europe/Stockholm` (with DST and numeric offset),
fall back to UTC when zone data is unavailable, and retain UTC, transition, severity, source and
correlation metadata below the human text. The finite template fits Discord's 2,000-character
content limit including its bold subject wrapper; the sender itself does not truncate. The next
step points to the fixed incident runbook URL rather than echoing runtime URL configuration.
Use the raw health surface separately for investigation; the alert does not reproduce diagnostics.
The template's production installation is recorded in the 2026-10-30 receipt below. The existing
incident continued suppressing duplicate alerts; controlled TEST acceptance remains open under
#4076. The dated receipts retain their exact source and observation scope.

The [2026-10-30 TEST first-preflight receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6493#issuecomment-6535859691)
records operation `230149723a60e4c497a04f8efc07a9a9` as `REFUSED` before qualified-worker or drill
entry: the same-project running-worker selector did not observe exactly one valid ID. This does
not distinguish worker count from ID shape or establish worker absence or health. The original
supervisor/cgroup were positively contained and the watch/TEST probe units were absent. The result
SHA-256 is `542a4448014fc00b91b3cf0a830f4dcdb8a8860febe5325ba4498fcb9a4c7b71`; its separate
reconciliation SHA-256 is `6a71c89eeaecfd53acc2e16315c8aa153bf0b07529d4a30a27fa6138cacdbfa0`.
Earlier `UNKNOWN` results remain preserved. No controlled down/recovery or live TEST acceptance
is claimed; #6493's actual acceptance and final receipt mapping remain open.

The Linux service uses the `heimdal-external-alerts` BWS consumer and the `discord.webhook`
binding. The BWS token is read through systemd credentials and is removed from the probe child's
environment; only a short-lived mode-0600 runtime file carries the declared webhook binding.
The fixed Linux launcher and shared probe source accept explicit `dev`, `test`, and `prod`;
DEV and TEST bind this consumer to `non-prod` and `shared/discord.webhook`, while PROD uses `prod`.
Endpoint, heartbeat, state, and alert-channel inputs remain explicit. The existing
`scripts/install_host_probe.py` installer remains TEST/PROD-only; its shared
`/opt/yggdrasil/host-probe` package is not a DEV installation plan. Native DEV configuration,
installation, baseline, and drill qualification remain pending with the Product keeper. DEV
source support does not upgrade the dated production installation below or satisfy #4076's
pending live TEST AC4.
The service has no Docker startup dependency and reads the worker heartbeat from the host volume.
The prior Mac LaunchAgent and plist remain legacy templates. The installer
`scripts/install_host_probe.py` prints a plan by default; host writes require `--apply` from a clean
checkout at the exact `origin/main` head. On 2026-10-29, production installation from source
`777726d3139fc82cd69097dcd3bccc4d1c6c167a` was
[verified on `ygg-prod`](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6444#issuecomment-6490667131):
all 60 package files, configuration and effective unit matched; the same active/enabled invocation
remained stable across two normal 60-second intervals with zero restarts. The declared BWS launch
and private runtime binding metadata were verified without exposing credentials.
The pre-existing `/readyz` HTTP 200 and `/api/health.required_ok=false` signal produced one confirmed
down alert followed by two duplicate suppressions, with no observed delivery or iteration errors.
This is normal production monitoring, not a controlled outage, source-health repair or TEST proof.

The [subsequent production upgrade](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6457#issuecomment-6502803665)
changed only `prod_probe.py` to SHA-256
`0172b37565a067c26acd37afed8d650be7a56117ad1962860446fd18353058ac` from source
`0d064c012296589e92987c1f374fa18b05104f7b`, retaining the other 59 files from the initial source above.
Its mixed 60-file manifest is `3ae600b78abefb751ef8fd73e7639b75a41b09f30d44fd4d06b1bb77101ae861`,
with unchanged configuration/unit and a qualified interpreter/private normal-child binding.
Read-only verification observed the same active/enabled invocation over 43 completed suppression
cycles, zero restarts and the unchanged existing incident. The original executor remains `UNKNOWN`
at `start_intent/main_process_boundary`, with its helper/cgroup reaped and immutable original
request/program/result/handle still followable through preserved pinned tooling. The linked actual
postcondition receipt does not adopt lifecycle ownership or relabel the executor. Its original
resource guard remains intact and fences later #6457 apply requests; no guard clearance or further
host compensation was performed. The separate #4076 controlled TEST acceptance remains open.

The [2026-10-30 readable-rendering installation](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6476#issuecomment-6512944547)
changed only the probe script to renderer source `7436ca29b863fca98faeb8e729d00e9832a71c22`, SHA-256
`17c2dced67a7830e453f4bf5d18e1e330086dab186501b80b259f569936c8e90` (28,710 bytes), retaining the same
59 package files from `777726d3139fc82cd69097dcd3bccc4d1c6c167a`. Its mixed 60-file manifest is
`317f99b147d23dcf20c3e59be2d542cd9f3f74aeca98d519ba2393a9eab3a635`.
Read-only qualification observed the same active/enabled normal invocation across 59 completed
cycles, zero restarts and continued suppression of the unchanged existing incident/acknowledgment/
correlation state. Configuration/effective unit, normal BWS launcher/SDK child/interpreter and
source/cache compatibility matched. No down/recovery send was forced or repeated.

The new operation `32967742602847edb920cab7a1023faf` remains `UNKNOWN` at
`start_intent/main_process_boundary`, with its finite helper/cgroup reaped. The linked receipt accepts
actual observed postconditions without adopting lifecycle ownership or relabeling the executor.
Both original5b47 and successor request/program/phase/handle/result bytes and resource fences remain
intact, including the original pinned follow tooling. The actual read-only qualification made no
lifecycle/metadata/incident/cache write; no additional compensation was indicated by its verified
postconditions. The original installation, subsequent 43-cycle proof and Mac retirement remain
historical facts above and below. #4076's separate controlled TEST acceptance stays open.

The fixed successor source support came from
[#6475](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6475), merge
`f3372e5fe88146266825cfa595f667f7d974ceee`.

The carrier's `--rendering-successor` path is fixed to #6476 and contract-body SHA-256
`7ef11ac405db559eec87c507c11eab13bf794a8421d6cd13e0aec98bcaa8ae1c`. Before an installation operation,
its normal Issue claim must be open/in-progress with the exact unexpired dispatcher lease.
For this fixed installation, the normal pickup uses the actual `CODEX_THREAD_ID` as both
`--agent` and `--session`; the dispatcher holder must equal that native owner identity.
The carrier must run from that same registered worktree root. Its current Git branch and
generation-bound lifecycle authority must agree with the sole active owner registration;
an inherited session label, a different runtime cwd or another owned worktree cannot supply the
binding. The clean checkout's current committed carrier/core/helper bytes and head are bound into
the frozen request.
Names, a new operation ID, source CI, a historical receipt or the closed #6475 lease supply none of
this authority. The installation owner retains the reviewed source/program binding and original
new-operation handle for follow/reconciliation.

Inside the existing physical resource lock, admission pins original5b47's request/programs,
authorization, phase, handle and honest UNKNOWN result, rejects any original continuation, and
freshly proves its helper and cgroup reaped. It then qualifies the complete current60 package,
configuration/effective unit, interpreter/launcher/private child, normal invocation, other consumers
and latest incident. A fixed `rendering-successor.json` selector retains the original `active.json`
bytes; both paths acquire the same `resource.lock`, whose inode and request/admission binding are
rechecked before stop, replacement, start and compensation. The original pinned follow remains
read-only and usable. The admitted normal invocation remains the identity for the first stop,
including after execution qualification and durable stop intent. Every present successor selector
must qualify; an empty selector or a missing selector alongside prior attempt metadata never opens
a new operation. Unqualified or partial evidence, foreign ownership and concurrent writers refuse
admission. A lost response follows the same successor handle; unresolved start ownership
stays UNKNOWN. Existing finite helper limits, descriptor custody and code-only compensation apply,
retaining current incident acknowledgments, correlation/history and qualified caches.
The linked actual receipt verifies installation and completed normal cycles while preserving the
executor's UNKNOWN status. The source prerequisite does not gate #4076's accepted TEST lane.

**Two distinct Makefile targets — do not confuse them:**

| Target | What it does |
| --- | --- |
| `make live-prod-probe` | Runs one local spot-check against `http://127.0.0.1:18000` by default, with notifications disabled by default. Set `PROBE_BASE_URL`, `WORKER_HEARTBEAT_PATH`, and `PROBE_STATE_FILE` to explicit local values as needed. Exits 0 if healthy, 1 if prod is down, 78 for missing/invalid configuration. |
| `make check-prod-channel` | Runs the pytest channel-isolation suites (`tests/ops/test_release_channel_isolation.py`, `tests/ops/test_release_channel_startup_targets.py`) to confirm that prod and test channels are correctly isolated. No live network calls to the running stack. |
| `make check-test-channel` | Same channel-isolation suites plus the test-channel preflight (`tests/release_channels/test_channel_isolation_preflight.py`). |

**Transition / recovery guarantee:** A sustained outage sends one down alert, repeated
down probes suppress while the outage remains active, and the first healthy run sends one
recovery signal and clears the outage state. A later distinct outage alerts again.
The state marker (`PROBE_STATE_FILE`) is channel-specific and host-local. Delete it only when
intentionally re-arming notifications; the installed Linux state path is under
`/var/lib/yggdrasil-host-probe-<channel>/`.

**Install:** `python3 scripts/install_host_probe.py --channel test` prints the TEST plan;
`--apply` writes the host from the exact merged `origin/main` checkout. Production installation
uses `--channel prod`. The installer is deliberately separate from the TEST outage/recovery drill;
the parent Issue #4076 owns both live host operations and disabling the legacy Mac LaunchAgent after
the Linux production service is active. Linux activation is verified by the receipt above.
After a fresh check of the same active Linux invocation, the exact legacy
`com.yggdrasil.prod-probe` job was
[disabled and unloaded on 2026-10-29](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6449#issuecomment-6491766335)
in the qualified current user's GUI domain. Readback confirmed the disabled override, absent job
and preserved original plist metadata/selected identity. No legacy program was invoked and no
physical-asset identity is claimed. The separately qualified isolated TEST
down/repeat/recovery/restoration drill remains open under #4076. Existing catalog acceptance and
the #6347 shared webhook import must not be requested or repeated again.

## Prod backup watcher (stale or failed nightly dump)

`ops/host-setup/mac-mini/prod_backup_probe.py` is the watcher for the nightly prod DB
dump (`local.prod-pgdump` on the mac mini, which runs `~/bin/prod-pgdump-run.sh`). It is
installed as its own launchd job, `com.yggdrasil.prod-backup-probe`, and runs hourly. The installer
copies both the watcher and its shared `notification_channels.py` module to `~/bin` so the installed
entrypoint does not depend on the repository checkout.

**Why it exists:** the dump job failed every night from 2026-07-06 to 2026-07-29 and the
gap went unseen for three weeks, because nothing read its log. The underlying TCC
permission bug is fixed; this watcher closes the detection gap that let it hide.

**It does not depend on the backup job working.** The load-bearing signal is the dump
directory itself, so a job that stops firing entirely — and therefore writes no `FAIL`
line at all — is still caught. Three checks run on every pass and every failure is
reported in one alert:

| Check | Signal | Default budget |
| --- | --- | --- |
| Dump freshness | newest `prod-*.dump` in `BACKUP_DIR` (`/Volumes/T7/prod-db-backups`) | `BACKUP_MAX_AGE_HOURS=48` — tolerates one missed night |
| Status verdict | last line of `BACKUP_STATUS_FILE` (`~/Library/Logs/prod-pgdump.status`) reports `OK`, not `FAIL` | — |
| Status freshness | that line's own ISO-8601 timestamp | `BACKUP_STATUS_MAX_AGE_HOURS=30` — a job that did not fire |

**Unverifiable is never healthy.** A missing or unmounted `/Volumes/T7`, an unreadable
directory, an empty status file, or a garbled status line all alert. The watcher never
reports green on a signal it could not read.

### The TCC hop (one-time setup)

launchd starts jobs unattributed, with no TCC grants, so it cannot read the removable
volume holding the dumps. Verified on the mini 2026-07-29 — and the failure mode is
deceptive:

```
py_isdir True                                        # stat is allowed
py_listdir_ERR PermissionError [Errno 1] Operation not permitted
```

`Path.glob` silently swallows that `PermissionError` and yields nothing, so a naive
implementation reports "no dumps found" forever instead of "I am blind". The watcher
therefore uses `os.scandir` and separates *not mounted* from *permission denied*.

The fix is the same loopback ssh hop the backup job itself uses, through this watcher's
own key and its own read-only lister (`ops/host-setup/mac-mini/prod_backup_list.sh`,
installed to `~/bin/prod-backup-list.sh`) — no credential or code path is shared with the
backup job. `install.sh` wires the plist and prints these steps; run them once:

```bash
ssh-keygen -t ed25519 -N '' -C prod-backup-list -f ~/.ssh/id_ed25519_prod_backup_list
```

Then add the public key to `~/.ssh/authorized_keys` as a single line, locked to a forced
command so it can only ever list dumps:

```
command="$HOME/bin/prod-backup-list.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... prod-backup-list
```

Until that is done the watcher sends **one** alert saying it cannot see the dump volume
and naming the fix, then suppresses. The status-file checks keep working meanwhile, so a
failed or non-firing backup is still caught. Verify the hop with:

```bash
ssh -F /dev/null -i ~/.ssh/id_ed25519_prod_backup_list -o IdentitiesOnly=yes -o BatchMode=yes localhost
# → one "<epoch-mtime> <path>" line per dump, or MISSING / DENIED / EMPTY
```

**Transition / recovery guarantee:** identical to the prod probe — one alert on entering
a bad state, suppressed while it persists, one recovery signal on the first healthy run,
then re-armed for a later distinct failure. A failed push does *not* record the state, so
a channel outage retries on the next run instead of swallowing the alert. The state
marker (`PROD_BACKUP_PROBE_STATE_FILE`, default
`/tmp/yggdrasil-prod-backup-probe.state`) is rebuildable; delete it to re-arm manually.

The channel is pluggable via `PROD_BACKUP_PROBE_CHANNEL` (`ntfy` | `telegram` | `mail` |
`none` | `discord`) and defaults to the same `NTFY_TOPIC` the prod probe pushes to, so the
operator watches one topic for both. The host-secret-bound `discord` option is one-way code-path
support; provider/account/server/channel/webhook enactment remains external Heimdal work tracked by
#5506 and #4076.

```bash
make live-prod-backup-probe                              # live spot-check; exit 1 = backup failed or stale
PROD_BACKUP_PROBE_CHANNEL=none make live-prod-backup-probe   # dry run: log the verdict, push nothing
launchctl list | grep prod-backup-probe                  # confirm the job is loaded
```

**Known current state:** prod is down entirely (issue #4282 — the `pkm-prod_pgdata`
volume is gone), so the status file legitimately reports `FAIL pg_dump_failed` and the
newest dump is from 2026-07-11. The watcher alerts on both facts, which is correct: there
is no current prod backup. Expect it to stay in the alerted (suppressed) state until prod
is restored and a dump lands.

**Install:** `ops/host-setup/mac-mini/install.sh` step 4c registers the launchd job. The
plist is at `ops/host-setup/mac-mini/com.yggdrasil.prod-backup-probe.plist`.

The probe and its lister are installed to `~/bin/` and run under `/usr/bin/python3`, not
out of the repo checkout and not under the gateway venv. Both are deliberate: the probe
is stdlib-only, and a backup watcher must not go dark because the repo is parked on a
feature branch or the gateway venv was never built. `install.sh` is the single producer
of those copies, so the host and the repo cannot drift.

**Status as of 2026-07-29:** both `com.yggdrasil.prod-backup-probe` and
`com.yggdrasil.prod-probe` are loaded on the mini and have each pushed one live alert to
the `yggdrasil-prod-alerts` ntfy topic. The backup watcher is in its suppressed
alerted state pending the one-time key setup and the prod restore (#4282).

## Runtime health: watcher → DB outbox → worker
- Watcher heartbeat: `WATCHER_HEARTBEAT_PATH` (default `/app/tmp/watcher_heartbeat.json` in containers, `tmp/watcher_heartbeat.json` on host).
- Worker heartbeat: `WORKER_HEARTBEAT_PATH` (default `/app/tmp/worker_heartbeat.json`).
- DB outbox: check the `outbox` table for recent `ingest.vault.changed` and `panel.*` events; the worker should mark `delivered_at`.
- JSONL audit: `INDEX_OUTBOX_PATH` should append lines, but it is not the worker queue.
- Status: `python -m app.cli status` reports `worker_queue` vs `events_log` to distinguish DB vs JSONL.
- Settings gate view: `python -m app.cli settings-explain --json` is the canonical provenance and gate-resolution surface for watcher auto-exec, allowlist validity, and write guard context.
- Health command semantics and degradation rules live in `docs/HEALTH.md`.

## Event and queue troubleshooting
- Use the DB `outbox` table as the authoritative queue. Rows with `delivered_at is null` are pending
  or failed work; order them by `created_at` when reconstructing worker consumption order.
- Inspect the worker logs for `worker retry queued`, `worker retry exhausted`, `worker retry enqueue
  failed`, and `worker handler failed` messages. These are the current poison-message and retry
  observation points; there is no separate DLQ service in the active runtime.
- Promotion consumer failures should also surface as `promote.error` rows in the DB outbox or
  JSONL audit stream, with `source_event` and `trace_id` intact so the failed intent can be traced
  back to the originating input.
- Retry events carry `_worker_retry_count`, `_worker_retry_reason`, and
  `_worker_retry_enqueued_at` in the payload so operators can distinguish transient deferrals from
  fresh work.
- Use `event_id` to identify duplicate deliveries and `trace_id` to correlate watcher, worker,
  panel, promotion, and status/audit observations.
- Treat `INDEX_OUTBOX_PATH` JSONL lines as audit evidence only. A line in JSONL does not prove a DB
  outbox row is pending, delivered, or failed, and `python -m app.cli status` keeps
  `events_log` separate from `worker_queue` for that reason.
- A PROD deploy (`scripts/deploy_channel.sh deploy prod <sha>`) refuses to proceed — before pin or
  Compose mutation — when pending outbox rows are already at the terminal retry boundary and would
  deterministically dead-letter on worker restart (#3903). The deploy log always carries a
  `prod pending-retry preflight: ok|skipped:<reason>|blocked ...` status line; on a block, resolve
  the underlying processing failure first (this preflight never mutates the queue), then redeploy.
  Rollback is deliberately not gated. Full contract:
  `docs/HEALTH.md :: Outbox and dead-letter signals`.
- A `dev` or `test` deploy (`scripts/deploy_channel.sh deploy <dev|test> <sha>`) refuses to proceed
  — before pin or migration mutation — when a `CHANNEL_SERVICES` service's compose `environment:`
  override resolves blank while its `env_file` chain would otherwise supply a non-empty value for
  the same key (#4230; the shape that crash-looped `heimdal-capture-watch` before commit
  `f95a6811`). The deploy log always carries a
  `dev/test environment clobber preflight: ok|skipped:<reason>|blocked ...` status line; on a
  block, remove the blank override so the value rides the `env_file` chain instead. This preflight
  is read-only and is not applied to `prod` or to rollback. Full contract:
  `docs/RELEASE_CHANNELS/README.md :: Environment:-vs-env_file: blank-override clobber invariant`.

Operator triage order:
1. Run `make verify-runtime`.
2. If you need extra detail, run `docker compose exec -T api python -m app.cli health --json`.
3. Run `docker compose exec -T api python -m app.cli settings-explain --json` to confirm watcher gate state, allowlist validity, provenance, and write-guard context.
4. Run `docker compose exec -T api python -m app.cli status` to confirm watcher automation counters, last tick skips, last-run skip reasons, and panel-action/compiler provenance (source paths and combined digest).
5. Check watcher and worker heartbeat files.
6. Inspect DB outbox freshness and `delivered_at`.
7. For enablement decisions, treat `WATCHER_AUTO_EXEC` as necessary but not sufficient; corroborate with `allowlist`, `dedup/skipped_*`, `panel_skipped_policy`, and `writes_allowed`.
8. Escalate to `docs/INFRASTRUCTURE.md` or a task-specific runbook if the issue is startup/runtime-topology specific.

## Common operator CLI commands

Use `python -m app.cli <command> --help` for the full, current argument list. These are the stable operator-facing entrypoints:

| Command | Purpose |
| --- | --- |
| `health` | Local dependency and readiness checks (ffmpeg/yt-dlp/outbox/LLM reachability). |
| `status` | Human-readable runtime status snapshot for watcher/worker/outbox. |
| `watcher run` | Registry watcher loop for the runtime path. |
| `settings-validate` | Validate settings artifacts and compiled settings. |
| `settings-explain` | Show settings provenance and effective resolution. |
| `canvas open|edit|close` | Operate the bounded canvas co-authoring surface when `CANVAS_ENABLED=1`. |
| `llm check` | Probe LLM/embedding endpoint reachability. |
| `index rebuild|doctor|reconcile` | Rebuild derived vectors, diagnose drift read-only, or explicitly reconcile stale/mixed rows. |
| `rebuildability-doctor --snapshot <path> [--json] [--strict]` | Diagnose one explicit owner-native rebuildability snapshot with digest-only findings; it never discovers host state, repairs, restores, activates, or authorizes effects. |
| `pipe <note.md>` | Run ingest for a note/path outside the watcher loop. |
| `pkm-alpha-ingest`, `vault-alpha-ingest` | Compatibility aliases for legacy startup and ingest callers; prefer the neutral ingest commands for new scripts. |
| `make verify-runtime` | Check container health plus in-container runtime health/status for the live Docker stack. |

Flow mapping:
- `python -m app.cli watcher run` -> watcher runtime
- `python -m app.cli ask` -> ASK flow (see `docs/HUMAN-FLOWS.md`)
- `python -m app.cli canvas open|edit|close` -> bounded canvas co-authoring surface (flagged; see `docs/HUMAN-FLOWS.md` and `docs/CANVAS_CHAT_SURFACE/README.md`)
- `python -m app.cli runtime-loop` -> legacy/dev-only runtime path, not part of current baseline operations

Useful examples:

```bash
LLM_PROVIDER=mock python -m app.cli health --json
python -m app.cli watcher run --max-ticks 1
python -m app.cli pipe notes/meeting.md
python -m app.cli settings-explain --json
python -m app.cli settings-validate
```

Startup/runtime verification now treats selected text routes and embeddings explicitly:
- `checks.llm_access` verifies selected text-generation routes through no-inference preflight; `checks.llm_task_routes` remains a compatibility projection.
- `checks.embedding_index` reports `rebuild_required=true|false` and the active/stored embedding identity relationship.
- `make verify-runtime` prints the LLM access summary and the embedding-index rebuild state from inside the containerized stack.
- Index operations share the canonical text contract in `docs/DB_SCHEMA.md :: store_vector_index`.
  Every producer removes AI panels to a fixed point once, then uses those exact bytes for the
  provider call, content hash, and derived `content`/`text` aliases. A remainder containing only
  whitespace is treated as non-indexable rather than embedded or upserted as an empty vector payload;
  any prior derived vector is removed.
  `index doctor` remains read-only. During explicit `index reconcile`, a present authoritative
  source that has become canonically non-indexable is selected regardless of its stored hash or
  identity. Before deletion, reconcile locks and reclassifies that source in the same transaction as
  the conditional vector purge: a newly indexable source is embedded instead, while a source that
  disappeared retains the vector-payload fallback. The source row is never mutated.

## Startup telemetry (startup_status.json)
- Location: `tmp/startup_status.json` (workspace root on the host).
- Lifecycle: written by `scripts/start_full_system.sh` on phase changes and in the cleanup trap; the last write happens on exit. Values are merged with the existing file; fields with explicit `None`/empty values are cleared when the writer marks them as clearable.
- Fields:
  - `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `timestamp` (last write). `started_at`/`ended_at` may appear when callers add them.
  - `startup_succeeded`, `runtime_verified`, `operator_interrupted`
  - `ollama_endpoint_repaired`, `ollama_endpoint_drift`, `ollama_configured_base_url`, `ollama_effective_base_url`, `ollama_endpoint_persist_hint`
  - `llm_probe_step`, `llm_probe_cmd`, `llm_probe_rc`, `llm_probe_output_snippet`
  - `compose_up_step`, `compose_up_cmd`, `compose_up_rc`, `compose_up_output_snippet`
  - `db_probe_step`, `db_probe_cmd`, `db_probe_rc`, `db_probe_output_snippet`
- Durable fix flow:
  - If startup auto-repairs the Ollama endpoint, run `make persist-runtime-repairs` to write the working endpoint back to `.env`.
- Debugging cold-start failures after `docker compose down`:
  - Bucket A: compose-up failure → check `compose_up_*` fields; expect `exit_reason=compose_up_failed` and a short `compose_up_output_snippet`.
  - Bucket B: db container/CID failure → `db_probe_step=compose_ps_db` and an empty/failed `db_probe_output_snippet`.
  - Bucket C: exec/psql timing failure → `db_probe_step=db_env_*` or `db_probe_rc!=0`; `db_probe_output_snippet` shows the failing exec/psql error.
- What to paste into an issue/PR comment: `timestamp`, `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `compose_up_*`, `db_probe_*`, `llm_probe_*`.

## Incident handling
1. Identify the failing surface with `health`, `settings-explain`, `status`, and heartbeat/outbox checks.
2. Stabilize the runtime by reducing optional integrations only if needed for diagnosis.
3. If the incident concerns watcher auto-exec safety, record the observed allowlist, skip counters, write-guard/provenance state, and whether `CI SUMMARY GATES ok=<bool>` is green where CI is part of the rollout path.
4. Record whether the incident was observed in `dev` or `prod`, then update `docs/STATUS.md` if current operational reality changed.
5. Use the relevant companion document or runbook for recovery details.
6. For watcher, panel, or CLI-first orchestrator incidents on shipped current-state surfaces, use `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`.

Quick issue routing:
- Builder delivery/readiness/CI evidence gaps -> `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Escalation Classifier`. Advisory human flags are not authorization; recover technical evidence through the owning workflow, retaining the affected operation's block. Missing logs or conflicting report metadata do not by themselves require an owner decision. This route does not authorize runtime stabilization, deployment, or a bypass of an immediate-stop or operator gate.
- Missing dependency or local runtime startup issue -> `docs/INFRASTRUCTURE.md` and `docs/DEPENDENCIES.md`
- Health contract or degraded-state interpretation -> `docs/HEALTH.md`
- Metrics/logging interpretation -> `docs/OBSERVABILITY.md`
- Watcher/panel/orchestrator incident triage -> `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`
- Watcher/panel manual walkthrough -> `docs/runbooks/UAT_PANEL_WATCHER.md`
- Go-live/startup diagnostics -> `docs/runbooks/RUNBOOK_GO_LIVE.md`
- Prod go-live acceptance (preflight through soak, rollback rehearsal, receipt) -> `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md`

Native source-identity database diagnostics are opt-in and fail closed. Run the
`app.ops.native_source_identity_diagnostics coordinate` entrypoint only with an
immutable image and the accepted runtime's exact host source root plus exact
container source root. The coordinator reproduces the canonical non-database
registry settings, keeps source observation on `--network none`, and uses the
separate volume-free read-only database witness from the
`native-source-diagnostics` Compose profile. A diagnostic refusal never
authorizes retry, source repair, controller loading, deployment, TEST, or PROD.
See `docs/ENVIRONMENTS.md :: Native source-identity database diagnostics` for
the boundary contract.

## Companion UI Entry Surfaces

- Current Companion UI operator-visible entry surfaces include the server-rendered System Entry Point substrate: entry-state declarations, latency-ladder re-entry treatment, unified topbar/overlay host, Panel command palette, governed capture modal, memory review drawer, read-only receipts history modal, system map overlay, opt-in guidance layer, settings drawer, read-only commitment surfacing, and the state-gallery validation harness.
- Capture uses `POST /api/companion/capture`; it is a governed vault-inbox append through WriteGuard and `app.knowledge.write_ops`, with `capture.inbox.appended` emitted as metadata-only operational evidence.
- Memory review uses `GET /api/companion/memory/review-queue` and `POST /api/companion/memory/review-queue/{candidate_id}/decision`; accept/reject/revise are governed review outcomes, while defer remains non-terminal queue state.
- Parent #1782 is closed through #1795 validation. Operators should treat source-peek presentation, posture emphasis switching, and the context lane / place band as unshipped follow-ups unless a later owner-doc update promotes them.

## DB snapshot/restore

**Scope: dev-ergonomics and on-demand forensic dump — this is NOT scheduled disaster recovery.**
The vault (Obsidian iCloud) is the durable system-of-record; the database is a disposable projection.
These Makefile targets are for bug-reproduction and incident investigation only.
Do not use them as a prod DR restore path.

Snapshots and dumps are evidence/ergonomics only: they are never semantic authority and never a
mandatory restore proof. They cannot establish readiness, replace the DB outbox worker queue, or
restore lost operational ownership/lineage. See the [RSC-01 continuity classification](REBUILDABLE_SYSTEM_CONTINUITY/README.md#rsc-01-continuity-classification).

Three targets are available:

| Target | Purpose |
|---|---|
| `make db-snapshot` | Dumps the dev/test DB to a timestamped `.dump` file under `.db-snapshots/dev_<UTCstamp>.dump`. Refuses prod-looking DSNs; use `make db-dump-prod` for explicit prod forensic dumps. |
| `make db-restore` | Restores from the most-recent **dev_/test_** snapshot (or pass `SNAPSHOT=<path>` for a named file). |
| `make db-dump-prod` | Writes a timestamped forensic dump from the prod DB on demand (no scheduling). Source `.env.prod.local` first. Dump-only — it never restores. |

All three targets derive the DSN from `DATABASE_URL` / `DB_DSN` via `app/db/dsn.py::resolve_dsn()` — no hardcoded connection strings.

Host-published Postgres ports (see `docker-compose.*.yml`): **dev = `app_dev` on `15433`**, test = `app_test` on `15434`, prod = `app` on `15432`.

Dump files are written to `.db-snapshots/` which is gitignored. No retention/purge policy exists; remove old files manually.

**Restore safety (data-loss guard):**
- A bare `make db-restore` only ever considers `dev_*.dump` / `test_*.dump` snapshots — it will **never** auto-select a `prod_*.dump`. (A named `SNAPSHOT=<path>` restore of any file is still allowed for deliberate forensic work.)
- `db-restore` **refuses** to run when the resolved target DSN looks like prod (database name exactly `app`, or host port `15432`) unless you pass `ALLOW_PROD_RESTORE=1`. This stops a stray `.env.prod.local` in your shell from rewriting prod.

**Usage examples:**

```bash
# Dev snapshot + restore cycle (dev = app_dev on host port 15433)
export DATABASE_URL=postgresql://app:app@127.0.0.1:15433/app_dev
make db-snapshot                            # → .db-snapshots/dev_20260628T...Z.dump
# ...reproduce a bug, mutate state...
make db-restore                             # restores from the latest dev_/test_ snapshot
make db-restore SNAPSHOT=.db-snapshots/dev_20260628T153000Z.dump   # named restore

# Test DB is app_test on host port 15434:
#   export DATABASE_URL=postgresql://app:app@127.0.0.1:15434/app_test

# Prod forensic dump (operator-only, no automation)
source .env.prod.local
make db-dump-prod                           # → .db-snapshots/prod_20260628T...Z.dump
```

**Constraints:**
- These `make` targets are unscheduled and manual; there is no off-host/cloud backup
  strategy and no automated purge. Scheduling exists only for the separate nightly mac
  mini job `local.prod-pgdump` (dumps to `/Volumes/T7/prod-db-backups`), which is watched
  by `com.yggdrasil.prod-backup-probe` — see *Prod backup watcher* above.
- These dumps must not become a production DR restore path.
- pg_dump / pg_restore must be installed on the host (they are not bundled in containers).
## Mimer MCP adapter

The accepted Mimer MCP v1 adapter is a client-spawned stdio sidecar. Install
the standalone distribution with `pip install ./mimer-mcp-sidecar`, then start it
with `mimer-mcp --transport stdio`; it calls only the existing
loopback Mimer HTTP API. It opens no network listener, accepts no bind, TLS, or
authentication configuration, and exits when its client closes stdio. Network
transports and per-device authentication are separately gated follow-ons.

## Batch operation availability

AUTOOPS-08 provides dormant direct composition over the existing execution kernel and finite
versioned body-edit, placement and semantic owners. It installs no operator HTTP, GUI, MCP or CLI
endpoint, runtime singleton or scheduler. Authenticated installation remains with #5352 and
cross-surface capability acceptance with #5329. The [batch owner specification](YGGDRASIL_AUTONOMOUS_OPERATIONS/DELIVER_SAFE_BATCH_EXECUTION_AND_RECOVERY.md#dormant-implementation-and-supported-boundary)
defines the exact supported/refused kinds and original authority boundaries.

For an interrupted directly composed batch, preserve its frozen batch/request identities and native
receipts. Cancellation durably suppresses pending starts; already-started work reconciles through
the existing owner/kernel path. A refused recovery retains committed or unknown source evidence;
a new recovery attempt is durably uncertain before another native effect can start. Diagnostic,
queued or projection state is insufficient for source success, and an uncertain effect is never
blindly retried or a valid committed item automatically rolled back.

Repository evidence (2026-10-28): `app/operations/batch_operations.py`, the delivered native owner
bindings, and `tests/operations/test_batch_operations*.py` exercise isolated synthetic vaults,
durable native/GOV receipts, real source guards, cancellation and restart. This is repository proof,
not a production installation, deployment or channel-acceptance receipt.
