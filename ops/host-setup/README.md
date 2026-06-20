# Yggdrasil two-box host setup

Turn a base **Mac mini** (always-on core) + your **Windows gaming PC** (burst
inference) + a **MacBook Air** (thin client) into the local-first host for
Yggdrasil — with LLM routing that **prefers the gaming GPU when it's idle and
backs off the moment you start a game**.

```
            Tailscale (private, MagicDNS)
  MacBook Air ──────── Mac mini ──────── Gaming PC (Windows)
  thin client          ALWAYS-ON         BURST INFERENCE
  Screen Share/SSH     • runtime         • Ollama (fast MoE)
  Moonlight            • Ollama 8B+embed • gpu-warden (/status)
                       • llm-gateway ◀──── routes here when GPU is free
```

## The whole operator process

You only do the **bold** steps by hand. A coding agent (Claude Code or Codex) on
each box does the rest by reading that box's playbook.

1. **Install Tailscale on all three machines** and sign in to the same account.
   Enable **MagicDNS** in the Tailscale admin so `mac-mini` / `gaming-pc` resolve
   by name.
2. **Install Claude Code (or Codex) on the Mac mini and the gaming PC**, and clone
   this repo on each (the mini probably already has it).
3. **Edit `ops/host-setup/config.env` once** (copy it from `config.example.env`):
   set `MAC_MINI_HOST`, `GAMING_PC_HOST`, and — on the gaming side —
   `WARDEN_GAME_PROCESSES` to your games' `.exe` names. Defaults for ports/models
   are fine.
4. **On the gaming PC**, open the agent and paste:
   > Set up this machine. Read and execute `ops/host-setup/gaming-pc/AGENT_PLAYBOOK.md`.
5. **On the Mac mini**, open the agent and paste:
   > Set up this machine. Read and execute `ops/host-setup/mac-mini/AGENT_PLAYBOOK.md`.
6. **On the MacBook Air**, follow `ops/host-setup/macbook-air/AGENT_PLAYBOOK.md`
   (mostly just Tailscale + connection shortcuts — no services).

That's it. After step 5 the mini is serving the prosthesis 24/7 and routing chat
to the gaming PC whenever it's free.

## What each playbook does

| Machine | Role | Installs |
|---|---|---|
| `mac-mini/` | always-on core | Ollama (`nomic-embed-text` + `llama3.1:8b`), `llm-gateway` (launchd), wires Yggdrasil's `OLLAMA_URL` |
| `gaming-pc/` | burst inference | Ollama (`gpt-oss:20b`), `gpu-warden` (Scheduled Task) |
| `macbook-air/` | thin client | nothing — Tailscale + Screen Sharing / Moonlight |

## How the routing works

- Yggdrasil talks to **one** endpoint: the `llm-gateway` on the mini
  (`OLLAMA_URL=http://127.0.0.1:11500`). The runtime's own LLM fabric doesn't
  load-balance (see `docs/LLM_ROUTING.md`), so the gateway does it.
- **Embeddings always stay on the mini** — moving them would change embedding
  identity and force a full vector-index rebuild. The gateway enforces this pin.
- **Chat/reasoning** goes to the gaming PC **only when `gpu-warden` says the GPU is
  free** (no listed game running and GPU utilization below the threshold).
  Otherwise it serves from the mini's small model. If the gaming box disappears
  mid-request, the gateway degrades to the mini automatically.

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
