# Agent Playbook — MacBook Air (thin client)

This legacy playbook configures the Air as a **thin client** and installs no Product Runtime
services. It is mostly manual operator setup, not an inventory of services currently running on
the Air. [The infrastructure status view](https://github.com/RasmusTho/yggdrasil-infra/blob/main/CURRENT_STATUS.md)
owns dated host observations; this pass did not directly inventory Air services.

## Steps
1. **Tailscale** installed and signed in (same tailnet). Verify with
   `tailscale status` that the approved runtime and operator peers are reachable.

2. **Reach the Mac mini (macOS):**
   - GUI: Finder → Go → Connect to Server → `vnc://mac-mini` (Screen Sharing).
   - Admin: `ssh <user>@mac-mini`.

3. **Reach the gaming PC (Windows):**
   - Admin/headless: `ssh <user>@gaming-pc` (enable OpenSSH Server on Windows).
   - Full desktop / play remotely: install **Moonlight** here and **Sunshine**
     on the PC (low-latency GPU streaming over Tailscale). **RustDesk** is a
     simpler alternative for casual remote desktop.
   - Note: Windows 11 **Home cannot host RDP** — use Sunshine/Moonlight or RustDesk.

4. **Use the prosthesis:** follow the infrastructure repository's
   [UI access procedure](https://github.com/RasmusTho/yggdrasil-infra/blob/main/client/README.md)
   for the selected Linux channel. This legacy playbook does not establish a current direct-port
   entrypoint or authorize a tunnel. The Mac mini also hosts model-execution and operator services;
   its observed inventory belongs to the status view above. Application placement and routing
   remain governed by the application environment and Model Access contracts.

There is no Product Runtime service to install for this thin-client setup. If the operator wants a one-click
"connect" experience, create Shortcuts/bookmarks for the VNC, SSH, and companion
UI URLs above.
