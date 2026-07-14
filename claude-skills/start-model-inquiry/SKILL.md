---
name: start-model-inquiry
description: Run a durable pre-ticket Fable and GPT/Codex model inquiry on the configured remote host through its subscription-authenticated launcher when a development question needs independent model review before ticket creation.
---

# Start Model Inquiry

Use this Builder System skill only when the operator asks to investigate one concrete development
question before issue creation. Run the durable artifact-first workflow on the configured remote host;
do not conduct the inquiry in chat history or in the local workspace.

## Launch

Run this fixed-path protocol as a single-flight operation. Before staging a question, acquire the
exclusive remote lock exactly once:

   ```bash
   ssh -T Tailscale_macmini 'mkdir /tmp/yggdrasil-model-inquiry.lock'
   ```

   If the lock command fails, report its error and stop. Do not remove an existing lock, reuse the
   fixed question path, or substitute a different remote path.

   Immediately register deletion of the local temporary file as an unconditional `finally` action.
   Do not register remote lock release until the launch outcome is known.

1. Write the question verbatim to a local, temporary UTF-8 Markdown file with mode `0600`. Treat
   the question as file content; never interpolate it into a shell command.
2. Copy that file to the configured host:

   ```bash
   scp "$QUESTION_FILE" Tailscale_macmini:/tmp/model-inquiry-question.md
   ```

3. Run exactly:

   ```bash
   ssh -T Tailscale_macmini '$HOME/.local/bin/yggdrasil-model-inquiry --question-file /tmp/model-inquiry-question.md'
   ```

4. Interpret the outcome before releasing the remote staging path:

   - If the local question write or `scp` fails before the launcher starts, run this remote cleanup,
     then report the original failure:

     ```bash
     ssh -T Tailscale_macmini 'rm -f /tmp/model-inquiry-question.md; rmdir /tmp/yggdrasil-model-inquiry.lock'
     ```

   - Release the remote staging path with that same command only after the launcher returns one
     non-empty, valid JSON response containing `inquiry_id`, `final_state`,
     `terminal_receipt_id`, and `human_readable_report`.
   - If the launcher returns a nonzero status, empty stdout, malformed JSON, or a missing response
     field, delete only the local temporary file. Do not release the remote lock or staged question,
     because the remote launcher may still be running.

5. Always delete the local temporary question file through the registered `finally` action. Do not
   delete durable inquiry artifacts. If an allowed remote release fails, report the error and do not
   start another inquiry. Return the verified `inquiry_id`, `final_state`,
   `terminal_receipt_id`, and `human_readable_report` exactly as returned.

The configured remote host owns the existing Claude and Codex subscription sessions, BuilderOps configuration,
and durable inquiry artifacts. `Tailscale_macmini` is an operator-configured SSH host alias, and
the remote launcher is host-specific operator configuration outside Git.

On the configured host, the Fable command may be mediated by a host-local, GUI-session proxy so a
non-interactive SSH launch does not need direct login-keychain access. This is an internal remote-host
authentication path, not a desktop-skill capability: do not configure it, read or copy its credentials
or certificates, invoke it directly, or substitute a different provider path. If that host path is
unavailable, preserve the established ambiguous-launcher failure handling below.

The configured remote launcher owns the high-reasoning profile and extended per-role deadline for
both independent roles. Do not lower or override that profile from the desktop skill, and do not
move its model or adapter configuration into the local workspace.

## Failure Handling

- If `scp` fails after acquiring the lock, run the pre-launch remote cleanup first, then report the
  original failure. Include any cleanup failure without masking the original error.
- Treat every launcher SSH failure as ambiguous. Delete only the local temporary file, report the
  error, and stop.
- Treat exit code zero with empty stdout, malformed JSON, or any missing required response field as
  an ambiguous launcher failure. Delete only the local temporary file, report the observed output,
  and stop.
- Do not release the remote lock after an ambiguous launcher outcome. A later operator can decide
  whether the remote launcher completed; do not make that decision from this skill.
- Do not re-run the inquiry to recover a missing response. It may already have durable artifacts on
  the configured remote host.
- Do not overlap invocations that use the fixed remote question path; acquire and release its
  exclusive remote lock around each launch.
- Do not inspect or recover an inquiry from the vault as a substitute for the launcher's response.
- Do not substitute an in-chat Fable/GPT exchange or silently use one model for both roles.

## Boundaries

- Do not run local BuilderOps, Python, Codex, or Claude commands for this inquiry.
- Do not install dependencies, run vault-init, configure adapters, or use API keys.
- Do not configure, inspect, copy, or print remote-host proxy credentials, certificates, or endpoints.
- Do not create a GitHub Issue; use the separate promotion path after a ready receipt exists.
- Do not automate clicks, keystrokes, windows, tabs, or another desktop app.
- Do not write model transcripts to Companion UI or a human knowledge vault.
- Do not print subscription, adapter, or credential configuration while diagnosing a failure.
