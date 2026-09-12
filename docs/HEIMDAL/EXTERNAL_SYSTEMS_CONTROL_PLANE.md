State: Accepted owner-directed target-state boundary (2026-09-12); no separately deployed control-plane implementation is claimed.
Doc role: Heimdal external-systems ownership contract
Authority: Owns the ecosystem-level operational ownership boundary for external helper systems. Product meaning, security policy, Builder delivery authority, and the semantics of Heimdal's observation stream remain with their existing owner documents.
Owner: Heimdal / Yggdrasil ecosystem operations
Temporal class: strategic
Review cadence: event-driven, when an external system, credential boundary, or operational channel changes
Source of truth: this contract for ownership; Builder Vault for concrete helper-system records and runbooks; provider systems for provider-side state
Last reviewed: 2026-09-12

# Heimdal External Systems Control Plane

## Decision

Heimdal is the single Yggdrasil owner for external helper systems and their operational
relationships. This includes external accounts, channels, webhooks, service identities, credential
references, integration lifecycle, health/alert routes, runbooks, replacement, and retirement.

This is an **operational ownership** boundary. It does not make Heimdal the semantic authority for
Product/Runtime data, Builder delivery state, security policy, or the meaning of an observation.
Heimdal's existing sensor responsibility remains valid: its observation path publishes attributed
events; the external-systems control plane manages the machinery used to operate the ecosystem.

Heimdal may itself be attached as a helper capability to another Yggdrasil surface. That does not
create a second owner or a new authority path. A minimal independent liveness check may observe
Heimdal so that the owner is not the only witness of its own failure.

## Ownership map

| Concern | Owner | Boundary |
| --- | --- | --- |
| External helper-system registry, lifecycle, identity, channel topology, runbooks, and operational status | Heimdal | One canonical operational registry; no personal or subsystem-owned duplicate |
| Host, VM, Docker, Proxmox, channel execution, and recovery mechanics | Yggdrasil Platform and Operations System | Executes already-authorized operations; does not become the helper-system authority |
| Webhook, API, or MCP adapter implementation | Integration Fabric | Reusable transport/capability layer under Heimdal's ownership contract |
| Security policy, credential scope, exposure, and rotation rules | Security/deployment owner documents | Heimdal must comply with these rules; it does not silently weaken them |
| Source health and domain truth | The source system, such as BuilderOps, Product/Runtime, or Proxmox | Heimdal observes and routes the signal; it does not replace the source authority |
| Provider-side account state | The external provider, operated through a Heimdal-owned identity | Provider state is external; its local representation is recorded in Builder Vault |
| Human-facing operational record | Builder Vault | Canonical catalog and runbooks for external helper systems |

## Builder Vault is the operational source

Builder Vault is the single human-readable source for concrete external helper-system records. The
repository must not grow a second hand-maintained inventory of servers, channels, webhook URLs,
provider accounts, or credential values.

Each Builder Vault record should answer, at minimum:

- stable `system_id` and provider;
- purpose, capability class, environment/channel scope, and current status;
- `owner_system: Heimdal` and the responsible Heimdal service identity;
- provider-side server/account/channel identifiers, excluding bearer values;
- credential reference (for example a macOS Keychain service/account reference), never the secret;
- allowed operations and explicit authority limits;
- health/readiness endpoint, alert route, failure and degradation behavior;
- provisioning, rotation, recovery, replacement, and retirement runbooks;
- last verification time, evidence/receipt references, and known gaps.

The repository contains only the ownership contract, machine-readable schemas/validation where
needed, and pointers to the Builder Vault record. A generated or receipt-bound projection is a
mirror, not a second authority.

## Credential boundary

Heimdal owns the credential lifecycle, but secret material remains in the host's secure secret
store. For the Mac-hosted control path this is macOS Keychain under the existing
`yggdrasil.host-secrets` namespace. Builder Vault and the repository store only logical references,
scope, fingerprints where explicitly permitted, and rotation metadata.

No secret value may appear in Git, Builder Vault, ordinary configuration, Discord messages, logs,
issues, PRs, or receipts. A future Linux/Proxmox-hosted Heimdal process may use host-native secure
storage, but that is a custody migration, not permission to copy secrets into documentation.

## Shared Discord alert capability

Discord is a downstream delivery provider for one shared Yggdrasil alert capability:

- default route: one private `yggdrasil-alerts` channel;
- delivery: one-way incoming webhook managed by Heimdal;
- message contract: source system, environment, severity, transition, timestamp, correlation ID,
  and a redacted remediation pointer;
- state semantics: one notification on a sustained outage transition and one recovery notification;
- no acknowledgement, deployment, health, or semantic authority is granted to Discord;
- channel splits, if ever required, are by severity/privacy/audience, not by subsystem ownership;
- an optional Discord MCP may assist administration, but it is never part of the critical alert path.

The channel, webhook, provider account, and Keychain reference are not shipped by this document.
They require the bounded delivery work tracked by the observability Issues and a redacted live
drill receipt.

## Integration and event boundary

All external helper systems attach through the Integration Fabric contract. Adapters provide
capability or transport and must preserve provenance, timeout/failure visibility, replacement
posture, and authority separation. No adapter may create a second semantic source of truth or
bypass the event/receipt boundary for an effect that matters to Yggdrasil.

Heimdal's registry is an operational catalog in Builder Vault; it is not a runtime workflow store,
task queue, product database, or replacement for GitHub/BuilderOps delivery authority.

## Acceptance and change rule

This boundary is considered enacted only when:

1. the owner contract and Builder Vault record shape are merged and indexed;
2. concrete helper-system records identify Heimdal as owner and contain no secret material;
3. the Discord alert adapter has a Keychain-backed credential reference and a redacted outage /
   recovery drill receipt; and
4. each host or VM integration names the Platform and Operations execution boundary separately.

Changes to ownership, credential custody, provider exposure, or channel authority require an
architecture/owner decision before implementation. Routine provider configuration remains an
operational action under this contract.

## Related documents

- `docs/YGGDRASIL_PLATFORM_AND_OPERATIONS_SYSTEM/README.md`
- `docs/HEIMDAL/README.md`
- `docs/HEIMDAL/ECOSYSTEM_SOS_MODEL.md`
- `docs/INTEGRATION_FABRIC_CONTRACT.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md`
- `docs/OBSERVABILITY_STABILIZATION/SCHEDULED_PROBE_AND_PUSH_ALERT.md`
- `docs/SECURITY_ARCHITECTURE.md`
