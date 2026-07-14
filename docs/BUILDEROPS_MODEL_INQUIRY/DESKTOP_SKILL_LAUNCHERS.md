---
name: Desktop Skill Launchers
description: Package thin Codex and Claude desktop launchers that delegate inquiries to the configured remote-host runner.
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
orchestrator inside either chat history or configuring providers in the local workspace.

## What This Task Does

Create a repo-local `start-model-inquiry` skill and a portable Claude custom-skill package. Both
write the question verbatim to a mode-`0600` local Markdown file, copy it to
`Tailscale_macmini:/tmp/model-inquiry-question.md`, then run exactly:

```bash
ssh -T Tailscale_macmini '$HOME/.local/bin/yggdrasil-model-inquiry --question-file /tmp/model-inquiry-question.md'
```

The configured remote host owns the BuilderOps vault, adapters, durable artifacts, and the existing
Claude and Codex subscription sessions. Its launcher settings, credentials, and executable paths
are host-specific operator configuration and stay outside Git; the portable subscription adapter
profile is versioned with the BuilderOps command. That profile gives both roles `xhigh` reasoning
effort and a bounded extended deadline. Neither skill rebuilds that environment, configures
providers, or reimplements orchestration in prompt prose.

The operator machine needs the `Tailscale_macmini` SSH alias. The remote host may internally mediate
the Fable command through a GUI-session proxy so the SSH child does not directly depend on login-keychain
access. That authentication path is host-specific operator configuration outside Git; desktop skill
packages neither configure it nor access its credentials, certificates, or endpoint. A failed copy or SSH command, empty
stdout, malformed JSON, or absent response field fails loudly: report the error and stop. Do not
retry, inspect the vault for a substitute response, or fall back to an in-chat inquiry.

The established remote command has one fixed `/tmp/model-inquiry-question.md` input path. Before
copying the question, both packages acquire the atomic remote lock with
`mkdir /tmp/yggdrasil-model-inquiry.lock`. A failed lock acquisition stops the launch without
removing the existing lock. This prevents one desktop session from overwriting another inquiry's
question while retaining the required fixed copy and launcher commands.

After lock acquisition, local temporary-file cleanup is a registered `finally` action. The remote
question and lock are released only when the copy failed before the launcher began, or when the
launcher returned a valid non-empty JSON receipt with every required field. A transport failure,
empty stdout, malformed JSON, or missing field is ambiguous: the launcher may still run remotely,
so the package leaves the remote lock and staged question in place, reports the error, and does not
retry or infer completion.

## Concretely

```text
$start-model-inquiry Hur bör eventmodellen utformas?
```

## Why This Matters

The desktop apps are ergonomic front doors, not durable state machines or a reliable bridge to each
other.

## Acceptance Criteria

- [x] Both desktop skill packages use the exact remote-host bridge command and report its inquiry
  receipt fields. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages reject local BuilderOps setup, provider configuration, API keys, and
  desktop-control automation. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages fail loudly for a copy/SSH failure, empty stdout, malformed JSON, or an absent
  receipt field. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages atomically lock the fixed remote question path rather than silently overwriting
  a concurrent inquiry. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages release the remote lock only after a pre-launch failure or a verified receipt,
  preserving it after an ambiguous launcher result. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] A terminal `provider_error` returns one JSON response carrying the established receipt fields
  and only an optional allowlisted diagnostic object. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_local_launcher_emits_terminal_provider_error_json`.

## How to Verify (Pre-Merge)

- `pytest -q tests/governance/test_start_model_inquiry_skill.py`
- `python3 scripts/lint_skills_consistency.py`
- `python3 scripts/package_claude_skill.py --output /tmp/start-model-inquiry.zip`

The generated ZIP contains `start-model-inquiry/SKILL.md` at its root and is uploaded manually by
the operator. Generated archives are release artifacts and remain outside Git source control.

## Out of Scope

- automating clicks or keystrokes in the other desktop app;
- storing model transcripts in Companion UI or a human knowledge vault.
- installing Python, BuilderOps, Codex, or Claude on the local machine;
- changing authenticated subscription sessions or local desktop configuration.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `.codex/skills/README.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3292](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3292)
