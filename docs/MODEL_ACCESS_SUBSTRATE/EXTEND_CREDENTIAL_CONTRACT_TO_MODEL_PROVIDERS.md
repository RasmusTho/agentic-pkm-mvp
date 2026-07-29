---
name: Extend Credential Contract To Model Providers
description: Add model-provider identifiers to the delivered host secret contract, turn its hardcoded channel/consumer/secret allowlist into data, and stop the two CI paths that report success while their provider credential is absent.
task_id: MAS-03
source_anchor: docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 8. Migration (step 2)
parent_capability: Model Access Substrate
prerequisites: [MAS-02]
depends_on: [MAKE_BUILDER_TO_PRODUCT_LLM_DEPENDENCY_VISIBLE.md]
can_parallelize_with: []
---

State: Authored task specification (child issue #4289, filed 2026-07-29). Sibling extension of the
delivered Local Secret Provisioning mechanism; **not** a re-filing of HSP-02, which is closed (#3846 /
PR #4008).

# Extend Credential Contract To Model Providers

## Purpose

`config/secrets/host_secret_contract.json` is the only place in this repository that treats a credential
as a first-class, channel-scoped, contract-declared artifact — and it declares exactly one non-model
secret. ADR-0064 §4 makes declared API keys the default programmatic auth path for every headless
caller, which requires model-provider identifiers to live in that contract. Today they cannot:
`app/ops/host_secret_contract.py:16-18` hardcodes the permitted channel set, the single permitted
consumer, and the single permitted secret name, so adding a model provider is a code change rather than
a declaration.

The same task owns the two CI paths that report success while their model-provider credential is
absent, because they are exactly the fail-closed violation this contract exists to prevent.

## Relationship to Local Secret Provisioning

Both children of parent #3843 are delivered: HSP-01 as #3845 / PR #3888, and **HSP-02 as #3846 /
PR #4008, closed 2026-07-20**. This task therefore has no prerequisite inside #3843 and must not
re-specify the bootstrap. PR #4190 already corrected
`docs/LOCAL_SECRET_PROVISIONING/README.md :: Task order`; the dated audit remains a historical
snapshot. This task updates only the newly expanded model-provider scope.

#3843 stays open on its own two acceptance gates — a redacted dev-channel deploy receipt and the
`docs/SECURITY.md` promotion. **This task does not close #3843** and must not claim to.

## What this task does

1. Declare exactly these value-free entries in `config/secrets/host_secret_contract.json`, each for
   channels `dev`, `test`, and `prod` and consumer `builderops-model-inquiry`:
   - logical secret `openai.api-key`, child binding `OPENAI_API_KEY`, kind `api-key`;
   - logical secret `anthropic.api-key`, child binding `ANTHROPIC_API_KEY`, kind `api-key`.
   The `gpt_codex` inquiry role requires `openai.api-key`; the `fable` role requires
   `anthropic.api-key`. No value or host path enters the file. CKM/design-agent consumers receive no
   grant in this task.
2. Replace `_INITIAL_CHANNELS`, `_INITIAL_CONSUMER`, and `_INITIAL_SECRET`
   (`app/ops/host_secret_contract.py:16-18`) with declared data plus a **strict identifier grammar**.
   The v1 loader's value-free/anti-smuggling property is structural and semantic: top-level, secret,
   and consumer objects have closed schemas; duplicate keys and undeclared value-bearing fields fail;
   identifier classes are length-bounded and grammar-constrained; logical IDs must agree with their
   validation kind; child bindings are derived from logical IDs; and exact grants constrain every
   reference. Because the provider-agnostic `api-key` validator intentionally accepts any 20–512
   printable non-whitespace characters, its lexical language necessarily overlaps some legitimate
   metadata identifiers. Lexical disjointness is neither required nor claimed.
3. Make the logical-identifier-to-environment-variable mapping data. `_SECRET_ENV_NAMES`
   (`app/ops/host_secret_bootstrap.py:23`) currently hardcodes one pair; the mapping moves into the
   declared contract so a new provider is a declaration.
4. Make value-shape validation per secret **kind** rather than per secret name. `_validate_secret`
   (`app/ops/host_secret_bootstrap.py:119`) recognizes only `heimdal.raw-store-key` and returns `False`
   for everything else, which is the correct fail-closed default and must stay the default. Add an
   `api-key` kind whose value must equal its trimmed form, be 20–512 printable non-whitespace
   characters, and contain no control character, NUL, CR, or LF. Provider-specific prefixes are not
   required because key formats change; an identifier of unknown kind still fails closed.
5. Extend the existing INV-HSP-1/2/3 tests to a model-provider secret, rather than writing a parallel
   test file.
6. Repair the two green-on-absent CI paths (below).
7. Write back `docs/LOCAL_SECRET_PROVISIONING/README.md`: remove the now-superseded "runtime
   model-provider enablement" exclusion and state that
   model-provider identifiers are governed by ADR-0064 through this capability.

### The two CI paths, and why they belong here

ADR-0064 §6 makes both contract violations. They are placed in this task, not in
`DEFINE_PROVIDER_CENSUS` and not in a separate errand, because what they violate is the **credential**
contract's fail-closed invariant, not the provider set: neither `PANEL_AGENT_LLM_E2E_CI` nor
`CODEX_API_KEY` is a provider name, and the repair for each is to declare the credential it consumes
and make its absence visible. CI is one of the four bindings the audit names for this one contract
(`docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 5`).

| Workflow | Job / step | Credential | Current behaviour |
| --- | --- | --- | --- |
| `.github/workflows/ci-smoke.yaml:505-528` | `panel-llm-e2e` / `Detect live-LLM CI configuration` | `PANEL_AGENT_LLM_E2E_CI`, `LLM_PROVIDER`, `OPENAI_API_KEY` | every later step is gated on `enabled == 'true'`; unconfigured means nothing runs and the job reports success |
| `.github/workflows/architecture-ci.yaml:108-117` | `docs-guard` / `Detect Codex secret`, `Maybe install Codex CLI`, `Maybe run Codex guard` | `CODEX_API_KEY` | steps vanish silently when the secret is absent; the step also writes the secret into `$GITHUB_ENV` |

**The rule this task applies:** remove both optional paths. Neither may remain as a conditional
green-on-absent provider check. Reintroducing live provider CI requires a later bounded issue with a
declared credential backend and explicit cost/egress posture.

- **`architecture-ci.yaml` `docs-guard` — remove the Codex path.** The whole workflow is
  `workflow_dispatch`-only, so it never runs in normal CI at all; `codex run docs-guardian` has no
  counterpart in this repository's toolchain; and writing a credential into `$GITHUB_ENV` is the kind
  of disclosure surface INV-HSP-1 exists to prevent. Removal is the honest repair, and it needs no
  Actions secret.
- **`ci-smoke.yaml` `panel-llm-e2e` — remove the optional live-provider job.** It is not a required
  gate and its current green-on-absent result is false evidence.

## Concretely

```
$ python -m app.ops.host_secret_bootstrap --channel dev --consumer builderops-model-inquiry -- \
    python -c "import os; print('HOST_SECRET_RUNTIME_ENV_FILE' in os.environ, \
    'OPENAI_API_KEY' not in os.environ, 'ANTHROPIC_API_KEY' not in os.environ)"
True True True

# The mode-0600 file named by HOST_SECRET_RUNTIME_ENV_FILE contains only the
# declared OPENAI_API_KEY and ANTHROPIC_API_KEY bindings. MAS-05 owns bounded
# in-process consumption of that file; the bootstrap never copies either
# value into the child's ambient environment.

# with the Anthropic item present but the OpenAI item absent:
$ python -m app.ops.host_secret_bootstrap --channel dev --consumer builderops-model-inquiry -- true
host secret bootstrap failed for declared secret: openai.api-key
$ echo $?
1

# undeclared pair still refuses, without echoing the caller's identifiers:
$ python -c "from app.ops.host_secret_contract import load_host_secret_contract as l; \
             l().require_declared(channel='dev', consumer='not-declared', secret='openai.api-key')"
UndeclaredSecretConsumerError: undeclared host secret request
```

## Why this matters

Every headless failure this capability exists to remove is a credential failure. If the contract cannot
name a model-provider secret, `RESOLVE_MODEL_INQUIRY_CREDENTIALS_THROUGH_CONTRACT` has nothing to
resolve through and CKM has nothing to migrate to, and both would reinvent a per-consumer credential
path — which is precisely how twelve credential paths came to exist across two substrates that share
nothing.

The CI half matters for a different reason: an orchestrator whose CI reports green when unconfigured
cannot gate work. That is the argument that decided the ADR's option analysis, and leaving the two
workflows green-on-absent would leave the decision undelivered.

## Acceptance criteria

- [ ] Model-provider identifiers are declared in `config/secrets/host_secret_contract.json` and resolve
      as data, with no channel, consumer, or secret name hardcoded in `app/ops/host_secret_contract.py`.
      Verify: `tests/ops/test_host_secret_contract.py::test_model_provider_identifiers_are_declared_data`
- [ ] The exact OpenAI and Anthropic identifiers, child bindings, `api-key` validator, channel set,
      consumer, and two-role requirements match this specification.
      Verify: `tests/ops/test_host_secret_contract.py::test_model_inquiry_secret_contract_is_exact_and_value_free`
- [ ] A declared identifier whose Keychain value is absent or malformed fails the consuming process
      closed, before it starts, naming only the logical identifier and never the value.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_missing_model_provider_secret_fails_consumer_closed`
- [ ] An identifier of unknown kind still fails closed rather than being passed through unvalidated.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_unknown_secret_kind_still_fails_closed`
- [ ] The value-free/anti-smuggling property survives the move to data: undeclared value-bearing
      fields at top-level, secret, or consumer scope and duplicate keys are rejected; strict field
      grammars, logical-id/kind/binding relations, and exact grants remain enforced. Identifier and
      `api-key` lexical languages are not required to be disjoint.
      Verify: `tests/ops/test_host_secret_contract.py::test_contract_rejects_value_bearing_field`
      Verify: `tests/ops/test_host_secret_contract.py::test_identifier_grammar_rejects_out_of_grammar_names`
- [ ] `dev`, `test`, and `prod` resolve distinct Keychain accounts for the same model-provider
      identifier, and a `dev` request cannot resolve a `prod` item.
      Verify: `tests/ops/test_host_secret_contract.py::test_channel_isolation_holds_for_model_provider_secrets`
- [ ] A consumer receives only its own declared identifiers; an unrelated consumer's model-provider
      secret is unavailable to it.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_model_consumer_gets_only_allowlisted_values`
- [ ] No secret value appears in any success, failure, health, or receipt path for a model-provider
      identifier.
      Verify: `tests/ops/test_host_secret_bootstrap.py::test_model_provider_secret_is_never_disclosed`
- [ ] No workflow step in `.github/workflows/**` executes conditionally on the mere presence of a
      model-provider credential while reporting success when that credential is absent.
      Verify: `tests/ops/test_ci_smoke_workflow.py::test_no_workflow_step_is_green_on_absent_provider_secret`
- [ ] The resolution chosen for each of the two workflows is recorded with its reason.
      Verify: `doc writeback at docs/MODEL_ACCESS_SUBSTRATE/EXTEND_CREDENTIAL_CONTRACT_TO_MODEL_PROVIDERS.md :: The two CI paths, and why they belong here`
- [ ] `docs/LOCAL_SECRET_PROVISIONING/README.md` no longer excludes runtime model-provider enablement
      and records ADR-0064 scope without changing the already-correct HSP-02 delivery row.
      Verify: `doc writeback at docs/LOCAL_SECRET_PROVISIONING/README.md :: Out of scope`

## How to verify (pre-merge)

- `pytest -q tests/ops/test_host_secret_contract.py tests/ops/test_host_secret_bootstrap.py`
- `pytest -q tests/ops/test_ci_smoke_workflow.py tests/ops/test_ci_workflow.py`
- `pytest -q -m "not pg"` — full unit lane; this is credential-surface work on a hot path
- `python3 scripts/docs_guard.py`
- `python3 scripts/public_seam_lint.py --mode gate`
- Manual, with no Keychain item present: run the bootstrap for a declared model consumer and confirm a
  non-zero exit whose message contains the logical identifier and no value.

## Cross-task invariants preserved

INV-MAS-2 (credentials resolve only through the contract) is established here. INV-HSP-1..4 are
inherited unchanged. INV-MAS-6 (additive) holds: declaring identifiers changes no runtime behaviour
until a consumer resolves one, which is MAS-05 and MAS-06. Seam A is opened here — a declaration may
exist before any host holds the value — and the fail-closed criterion above is the invariant that keeps
the seam safe.

## Out of scope

The bootstrap mechanism itself (HSP-02, delivered by #3846 / PR #4008). Closing #3843 or discharging
its two remaining acceptance gates. Any consumer actually resolving a model credential — that is MAS-05
and MAS-06. Provisioning Keychain values or Actions secrets, which is an owner action. Key rotation,
cross-host sharing, cloud secret managers, and 1Password. The brokered-session backend. The provider
census, which is MAS-01.

## Related docs

- `docs/MODEL_ACCESS_SUBSTRATE/README.md` — capability contract, Seam A
- `docs/LOCAL_SECRET_PROVISIONING/README.md` — INV-HSP-1..4, identifier contract, delivered mechanism
- `docs/LOCAL_SECRET_PROVISIONING/DEFINE_HOST_SECRET_CONTRACT.md`, `docs/LOCAL_SECRET_PROVISIONING/DELIVER_RUNTIME_SECRET_BOOTSTRAP.md`
- `docs/adr/ADR-0064-model-access-substrate.md :: 4. Declared API keys are the default programmatic auth path`
- `docs/audits/MODEL_ACCESS_SUBSTRATE_2026-07-27.md :: 5. Credentials across laptop, host, channels, and CI`
- `docs/SECURITY.md :: Secrets in CI`, `docs/ENVIRONMENTS.md :: Cross-Environment Invariants`

## Related GitHub issues

One issue, filed as a **sibling** of #3843's delivered children rather than a new child of #3843. Its
`Context` must state that HSP-01 (#3845) and HSP-02 (#3846) are delivered, that this task does not
close #3843, and that filing anything named "HSP-02" would duplicate closed #3846. No credential
value provisioning is required to merge this declaration-only slice; live values are a MAS-05 parent
acceptance prerequisite.

TCD capability recommendation for the implementing agent: **Opus / xhigh reasoning** — credential and
auth surface plus CI gating, where a wrong direction is expensive and a silent weakening of a
fail-closed invariant is the worst outcome (`AGENTS.md :: Total Cost of Development`, the
auth/security/data escalation trigger). Non-binding; `issue-to-code` re-derives it.
