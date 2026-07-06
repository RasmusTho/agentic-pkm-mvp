State: Draft (advisory feasibility / decision-support, 2026-07-06). Transport-layer feasibility study for Heimdal voice capture on the Apple ecosystem (Apple Watch Ultra + iPhone + Mac Mini + iCloud), feeding the blocked owner decision on Bifrost **B3** ([#3026](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3026) — Heimdal-iPhone capture client + Watch). Advisory; enacts nothing. No runtime behavior, no schemas, no shipped-reality claims.
Doc role: Feasibility / decision-support study (transport mechanism only)
Authority: Subordinate to `OWNER_DECISIONS.md` (reserved calls stay reserved — this doc surfaces R-EXTERNAL, it does not take it), `FABLE_COMPANION.md` (the v1 vertical design it extends), and ADR-0049/0050/0051. Authoritative for nothing shipped; every mechanism below is either already-delivered reality (cited to #3025) or a *proposed* transport option for owner review. Web citations are external evidence gathered 2026-07-06, not Apple contracts.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: strategic
Review cadence: event-driven (owner decision on B3 #3026)
Source of truth: this doc + `FABLE_COMPANION.md` (§7.1, §9-h), `OWNER_DECISIONS.md` (R-EXTERNAL), ADR-0049, ADR-0051, and the cited external sources.

# Heimdal capture transport — Apple-ecosystem feasibility (B3 decision support)

## Purpose and scope

B3 ([#3026](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3026)) — the native Heimdal capture client for iPhone + Apple Watch — is `agent:blocked` / `agent:needs-human`. It is blocked partly for want of **empirical transport feasibility**: *how does audio get from the wrist to Heimdal's raw seam on the Mac Mini, reliably, with minimal interaction?* This doc supplies that evidence so the owner decision on B3 rests on verified platform constraints rather than assumption.

**This doc decides nothing.** It lays out three transport models, a decision table, the one governance escalation they imply, and two cheap gating experiments.

### Working within already-settled decisions (do not relitigate)

This study stays strictly inside decisions already taken. It does **not** reopen them:

- **Capture posture — A (discrete) for v1, B (always-on/ambient) deferred.** Owner-decided; see `FABLE_COMPANION.md` §9 and `CAPABILITY_CHARTER.md`. Everything here is Posture-A transport.
- **Clean folder, not DB-scraping.** v1 lands audio via *"the existing iOS Voice Memos app + a Shortcut into an iCloud-synced folder — no custom capture app"* and explicitly does **not** scrape Voice Memos' TCC-protected store (`FABLE_COMPANION.md` line 23, §Vertical build step 4, delivered as A6 [#3025](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3025)). This feasibility work confirms that choice was correct and asks only *what transport comes next*.
- **iCloud in the v1 pre-seam chain is owner-acknowledged.** `FABLE_COMPANION.md` §7.1 / §9-h accept Apple/iCloud inside the v1 trust boundary with delete-after-confirmed-ingest, and **already name** "direct device→host transfer (e.g. Tailscale-local shortcut upload)" as a v2 hardening path. Models 2–3 below are the concrete feasibility of that named-but-unanalyzed item — an `extend`, not a new proposal.

## Bottom line

The Apple ecosystem **can** serve as Heimdal's capture layer. Two findings frame everything:

1. **Capture is already frictionless.** The Apple Watch Ultra Action Button natively maps to a voice memo (press once to start, again to stop) or to a Shortcut, native since watchOS 11 ([Apple Support — Action button](https://support.apple.com/guide/watch/apda005904ef/watchos)). Nothing needs building to make one-press capture work.
2. **The risk is entirely on the ingestion/transport side, and it does not move with transport choice.** iCloud sync is non-deterministic by Apple's own documentation — files can be listed as *dataless placeholders* that require an implicit (and silently-failing) network fetch before they are readable ([Apple File Management — iCloud](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/iCloud/iCloud.html)). A **cellular Watch removes the Watch→iPhone availability dependency** ([Apple Support — Voice Memos on Watch](https://support.apple.com/guide/watch/voice-memos-apd441786282/watchos)) but does **not** make sync deterministic — that is a server-layer property, unchanged by how bytes reach the network.

Consequently: **live streaming *from the Watch* is the least-supported path on Apple's platform and must not be the foundation.** The durable floor is capture-to-local-file (Model 1, already shipped). Lower latency, if wanted, belongs at the **iPhone tier** (Model 2), not the Watch.

## The three transport models

### Model 1 — Watch → local file → iCloud sync **(v1, SHIPPED as #3025)**

The Action Button (or Shortcut) records a memo; a Shortcut saves it to an iCloud-synced folder; the Mac Mini adapter watches that folder, admits under consent grant, encrypts the raw bytes, and deletes the source after confirmed ingest (`FABLE_COMPANION.md` §Vertical build; `docs/EVENTS.md :: Heimdal raw-evidence store`).

- **Phoneless:** yes on a cellular Watch — Voice Memos sync over cellular without the iPhone nearby, given iCloud Voice Memos enabled + same Apple ID ([Apple Support](https://support.apple.com/guide/watch/voice-memos-apd441786282/watchos), [AppleToolbox](https://appletoolbox.com/voice-memos-not-syncing-from-your-apple-watch-how-to-fix/)).
- **Cost:** latency + iCloud non-determinism. The Mac side must **confirm-by-materialization** (check `NSURLUbiquitousItemDownloadingStatusKey`, call `startDownloadingUbiquitousItemAtURL`, verify readable before ingest), **dedup idempotently**, and **assume failures are silent** — never treat absence-of-error as success ([Apple File Management](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/iCloud/iCloud.html); [Apple `NSMetadataQuery`](https://developer.apple.com/documentation/foundation/nsmetadataquery) is the sanctioned no-poll detector for app-owned iCloud containers).
- **Verdict:** the **durable floor.** Robust, low effort, already delivered.

### Model 2 — iPhone-tier stream-first + local-file fallback **(proposed; extends §7.1 v2 hardening)**

iOS — unlike watchOS — has full background-audio support, unrestricted `Network`/`URLSession`/WebSocket, and a Tailscale client. Path: **Watch → WatchConnectivity → iPhone app → stream to the Mac Mini over the tailnet**; if the stream drops, the locally-buffered file falls back to Model 1's iCloud path.

- **Win:** low latency and iCloud *bypassed while streaming* — the observable, controllable channel (you see bytes arrive; you can NAK/retry) replaces iCloud's opaque eventually-consistent one. This is exactly the "direct device→host transfer (Tailscale-local)" hardening §7.1/§9-h already anticipated.
- **Cost:** reintroduces a **phone-present dependency**, which partly negates the reason for a cellular Watch. Streaming is therefore *opportunistic*; file-sync (Model 1) remains the phoneless fallback.
- **R-EXTERNAL:** the tailnet path stays inside the trusted LAN/overlay and does **not** trip R-EXTERNAL.

### Model 3 — Live streaming direct from the Watch **(NOT RECOMMENDED — two hard blockers)**

- **(a) No sanctioned watchOS pattern for streaming mic audio to a server.** Low-level networking on watchOS (`Network` framework, BSD sockets, WebSocket) only functions inside an active audio *session*, and that context is built for audio *playback*, not mic *upload*; the socket dies when the app suspends (~seconds after wrist-drop). Refs: [Apple TN3135 — low-level networking on watchOS](https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos), [WWDC19 s716](https://developer.apple.com/videos/play/wwdc2019/716/), [DevForums 714796](https://developer.apple.com/forums/thread/714796), [DevForums 716118](https://developer.apple.com/forums/thread/716118). `WKExtendedRuntimeSession` cannot legitimately keep such an app alive (restricted to self-care/mindfulness/PT/smart-alarm; other use risks App Review rejection — [DevForums 819449](https://developer.apple.com/forums/thread/819449)).
- **(b) The cellular Watch cannot reach the Mac Mini directly.** Tailscale does **not** run on watchOS ([Tailscale docs](https://tailscale.com/docs/install/appletv); [plappa #276](https://github.com/LeoKlaus/plappa/issues/276)), so a direct Watch→home-mini channel would require a **public ingress endpoint** — a new external surface.
- **Verdict:** highest developer effort, App-Review and OS-upgrade fragility, and it forces the R-EXTERNAL escalation below. Do not build.

### On the map but out of scope: dedicated always-on hardware (Posture B)

Pendant hardware (Omi/Bee-class, BLE → phone with background audio) *can* stream continuously — but that is **Posture B (ambient/always-on)**, owner-deferred and GDPR/third-party-consent weighted. Noted for completeness; not a v1 option.

## Decision table

| Dimension | **Model 1** Watch→file→iCloud (shipped) | **Model 2** iPhone-tier stream + file fallback | **Model 3** Watch direct stream |
|---|---|---|---|
| Status | Delivered (#3025) | Proposed (extends §7.1) | Not recommended |
| Phoneless (cellular Watch) | ✅ yes | ⚠️ fallback only (stream needs phone) | ✅ but blocked by (b) |
| Latency | ⚠️ iCloud-bound, non-deterministic | ✅ low when streaming | ✅ (if it worked) |
| Platform support | ✅ sanctioned | ✅ sanctioned (iOS) | ❌ no sanctioned pattern |
| Reaches Mac Mini | ✅ via iCloud | ✅ via tailnet | ❌ needs public ingress |
| iCloud determinism risk | inherited (mitigable Mac-side) | bypassed while streaming | bypassed |
| R-EXTERNAL escalation | no (already acknowledged §9-h) | no (tailnet, trusted) | **yes** (public ingress) |
| Dev effort | done | medium | high + fragile |
| Verdict | **Durable floor** | **Add only if latency proves insufficient** | **Do not build** |

## Governance escalation (the one owner call this surfaces)

Per `OWNER_DECISIONS.md` **R-EXTERNAL** — *"Any capture of, or data flow to, external/third-party services or people"* is external-facing and often legally binding, reserved to the owner. Mapping:

- **Model 1's** iCloud transit is already the owner-acknowledged R-EXTERNAL residual (§9-h), bounded by delete-after-ingest. No new call.
- **Model 2's** tailnet transfer stays inside the trusted overlay → **does not trip R-EXTERNAL.**
- **Model 3's** public-ingress endpoint is a **new external surface → escalates to the owner as R-EXTERNAL.** It is not a decision B3 makes internally.

## Metadata → Episode: an argument the current docs don't yet make

A raw voice memo carries almost no context — creation timestamp and duration (`FABLE_COMPANION.md` §1.3, `clock_basis: device_metadata`). The richer signals a capture app could stamp — GPS, device-of-origin, Focus state, motion, protagonist hints — are **exactly the dimensions ADR-0051 wants** for `episode_ref` (time, space, causation, goal, protagonist), and they can **only** be captured *at capture time*, by a capture app. They cannot be reconstructed Mac-side from a bare `.m4a`.

Therefore the native B3 client is justified by **Episode richness**, not just Action-Button ergonomics: a native capture app is the only point in the chain where `space`/`protagonist`/`causation` context can enter an observation. This strengthens the case for B3 beyond friction reduction and connects it to the Episode primitive (ADR-0051) and event-triggered relevance decay via episode closure.

## Two gating experiments (both cheap; #1 needs no code)

- **EXP-1 — phoneless sync latency & reliability.** Enable iCloud Voice Memos + the v1 Shortcut; put the iPhone in another room / airplane mode; record from the Watch on cellular; measure **time-to-materialize on the Mac Mini** and the **failure/stall rate** across N trials. Resolves whether **Model 1 alone** is fast and reliable enough. *No code.*
- **EXP-2 — iPhone-tier stream win.** Only if EXP-1 shows latency is a real problem: prototype Model 2's Watch→iPhone→tailnet stream and measure the latency gain against the phone-present cost. Decides whether Model 2 is worth its complexity.

**Recommendation on sequencing:** run EXP-1 first. If Model 1's phoneless latency is acceptable, **streaming may not be worth building at all** — decide on evidence, not intuition.

## Recommendation

1. **Keep the Watch as a trigger + durable-buffer device.** Model 1 is the floor and is already shipped.
2. **Add Model 2 (iPhone-tier hybrid) only if EXP-1 proves Model 1's latency insufficient.** Streaming is opportunistic; file-sync stays the phoneless fallback.
3. **Do not build Model 3.**
4. **Escalate any public-ingress streaming design to the owner as R-EXTERNAL** — it does not get decided inside B3.

## Reconciliation against existing SoT

- **Conforms to:** ADR-0049 (discrete Posture-A ingestion organ), `FABLE_COMPANION.md` line 23 / §Vertical (clean-folder capture, delivered #3025), §9-h (iCloud acknowledgment + delete-after-ingest).
- **Extends:** `FABLE_COMPANION.md` §7.1 / §9-h "direct device→host transfer (Tailscale-local shortcut upload)" — Models 2–3 add the transport feasibility detail behind that named v2 item; and ADR-0051 — adds the capture-time-metadata → `episode_ref` argument.
- **Reshapes:** nothing. No decision is reopened; no contract changes.

## Sources

External evidence gathered 2026-07-06 (adversarially verified where load-bearing). Third-party blogs are corroboration, not Apple contracts; the iCloud non-determinism claims stand on Apple's own File Management docs even where a preprint ([arXiv 2602.19433](https://arxiv.org/html/2602.19433v3), a non-peer-reviewed advocacy preprint) is cited alongside.

- Action Button / Voice Memos on Watch: [Apple Support apda005904ef](https://support.apple.com/guide/watch/apda005904ef/watchos), [apd441786282](https://support.apple.com/guide/watch/voice-memos-apd441786282/watchos)
- iCloud non-determinism / dataless files / `NSMetadataQuery`: [Apple File Management](https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/iCloud/iCloud.html), [Apple NSMetadataQuery](https://developer.apple.com/documentation/foundation/nsmetadataquery)
- Cellular-Watch Voice Memos sync: [Apple Support](https://support.apple.com/guide/watch/voice-memos-apd441786282/watchos), [AppleToolbox](https://appletoolbox.com/voice-memos-not-syncing-from-your-apple-watch-how-to-fix/)
- watchOS background upload deferral / `WKExtendedRuntimeSession`: [DevForums 819449](https://developer.apple.com/forums/thread/819449), [Apple — downloading files in the background](https://developer.apple.com/documentation/Foundation/downloading-files-in-the-background)
- watchOS low-level networking only within audio session: [Apple TN3135](https://developer.apple.com/documentation/technotes/tn3135-low-level-networking-on-watchos), [WWDC19 s716](https://developer.apple.com/videos/play/wwdc2019/716/), [DevForums 714796](https://developer.apple.com/forums/thread/714796), [DevForums 716118](https://developer.apple.com/forums/thread/716118)
- Tailscale not on watchOS: [Tailscale docs](https://tailscale.com/docs/install/appletv), [plappa #276](https://github.com/LeoKlaus/plappa/issues/276)
