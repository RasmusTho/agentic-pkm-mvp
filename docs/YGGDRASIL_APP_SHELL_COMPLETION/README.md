State: Active specification (2026-07-07). Governs the remaining bounded work to truthfully complete and close B1 (#3023) — the Yggdrasil app shell + Mimer-iPhone client. The B1 core implementation is already delivered in `RasmusTho/bifrost` (bifrost PR #2, merged `b9e9e7c`; PR #3, merged `b77cb205`); this spec covers what is still owed: contract alignment to the since-landed decisions (ADR-0055, ADR-0056/`MIMER_CLIENT_CONTRACT.md`), the documented review follow-ups, the UAT that was explicitly deferred at delivery, the cross-writer round-trip proof, and truthful closure.
Doc role: Specification directory (feature-breakdown lane)
Authority: Specifies the remaining B1 work. Subordinate to `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` (design-of-record), `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md`, `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`, and `docs/contracts/MIMER_CLIENT_CONTRACT.md`. GitHub issues created from this spec track backlog state; this spec is the source of truth for what each slice must do.
Owner: Architecture / product (Rasmus)

# Yggdrasil App Shell Completion (B1 close-out)

## Why this spec exists

B1 (#3023, Epic B #3020) shipped its core in the `RasmusTho/bifrost` constituent repo on 2026-07-06:
the Yggdrasil thin host shell (local device auth, visual vault pick — no path typing, generic `.md`
renderer/editor, shared design system) hosting the Mimer-iPhone client with one lens per A14–A19
`_heimdal/**` control-surface note, plus the platform-agnostic `Packages/YggdrasilCore` Swift package.
CI (`macos-14`, real Xcode) is green on `xcodebuild build test` + `swiftlint --strict`.

Between that delivery and now, three hub decisions landed that B1 must be reconciled against, and the
delivery itself documented explicit debts:

1. **ADR-0055** (Accepted 2026-07-07, supersedes ADR-0053, resolves #3114) decided the full
   multi-writer vault-consistency model. Its item 5 rules the **Bifrost client write mechanism**:
   coordinated file access (`NSFileCoordinator`/`UIDocument`), not plain `FileManager` I/O. The
   shipped client uses plain `String.write(atomically:)` and explicitly states it adds no
   coordination (`bifrost:Yggdrasil/README.md :: Vault write consistency`).
2. **ADR-0056 + `docs/contracts/MIMER_CLIENT_CONTRACT.md`** (2026-07-07) is now the canonical client
   contract B1 consumes. Its Bifrost-family fields require writer provenance on created notes and
   that "B1 cites ADR-0055, not a client-side invention, as its consistency posture" — the shipped
   README predates both and cites its own replicated-backend-discipline stance.
3. **Delivery debts recorded in `bifrost#1`'s closing receipt / bifrost PR #2:** the manual
   on-device/simulator UAT walkthrough is "still owed as a follow-up" (the authoring environment had
   no `Xcode.app`), and four non-blocking review follow-ups were documented but not fixed.

None of this reopens the B1 design: topology C is ratified (ADR-0049 §4, ADR-0050), the design-of-record
is committed (`docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md`), and ADR-0053's "B1 is unconstrained"
ruling (carried forward by ADR-0055) means the shipped client was *compliant at delivery time*. This
spec is the convergence-and-closure lane, not a rework lane.

## What this spec does NOT cover (already owned elsewhere)

- **Hub-side ADR-0055 enactment** — note-class table, stale-detection/conflict-staging/iCloud
  quarantine, INV-VW2: already backlogged as #3132 and #3129 (gating B2, not B1).
- **`_heimdal/**` note-shape schema publication + contract materialization (T2)** — already
  backlogged as #3131. Task specs here reference the schema risk (contract §9 F7) but do not
  duplicate that work.
- **B2 (#3024) and B3 (#3026)** — out of scope entirely.
- **Auth hardening / per-device identity** (contract §9 F2) — owner-ruled the *first hardening
  slice*, explicitly not a v1/B1 blocker. Not respecified here.

## Implementation tasks

| Task | Repo | Purpose |
|---|---|---|
| [ALIGN_VAULT_WRITES_TO_COORDINATED_FILE_ACCESS.md](ALIGN_VAULT_WRITES_TO_COORDINATED_FILE_ACCESS.md) | `RasmusTho/bifrost` | Adopt ADR-0055 item 5: coordinated file access + client-side stale-verify in `VaultFileStore` |
| [TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL.md](TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL.md) | `RasmusTho/bifrost` | Writer-provenance tagging per contract §5 / ADR-0055 item 4; README consistency stance re-anchored to ADR-0055 + the client contract |
| [FIX_FIRST_DELIVERY_REVIEW_FOLLOWUPS.md](FIX_FIRST_DELIVERY_REVIEW_FOLLOWUPS.md) | `RasmusTho/bifrost` | The four documented non-blocking review follow-ups from bifrost PR #2 |
| [PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE.md](PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE.md) | `RasmusTho/bifrost` | Mechanize the deferred UAT as XCUITest journeys in CI; scripted eyes-on device walkthrough for the operator |
| [VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL.md](VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL.md) | `RasmusTho/agentic-pkm-mvp` (hub) | Real-runtime receipt: an app-shaped `_heimdal/**` edit round-trips through the hub test channel (watcher → runtime state) |
| [RECONCILE_AND_CLOSE_B1_TRACKING.md](RECONCILE_AND_CLOSE_B1_TRACKING.md) | `RasmusTho/agentic-pkm-mvp` (hub) | Assemble the verification ledger on #3023, close it truthfully, update Epic B #3020 |

## Execution order

1. `ALIGN_VAULT_WRITES_TO_COORDINATED_FILE_ACCESS` (bifrost) — the write seam first; everything downstream verifies against the aligned client.
2. `TAG_WRITER_PROVENANCE_AND_CITE_DECIDED_CONSISTENCY_MODEL` (bifrost) — after 1 (both restate the consistency story; serializing avoids README/write-path merge collisions). May run concurrently with 3.
3. `FIX_FIRST_DELIVERY_REVIEW_FOLLOWUPS` (bifrost) — independent of 1–2 in code surface; parallel-safe.
4. `PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE` (bifrost) — after 1–3 merge, so the UAT exercises what will actually be verified/closed.
5. `VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL` (hub) — after 2 (so the receipt can show writer provenance), independent of 3–4; may run in parallel with 4.
6. `RECONCILE_AND_CLOSE_B1_TRACKING` (hub) — strictly last; blocked on receipts from 4 and 5.

## Cross-Task Invariants / Interaction Safety

Tasks 1–3 touch the same client write path; tasks 4–6 consume its outcomes as receipts. The seams:

- **INV-B1C-1 — No silent loss of human content.** After task 1, every whole-file write of a vault
  note from the client goes through coordinated access with a client-side stale re-check; a
  concurrent change observed between read and write is re-read and re-applied, never overwritten from
  a stale copy. Until ADR-0055's hub-side enactment (#3132) lands, this is discipline that shrinks
  the collision window (contract §6, stated honestly) — no task in this spec may *claim* collisions
  are eliminated.
- **INV-B1C-2 — Provenance never gates a write.** Task 2's provenance tagging is best-effort
  attribution (contract §5: advisory to the runtime, binding on clients). A provenance failure must
  not block or fail a user write; it degrades to an untagged write plus a client-side log line.
- **INV-B1C-3 — Markdown-first survives every task.** No task introduces app-only capability or a
  client-local store of meaning. If task 1's coordination work ever needs a client-side cache (e.g.
  content hashes for stale-checks), that cache is rebuildable and never authoritative (contract §3
  invariant 3).
- **INV-B1C-4 — Closure is terminal only on receipts.** Task 6 may close #3023 only when the UAT
  receipt (task 4) and the round-trip receipt (task 5) both exist on #3023. Partial-failure path: if
  task 4's on-device pass stalls (operator availability) while 1–3 and 5 are done, #3023 stays open
  with the ledger showing exactly the one outstanding receipt — the tracking issue is the memory, not
  an agent's session. If task 5 finds the round-trip broken (e.g. watcher does not ingest the app's
  edit), that is a **bug intake** (`bug-to-issue`) against the hub ingest path, and task 6 remains
  blocked; it is not absorbed into this spec.
- **INV-B1C-5 — One writer story, told once.** Tasks 1 and 2 both edit
  `bifrost:Yggdrasil/README.md`'s consistency section. Task 1 changes the mechanism; task 2 owns the
  final narrative (cite ADR-0055 + contract). If task 2 lands first for any reason, task 1 must not
  regress the citation back to the old self-invented stance.

## Capability acceptance criteria

B1 (#3023) can be closed when all of the following hold:

- [ ] The bifrost client writes vault notes via coordinated file access with client-side
  stale-verify (task 1 merged; bifrost CI green).
- [ ] Client writes carry writer provenance, and the bifrost docs cite ADR-0055 + the Mimer client
  contract as the consistency posture (task 2 merged).
- [ ] The four documented review follow-ups are fixed (task 3 merged).
- [ ] The B1 acceptance journeys run as XCUITests in bifrost CI, and the operator's eyes-on device
  walkthrough receipt is posted to #3023 (task 4).
- [ ] A test-channel round-trip receipt (app-shaped `_heimdal/**` edit → watcher ingest → runtime
  state) is posted to #3023 (task 5).
- [ ] #3023 is closed with the assembled verification ledger and Epic B #3020 reflects B1 as
  delivered (task 6).

## Relationship to GitHub issues

- **Parent / validation hub:** #3023 (`task: B1 — Yggdrasil app shell + Mimer-iPhone client`) —
  already exists and stays the live validation hub; no new parent issue is created. Its body Verify
  pointers were repaired 2026-07-07 to the committed design-of-record.
- **Grandparent:** Epic B #3020.
- **Hub child issues** (this repo) implement `VERIFY_CONTROL_SURFACE_ROUND_TRIP_ON_TEST_CHANNEL` and
  `RECONCILE_AND_CLOSE_B1_TRACKING`.
- **Bifrost child issues** (`RasmusTho/bifrost`) implement the four bifrost tasks; each posts its
  delivery receipt back to #3023.
- Adjacent, not children: #3131 (contract materialization T2), #3132 (ADR-0055 enactment), #3129
  (INV-VW2) — they gate **B2**, not this spec.

## Verification path

Per-task `Verify:` targets are declared inline in each task file. Environment reality: the operator
laptop has no runtime deps by design — Swift verification runs in bifrost CI (`macos-14`, real
Xcode); real-URL/real-runtime verification runs on the hub **test channel** host
(`docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md :: test channel`); the only genuinely human step
is the eyes-on device walkthrough in task 4.

## Evidence surface

Validation receipts accumulate as comments on #3023 (one short receipt per merged task). Owner-doc
promotion happens once, at task 6, when the closure updates Epic B and this README's `State:` line.
