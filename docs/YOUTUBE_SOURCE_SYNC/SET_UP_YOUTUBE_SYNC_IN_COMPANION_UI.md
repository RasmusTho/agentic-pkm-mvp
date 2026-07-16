---
name: Set Up YouTube Sync in Companion UI
description: Guided setup flow (connect → pick inbox → choose sources → Takeout → preview/confirm) and a live status card with Sync now / Pause / Reconnect / Change inbox / Disconnect, rendering cold/connected/degraded/paused/offline truthfully.
task_id: YSS-11
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Reason codes"
parent_capability: YouTube Source Sync
prerequisites: [YSS-02, YSS-05, YSS-06, YSS-09]
depends_on: [BIND_YOUTUBE_ACCOUNT_WITH_OAUTH.md, DISCOVER_PLAYLIST_ITEMS_CONTINUOUSLY.md, SCHEDULE_AND_OPERATE_CONTINUOUS_SYNC.md, SURFACE_SYNC_HEALTH_STATUS_AND_RECEIPTS.md]
can_parallelize_with: []
---

# Set Up YouTube Sync in Companion UI

## Purpose

The owner is not a CLI user day-to-day. Connecting YouTube, choosing the inbox, and understanding
sync state must be a guided visual flow — selection by clicking, never by typing IDs or paths —
with degraded states that explain themselves.

## What This Task Does

1. **API endpoints** (FastAPI, `app/api/routes/companion.py` namespace, pydantic response models
   mirroring the core dataclasses, redaction-safe):
   `GET /api/companion/youtube/status` (YSS-09 slice + setup-progress projection);
   `POST /api/companion/youtube/auth/start` (device flow: returns `verification_url_complete` +
   `user_code`), `GET /api/companion/youtube/auth/poll`;
   `GET /api/companion/youtube/playlists` (user's playlists for pickers — from the API client);
   `POST /api/companion/youtube/sources` (configure: set-inbox swap, enable/disable, liked
   toggle, add public playlist, intervals, policy);
   `POST /api/companion/youtube/takeout` (import from an operator-picked path);
   `POST /api/companion/youtube/backfill/plan` + `/execute` (YSS-08 gate verbatim);
   `POST /api/companion/youtube/sync-now` | `/pause` | `/resume`;
   `POST /api/companion/youtube/disconnect`.
2. **Settings-drawer section** `_youtube_section()` in
   `companion-ui/…/workspace/settings_drawer.py`, registered in `SETTINGS_SECTIONS`, marked
   `data-authority="server-write"` (the vault-section precedent): renders the **setup flow** when
   unconfigured and the **status card** when configured, as server-rendered fragments refetched
   after every write (never client-optimistic).
3. **Setup flow states** (each a pure-render function over a plain projection dict):
   - *cold*: one-paragraph explanation of what connecting does (read-only scope, what gets
     created, that nothing is promoted without review) + Connect button;
   - *connecting*: the device-flow link/code rendered large (clickable
     `verification_url_complete`; the code is display-redundant, not required typing);
   - *pick inbox*: the user's playlists as a clickable list; suggests creating "Mimer Inbox" in
     YouTube if no candidate exists (suggested name only — binding is by playlist ID, INV-YSS-9);
   - *choose sources*: owned playlists multi-select, Liked Videos toggle, explicit
     public-playlist add; **Watch Later and Watch History shown as not connectable** with the
     one-line reason (official API does not expose them);
   - *subscriptions*: Takeout import offer with the conservative default policy stated;
   - *preview*: the YSS-08 plan receipt (sources, discovered counts, estimated work,
     new-items-only vs historical choice) + explicit confirm; historical backfill requires the
     distinct armed confirmation;
   - *done*: hands over to the status card.
4. **Status card:** connected account (no tokens ever), per-source rows (title, kind, last sync,
   next due, queue contribution, degraded reason via the calm-degraded copy module), global
   state chip — `cold / connected / degraded / paused / offline` — where *offline* derives from
   `runner_offline` staleness (never "up to date" when stale, INV-YSS-4); queue depth + quota;
   actions **Sync now, Pause/Resume, Reconnect, Change inbox, Disconnect** (disconnect confirm
   states that acquired notes are kept).
5. **Degraded copy:** every contract reason code gets a `_BLOCK_GATE_COPY`-style entry (what
   happened + what would fix it) through `calm_degraded.py`; unknown codes fail closed to the
   generic degraded line.

## Concretely

`render_youtube_section(projection: dict) -> str` is pure and HTML-escaped; tests assert
substrings per state (`data-testid="youtube-setup-cold"`, `data-state="degraded"`,
`data-reason="auth_revoked"`, …). The JS controller only POSTs and refetches the fragment — the
server projection is the single truth.

## Why This Matters

This surface is the product promise: connect once, save from your phone, trust the state chip.
A UI that shows "up to date" while the runner is dead, leaks a token, or lets a click start a
4,000-item backfill without preview would betray exactly the trust the capability exists to build.

## Acceptance Criteria

- [ ] Each setup state and the status card render correctly from fixture projections: cold,
      connecting, pick-inbox, choose-sources, subscriptions, preview, connected, degraded (per
      reason code), paused, offline.
      Verify: `tests/companion_ui/test_youtube_sync_section.py::test_all_states_render_from_projections`
- [ ] Watch Later / Watch History appear as not-connectable with the explanation; no control can
      submit them.
      Verify: `tests/companion_ui/test_youtube_sync_section.py::test_watch_later_history_shown_unsupported`
- [ ] The offline chip derives from staleness — a stale projection can never render "up to date".
      Verify: `tests/companion_ui/test_youtube_sync_section.py::test_offline_derived_never_up_to_date_when_stale`
- [ ] Backfill execute is unreachable in markup without a rendered plan id confirm; historical
      requires the distinct armed step.
      Verify: `tests/companion_ui/test_youtube_sync_section.py::test_backfill_confirm_gates_in_markup`
- [ ] No token or secret-shaped value appears in any rendered fragment or API response for any
      state (sentinel scan across fixtures).
      Verify: `tests/companion_ui/test_youtube_sync_section.py::test_no_secret_in_markup_or_responses`
- [ ] Every endpoint enforces the same core-layer gates (inbox swap atomicity, unsupported
      refusal, lease-guarded sync-now) — production route wiring asserted, not handlers in
      isolation.
      Verify: `tests/api/test_companion_youtube_routes.py::test_routes_wired_to_core_gates`
- [ ] Disconnect flow states artifacts are kept, calls the YSS-02 disconnect, and the section
      returns to cold with reconnect offered.
      Verify: `tests/companion_ui/test_youtube_sync_section.py::test_disconnect_preserves_artifacts_copy_and_state`

## How to Verify (Pre-Merge)

- `pytest -q tests/companion_ui/test_youtube_sync_section.py tests/api/test_companion_youtube_routes.py`
- `pytest -q -m "not pg"` (companion routes + UI are hot-path; full default suite)
- `ruff check app tests && mypy app`

## Out of Scope

Browser-harness JS tests beyond what static-render assertions cannot cover (add only if the
fragment-refetch controller needs one, per the `_browser.py` convention), History/Search surfaces,
any promotion/triage UI (the candidate review surface is the vault note itself, unchanged).

## Restart / Durability Posture

The section is a stateless projection of server truth; nothing UI-side survives or needs to
survive restart. Mid-setup restarts resume from the durable step (binding exists → pick-inbox;
sources exist → status card) — the flow re-derives its position from server state, the user never
re-enters data already saved.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Reason codes / Settings model`
- `docs/COMPANION_UI_PRODUCT_SPEC.md` (authority boundaries), `docs/UI_UX_DESIGN_BLUEPRINT.md`
- Parent-closure handoff: this is the final child — its PR posts the capability validation
  receipt on the parent feature issue and updates `PARENT_FEATURE_ISSUE.md` + `README.md` state
  lines per the feature-breakdown closure rules.

## Related GitHub Issues

One issue. TCD hint: Sonnet / high — many render states over fixed projections; the risk is
truthfulness of state derivation, covered by the fixture matrix.
