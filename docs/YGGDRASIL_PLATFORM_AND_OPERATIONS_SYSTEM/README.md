State: Accepted target-state ecosystem enabling-system specification (owner decision, 2026-08-15). This document establishes an ownership boundary; it does not claim that a separately delivered platform implementation, service, or control plane exists.
Doc role: System specification / operational-platform boundary owner
Authority: Defines the scope, exclusions, script-classification rule, and documentation hierarchy for the Yggdrasil Platform and Operations System. It is subordinate to Product/Runtime owner documents for product behavior and current runtime truth, and to the Builder System owner documents for development delivery.
Owner: Yggdrasil ecosystem architecture / operational platform
Temporal class: strategic
Review cadence: event-driven, when operational topology or an ownership boundary changes
Source of truth: Owner decision 2026-08-15, grounded in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, `docs/architecture/system-context-overlay.md`, `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`, `docs/INFRASTRUCTURE.md`, and `docs/OPERATIONS.md`
Last reviewed: 2026-08-15
Last verified against: `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, `docs/architecture/system-context-overlay.md`, `docs/architecture/SBS_OPERATING_MODEL.md`, `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`, `docs/ENVIRONMENTS.md`, `docs/RELEASE_CHANNELS/README.md`, `docs/INFRASTRUCTURE.md`, `docs/HEALTH.md`, `docs/OBSERVABILITY.md`, `docs/SECURITY_ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md`, and `ops/host-setup/README.md`

# Yggdrasil Platform and Operations System

## Decision and system position

The **Yggdrasil Platform and Operations System** is a distinct ecosystem enabling system. It is
parallel to the Builder System and supports the lifecycle of the Mimer Product/Runtime System.
It is **not** a Product/Runtime SBS subsystem, an additional SBS macro-domain or control boundary,
or a new runtime product capability.

Its purpose is to make the operating platform legible, supportable, and replaceable without
turning operational machinery into product semantics. This specification names a durable ownership
boundary. It does not assert that today's distributed scripts, Compose files, host setup, or
runbooks have already become one separately deployed platform.

## Scope

The Platform and Operations System owns the operational-platform specification for:

| Responsibility | Platform ownership |
| --- | --- |
| Host lifecycle and provisioning | Host readiness, provisioning, service/VM prerequisites, and host-local recovery posture needed to operate Yggdrasil. |
| Container and Compose topology | Docker/Colima operation, Compose-project topology, container lifecycle, mounts, ports, and the operational consequences of those bindings. |
| Channel topology | The operational topology that separates `dev`, `test`, and `prod`, including the lifecycle of their runtime units and the path by which a channel is started, stopped, recovered, or physically deployed. |
| Runtime lifecycle wrappers | Startup, stop, restart, recovery, environment-export, and deployment wrappers when their primary effect is to operate the host, container runtime, Compose stack, or channel. |
| Platform health | Operational handling of host, container runtime, Compose-unit, gateway, binding, and recovery-prerequisite signals; the signal definitions and product-health interpretation remain with their existing owners. |
| Operational runbooks | Operator-facing procedures for provisioning, startup, recovery, deployment, rollback execution, and platform incident handling. |
| External helper-system execution | Host/topology mechanics for already-authorized Heimdal-managed helper systems; this system only executes the approved host/VM mechanics. |

This is ownership of the **operational platform**, not of every capability the platform runs. A
platform wrapper may invoke a Product/Runtime command, but that does not transfer the command's
product authority to this system.

## Boundaries and exclusions

The following boundaries are strict.

| Surface | Owner | Platform and Operations System boundary |
| --- | --- | --- |
| Product data, persistence semantics, artifact meaning, and product-facing state | Product/Runtime System; in the target SBS, principally PDM and the semantic owners it serves | May operate the store's host/container/volume topology and availability posture, but does not own product data semantics, schema meaning, migration intent, or artifact authority. |
| Product observability, evaluation, and fitness | Product/Runtime System; OEF and its owner documents | May expose or operate platform-health signals. It does not own product telemetry meaning, runtime evaluation, quality judgment, or product fitness policy. |
| Product runtime lifecycle authority | Existing Product/Runtime SBS owners, including the WSP lifecycle-binding decision and its EBF/EXE/PDM/OEF mechanism split | May operate host/Compose mechanics only with already-authorized channel, binding, and promotion inputs. It must not redefine whether a product process should run, what vault/context it is bound to, or the authority needed for a product side effect. |
| Build, test, PR, CI, agent, and delivery workflows | Builder System | Does not own Builder System build/test/PR/CI workflows, delivery governance, or BuilderOps evidence. Deployment and promotion can cross the platform boundary, but their delivery policy and acceptance remain with their existing Builder and release-channel owners. |
| Security, credentials, and exposure | Security and deployment owner documents | Implements approved host and topology mechanics only. It does not set security policy, credential scope or rotation, network exposure, or proxy-trust decisions. |
| External helper-system ownership | Heimdal, under `docs/HEIMDAL/EXTERNAL_SYSTEMS_CONTROL_PLANE.md` | May execute Heimdal-owned host/topology actions, but must not create a competing helper-system registry or reassign provider/channel ownership. |
| Product-function scripts | The Product/Runtime owner determined by the script's effect | A script is not a platform script merely because it lives in `scripts/`, is called by a runbook, or runs on a host. |

### Script classification rule

Classify a script by its **primary effect**, not by its path, caller, language, or whether it is
invoked during an operational procedure:

- A script that provisions a host, controls Docker/Colima or Compose, selects and operates a
  channel, starts/stops/restarts a runtime unit, exports runtime environment for that unit, or
  performs platform recovery is a Platform and Operations System script.
- A script that implements ingest, retrieval, data migration semantics, indexing, product health,
  evaluation, user-visible behavior, or another product function remains Product/Runtime work under
  the relevant product owner.
- A script that builds, tests, reviews, publishes, dispatches, or governs repository delivery is
  Builder System work.
- A mixed wrapper must state its cross-system dependency. Its operational wrapper remains platform
  work; the invoked product or Builder operation retains its own authority. This specification does
  not require immediate file moves or a rewrite of existing scripts.

### Authority limits for platform wrappers

Platform wrappers may operate host and Compose mechanics using only the **already-authorized inputs
applicable to that operation**. A start or recovery uses its authorized channel and binding inputs;
promotion authorization is required only where the governing deployment or promotion procedure
requires it, and approved security/topology inputs apply only where that boundary is implicated.
They may emit execution receipts that record the operation performed and its observed result. Such a
receipt is evidence of execution; it does not authorize the operation or upgrade any product,
release, or security authority.

Platform wrappers must not originate or alter environment-selection policy, vault/context binding,
promotion eligibility, migration intent, product side-effect authority, security policy, credential
scope or rotation, network exposure, or proxy-trust decisions. A change that crosses one of those
boundaries cites the controlling current contract and its required decision or receipt before the
platform mechanism is operated.

### High-risk mixed-wrapper routing aid

This is a small, non-relocating routing aid for mixed wrappers with high authority or recovery
impact. It is not a scripts registry, a new lifecycle contract, or a second source of truth. The
named current procedures remain authoritative.

| Wrapper class | Platform primary effect | Crossed owner(s) | Current procedure or contract | Required precondition or receipt | Failure and recovery owner |
| --- | --- | --- | --- | --- | --- |
| `scripts/deploy_channel.sh` | Physically operates a selected channel's Compose units and gateway. | Deployment, release channels, environment selection, product migration/data owners, and security where topology is affected. | `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deploy procedure` and `:: Rollback procedure`; `docs/RELEASE_CHANNELS/README.md`. | An already-authorized target/promotion input; unchanged governed binding; migration classification and acknowledgement where required; the deploy or rollback receipt required by the deployment procedure. | The deployment rollback procedure and the relevant release, migration, or security owner; an execution failure does not let the wrapper select a new target or binding. |
| `scripts/start_full_system.sh` | Starts and verifies a selected local runtime/Compose stack; on `dev`/`prod`, it also invokes the BuilderOps coordination bootstrap before Compose startup. | Environment selection; Product/Runtime lifecycle/binding, runtime health, and observability; Builder System / BuilderOps coordination for the `dev`/`prod` bootstrap. | `docs/INFRASTRUCTURE.md :: Startup Flow`; `docs/ENVIRONMENTS.md :: Runtime Control Surface`; `docs/OPERATIONS.md :: Startup telemetry`; `docs/AGENT_ISSUE_DISPATCHER.md :: Dev/prod startup bootstrap` for the BuilderOps bootstrap and its degraded branch. | Existing resolved channel and binding input; the current startup preflight and startup-telemetry/runtime-verification evidence. For `dev`/`prod`, record the BuilderOps bootstrap result required by its current procedure; a degraded result does not grant BuilderOps delivery authority. | `docs/OPERATIONS.md` and the applicable startup/recovery runbook, with Product/Runtime owners handling a runtime-health or binding failure. BuilderOps bootstrap degradation follows `docs/AGENT_ISSUE_DISPATCHER.md :: Dev/prod startup bootstrap`; it does not let the Platform wrapper alter Builder System coordination authority. |
| Channel-start wrappers such as `scripts/{dev,test,prod}/start_*.sh` | Starts the already-selected channel and its managed units. | Deployment, environments, release channels, runtime health, and gateway topology. | The deployment environment matrix and the relevant `docs/ENVIRONMENTS.md` and `docs/RELEASE_CHANNELS/README.md` procedure. | Existing channel configuration and binding; the current readiness, health, or deployment evidence required for that path. | The channel's current deployment or operations procedure; the wrapper does not substitute another channel, vault, or promotion target. |
| `ops/host-setup/**` where it provisions or recovers a host | Establishes host-local prerequisites and service/VM topology. | Security, deployment/topology, external-host integrations, and the affected runtime channels. | `ops/host-setup/README.md` and the applicable infrastructure, deployment, and security owner documents. | Operator-approved host/network/credential posture; the runbook's required setup or recovery evidence, with no credential material copied into an execution receipt. | The host-setup runbook plus the controlling security or deployment owner for the failed surface. |

## Documentation hierarchy

This document is the ownership and target-scope entrypoint. It deliberately delegates detailed
current-state claims and procedures to the documents below.

| Document | Owns | Relation to this specification |
| --- | --- | --- |
| `docs/architecture/system-context-overlay.md` | The enabling-system / deployed-COTS / external-system classification vocabulary | Explains why operational platform mechanisms sit outside the Product/Runtime SBS. |
| `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` | Target Product/Runtime SBS boundaries | Excludes this enabling system from the SBS and retains product-runtime lifecycle authority. |
| `docs/architecture/SBS_OPERATING_MODEL.md` | Product/Runtime, Builder System, Platform and Operations System, and boundary-work classification | Routes work to the correct system without recasting platform work as Builder or Product/Runtime work. |
| `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` | Canonical current deployment and environment-topology contract | Owns how a deploy physically happens, the current/target deployment matrix, managed units, deploy/rollback procedure, and deployment gates. |
| `docs/ENVIRONMENTS.md` | Environment selection and path scoping | Owns what data and configuration each channel touches. |
| `docs/RELEASE_CHANNELS/README.md` | Channel identity, promotion contract, migration classification, and rollback semantics | Owns release-channel policy and evidence, not platform topology alone. |
| `docs/INFRASTRUCTURE.md` | Current local Docker/Colima runtime description | Describes current local implementation details; update it when that reality changes. |
| `docs/HEALTH.md` | Runtime health CLI behavior and health-contract meaning | Owns product/runtime health definitions and remediation meaning; platform handling starts only with the prerequisite signals below. |
| `docs/OBSERVABILITY.md` | Runtime logs, counters, heartbeats, and status interpretation | Owns runtime observability signal definitions and interpretation; platform signals do not replace OEF/runtime observability. |
| `docs/SECURITY_ARCHITECTURE.md` | Security framing, invariants, and review routing | Retains security-policy, credential, exposure, and proxy-trust authority while platform mechanisms implement approved topology. |
| `docs/OPERATIONS.md` and `docs/runbooks/**` | Current operator entrypoint and task-specific procedures | Provide executable operator guidance within this system boundary. |
| `ops/host-setup/README.md` | Specific host-provisioning procedure | Is a platform runbook, not a Product/Runtime or Builder System specification. |
| `docs/HEIMDAL/EXTERNAL_SYSTEMS_CONTROL_PLANE.md` | Heimdal's external helper-system ownership, Builder Vault record shape, credential boundary, and shared Discord capability | Owns who manages external helpers; this document owns host and topology mechanics only. |

### Proposed separate infrastructure repository and disposable pilot (Issue #5856; preparation only)

The repository split remains a proposal. This issue creates no repository, provider token, backend,
state object, imported binding, VM, network, or deployment. If the owner approves the split, the
private repository candidate is `yggdrasil-infra` (the final name is an owner decision). Its boundary
is the Platform and Operations System and its first slice should be deliberately small:

| Candidate surface | Owns | Does not own |
| --- | --- | --- |
| `infra/` OpenTofu root and modules | Proxmox VM, storage, and network resource lifecycle, provider configuration, import, plan, and later explicitly approved apply | Application images, Compose topology, migrations, release selection, database/data or vault semantics |
| `guest/` Ansible roles and cloud-init templates | Guest prerequisites needed before a selected deployment, with versioned inputs and checkable output | Application services, channel promotion, secret administration, or a second deployment controller |
| `checks/` | Short pilot checks for formatting, provider validation/plan, Ansible syntax/check mode, cloud-init schema/rendering, redaction, and state recovery | A dashboard, registry, queue, permanent evidence store, or copied monorepo governance |

The recommended tool pairing is OpenTofu with the `bpg/proxmox` provider. The provider's primary
documentation describes Terraform/OpenTofu support, API-token authentication, VM, storage, and
network resources, and an import form of `node_name/vm_id` for the VM resource. It also documents
that API-backed VM disk import through `import_from` needs no SSH or sudo. The future repository
must pin the exact provider release that its compatibility check passes in its lock file; this
preparation does not guess or claim that release. The provider's current resource-name migration
and compatibility notes should be read before choosing a new short resource alias. A Linux bridge
is intentionally not the first pilot resource: the provider's current issue tracker records an
import/read failure on PVE 9.2.5, so network-resource coverage remains a later, separately reviewed
choice.

The checked primary references are the [provider overview](https://registry.terraform.io/providers/bpg/proxmox/latest/docs),
[VM resource and import contract](https://registry.terraform.io/providers/bpg/proxmox/latest/docs/resources/virtual_environment_vm),
[provider upgrade guidance](https://registry.terraform.io/providers/bpg/proxmox/latest/docs/guides/upgrade),
[provider API-token guidance](https://github.com/bpg/terraform-provider-proxmox/blob/main/docs/index.md),
and the [documented Linux-bridge import issue](https://github.com/bpg/terraform-provider-proxmox/issues/3029),
reviewed 2026-10-09. The provider's sample role is explicitly described as likely too permissive and
some operations are documented as unsupported with API tokens; the pilot must derive its actual
permission set from the selected resource's API calls and Proxmox permission responses rather than
copying that sample role.

The pilot's effect boundary is one existing disposable dev/test VM selected by an operator outside
Git. Its token is referenced from an approved secret source, scoped to that VM and the minimum
read/plan operations, and never committed to the repository. The first pass is import and plan only:
no production target, cluster-wide ACL, storage mutation, network mutation, SSH sudo rule, or
application effect is in scope. If a later approved apply needs VM power, config, disk, or network
permissions, each permission is added only after the planned API operation and its Proxmox
permission requirement have been read back. API-only resources should be preferred; any resource
that needs SSH, snippets, or host-side file operations requires a separate narrow account and
review, and must not receive broad `qm`, `pvesm`, or root access.

State must be outside Git in a private, encrypted, access-controlled, audited, versioned backend.
The OpenTofu [S3 backend contract](https://opentofu.org/docs/language/settings/backends/s3/)
documents server-side encryption, native S3 locking with `use_lockfile = true` or DynamoDB locking,
and bucket versioning for recovery; the [state-locking contract](https://opentofu.org/docs/language/state/locking/)
requires writes to stop when locking fails. The implementation follow-up must select a compatible
existing backend and prove encryption, locking, access scope, versioned recovery, and the
non-secret recovery procedure before any apply. No backend, lock service, or recovery claim is
created by this preparation.

The finite pilot acceptance and teardown checks are:

1. The operator records an out-of-band disposable-resource identifier and confirms that it carries
   no production, database, vault, or irreplaceable data; the repository stores only a redacted
   reference.
2. The future repository runs the pinned-provider lock check, `tofu fmt -check`, `tofu init`, and
   `tofu validate`; `tofu import` binds the selected VM and a reviewed `tofu plan` reports no
   unintended create, destroy, or replacement. Any non-zero change is a stop condition until the
   configuration and resource owner explain it.
3. Guest preparation runs `ansible-playbook --syntax-check` and `ansible-playbook --check --diff`
   with sensitive tasks protected from output, then validates cloud-init with
   `cloud-init schema --config-file` (or the image-supported equivalent) and checks the resulting
   guest prerequisites. Ansible's [check/diff contract](https://docs.ansible.com/projects/ansible-core/devel/playbook_guide/playbooks_checkmode.html)
   and cloud-init's [schema and instance-data contracts](https://cloudinit.readthedocs.io/en/latest/topics/instancedata.html)
   are the primary references; neither check deploys the application.
4. The backend test uses only disposable pilot state: lock acquisition and failure behavior,
   versioned object recovery, state readback, and a no-concurrent-writer check are demonstrated.
   A redacted plan and permission/readback evidence are retained with the implementation PR, never
   with secrets or private host identifiers.
5. Teardown removes the pilot state binding and any pilot-only guest configuration without
   destroying the imported existing VM. A future disposable VM created by a separately authorized
   implementation must use an explicit reviewed destroy plan; this issue authorizes no apply or
   destroy.

The implementation follow-up must record the final repository name, OpenTofu-versus-Terraform
choice, exact provider lock, backend compatibility, resource identifier, least-privilege token
scope, and the owner-approved apply/teardown authority. Application source and image artifacts,
Compose units, migrations, release bindings, database/data and vault semantics remain with their
current owners. The host/VM and complete-system qualification remains [#5052](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5052);
the independent BuilderOps control plane remains [#3788](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3788);
the dev/test/prod startup chain remains [#4913](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4913);
and secret/provider qualification remains [#5667](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667).
This proposal supplies an infrastructure interface and finite pilot checks; it does not create a
new platform-completeness gate for Builder or promote target-state documentation to shipped truth.

When an operational change changes present-tense reality, update the most local current-state owner
above in the same delivery. When a change alters this system's scope, exclusion, or cross-system
ownership, update this specification as well. A conflict over current behavior is resolved by the
current-state owner document, not by this target-state specification.

## Platform signal, runbook, and escalation aid

This compact aid routes operational prerequisites; it does not define a platform-health control
plane, new signal names, or product-health semantics.

| Operational concern | Platform handling and current runbook owner | Required handoff |
| --- | --- | --- |
| Host readiness | Use the current infrastructure and host-setup procedures to establish host prerequisites before operating a channel. | Once the host is ready, use `docs/HEALTH.md` for runtime-health meaning and `docs/OBSERVABILITY.md` for runtime signal interpretation. |
| Docker/Colima availability | Follow `docs/INFRASTRUCTURE.md :: Colima / Docker recovery` for the host/container-runtime recovery path. | A recovered daemon is not runtime readiness; hand off to the channel's runtime health and observability checks. |
| Compose-unit and gateway reachability | Use `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deploy procedure` for recreate, gateway, liveness, readiness, and deploy-receipt gates. | The deployment health gate hands product readiness and telemetry interpretation to `docs/HEALTH.md` and `docs/OBSERVABILITY.md`. |
| Port, binding, and recovery prerequisites | Resolve them through the deployment environment matrix, `docs/ENVIRONMENTS.md`, and the applicable startup/recovery runbook. | Environment-selection policy and vault/context binding stay with their controlling Product/Runtime and environment contracts; platform handling must not change them. |

### Host-global recovery

Docker/Colima and host recovery are host-global operations: an action can affect more than the
channel whose symptom triggered it. Before a host/container-runtime restart, inventory the affected
`dev`, `test`, and `prod` channels and their host-local dependencies. If any channel is active, use
the most conservative active-channel runbook and controlling authority before restart; do not infer
that a local symptom authorizes interruption of another channel.

### Current-topology caveat

Channel separation describes an operational topology, not a claim of code-artifact isolation. The
exact current matrix, including the shared-checkout limitation where it applies, is owned by
`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Environment matrix`. This specification does not
claim that `dev`, `test`, and `prod` currently run isolated code artifacts.

### Security handoff

The Platform and Operations System implements approved host and topology mechanics. Security and
deployment owners retain policy decisions for credentials and their scope/rotation, exposure,
trusted proxies, and related controls. A platform change that touches those decisions must cite the
controlling security or deployment contract and its existing decision/receipt; it must not create a
parallel policy path.

## Current-state and delivery posture

Current operational reality remains intentionally distributed across the deployment, environment,
infrastructure, operations, release-channel, and host-setup documents. The existing Docker/Colima,
Tailscale, host-provisioning, Compose, startup, recovery, and runbook surfaces are evidence for
this ownership boundary; they are not evidence that a unified platform implementation is already
shipped.

Future implementation work may consolidate or replace those mechanisms only through normal
repository authority: a bounded issue where implementation is needed, the relevant Product/Runtime
and Builder/release owners for crossed boundaries, and current-state documentation writeback after
the behavior is proven. This specification neither authorizes a new runtime subsystem nor changes
product behavior by itself.

### Proposed single-operator recovery boundary (Issue #5855; pending owner decision)

For the existing Linux secret and channel-recovery surfaces, the proposed normal operating model is
one designated agent-host controller coordinating the checked-in CLI/API producers and supervised VM
worker. The controller's lock is cooperative host-local serialization, not global fencing. Retained
human organization administration remains valid, but it is a separate break-glass/maintenance path;
an out-of-band write invalidates the qualification observation until selected-target parity and the
matching operation-ID terminal receipt are re-established.

Platform and Operations owns host, VM, systemd, Compose, channel, file-ownership, and recovery
mechanics. Builder System owns the repository delivery and evidence workflow. Product/Runtime owners
retain product data, database-role, vault/context, migration intent, provider-key, and product
side-effect authority. A platform wrapper may execute only already-authorized inputs and may report
execution evidence; it cannot approve a credential scope, choose a target, rotate a secret, grant
access, or treat a local lock as a global writer fence.

The proposed model remains preparation-only until #5667 records one concrete owner choice: approve
the designated normal writer with retained human administration and credential-restriction evidence,
or require shared/distributed fencing before BWS administration, first-init bootstrap, and parity
qualification. `--existing-secrets-only` remains a read/validate path where its own preconditions
pass. No preparation receipt in this document claims live access, token installation, deployment,
first healthy release, rollback, host cleanup, or channel qualification; those effects require their
existing deployment, security, release, and operator gates.
