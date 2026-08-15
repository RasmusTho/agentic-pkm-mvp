# Yggdrasil Ollama host setup

State: Legacy host-setup reference; product runtime deployment is owned by `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`.

**Current boundary (2026-08-22): the Mac mini is Ollama-only.** Do not install or run the Yggdrasil
API, database, worker, watcher, Companion UI, or gateway on it. Product runtime belongs on the new
Linux/Tailscale `ygg-dev`, `ygg-test`, and `ygg-prod` hosts. The playbooks below predate that split and
must not be treated as a live deployment procedure until they are reconciled with the new host handoff.

The remaining supported purpose of this setup is to provide optional Ollama capacity to the product
runtime over the private Tailscale network.

```
            Tailscale (private, MagicDNS)
  MacBook Air ──────── ygg-dev / ygg-test / ygg-prod
  thin client          Linux product runtime hosts
       │                         │
       └──── Tailscale ──── Mac mini Ollama-only
                              (optional Gaming PC Ollama)
```

## The whole operator process

You only do the **bold** steps by hand. A coding agent (Claude Code or Codex) on
each box does the rest by reading that box's playbook.

1. **Install Tailscale on all three machines** and sign in to the same account.
   Enable **MagicDNS** in the Tailscale admin so `mac-mini` / `gaming-pc` resolve
   by name.
2. **Edit `ops/host-setup/config.env` once** (copy it from `config.example.env`):
   set `MAC_MINI_HOST`, `GAMING_PC_HOST`, and — on the gaming side —
   `WARDEN_GAME_PROCESSES` to your games' `.exe` names. Defaults for ports/models
   are fine.
3. **On the gaming PC**, open the agent and paste:
   > Set up this machine. Read and execute `ops/host-setup/gaming-pc/AGENT_PLAYBOOK.md`.
4. **On the MacBook Air**, follow `ops/host-setup/macbook-air/AGENT_PLAYBOOK.md`
   (mostly just Tailscale + connection shortcuts — no services).

The product hosts are separate from this optional inference setup. They must be
deployed and verified through the governed deployment handoff.

## Colima Docker startup durability gate

The Mac mini's Colima guest has a separate, refusal-first startup artifact set
for Docker/containerd persistence. It lives in
`ops/host-setup/mac-mini/systemd/` and is installed by
`install_colima_runtime_readiness.sh`. The installer is a dry-run unless the
governed host procedure explicitly sets `COLIMA_RUNTIME_APPLY=1`; installation
does not restart Colima, containerd, Docker, or any application channel.

`colima-data-mount.service` is the explicit systemd dependency boundary for
the existing Colima/Lima per-boot mount provisioner. It verifies the reviewed
source and bind mounts but does not guess a device, perform an unsafe mount,
or modify Docker/containerd metadata.

The gate binds one explicit Docker context, verifies the exact configured
persistent source and canonical UUID/LABEL/PARTUUID identity at
`/var/lib/docker` and `/var/lib/containerd`, waits for containerd RPC and
metadata readiness, and refuses a pre-start persisted inventory count that
differs from the reviewed expected count. After Docker responds, it also
refuses a Docker API whose persisted inventory is truncated. It never prunes,
recreates, deletes, or edits existing Docker/containerd metadata. The example
profile is an input template only; the live source identity, free-space floor,
and profile approval
must be supplied by the managed-host operator in the explicit
`COLIMA_RUNTIME_ENV_FILE` and recorded in a redacted receipt. The startup gate
is selected only by `COLIMA_RUNTIME_PROVIDER=colima`; another Docker provider
is left on its existing context.

Host activation, isolated candidate activation, default-profile cold start,
and final dev/test/prod channel isolation are separate gates. Repository
artifacts and a passing fake-command test do not claim that any live channel is
fixed.

## What each playbook does

| Machine | Role | Installs |
|---|---|---|
| `mac-mini/` | Ollama-only model host | Ollama (`nomic-embed-text` + `llama3.1:8b`); no product runtime or gateway |
| `gaming-pc/` | burst inference | Ollama (`gpt-oss:20b`), `gpu-warden` (Scheduled Task) |
| `macbook-air/` | thin client | nothing — Tailscale + Screen Sharing / Moonlight |

### Mac mini scheduled host jobs

The Mac mini also has an operator-owned weekly Docker cleanup LaunchAgent at
`~/Library/LaunchAgents/local.docker-weekly-prune.plist`. It runs
`~/bin/docker-weekly-prune.sh` on Sundays at 02:00. These two files are host-local:
the repository does not install, mirror, or otherwise own their contents. This
runbook records the safety contract across that boundary.

The weekly cleanup must never prune Docker volumes. Named channel volumes can be
unused after `docker compose down`, so `docker volume prune`, `docker system prune
--volumes`, and equivalent volume-deleting commands are forbidden in this job.
The existing image, builder-cache, and VM trim steps may continue; reclaiming
dangling volumes requires a separate bounded operator procedure.

After changing the host script:

1. Preserve a timestamped, mode-preserving copy of the pre-change script as
   audit evidence and mark it unsafe/non-restorable when it contains a forbidden
   prune path.
2. Build a same-directory candidate, run `sh -n`, confirm it contains no
   volume-pruning path, and record its SHA-256 and executable mode. Preserve a
   recovery copy of that exact candidate. Also prepare a checksum-recorded
   refusal artifact containing no Docker command; it only reports the failed
   safety proof and exits nonzero.
3. Validate the unchanged plist with `plutil -lint`, and confirm its program
   target and Sunday 02:00 schedule are unchanged.
4. Authenticate and atomically install the refusal artifact at the LaunchAgent's
   stable script path before executing the candidate from its separate,
   authenticated path. Retain a second pre-authenticated refusal candidate for
   the post-promotion readback fallback. A crash or failed pre-promotion check
   must therefore leave the scheduled job in the no-Docker refusal state.
5. Start a disposable isolated Docker daemon that cannot see the host daemon's
   channel volumes, and prove its daemon identity differs from the host's. Create
   one uniquely named, unused throwaway volume there. Point the candidate at the
   isolated daemon explicitly and capture its complete exit without
   short-circuiting the separate exact-volume check. Never run an unproved
   candidate against the host daemon.
6. Require the isolated volume to survive, remove only that exact throwaway,
   independently confirm its absence, and remove the disposable daemon. Any
   missing volume, later script failure, cleanup failure, or authentication
   failure before promotion leaves refusal installed and blocks.
7. After volume survival, script exit 0, and exact isolated cleanup, authenticate
   the same proved candidate again and only then promote it atomically to the
   stable path. Recheck its installed identity; on mismatch, atomically restore
   and authenticate the pre-built refusal fallback before blocking. Record the
   daemon isolation proof, throwaway name, create/survive/remove results,
   script exit, and promotion result. Never use or stop a real channel for this
   check.

Recovery must never restore an unsafe pre-change copy: that would reinstate the
forbidden deletion path. Recovery uses the same refusal-first sequence:
authenticate and install refusal at the stable path, prove the separately
authenticated safe artifact against a disposable isolated Docker daemon, and
promote that exact artifact only after the complete proof and cleanup pass. A
failed check or interrupted proof leaves refusal installed. A failed
post-promotion identity readback restores the pre-authenticated refusal
fallback; a crash after the atomic promotion leaves the exact proved safe
artifact installed. Use explicit failure branches with cleanup and nonzero exit
status rather than bare shell assertions.
Keep both the non-restorable audit copy and the authenticated safe recovery copy
until the change receipt is accepted.

## How the routing works

- The current Linux/Tailscale runtime binds to one explicit Ollama endpoint. The
  dedicated Ollama host provides model service only; it does not run the Yggdrasil
  API, watcher, or an `llm-gateway`.
- Keep the embedding model identity stable. A runtime change of embedding provider
  or model requires the repository's explicit index-rebuild decision; it is not an
  automatic routing fallback.
- Chat and reasoning use the selected runtime's declared provider binding. Do not
  infer a second host, gaming-PC burst route, or gateway fallback from this
  playbook. Local Compose remains a separate fallback/reference environment.

## Tuning & options

- **Priority knobs** live in `config.env`: `WARDEN_GAME_PROCESSES` (strong "I'm
  gaming" signal) and `WARDEN_GPU_BUSY_PCT` (utilization threshold).
- **Reclaim idle games** (close a game left running while you're AFK to free the
  GPU) is **off by default** — set `WARDEN_RECLAIM_IDLE=1`. It can lose unsaved
  progress, so only list games you're comfortable having closed.
- **Power saver:** let the gaming PC sleep when idle and add Wake-on-LAN so the
  gateway can wake it on demand (future enhancement; serve from mini/cloud while
  it wakes).
- **Cloud burst:** to add a frontier fallback for the heaviest reasoning, extend
  the gateway's chat branch to forward to DeepSeek/OpenAI when both local hosts
  are busy. Left out of v1 to keep core flows fully local.

## Security

Ollama and the warden have **no authentication**. They are only safe because
Tailscale makes them reachable to your devices alone. Never bind these ports to a
public interface, and scope any Windows Firewall rules to the Tailscale interface.

> Status: v1 operator tooling. Heuristics (GPU-util threshold, game detection) are
> meant to be tuned per setup. Lives under `ops/` and changes no product runtime
> behavior.
