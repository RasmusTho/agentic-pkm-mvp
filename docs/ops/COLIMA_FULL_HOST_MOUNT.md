# Colima full-host mount (in-process vault selection)

State: Operator runbook for the #2310 full-host mount — the compose-static `/Users` + `/Volumes` bind mounts plus the one-time Colima sharing + restart on the host (mac mini) that activates them. Live as of the #2310 delivery.

**Issue:** #2310 · **Enables:** Option-2 vault selection (#2309/#2325)

After Option-2, the runtime boots with no vault selected and the human picks a
vault in-process. For the containerized runtime to reach a vault on **any** disk,
the host's `/Users` and `/Volumes` are bind-mounted into the `api`, `worker`, and
`watcher` containers at **identical paths** (`docker-compose.yaml`), so a selected
host-absolute path (e.g. an iCloud Obsidian vault under
`/Users/<you>/Library/Mobile Documents/iCloud~md~obsidian/Documents/<Vault>` or a
T7 vault under `/Volumes/T7/<Vault>`) resolves transparently in-container.

The compose bind only works if the **Colima VM** shares those host directories.
Colima shares the home directory by default but **not `/Volumes`**, and a
whole-`/Users` share is not guaranteed — so this one-time reconfiguration is
required on the host (the mac mini).

## Security posture

Mounting the host filesystem widens what is *selectable / readable*, not what is
*writable beyond the selected vault*. Vault writes go through
`write_note_from_absolute`, which enforces `resolved_path.relative_to(vault_root)`
([app/knowledge/write_ops.py](../../app/knowledge/write_ops.py)), and
`app/write_guard.py` gates vault writes. A write cannot escape the selected vault
regardless of mount breadth.

## One-time host activation (mac mini)

> Reconfiguring Colima restarts the VM and therefore the dev stack. Do this in a
> maintenance window. Plug in the T7 first if you want to verify it.

```bash
# 1. Inspect current mounts
colima list
cat ~/.colima/default/colima.yaml | grep -A20 'mounts:'

# 2. Add /Users and /Volumes as writable mounts. Either edit the config:
#    ~/.colima/default/colima.yaml
#      mounts:
#        - location: /Users
#          writable: true
#        - location: /Volumes
#          writable: true
#    then: colima restart
#
#    …or restart with explicit flags:
colima restart --mount /Users:w --mount /Volumes:w

# 3. Bring the dev stack back up (regenerates runtime env, re-arms watcher).
cd <repo> && bash scripts/start_full_system.sh    # or the channel's start command
```

## Verify

```bash
# /Users and /Volumes are visible inside the api container at the same paths:
docker exec pkm-api-1 ls -ld /Users /Volumes

# Then in the UI: open a vault on the internal SSD and on /Volumes/T7 via the
# picker; confirm a note opens from each. Record the receipt on #2310.
```

## Notes

- Mount the **parents** `/Users` / `/Volumes`, never a specific volume, so the
  stack boots and stays healthy when the T7 is unplugged (`/Volumes` always
  exists; `/Volumes/T7` may not).
- The legacy `${VAULT_HOST_ROOT}:/app/vault` mount and container
  `VAULT_ROOT=/app/vault` remain until #2311 migrates the eager
  `resolve_vault_root()` consumers; this mount is purely additive.
