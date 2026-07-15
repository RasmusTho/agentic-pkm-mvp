---
name: Provision Encrypted Cold Volume
task_id: HAR-03
source_anchor: docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Fixed constraints
parent_capability: Heimdal Local Archive
prerequisites: [HSP-02, HAR-02]
depends_on: [HSP-02, HAR-02]
can_parallelize_with: []
---

State: Authored task specification (future-state; child issue not yet filed)

# Provision Encrypted Cold Volume

## Purpose

Provision and validate the local encrypted archive mount without reformatting or directly trusting
the external disk's filesystem.

## What this task does

1. Define archive-volume identity, mountpoint, capacity ceiling, and Keychain-backed unlock
   credential under the Local Secret Provisioning contract.
2. Create/use an encrypted APFS sparsebundle located on the external disk; do not reformat, erase, or
   write raw audio directly to the parent volume.
3. Validate mount, encryption, capacity, and ownership before archive work begins; absence, lock, or
   wrong volume identity is a loud unhealthy state.
4. Add an operator runbook with non-destructive setup, mount/unmount, and recovery steps.

## Acceptance criteria

- [ ] Archive startup refuses an absent, locked, unencrypted, or identity-mismatched archive mount.
      Verify: `tests/heimdal/test_local_archive_volume.py::test_archive_requires_mounted_encrypted_volume`
- [ ] The provisioner does not invoke reformat/erase operations and does not write raw blobs directly
      to the parent external volume.
      Verify: `tests/heimdal/test_local_archive_volume.py::test_provisioner_never_reformats_or_uses_parent_volume`
- [ ] The mount credential is resolved only through HSP and is not recorded in the runbook or deploy
      configuration.
      Verify: `tests/heimdal/test_local_archive_volume.py::test_mount_credential_is_keychain_backed_and_redacted`

## Out of scope

Copying raw data, retention behavior, cloud/off-site replication, and changing external-disk
partitions.

## How to verify

`pytest -q tests/heimdal/test_local_archive_volume.py`
