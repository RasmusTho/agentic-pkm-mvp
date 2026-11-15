---
name: Prepare certificate renewal candidate
description: Build and verify an in-memory DEV/TEST renewal candidate without operational activation.
task_id: MODEL-CERT-01
source_anchor: docs/MODEL_ACCESS_ROUTER/README.md :: Planned DEV/TEST certificate continuity
parent_capability: MODEL_ACCESS_ROUTER
parent_issue: 6575
github_issue: 6576
depends_on: []
---

# PREPARE_CERTIFICATE_RENEWAL_CANDIDATE

## Purpose

Provide a bounded, testable cryptographic building block for the future managed DEV/TEST renewal
flow. A valid candidate is neither signer authorization nor published/accepted rotation.

## What This Task Does

Given an explicitly supplied CSR, already-held issuer certificate and signing key, and exact target
policy, produce and independently verify an in-memory signed candidate. Bind the CSR signature,
issuer key/certificate and CA constraints, subject, complete intended SANs, TLS purpose, public-key
identity and bounded validity. Refuse malformed, unauthorized-by-policy, mismatched, expired or
issuer-outliving input with fixed non-green results and no candidate. Do not infer authority from
possession of a key or accept arbitrary certificate extensions from the CSR.

No API in this slice reads a key path, discovers a signer, writes a file, contacts a service,
publishes a certificate, schedules work or activates a consumer. Only disposable synthetic keys and
CSRs are used during verification. Actual signer custody, original-operation identity, durable
transaction/recovery, old/new consumer lifetimes, native journaling snapshots and shared PROD trust
remain unimplemented and must be bound through later owner-controlled slices before any live signing
or rotation.

## Concretely

A synthetic issuer and matching CSR under an explicit server or client policy yield a certificate
whose signature, issuer, public key, exact names, purpose and expiry can be verified. A different
issuer key, unexpected name, wrong purpose or invalid CSR yields no candidate and no raw input in
its diagnostic.

## Why This Matters

The current public-file preflight does not issue a candidate or establish continuity. A cryptographic
candidate builder is useful only as part of the broader managed and actually verified lifecycle.

## Acceptance Criteria

- [ ] Real synthetic server and client CSRs produce correctly signed candidates bound to the exact
  issuer, key, names, TLS purpose and validity policy.
  - Verify: `tests/model_access/test_certificate_candidate_renewal.py::test_synthetic_candidates_bind_requested_identity`
- [ ] Invalid or foreign CSR, issuer/key, CA constraints, names, purpose and lifetime refuse without
  producing a candidate or exposing private input.
  - Verify: `tests/model_access/test_certificate_candidate_renewal.py::test_invalid_candidate_inputs_refuse_without_disclosure`
- [ ] The component performs no path, network, persistence, scheduler, runtime activation or live
  credential acquisition; future callers must separately establish real authority.
  - Verify: `tests/model_access/test_certificate_candidate_renewal.py::test_candidate_builder_has_no_operational_side_effects`

## How to Verify (Pre-Merge)

Run the three referenced tests with fresh synthetic cryptographic material under the host lease.
Run focused lint/type checks and obtain independent review of cryptographic and input boundaries.

## Out of Scope

Live signing, actual signer or key loading, filesystem transactions, install/reload, consumer
adoption, runtime scheduling, recovery, PROD changes, and closing parent #6575.

## Related Docs

- `docs/MODEL_ACCESS_ROUTER/README.md :: Planned DEV/TEST certificate continuity`
- `app/model_access/codex_remote_transport.py :: _private_ingress_ssl_context`
