---
name: mimer-governed-boundary
description: "External app-agent client skill (product lane; NOT for dev/build work in this repo): shared contract for the mimer-* family — the three hard invariants, exclusion list, provenance block, and error-surfacing duties every mimer-* skill inherits. Loaded by reference from the other mimer-* skills; never invoked directly by a human request."
---

# Mimer Governed Boundary

Product-lane client skill; not a Builder System workflow — for dev work in this repo use the
builder skills per `.codex/skills/README.md`.

This is the `_shared/`-analogue for the Mimer app-agent skill family (`mimer-capture`,
`mimer-retrieve`, `mimer-ask`, `mimer-vault-workspace`). It carries no operations of its own — the
other four skills load it by reference instead of restating its contents. No human request should
route here directly; if one seems to, it belongs to one of the other four.

Full authority: `docs/contracts/MIMER_CLIENT_CONTRACT.md` ("the contract" below), enacted by
`docs/adr/ADR-0056-mimer-client-contract-and-transports.md`. This file is a client-side operating
summary, not a replacement — read the contract itself before acting on anything unclear here.

## The three hard invariants (contract §3)

Every mimer-* skill, on both transports (governed HTTP API and direct filesystem):

1. **Never semantic authority.** Never decide what a vault note means, never own a Core-6 field,
   never treat the client's own output as human-canonical. Output enters at the zone posture of
   where it lands; promotion to human-canonical knowledge is a human act.
2. **Every durable mutation stays inside a named transport.** Exactly two exist: the governed API
   (`POST /api/companion/capture`) and the direct-filesystem path. No bespoke side channels, no
   invented write mechanisms, no local write queue that replays into the vault without the human.
3. **Never a hidden source of truth.** No client-local store may hold meaning the vault + companion
   set cannot rebuild. Client caches are opaque, rebuildable, and never written back as authority.

## Never-degrade rule

A blocked or failed governed API write must **never** be re-routed as a direct filesystem write.
That is a governance bypass, not a degradation (contract §3, §6 failure table). If
`POST /api/companion/capture` returns a WriteGuard-blocked, vault-selection-required, or any other
blocked/degraded response, surface it to the human — never fall back to writing the vault directly
to "get the capture done anyway."

## Exclusion list — never direct-write (contract §5)

| Surface | Why |
| --- | --- |
| The capture inbox note (the vault's `inbox.md` or its configured override) | Actively-appended governed target; a rewrite races the governed append and last-write-wins can silently drop a capture. Intake goes through the capture skill's governed call only. |
| Companion notes (the vault's `⚙️ System/companions/` tree, and its legacy location) | KnowledgePort-only, system-owned. |
| System-plane settings/bootstrap notes and other system-owned paths | Runtime-owned; a direct edit forks runtime state. |
| The `_heimdal` control tree | Bifrost's/the runtime's control seam; app agents have no role there. |
| The Sources zone (the settings-resolved default is `Sources/`) | Reserved for Heimdal-side sensor/acquisition writers. It is not an app-agent workspace or a capture-endpoint target. |
| iCloud "conflicted copy" artifacts | Never create, never silently resolve; surface to the human. |

## Provenance frontmatter (contract §5)

Every file an app agent **creates** in the vault MUST carry this block; every substantive edit to
an existing note SHOULD append to it:

```yaml
agent_provenance:
  author: <client-id>        # e.g. claude-app, codex-app
  model: <model-id>          # where applicable
  written_at: <utc-iso>
  origin: direct-fs
  trace: <trace-id or session ref, if any>
```

## Error-surfacing duties (verbatim, never absorb)

Every named error or degraded state in the contract (§4.1, §6) must reach the human verbatim, not
be paraphrased into a generic failure or silently retried:

- WriteGuard-blocked (409) — reason included, nothing written. Surface the reason as given.
- Vault-selection-required (a structured state, matched on the response's `state` field, not an
  `error` field) — no active vault; the human selects one. Never guess a vault.
- Not-acknowledged (500) — the write may have landed; its receipt could not be persisted. Never
  blind-retry; verify by reading the target first.
- Inbox-convention-unresolved (409), schema errors (422) — surface and let the human decide next.
- Retrieval/ask failures propagate; never answer from the client's own knowledge while implying
  vault grounding it doesn't have.

## Health duties before writing (contract §7)

- Check `GET /healthz` (or `/api/status`) before entering any write flow — API or direct-FS.
  If the runtime is unhealthy or unreachable, degrade per the contract's §6 table (blocked
  governed write → surface the reason; API unreachable → read-only over declared filesystem
  roots) and say so.
- Send an `X-Trace-Id` header on every API call and log it client-side, so a capture, its
  receipt, and its outbox event stay joinable across the seam.
- Use `GET /version` to record which runtime build served a session when reporting anomalies.

## LAN/loopback-only posture (contract §4)

A client under this contract MUST refuse to operate against a Mimer host that is not loopback,
LAN, or tailnet. Per-agent identity/keys is named follow-on work (contract §9 F2), not a v1
requirement — do not invent a workaround for it.

## Selection is always a human pick, never a typed path

The human never types or pastes a file path, a vault name, or a search string to prove intent.
Vault selection, note targets, and search scope are things the human points at, or the agent
infers from the live conversation — this applies across every skill in the family.

## References

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` — full contract (§3 invariants, §4 HTTP surface, §5
  direct-FS transport, §6 write discipline + failure table, §7 health duties).
- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md` — the enacting decision.
- `docs/AGENT-FLOWS.md` §4/§7 — observed-write semantics, workspace zones.
