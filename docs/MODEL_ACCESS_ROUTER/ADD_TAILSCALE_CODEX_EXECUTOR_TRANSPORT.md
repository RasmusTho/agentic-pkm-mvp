---
name: Add Tailscale Codex Executor Transport
description: Add one bounded Product completion API/client over a private Tailscale Serve endpoint, dispatching an exact declared Codex CLI or Ollama route.
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

Provide a thin cross-host completion path from Product on Linux to the host-local Codex CLI or
Ollama on macOS. Product continues to select the exact target; the API hides the harness protocol
and does not move Product policy, Product runtime, credentials, or general-purpose execution to the
Mac.

## What This Task Does

Add one `POST /v1/complete` operation and a Product-side client. Product supplies an already
resolved provider/model/transport identity, optional Codex reasoning effort and output schema,
capability intent, trusted instructions, and user input as separate fields. The request does not
accept shell commands, argv, paths, arbitrary environment variables, files, tools, MCP servers,
provider endpoints, or credentials. Unknown fields fail closed. The executor checks the route
against the declared provider census and adapter capabilities, then dispatches exactly once to the
declared `codex_cli` or `ollama_http` adapter.

Codex uses the existing bounded no-tools `CodexCliExecutor`; trusted instructions map to its
separate `developer_instructions` channel and user content stays in the prompt. Requests requiring
native tools or a literal system role are rejected on Codex. Ollama uses one local `/api/chat`
request with separate `system` and `user` messages. No provider is selected implicitly.

The host service exposes only `/v1/complete`; docs, OpenAPI, health, catalog, and preflight routes
are disabled. It binds only to loopback and requires the configured Serve-forwarded
`Tailscale-App-Capabilities` claim for `channel=product` and `actions=["complete"]`. It does not
authorize from request-body claims or ordinary identity headers. Tailscale Serve 1.92 or later is
required to forward app capabilities. The Uvicorn runner disables proxy-header rewriting so the
loopback guard sees the local Serve connection rather than the remote peer in `X-Forwarded-For`.
No Funnel/public endpoint, direct LAN listener, shared bearer token, or unencrypted fallback is
allowed. The grant, endpoint, Codex safe-profile path, CLI environment, and Ollama endpoint remain
operator-owned host configuration, not Git policy.

Bound request/response bytes, adapter concurrency, and execution time. Do not log prompts, output,
capability claims, endpoint identity, or raw adapter output. The Product client uses verified HTTPS,
performs one POST, validates that the response route matches the request, and never retries or
switches provider after an ambiguous result. This slice adds no automatic Codex-to-Ollama fallback,
model discovery, latest-model promotion, catalog endpoint, or live host/Tailscale activation.

## Concretely

The Product client calls a configured private Tailscale Serve HTTPS origin. Serve injects the
authorized app-capability claim into the loopback request; the Product client does not create or
send that header itself. Tests use fake Codex CLI and Ollama adapters and fake HTTP/Tailscale
boundaries to prove exact routing, channel separation, loopback/auth enforcement, and no retry after
an ambiguous completion.

## Why This Matters

The Product runtime and subscription-backed Codex CLI are on different hosts. A direct local
subprocess adapter cannot service deployed Product traffic. A narrow identity-bound remote
protocol closes that topology gap without turning the macOS host into a Product API/gateway or
reusing its local user identity as a shared credential.

## Acceptance Criteria

- [ ] The API accepts only a bounded resolved route and dispatches one declared Codex CLI or Ollama completion.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_complete_dispatches_one_declared_transport`
- [ ] The executor is loopback-only and refuses requests without the configured Product Serve capability; request data cannot self-authorize or widen the operation surface.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_complete_requires_loopback_and_served_app_capability`
- [ ] Codex uses the exact requested model, preserves trusted/user channels, and rejects tool intent.
  - Verify: `tests/model_access/test_codex_executor_service.py::test_codex_complete_preserves_channels_and_rejects_tools`
- [ ] The Product client uses verified HTTPS, returns the exact resolved route identity, and sends no retry or provider switch after an ambiguous execution result.
  - Verify: `tests/model_access/test_codex_remote_transport.py::test_remote_complete_is_route_bound_and_never_retries`
- [ ] This specification identifies catalog discovery, automatic fallback, caller migration, host activation, and staged rollout as separate follow-ups, not API prerequisites.
  - Verify: `docs/MODEL_ACCESS_ROUTER/README.md :: Implementation Tasks and Parent Capability Acceptance`

## How to Verify (Pre-Merge)

- Run `pytest -q tests/model_access/test_codex_executor_service.py tests/model_access/test_codex_remote_transport.py`.
- Use fake HTTP/Tailscale capability headers, fake Codex CLI, and fake Ollama HTTP; do not alter a live tailnet, start a host service, read host credentials, or invoke a live model.
- Test absent/malformed/wrong-channel capability claims, non-loopback peer/bind refusal, request schema abuse, TLS endpoint validation, bounded bodies, timeout ambiguity, and single execution.

## Out of Scope

- Editing tailnet grants, applying tags, enabling HTTPS/Serve, installing or starting a host service, provisioning credentials, or changing release channels.
- Moving Product API/gateway/runtime services to the macOS host.
- Product caller migration, dynamic model discovery/latest promotion, and automatic provider fallback; these have separate task contracts.
- Arbitrary shell/tool execution or model/provider fallback after execution may have started.

## Related Docs

- docs/adr/ADR-0066-shared-model-access-router-and-catalogs.md
- docs/MODEL_ACCESS_ROUTER/README.md
- docs/MODEL_ACCESS_ROUTER/BUILD_ADAPTER_REGISTRY_AND_CODEX_CLI_TRANSPORT.md
- docs/MODEL_ACCESS_ROUTER/PROVE_MAC_MINI_ACCEPTANCE.md

## Related GitHub Issues

Created from this specification; issue number is written here when filed.
