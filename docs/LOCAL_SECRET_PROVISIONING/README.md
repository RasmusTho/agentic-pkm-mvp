State: Specification directory (design + bounded slices). Both child tasks are delivered (HSP-01 via #3845/PR #3888; HSP-02 via #3846/PR #4008, merged 2026-07-20); parent #3843 remains open only for the redacted dev-deploy validation receipt and the `docs/SECURITY.md` promotion described under `Validation and acceptance`. Defines the shared host/deploy secret boundary for the local-first posture; it does not claim a new runtime subsystem or a shipped secret manager.
Doc role: Capability specification (feature-breakdown lane)
Authority: Owns the proposed local secret-provisioning design. Subordinate to `docs/SECURITY.md` for the security baseline, `docs/ENVIRONMENTS.md` for channel isolation, and the product owner documents of consumers it provisions.
Owner: Architecture / operations
Temporal class: strategic
Review cadence: event-driven (task merge, host-topology change, or first CI/multi-host use)
Source of truth: this directory for the proposed capability; GitHub parent/child issues are execution artifacts once filed
Last reviewed: 2026-10-21 (bounded TypeSafe DEV acceptance writeback; broader channel acceptance unchanged)
Last verified against: #5667 comments #6114638077, #6114724380, and #6114787299; merged BWS slices #5703, #5717, #5725, and #5732. These verify current entitlement, existing reader scopes, the MARR non-prod binding, active encrypted reader services on all three channel VMs, and the accepted normal-writer model; Product/Builder acceptance and full channel deployment/runtime acceptance remain separate.

# Local Secret Provisioning

## Outcome

Provide one small, host-local provisioning boundary for development and runtime processes without
placing credentials in Git, iCloud, BuilderOps records, Mimer content, or ordinary deploy files.
The Mac-hosted implementation keeps existing local secrets and the MARR read-only BWS bootstrap
token in **macOS Keychain**. Merged PR #5803 and follow-up #5808 deliver the repository path for the TypeSafe provider
key through the existing `non-prod` BWS project and reader identity. The #5667 receipt #6114638077
verifies the current Free-plan entitlement, both existing reader-token scopes, the imported MARR key,
and the current-main `marr-server-dev` consumer check. This does not complete the separate
Product/Builder acceptance under #5764 or the broader integrated deployment/runtime acceptance under
#5667.
Heimdal owns the lifecycle of external-helper credentials, while a narrowly scoped
bootstrap resolves only the secrets a channel/process needs through a temporary owner-readable
runtime surface, cleans it up, and redacts all values from logs and receipts.

This is **boundary work**, not a new Yggdrasil/Mimer product subsystem and not a BuilderOps store:
Builder System consumers may use provider credentials for explicitly invoked development tools, while
Product/Runtime consumers may use channel-scoped runtime credentials such as
`HEIMDAL_RAW_STORE_KEY`. The bootstrap carries values; it does not decide model routing, grant
authority, retention, or product memory.

For external helper systems, Builder Vault records the non-secret credential reference and Heimdal
ownership metadata. The Mac-hosted path uses macOS Keychain; Linux channel VMs use the accepted BWS
contract defined in docs/CLOUD_SECRET_PROVISIONING/README.md. The #5667 receipt #6114638077 verifies
active encrypted reader services on ygg-dev, ygg-test, and ygg-prod; broader integrated channel
qualification remains open.
External provider identities, including the Discord webhook identity, remain owned and provisioned
outside this design; the value-free binding is declared below and is not a value stored in the Vault
or repository.

The canonical v1 capture ingress is
`~/Library/Mobile Documents/com~apple~CloudDocs/Yggdrasil/Heimdal/Capture/Inbox`. iCloud is an
ingress transport only; it is never a secret store or raw-audio archive.

## Linux Bitwarden Secrets Manager

Linux explicitly selects `HOST_SECRET_PROVIDER=bws`; failed or missing BWS access never falls back
to Keychain. The reader uses the explicitly selected project for channel lookup and resolves only
code-declared consumer bindings. The existing reader identities may access both projects under the
accepted store-level policy; dev/test still select non-prod and prod selects prod. BWS administration uses `scripts/secrets` on Demerzel with the admin token in its login
Keychain; a VM receives only its reader's encrypted systemd credential. The
[2026-10-11 owner receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667#issuecomment-6114787299) accepts this sole supported normal writer,
retains the human Organization Owner as break-glass, and accepts deliberate same-user bearer use
outside the controller as a residual. No separate writer daemon or shared fencing is required for
this one-owner setup. Reassess before extra operators/controllers or prod secrets requiring
confidentiality; this is host custody and normal-path policy, not executable confinement.
BWS-03 / #5679 and PR #5732 delivered the repository installer. The #5667 receipts #6114638077 and
#6114724380 verify active encrypted channel credentials and retirement of the unused generic helper
and extra shared token on all three channel VMs. The parent remains open for integrated deployment
and runtime acceptance.

The BWS-04 supervisor unit uses
`LoadCredentialEncrypted=bws-machine-account-token:/var/lib/yggdrasil/bws-tokens/%i/current`
and `BWS_ACCESS_TOKEN_FILE=%d/bws-machine-account-token`. It admits a value-free request only after
the host controller's selected-consumer parity check. Same-ID retries join the existing worker;
a missing durable terminal receipt leaves admission pending. The normal-writer decision on #5667
is accepted; bootstrap still requires the existing local qualification receipt described by the
deployment owner. The owner decision does not supply that local file or complete live deployment
qualification. Explicit `--existing-secrets-only` deployment retains its read-only qualification exception.

PostgreSQL alone uses file delivery: a root-owned `0440` source, group `LOCAL_GID`, under root-only
`0700` tmpfs is mounted into the six authorized database services. Direct DSNs must be credential-free;
one database resolver reads `DATABASE_PASSWORD_FILE` in process memory for app config, migrations,
and direct DB clients. Missing files and password-bearing overrides fail closed. Initialized roles
require real password authentication; updating BWS or its file does not rotate a database role.
The deployment owner document describes the DB-only cold-start probe, lifecycle, and pending recovery.

Mac Keychain consumers retain their existing bindings and cleanup behavior. Repository tests and
code-delivery receipts prove only the fake-backed contract; separate #5667 receipts verify the
current entitlement, reader scopes, MARR binding, encrypted reader services, and retired legacy
helper/token. Those receipts do not establish complete target/action-bound channel acceptance, so
parent #5667 remains open for that gate.

## Fixed constraints

1. **No plaintext persistence.** No secret value may appear in Git-tracked config, iCloud,
   BuilderOps artifacts, Mimer/vault notes, command output, CI logs, or receipts.
2. **Least privilege by consumer and channel.** A dev capture watcher receives its raw-store key and
   watched path only; it does not receive unrelated provider or deployment credentials. `dev`,
   `test`, and `prod` secret values remain distinct except for the narrow BWS exception approved in
   #5667: `openai.api-key`, `anthropic.api-key`, `github.token`, and `discord.webhook` use one
   externally issued `shared/` value mirrored in the prod and non-prod BWS projects. This records
   the accepted tradeoff that a non-prod project reader can retrieve those same provider values used
   by prod. No other identity is shared across channels, and this exception does not widen consumer
   grants or change the dev capture watcher's least-privilege grant.
3. **Fail closed.** A missing, malformed, or inaccessible required secret prevents the named process
   from starting; it does not select a default, print the value, or silently weaken encryption. Since
   #4489 "required" is a property the schema states rather than assumes: each secret carries an
   explicit global `optional` boolean, and a consumer may separately declare that an otherwise
   required secret can be absent for that consumer. The raw-store key remains globally required and
   is optional for `heimdal-api-ingress`, whose media/screen lanes report unavailable without
   encryption, and for `heimdal-raw-migrate`, whose locked Alembic transaction reads it only when
   legacy rows need identity verification. Capture-watch still requires it when selected.
   Optionality never covers a value that is present and malformed — that still fails closed.
4. **Key material stays outside the raw volume and database.** This preserves Heimdal's raw-store
   trust boundary.
5. **Mac Keychain remains the source for existing Mac secrets and the BWS bootstrap token.** TSO-07
   (#5801, merged PR #5803) and #5808 deliver the repository lookup for the TypeSafe provider key
   from the existing `non-prod` BWS project through the `non-prod-reader` identity. Existing reader
   scope and MARR binding are verified by #5667 comment #6114638077; full channel acceptance remains
   open under #5667. This does not change other Mac Keychain bindings or the
   explicit Linux channel project mapping.

### Declared identifier contract

The existing BWS-backed value-free declarations are `heimdal.raw-store-key`, `heimdal.archive-pass`, `openai.api-key`,
`anthropic.api-key`, `github.token`, and `discord.webhook`, their child bindings, validation kinds, and whether each is optional. The
raw-store key is granted to `heimdal-capture-watch`, `heimdal-api-ingress`, and the one-shot
`heimdal-raw-migrate` transformer. The existing `openai.api-key` grants are `builderops-model-inquiry`
with the `model_inquiry` role and `builderops-ckm-semantic` with the `ckm_semantic` role;
`anthropic.api-key` remains a declared identity without a consumer grant. These pre-existing grants are
declared for `dev`, `test`, and `prod` in
`config/secrets/host_secret_contract.json`; no value or host path is stored in that file. This is the
ADR-0064 declared-API-key scope. It declares the credential boundary but does not authorize provider
selection, calls, CKM access, or fallback.

Karakeep's BWS-only declarations are channel-scoped under `non-prod` on `dev` and `test`:
`karakeep.session-token` goes only to `karakeep-service-web`, `karakeep.search-token` only to
that web consumer and `karakeep-service-search`, `karakeep.api-key` only to
`heimdal-karakeep-fetch`, and the password-kind `karakeep.account-pass` only to
`karakeep-account-setup`. There is no production, Mimer, unrelated consumer or Keychain fallback
grant. Service startup selects only the web/search consumers; account/API-key issuance follows
startup as separately authorized operational work. The finite preparation and ephemeral delivery
procedure is owned by
`docs/KARAKEEP_MIMER_ACQUISITION/DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md :: Test-channel placement and prerequisites`.
These are repository bindings, not live installation or KMA-06 acceptance evidence.

The MARR-only `typesafe.api-key` repository binding resolves the exact
`dev/typesafe.api-key` identity from the existing non-prod BWS project through the `non-prod-reader`
identity. The supported normal admin writer reads pre-state and writes this project through
Demerzel's designated controller under the accepted #5667 model; the same-user residual above
remains explicit. The non-prod and prod reader project scope is an accepted
one-operator store risk; code-level channel selection and the MARR consumer allowlist remain explicit.
The BWS reader token remains a separate Keychain bootstrap credential under service
`yggdrasil.bws-reader`, account `non-prod-reader.token`; it is not an admin credential and stays on
the MARR server path. The live receipt #6114638077 verifies BWS entitlement, both reader identities'
access to both projects, the imported MARR item and its current-main consumer check, plus active
encrypted reader services on all three channel VMs. Product and Builder keep distinct
caller policies, caller credentials, and owner model profiles; neither receives or resolves the MARR
server's provider key. Codex and Claude runtime consumers have no grant; direct development calls
are separately governed under #5778.

Repository tests and code-delivery receipts verify the declaration with fake sources; they do not
prove host provisioning or activation. Separate #5667 receipts above verify the specific live
entitlement, reader, token, cleanup, and MARR facts they report, not the complete channel
deployment/runtime acceptance.
Any live MARR runtime use requires owner confirmation of rotation after the earlier exposure, scoped MARR dev
host installation, explicit one-call authorization with synthetic input, and a redacted receipt.
The separate actual Product and Builder DEV receipts are verified under
[TypeSafe development host acceptance](../TYPESAFE_SYSTEM_ONE/README.md#typesafe-development-host-acceptance).
Both allowances are consumed; ordinary routes remain off and broader #5667 channel acceptance
retains its own gates. The original repository slice performed no rotation, Keychain read/import,
installation, live provider call or channel activation; the linked operational receipts supply the
separate DEV evidence.

The Mac model-access executor is the dev-only `model-access-executor` consumer of the existing
`openai.api-key` (owner decision on [#3429](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3429#issuecomment-6461562895),
#6386). It serves only the explicit `openai_api` evaluation transport; Product model defaults and
routes are unchanged. `scripts/start_model_access_executor.sh` launches the executor through
`app.ops.host_secret_bootstrap --provider keychain --channel dev --consumer model-access-executor
--run-on-credential-unavailable`. The executor reads the binding from the bootstrap runtime file, and
a missing item still starts it with that transport reporting `credential_unavailable`. The owner
provisions the item once, interactively, so the value never enters argv, shell history, or an agent:
`security add-generic-password -U -s yggdrasil.host-secrets -a dev:model-access-executor:openai.api-key -w`
(with `-w` last, `security` prompts for the value). This repository support is not live activation:
the running launchd job must separately be switched to this launcher from a release that contains it.

The Discord binding is granted only to the Heimdal-owned `heimdal-external-alerts` consumer on
`dev`, `test`, and `prod`, and is one-way notification transport only. Creating, rotating, deleting,
or live-validating the provider identity remains external operational work.

HAR-02 adds no key, rotation, or provisioning authority. Its governed deploy path bootstraps the
`heimdal-raw-migrate` consumer only when the trusted migration inventory contains HAR-02's exact
revision filename. A value-free preflight runs before pin, marker, volume, Docker, or writer-stop
mutation. The migration consumer tolerates an absent key; HAR-02's source-table lock and transaction
decide whether the key is needed. An empty legacy table migrates without a key, while rows without a
valid key roll back before legacy schema or encrypted bytes change. The exact one-shot migration
invocation resolves the consumer again, renames the temporary bootstrap handle for the `migrate`
service, and removes it when that invocation exits. Present malformed or shared-domain-divergent
material fails before migration. Unrelated migration inventories do not resolve or borrow this
consumer. Long-lived services cannot read the migrate-only handle, and an ordinary Compose invocation
does not acquire one. The repository declares and validates this delivery path; it does not claim
that a host item was created or changed.

HAR-03 adds the required `heimdal.archive-pass` identifier for the dedicated
`heimdal-cold-volume` consumer on `dev`, `test`, and `prod`. It is not shared with the raw-store
cipher domain. The consumer receives it only through HSP's mode-0600 temporary file and feeds it to
the fixed sparsebundle command over standard input. The tracked metadata, startup/deploy gates,
runbook, and receipts remain value-free; provisioning a host item is an explicit operator action.

`github.token` (#4489) is the one **globally optional** declaration. `heimdal.raw-store-key` is
globally required but absent material is tolerated by `heimdal-api-ingress` and
`heimdal-raw-migrate`; HAR-02's table lock and transaction decide whether the key is needed for
existing legacy rows. The active capture-watch consumer always requires it. This preserves degraded
API operation without weakening identity verification or encryption for raw data. `github.token` is
granted to `heimdal-api-ingress`
so the BuilderOps cockpit's `github-live` plane can read GitHub from inside the `api` container via
`gh`, which reads `GITHUB_TOKEN` from its own environment. It must be optional because the
bootstrap is fail-closed over every declared secret for a consumer: a required GitHub token would
make a Keychain item mandatory on `dev`, `test`, **and** `prod`, and a host without one would lose
the Heimdal media/screen ingress lanes that share this consumer's layer. Two properties follow, and
both are deliberate:

- **The grant is per-consumer, not per-channel.** A consumer's channels and its secrets are separate
  flat lists, so `github.token` is declared on all three channels. It is inert wherever nothing is
  provisioned and wherever no channel binds `COCKPIT_GITHUB_REPO` (`dev` and `prod` bind it; `test`
  does not), so least privilege holds in effect.
- **The Keychain path keeps its existing layer coupling.** Its Compose helper only wraps the API
  with this bootstrap when `heimdal.raw-store-key` resolves, so that path delivers no `GITHUB_TOKEN`
  while the raw key is absent. The BWS VM path resolves the API consumer's bindings directly and
  may deliver `GITHUB_TOKEN` without the raw key; in that case only the media/screen ingress lanes
  are unavailable. Provisioning the token alone remains insufficient for those raw-data lanes.

The external-alert binding `discord.webhook` is declared for the Heimdal-owned
`heimdal-external-alerts` consumer on `dev`, `test`, and `prod`. The consumer receives only the
one-way Discord webhook binding through the same temporary mode-0600 runtime env-file boundary;
provider/account/channel/webhook enactment remains an external Heimdal operation and is not implied
by the repository declaration.

The committed repository binding is not deployment or credential-presence evidence. The read-only
prod prerequisite reports separate booleans for `github.token` and the coupled
`heimdal.raw-store-key`; it creates, changes, persists, or reveals neither value. Repository
configuration therefore never substitutes for host provisioning or a deployed-host receipt.

The v1 Keychain service is pinned to the stable non-secret namespace
`yggdrasil.host-secrets`, and its account is derived by percent-encoding each
`{channel}:{consumer}:{secret}` component before colon-joining the declared tuple, so distinct
tuples cannot collide and each channel resolves a distinct item. The loader accepts only
grammar-valid, contract-declared identifiers. Identifier namespaces are length-bounded, require
logical-id/validation-kind agreement, and derive each child binding from its logical identifier.
Value-freedom is structural and semantic: the schema is closed at every level, duplicate keys fail,
declarations carry no value field, and exact grants constrain every identifier. `optional` is a
required field on every declaration for exactly this reason — an omitted field would be an implicit
default in a schema that has none. Identifier strings and the deliberately provider-agnostic
`api-key` value validator are not required to have disjoint lexical languages; `token` shares that
validator rather than introducing a second near-identical grammar for the same shape of opaque
bearer string.
Contract JSON must use unique object keys; a duplicate declaration fails closed rather than allowing a
value to be hidden behind a later canonical field.
The delivered HSP-02 bootstrap resolves each consumer's allowlist into a temporary mode-0600 file.
The child receives only `HOST_SECRET_RUNTIME_ENV_FILE`; declared secret bindings are never copied
into its ambient environment.

Status 2026-07-30: both model-provider identifiers remain declared and are **intentionally
unprovisioned** by owner cost ruling
(`docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner cost ruling on the
model-inquiry path`); `credential_unavailable` on their resolution path is expected state, not a
provisioning gap to escalate. `heimdal.raw-store-key` provisioning is unaffected.

## Task order

| Order | Task | ID | Prerequisite | Outcome |
| --- | --- | --- | --- | --- |
| 1 | [Define host secret contract](DEFINE_HOST_SECRET_CONTRACT.md) | HSP-01 | — | delivered by [#3845](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3845) / PR #3888: names, consumer allowlist, Keychain access and redaction contract |
| 2 | [Deliver runtime secret bootstrap](DELIVER_RUNTIME_SECRET_BOOTSTRAP.md) | HSP-02 | HSP-01 | delivered by [#3846](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3846) / PR #4008 (merged 2026-07-20): bootstrap, channel integration and fail-closed/redaction tests |
| Evidence | Delivered [#3830](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3830) | — | completed 2026-07-16 | redacted dev Keychain provisioning and healthy capture-watch receipt; it is not a child or dependency |

## Cross-task invariants

- **INV-HSP-1 — value non-disclosure.** No success, failure, health, or receipt path writes a secret
  value. Tests exercise failure paths as well as successful launch.
- **INV-HSP-2 — channel isolation.** Selecting `dev` cannot resolve `test` or `prod` secret names;
  environment selection never bypasses policy.
- **INV-HSP-3 — consumer minimization.** A bootstrap invocation resolves only a declared consumer's
  allowlisted names. New names require a contract change and test.
- **INV-HSP-4 — stable raw-key lifecycle.** A raw-store key is generated once into Keychain and is
  never rotated by bootstrap. Rotation is a separate migration because encrypted evidence must remain
  readable until governed deletion.

## Capability acceptance criteria

- [ ] A declared dev runtime consumer can receive its required secret without the value appearing in
      tracked config, process logs, or a redacted receipt.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_runtime_secret_is_injected_and_redacted`
- [ ] A missing or malformed secret prevents the intended process from starting and names only the
      logical secret identifier.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_or_malformed_secret_fails_closed`
- [ ] `dev`, `test`, and `prod` resolve distinct allowlisted identifiers.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_channel_and_consumer_are_isolated`
- [ ] The delivered #3830 dev receipt remains usable as prior evidence, and HSP-02 proves its
      bootstrap does not regress that capture-watch health path.
      Verify: parent-issue redacted `scripts/deploy_channel.sh deploy dev` validation receipt, compared with #3830

## Validation and acceptance

Each child PR proves its named tests and posts a receipt on the parent. #3830 is prior dev-channel
evidence, not a future task. After HSP-02, a new redacted parent validation receipt proves bootstrap
did not regress capture-watch health. Acceptance is that receipt plus an owner-doc update to
`docs/SECURITY.md` describing the delivered mechanism without values or host identifiers.

## Out of scope

Linux BWS provisioning is specified in docs/CLOUD_SECRET_PROVISIONING/README.md; this directory
continues to own the Mac Keychain contract. 1Password installation, CI secret migration, automatic key
rotation, generic configuration management, secret discovery, provider calls, model routing, CKM
grants, and credential provisioning remain out of scope. Runtime consumers and provider execution
remain separately governed by ADR-0064 and the Model Access Substrate task chain.

## Related sources

- `docs/SECURITY.md :: Secrets in CI`
- `docs/ENVIRONMENTS.md :: Cross-Environment Invariants`
- `docs/HEIMDAL/FABLE_COMPANION.md :: T1 raw-store key boundary / Voice-memo capture adapter`
- `docs/HEIMDAL_CAPTURE_CLIENT/HEIMDAL_CLIENT_SCAFFOLD_AND_CAPTURE_FOLDER_BINDING.md`
