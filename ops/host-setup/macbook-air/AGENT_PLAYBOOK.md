# Agent Playbook — MacBook Air (thin client)

The Air is just a **thin client**. No services run here; it only needs to reach
the mini and the gaming PC over Tailscale. This is mostly manual operator setup.

## Steps
1. **Tailscale** installed and signed in (same tailnet). Verify with
   `tailscale status` that both `mac-mini` and `gaming-pc` are reachable.

2. **Reach the Mac mini (macOS):**
   - GUI: Finder → Go → Connect to Server → `vnc://mac-mini` (Screen Sharing).
   - Admin: `ssh <user>@mac-mini`.

3. **Reach the gaming PC (Windows):**
   - Admin/headless: `ssh <user>@gaming-pc` (enable OpenSSH Server on Windows).
   - Full desktop / play remotely: install **Moonlight** here and **Sunshine**
     on the PC (low-latency GPU streaming over Tailscale). **RustDesk** is a
     simpler alternative for casual remote desktop.
   - Note: Windows 11 **Home cannot host RDP** — use Sunshine/Moonlight or RustDesk.

4. **Use the prosthesis:** open the Yggdrasil companion UI at the mini's API port
   over Tailscale (e.g. `http://mac-mini:18000`). Everything else (LLM routing,
   embeddings, the watcher) is handled by the mini.

There is nothing to install as a service here. If the operator wants a one-click
"connect" experience, create Shortcuts/bookmarks for the VNC, SSH, and companion
UI URLs above.
