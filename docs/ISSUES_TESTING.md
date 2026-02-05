State: Testing backlog (SoT v5.5 baseline). This file tracks gaps that are not yet covered by CI smoke/pytest suites.
# Testing Coverage Issues

## router-malformed-intent
- Status: obsolete (v4.x)
- Scope: v5.5 runtime no longer has the v4.x router/fabric stack (`app/llm/router.py`, `LLMTaskIntent`, etc.). If we reintroduce a router/fabric layer, track malformed intent handling under the new module names and add tests there.

## fabric-provider-unavailable
- Status: obsolete (v4.x)
- Scope: v5.5 runtime no longer has the v4.x fabric stack. Provider-unavailable behavior should be covered under the current LLM adapter (`app/llm/adapter.py`) and embedding client (`app/llm/embeddings.py`) instead.

## health-future-timestamp
- Status: open
- Scope: add/verify coverage for rejecting future heartbeat timestamps (clock skew) in the health contract / status service heartbeat readers.
