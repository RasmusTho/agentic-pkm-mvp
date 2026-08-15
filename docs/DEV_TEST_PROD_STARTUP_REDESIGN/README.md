State: Filed capability specification. P1 is active under #4914; later slices remain dependency-blocked. It does not claim a running deployment model.
Doc role: Capability specification directory (Product/Runtime + Builder System release boundary)
Owning SoT: `docs/ENVIRONMENTS.md`, `docs/RELEASE_CHANNELS/README.md`, and `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

# Dev/Test/Prod Startup Redesign

## Purpose

Define the small, deterministic startup and promotion kernel needed to recover stable production without making ordinary boot a deployment engine. This supersedes no existing issue: before filing, its overlap with `PINNED_IMAGE_CUTOVER` (#2655/#2698 and children) must be reconciled against live GitHub state.

## Capability boundary

The redesign has two explicit delivery modes: `local-source` for dev/local-test, and immutable `promotion` for promotion-test and prod. Compose remains the topology mechanism; the only new control components are a deterministic manifest resolver, operation journal, and receipt validator. It does not add a service mesh, orchestration service, hosted deployment, or a second authority system.

## Implementation tasks

P0 is deliberately not a child task: the live Colima persistent-substrate recovery is already tracked by #4899 and remains a hard prerequisite for any channel mutation.

1. [Freeze Channel Manifest And Operation Contract](FREEZE_CHANNEL_MANIFEST_AND_OPERATION_CONTRACT.md) — P1
2. [Build Immutable Artifact Graph](BUILD_IMMUTABLE_ARTIFACT_GRAPH.md) — P2
3. [Implement Read-Only Ordinary Boot](IMPLEMENT_READ_ONLY_ORDINARY_BOOT.md) — P3
4. [Prove Promotion-Test Receipts](PROVE_PROMOTION_TEST_RECEIPTS.md) — P4
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

## Cross-Task Invariants / Interaction Safety

`local-source` and `promotion` artifacts are disjoint identities: a local build may never be relabelled as a promotion candidate. A promotion is non-terminal until the immutable digest, schema journal, and promotion-test receipt agree; a deploy that writes a journal but fails activation records `failed_after_migration`, not PASS. A prod recovery cannot repair ambiguity by choosing a vault, image, or receipt: it fails closed. Rollback changes the runtime artifact only after compatibility proof and leaves the vault untouched. P6 may remove a legacy caller only after a later digest promotion and recovery/rollback drills prove no supported caller remains.

## Verification and acceptance

P1 is proven by the static contract test and fixture in `tests/architecture/test_startup_redesign_contract.py`. P2–P4 have strict-xfail call-site skeletons until their production entrypoints exist; an XPASS is a failure and requires converting the skeleton into a real runtime-path proof. P5 requires a live-host acceptance receipt; P6 requires soak and drill receipts. No local-source result is promotion evidence.

## Relationship to existing work

`docs/deployment/PINNED_IMAGE_CUTOVER/` remains the existing documented pinned-image/cutover capability. This directory is a contract freeze for the newer two-mode, receipt-gated design and must be reconciled with its open/closed issue set before any GitHub issue is created or any current SoT claim changes.

## Relationship to GitHub issues

Parent validation hub: #4913. The execution chain is #4914 (P1) → #4915 (P2) → #4916 (P3) → #4917 (P4) → #4918 (P5, operator-gated) → #4919 (P6). P0 recovery remains #4899 and blocks host Docker/Colima recovery and any cutover.
