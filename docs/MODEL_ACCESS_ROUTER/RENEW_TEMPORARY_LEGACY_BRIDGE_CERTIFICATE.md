---
name: Renew the temporary legacy bridge certificate
description: Renew and verify the temporary Mac legacy bridge certificate through its existing owner.
task_id: MODEL-CERT-02
source_anchor: docs/MODEL_ACCESS_ROUTER/README.md :: Planned DEV/TEST certificate continuity
parent_capability: MODEL_ACCESS_ROUTER
parent_issue: 6575
github_issue: 6581
depends_on: [MODEL-CERT-01]
---

# RENEW_TEMPORARY_LEGACY_BRIDGE_CERTIFICATE

## Purpose

Replace the previously used one-time legacy candidate and switch tools with one schedulable,
reviewable operation for the actual temporary Mac legacy bridge. Retire it when that bridge is
replaced by a verified permanent route. A source change or synthetic pass is neither installation
nor acceptance of the wider DEV/TEST certificate-continuity outcome in #6575.

## What This Task Does

Implement the fixed GUI-domain `com.agenticpkm.model-access-legacy-bridge` flow against its actual
user-owned ingress config and PKI. Before any sign or switch, bind one immutable operation to the
qualified LaunchAgent and exact Apache generation, config, existing leaf, CSR, CA, key identity,
server purpose, names, validity, target and every affected caller. Use the MODEL-CERT-01 candidate
primitive and existing `.legacy-bridge-switch.lock`. Reconcile the previously used one-shot
pending/terminal/backup evidence and refuse unresolved, foreign or changed state. A caller-supplied
callback or possession of a key is not operational authorization.

Under that same owner and lock, reserve the operation before signing; stage and verify a unique
candidate; retain the exact previous config and leaf; atomically replace only the legacy config;
reload the same qualified Apache generation once; and verify the public leaf on the actual mTLS
connection for each still-qualified caller. Preserve metadata and fsync the relevant files and
directories. A lost reply, crash, uncertain signer/reload, foreign writer or identity drift remains
UNKNOWN and never authorizes a repeated sign, reload or inference. A bounded rollback requires the
same original owner, operation and positively qualified previous state, followed by old-leaf and
caller verification.

Supply a fixed schedulable entry with a finite, configurable cadence no slower than six hours and
start renewal when seven days remain before expiry, subject to the CA validity and admitted policy.
A late run alerts on the missed deadline but may perform one otherwise-qualified original operation;
it must not treat elapsed time as authority to replay an unknown effect. A not-due run creates no
signing operation. Unavailable signer, failed switch, unknown operation or
missed deadline must produce a value-free non-green result and use a positively qualified existing
operational alert path; a qualified independent observer must detect a missed scheduler execution.
Do not report activation-ready when this alert path, scheduler owner or supported login/restart
lifecycle is absent. Tests use disposable identities, processes, services and alert transport; they
do not send real notifications or install a scheduler.

The shared Product CA may also serve PROD. Do not change CA key, CA serial, CA/client trust,
ordinary Product listeners, guest files or PROD. Existing TLS contexts and active native journaling
snapshots can outlive file changes: preserve compatible old identity/trust and do not invalidate or
replay any in-flight operation. Verify old and new caller behavior with qualified consumers rather
than treating file replacement or one listener as adoption. Actual runtime use requires separately
qualified signer custody, exact original operation, all affected consumers, monitoring and owner
coordination; until then the effect remains closed.

## Concretely

A synthetic scheduled owner with a matching CSR and issuer completes one signed renewal and
qualified legacy-only activation; old and new TLS clients work with the preserved trust, and other
listeners and PROD-like files remain unchanged. A changed service, prior unresolved request,
missing signer or lost response fails without replay and yields the corresponding qualified alert.
No-due checks do not sign or reload.

## Acceptance Criteria

- [ ] Fixed Mac legacy admission binds the exact original LaunchAgent/Apache, PKI/CA/CSR and prior
  operation, uses the existing switch lock, and refuses identity, authority, consumer or pending-state
  drift before signing.
  - Verify: `tests/ops/test_legacy_bridge_certificate_renewal.py::test_legacy_owner_and_prior_operation_are_bound`
- [ ] Disposable PKI and an owned legacy service exercise signed candidate, atomic legacy-only config
  switch, same-generation reload and actual presented-leaf/mTLS verification, preserving old
  material and Product/PROD-like state.
  - Verify: `tests/ops/test_legacy_bridge_certificate_renewal.py::test_scheduled_legacy_renewal_end_to_end`
- [ ] Crashes and lost replies around signing, publication, reload and readback preserve the original
  operation, report UNKNOWN and never blindly repeat an effect; only a positively qualified original
  state permits bounded rollback.
  - Verify: `tests/ops/test_legacy_bridge_certificate_renewal.py::test_legacy_operation_reconciles_without_replay`
- [ ] A fixed schedulable entry renews before expiry, does not produce repeated operations when not due
  or unresolved, and uses a qualified existing alert path for missing signer, failed activation or
  missed deadline; existing and new clients and native snapshots remain correctly protected.
  - Verify: `tests/ops/test_legacy_bridge_certificate_renewal.py::test_scheduler_alerts_and_preserves_consumers`

## How to Verify (Pre-Merge)

Use disposable PKI, process and filesystem fixtures under the host lease. Exercise the real fixed
entry, contention, earlier pending/terminal evidence, changed identity and every crash boundary.
Prove synthetic mTLS and both client lifetimes, the independent missed-run alarm, exact rollback and
PROD-like non-impact. Obtain independent security/state-machine review and exact-head CI. Synthetic
evidence does not establish installed owner, actual keys, guest identity or operational health.

## Out of Scope

Real key reads, signing, switching, notification delivery or scheduler installation during
development; client/CA rotation, shared PROD changes and #6575 acceptance. The separate optional
Tailnet route from #6550 is not replaced by this temporary task.

## Related Docs

- `docs/MODEL_ACCESS_ROUTER/README.md :: Planned DEV/TEST certificate continuity`
- `docs/MODEL_ACCESS_ROUTER/PREPARE_CERTIFICATE_RENEWAL_CANDIDATE.md`
- `docs/LLM_ROUTING.md :: Configuration precedence`
