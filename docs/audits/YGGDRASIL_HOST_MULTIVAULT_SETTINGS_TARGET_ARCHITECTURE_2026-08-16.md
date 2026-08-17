# Yggdrasil host, multi-vault, and settings target architecture

State: Advisory architecture research snapshot, 2026-08-16; subordinate to `docs/DOCS_INDEX.md` and all owner contracts; no executable specification directory exists.
Doc role: Reference (audit snapshot).
Repository authority: `origin/main` at `4b75048288a1c4e006a200a470411ca31ae64274`.
Scope: Future local hosting, environment isolation, complete Obsidian vaults, iCloud reachability, settings authority, network access, backup/recovery, and bounded agent control of the virtualization host.
Authority: Evidence-based structural analysis whose repository anchors reflect `origin/main` at the snapshot above. Owner documents win on disagreement. This document does not change current runtime behavior, accept a target state, create an Issue, authorize a migration, or replace any owner document.

## 1. Executive recommendation

Adopt a **single-node Proxmox VE host only after a hardware and storage qualification gate**, and keep Docker Compose as the application topology inside three isolated Linux VMs:

- `yg-prod`: always-on production runtime and its own Postgres;
- `yg-dev`: development runtime and its own Postgres;
- `yg-test`: disposable/restore-tested validation runtime and its own Postgres, stopped by default;
- optionally, a very small `yg-ops` VM for Tailscale routing and a narrowly scoped Proxmox API adapter.

This is an evolution of the accepted Platform and Operations System, not a new Product/Runtime SBS subsystem. It preserves the decided build-once, pinned-image, configuration-separated Compose direction while replacing shared-host failure domains with VM boundaries.

Do **not** put Product Postgres in one shared database VM initially. Keep one Postgres instance inside each environment's Compose project and VM. A shared database VM would reintroduce a common failure, credential, maintenance, and resource-contention domain precisely where the virtualization work is intended to remove one.

Treat every user's Obsidian vault as one complete, independent vault root, including its own `.obsidian` configuration and Yggdrasil settings. Do not introduce a master vault that overwrites the others. The current durable registry and future ActiveContextSet remain the vault identity and binding substrate.

Because Apple documents iCloud Drive clients for Apple platforms and Windows, not Linux, and Obsidian recommends iCloud for macOS/iOS/iPadOS while warning about Windows duplication or corruption, a Proxmox/Linux guest must **not** directly mount or emulate iCloud as an active writable vault. Use a Mac-side, fully hydrated **vault bridge**:

1. iCloud remains the transport used by Obsidian and iPad.
2. A Mac keeps each served vault `Keep Downloaded`.
3. Yggdrasil reads from a server-local replica or snapshot.
4. Every Yggdrasil mutation is sent to the Mac bridge with vault identity, path, expected revision/hash, write class, and idempotency key.
5. The bridge applies the mutation using the existing governed-write/CAS posture and returns a durable receipt.
6. Stale bases, iCloud conflict copies, hydration gaps, and ambiguous case/Unicode identities fail closed into conflict staging; they are never resolved by silent last-writer-wins.

This makes the Mac bridge a write coordinator for Yggdrasil effects, not a claim that iCloud has a primary device. iCloud and Obsidian remain eventually consistent multi-device systems.

Use a **hybrid settings model**, not one flat precedence stack:

- central instance/channel policy owns security ceilings, network exposure, allowed sync transports, resource ceilings, credentials, and deployment wiring;
- vault-shared Yggdrasil settings own user intent for that vault within those ceilings;
- device-local state owns UI layout, local paths, caches, and machine-specific tuning;
- `.obsidian` remains vault-owned Obsidian configuration and is not rewritten by the Yggdrasil settings plane;
- request/session overrides are allowlisted and ephemeral.

Do not build a cloud settings control plane now. Add one only if multiple physical runtime nodes, multiple operators, or off-site availability create a measured need that the existing instance registry plus vault settings cannot meet.

## 2. Evidence boundary and unresolved physical facts

### 2.1 What the repository establishes

The current runtime is macOS -> Colima -> repository-root Docker Compose, with pgvector Postgres, API, worker, and host-resident vaults (`docs/INFRASTRUCTURE.md:14-23`). Dev, test, and prod are separate Compose projects and ports (`scripts/start_full_system.sh:727-755`; `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:34-54`), but they remain on one physical host.

Product Postgres is already Compose-local per channel (`docker-compose.yaml:2`; `docker-compose.dev.yml:8`; `docker-compose.test.yml:14`; `docker-compose.prod.yml:63`). The runtime bind-mounts broad host path trees so selected vaults can be reached in containers (`docker-compose.yaml:200`; `docs/ENVIRONMENTS.md:147-185`). This mechanism cannot be carried unchanged into isolated Linux VMs with iCloud-hosted vaults.

The accepted deployment direction remains Docker Compose with pinned images built once per SHA and promoted across channels, with environment differences confined to configuration, data, and ports (`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:21-26,171`). The Platform and Operations System already owns host lifecycle, VM/service prerequisites, Compose/channel topology, wrappers, health, and runbooks without claiming a separate delivered control plane (`docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md:20-40,161-169`).

The current vault runtime is not yet generally multi-vault. Registry, default selection, ActiveContextSet, and dimensions exist, but request propagation and context-bound production consumers remain future work (`docs/MULTI_VAULT_RUNTIME/README.md:1-12,270-310,454-478`; `app/instance/scalar_binding_runtime.py:162-190`). The current settings resolver does implement built-in -> app-local -> vault-shared -> vault-local -> runtime precedence (`app/vault/settings_service.py:706-882`), but not every runtime consumer is proven receipt-gated, and watcher rebind remains future/blocked work (`docs/SETTINGS_SPINE/REBIND_ON_VAULT_SELECTION.md:16-27`).

Local conflict protection is real: stale writes use CAS/conflict staging, and iCloud-style conflict artifacts are recognized and quarantined (`docs/CONCURRENCY.md:21-57`; `app/knowledge/multiwriter.py:36-83`; `tests/watcher/test_vault_conflict_quarantine.py:26-84`). The shipped sync factory, however, provides filesystem and Git transports only; iCloud appears only as an abstract possibility (`app/sync/base.py:66-119`; `app/sync/factory.py:16-48`).

### 2.2 What was not inspected and must not be guessed

This research did not inspect the physical HP laptop, BIOS, disk controller, CPU model, battery health, NIC, thermals, fan condition, or exact storage slots. It also did not inspect a live iCloud vault, its case-sensitivity behavior, current hydration state, or an installed Proxmox node.

Therefore the following remain qualification facts, not architecture assumptions:

- CPU virtualization support and BIOS enablement;
- Proxmox/Debian support for NIC, Wi-Fi, storage controller, graphics, sleep/lid, and battery reporting;
- whether wired Ethernet is available and reliable;
- SSD form factor, interface, capacity, endurance, and firmware health;
- sustained thermal behavior under simultaneous VM, Postgres, embedding, and backup load;
- whether the machine can auto-boot and recover unattended after power loss;
- actual vault sizes, attachment growth, database size, ingest rate, and desired RPO/RTO.

Proxmox's own guide requires an AMD64 system with hardware virtualization for KVM, reserves memory for the host in addition to guests, recommends fast/redundant storage, and provides `pveperf` for host benchmarking. Those are gates for this laptop, not proof that it is suitable merely because it has 32 GB RAM.

### 2.3 Documentation classification

| Surface | What it represents at this snapshot | Revision posture |
|---|---|---|
| `docs/INFRASTRUCTURE.md` | Actual current macOS/Colima/Compose runtime | Keep current until cutover; then rewrite as current reality |
| `ops/host-setup/README.md` | Actual current Mac mini/Windows inference/MacBook topology | Keep current until roles change; do not insert Proxmox as shipped |
| `scripts/start_full_system.sh` and `docker-compose*.yml` | Executable current behavior; stronger evidence than aspirational prose | Change only through implementation Issues |
| `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` | Mixed: actual current matrix plus decided pinned-image/Compose target | Extend the accepted target after owner decision; correct current drift separately |
| `docs/ENVIRONMENTS.md` | Current contracts plus some claims that diverge from startup/release reality | Needs bounded current-state reconciliation; later add VM/bridge semantics |
| `docs/RELEASE_CHANNELS/README.md` | Current channel truth plus deferred stable/pinned-image target | Preserve the distinction; extend target before VM promotion work |
| `docs/OPERATIONS.md` | Actual current runbooks; backup/snapshot sections are not a complete DR contract | Replace only after new operations are proven |
| `docs/CONCURRENCY.md` | Current normative local multiwriter contract | Extend with bridge/distributed conflict semantics before bridge delivery |
| `docs/architecture/SBS_OPERATING_MODEL.md` and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` | Target authority/control-boundary model, not physical deployment | No new SBS boundary; record explicit conformance/extension only |
| `docs/testing/invariant-tests.md` | Current enforcement registry plus named future targets | Add promoted invariants only with their real gates/doctors |

Two existing current-state divergences should not be hidden inside the host program: `docs/ENVIRONMENTS.md:191` says channels use dedicated worktrees and describes prod as stable-pinned, while `docs/RELEASE_CHANNELS/README.md:101,212-237` says current prod tracks `main`; and the deployment matrix differs from the startup wrapper's default source bind-mount behavior (`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:44`; `scripts/start_full_system.sh:7,727`; `docker-compose.app-bind.yml:2-7`). These are documentation/runtime reconciliation items, not evidence that the future state already exists.

### 2.4 Ranked weakness analysis and disposition

Ranking is by systemic impact: blast radius multiplied by silence of failure. “Accepted” below means an existing owner program already accepts the underlying correction; it does not mean this audit accepts a new target or has crossed the BuilderOps promotion boundary.

| Rank | Finding | Blast/silence | Anchored evidence | Disposition |
|---:|---|---|---|---|
| F1 | The hard iCloud requirement has no supported Linux writer, while a naive mount can appear healthy until duplication, hydration, or conflict failure. | critical / high | shipped sync factory is filesystem/Git only (`app/sync/factory.py:16-48`); Apple/Obsidian platform evidence in section 16 | requires owner decision: Mac bridge availability versus changing the iCloud constraint |
| F2 | The desired many-vault runtime can appear configured while production consumers still collapse to one scalar binding. | critical / high | scalar binding (`app/instance/scalar_binding_runtime.py:162-190`); unchecked many-vault criteria (`docs/MULTI_VAULT_RUNTIME/README.md:454-478`) | accepted by existing MVR program; reuse #2143/#3860-#3869 |
| F3 | “Vault-local” settings can silently become cross-device settings when the whole vault is in iCloud. | high / high | current five-layer resolver (`app/vault/settings_service.py:706-882`); current iCloud-backed full-root requirement has no device-locality gate | accepted by existing Settings Spine scope only where its owner contract applies; iCloud locality correction requires owner promotion |
| F4 | Current channels share one host and broad host mounts, so logical separation can be mistaken for fault/security isolation. | high / medium | broad mounts (`docker-compose.yaml:200`); same-host channels (`docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md:34-54`) | requires owner decision on conditional Proxmox target |
| F5 | Current backup evidence does not provide an independent, measured restore contract for VM, DB, vault, and control state. | high / medium | nightly DB dump (`docs/OPERATIONS.md:505-605`); current snapshots explicitly not true DR (`docs/OPERATIONS.md:751-800`) | deferred pending RPO/RTO and storage decision; blocks cutover |
| F6 | Proxmox automation has no current repo-owned least-privilege adapter contract; generic SSH/API use could silently exceed intended authority. | high / low | current platform owner stops at host/Compose/wrapper ownership (`docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md:20-40,72-86`) | requires owner decision on agent privilege ceiling |
| F7 | Current environment, release, deployment, and startup descriptions disagree, so a future migration could report progress against the wrong baseline. | medium / high | divergence anchors in section 2.3 | deferred to bounded current-state reconciliation; do not fold into target claims |

Novel F1/F3/F4-F6 recommendations remain advisory and are not eligible for `feature-breakdown` until an owner-accepted PromotionIntent supplies the normative handoff. The candidate sequence in section 13 is therefore a Verify-able planning backlog, not executable Issue authority.

## 3. Current, transition, and target state

| Concern | Current reality | Transition state | Recommended target |
|---|---|---|---|
| Physical host | Mac mini/Colima; documented burst inference on a separate Windows PC (`ops/host-setup/README.md:3-46`) | HP laptop lab node; no production data | Qualified single Proxmox node; no HA claim |
| Environments | Three Compose projects on one host | Dev/test VMs first; prod stays on current host | Three VM failure domains; test off by default |
| Application packaging | Shared checkout/bind-mount drift remains (`scripts/start_full_system.sh:7,727`; `docker-compose.app-bind.yml:2-7`) | Produce and boot pinned SHA images in lab | Same immutable image digest promoted through channel configuration |
| Postgres | Per-channel Compose service/volume | Same topology inside lab VMs | One Postgres per environment VM |
| Vault access | Broad host `/Users` and `/Volumes` mounts | Read-only exported test vaults, then bridge prototype | Per-vault replica plus Mac write bridge; no direct iCloud mount |
| Multi-vault | Registry/default delivered, scalar production binding remains | Complete context propagation and binding-keyed consumers | Zero/one/many vaults per instance with per-binding isolation |
| Settings | Multiple sources; partial settings spine | Authority-domain split and rebind completion | Hybrid instance policy + vault intent + device-local state |
| Remote access | Tailscale private host topology | Tailscale on endpoints; lab firewall | No public ingress; endpoint agents first, subnet router only when needed |
| Backup | Nightly prod DB dump to T7; vault treated as iCloud SoR (`docs/OPERATIONS.md:505-605,751-800`) | Independent lab backup and restore exercises | Separate VM, DB, vault, and control-state backups with restore receipts |
| Agent control | Shell/wrappers and internal allowlisted tools | Read-only Proxmox API token | Allowlisted adapter; separate test lifecycle token; prod effects gated |

The transition must be additive. Production remains on the current host until the candidate host passes qualification, the vault bridge has conflict and offline tests, environment isolation is proven, backups are restored, and the same pinned application artifact has passed test.

## 4. Target topology

```text
                                      iCloud Drive
                                           |
                                  iPad / Obsidian clients
                                           |
                                 eventual file convergence
                                           |
                            Mac vault bridge (fully hydrated)
                           /          |                 \
                    vault A       vault B ...       vault N
                       | mutation receipts + versioned replication
                       |
   owner LAN + tailnet |                         no public port forwards
  ---------------------+------------------------------------------------
                       |
              Proxmox VE, single qualified node
              management LAN only; host RAM reserved
                       |
         +-------------+------------------+------------------+
         |                                |                  |
     yg-prod VM                       yg-dev VM          yg-test VM
   Compose project                   Compose project    Compose project
   API/worker/watcher                API/worker/...     API/worker/...
   Postgres-prod                     Postgres-dev       Postgres-test
   vault replicas                    vault replicas     synthetic copies
   prod credentials                  dev credentials    test credentials
         |                                |                  |
         +---------------- isolated VM disks/networks ------+
                       |
             optional yg-ops VM
        Tailscale connector + scoped PVE adapter

   Independent external backup target (USB/NAS/off-host)
       VM backups + DB dumps + vault backup + config export
```

### 4.1 VM sizing on a 32 GB host

Sizing is a starting envelope, not an entitlement:

| Allocation | Initial range | Operating posture |
|---|---:|---|
| Proxmox host reserve | 4-6 GB | Never allocated to guests; increase if ZFS is selected |
| `yg-prod` | 8-10 GB | Always on; fixed minimum preferred |
| `yg-dev` | 6-8 GB | On when used |
| `yg-test` | 6-8 GB | Off by default; disposable data allowed only by contract |
| `yg-ops` | 1-2 GB | Optional; no Product data |

Do not depend on memory ballooning to make an unsafe all-guests-active plan appear viable. The initial scheduling rule is **prod plus at most one fully loaded non-prod environment**. Change that rule only after measured peak RSS, cache behavior, I/O latency, and swap pressure establish headroom.

CPU allocation must be derived from the actual processor and thermal test. VCPU counts are scheduling limits, not physical isolation. Embedding or local LLM inference should remain on a separately measured accelerator/host unless the HP laptop proves it can sustain that work without degrading Postgres and vault durability.

### 4.2 Storage layout

Replace the HDD before the platform trial. Prefer a supported, high-endurance SSD; power-loss protection is desirable where the interface and budget permit it. Do not represent a single SSD as redundant.

For a one-disk laptop, the simplest qualified Proxmox storage (typically LVM-thin on a conventional filesystem) is the default. Single-disk ZFS is an option only if checksumming/snapshot benefits are deliberately chosen, host memory is budgeted, SSD endurance is acceptable, and nobody mistakes it for redundancy.

Each environment VM should receive separate virtual disks or volumes for:

- guest OS and immutable application artifacts;
- Postgres data;
- server-side vault replicas/staging;
- runtime and instance state.

These are restore, quota, and blast-radius boundaries. They are not physical failure isolation because all reside on one SSD. Secrets should not be embedded in VM templates or backups without encryption and access control.

### 4.3 Postgres placement

Recommended: **Postgres remains an infrastructure service inside each environment's Compose topology**.

Advantages:

- VM isolation and database isolation align one-to-one;
- environment credentials and lifecycle remain local;
- prod survives destructive test work and test database recreation;
- restore and rollback can be rehearsed per environment;
- the existing Compose contract changes less.

Rejected initial alternative: one shared Postgres VM. It saves some idle RAM but introduces a shared maintenance window, shared host-level network authority, a common credential target, and one failure domain across dev/test/prod. It also makes “environment isolation” depend on logical database and role correctness.

A dedicated database VM may be reconsidered only after measurement shows material benefit and a new contract supplies separate clusters/roles, network ACLs, backup ownership, migration ordering, and failure-mode tests. It is not a microservice boundary.

## 5. Vault and iCloud authority model

### 5.1 One complete root per user vault

Each user vault is independently selectable and contains:

- all Markdown notes and attachments;
- its own `.obsidian` folder or device-specific Obsidian configuration profile;
- its own Yggdrasil shared settings under the canonical vault settings location;
- no symlink or path escape into another vault;
- a durable vault identity distinct from display name and physical path.

The registry/default selection contract remains authoritative for binding. No environment may infer a vault from CWD, “last active”, folder ordering, or a shared master vault (`docs/ENVIRONMENTS.md:46-71,115-131`; `docs/MULTI_VAULT_RUNTIME/README.md:39-142`).

### 5.2 Why direct iCloud access from Linux is rejected

Apple's supported setup surface lists iPhone/iPad, Mac, Windows, and iCloud.com, but no Linux filesystem client. Obsidian recommends iCloud for macOS/iOS/iPadOS, warns that iCloud Drive on Windows can cause duplication/corruption, recommends keeping vaults downloaded, and warns against mixing sync services.

Accordingly, reject all of these as active-writer designs:

- an unofficial Linux iCloud/FUSE client mounted into prod;
- a Windows iCloud guest used as the authoritative server-side vault writer;
- SMB/NFS exposure of an iCloud folder as if it were a coherent local POSIX filesystem;
- simultaneous iCloud plus Obsidian Sync/Syncthing/Git synchronization of the same working root;
- treating a server replica as silently authoritative while iPad edits continue elsewhere.

### 5.3 Mac bridge protocol contract

The bridge is a narrow product/platform seam, not a generic remote filesystem server. Minimum request fields:

- `vault_id` and resolved binding generation;
- normalized relative path plus original spelling;
- operation class: create-once, append, compare-and-swap rewrite, delete/tombstone;
- expected content revision/hash and optional base snapshot identity;
- principal, policy decision/authorization reference, idempotency key, and trace ID;
- payload digest and size.

Minimum response/receipt fields:

- accepted/rejected/conflict/deferred status;
- before/after revision and bridge-observed iCloud/hydration state;
- actual relative path and filesystem identity;
- durable receipt identity and timestamp;
- conflict or quarantine artifact reference when applicable.

The bridge must pin served roots with `Keep Downloaded`, refuse placeholder/partial files, use atomic no-follow writes, and never follow symlinks outside the registered root. A bridge outage queues a bounded mutation intent or rejects the effect; it never causes fallback to a different vault or local path.

The bridge cannot guarantee that an offline iPad has no unseen edit. Therefore the truthful model is eventual convergence plus detectable conflicts, not global serializability. Post-sync iCloud conflict copies and base mismatches must be quarantined and surfaced for resolution.

### 5.4 Backup authority

iCloud is synchronization, not backup. Obsidian explicitly distinguishes the two. Choose one fully hydrated Mac as the vault backup source and create a one-way, versioned backup to storage outside the Proxmox SSD and outside the live iCloud root.

## 6. Settings authority and precedence

### 6.1 Do not use one universal “last value wins” stack

Precedence must be constrained by **authority domain**. A vault cannot weaken central security policy, and an environment variable cannot silently become a durable user preference.

| Domain | Authoritative source | Permitted override direction | Example |
|---|---|---|---|
| Deployment wiring | environment/channel manifest and secret store | operator-controlled only | ports, DSN, image digest, credential reference |
| Security/exposure ceilings | instance/channel policy | vault may only narrow | allowed principals, remote write, network exposure |
| Sync policy | instance policy + per-vault registration | vault may opt out or narrow; cannot add an unapproved transport | bridge enabled, direction, size limit |
| Indexing/resources | instance ceiling + vault request | effective value is the safer intersection | excluded paths, attachment limits, cadence |
| Yggdrasil user behavior | vault-shared settings | vault overrides built-in/app defaults | capture/retrieval preferences |
| Device/runtime tuning | device-local instance state | device only | local paths, cache, watcher debounce |
| Obsidian UI/plugins | `.obsidian*` inside the vault | Obsidian/device profile only | workspace, themes, plugins, hotkeys |
| Session/request | allowlisted ephemeral override | highest only for permitted keys | one request's retrieval limit |

### 6.2 Resolution contract

For keys whose authority class allows ordinary override, resolve:

1. typed built-in default;
2. application default;
3. instance/channel policy;
4. vault-shared setting;
5. device-local setting;
6. allowlisted runtime/session override.

Then apply the authority constraint for that key. For a ceiling, “later” does not mean “more permissive”; the effective value is the intersection or most restrictive valid value. Every resolved value must carry source, scope, version, digest, binding generation, validation state, and degraded/last-valid status.

### 6.3 Important iCloud correction

The existing name `vault-local` or a file such as `<vault>/settings/local.md` does **not** make data device-local when the complete vault is synchronized by iCloud. `.gitignore` is irrelevant to iCloud. Machine-local settings must live in instance/device state outside the synchronized root, or in an explicitly device-keyed Obsidian configuration profile. This semantic correction must precede migration of settings into iCloud-backed vaults.

### 6.4 Central cloud settings control plane

Do not add one in the first target. The durable local instance registry plus per-vault settings spine is adequate for one physical runtime node and one operator.

If later justified, a central settings service must be optional and cacheable, export the complete effective state, use per-vault identities and CAS versions, remain offline-safe, encrypt secrets separately from preferences, preserve receipts, and never become the sole route to opening a local vault. It may distribute policy; it may not replace vault content authority or Obsidian configuration authority.

### 6.5 Data placement contract

| Data | First target placement | May later use cloud? | Authority note |
|---|---|---|---|
| Notes, attachments, `.obsidian`, vault-shared Yggdrasil settings | complete per-user vault in iCloud, hydrated on the Mac bridge; versioned backup elsewhere | already uses iCloud transport; do not add a second live sync service | vault files remain content authority |
| Server vault replica, ingest staging, caches, embeddings, indexes | local to the bound environment VM | derived replicas may move when portability/encryption/latency are proven | never silently promoted to content authority |
| Product relational state and receipts | per-environment Postgres in its VM; independent backup | managed/off-site database only after an explicit data/availability decision | preserve environment and vault binding lineage |
| Instance registry, bridge journal, settings resolution receipts, channel manifest | local durable control state with encrypted/off-host backup | optional replicated control plane later | must export/restore without cloud availability |
| Secrets and Proxmox/Tailscale credentials | environment/role-scoped local secret mechanism | external secret manager may be justified later | never stored in vault settings or VM template |
| Device UI state, caches, local tuning | device-local outside the synchronized vault, or device-keyed Obsidian profile | no central requirement | a device setting cannot become shared by accident |
| Backups | physically independent USB/NAS/off-host target | off-site encrypted copy is desirable | backup is not an active sync root |

## 7. Network and access topology

### 7.1 Recommended posture

- No public port forwards to Proxmox, Postgres, Ollama, bridge, or Yggdrasil APIs.
- Proxmox management listens on a management LAN/VLAN reachable by the owner and the scoped ops adapter.
- Prod, dev, and test use separate Proxmox firewall groups or VLANs when supported by the home network; at minimum, host firewall rules prevent lateral access not required by explicit contracts.
- Postgres is not exposed outside its environment VM/Compose network except for a time-bounded operator recovery path.
- Install Tailscale directly on endpoints that need tailnet identity whenever practical.
- Use a subnet router only to reach LAN resources that cannot run Tailscale.
- Do not configure an exit node merely to reach the home LAN. Tailscale defines a subnet router for private-subnet access and an exit node for routing clients' general internet traffic.
- Test remains stopped by default and has no prod routes, credentials, vault roots, or backup keys.

### 7.2 Suggested access matrix

| Source | Proxmox API/UI | Prod API | Dev API | Test API | Mac bridge |
|---|---:|---:|---:|---:|---:|
| Owner LAN/tailnet | admin | allowed | allowed | allowed when on | status/admin |
| `yg-ops` adapter | scoped API only | health only | deploy if authorized | lifecycle/deploy | health only |
| `yg-prod` | no | local | no | no | per-vault mutation protocol |
| `yg-dev` | no | no | local | no | dev/test vault registrations only |
| `yg-test` | no | no | no | local | synthetic/test bridge only |
| Internet | no | no | no | no | no |

Credentials, Tailscale tags/grants, and Proxmox tokens are separate per environment and role. Network reachability never substitutes for Product authorization.

## 8. Backup, recovery, and failure domains

### 8.1 Independent backup sets

Maintain four separately restorable sets:

1. **Vault backup:** one-way, versioned copy from the designated hydrated Mac; includes `.obsidian` and Yggdrasil settings, excludes caches and conflict quarantine only when separately retained.
2. **Database backup:** per-environment `pg_dump` initially; add WAL/continuous recovery only if the accepted RPO requires it. Until every table is proven rebuildable, do not assume Postgres is disposable.
3. **VM/platform backup:** Proxmox VM backups plus exported host/firewall/storage configuration to an independent target.
4. **Control state:** vault registry, settings receipts, bridge journal, image/channel manifests, secret references, and restoration instructions; secrets themselves use an encrypted recovery mechanism.

The external target must not be the same internal SSD. A USB disk is acceptable for an initial single-operator posture if it is regularly disconnected/rotated; a NAS or Proxmox Backup Server is stronger when cost and operations justify it. VM snapshots on the same SSD are rollback aids, not backups.

### 8.2 Recovery order

1. Qualify or replace the physical host and install the pinned Proxmox baseline.
2. Restore network/firewall and minimal ops access without exposing Product services publicly.
3. Restore VM definitions and immutable application artifacts.
4. Restore per-environment Postgres and instance/control state.
5. Restore or re-register vault replicas from the hydrated Mac/backup source.
6. Reconcile vault identity, binding generation, settings digest, bridge journal, and DB projection.
7. Run environment-specific health and invariant gates before enabling writes.
8. Rebuild derived indexes where possible and compare expected counts/digests.

Quarterly, restore one vault and one database into `yg-test`. At least annually or after material topology changes, perform a bare-host recovery rehearsal. Record measured RPO/RTO and any manual steps.

### 8.3 Failure-domain truth

VMs isolate operating systems, credentials, processes, and many operator mistakes. They do not isolate:

- physical disk failure;
- laptop motherboard, RAM, thermal, power, or NIC failure;
- Proxmox host compromise;
- a mis-scoped host administrator or backup credential;
- iCloud account or sync-wide destructive change;
- loss of the only Mac bridge.

The laptop battery can soften short power interruptions but is not a substitute for tested UPS behavior, battery health monitoring, controlled shutdown, or external backup.

## 9. Agent control of Proxmox

No Proxmox-specific MCP server or callable Proxmox tool was present in the bounded repository/session inventory used for this audit. That absence is not proof that no community integration exists; it means the target must not depend on one today.

Use Proxmox's REST API and ACL/token model, not generic root SSH, as the normal automation boundary. Proxmox documents path-scoped ACLs and API tokens whose permissions can be separated and limited relative to the backing user.

Recommended privilege ladder:

| Token/route | Rights | Default holder |
|---|---|---|
| inventory | read-only/auditor for node, storage, VM state | agent adapter |
| test lifecycle | start, stop, reboot `yg-test` only | agent adapter |
| test snapshot/restore | named test storage and VM only | separate token; explicit workflow |
| dev deploy | guest-level deployment, not PVE admin | deployment workflow |
| prod health | read-only | agent adapter |
| prod lifecycle/snapshot | normally absent; time-bounded operator grant | owner-controlled |
| host/network/storage/delete | no standing agent token | owner/break-glass |

Build an adapter or MCP server only if the existing tool estate lacks an adequate scoped Proxmox integration. It must expose named idempotent operations, not arbitrary API paths or shell commands; hold separate tokens by capability; bind only on LAN/tailnet; validate VM IDs and storage names against an allowlist; emit receipts; and refuse deletion, host updates, network changes, token management, or prod mutation without an explicit governed operator gate.

SSH remains bootstrap and break-glass. If it is automated at all, use a separate non-root account, forced commands, short-lived credentials, and full logging.

## 10. Invariant kernel and enforcement

`MUST` fails loudly at the runtime effect boundary. `GATE` is a CI/PR/promotion-blocking proof. `DOCTOR` is read-only reconciliation that detects drift or degradation and gives an operator remediation path.

| ID | Class | Invariant | Existing posture | Enforcement target |
|---|---|---|---|---|
| HOST-01 | GATE | Proxmox is not promoted to prod until CPU, NIC, SSD, thermals, unattended boot, and recovery are proven. | New | qualification script + signed receipt |
| HOST-02 | DOCTOR | A single physical disk/node is never described as redundant or highly available. | New | owner-doc/topology reconciliation |
| ENV-01 | GATE | Dev/test cannot address prod DB, vault replicas, volumes, credentials, or bridge registrations. | Violated by current shared-host physical topology; target K2 exists in `docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md:17` | firewall/ACL tests + negative integration test |
| ENV-02 | GATE | The exact image digest promoted to prod has passed test; prod never boots source bind mounts. | Target exists; current wrapper defaults to bind mount (`scripts/start_full_system.sh:7,727`) | channel manifest + startup preflight |
| ENV-03 | MUST | Each environment owns its Postgres instance, credentials, volume, and backup lineage. | Partial — per-channel Compose DB/volume exists | startup runtime check + restore receipts |
| VAULT-01 | MUST | Every vault has a stable identity and complete independent root; display name/path is not authority. | Partial — registry identity exists; complete-root bridge does not | registry/runtime validation |
| VAULT-02 | GATE | No effect occurs without explicit, authorized vault context and binding generation. | Partial — ActiveContext exists; production propagation incomplete | request/worker/watcher integration gates |
| VAULT-03 | MUST | No direct Linux/Windows iCloud mount is used as the prod writer. | New | startup mount/source refusal |
| VAULT-04 | GATE | Bridge writes require expected revision, idempotency key, authorized write class, and durable receipt. | New | bridge protocol tests |
| VAULT-05 | MUST | Stale, ambiguous-case/Unicode, placeholder, and conflict-copy states never silently overwrite content. | Partial — local CAS/quarantine exists; bridge/case/Unicode/hydration proof does not | effect refusal + conflict doctor |
| SET-01 | MUST | Each setting key has one owner scope and authority class; source-scope forgery fails. | Exists — keep and extend (`app/vault/settings_service.py:706-882`) | settings resolver runtime validation |
| SET-02 | GATE | Security/sync/resource ceilings cannot be weakened by vault or request overrides. | New authority-domain proof | effective-policy resolver tests |
| SET-03 | MUST | Device-local settings are outside the iCloud-synchronized root or explicitly device-keyed. | Violated by relying on naming/ignore semantics alone | location refusal + read-only doctor |
| SET-04 | GATE | A changed vault setting takes effect with a receipt or enters visible last-valid degraded state. | Partial target; rebind remains future/blocked | watcher/rebind integration test |
| NET-01 | DOCTOR | No PVE, Postgres, Ollama, bridge, or Product admin endpoint is internet-exposed. | Partial host guidance exists (`ops/host-setup/README.md:139-146`) | firewall/listener/route reconciliation |
| NET-02 | GATE | Test is off by default and has no prod route/credential. | New VM-level proof | VM config + negative connectivity test |
| BAK-01 | GATE | Production cutover requires successful independent restore of VM, DB, vault, and control state. | New | restore rehearsal receipt |
| BAK-02 | DOCTOR | Sync, snapshots, and same-disk copies are not counted as backup. | Partial — current docs admit snapshot limits | backup inventory reconciliation |
| AGENT-01 | DOCTOR | Standing agent access is capability-scoped; no generic root/PVE-admin token exists. | New | ACL/token census |
| AGENT-02 | GATE | Host/network/storage/delete and prod mutation require explicit owner authority. | New | adapter deny-by-default policy tests |

The existing vault multiwriter, settings, multi-vault, startup, and release invariant registries should be extended rather than duplicated (`docs/testing/invariant-tests.md:945-1015,1078-1144`).

The **minimal cutover kernel** is `HOST-01`, `ENV-01`, `ENV-02`, `VAULT-02`, `VAULT-03`, `VAULT-04`, `VAULT-05`, `SET-02`, `BAK-01`, and `AGENT-02`. Without any one of these, the target's central safety claim can fail silently or across a large blast radius. The remaining invariants provide defense in depth, operability, or continuing drift detection.

## 11. Research-question resolutions

### RQ1. Is Proxmox the right host architecture?

**Conditional yes.** It is proportionate when the purpose is real dev/test/prod failure-domain separation, restore rehearsal, and bounded VM lifecycle automation. It is not justified by 32 GB RAM alone. Reject it if wired networking, SSD compatibility, thermals, unattended recovery, or backup restore cannot pass the qualification gate. In that case, use bare-metal Linux plus Compose as the simpler fallback, accepting weaker environment isolation.

### RQ2. What disk and storage layout is required?

Replace the HDD with a qualified SSD. Keep Proxmox and VM disks on the internal SSD, but split guest OS/artifacts, Postgres, vault replica/staging, and runtime/instance state into separate virtual volumes for quota and restore control. Put all backups on independent media. Default to the simplest supported one-disk storage; use ZFS only as an explicit checksumming/snapshot choice, never as a redundancy claim.

### RQ3. What isolation level is justified between dev, test, and prod?

Separate Linux VMs are justified because they isolate operating systems, processes, credentials, networks, volumes, Postgres, and destructive test lifecycle. Three physical machines are not justified for this one-operator scale. Test is off by default; prod plus at most one loaded non-prod VM is the initial 32 GB scheduling rule.

### RQ4. Should Postgres be per environment or centralized?

Keep one Postgres service inside each environment's VM/Compose project. Do not centralize it initially. Reconsider only with measured resource pressure and a complete replacement isolation, ACL, migration, and backup contract.

### RQ5. Can an iCloud vault safely be the active server source?

Not as a direct Linux/Proxmox writable mount. iCloud can remain the user-facing synchronization transport and content location, but the server must consume a registered replica/snapshot and route writes through a supported Mac endpoint. Any other conclusion requires live proof of a supported coherent Linux filesystem client, which current Apple and Obsidian evidence does not provide.

### RQ6. Which bridge/replica model preserves full Obsidian access?

A Mac keeps complete vault roots hydrated and exposes a narrow versioned mutation/replication protocol. Every server write is vault-bound, revision-checked, authorized, idempotent, receipted, and conflict-staged. The server may index local replicas, but it never silently promotes them to content authority. No folder-level selective publication is used.

### RQ7. Which settings model avoids a hidden master vault and drift?

Hybrid by authority domain. Central instance/channel policy owns safety ceilings and deployment wiring; vault settings own per-vault user intent; device state owns machine-local tuning; `.obsidian` remains Obsidian-owned; ephemeral overrides are allowlisted. The resolver emits provenance and last-valid/degraded receipts. No master vault writes other vaults' configuration.

### RQ8. Which data is local, in iCloud, or potentially in a cloud service?

Complete human vaults live in iCloud and on the hydrated Mac; server replicas, indexes, caches, environment Postgres, runtime state, and deployment control state remain local with independent backups. Secrets remain role/environment scoped and outside vaults. A future cloud service may replicate encrypted policy/control or managed data, but it must not become the only copy or silently take content authority.

### RQ9. When is a cloud control plane justified and what must it provide?

Only when multiple physical runtime nodes, multiple operators, off-site availability, or measured remote-management cost exceed the local model's capabilities. It must be optional/offline-safe, per-vault and per-environment scoped, versioned/CAS-protected, encrypted, receipted, exportable, restorable, least-privilege, and unable to weaken local security ceilings or replace vault/Obsidian authority.

### RQ10. How can agents safely observe and control Proxmox?

Use Proxmox REST API ACLs and separated tokens through a named allowlisted adapter: read-only inventory globally, optionally start/stop/restore `yg-test`, and guest-level deploy for dev. Keep prod mutation, host upgrades, networking, storage, deletion, and token management behind explicit owner authority. SSH is bootstrap/break-glass, not the normal agent plane.

### SBS reconciliation

The proposal **conforms** to the SBS by remaining an enabling Platform/Operations topology rather than a new Product/Runtime boundary. It **extends** the Platform and Operations specification with a Proxmox/VM target and a vault-bridge seam. It extends WSP/MVR and Settings Spine only through their existing identity, context, and resolution owners. It does not reshape the SBS unless later design assigns cross-node federation authority to a new Product subsystem; current SFC remains a single-node/no-op future seam.

## 12. Alternatives and trade-offs

### 12.1 Host alternatives

| Option | Strength | Cost/risk | Verdict |
|---|---|---|---|
| Keep Mac mini + Colima | Lowest migration cost; native iCloud | Shared failure domain and existing Colima/checkout drift | Valid short-term baseline, not isolation target |
| Bare-metal Linux + Compose | Simple and efficient | Environment isolation remains mostly logical | Fallback if laptop fails VM qualification |
| Single-node Proxmox | Strong VM isolation, snapshots, repeatable restore, scoped API | More operations; one-node/one-disk failure remains; iCloud needs Mac bridge | Recommended conditionally |
| Kubernetes/cluster | Scheduling and declarative control | Disproportionate complexity; no HA hardware | Reject |

### 12.2 Vault transport alternatives

| Option | iPad fit | Linux fit | Consistency risk | Verdict |
|---|---:|---:|---:|---|
| Direct iCloud on Linux | nominal | unsupported | very high | Reject |
| Windows iCloud VM | yes | indirect | Obsidian warns of duplication/corruption | Reject for prod writer |
| Mac bridge + iCloud | yes | explicit API/replica | manageable but eventually consistent | Recommend under hard iCloud constraint |
| Obsidian Sync/headless | yes | stronger | conflicts with hard iCloud/mixing rule | Best alternative only if iCloud constraint changes |
| Syncthing/Git on same live root | variable | good | dual-sync conflict | Reject while iCloud is active |

### 12.3 Settings alternatives

| Option | Benefit | Failure mode | Verdict |
|---|---|---|---|
| Everything in each vault | portable | vault can alter security/deployment; device-local data syncs | Reject |
| Master vault pushes settings to all vaults | one editing point | hidden coupling, overwrites per-vault UI/plugins, unclear conflict authority | Reject |
| Yggdrasil declarative registry/policy only | uniform runtime control | cannot legitimately own Obsidian UI or human content preferences | Use for central policy domains only |
| Hybrid authority domains | safe, portable, compatible with existing spine | requires typed schema/receipts | Recommend |
| Future cloud settings/sync plane | multi-node/off-site potential | offline dependency and new security/data authority | Defer until trigger is measured |

## 13. Dependency-ordered implementation handoff

This is a planning handoff only. `feature-breakdown` should turn accepted slices into specifications and then reconcile/create Issues. Existing Issues must be reused when their contracts already own the work.

| Order | Candidate slice | Dependency | Verify target | Backlog reconciliation |
|---:|---|---|---|---|
| 0 | Accept/revise this target and record genuine owner decisions | none | owner receipt names host, bridge, RPO/RTO, agent-control posture | no Issue yet |
| 1 | HP hardware and SSD qualification | 0 | inventory + VT/NIC/storage/thermal/power/pveperf report; fail-closed verdict | new Platform/Operations spec likely |
| 2 | Promote host/VM invariants into owner docs and test registry | 0 | each invariant has owner, producer, GATE/DOCTOR target | extend Platform/Operations; no runtime claim |
| 3 | Build lab Proxmox baseline and independent backup target | 1-2 | rebuild from documented install; firewall scan; backup/restore one empty VM | new platform slice |
| 4 | Produce minimal Linux VM template and channel manifests | 3 | reproducible VM from template; no secrets; pinned versions | reuse startup redesign #4913/#4914-#4918 where applicable |
| 5 | Prove dev/test physical isolation and per-VM Postgres | 4 | negative prod-route/credential tests; DB destroy/restore confined to test | reconcile #4899, #4326, #4517, #4539 |
| 6 | Complete immutable build-once promotion path | 4-5 | identical image digest in test/prod; no prod bind mount; current-SHA health | release/startup program |
| 7 | Specify and prototype Mac vault bridge with synthetic vaults | 2 | offline, hydration, stale-base, idempotency, conflict-copy, case/Unicode, symlink tests | new Product/Platform seam spec; reconcile ADR-0055/CONCURRENCY |
| 8 | Correct settings authority/location semantics for iCloud | 2,7 | effective-value provenance; vault cannot weaken ceilings; device-local value does not sync | reuse Settings Spine #3156/#4797/#4798 |
| 9 | Complete production MVR context propagation and rebind | 7-8 | two simultaneous sessions/vaults across API/worker/watcher/settings/retrieval/write with no bleed | reuse #2143 and #3860-#3869 |
| 10 | Add bridge-backed full-vault migration tooling | 7-9 | dry-run inventory; reversible copy; identity preservation; no missing `.obsidian`/settings/attachments | new bounded migration slice |
| 11 | Implement four-set backup and recovery receipts | 3,7,10 | restore VM+DB+vault+control state into test; measured RPO/RTO | extend operations; avoid treating old dev snapshot as DR |
| 12 | Add scoped Proxmox API adapter | 3,5 | token census; test lifecycle succeeds; every forbidden prod/host/delete call denied | new Platform/Builder boundary slice |
| 13 | Non-prod soak and fault injection | 6-12 | power loss, bridge outage, Mac offline, disk pressure, DB restore, network partition evidence | verification issue only if needed |
| 14 | Production cutover and rollback rehearsal | 13 | operator-acknowledged plan; independent backups; old host retained; rollback succeeds | prepare/execute/verify promotion chain |
| 15 | Current-state docs writeback and legacy retirement | 14 | owner docs match live topology; no target-as-current claims; old wrappers retired only with usage proof | post-merge owner-doc lane |

No slice should open a second vault registry, settings resolver, promotion state machine, or deployment authority. The MVR, Settings Spine, release-channel, and startup-redesign programs remain the executable owners for their existing scopes.

## 14. Genuine owner decisions

The architecture can default most choices, but these decisions affect cost or authority and belong to the owner:

1. **Mac bridge availability:** accept that iCloud makes a Mac the eventual write-application dependency, including queued/deferred Yggdrasil writes while it is offline. Recommendation: retain one always-on or regularly available Mac and designate it as bridge/backup source. If that is unacceptable, relax the hard iCloud requirement and evaluate Obsidian Sync instead.
2. **Storage and backup spend:** choose the supported SSD and an independent backup target after hardware inventory. Recommendation: do not start the platform migration with the HDD or without off-disk restore proof.
3. **Recovery objectives:** set production vault and DB RPO/RTO. Recommendation for the first target: vault backup daily plus version history, DB dump at least daily, and restore within one operator session; tighten only when measured need justifies WAL/PBS complexity.
4. **Remote management reach:** decide whether only named tailnet endpoints need access or the full home LAN must be reachable. Recommendation: endpoints first; subnet router only for non-Tailscale devices; no exit node by default.
5. **Agent privilege ceiling:** decide whether agents may mutate only `yg-test` or also `yg-dev`. Recommendation: read-only globally, lifecycle/restore on test, guest-level deploy on dev, no standing prod/host mutation.

## 15. Owner documents to update after acceptance or delivery

Do not update these as if the target were shipped. After target acceptance, update target-state owners; after cutover, update current-state owners:

- `docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md` — accepted Proxmox/VM target and platform authority;
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` — Compose-inside-VM deployment target, artifact and cutover contract;
- `docs/RELEASE_CHANNELS/README.md` — VM-aware promotion/rollback and database/vault separation;
- `docs/ENVIRONMENTS.md` — host-to-VM binding, device-local settings semantics, and complete-vault rules;
- `docs/MULTI_VAULT_RUNTIME/README.md` — bridge integration only through existing binding/context owners;
- `docs/SETTINGS_SPINE/README.md`, `docs/SETTINGS.md`, and `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md` — authority-domain precedence and iCloud-locality correction;
- `docs/CONCURRENCY.md` and `docs/testing/invariant-tests.md` — bridge conflict, case/Unicode, hydration, and isolation enforcement;
- `docs/OPERATIONS.md` — backup, recovery, bridge, VM, and Proxmox runbooks;
- `docs/INFRASTRUCTURE.md` and `ops/host-setup/README.md` — current topology only after the cutover;
- security/network owner surfaces located through `docs/DOCS_INDEX.md` — ACL, token, exposure, and secret boundaries;
- `docs/DOCS_INDEX.md` — role/date/description changes in the same governed doc updates.

## 16. External evidence

- [Proxmox VE Administration Guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf) — platform requirements, storage guidance, API/ACL model, `pveperf`, VM backup and restore tooling.
- [Apple: Set up iCloud Drive](https://support.apple.com/en-us/118443) — supported iPhone/iPad, Mac, Windows, and web setup surfaces.
- [Apple: Work with folders and files in iCloud Drive](https://support.apple.com/en-gb/guide/mac-help/-mchl1a02d711/mac) — `Keep Downloaded` behavior.
- [Obsidian: Sync your notes across devices](https://obsidian.md/help/sync-notes) — complete-vault filesystem model, platform recommendations, iCloud/Windows warning, keep-downloaded and avoid-mixed-sync guidance.
- [Obsidian: Back up your Obsidian files](https://obsidian.md/help/backup) — synchronization is not backup.
- [Obsidian: Sync settings and selective syncing](https://obsidian.md/help/sync/settings) — device-specific settings, conflict choices, `.obsidian` handling, and configuration profiles.
- [Tailscale: Subnet routers](https://tailscale.com/docs/features/subnet-routers) — private-subnet routing versus exit-node internet egress.
- [Tailscale: Policy syntax](https://tailscale.com/kb/1337/policy-syntax) — grants/ACL behavior and policy tests for routes.

## 17. Research limits and promotion gate

This was repository and vendor-document research. It did not run live host qualification, Proxmox installation, iCloud concurrency experiments, restore drills, or network scans. Resource numbers and bridge behavior are hypotheses until those gates pass.

Promotion sequence:

1. owner accepts or revises the target decisions;
2. `feature-breakdown` creates bounded specs and reconciles the existing backlog;
3. owner documents accept the normative parts;
4. implementation Issues deliver the gates in dependency order;
5. only verified current reality is written back to current-state docs.

Until then, this audit creates no platform, vault, settings, security, or backlog authority.
