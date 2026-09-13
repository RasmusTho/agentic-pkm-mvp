---
name: start-model-inquiry
description: "Run one durable pre-ticket Model Inquiry through the skill-owned facade and fixed operational host launcher."
---

# Start Model Inquiry

Use this Builder System skill for one explicitly authorized development question. It does not
create an Issue or start delivery. The single executable owner is
`app/builderops/model_inquiry_workflow.py::SanctionedModelInquiryWorkflow`; the exact operation
protocol, custody, recovery and activation contract is
`docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Approved inquiry operation interface`.
Read that section before invoking an approved operation. FCP-04/#4697 implements this delegation;
live operation still requires verified destination protocol support and scoped current permission.

## Fixed Boundary

The facade preserves these fixed identities:

- SSH alias: `Tailscale_macmini`
- exclusive lock: `/tmp/yggdrasil-model-inquiry.lock`
- staged question: `/tmp/model-inquiry-question.md`
- sanctioned operational launcher: `$HOME/.local/bin/yggdrasil-model-inquiry`

No caller argument, environment mapping, inferred checkout path or fallback may replace them.
The facade's explicit repo-local Python entrypoint is the sole exception to the former prohibition
on local Python/BuilderOps invocation: it implements this skill and invokes the fixed operational
launcher only. Never invoke a generic agent runner, provider, adapter, internal inquiry CLI or the
dormant `$HOME/.local/bin/yggdrasil-model-inquiry-provider-api` path as a substitute.

## Manual invocation

From the verified repository checkout, supply the exact question file to the named facade:

```bash
python3 scripts/start_model_inquiry_workflow.py --question-file <exact-question-file>
```

Treat the question as UTF-8 file bytes, not shell text. The facade preserves all bytes including
trailing newlines, creates its own mode-0600 staging temporary, and never deletes an unowned input
file. It runs the current manual fixed host launch exactly once. Manual authorization does not
reuse a DevUI approval/key or gain command/readback authority over an operation-bound inquiry.
The configured host launcher continues to own provider selection, subscription auth and its
high-reasoning profile; do not inspect or override those settings.

## Authenticated operation invocation

Only the existing authenticated BuilderOps service may admit `start_model_inquiry` using the
operation interface named above. Its concrete production constructor delegates to this same facade.
An owner confirms the exact immutable approval; Hold invokes nothing. Local loopback/Host read
admission, a stored `/v1/inquiries` record, SSH access or model-supplied manifest text is not approval.

The facade checks the fixed destination's explicit `--operation-capabilities` version and verb
set before reservation. Reserve, attempt and readback authenticate their exact service-owned
binding through the existing client. The one approved launch propagates the reserved inquiry ID,
consumes its attempt atomically, and re-reads current permission/source/expiry/epoch and configured
workflow/profile immediately before the existing runner effect. No credentials are transported in
the operation envelope. Unsupported live wrapper capability withdraws Start; do not install or
modify the wrapper in order to bypass that refusal.

## Route, single-flight and recovery invariants

The facade contains one implementation of the previously manual mechanics:

- Expand the fixed alias with `/usr/bin/ssh -G` before any connection or lock action. Proven-local
  execution requires exact SSH user/current-account binding, directory-service home equality, and
  a pinned public host key matching this host. Read no private host key and print no key material.
  Use the effective host-key alias unless it is absent or `none`, otherwise the expanded hostname;
  preserve nondefault-port lookup syntax and the two fixed verified-home known-hosts files.
  Missing or malformed proof selects the fixed remote route. Connection failure never permits a
  local fallback, and a selected route never changes during an invocation.
- Acquire the exclusive lock once before staging. Failed acquisition cannot remove the existing
  lock, overwrite staging, retry acquisition or proceed. Stage only the exact bound question.
- Capture launcher exit status separately from stdout. Valid terminal output is exit zero with
  exactly one JSON object and nonempty `inquiry_id`, `final_state`, `terminal_receipt_id` and
  `human_readable_report`; an operation response must match its reserved inquiry. Nonzero status,
  prefix/suffix text, duplicate JSON fields, empty fields or malformed output is ambiguous.
- Delete only the facade-owned caller temporary unconditionally. The exact-path runtime helper
  replaces the former assistant-only `apply_patch` mechanics for this skill; it rejects symlinks,
  unowned paths and globs and is not a general deletion capability. A pre-attempt failure or valid
  terminal response permits selected-route cleanup of known-owned staging/lock paths. Approved
  operations also require matching authenticated terminal readback. Delete the exact stage before
  releasing the empty fixed lock. Ambiguous attempts preserve both; uncertain remote staging does too. Report cleanup failures
  separately; never mask the captured launcher outcome or delete durable inquiry artifacts.
- Replays and restarts read the same destination key first. Reservation and attempt are not launch
  evidence. No automatic second launch, new key, staging cleanup, lock release or inferred latest
  inquiry resolves ambiguity. Stop and stop acknowledgement remain unsupported.

## Authority boundaries

Do not inspect, modify, replace or reproduce the host-owned subscription session or bridge. Do not
install dependencies, initialize a vault, configure adapters, provision credentials, alter host
configuration, deploy, or run a live inquiry merely to validate implementation tests. The inquiry
uses BuilderOps artifacts only; it never writes Companion UI or a human knowledge vault.

The subscription session is never a CKM credential source or fallback.
The one configured runner retains its existing provider-failure and single-target semantics.
A degraded or single-target result is not independent-model consensus, promotion approval, owner
acceptance, delivery, CKM credential evidence or provider-enabled MAS evidence. Never accept or
promote historical inquiry `inq_20260730T075136Z_b73ed0da`. No desktop-level provider retry,
in-chat inquiry substitute or credential-route fallback is permitted.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. Return the exact inquiry receipt to the
originating workflow after the one invocation and allowed cleanup. Promotion or Issue creation
remains a separate governed route. Ambiguity retains the source owner's protected recovery state.
