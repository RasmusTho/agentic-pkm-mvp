# Agent Playbook — Gaming PC (Windows)

You are a coding agent (Claude Code / Codex) running on the Windows gaming PC.
Set this machine up as the **burst inference node**. Work top to bottom; stop and
report if a step fails.

## Preconditions (the operator did these by hand)
- Tailscale installed and signed in (same tailnet as the mini + Air).
- This repo is cloned locally, or at least the `ops/host-setup/` folder is present.
- `python` and `winget` are available (`python --version`, `winget --version`).

## Steps
1. **Confirm tailnet.** Run `tailscale status`. Note this machine's name and that
   `mac-mini` is visible. The name here must match `GAMING_PC_HOST` in
   `ops/host-setup/config.env` (create it from `config.example.env` if missing).

2. **Pick the burst model.** Default is `gpt-oss:20b` (MoE, fast on the RX 9070 XT).
   Leave it unless the operator asked otherwise. The heavy model
   (`qwen3:30b-a3b`) is optional — only pull it if asked.

3. **Set your games.** Edit `WARDEN_GAME_PROCESSES` in `config.env` to the actual
   `.exe` names of games the operator plays (e.g. `cs2.exe,bg3.exe`). This is the
   strong "I'm gaming, hands off the GPU" signal. Leave `WARDEN_RECLAIM_IDLE=0`
   unless the operator explicitly opts into auto-closing idle games.

4. **Run the installer** in an elevated PowerShell:
   `powershell -ExecutionPolicy Bypass -File ops/host-setup/gaming-pc/install.ps1`
   It installs Ollama, serves it on the tailnet, pulls the model, creates the
   warden venv, and registers the `yggdrasil-gpu-warden` Scheduled Task.

5. **AMD note (RX 9070 XT / RDNA4).** If Ollama fails to use the GPU, check
   `ollama ps` during a test generation. If it runs on CPU, install **LM Studio**
   and enable its Vulkan runtime + local server instead, then set
   `GAMING_OLLAMA_PORT` to LM Studio's port and re-run only the warden step.
   Report which backend you ended up using.

6. **Verify locally:**
   - `Invoke-RestMethod http://127.0.0.1:9090/status` → JSON with `available`.
   - `ollama run gpt-oss:20b "say hi"` → a fast reply.

7. **Verify the firewall** allows the tailnet to reach ports
   `GAMING_OLLAMA_PORT` and `WARDEN_PORT` (add inbound rules scoped to the
   Tailscale interface / 100.64.0.0/10 if needed). Do **not** open them to the
   public internet.

8. **Report** to the operator: machine name, model + backend, warden `/status`
   output, and any firewall rule you added.
