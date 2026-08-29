State: Active capability specification. P1's manifest contract, P2's immutable artifact renderer,
P3's read-only ordinary-boot doctor, and P4's durable promotion-test receipt writer and prod
admission validator are implemented in the repository; P5–P6 remain unimplemented. This does not claim a running remote
deployment model or a live immutable channel identity.
Current-state note (2026-08-22): the live topology is now intended to be a dedicated Ollama host plus
Linux/Tailscale `ygg-dev` / `ygg-test` / `ygg-prod` runtime hosts. The redesign contract is not yet
implemented as a remote-host deployment path; `ygg-test` and immutable live artifact identity remain
gates before staged promotion.
Doc role: Capability specification directory (Product/Runtime + Builder System release boundary)
Owning SoT: `docs/ENVIRONMENTS.md`, `docs/RELEASE_CHANNELS/README.md`, and `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

# Dev/Test/Prod Startup Redesign

## Purpose

Define the small, deterministic startup and promotion kernel needed to recover stable production without making ordinary boot a deployment engine. Before filing, its overlap with `PINNED_IMAGE_CUTOVER` (#2655/#2698 and children) was reconciled against the live issue set; this filed chain owns the newer two-mode, receipt-gated contract and does not rewrite the earlier capability.

## Capability boundary

The redesign has two explicit delivery modes: `local-source` for dev/local-test, and immutable `promotion` for promotion-test and prod. Compose remains the topology mechanism; the only new control components are a deterministic manifest resolver, operation journal, and receipt validator. It does not add a service mesh, orchestration service, hosted deployment, or a second authority system.

## Implementation tasks

P0 is deliberately not a child task: the live Colima persistent-substrate recovery is already tracked by #4899 and remains a hard prerequisite for any channel mutation.

1. [Freeze Channel Manifest And Operation Contract](FREEZE_CHANNEL_MANIFEST_AND_OPERATION_CONTRACT.md) — P1, implemented by #4914
2. [Build Immutable Artifact Graph](BUILD_IMMUTABLE_ARTIFACT_GRAPH.md) — P2, implemented by #4915
3. [Implement Read-Only Ordinary Boot](IMPLEMENT_READ_ONLY_ORDINARY_BOOT.md) — P3, implemented by #4916
4. [Prove Promotion-Test Receipts](PROVE_PROMOTION_TEST_RECEIPTS.md) — P4, implemented by #4917
5. [Execute Topology-Only Prod Cutover](EXECUTE_TOPOLOGY_ONLY_PROD_CUTOVER.md) — P5, operator-gated
6. [Retire Legacy Startup Paths](RETIRE_LEGACY_STARTUP_PATHS.md) — P6, post-soak

## Kernel invariants

- **K1:** Every operation resolves one exact ChannelManifest; prod has no implicit fallback.
- **K2:** Dev and test cannot physically access prod DBs, vaults, volumes, or credentials.
- **K3:** Local-source identity records source SHA plus dirty state and cannot authorize promotion; promotion identity is `repo@image-digest`.
- **K4:** Only deploy/promotion migrates. Ordinary boot performs a read-only compatibility check.
- **K5:** Prod accepts only a non-revoked PASS receipt bound to artifact digest, config/test identities, schema, and required checks.
- **K6:** Writers require one enrolled, unambiguous prod-vault identity.
- **K7:** Deploy and recovery each emit exactly one truthful terminal result with a classified phase.
- **K8:** A rollback target is runtime/schema/vault compatible and never rewinds operator-authored vault content.
- **K9:** Secrets never appear in manifests, config hashes, logs, or receipts; no ambient fallback is permitted.

### Invariant enforcement phases

The phase column is the frozen enforcement hand-off for the later implementation slices. P1
proves the mapping statically; it does not claim that these runtime phases are shipped.

| Invariant | Enforcement phase | Owning slice |
| --- | --- | --- |
| **K1** | `resolve` | P1 / P3 |
| **K2** | `admit` | P2 / P3 |
| **K3** | `admit` | P1 / P2 |
| **K4** | `resolve` | P3 |
| **K5** | `receipt` | P1 / P4 |
| **K6** | `admit` | P1 / P3 |
| **K7** | `terminal` | P1 / P3 / P4 |
| **K8** | `recover` | P1 / P5 / P6 |
| **K9** | `resolve` | P1 / P2 / P4 |

## Cross-Task Invariants / Interaction Safety

`local-source` and `promotion` artifacts are disjoint identities: a local build may never be relabelled as a promotion candidate. A promotion is non-terminal until the immutable digest, schema journal, and promotion-test receipt agree. A prod recovery cannot repair ambiguity by choosing a vault, image, or receipt: it fails closed. Rollback changes the runtime artifact only after compatibility proof and leaves the vault untouched. P6 may remove a legacy caller only after a later digest promotion and recovery/rollback drills prove no supported caller remains.

### Terminal operation vocabulary

Every deploy, recovery, and ordinary-boot operation emits exactly one terminal result from this
vocabulary:

| Terminal phase | Meaning |
| --- | --- |
| `PRE_MUTATION_FAILURE` | Validation, identity, dependency, or receipt admission failed before any migration or activation mutation. |
| `FAILED_AFTER_MIGRATION` | An actual migration/schema mutation occurred, but the operation did not reach activation success; this takes precedence over any later activation/health failure and is never PASS. A journal attempt alone is not migration. |
| `ACTIVATION_FAILURE` | Activation/health proof failed without any migration/schema mutation; a journal attempt may exist, but this is never PASS. |
| `PASS` | Required migration (when applicable), activation, and receipt checks completed for the exact manifest. |
| `ORDINARY_BOOT_PASS` | Read-only compatibility, identity, and health checks completed for the exact manifest; no migration, activation mutation, or promotion receipt is implied. |

Terminal classification is ordered by mutation evidence: validation or journal-only failure is
`PRE_MUTATION_FAILURE`; an actual schema/migration mutation selects `FAILED_AFTER_MIGRATION`; only
activation/health failure with no migration selects `ACTIVATION_FAILURE`; a successful read-only
ordinary boot selects `ORDINARY_BOOT_PASS`.

### Promotion receipt contract

The K5 receipt uses schema `promotion-receipt.v2` and is a machine-readable, content-addressed
record with exactly these semantic fields:
`receipt_version`, `receipt_id`, `outcome`, `artifact_digest`, `config_identity`, `test_identity`,
`vault_identity`, `schema_identity`, `required_checks`, `issued_at`, `fresh_until`, `issuer_id`,
`issuer_key_id`, `migration_baseline_identity`, `migration_set_identity`,
`check_report_identity`, and `issuer_signature`. The canonical
bytes are UTF-8 JSON with lexicographically sorted keys, compact separators, and no trailing
newline; `receipt_id` is `sha256:` plus the digest of those bytes with `receipt_id` excluded.
The issuer signs a separate acyclic canonical unsigned payload using the same encoding with both
`receipt_id` and `issuer_signature` excluded; `issuer_signature` is verified against that payload
and the trusted issuer key, never against the receipt ID. `outcome` is `PASS` or `FAIL`; the
identity values bind the receipt to the exact admission context.
`required_checks` must exactly equal the versioned external policy
`promotion-receipt.v1/required-checks` = `[migration, readiness, schema, smoke, ui, version]` in
sorted order. `fresh_until` is the exclusive freshness deadline. `issuer_signature` is verified
against the trusted `promotion-test-issuer` key/authority registry. The registry binds that
attestation to the immutable receipt ID. Revocation is not a mutable receipt field: the machine-readable
`promotion-receipt-registry.v1` stores `registry_version` and entries keyed by immutable
`receipt_id`, each with `issuer_id`, `issuer_key_id`, `public_key`, `issuer_signature`, and `status`
(`issued` or `revoked`); `public_key` is exactly 32 raw Ed25519 public-key bytes encoded as
unpadded URL-safe Base64, and `issuer_signature` is exactly 64 raw Ed25519 signature bytes encoded
as `ed25519:v1:<unpadded-base64url>`. `issuer_key_id` selects the trusted public key. Registry
fields are outside the receipt digest. The registry also has exactly `trusted_keys`, an independent
`issuer_key_id` → `public_key` mapping; admission resolves the key only from that mapping and
requires the entry key material to match it. That trust-root mapping must be provisioned by an
independent operator-controlled producer before promotion-test verification. The receipt writer
never creates the registry or enrolls a caller-supplied key; a missing registry, absent key, or key
mismatch fails before it reserves an attempt or publishes terminal evidence. Registry lookup
failure is a hard admission failure.
Prod admission requires `outcome=PASS`, matching expected
identities from an independently supplied prod-admission manifest and `test_identity` from the
versioned promotion-test policy, current time at or after `issued_at` and before `fresh_until`, a valid trusted
issuer attestation, a present registry entry with `status=issued` (never absent or revoked), and
exact required-check coverage. The validator also consumes the canonical promotion-test check
report: its digest must equal the signed `check_report_identity`, its migration-set identity must
equal the signed `migration_set_identity`, and its baseline must equal both the signed
`migration_baseline_identity` and the independently supplied prod-admission context. The writer
and validator resolve that baseline from the authoritative current promotion ref (`origin/main`
in the current interim model), so a caller cannot choose the candidate itself or substitute a
different syntactically valid baseline or report.
`tests/fixtures/startup_redesign/promotion_admission_context.valid.json` supplies the independent
positive-admission expectations, while
`tests/fixtures/startup_redesign/promotion_check_report.valid.json` supplies the signed report
evidence; the receipt fixture is validated against both rather than against itself. Receipts and
check reports contain no secret values
or secret references.

The machine-readable shapes are frozen as follows; producers must emit no additional fields:

```json
{
  "receipt": [
    "receipt_version", "receipt_id", "outcome", "artifact_digest", "config_identity",
    "test_identity", "vault_identity", "schema_identity", "required_checks", "issued_at",
    "fresh_until", "issuer_id", "issuer_key_id", "migration_baseline_identity",
    "migration_set_identity", "check_report_identity", "issuer_signature"
  ],
  "registry": ["registry_version", "trusted_keys", "entries"],
  "registry_entry": [
    "issuer_id", "issuer_key_id", "public_key", "issuer_signature", "status"
  ]
}
```

`issuer_key_id` participates in the receipt's canonical digest and unsigned signed payload.
`issuer_signature` participates in the receipt digest, but not in the signed payload; it is
the signature over the canonical unsigned payload after both `receipt_id` and `issuer_signature`
are removed. Registry fields are not receipt-digest inputs. Every Base64URL value is decoded and
re-encoded before use; the re-encoded
unpadded URL-safe value must be byte-for-byte identical, which rejects nonzero terminal pad bits
as well as padding and standard-Base64 characters.

The P4 writer stores receipts under an explicitly configured non-resettable promotion-test store,
never under `tmp-test/` or `vault-test/`. It derives artifact/config/schema identity from a validated
P2 promotion-test candidate, matches that against an independently supplied prod-admission context,
including that context's exact Git migration-baseline identity, and requires the runner report to
bind the same candidate, identity, and check results. Under the store lock it first verifies the
independently provisioned trust registry and then durability-fences an immutable attempt
reservation. It writes and durability-fences the content-addressed receipt and one immutable
canonical attempt binding. Only after both terminal records revalidate does it add the issued entry
to the pre-existing durability-fenced `registry.json`; it never changes `trusted_keys`. That
registry is the authority input consumed by `prepare_prod_activation`; an absent, changed, or
revoked entry fails closed. A later PASS/FAIL,
timestamp, identity, candidate, or
migration-set change for the same `pt-<id>` attempt is rejected. A crash after receipt persistence
but before the attempt binding leaves an immutable reserved orphan; only an identical retry can
reuse it and publish the single binding. A crash after the binding but before registry publication
leaves terminal evidence that remains inadmissible to prod until an identical retry publishes the
matching issued entry; a revoked or conflicting entry is never repaired away. Immutable
records use a same-directory fsynced temp hard link, remove that temp name before the final
directory fence, and recover only a same-owner temp that is the exact published inode after a
crash in that unlink/fence gap. The complete migration delta is derived, not accepted from the
caller: the writer resolves the authoritative current promotion ref (`origin/main` in the current
interim model), then diffs that baseline commit against the candidate's exact
source commit under `app/alembic/versions`, then materializes each target file from those immutable
Git objects. The same object bytes feed both the migration-set digest and
`app.release_channels.reversibility.check_migration_snapshots`. The attempt journal records the six
boolean check outcomes and that existing classifier's receipt. The promotion
receipt itself retains the closed semantic field set above. Migration marker rules remain owned by
the release-channel reversibility contract and are not reimplemented by P4.

## Verification and acceptance

P1 is proven by the static contract test and fixture in `tests/architecture/test_startup_redesign_contract.py`. P2 is proven through the side-effect-free production renderer in `app/release_channels/channel_manifest.py` and its runtime call-site tests. P3 is proven through the read-only resolver and exactly-once terminal journal in `app/release_channels/ordinary_boot.py` plus the production call-site tests. P4 is proven through `app/release_channels/promotion_receipt.py`: the promotion-test entrypoint binds runner observations to one validated candidate and writes one signed PASS/FAIL receipt plus its terminal attempt journal. The `prepare_prod_activation` boundary invokes the prod validator and accepts only an exact, current, issued, non-revoked PASS. It returns `validated_not_activated` admission evidence only; it cannot activate, deploy, migrate, restart, or bypass a channel. P5 must consume this boundary immediately before its separately governed activation. P3 does not activate a channel or replace the current canonical prod startup command. P5 requires a live-host acceptance receipt; P6 requires soak and drill receipts. No local-source result is promotion evidence.

## Relationship to existing work

`docs/deployment/PINNED_IMAGE_CUTOVER/` remains the existing documented pinned-image/cutover capability. Its open/closed issue set and overlap with this design were reconciled before the #4913–#4919 chain was filed. This directory is a contract freeze for the newer two-mode, receipt-gated design; it does not change the earlier capability's current-state claims.

## Relationship to GitHub issues

Parent validation hub: #4913. The execution chain is #4914 (P1) → #4915 (P2) → #4916 (P3) → #4917 (P4) → #4918 (P5, operator-gated) → #4919 (P6). P0 recovery remains #4899 and blocks host Docker/Colima recovery and any cutover.
