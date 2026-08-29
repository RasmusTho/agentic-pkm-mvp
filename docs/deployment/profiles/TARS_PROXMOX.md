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
Last reviewed: 2026-08-29
Last verified against: repository deployment contract only; no live TARS/Proxmox readback in this slice

# TARS / Proxmox Deployment Profile

## Purpose

This profile isolates one TARS/Proxmox setup from the portable BuilderOps deployment contract.
Alternative hosts, hypervisors, VM layouts, container runtimes, and alerting mechanisms may satisfy
the generic contract with equivalent evidence.

## BuilderOps placement boundary

The TARS qualification contract identifies VM 102 (`builder-system`) as the intended isolated
BuilderOps candidate. That is a candidate-policy identifier, not a live deployment assertion. The
candidate must remain separate from Product Runtime: it must not host a `pkm-*` Product Compose
project or carry Product production credentials, vault references, or network identities. See
`docs/BUILDEROPS_CONTROL_PLANE/README.md :: TARS qualification contract` for the owner contract.

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
mutation, backup/restore result, network reachability, or authority cutover.
