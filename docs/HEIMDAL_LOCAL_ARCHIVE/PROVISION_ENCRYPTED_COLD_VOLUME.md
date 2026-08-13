---
name: Provision Encrypted Cold Volume
task_id: HAR-03
source_anchor: docs/HEIMDAL_LOCAL_ARCHIVE/README.md :: Fixed constraints
parent_capability: Heimdal Local Archive
prerequisites: [HSP-02, HAR-02]
depends_on: [HSP-02, HAR-02]
can_parallelize_with: []
---

State: HAR-03 encrypted-volume lifecycle delivered; archive copy/retention remain future-state

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

## Delivered boundary

`app/ops/heimdal_cold_volume.py` is the host-only enforcement boundary. It accepts one closed,
mode-0600 metadata document that binds archive identity, the sparsebundle location, mountpoint,
capacity ceiling, external-parent volume UUID, sparsebundle inode, bounded immutable image-metadata
fingerprint, APFS volume UUID, verified mounted-filesystem capacity, monotonic transition generation,
numeric owner/group, mode, and lifecycle state. Initial metadata is generation zero
`planned-unbound` with null bundle binding, filesystem capacity, and APFS UUID. Immediately after creation the provisioner
durably records `provisioning-failed` with the bundle inode and SHA-256 of its bounded, parsed
`Info.plist` at generation one; that deliberately named residual is safe to replay but is never startup-ready. The
first successful attach validates the generated APFS UUID and durably advances through
`attached-verified` (generation two) to `bound-active` (generation three); startup and ordinary mounting accept only the final state. Each
transition holds a descriptor-bound adjacent mode-0600 OS file lock, rereads the exact expected
generation and canonical bytes under that lock, then atomically replaces and fsyncs the metadata
and parent directory. A stale concurrent writer refuses rather than overwriting a newer identity. It
permits only fixed `hdiutil create`, `attach`, `info`, and `isencrypted` forms plus read-only
`diskutil info`; all machine output is bounded and parsed as typed property lists. Detach is not
available through the generic command adapter. A private compensation capability, issued only from
one successful attach response, may detach exactly that response's device. Shell commands,
caller-selected detach devices, raw-device sources, overwrites, disk erasure, partition changes,
and parent-volume targets are not representable.

The configured sparsebundle parent must be the exact root reported by `diskutil` for an external
volume, not a child directory or symlink. The declared image capacity is an exact positive multiple
of 512 bytes, bounded by the sparsebundle format, and is passed as a checked sector count. `hdiutil`
documents that partition and filesystem overhead is not available to the filesystem, so the first
successful attach records the positive, aligned mounted APFS capacity only when it is no greater
than the declared image maximum; every later validation requires that exact recorded value. Image
encryption and filesystem format are deliberately separate layer contracts: `hdiutil isencrypted`
must prove the AES-encrypted sparsebundle wrapper, while `diskutil` must prove APFS. The default APFS
volume inside an encrypted image is not itself asserted to carry APFS-layer encryption. Owner,
group, mode, mountpoint, bundle path, device, filesystem UUID, volume name, external-media flag, and
filesystem type are checked using bounded typed output and descriptor-bound filesystem identity.
Every image path reported by `hdiutil` is opened component by component without following symlinks;
its final device/inode must equal the persisted bundle identity. Path spelling or case-folded text
alone never associates an attachment with the archive. Creation passes only the bundle basename to
a child process that changes directory directly through the still-open, revalidated external-root
descriptor before executing the fixed command. That child hook is restricted to the short-lived,
single-threaded provisioning CLI; threaded or imported runtime use refuses. The descriptor and its
device/inode authority remain live through creation, descriptor-relative encryption inspection and
attach, and the post-attach parent UUID, bundle inode, and image-metadata fingerprint recheck. A successful attach response
establishes the newly attached device identity before rediscovery, so later validation failure
compensates only that invocation's mount. No failure path automatically deletes a sparsebundle path:
the residual binding is preserved for replay or explicit operator recovery, and cleanup never
selects or detaches a device by rediscovering the mutable live bundle path. Live readiness requires
the persisted parent-volume UUID, bundle inode, image-metadata fingerprint, and mounted APFS UUID;
path text alone is never authority.

The unlock secret is the required `heimdal.archive-pass` declaration for the dedicated
`heimdal-cold-volume` consumer in the Local Secret Provisioning contract. HSP resolves it from the
macOS Keychain into its existing owner-only temporary file, and the volume boundary passes it to
`hdiutil` only as null-terminated standard input. It is never an argument, ordinary environment
variable, metadata field, log field, or receipt field.

Production startup and deployment share `scripts/lib/heimdal_cold_volume_preflight.sh`. Its one
effective-channel classifier treats a normalized prod channel, the prod Compose project, or an
explicit prod Compose overlay as production. That gate
only validates an already mounted archive and runs before generic startup or deploy mutation. It
never creates or attaches an image. The direct full-system prod launcher, the Companion UI
(including its warm-start path), `cold_boot` before host-state preparation or Compose teardown,
`make prod-up`, the prod wrapper, and the deploy action all invoke
the same gate. Rollback remains reachable when the archive is unavailable so the previous-good
service can be restored. HAR-04 remains responsible for any archive write, verified copy,
representation activation, or hot retirement.

## Non-destructive operator runbook

1. Choose an existing external volume root, a separate empty mountpoint, a stable archive identifier,
   a 512-byte-aligned maximum capacity, and the intended numeric uid/gid. Keep these host-specific
   values out of Git. Write the closed metadata document with `generation` zero, state
   `planned-unbound`, null `bundle_inode`, `image_metadata_sha256`, `filesystem_capacity_bytes`, and
   `volume_uuid`, the exact external parent volume UUID,
   mode value `448` (`0700`), and file mode `0600`; set its absolute path as
   `HEIMDAL_ARCHIVE_METADATA_FILE` in the ignored channel-local environment file. Do not choose or
   invent an APFS UUID: the provisioner binds the one generated by the image tool.
2. Add one strong passphrase to the existing `yggdrasil.host-secrets` Keychain service under the
   HSP-derived `{channel}:heimdal-cold-volume:heimdal.archive-pass` account. Use Keychain Access or a
   non-echoing prompt; never put the value on a command line or in a file.
3. Run provisioning through HSP, which owns and removes the temporary credential surface:

   ```bash
   python3 -m app.ops.host_secret_bootstrap \
     --channel <dev-or-test> --consumer heimdal-cold-volume -- \
     python3 -m app.ops.heimdal_cold_volume provision \
     --metadata "$HEIMDAL_ARCHIVE_METADATA_FILE"
   ```

   Provisioning is idempotent. An existing bound bundle is never overwritten, and an already correct
   mount is only revalidated. Creation uses an AES-256 encrypted sparsebundle image containing an
   APFS filesystem inside the external parent root; it never reformats or partitions the parent
   disk. Success means the
   generated UUID, actual verified filesystem capacity, and `bound-active` state were persisted
   through the locked generations before the command
   returned.
4. For a later mount, use the same HSP wrapper with the `mount` action. To detach, first stop the
   future HAR-04 archive worker, obtain the verified device from a redacted local diagnostic, and use
   the fixed `hdiutil detach` operation. Production startup itself never auto-mounts.
5. On failure, do not delete, recreate, resize, erase, or partition anything. Correct the Keychain
   item or metadata mismatch and replay the same action. A mount newly attached by a failed attempt
   is detached by that attempt; a pre-existing mount is preserved for diagnosis. The provisioner
   never auto-deletes a sparsebundle. A normal post-create failure remains durably
   generation-one `provisioning-failed` with its exact parent/bundle/image binding and replay validates that binding
   while unmounted, then requires a fresh attach from that bundle; it never adopts an attachment
   found before replay. If even the residual metadata write fails, the created bundle is preserved and
   `planned-unbound` replay refuses its presence for explicit operator recovery. An
   generation-two `attached-verified` replay validates the already-bound UUID and filesystem
   capacity and may advance to generation-three `bound-active`
   without recreating anything. UUID drift or any unprovable parent UUID, bundle inode/fingerprint,
   encryption, owner/mode, mountpoint,
   capacity, image, or parent association always refuses.

## Acceptance criteria

- [x] Archive startup refuses an absent, locked, unencrypted, or identity-mismatched archive mount.
      Verify: `tests/heimdal/test_local_archive_volume.py::test_archive_requires_mounted_encrypted_volume`
- [x] The provisioner does not invoke reformat/erase operations and does not write raw blobs directly
      to the parent external volume.
      Verify: `tests/heimdal/test_local_archive_volume.py::test_provisioner_never_reformats_or_uses_parent_volume`
- [x] The mount credential is resolved only through HSP and is not recorded in the runbook or deploy
      configuration.
      Verify: `tests/heimdal/test_local_archive_volume.py::test_mount_credential_is_keychain_backed_and_redacted`

## Out of scope

Copying raw data, retention behavior, cloud/off-site replication, and changing external-disk
partitions.

## How to verify

`pytest -q tests/heimdal/test_local_archive_volume.py`
