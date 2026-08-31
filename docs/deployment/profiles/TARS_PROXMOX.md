---
name: TARS / Proxmox Deployment Profile
description: Setup-specific BuilderOps placement and qualification posture for TARS/Proxmox
type: deployment-profile
authority: Reference for one infrastructure setup; it does not override environment, channel, or deployment contracts
source_of_truth: Fresh qualification input and deployment receipts
---

State: Setup-specific deployment profile. It is not a live host qualification or deployment receipt.
Doc role: Reference (deployment profile)
Authority: Records only the TARS/Proxmox-specific posture that the generic deployment contract must
not absorb. It does not qualify a host or authorize a deployment, and it does not define environments.
Owner: Platform and Operations System, with the BuilderOps deployment owner
Temporal class: operational
Review cadence: before a TARS BuilderOps deployment and whenever host, VM, network, or disk posture changes
Source of truth: a fresh qualification input and deployment receipts
Last reviewed: 2026-08-31
Last verified against: repository deployment contract, `product_tars_channel_topology.v1`, and no live TARS/Proxmox readback in this slice

# TARS / Proxmox Deployment Profile

## Purpose

This profile isolates one TARS/Proxmox setup from the portable BuilderOps deployment contract.
Alternative hosts, hypervisors, VM layouts, container runtimes, and alerting mechanisms may satisfy
the generic contract with equivalent evidence.

## Product Runtime channel placement boundary

This profile selects the TARS-hosted Linux VM topology as the intended placement for the Product
Runtime `dev`, `test`, and `prod` channels. It does not invent channel VM identities or assert live
residency. A fresh, redaction-safe `product_tars_channel_topology.v1` qualification input must bind
each channel to its VM and engine identity, source/image identity, private ingress/auth class,
health/version evidence, data/backup/rollback boundary, observed-at time, and explicit gaps/refusals.
Until that input and later operator acceptance exist, placement remains a repository contract only.

Demerzel/Mac mini is a control, development, client, and operator computer, not a Product Runtime
channel host. Local Compose/Colima is a non-authoritative development fallback. VM 102
(`builder-system`) remains the separate complete Builder System / Dev System target and must not
host a `pkm-*` Product Runtime project or share its Product engine.

Provider/model selection is outside placement and is resolved by capability configuration. This
profile carries no named provider, model, or Codex-only architecture decision.

## Complete Dev System placement boundary

The TARS qualification contract identifies VM 102 (`builder-system`) as the intended cohesive home
for the complete Builder System / Dev System, including Dev UI as one read-only projection and the
BuilderOps control plane and internal providers. That is a candidate-policy identifier, not a live
deployment assertion. The complete topology is owned by
`docs/BUILDEROPS_CONTROL_PLANE/README.md :: Complete Dev System VM-102 topology contract`; every
unresolved component remains a named reconciliation gap.

The candidate must remain separate from Product Runtime: it must not host a `pkm-*` Product Compose
project or carry Product production credentials, vault references, or network identities. Strict
host-key verification is required for any operational readback. A failed or unavailable host
ownership inventory is evidence of an open qualification gate, not permission to weaken SSH policy.

The ordered schemas and rollback-baseline rules are owned only by the
[VM-102 evidence and receipt contract](../../BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract).
This profile supplies setup-specific qualification evidence and refuses missing ownership,
identity, ingress, health, or rollback evidence; it does not redefine the receipt chain or record
live residency, deployment, health, or owner acceptance.

## Disk and WAL headroom policy

No current VM disk capacity, used-space value, or free-space value is asserted here. Before a TARS
deployment or operational change, a fresh qualification input (no more than 24 hours old and
fingerprint-verifiable) must establish the relevant disk and volume facts. Only that fresh
qualification input may bind this setup-specific profile to current disk/headroom evidence.

For the rebuildable local BuilderOps posture, PostgreSQL keeps both `max_wal_size` and
`max_slot_wal_keep_size` at 2 GiB. The local database health guard refuses WAL growth above 2 GiB
or a data-volume usage at or above its configured threshold. These are bounded local-disk guardrails,
not backup, point-in-time recovery, or restore evidence. The generic deployment contract owns the
portable policy; this profile only names its TARS qualification input.

## Probe and alerting posture

The repository contains a macOS launchd BuilderOps outage probe under
`ops/host-setup/mac-mini/`. It is not a Linux probe and does not prove a Linux installation. A
Linux service/timer that checks the BuilderOps readiness endpoint and local database health guard,
then sends the configured outage/recovery alert, is a required-but-not-yet-installed live
prerequisite for any TARS BuilderOps deployment receipt. Installation, credential binding, schedule,
and live alert delivery require their own fresh operational evidence and are outside this repository
slice.

## Inherited generic contract

This profile inherits, without redefining:

- environment selection and path scoping from `docs/ENVIRONMENTS.md`;
- channel identity, promotion, and rollback from `docs/RELEASE_CHANNELS/README.md`;
- portable BuilderOps deployment, loopback exposure, authenticated private ingress, and health-gate
  policy from `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`; and
- TARS candidate policy from `docs/BUILDEROPS_CONTROL_PLANE/README.md`.

A fresh qualification result, a passing repository test, or this profile never proves a live host
mutation, deferred durability capability, network reachability, or authority cutover.
