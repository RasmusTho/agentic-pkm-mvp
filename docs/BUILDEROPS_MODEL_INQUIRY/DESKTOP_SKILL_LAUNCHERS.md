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

The configured inquiry host owns the BuilderOps vault, adapters, durable artifacts, and the
host-local values declared by the repository's host-secret contract. Its launcher settings,
credential values, and executable paths are host-specific operator configuration and stay outside
Git. The launcher invokes `app.ops.host_secret_bootstrap` for the `builderops-model-inquiry`
consumer before Model Inquiry starts; the bootstrap materializes one owner-only runtime file and
removes it after the child terminates. Neither desktop skill rebuilds that environment, configures
providers, handles credential values, or reimplements orchestration in prompt prose.

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

The operator machine needs the `Tailscale_macmini` SSH alias. On the remote host, declared Anthropic
and OpenAI API-key identities resolve through the host-secret bootstrap and Keychain contract; no
headless route uses the legacy GUI-session proxy or an interactive subscription session. (Owner
ruling 2026-07-30: this paragraph describes the delivered provider-API mechanism, not the
operational host state — the declared identifiers are intentionally unprovisioned and the
subscription-backed session remains the sanctioned operational auth; see
`docs/adr/ADR-0064-model-access-substrate.md :: Amendment 2026-07-30 — owner cost ruling on the
model-inquiry path`.) Desktop
skill packages neither provision nor access credential values. If that bootstrap cannot resolve or
validate a declared API credential, the fixed Model Inquiry launcher passes only the logical
credential identifier to the runner. The runner then persists a terminal
`provider_error`/`credential_unavailable` receipt before any adapter can run; no credential value,
provider request, subscription command, or alternate provider participates in that handoff. The
launcher returns that complete receipt JSON with exit status 1. Desktop skills accept only that
exact status together with `final_state=provider_error`, a `credential_unavailable` diagnostic, and
all required receipt fields as a valid terminal failure. The diagnostic has the exact persisted
field set (`adapter_id`, `adapter_failure_class`, `credential_identity_ref`), validates the safe
adapter ID and declared logical-secret grammars, and permits no extra field or adapter exit code.
The exit-1 top-level object likewise uses only the declared desktop-launch schema fields. Only then
do callers release single-flight staging, report the failure, and stop. A failed copy or any other launcher error,
empty stdout, malformed/non-object JSON, or absent/empty response field fails loudly: report the
error and stop. Do not retry, inspect the vault for a substitute response, or fall back to an
in-chat inquiry.

The established host command has one fixed `/tmp/model-inquiry-question.md` input path. Before
copying the question, both packages acquire `/tmp/yggdrasil-model-inquiry.lock` atomically: through
SSH for remote callers and directly only for a proven-local Codex caller. A failed lock acquisition
stops the launch without removing the existing lock. Both routes therefore share one single-flight
boundary and cannot overwrite another inquiry's question.

After lock acquisition, local temporary-file cleanup is a registered `finally` action. The remote
or proven-local staged question and lock are released only when staging failed before the launcher
attempt began, when the launcher returned exit zero with one valid terminal JSON object, or when it
returned exit status 1 with the exact typed `credential_unavailable` terminal JSON contract above.
Any other transport or launcher failure, empty stdout, malformed/non-object JSON, or invalid required
field after launch begins is ambiguous: the launcher may have created durable artifacts, so both
routes leave the shared lock and staged question in place, report the error, and do not retry or
infer completion. A valid terminal response and a pre-launch failure use the same route by which the
lock was acquired for cleanup; cleanup failure is reported without masking the original outcome.
Codex deletes its dynamic caller-temp file and any allowed proven-local fixed staging file through
exact-target `apply_patch` deletion, never a shell `rm -f`; it removes the empty fixed lock directory
only after staging deletion succeeded or the staged path was absent. Launcher status and JSON are
captured and validated before cleanup, so a cleanup failure is reported separately and cannot erase
or reclassify the launcher outcome.

The SSH host must expose the repository-owned fixed launcher and both durable role entrypoints
before its launcher is considered ready. All three are installed and content/lineage-checked with the repository-owned
`scripts/install_model_inquiry_host.py` routine documented in the host agent playbook. This
stabilizes the versioned command boundary across shell and reboot changes without moving provider
credential values into Git. Each installed wrapper enters the same `run_with_host_secrets` boundary
before executing the versioned provider-API adapter; it never launches a subscription CLI. A merely
discoverable stale `yggdrasil-model-inquiry` is rejected.

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
- [x] Both packages reject local BuilderOps setup, provider configuration, credential provisioning, and
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
- provisioning or inspecting declared host-secret values.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `.codex/skills/README.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3292](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3292)
