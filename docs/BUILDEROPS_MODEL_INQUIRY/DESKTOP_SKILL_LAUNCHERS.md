---
name: Desktop Skill Launchers
description: Package thin Codex and Claude desktop launchers over the common BuilderOps inquiry command.
task_id: BMI-04
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Scope
parent_capability: BuilderOps Model Inquiry
prerequisites: [BMI-02, BMI-03]
depends_on: [PRE_TICKET_INQUIRY_RECORDS.md, MODEL_TURN_ADAPTERS.md]
can_parallelize_with: []
---

# Desktop Skill Launchers

## Purpose

Let an operator begin the same inquiry from Codex Desktop or Claude Desktop without putting the
orchestrator inside either chat history.

## What This Task Does

Create a repo-local `start-model-inquiry` skill and a portable Claude custom-skill package. Both call
the repo-owned `scripts/start_model_inquiry.sh` entrypoint, which resolves the same canonical repo
virtualenv as the BuilderOps CLI wrapper. Its Python launcher validates the shared vault and both
explicit role adapters **before mutation**, calls the repo-supported
`scripts/builderops_cli.sh builderops inquiry start` command, then calls the common `inquiry run`
command. It displays the returned `inquiry_id` and terminal outcome; neither skill reimplements
orchestration in prompt prose.

The portable Claude package is an instruction package, not a host-filesystem bridge. Its execution
environment must already be able to access the repository checkout, shared vault, and configured
adapters. If it cannot, preflight fails loudly. The package never guesses an application-private
path or automates another desktop app.

## Concretely

```text
$start-model-inquiry Hur bör eventmodellen utformas?
```

## Why This Matters

The desktop apps are ergonomic front doors, not durable state machines or a reliable bridge to each
other.

## Acceptance Criteria

- [x] The Codex skill invokes the common BuilderOps inquiry command and reports its inquiry ID.
  Verify: `tests/governance/test_start_model_inquiry_skill.py::test_codex_skill_calls_common_command`.
- [x] The Claude package contains the same launcher contract and no desktop-control automation.
  Verify: `tests/governance/test_start_model_inquiry_skill.py::test_claude_package_uses_common_launcher_contract`.
- [x] Launcher preflight fails loudly when the shared vault or required adapter is unavailable.
  Verify: `tests/governance/test_start_model_inquiry_skill.py::test_skill_preflight_reports_missing_dependencies`.

## How to Verify (Pre-Merge)

- `pytest -q tests/governance/test_start_model_inquiry_skill.py`
- `python3 scripts/lint_skills_consistency.py`
- `python3 scripts/package_claude_skill.py --output /tmp/start-model-inquiry.zip`

The generated ZIP contains `start-model-inquiry/SKILL.md` at its root and is uploaded manually by
the operator. Generated archives are release artifacts and remain outside Git source control.

## Out of Scope

- automating clicks or keystrokes in the other desktop app;
- storing model transcripts in Companion UI or a human knowledge vault.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `.codex/skills/README.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3292](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3292)
