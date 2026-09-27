State: Open parent validation hub Issue #5618; lifecycle agent:blocked. It remains blocked until all child slices and integrated acceptance evidence are complete. The live parent Issue body still reflects the prior Tailscale-only/Ollama-acceptance target and must be reconciled before child pickup under the amended ADR-0066.

# Model Access Router Parent Feature Issue

This document is the local contract for the feature issue that will validate the shared Model Access Router capability. It is not a pickup task and does not authorize implementation outside the dependency-ordered child issues.

## Intended Parent Issue

Title: [ModelAccessRouter] model-access-router: shared Product and Builder access with governed discovery

Issue: #5618 (open, agent:blocked).
Initial state: agent:blocked; the parent waits on child work and host acceptance and is never agent:ready.

## Validation Hub Responsibilities

- Keep the child issue ledger and dependencies aligned with README.md.
- Record each merged child's validation receipt.
- Hold the integrated Product-Linux-to-Mac-mini proof, VLAN-primary/Tailscale-fallback path contract, common channel/action authorization, Codex CLI Luna route, provider-neutral capability health, and sanitized runtime receipt.
- Keep current-state owner docs unchanged until the capability acceptance gate passes.
- Hand off production rollout to the release-channel workflow; do not treat a PR merge as deployment approval.
- Close only after acceptance is complete and owner-doc writeback is resolved.

## Parent Closure Gate

The parent closes only when the capability acceptance checklist in README.md is satisfied, every child receipt is linked, the cross-host designated-executor receipt proves VLAN-first access, configured Tailscale fallback, equivalent channel/action authorization, provider-neutral capability health, and a loopback-only service without leaking host identity or secrets, release-channel verification is complete for the authorized target, and owner-doc changes state only what is actually shipped. The live parent Issue body must be reconciled before implementation pickup because it still names the superseded network and Ollama acceptance conditions.
