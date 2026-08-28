State: Specification directory (design + bounded slices). Both child tasks are delivered (HSP-01 via #3845/PR #3888; HSP-02 via #3846/PR #4008, merged 2026-07-20); parent #3843 remains open only for the redacted dev-deploy validation receipt and the `docs/SECURITY.md` promotion described under `Validation and acceptance`. Defines the shared host/deploy secret boundary for the local-first posture; it does not claim a new runtime subsystem or a shipped secret manager.
Doc role: Capability specification (feature-breakdown lane)
Authority: Owns the proposed local secret-provisioning design. Subordinate to `docs/SECURITY.md` for the security baseline, `docs/ENVIRONMENTS.md` for channel isolation, and the product owner documents of consumers it provisions.
Owner: Architecture / operations
Temporal class: strategic
Review cadence: event-driven (task merge, host-topology change, or first CI/multi-host use)
Source of truth: this directory for the proposed capability; GitHub parent/child issues are execution artifacts once filed
Last reviewed: 2026-08-12

# Local Secret Provisioning

## Outcome

Provide one small, host-local provisioning boundary for development and runtime processes without
placing credentials in Git, iCloud, BuilderOps records, Mimer content, or ordinary deploy files.
The initial implementation uses **macOS Keychain** as secret source of truth. A narrowly scoped
bootstrap resolves only the secrets a channel/process needs through a temporary owner-readable
runtime surface, cleans it up, and redacts all values from logs and receipts.

This is **boundary work**, not a new Yggdrasil/Mimer product subsystem and not a BuilderOps store:
Builder System consumers may use provider credentials for explicitly invoked development tools, while
Product/Runtime consumers may use channel-scoped runtime credentials such as
`HEIMDAL_RAW_STORE_KEY`. The bootstrap carries values; it does not decide model routing, grant
authority, retention, or product memory.

The canonical v1 capture ingress is
`~/Library/Mobile Documents/com~apple~CloudDocs/Yggdrasil/Heimdal/Capture/Inbox`. iCloud is an
ingress transport only; it is never a secret store or raw-audio archive.

## Fixed constraints

1. **No plaintext persistence.** No secret value may appear in Git-tracked config, iCloud,
   BuilderOps artifacts, Mimer/vault notes, command output, CI logs, or receipts.
2. **Least privilege by consumer and channel.** A dev capture watcher receives its raw-store key and
   watched path only; it does not receive unrelated provider or deployment credentials. `dev`,
   `test`, and `prod` secrets remain distinct.
3. **Fail closed.** A missing, malformed, or inaccessible required secret prevents the named process
   from starting; it does not select a default, print the value, or silently weaken encryption. Since
   #4489 "required" is a property the schema states rather than assumes: every declaration carries an
   explicit `optional` boolean, and only a declaration marked `optional` may be *absent* without
   failing its consumer. Optionality never covers a value that is present and malformed — that still
   fails closed, for optional and required secrets alike — so this constraint is unweakened for every
   secret that guards a shipped lane.
4. **Key material stays outside the raw volume and database.** This preserves Heimdal's raw-store
   trust boundary.
5. **No cloud secret service now.** 1Password Developer/CLI is a future migration option only when
   sharing/rotation across hosts or CI makes it worthwhile. It is not a prerequisite for v1.

### Declared identifier contract

The value-free contract declares `heimdal.raw-store-key`, `heimdal.archive-pass`, `openai.api-key`,
`anthropic.api-key`, and `github.token`, their child bindings, validation kinds, and whether each is optional. The
raw-store key is granted to `heimdal-capture-watch`, `heimdal-api-ingress`, and the one-shot
`heimdal-raw-migrate` transformer; both model-provider identifiers are granted only to
`builderops-model-inquiry`, with exact `fable` and `gpt_codex` role requirements. Every grant is
declared for `dev`, `test`, and `prod` in
`config/secrets/host_secret_contract.json`; no value or host path is stored in that file. This is the
ADR-0064 declared-API-key scope. It declares the credential boundary but does not authorize provider
selection, calls, CKM access, or fallback.

HAR-02 adds no key, rotation, or provisioning authority. Its governed deploy path bootstraps the
`heimdal-raw-migrate` consumer only when the trusted migration inventory contains HAR-02's exact
revision filename. A value-free preflight then runs before any pin, marker, volume, Docker, or
writer-stop mutation. The exact one-shot migration invocation resolves the consumer again, renames
the temporary bootstrap handle for the `migrate` service, and removes it when that invocation exits.
This second resolution closes the check/use window: missing, malformed, or shared-domain-divergent
material stops before deployment mutation, while a later change still stops before Alembic.
Unrelated migration inventories do not resolve or borrow this consumer. Long-lived services cannot
read the migrate-only handle, and an ordinary Compose invocation does not acquire one. The
repository declares and validates this delivery path; it does not claim that a host item was
created or changed.

HAR-03 adds the required `heimdal.archive-pass` identifier for the dedicated
`heimdal-cold-volume` consumer on `dev`, `test`, and `prod`. It is not shared with the raw-store
cipher domain. The consumer receives it only through HSP's mode-0600 temporary file and feeds it to
the fixed sparsebundle command over standard input. The tracked metadata, startup/deploy gates,
runbook, and receipts remain value-free; provisioning a host item is an explicit operator action.

`github.token` (#4489) is the one **optional** declaration. It is granted to `heimdal-api-ingress`
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
- **The token inherits the layer's activation condition.** `deploy_channel_compose.sh` only wraps
  compose with this consumer's bootstrap when `heimdal.raw-store-key` resolves, so a host without
  that key materializes no layer and therefore receives no `GITHUB_TOKEN` either — provisioning the
  token alone is not sufficient on the governed deploy path.

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

Cloud secret managers, 1Password installation, CI secret migration, automatic key rotation, generic
configuration management, secret discovery, provider calls, model routing, CKM grants, and
credential provisioning. Runtime consumers and provider execution remain separately governed by
ADR-0064 and the Model Access Substrate task chain.

## Related sources

- `docs/SECURITY.md :: Secrets in CI`
- `docs/ENVIRONMENTS.md :: Cross-Environment Invariants`
- `docs/HEIMDAL/FABLE_COMPANION.md :: T1 raw-store key boundary / Voice-memo capture adapter`
- `docs/HEIMDAL_CAPTURE_CLIENT/HEIMDAL_CLIENT_SCAFFOLD_AND_CAPTURE_FOLDER_BINDING.md`
