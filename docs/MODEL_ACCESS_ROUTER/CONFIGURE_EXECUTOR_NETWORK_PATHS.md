---
name: Configure executor network paths
description: Define the VLAN-only Ygg executor path and retain optional config-driven path adapters independently of model/provider selection.
task_id: MARR-09
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D2, D3
parent_capability: MODEL_ACCESS_ROUTER
depends_on: [MARR-01, MARR-02, MARR-05, MARR-08]
---

# CONFIGURE_EXECUTOR_NETWORK_PATHS

## Purpose

Separate how Product reaches a remote model executor from which model/provider the executor uses.
The current Ygg deployment selects the designated macOS executor over the shared VLAN. VLAN is the
only configured or required path; Tailscale is not part of current acceptance or rollout.

## Contract

- A logical executor profile is independent of network transport, endpoint address, and model
  provider. Product model policy names the logical executor and exact route; deployment config names
  an ordered list of network path profiles.
- The checked-in Ygg environment configures only `ygg_vlan_primary`. The shared path-adapter
  interface can accept additional paths when a future deployment explicitly configures them; no
  Tailscale endpoint, Serve profile, grant, or fallback is required here. Concrete addresses, host
  identities, and secrets remain in host-local config and do not enter Product settings, source
  code, or receipts.
- The path adapter checks connectivity and performs route-bound preflight without inference. It may
  advance to the next configured path only before completion and only for the same logical executor,
  exact model, reasoning effort, and capability intent. Failover is limited to these typed,
  path-local outcomes: `PATH_UNAVAILABLE`, `CONNECT_TIMEOUT`, `PREFLIGHT_TIMEOUT`, and
  `PATH_AUTHENTICATION_FAILED` (the candidate ingress could not establish its own caller identity).
- Application-level preflight failures are terminal unless they are one of those typed path-local
  outcomes. Malformed requests, missing model capabilities, route mismatch, and missing or invalid
  path configuration cannot be hidden by trying another path.
- The current configured path requires mutual TLS at the private VLAN ingress. The executor backend
  remains loopback-bound and accepts no Tailscale-injected capability claim; no per-action claim or
  shared bearer token is required for this single-operator deployment. Model capability checks still
  validate each route before inference. Public ingress is forbidden.
- The VLAN private-HTTPS adapter accepts only an HTTPS origin using a literal IPv4 address in
  RFC1918 space or a literal IPv6 unique-local address. DNS names are rejected so a host-local
  endpoint typo cannot send completion content to a public host. Tailscale is not required for the
  current VLAN-only Product portal.
- Once a completion may have reached the executor, a timeout or lost response is terminal. The
  client does not retry over another path, change provider, or send a second completion.
- Network-path fallback does not imply provider/model fallback. Those decisions remain separately
  configured and authorized by Product policy. The Luna Codex CLI route has no implicit Ollama
  fallback.
- Invalid common authorization, mismatched preflight, or an exhausted path list fails closed with a
  sanitized reason code.

The active Ygg profile is VLAN-only. Its checked-in shape is:

```yaml
executor_path_policies:
  profile.codex_remote_host:
    order: [ygg_vlan_primary]

path_profiles:
  ygg_vlan_primary:
    adapter: private_https_ingress
    endpoint_ref: host_config.ygg_codex_vlan
    authentication_profile_ref: host_config.ygg_vlan_mutual_tls
    caller_policy_ref: policy.vlan_mtls_authenticated_caller
```

The references above are logical placeholders, not checked-in endpoint or credential values.
Additional adapter profiles and ordered failover remain generic capabilities, but must be configured
explicitly before use; they are not implicit Ygg dependencies.

## Acceptance Criteria

- [ ] Configuration can order multiple named path profiles for one logical executor without adding
  transport or endpoint branches to model/provider policy.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_path_order_is_configuration_driven`
- [ ] The generic path router uses the next path only when an additional compatible path is
  explicitly configured and a typed path-local failure occurs before completion; the current Ygg
  profile contains no second path.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_only_typed_path_local_failures_use_next_path`
- [ ] Malformed request, route mismatch, missing path configuration, and capability mismatch fail
  closed without trying another path.
  - Verify: `tests/model_access/test_executor_network_authorization.py::test_terminal_preflight_failures_do_not_use_another_path`
- [ ] The configured Ygg path is VLAN-only, uses mutual TLS, and the loopback backend does not need
  a Tailscale Serve header.
  - Verify: `tests/model_access/test_executor_network_authorization.py::test_configured_mtls_vlan_path_is_the_only_executor_path`
- [ ] An ambiguous completion result does not retry over another path or dispatch a second model
  completion.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_ambiguous_completion_does_not_fail_over`
- [ ] Endpoint values, host identities, credentials, and raw authorization claims are absent from
  checked-in policy, user-facing health output, and receipts.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_path_receipts_are_logical_and_secret_free`

## Out of Scope

- Activating host services, listeners, or firewall policy.
- Provisioning credentials or changing Product/model policy.
- Selecting a different model/provider after a path failure.
- Production deployment or release-pointer changes.
