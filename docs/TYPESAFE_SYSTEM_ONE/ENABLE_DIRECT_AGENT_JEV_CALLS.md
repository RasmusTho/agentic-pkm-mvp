---
name: Enable direct Jev calls for Codex and Claude
description: Add a local one-shot typed Jev command and installable agent skill without exposing the API key to agent output or runtime bindings.
task_id: TSO-06
github_issue: 5778
source_anchor: docs/TYPESAFE_SYSTEM_ONE/README.md :: Data and Credential Boundary
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: []
depends_on: []
can_parallelize_with: [DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md, ADD_TYPESAFE_TO_MAC_EXECUTOR.md, MIGRATE_PRODUCT_INTENT_CLASSIFIER.md, MIGRATE_BUILDER_CKM_ASSOCIATION.md]
---

# Enable Direct Agent Jev Calls

## State

Target-state task. User authorized direct one-shot Jev calls from Codex and Claude on the local development host on 2026-10-04. Product and Builder runtime credential bindings remain separate.

## Purpose

Let Codex and Claude request bounded typed Jev judgments during development through one local command. Keep the API key inside the command process and leave coding-agent models and Product/Builder runtime routes unchanged.

## What This Task Does

- Add a standard-library command that accepts bounded JSON on stdin, obtains `typesafe.api-key` by invoking the existing `ygg-secret` helper internally, and sends one request to the fixed TypeSafe System One endpoint using `jev-latest`.
- Validate the request size and typed question shapes before dispatch; validate that the response has exactly one matching typed answer per question.
- Require score rubrics to be ordered, unique, non-empty string labels and require the provider legend to match that rubric exactly. Bound secret-helper output to a single small key value and discard helper diagnostics.
- Return only validated answer JSON and non-secret usage metadata. The output reports the fixed requested model alias and never forwards provider-controlled model metadata. Never print or persist the API key, authorization header, request state, or raw provider error.
- Do not retry, fall back, or replay after timeout, process exit, or another ambiguous send outcome; if no validated result returns after dispatch, the outcome is indeterminate.
- Install one shared executable at `~/.local/bin/jev-direct` and copy the `jev-direct` skill into both `~/.codex/skills/jev-direct/` and `~/.claude/skills/jev-direct/` for the current user on the local development host. No VM install or remote configuration.
- Keep API-key resolution separate from the MARR runtime host-secret contract. Do not change BWS projects, machine accounts, reader scope, or key provisioning.

## Acceptance Criteria

- [ ] The CLI makes exactly one request to the fixed TypeSafe endpoint, validates matching typed answers including the ordered score legend, and returns no credential or raw provider error. Verify: `tests/builderops/test_typesafe_direct_jev.py::test_cli_makes_one_validated_request_without_emitting_credential`; `tests/builderops/test_typesafe_direct_jev.py::test_response_validator_rejects_mismatched_score_legend`.
- [ ] Invalid, oversized, missing-key, and ambiguous requests fail closed without retry or provider fallback. Verify: `tests/builderops/test_typesafe_direct_jev.py::test_invalid_missing_and_ambiguous_requests_are_terminal`.
- [ ] Secret-helper output is bounded and diagnostics are discarded. Verify: `tests/builderops/test_typesafe_direct_jev.py::test_secret_helper_output_is_bounded`.
- [ ] The installer places one shared command in the user's local bin and copies the skill into both Codex and Claude user-level skill directories; repeated installs are idempotent. Verify: `tests/builderops/test_install_typesafe_direct_agent.py::test_installs_command_and_skill_for_both_agents`.
- [ ] Direct development calls are documented separately from runtime routing; no API key is placed in agent settings, environment, arguments, files, logs, or receipts. Verify: doc writeback at `docs/TYPESAFE_SYSTEM_ONE/README.md :: Data and Credential Boundary`.

## How to Verify (Pre-Merge)

- `pytest -q tests/builderops/test_typesafe_direct_jev.py tests/builderops/test_install_typesafe_direct_agent.py`
- `python3 scripts/lint_skills_consistency.py`
- `git diff --check`

## Out of Scope

- Product or Builder runtime routes, MARR credential bindings, VM installation, BWS project/account or reader changes, key provisioning/rotation, TypeSafe plan changes, provider retries, generic chat/completion, or live API calls in tests/CI.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/TYPESAFE_SYSTEM_ONE/DEFINE_TYPESAFE_CREDENTIAL_BINDINGS.md`
- `docs/CLOUD_SECRET_PROVISIONING/README.md`
- `docs/LOCAL_SECRET_PROVISIONING/README.md`

Parent: #5764
