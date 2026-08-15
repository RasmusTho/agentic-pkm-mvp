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
