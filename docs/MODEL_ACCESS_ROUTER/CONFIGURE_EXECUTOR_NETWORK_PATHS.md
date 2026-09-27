---
name: Configure VLAN-primary and Tailscale-fallback executor paths
description: Specify config-driven VLAN-first executor routing with private Tailscale fallback, independent of model/provider selection.
task_id: MARR-09
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D2, D3
parent_capability: MODEL_ACCESS_ROUTER
depends_on: [MARR-01, MARR-02, MARR-05, MARR-08]
---

# CONFIGURE_EXECUTOR_NETWORK_PATHS

## Purpose

Separate how Product reaches a remote model executor from which model/provider the executor uses.
For the Ygg deployment, select the designated macOS executor over the shared VLAN first and use the
configured private Tailscale path only when a no-inference connectivity or preflight check shows
that the VLAN path is unavailable.

## Contract

- A logical executor profile is independent of network transport, endpoint address, and model
  provider. Product model policy names the logical executor and exact route; deployment config names
  an ordered list of network path profiles.
- The Ygg environment configures the VLAN profile first and Tailscale Serve profile second. Both
  resolve through the same path-adapter interface. Concrete addresses, host identities, and secrets
  remain in host-local config and do not enter Product settings, source code, or receipts.
- The path adapter checks connectivity and performs route-bound preflight without inference. It may
  advance to the next configured path only before completion and only for the same logical executor,
  exact model, reasoning effort, and capability intent. Failover is limited to these typed,
  path-local outcomes: `PATH_UNAVAILABLE`, `CONNECT_TIMEOUT`, `PREFLIGHT_TIMEOUT`, and
  `PATH_AUTHENTICATION_FAILED` (the candidate ingress could not establish its own caller identity).
- Application-level preflight failures are terminal unless they are one of those typed path-local
  outcomes. Common Product channel/action denial, malformed request, missing required model
  capability, route mismatch, missing or invalid path configuration, and common-policy
  authorization failure cannot be hidden by trying another path. The decision and reason code
  distinguish path authentication from common Product authorization.
- Every path authenticates the caller and authorizes the same Product channel and operation-specific
  action. VLAN membership, source IP, or request-body claims alone do not authorize the request.
  The Tailscale adapter validates its configured Serve-forwarded application capability. The
  executor backend remains loopback-bound; Funnel and public ingress are forbidden.
- The VLAN private-HTTPS adapter accepts only an HTTPS origin using a literal IPv4 address in
  RFC1918 space or a literal IPv6 unique-local address. DNS names are rejected so a host-local
  endpoint typo cannot send completion content to a public host. Tailscale Serve uses its separate
  verified `.ts.net` adapter.
- Once a completion may have reached the executor, a timeout or lost response is terminal. The
  client does not retry over another path, change provider, or send a second completion.
- Network-path fallback does not imply provider/model fallback. Those decisions remain separately
  configured and authorized by Product policy. The Luna Codex CLI route has no implicit Ollama
  fallback.
- Invalid common authorization, mismatched preflight, or an exhausted path list fails closed with a
  sanitized reason code.

Illustrative configuration shape (schema and filenames are implementation work):

```yaml
executor_path_policies:
  product_codex:
    order: [ygg_vlan_primary, tailscale_fallback]

path_profiles:
  ygg_vlan_primary:
    adapter: private_https_ingress
    endpoint_ref: host_config.ygg_codex_vlan
    authentication_profile_ref: host_config.ygg_vlan_auth
    caller_policy_ref: policy.product_channel_actions
  tailscale_fallback:
    adapter: tailscale_serve_https
    endpoint_ref: host_config.ygg_codex_tailnet
    authentication_profile_ref: host_config.ygg_tailscale_auth
    caller_policy_ref: policy.product_channel_actions
```

The references above are logical placeholders, not checked-in endpoint or credential values.

## Acceptance Criteria

- [ ] Configuration can order multiple named path profiles for one logical executor without adding
  transport or endpoint branches to model/provider policy.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_path_order_is_configuration_driven`
- [ ] Typed VLAN `PATH_UNAVAILABLE`, `CONNECT_TIMEOUT`, `PREFLIGHT_TIMEOUT`, or
  `PATH_AUTHENTICATION_FAILED` selects the configured Tailscale path while preserving the exact
  executor, model, effort, and capability intent.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_only_typed_path_local_failures_use_next_path`
- [ ] Common authorization denial, malformed request, route mismatch, missing path configuration,
  and capability mismatch fail closed without trying another path.
  - Verify: `tests/model_access/test_executor_network_authorization.py::test_terminal_preflight_failures_do_not_use_another_path`
- [ ] Both VLAN and Tailscale paths enforce the same Product channel/action authorization contract;
  source IP or VLAN membership alone is rejected.
  - Verify: `tests/model_access/test_executor_network_authorization.py::test_paths_require_channel_and_action_authorization`
- [ ] An ambiguous completion result does not retry over another path or dispatch a second model
  completion.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_ambiguous_completion_does_not_fail_over`
- [ ] Endpoint values, host identities, credentials, and raw authorization claims are absent from
  checked-in policy, user-facing health output, and receipts.
  - Verify: `tests/model_access/test_executor_network_policy.py::test_path_receipts_are_logical_and_secret_free`

## Out of Scope

- Activating VLAN listeners, Tailscale grants, Serve, host services, or firewalls.
- Provisioning credentials or changing Product/model policy.
- Selecting a different model/provider after a path failure.
- Production deployment or release-pointer changes.
