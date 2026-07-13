---
name: start-model-inquiry
description: "Run a durable pre-ticket Fable and GPT/Codex model inquiry on the configured remote host through its subscription-authenticated launcher when a development question needs independent model review before ticket creation."
---

# Start Model Inquiry

Use this Builder System skill when the operator asks to investigate one concrete development
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

4. After acquiring the lock, always delete the temporary question file locally and release the
   remote staging path after the command returns, including on failure:

   ```bash
   ssh -T Tailscale_macmini 'rm -f /tmp/model-inquiry-question.md; rmdir /tmp/yggdrasil-model-inquiry.lock'
   ```

   Do not delete durable inquiry artifacts. If release fails, report the error; do not start
   another inquiry.
5. Require the launcher to return one non-empty JSON response on stdout. Report its
   `inquiry_id`, `final_state`, `terminal_receipt_id`, and `human_readable_report` exactly as
   returned.

The configured remote host owns the existing Claude and Codex subscription sessions, BuilderOps configuration,
and durable inquiry artifacts. `Tailscale_macmini` is an operator-configured SSH host alias, and
the remote launcher is host-specific operator configuration outside Git.

## Failure Handling

- If `scp` or SSH fails, report the command's error text and stop.
- Treat exit code zero with empty stdout, malformed JSON, or any missing required response field as
  a launcher failure. Report the observed output and stop.
- Do not re-run the inquiry to recover a missing response. It may already have durable artifacts on
  the configured remote host.
- Do not overlap invocations that use the fixed remote question path; acquire and release its
  exclusive remote lock around each launch.
- Do not inspect or recover an inquiry from the vault as a substitute for the launcher's response.
- Do not substitute an in-chat Fable/GPT exchange or silently use one model for both roles.

## Boundaries

- Do not run local BuilderOps, Python, Codex, or Claude commands for this inquiry.
- Do not install dependencies, run vault-init, configure adapters, or use API keys.
- Do not create a GitHub Issue; use the separate promotion path after a ready receipt exists.
- Do not automate another desktop app or copy turns between apps.
- Do not write inquiry artifacts to Companion UI or a human knowledge vault.
- Do not print subscription, adapter, or credential configuration while diagnosing a failure.
