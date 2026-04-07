---
name: publish-pr
description: "Create or update the implementation, docs, or governance PR after local changes are ready."
---

# Publish PR

Use this skill when local work is complete enough to publish as a branch and pull request.

Goal:
turn validated local changes into a truthful branch, commit, pushed head, and PR artifact without mixing publication with implementation logic.

## Canonical workflow position

`Docs -> Issue -> Project -> Issue maintenance -> Agent -> Publish PR -> PR integration -> CI -> Verification -> Project/doc closure -> Owner Doc`

## Entry conditions

- Local changes are already implemented.
- Focused validation has already been run and captured.
- The correct lane is already known:
  - implementation
  - docs authoring
  - governance

## Responsibilities

- create or switch to the correct branch
- stage only the intended files
- create an intentional commit
- push the branch
- open or update the PR
- apply the correct PR template lane and linked-Issue metadata

## Core rules

- Do not expand implementation scope during publication.
- Do not publish unrelated local changes.
- For implementation lane PRs, the body must include `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- For docs-authoring or governance lane PRs, leave the linked Issue blank unless a governing Issue actually exists.
- Default to opening a draft PR unless the work is explicitly ready for review handoff.
- Publication does not move work to `Done`.

## Recommended publication sequence

1. Confirm the file set belongs to a single lane and single bounded change.
2. Create or switch to a dedicated branch.
3. Stage only the intended files.
4. Write a commit message that matches the bounded outcome.
5. Push the branch.
6. Open or update the PR with truthful lane classification.
7. Hand off to `.codex/skills/pr-integration/SKILL.md`.

## PR body requirements

Implementation lane:

- include `Fixes #<id>`
- summarize the bounded change
- state focused validation that actually ran

Docs authoring lane:

- mark `Docs authoring lane`
- confirm the change stays within approved docs surfaces

Governance lane:

- mark `Governance lane`
- confirm the change stays within approved governance surfaces

## Output format

1. Publication Inputs
2. Branch and Commit Created
3. PR Created or Updated
4. Handoff Target
