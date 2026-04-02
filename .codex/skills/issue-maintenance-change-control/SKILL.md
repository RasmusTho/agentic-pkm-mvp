---
name: issue-maintenance-change-control
description: "Perform Issue maintenance for high-risk or cross-boundary changes (especially Core Runtime <-> Agentic Lab moves) by enforcing the change-control contract and producing a corrected, executable GitHub Issue."
---

# Issue Maintenance: Change Control

Use this skill when a request touches:

- Core Runtime <-> Agentic Lab boundary moves
- operator-facing defaults, safety posture, or contract surfaces
- other changes that must not proceed without an explicit, verified task contract

Goal: produce a truthful GitHub Issue contract (and Project state) that can be safely picked up by `issue-to-code`.

## Authority and entry points

- Read `AGENTS.md` first (repo builder-agent policy).
- For boundary moves, treat `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md` as the governing change-control contract.
- Use `docs/DOCS_INDEX.md` to find owner docs for any affected surfaces.
- If the request is "maintenance run on everything not done" or similar, default to open issues in the repo and do not touch Project state unless explicitly requested.

## Change-control checklist (Core Runtime <-> Agentic Lab)

Before coding, ensure the Issue explicitly states:

- Direction: `Agentic Lab -> Core Runtime` or `Core Runtime -> Agentic Lab`
- Exact module(s)/paths being moved (file paths or module area names)
- Default posture impact (defaults unchanged vs changed; flags/profiles required)
- Operator-facing contract impact (startup flows, settings, panel actions, event/outbox, knowledge boundary)
- Verification anchors: which SoT docs are being treated as authoritative for this change
- Test plan: what regression/boundary tests will prove no silent default flips

If any of the above is ambiguous, do not code. Keep the Issue `agent:needs-human`.

## Issue maintenance workflow

1. Identify the governing doc(s) and contract(s).
2. Find the existing Issue(s) (search by keywords and source anchors); avoid duplicates.
3. If an Issue exists, edit it to match the required contract shape exactly.
4. If no Issue exists, create one using the required contract shape.
5. Ensure labels and Project state are truthful:
   - `agent:ready` only when the change is bounded, testable, unblocked, and safe for agent execution.
   - Otherwise use `agent:needs-human` or `agent:blocked`, and keep Project Status at `Backlog`.

## Required Issue contract shape

Issue body must contain exactly these sections:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`

Allowed labels only:

- `type:task`
- `type:bug`
- `type:refactor`
- `prio:high`
- `prio:med`
- `prio:low`
- `agent:ready`
- `agent:blocked`
- `agent:needs-human`

## Output expectations

- A corrected/created Issue that a builder can execute.
- A short receipt: Issue number, labels, and Project Status.

## Fast maintenance run (open issues)

Use this when the user asks for a maintenance run across everything not done.

1. Resolve repo:
   - If repo not given, ask for `owner/repo`.
   - If user says they are the owner, resolve the username via GitHub app `list_installed_accounts` and use that as owner.
2. List open issues:
   - Prefer GitHub app for structured data when possible.
   - For bulk edits, use `gh issue list --state open --json number,title,labels,body` for full bodies.
3. For each open issue:
   - If body already matches the contract shape exactly, do not rewrite it.
   - If contract shape is missing or malformed, edit the issue to match the required sections.
   - Set labels:
     - Add `agent:ready` only if Scope/Constraints/Acceptance Criteria are concrete and no ambiguity remains.
     - Keep or set `agent:needs-human` for boundary moves without explicit direction or module paths.
     - Keep or set `agent:blocked` when external dependencies are stated.
4. Dedupe:
   - If duplicate issues have the same scope/contract, leave a comment pointing to the canonical issue and close the duplicate.
5. Do not change GitHub Project Status unless explicitly asked.
6. Output a receipt listing edited issues, labels changed, and any closures.
