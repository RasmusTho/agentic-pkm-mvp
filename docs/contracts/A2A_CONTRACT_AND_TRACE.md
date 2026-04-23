State: Aligned (forward line v5.x)
Doc role: Reference contract
Authority: Canonical current-state contract for the repo's A2A message schema, audit event names, and trace propagation examples. This document describes enacted behavior only and must stay aligned with `app/a2a/`, `app/events/types.py`, and the owning SoT docs.

# A2A Contract And Trace

This document describes the current A2A envelope used inside the repository for bounded agent-to-agent messages.
It is a current-state contract for schema shape, audit event naming, routing posture, and trace expectations.
It does not claim that orchestrator-managed A2A routing, queue semantics, or long-running multi-agent delivery are already shipped.

Use this document with:
- `docs/ARCHITECTURE.md` for current runtime boundaries and the "LangGraph inner, events/A2A outer" direction.
- `docs/AGENTS.md` for the current agent matrix and the fact that A2A coordination is still mostly planned beyond the deterministic scaffolding.
- `docs/EVENTS.md` for canonical outbox event envelope rules.
- `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md` for backlog/track context.

## Current posture

- A2A currently exists as an internal schema plus audit/event helpers under `app/a2a/`.
- The shipped message families are `request`, `response`, and `error`.
- The canonical audit/event names for those families are:
  - `agent.request.created`
  - `agent.response.created`
  - `agent.error.created`
- The docs/research backlog may still refer to `agent.error` as a shorthand family name. Current runtime reality is `agent.error.created`, and compatibility notes should preserve that distinction instead of silently renaming the emitted action.
- Current routing is in-process and call-site owned. This repo does not yet claim a production A2A transport, retry queue, or orchestrator-managed delivery layer.

## Message schema

The canonical schema lives in `app/a2a/schema.py`.
All A2A messages share this base shape:

| Field | Type | Current requirement | Meaning |
| --- | --- | --- | --- |
| `id` | UUID | required | Message identifier generated at creation time. |
| `kind` | `request` \| `response` \| `error` | required | Message family discriminator. |
| `sender` | string | required | Stable sender label. |
| `recipient` | string | required | Intended receiving agent/unit label. |
| `correlation_id` | string \| null | optional but supported on every family | Links related request/response/error messages inside one bounded exchange. |
| `trace_id` | string \| null | optional but supported on every family | Carries the broader operational trace across agent steps and audit logs. |
| `created_at` | datetime (UTC) | required | UTC creation time generated at message creation. |
| `payload` | object | required | Family-specific structured content; defaults to `{}`. |
| `metadata` | object | required | Non-semantic annotations; defaults to `{}`. |

Family-specific fields:

- `AgentRequest`
  - `intent`: string or null
- `AgentResponse`
  - `status`: `ok` | `partial` | `error`
- `AgentError`
  - `error_type`: string
  - `error_message`: string

## Trace and correlation rules

Current contract:

- `correlation_id` and `trace_id` are supported by all three message families and must be preserved when supplied.
- New request/response/error factory helpers must continue to expose both fields.
- Audit emission mirrors both values into the logged details payload.
- `trace_id` is also passed as the top-level audit trace when available.

Current limitation:

- The schema currently allows `correlation_id` and `trace_id` to be omitted (`null`).
- This document does not upgrade them to universally mandatory runtime fields because the repo does not yet claim a full A2A transport or timeout-managed execution contract.
- New callers should still provide them whenever the surrounding flow already has trace/correlation context.

## Routing and timeout posture

Current runtime truth:

- Requests are created in-process via `new_request(...)` or `send_agent_request(...)`.
- Responses and errors are represented by schema objects and can be emitted to audit via `emit_agent_response_event(...)` and `emit_agent_error_event(...)`.
- There is no shipped repo-wide timeout scheduler, retry loop, dead-letter queue, or delivery SLA for A2A messages.
- If a caller needs timeout behavior today, that policy lives in the owning caller/agent/orchestrator code path rather than in a central A2A runtime.
- Delivery-SLA terminal-state reporting for timeouts/failures is owned by orchestrator runtime/status surfaces, not by A2A transport.

Error taxonomy posture:

- `AgentError.error_type` is the current bounded error taxonomy field.
- The repo does not yet define a closed global enum for all A2A error categories.
- Existing code/tests show local values such as `not_ready`, `failed`, and `not_implemented`; callers should use stable machine-readable labels rather than prose-only categories.

## Panel trust-verb and APPLY receipt compatibility

Current runtime now carries bounded trust-verb and APPLY-accountability fields for the Panel mutation path while preserving the existing outbox envelope:

- Promotion-intent payloads emitted from Panel runtime include `trust_verb` and `action.trust_verb` when available from the panel action mapping.
- Mutation-capable panel actions (current promotion path) are admitted only when explicitly classified as `APPLY`; missing/invalid/non-`APPLY` trust-verb values are logged and not emitted as mutation intents.
- `promotion.transition.applied` payloads include accountability fields:
  - `verb`
  - `authority`
  - `basis`
  - `outcome`
  - `artifact_linkage`
  - `instance_provenance`

Compatibility posture:
- Event envelope shape (`event`, `event_id`, `trace_id`, `source`, `timestamp`, `payload`) is unchanged.
- Added payload fields are backward-compatible extensions; existing consumers that ignore unknown payload keys remain valid.

## Audit event mapping

The canonical event-type constants live in `app/events/types.py`.
Current mapping:

| Message family | Audit action emitted | Helper |
| --- | --- | --- |
| request | `agent.request.created` | `emit_agent_request_event(...)` |
| response | `agent.response.created` | `emit_agent_response_event(...)` |
| error | `agent.error.created` | `emit_agent_error_event(...)` |

Current logged detail fields always include:

- `message_id`
- `kind`
- `sender`
- `recipient`
- `correlation_id`
- `trace_id`
- `created_at`

Family-specific logged detail additions:

- request: `intent`, `payload_size`
- response: `status`, `payload_size`
- error: `error_type`, `error_message`, `payload_size`

## Worked trace example

Example bounded exchange for a review request:

1. `Classifier` creates a request for `Reviewer` with `correlation_id="corr-review-7"` and `trace_id="trace-review-42"`.
2. `emit_agent_request_event(...)` records `agent.request.created` with both ids in the audit details.
3. `Reviewer` cannot handle the request and returns an `AgentError` using the same correlation and trace ids.
4. `emit_agent_error_event(...)` records `agent.error.created`, preserving the same exchange identifiers.

Illustrative payloads:

```json
{
  "kind": "request",
  "sender": "Classifier",
  "recipient": "Reviewer",
  "intent": "review",
  "correlation_id": "corr-review-7",
  "trace_id": "trace-review-42",
  "payload": {"object_id": "obj-7"}
}
```

```json
{
  "kind": "error",
  "sender": "Reviewer",
  "recipient": "Classifier",
  "error_type": "not_implemented",
  "error_message": "Reviewer flow not wired for this request",
  "correlation_id": "corr-review-7",
  "trace_id": "trace-review-42",
  "payload": {"object_id": "obj-7"}
}
```

Expected audit sequence:

| Order | Action | Required trace fields |
| --- | --- | --- |
| 1 | `agent.request.created` | `correlation_id`, `trace_id` copied into details |
| 2 | `agent.error.created` | same `correlation_id`, same `trace_id` copied into details |

## Compatibility note

When older planning or research text says `agent.error`, read it as the broader error family label.
Current emitted runtime action is `agent.error.created`.
Do not rewrite current code/docs to claim the shorter name is the emitted action unless the actual constants and emitters change in the same bounded change.
