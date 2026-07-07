State: Decided posture (owner ruling 2026-07-07, recorded on #3173). Governs how Bifrost app builds reach the operator's physical devices until the revisit trigger fires.
Doc role: Reference (deployment posture + operator runbook for the Bifrost native apps)
Authority: Decides the distribution mechanism only. Build/test gates stay owned by bifrost CI (`bifrost:.github/workflows/ci.yml`); backend channel promotion stays owned by `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`. Owner docs and ADRs win on any conflict.
Owner: Architecture / product (Rasmus)

# Bifrost app deployment posture — free-provisioning manual sideload

## The decision

**Builds reach devices via manual Xcode sideload with free provisioning (Apple "Personal Team").**
No Apple Developer Program membership is purchased. This was decided on #3173 (2026-07-07) with the
explicit constraint "not willing to pay the 99 USD/yr"; under that constraint the alternatives are
not merely inconvenient, they are unavailable:

- **TestFlight** distribution requires the paid Apple Developer Program.
- **Ad-hoc `.ipa` export** (CI-signed artifact, side-loaded later) also requires the paid program —
  ad-hoc distribution profiles do not exist for personal teams.

So the free tier has exactly one shape, and this doc makes it a documented, repeatable runbook
instead of tribal knowledge.

## What agents own vs what the operator owns

| Step | Owner | Mechanism |
|---|---|---|
| Build + unit/UI test | agents | bifrost CI (`macos-14`, simulator, `CODE_SIGNING_ALLOWED=NO`) — the merge gate |
| Simulator UAT journeys | agents | XCUITest in CI (see `docs/YGGDRASIL_APP_SHELL_COMPLETION/PROVE_UAT_JOURNEYS_IN_SIMULATOR_AND_ON_DEVICE.md`) |
| Device install | **operator** | Xcode → run on device with Personal Team signing (runbook below) |
| Eyes-on device walkthrough receipts | **operator** | posted to the tracking issue per the relevant spec |

Agent ceiling under this posture: **build + test in simulator.** Device deployment is a deliberate
human step, accepted as proportionate for a single-operator system (one human, own devices, no
distribution to anyone else).

## Operator runbook (per install)

1. On the Mac with `Xcode.app`: pull the bifrost commit to install (normally `origin/main` after the
   relevant PR merged; CI must be green on that SHA).
2. Open `Yggdrasil/Yggdrasil.xcodeproj`, select the app target → Signing & Capabilities →
   Team = your Apple-ID Personal Team, `Automatically manage signing` on. Xcode generates the free
   provisioning profile.
3. Connect the device (or use Wi-Fi debugging once trusted), select it as the run destination, Run.
4. First install per device: on the device, Settings → General → VPN & Device Management → trust the
   developer certificate.
5. Watch app (when B3 lands): installs via the paired iPhone automatically when the Watch target is
   included in the run scheme.

## Known constraints of the free tier (accepted)

- **7-day expiry:** free-provisioned apps stop launching after 7 days; re-running from Xcode
  re-signs. Practical cadence: re-install roughly weekly, or when picking up a new build — whichever
  comes first.
- **3-app limit** per free Apple ID on device (commonly cited; verify against current Apple policy
  when it starts to matter). Topology C (one shell app) spends one slot; a future
  split (capture app as its own bundle, per `APP_TOPOLOGY_AND_PLATFORMS.md :: Split triggers`) would
  spend a second.
- **No paid-tier entitlements:** no iCloud key-value/CloudKit containers, no push notifications, no
  App Groups guarantees. Spec authors: do not design Bifrost features against these. Background
  audio, WatchConnectivity, security-scoped file access, and local notifications are all available
  on the free tier and are what B3 designs against. (On-device ASR is deliberately NOT in that
  list — the B3 client captures and delivers audio only; ASR stays hub-side per
  `docs/HEIMDAL_CAPTURE_CLIENT/README.md :: The ASR ruling`.)
- **No App Store review:** nothing ships through review under this posture, so App-Store-review risk
  (the always-on-mic concern in the split triggers) is dormant until the posture changes.

## Revisit trigger

Re-open #3173's question (one comment on Epic B #3020 suffices) if any of these fire:

- the 7-day re-sign churn becomes a real annoyance in practice (the owner says so),
- a second person needs the app on their device, or
- the owner buys the Apple Developer Program for any other reason — at which point the TestFlight
  pipeline (CI archive → App Store Connect API upload → OTA install) becomes the natural upgrade and
  should be specified as its own bounded capability.
