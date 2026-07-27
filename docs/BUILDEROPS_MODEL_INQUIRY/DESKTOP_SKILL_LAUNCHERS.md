---
name: Desktop Skill Launchers
description: Package thin Codex and Claude desktop launchers that delegate inquiries to the configured host runner.
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
write the question verbatim to a mode-`0600` local Markdown file. Remote callers copy it to
`Tailscale_macmini:/tmp/model-inquiry-question.md`, then run exactly:

```bash
ssh -T Tailscale_macmini '$HOME/.local/bin/yggdrasil-model-inquiry --question-file /tmp/model-inquiry-question.md'
```

The configured inquiry host owns the BuilderOps vault, adapters, durable artifacts, and the existing
Claude and Codex subscription sessions. Its launcher settings, credentials, and executable paths
are host-specific operator configuration and stay outside Git; the portable subscription adapter
profile is versioned with the BuilderOps command. That profile gives both roles `xhigh` reasoning
effort and a bounded extended deadline. Neither skill rebuilds that environment, configures
providers, or reimplements orchestration in prompt prose.

The repo-local Codex skill also supports a caller already running on the configured inquiry host. Before
any connection attempt or lock mutation, it expands the fixed `Tailscale_macmini` alias with
the fixed system `ssh -G`. The effective SSH user must equal the current fixed-system `id -un`, and
the process `$HOME` must byte-match that account's `NFSHomeDirectory` from macOS directory service.
The local route then requires a public key pinned for the effective SSH host identity in one of the
two fixed user `known_hosts` files to exactly match a local public SSH host key under `/etc/ssh/`.
The proof uses fixed system tools, reads no private key, and prints no key material. Missing,
invalid, or non-matching alias, principal, home, or host-key evidence selects the remote route. A
failed SSH, copy, DNS, or alias-resolution attempt never proves local identity. The proven-local
route copies to the same fixed staging file and directly invokes only:

```bash
"$HOME/.local/bin/yggdrasil-model-inquiry" --question-file /tmp/model-inquiry-question.md
```

The operator machine needs the `Tailscale_macmini` SSH alias. The remote host may internally mediate
the Fable command through a GUI-session proxy so the SSH child does not directly depend on
login-keychain access. That authentication path is host-specific operator configuration outside Git;
desktop skill packages neither configure it nor access its credentials, certificates, or endpoint.
A failed copy or launcher command, empty stdout, malformed/non-object JSON, or absent/empty response
field fails loudly: report the error and stop. Do not retry, inspect the vault for a substitute
response, or fall back to an in-chat inquiry.

The established host command has one fixed `/tmp/model-inquiry-question.md` input path. Before
copying the question, both packages acquire `/tmp/yggdrasil-model-inquiry.lock` atomically: through
SSH for remote callers and directly only for a proven-local Codex caller. A failed lock acquisition
stops the launch without removing the existing lock. Both routes therefore share one single-flight
boundary and cannot overwrite another inquiry's question.

After lock acquisition, local temporary-file cleanup is a registered `finally` action. The remote
or proven-local staged question and lock are released only when staging failed before the launcher
attempt began, or when the launcher returned exit zero and exactly one non-empty JSON object with
non-empty string values for `inquiry_id`, `final_state`, `terminal_receipt_id`, and
`human_readable_report`. A transport or launcher failure, empty stdout, malformed/non-object JSON,
or invalid required field after launch begins is ambiguous: the launcher may have created durable
artifacts, so both routes leave the shared lock and staged question in place, report the error, and
do not retry or infer completion. A valid terminal response and a pre-launch failure use the same
route by which the lock was acquired for cleanup; cleanup failure is reported without masking the
original outcome. Codex deletes its dynamic caller-temp file and any allowed proven-local fixed
staging file through exact-target `apply_patch` deletion, never a shell `rm -f`; it removes the
empty fixed lock directory only after staging deletion succeeded or the staged path was absent.
Launcher status and JSON are captured and validated before cleanup, so a cleanup failure is reported
separately and cannot erase or reclassify the launcher outcome.

The SSH host must expose both durable role entrypoints before its launcher is considered ready.
They are installed and checked with the repository-owned
`scripts/install_model_inquiry_host.py` routine documented in the host agent playbook. This
stabilizes the versioned command boundary across shell and reboot changes without moving provider
credentials or subscription configuration into Git. The routine deliberately does not create a
GUI-session proxy or alter authentication; those remain explicit host-operator setup when needed.

## Concretely

```text
$start-model-inquiry Hur bör eventmodellen utformas?
```

## Why This Matters

The desktop apps are ergonomic front doors, not durable state machines or a reliable bridge to each
other.

## Acceptance Criteria

- [x] Both desktop skill packages preserve the exact remote-host bridge command and report its
  inquiry receipt fields. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages reject local BuilderOps setup, provider configuration, API keys, and
  desktop-control automation. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages fail loudly for a copy/SSH failure, empty stdout, malformed JSON, or an absent
  receipt field. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages atomically lock the fixed host question path rather than silently overwriting
  a concurrent inquiry. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages release staging and the lock through the selected route only after a pre-launch
  failure or a verified receipt, preserving both after an ambiguous launcher result. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Codex local cleanup uses policy-compatible exact-target deletion for the caller temp and fixed
  staging file, never a blocked shell `rm -f`, and cannot mask the captured launcher result. Verify:
  `tests/architecture/test_agent_skill_entrypoints.py::test_model_inquiry_local_host_route_is_identity_gated_and_fail_closed`.
- [x] The Codex skill selects its local-host route only after fixed-alias, OS principal/home, and
  pinned-host-key proofs all match, invokes only the fixed host launcher, shares the fixed
  single-flight lock, strictly validates the terminal response, and preserves staging after
  ambiguous outcomes. Verify:
  `tests/architecture/test_agent_skill_entrypoints.py::test_model_inquiry_local_host_route_is_identity_gated_and_fail_closed`.
- [x] A terminal `provider_error` returns one JSON response carrying the established receipt fields
  and only an optional allowlisted diagnostic object. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_local_launcher_emits_terminal_provider_error_json`.

## How to Verify (Pre-Merge)

- `pytest -q tests/architecture/test_agent_skill_entrypoints.py tests/governance/test_start_model_inquiry_skill.py`
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
