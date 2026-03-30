State: Development reference. Not an auto-loaded instruction file.
# Exact Governance Doc Patches

These patches are ready to apply to the named files. They were captured here because the available GitHub connector in this run could create new files but did not expose a direct update path for existing files.

## Patch 1 — `docs/ARCHITECTURE.md`

Append:

```md
## GitHub Delivery Control Plane (development governance)

This section governs development-time delivery control in GitHub. It does not define runtime/system-agent behavior.
Runtime/system semantics remain owned by the existing architecture, agent, concept, and settings documents.

Development control model:

- Docs define intent, contracts, and owner boundaries.
- GitHub Issues are the canonical task contract for implementation work.
- GitHub Project v2 is the delivery state machine.
- Coding agents are the execution layer that implement bounded Issues.
- Pull requests are the implementation artifact.
- CI/test workflows are the validation loop.
- Outcomes feed back into docs, Issues, and Project state.

Canonical delivery sequence:

`Docs -> Issue -> Project -> Agent -> PR -> CI -> Feedback`

Required Issue contract:

- `Context`
- `Scope`
- `Constraints`
- `Acceptance Criteria`
- `Out of Scope`

Required label ontology:

- type: `type:task`, `type:bug`, `type:refactor`
- priority: `prio:high`, `prio:med`, `prio:low`
- agent state: `agent:ready`, `agent:blocked`, `agent:needs-human`

Required Project state machine:

- `Backlog -> Ready -> In Progress -> Review -> Done`

Optional Project field:

- `Agent State`: `Idle`, `Running`, `Waiting`

Guardrails for builder agents:

- Agents only pick Issues labeled `agent:ready`.
- Agents must stay within the linked Issue scope.
- Agents must respect the linked Issue constraints.
- Agents must satisfy the linked Issue acceptance criteria before claiming completion.
- No architecture-breaking or boundary-breaking work proceeds without an Issue.
- No free-form tasks are canonical; GitHub Issues are the source of truth for delivery tasks.

This GitHub control plane is a development governance layer around the repo-first/docs-as-code workflow.
It must not be confused with the runtime agent architecture described elsewhere in this document.
```

## Patch 2 — `docs/ROADMAP.md`

Append:

```md
## Delivery Control Plane (GitHub)

The repo now adopts a GitHub-based delivery control plane for implementation work:

- Docs/ADRs/owner docs define intent and architecture.
- GitHub Issues are the canonical task contract.
- GitHub Project v2 is the delivery state machine.
- Coding agents execute only bounded Issues.
- PR + CI are the validation loop.

Delivery lifecycle:

`Backlog -> Ready -> agent:ready -> In Progress -> Review -> Done`

Builder-agent rule:

- agents only pick Issues labeled `agent:ready`
- agents must follow `Constraints`
- agents must satisfy `Acceptance Criteria`
- PRs must link the governing Issue

Platform-state note:

- repo-side enforcement lives in `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`, `.github/workflows/issue-pr-governance.yml`, and `.github/github-governance.yml`
- GitHub labels, Project fields/views, and Project automation must match that contract
```

## Patch 3 — `docs/STATUS.md`

Append:

```md
## GitHub delivery governance snapshot

Repo-side governance added:
- task Issue form
- blank Issue disablement
- PR template requiring Issue linkage
- governance workflow checking Issue shape and PR Issue linkage
- machine-readable GitHub governance contract in `.github/github-governance.yml`

Observed before this change:
- existing Issues were present but not normalized to a strict machine-readable task contract
- recent PR practice showed inconsistent Issue-linking and branch naming conventions
- no dedicated repo workflow enforced the Issue/PR contract

Known remaining gap:
- the available GitHub connector for this change did not expose label/Project-v2 write operations
- therefore labels, Project fields/views, and Project automation still require platform-side application to match the repo contract

Target delivery model:
- Issues = canonical task contract
- Project = state machine
- agents = execution layer
- PR = implementation artifact
- CI = validation gate
```

## Patch 4 — `AGENTS.md`

Append:

```md
## GitHub delivery governance

For implementation work, GitHub Issues are the canonical task contract.

Builder-agent rules:

- Only pick work from a GitHub Issue labeled `agent:ready`.
- Read the full Issue before editing.
- Treat `Context`, `Scope`, `Constraints`, `Acceptance Criteria`, and `Out of Scope` as binding.
- Link the PR back to the governing Issue using `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- Do not treat chat-only requests as canonical implementation tasks when an Issue is expected.
- Do not expand scope beyond the Issue without updating the task contract first.
```

## Patch 5 — `docs/development/DEV_WORKFLOW.md`

Append:

```md
## GitHub issue-first execution loop

For implementation work, the delivery loop is:

1. Docs/owner docs define the intended contract.
2. GitHub Issue defines the bounded task contract.
3. GitHub Project tracks lifecycle state.
4. Builder agent implements the Issue in a PR.
5. CI/test workflows validate the change.
6. Human review closes the loop and updates docs/status/roadmap as needed.

Execution rule:

- do not start non-trivial implementation without a governing Issue
- prefer Issues labeled `agent:ready`
- use the linked Issue as the bounded source of truth for scope and acceptance
```
