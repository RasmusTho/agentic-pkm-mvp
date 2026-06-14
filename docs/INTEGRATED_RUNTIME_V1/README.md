State: Non-authoritative planning package superseded for executable delivery by epic #1874 and child issues.

# Integrated Runtime v1 - Pre-Fable Package

Status: non-authoritative planning package. This directory prepares the handoff from the merged Integrated Runtime v1 evidence pack and errata into a future Fable synthesis pass.

Authority: planning draft only. GitHub Issues, owner docs, PRs, tests, and receipts remain the durable delivery truth. Nothing in this directory implements runtime behavior, creates product authority, or supersedes `docs/STATUS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, or the owning capability specs.

Source inputs:

- `docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK.md`
- `docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK_ERRATA.md`
- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`
- System Entry Point validation hub #1782, state-gallery closure #1795, review residuals #1851
- TTS readiness #1699 and voice acceptance/dogfood #1702

## Purpose

The project has many real runtime and UI capabilities, but they still read as islands until they share one production/operator loop. Integrated Runtime v1 is the proposed productization line that turns already-built capabilities into a coherent local-first Companion UI/operator workflow.

The proposed operating loop is:

```text
Start -> Orient -> Work -> Review -> Commit/Confirm -> Receipt -> Resume
```

## Non-negotiable boundaries

- The vault remains the human/canonical surface.
- Runtime projections are not truth.
- No hidden writes.
- WriteGuard, provenance, source/projection separation, and event/receipt separation must not be weakened.
- Governed mutations remain governed.
- Body edits remain human save or authorized edit paths.
- Source Understanding outputs remain non-authoritative until promoted through a governed path.
- Memory/context may support awareness and proposals but must not authorize mutation.
- BuilderOps remains build-plane/operator support, not product/runtime truth.
- Proportional governance is a future design question, not solved by this package.

## Draft classification before Fable

This is a working classification for Fable validation, not a final scope decision.

| Capability | Pre-Fable v1 posture | Reason |
| --- | --- | --- |
| System Entry Point | Core | The shell and child surfaces are the front door; parent closure and residual repair gate release. |
| Companion UI shell/routes | Core | Operator use must not depend on dead affordances, dev-only routes, or hidden API paths. |
| Health/status/config profile | Core | v1 needs one operator-facing readiness matrix. |
| Orientation | Core | It is the read-only re-entry and situational frame. |
| Vault Browser | Core | It is the primary artifact inspection surface. |
| Panel Confirm | Core | It is the governed mutation authority path for Panel-origin proposals. |
| Receipts History | Core | It is the operator-visible accountability surface; it must remain read-only projection. |
| Capture | Core-candidate | Errata confirms governed API plus UI; final v1 decision is whether quick intake is mandatory. |
| Memory Review | Optional or core-candidate | Errata confirms API plus drawer; persistence/restart/recall gate core status. |
| Resurfacing | Optional/core-adjacent | Useful for orientation, but no push/urgency semantics. Needs explicit handoff posture. |
| TTS/read-back | Optional | Local-first readiness and voice acceptance are still open; useful but may not gate v1. |
| Source Understanding P0 | Optional | API-only/proposal path remains useful but should not block v1 front-door integration. |
| Canvas/Chat co-authoring | Experimental unless promoted | Flag-gated, provider-dependent, process-memory-backed; include only after explicit v1 decision. |
| Chat -> Panel handoff | Experimental unless promoted | Valuable but depends on Canvas and durable proposal/route parity decisions. |
| BuilderOps projections | Optional operator support | Non-authoritative build-plane support; do not promote into product truth. |

## Files in this package

- `FABLE_HANDOFF_PROMPT.md` - paste-ready Fable prompt and input instructions.
- `PARENT_EPIC_DRAFT.md` - pre-Fable parent issue body plus dependency-ordered child issue table.
- `CODEX_DELEGATION_QUEUE.md` - bounded tasks that can be delegated to Codex before or after the Fable pass.

## Recommended next sequence

1. Use this package as the pre-Fable draft.
2. Give Fable the evidence pack, errata, selected SoT excerpts, and `FABLE_HANDOFF_PROMPT.md`.
3. Ask Fable to validate scope, ordering, release gates, and child issue decomposition.
4. Let Codex convert the accepted Fable output into final spec-dir files and GitHub issues.
5. Human decides the final v1 scope: core, optional, experimental, out of scope.
