---
name: TARS / Proxmox Deployment Profile
description: Setup-specific host and VM placement for the TARS/Proxmox deployment
type: deployment-profile
authority: Reference for one infrastructure setup; it does not override environment, channel, or deployment contracts
source_of_truth: Live host inventory and deployment receipts
related_docs:
  - docs/ENVIRONMENTS.md
  - docs/RELEASE_CHANNELS/README.md
  - docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md
  - docs/INFRASTRUCTURE.md
  - docs/BUILDEROPS_CONTROL_PLANE/README.md
---

State: Setup-specific deployment profile. Host, guest, endpoint, and runtime claims are current only
when backed by a dated live inventory or deployment receipt.
Doc role: Reference (deployment profile)
Authority: Records the concrete placement of environments for the TARS/Proxmox setup. It does not
define what `dev`, `test`, or `prod` mean, and it does not qualify a host or authorize a deployment.
Owner: Platform and Operations System, with deployment and environment owners
Temporal class: operational
Review cadence: when host, VM, network, or deployment topology changes
Source of truth: live host inventory and deployment receipts
Last reviewed: 2026-08-28
Last verified against: no new live host readback in this documentation refactor

# TARS / Proxmox Deployment Profile

## Purpose

This profile separates one concrete infrastructure arrangement from the reusable environment and
deployment contracts. Other setups may use different physical hosts, hypervisors, VM layouts,
container runtimes, or managed services without changing those contracts.

## Profile identity

| Field | Value | Verification posture |
| --- | --- | --- |
| Physical infrastructure host | `TARS` | Setup identity; live host qualification is separate |
| Virtualization layer | Proxmox VE | Setup-specific; verify from live inventory |
| Product runtime placement | One or more Linux runtime guests/targets | Exact guest mapping requires live inventory |
| Model-service placement | Dedicated Ollama/model-service target | Setup-specific; verify from live inventory |
| BuilderOps placement | Separate BuilderOps guest or service | Must remain separate from Product Runtime |

The profile name is not a universal architecture term. A future setup should receive its own profile
under `docs/deployment/profiles/` and implement the same environment and channel contracts.

## Environment placement

The repository's current runtime evidence names the following setup-specific runtime targets. These
labels are not required by the generic environment model and must not be treated as proof that the
targets are currently reachable or that their Proxmox guest IDs are known.

| Environment | Runtime target label | Target kind | Endpoint evidence | Proxmox guest / physical placement | Live status |
| --- | --- | --- | --- | --- | --- |
| `dev` | `ygg-dev` | Linux/Tailscale runtime target | API `:18001`, UI `:8111` responded | Requires live inventory mapping | Degraded; see `docs/STATUS.md` |
| `test` | `ygg-test` | Linux/Tailscale runtime target | No reachable endpoint | Requires live inventory mapping | Unavailable; see `docs/STATUS.md` |
| `prod` | `ygg-prod` | Linux/Tailscale runtime target | API `:18000` liveness responded; UI `:8113` unavailable | Requires live inventory mapping | Functional health failing; see `docs/STATUS.md` |

Until a live inventory and deployment receipt establish the host-to-guest mapping, this table is a
placement record, not a live deployment handoff. In particular, do not infer that VM 102 hosts a
product environment.

For this setup, the dedicated model-service target is the Mac mini and is Ollama-only. It is not a
Product Runtime or BuilderOps host. Keep that fact in this profile rather than in the generic
environment or deployment contracts.

## BuilderOps separation

The TARS qualification contract currently identifies VM 102 as `builder-system`. That contract
requires BuilderOps isolation and explicitly rejects a `pkm-*` Product Compose project, production
credentials, production vault references, or production network identities on that VM. TARS
qualification and Product Runtime deployment are therefore separate concerns; see
`docs/BUILDEROPS_CONTROL_PLANE/README.md :: TARS qualification contract`.

## Contract inherited from the generic docs

This profile inherits, without redefining:

- environment selection and path scoping from `docs/ENVIRONMENTS.md`;
- channel identity, isolation, promotion, and rollback from `docs/RELEASE_CHANNELS/README.md`;
- physical deploy, health, gateway, and rollback procedure from
  `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`;
- platform and host-lifecycle boundaries from
  `docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md`.

An alternative setup is valid only when it supplies equivalent bindings and evidence for those
contracts. The generic documents must not be edited merely because the physical setup changes.

## Required profile evidence

A profile may be treated as current operational truth only when it records, or links to:

1. the physical host and virtualization identity;
2. the environment-to-runtime-target mapping;
3. guest IDs or equivalent target identities where applicable;
4. network and access boundaries without storing credentials or secret values;
5. deployment and rollback receipts for the affected channels; and
6. dated health/readiness evidence for each claimed live target.

Missing or stale evidence downgrades the profile to setup reference or planned topology. It does not
upgrade local Compose, repository fixtures, or a TARS candidate-evaluation result into deployment
authority.

## Related documents

- `docs/ENVIRONMENTS.md` — generic environment semantics and path scoping
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` — generic physical deployment contract
- `docs/RELEASE_CHANNELS/README.md` — channel identity and promotion/rollback semantics
- `docs/INFRASTRUCTURE.md` — current platform and local fallback description
- `docs/BUILDEROPS_CONTROL_PLANE/README.md` — TARS qualification and BuilderOps boundary
