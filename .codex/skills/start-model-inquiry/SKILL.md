---
name: start-model-inquiry
description: "Run a durable pre-ticket Fable and GPT/Codex model inquiry through the configured host-local subscription launcher when a development question needs independent model review before ticket creation."
---

# Start Model Inquiry

Use this Builder System skill when the operator asks to investigate one concrete development
question before issue creation. Run the durable artifact-first workflow on the configured inquiry host;
do not conduct the inquiry in chat history or in the calling workspace.

## Fixed Boundary

The host bridge has four fixed identities:

- SSH alias: `Tailscale_macmini`
- exclusive lock: `/tmp/yggdrasil-model-inquiry.lock`
- staged question: `/tmp/model-inquiry-question.md`
- sanctioned host-local subscription launcher:
  `$HOME/.local/bin/yggdrasil-model-inquiry`

Do not accept an environment variable, caller argument, inferred checkout path, or fallback command
for any of these identities. In particular, do not invoke a checkout-local launcher, provider
command, adapter, Codex, Claude, or BuilderOps directly.

## Route Selection

Select the route before acquiring the lock and before attempting any SSH connection:

1. Expand the fixed alias without connecting:

   ```bash
   /usr/bin/ssh -G Tailscale_macmini
   ```

   Read the first effective `hostname`, `hostkeyalias`, `port`, and `user` values. The expansion
   must succeed, `hostname` and `user` must be non-empty, and `hostname` must not equal the literal
   alias after ASCII case-folding.
2. Bind the local account and home directory to the SSH principal:

   ```bash
   /usr/bin/id -un
   /usr/bin/dscl . -read "/Users/$(/usr/bin/id -un)" NFSHomeDirectory
   ```

   The effective SSH `user` must exactly equal `/usr/bin/id -un`. Parse exactly one non-empty,
   absolute `NFSHomeDirectory` value from the directory-service record, and require the current
   `$HOME` to equal it byte-for-byte. Do not rewrite `$HOME`, accept a different home, or read
   `known_hosts` or a launcher below an unverified home.
3. Prove that the fixed alias identifies this host without attempting a connection. Use the
   effective `hostkeyalias` when it is non-empty and not `none`; otherwise use the effective
   `hostname`. For a non-default port, use the OpenSSH `[host]:port` lookup form. Use
   `/usr/bin/ssh-keygen -F` to inspect only `$HOME/.ssh/known_hosts` and
   `$HOME/.ssh/known_hosts2`. The proof matches only when one pinned public key's algorithm and
   base64 key blob exactly equal one public key in `/etc/ssh/ssh_host_*_key.pub`. Never read a
   private host-key file, and never print public-key material while checking.
4. Use the **proven-local route** only when alias expansion, principal binding, home binding, and
   the pinned host-key proof all succeed. Otherwise use the **remote route**. An unavailable,
   failed, malformed, incomplete, or non-matching check is not permission to weaken another check.

This is an evidence check, not a connectivity fallback. Never infer that the caller is local because
SSH, `scp`, DNS, or the `Tailscale_macmini` alias failed to connect or resolve. Once selected, do not
switch routes during the invocation.

## Single-Flight Launch

Run exactly one route as a single-flight operation.

1. Acquire the exclusive lock exactly once.

   Remote route:

   ```bash
   ssh -T Tailscale_macmini 'mkdir /tmp/yggdrasil-model-inquiry.lock'
   ```

   Proven-local route:

   ```bash
   /bin/mkdir /tmp/yggdrasil-model-inquiry.lock
   ```

   If lock acquisition fails, report the error and stop. Do not remove an existing lock or staged
   question, retry acquisition, or reuse the fixed question path.
2. Immediately register deletion of the calling process's temporary question file as an
   unconditional `finally` action. Record its resolved absolute path. The action must perform a
   read-only exact-path existence check and, when present, delete that one recorded path with the
   `apply_patch` tool:

   ```text
   *** Begin Patch
   *** Delete File: <absolute QUESTION_FILE>
   *** End Patch
   ```

   Do not use `rm`, `unlink`, a glob, or a shell cleanup wrapper for this local temporary file. Do
   not register staging or lock release as unconditional cleanup.

   Do not register remote lock release until the launch outcome is known.
3. Write the question verbatim to a temporary UTF-8 Markdown file with mode `0600`. Treat the
   question as file content; never interpolate it into a shell command.
4. Stage the question.

   Remote route:

   ```bash
   scp "$QUESTION_FILE" Tailscale_macmini:/tmp/model-inquiry-question.md
   ```

   Proven-local route:

   ```bash
   /usr/bin/install -m 0600 "$QUESTION_FILE" /tmp/model-inquiry-question.md
   ```

5. Start the fixed host launcher exactly once.

   Remote route:

   ```bash
   ssh -T Tailscale_macmini '$HOME/.local/bin/yggdrasil-model-inquiry --question-file /tmp/model-inquiry-question.md'
   ```

   Proven-local route:

   ```bash
   "$HOME/.local/bin/yggdrasil-model-inquiry" --question-file /tmp/model-inquiry-question.md
   ```

   Capture the launcher's exit status and stdout separately. Do not pipe the launcher through
   another command or let a formatter replace its exit status.
6. Validate the response before releasing staging. A valid terminal response requires exit status
   zero and non-empty stdout whose entire contents parse as exactly one JSON object with non-empty
   string values for `inquiry_id`, `final_state`, `terminal_receipt_id`, and
   `human_readable_report`. Any nonzero status, non-JSON prefix or suffix, array or scalar, empty
   required value, or missing required field is invalid and therefore ambiguous.

   This launcher response is a durable Model Inquiry artifact only. It does not satisfy the
   withdrawn `model_access_substrate.provider_enabled_noninteractive_inquiry.v1` or
   `legacy_bridge_retirement.v1` gates, does not prove metered-provider access, and is never CKM
   credential evidence. Never accept or promote historical inquiry
   `inq_20260730T075136Z_b73ed0da`.

## Cleanup Matrix

The launcher attempt begins at step 5. Apply exactly one row:

| Outcome | Remote route | Proven-local route |
| --- | --- | --- |
| Failure after lock acquisition but before step 5 starts | Run the fixed remote release command below; report the original failure and any cleanup failure. | Run the fixed proven-local release procedure below; report the original failure and any cleanup failure. |
| Valid exit-zero terminal response | Preserve the response, then run the fixed remote release command. | Preserve the response, then run the fixed proven-local release procedure. |
| Ambiguous launcher outcome after step 5 starts | Preserve the remote staging file and lock. | Preserve the local staging file and lock. |

Fixed remote release:

```bash
ssh -T Tailscale_macmini 'rm -f /tmp/model-inquiry-question.md; rmdir /tmp/yggdrasil-model-inquiry.lock'
```

Fixed proven-local release procedure:

1. Perform a read-only exact-path check for `/tmp/model-inquiry-question.md`.
2. If it exists, delete exactly that file with:

```text
*** Begin Patch
*** Delete File: /tmp/model-inquiry-question.md
*** End Patch
```

3. Only when the staged path was absent or that exact deletion succeeded, run:

```bash
/bin/rmdir /tmp/yggdrasil-model-inquiry.lock
```

If exact staging deletion fails, do not remove the lock. Report the cleanup failure and do not start
another inquiry.

Always delete only the calling process's temporary question file through the registered `finally`
action. Capture and validate the launcher result before any cleanup, and report cleanup outcomes
separately: a cleanup failure must not replace or reclassify the captured launcher outcome. If an
allowed staging/lock release fails, report it and do not start another inquiry. Never delete durable
inquiry artifacts.

The configured inquiry host owns BuilderOps configuration, durable inquiry artifacts, and the
sanctioned subscription session. `Tailscale_macmini` is an operator-configured SSH host alias. The
launcher, subscription bridge, and pinned host identity are host-specific operator configuration
outside Git. This skill invokes that fixed launcher exactly once but must never inspect, modify,
replace, or reproduce its subscription session or bridge.

The configured host launcher owns the high-reasoning profile and extended per-role deadline for
both independent roles. Do not lower or override that profile from the desktop skill, and do not
move its model or adapter configuration into the local workspace.

## Failure Handling

The desktop skill never retries a provider or starts a second inquiry. Within the one fixed launcher
invocation, the sanctioned operational runner may try the other already-configured subscription
adapter after an eligible, durably receipted candidate failure. Its two logical lanes carry
complementary question-focused roles. If one effective target fills both lanes, the valid terminal
result is `degraded_consensus`; report it as degraded and never treat it as independent-model or
promotion evidence.

- Treat every launcher SSH failure and every proven-local launcher failure after step 5 starts as
  ambiguous.
- Treat every nonzero launcher status, empty stdout, malformed JSON, non-object JSON, or invalid
  required response field as an ambiguous launcher failure.
- On an ambiguous outcome, delete only the calling process's temporary question file. Do not
  release either route's lock or staged question. A later operator can decide whether the host
  launcher completed; do not make that decision from this skill.
- Do not release the remote lock after an ambiguous launcher outcome.
- Do not re-run the inquiry to recover a missing response. It may already have durable artifacts on
  the configured host.
- Do not retry a provider from the desktop skill, inspect credentials, or route around the
  sanctioned host launcher. Its bounded internal candidate chain is the only fallback authority.
- Do not overlap invocations that use the fixed question path; both routes use the same exclusive
  lock.
- Do not inspect or recover an inquiry from the vault as a substitute for the launcher's response.
- Do not substitute an in-chat Fable/GPT exchange or silently use one model for both roles.

## Boundaries

- Do not run local BuilderOps, Python, Codex, or Claude commands directly for this inquiry, and do
  not invoke providers or adapters directly. The proven-local route may invoke only the fixed
  sanctioned host-local subscription launcher.
- Do not install dependencies, run vault-init, configure adapters, or provision API keys.
- Do not configure, inspect, copy, or print subscription-session material, host-secret values,
  provider credentials, or provider endpoints.
- Do not invoke `$HOME/.local/bin/yggdrasil-model-inquiry-provider-api`; it is a distinct dormant
  mechanism and not the operational Model Inquiry route.
- Do not create a GitHub Issue; use the separate promotion path after a ready receipt exists.
- Do not automate another desktop app or copy turns between apps.
- Do not write inquiry artifacts to Companion UI or a human knowledge vault.
- Do not print adapter or credential configuration while diagnosing a failure.
