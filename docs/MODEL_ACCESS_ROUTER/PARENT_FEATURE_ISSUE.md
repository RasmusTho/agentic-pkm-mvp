State: Open parent validation hub Issue #5618; lifecycle agent:blocked. Its contract was reconciled on 2026-09-27 to the ten-slice ledger and amended ADR-0066. It remains blocked until child delivery, separately authorized host acceptance, and rollout evidence are complete.

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

The parent closes only when the capability acceptance checklist in README.md is satisfied, all ten child-slice receipts are linked, and the cross-host designated-executor v3 receipt proves VLAN-first access, configured Tailscale fallback for typed path-local failures, equivalent channel/action authorization, Luna through Codex CLI, provider-neutral capability health, unsupported-capability refusal before inference, and a loopback-only service without leaking host identity or secrets. Ollama is not a Luna acceptance prerequisite. Authorized release-channel verification must be complete, and owner-doc changes must state only what is actually shipped. The parent remains blocked until these gates pass.
