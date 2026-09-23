---
name: Add Tailscale Codex Executor Transport
description: Connect Product's Linux router to the macOS Codex executor over a private Tailscale Serve endpoint with app-capability authorization and a bounded request protocol.
task_id: MARR-08
github_issue: 5635
source_anchor: docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md :: D2
parent_capability: MODEL_ACCESS_ROUTER
prerequisites: [MARR-01, MARR-02]
depends_on: [ESTABLISH_SHARED_ROUTE_AND_PROVENANCE_CONTRACTS.md, BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md]
can_parallelize_with: []
---

# ADD_TAILSCALE_CODEX_EXECUTOR_TRANSPORT

## Purpose

Provide the missing cross-host path between Product on Linux and the host-local Codex CLI session
on macOS without moving Product runtime, credentials, policy authority, or unrestricted execution
to the macOS host.

## What This Task Does

Add a narrow Product-side remote adapter and a host-side executor API around the MARR-02 local
Codex adapter. The only operations are sanitized read-only catalog retrieval, model preflight, and a
single bounded inference request. The request schema accepts a resolved provider/model/effort,
declared capability intent, output schema, trusted instructions, and user input as distinct fields;
it does not accept shell commands, argv, paths, arbitrary environment variables, files, MCP
servers, or caller-selected credentials.

Expose the host service only through Tailscale Serve HTTPS. Serve forwards one narrowly scoped app
capability for authorized Product workload identities. The upstream service binds exclusively to
loopback and rejects absent, malformed, unrecognized, or wrong-channel
`Tailscale-App-Capabilities`; it does not authorize from user-supplied body fields or ordinary
identity headers. No Funnel/public endpoint, direct LAN listener, shared bearer token, or
unencrypted fallback is allowed. The grant and exact Serve endpoint remain operator-owned
host/tailnet configuration, not repository policy.

Use separate `/v1/catalog`, `/v1/preflight`, and `/v1/execute` operations. Catalog and preflight
never send an inference request. Product may choose Ollama only after the remote preflight fails
before `/v1/execute` is sent. Once an execute request may have reached the executor, any lost
response or timeout is terminal/indeterminate and must not retry or call Ollama. Bound request and
response sizes, concurrency, and timeouts; redact prompts, capability claims, Tailscale identity,
endpoint, and raw CLI output from logs and receipts.

The backend may trust forwarded app-capability headers only while bound to loopback behind Serve.
Record the supported Tailscale/Serve minimum and verified auth scheme as non-secret profile
metadata. If Serve cannot forward app capabilities, no substitute authentication method is
implicitly accepted.

## Concretely

The Product adapter calls the configured private service address using verified TLS. A fake Serve
boundary injects the authorized app-capability claim into the loopback request. Tests prove the
caller cannot authorize itself, choose a different Product channel, supply arbitrary process
configuration, or cause a second provider execution after an ambiguous timeout.

## Why This Matters

The Product runtime and subscription-backed Codex CLI are on different hosts. A direct local
subprocess adapter cannot service deployed Product traffic. A narrow identity-bound remote
protocol closes that topology gap without turning the macOS host into a Product API/gateway or
reusing its local user identity as a shared credential.

## Acceptance Criteria

- [ ] The host executor exposes only schema-validated catalog, preflight, and single-execution operations; no arbitrary command, path, environment, file, or tool surface is reachable.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_executor_exposes_only_bounded_model_operations`
- [ ] The backend binds to loopback only, and requests fail closed without the expected Serve-forwarded app capability and authorized Product channel.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_executor_requires_loopback_and_channel_scoped_app_capability`
- [ ] The Product remote adapter uses verified TLS to the private configured executor endpoint and does not emit endpoint or identity secrets in provenance.
  - Verify: `tests/model_access/test_codex_remote_transport.py::test_transport_uses_private_tls_and_secret_free_provenance`
- [ ] Catalog/preflight operations make no model call; Ollama fallback remains eligible only before an execute request can reach the host.
  - Verify: `tests/model_access/test_codex_remote_transport.py::test_preflight_failure_allows_only_pre_send_fallback`
- [ ] An ambiguous timeout after execute is sent is terminal and does not retry Codex or invoke Ollama.
  - Verify: `tests/model_access/test_codex_remote_transport.py::test_execute_timeout_is_indeterminate_and_never_falls_back`
- [ ] Payload limits, output limits, concurrency bounds, strict message-channel separation, and prompt/output redaction are enforced.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_executor_bounds_and_redacts_remote_requests`
- [ ] The app-capability wire contract uses Tailscale Serve's forwarded capability header only when the installed version supports it; unsupported Serve versions fail closed.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_unsupported_serve_profile_fails_closed`

## How to Verify (Pre-Merge)

- Run `pytest -q tests/model_access/test_codex_executor_service.py tests/model_access/test_codex_remote_transport.py`.
- Use fake HTTP/Tailscale identity middleware and the fake Codex executor; do not alter a live tailnet, start a host service, access credentials, or invoke a live model.
- Test absent/forged/wrong-channel app-capability claims, non-loopback bind refusal, request schema abuse, stale catalog, TLS failure, body limits, timeout ambiguity, redaction, and single-execution behavior.

## Out of Scope

- Editing tailnet grants, applying tags, enabling HTTPS/Serve, installing or starting a host service, provisioning credentials, or changing release channels.
- Moving Product API/gateway/runtime services to the macOS host.
- Arbitrary shell/tool execution or model/provider fallback after execution may have started.

## Related Docs

- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/MODEL_ACCESS_ROUTER/README.md
- docs/MODEL_ACCESS_ROUTER/BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md
- docs/MODEL_ACCESS_ROUTER/PROVE_MAC_MINI_ACCEPTANCE.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
