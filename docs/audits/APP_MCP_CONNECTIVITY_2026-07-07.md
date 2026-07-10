State: Advisory audit snapshot, 2026-07-07. App inventory taken from the operator's MacBook and mac mini on the audit date; MCP-ecosystem claims verified by web research the same day (the MCP ecosystem moves fast — re-verify before building). Owner ruled D1 2026-07-10 (§4): self-host Karakeep on the mac mini as the read-later/highlights/Mimer-ingestion source, keep Raindrop.io as the bookmark layer with its official MCP adopted (both, not either/or). Owner ruled D2 2026-07-10 (§4): Todoist for personal/household tasks (spouse is Android, ruling out Apple Reminders as the shared surface), Bring! for the shared grocery list specifically, work stays on Microsoft's tools untouched, deferred behind the not-yet-built Mimer work-satellite. Subordinate to `docs/DOCS_INDEX.md` and owner contracts; owner docs win on disagreement.
Doc role: Reference (audit snapshot)
Authority: Evidence-based inventory of the operator's applications and their MCP (Model Context Protocol) connectivity status, with adopt/build/switch/drop verdicts and a roadmap handoff. Advisory only — app-switch decisions are the owner's; build items enter the backlog only through the normal feature-breakdown/issue path.

# App & MCP Connectivity Inventory — 2026-07-07

Charter: inventory the operator's apps and programs, determine which already have MCP servers
(official or community), which would need a custom MCP built, which should be replaced by an
MCP-friendlier alternative, and which new apps are worth adopting — then hand the result to
`docs/ROADMAP.md` as a bounded external-connectivity line.

## 1. Scope and method

- **Machines scanned:** MacBook (`/Applications`, `~/Applications`, Homebrew, System apps) and the
  mac mini (`/Applications`, Homebrew) via SSH. The mac mini adds Microsoft Office, Outlook,
  OneNote, Trello, Termius, Jump Desktop over the MacBook set.
- **Not scanned:** the iPhone. iOS-only apps (and the Omi wearable app) need an owner pass; the
  verdicts below cover their Mac/service-side surfaces where those exist.
- **Research:** four parallel research passes over vendor docs, GitHub, and the MCP
  registry/directory ecosystem, snapshot 2026-07-07. Load-bearing claims (the official
  servers/repos that gate a verdict) were re-verified directly against GitHub/vendor pages by the
  coordinating agent; remaining claims carry source URLs and should be treated as leads.
- Utilities and games (CCleaner, CyberGhost, balenaEtcher, Raspberry Pi Imager, Amphetamine,
  Logi Options, Epic Games, Polytopia, GarageBand, iMovie, etc.) are out of scope: no agent value.

## 2. The strategic frame — three distinct MCP directions

"Which apps have MCP" is three different questions for this ecosystem. Keeping them separate is
what makes the roadmap handoff bounded:

- **Direction A — assistant connectors (adopt, no code).** Claude Desktop / Claude Code / ChatGPT
  sessions acting *for the owner* connect directly to third-party MCP servers (Home Assistant,
  Todoist, Drafts, Google Workspace, …). This is configuration, not development, and it is where
  most of the value below lands immediately.
- **Direction B — Mimer as an MCP server (build).** Today external agents reach Mimer through the
  repo-local `mimer-*` skills over HTTP (`docs/contracts/MIMER_CLIENT_CONTRACT.md`). No MCP server
  exists — `app/mcp/vault_tools.py` is internal orchestrator plumbing, not a transport. A thin MCP
  server over the existing ask / capture / retrieve / read-note / health endpoints, forwarding the
  governed receipt already returned by capture, would let every MCP client the owner uses (Claude
  apps, ChatGPT desktop, Codex) reach the vault through the governed path. MCP is explicitly not a
  current client transport under `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`; B1
  therefore requires a superseding ADR decision that ratifies MCP as an additional adapter before
  implementation. This is the single highest-leverage build item in this audit.
- **Direction C — Mimer as an MCP client (runtime consumption, later).** The runtime consuming
  external MCP servers as signal sources: Home Assistant presence/state, calendar, tasks, reading
  history as CRE context dimensions and Knowledge Acquisition Platform intake. The flagged remote
  MCP multiplex seam (`docs/ROADMAP.md :: Post-v5.6 follow-ups`) is the landing zone; the CRE
  "external connectors" deferral gets its concrete priority list from this audit.

Governance invariant (all three directions): **generic third-party MCP servers never write the
vault.** Third-party
Obsidian MCP servers exist (fragmented ecosystem, and the most common REST-API plugin had a
documented silent-overwrite data-loss bug, coddingtonbear/obsidian-local-rest-api issue #237) —
none of them may be pointed at a real vault with write access. MCP-originated writes use Mimer's
governed capture endpoint (WriteGuard + receipt). The separate owner-permitted direct-filesystem
transport remains available only under the discipline and human delegation defined by
`docs/contracts/MIMER_CLIENT_CONTRACT.md` §§2, 5–6 and ADR-0056. This is the moat, not an
inconvenience.

## 3. Inventory and verdicts

Verdict vocabulary: **adopt** (connect an existing MCP, no code) · **build** (custom work, enters
backlog via feature-breakdown) · **switch** (replace the app; owner decision) · **drop** (retire,
no replacement needed) · **keep/ignore** (fine as is, no agent surface warranted) · **later**
(viable, not now).

### 3.1 PKM core and capture

| App | MCP status | Verdict |
|---|---|---|
| Obsidian (3 vaults) | No official; community servers fragmented, write-safety bug history | **keep** — Mimer *is* the agent layer; never attach a generic vault-writing MCP (§2) |
| Drafts | **Official** vendor MCP server (`agiletortoise/drafts-mcp-server`, macOS, full CRUD+actions) | **adopt** — capture inbox becomes agent-readable |
| Apple Notes | Community only (small, embedding-search variants exist) | **later** — low value while the vault is canonical |
| Apple Journal | No API, no automation, manual export only — confirmed not integratable | **switch practice** — journal into the vault (or Drafts) if journaling should feed Mimer |
| Apple Freeform | No scripting surface found | **ignore** |
| Apple Voice Memos | Community MCP extracts Apple's own transcripts from `.m4a` (`jwulff/apple-voice-memo-mcp`) | **build-adjacent** — feeds the voice pipeline (§5 B3) |
| Omi wearable | **Official** MCP (memories/conversations/action items) + REST API + open-source platform | **adopt when worn** — strengthens Posture A in `docs/` capture-posture material; only independent wearable left (Limitless→Meta, Bee→Amazon) |

### 3.2 Read-later, bookmarks, references

| App | MCP status | Verdict |
|---|---|---|
| Pocket | **Dead** — Mozilla shut it down 2025-07-08, API included; data export window closed 2025 | **drop/uninstall** (both Macs still have it) |
| Instapaper | Alive but no official MCP; community server needs a manually-approved API key | **retired** — superseded by self-hosted Karakeep (D1 ruling, §4) |
| Raindrop.io | **Official** MCP (beta, Pro plan) + strong community server (`adeze/raindrop-mcp`) | **adopt** — bookmark layer, official MCP adopted (D1 ruling, §4) |
| Readwise Reader | **Official hosted** MCP (`mcp2.readwise.io/mcp`) + export API built for PKM ingestion | **not selected** — self-hosted Karakeep chosen instead: same ingestion value at $0 vs. $9.99+/mo, local-first (D1 ruling, §4) |
| Karakeep (self-hosted, ex-Hoarder) | No official *vendor* MCP concept needed — **the self-hosted instance ships its own MCP server plus a clean REST API** (`karakeep-app/karakeep`, 27.2k★, AGPL-3.0, pushed 2026-07-06). AI auto-tagging, full-text search, notes/images/PDFs alongside links. | **build (adopted, D1 ruling, §4)** — Docker on the mac mini; REST API feeds the Mimer ingestion worker, MCP server is a free bonus for interactive Claude access to the reading archive |
| Zotero | No official; community `54yyyu/zotero-mcp` is excellent (4.2k★, semantic search, PDF annotations, active) | **adopt** |

### 3.3 Tasks, lists, calendar, mail

| App | MCP status | Verdict |
|---|---|---|
| Microsoft To Do | No official MCP; product being absorbed into Planner; community Graph wrappers only | **retained, work-only** — untouched for now, no agent access (D2 ruling, §4; future work-satellite territory) |
| Todoist | **Official hosted** MCP (`Doist/todoist-mcp`, `ai.todoist.net/mcp`, active) — only task manager with a first-party hosted endpoint | **adopted** — personal/household task home (D2 ruling, §4); native Android + iOS solves the spouse-sharing requirement that Reminders couldn't |
| Apple Reminders | Community, healthy (`mattt/iMCP` bridge; `FradSer/mcp-server-apple-events`, EventKit-native) | **not selected as the shared hub** — no native Android app, `icloud.com` web fallback can't create/delete lists or notify; Reminders ruled out once the spouse's Android phone was factored in (D2 ruling, §4) |
| Listonic | No API at all (dev portal is their B2B agency site); reverse-engineered HA shims only | **retired** — replaced by Bring! (D2 ruling, §4) |
| Bring! | No official vendor API, but a **Platinum-quality first-party Home Assistant integration** (`miaucl/bring-api`, 63★, active, pushed 2026-07-06) surfaces lists as `todo.*` entities; agent access via HA's official `mcp_server` or the very active `homeassistant-ai/ha-mcp` (3.9k★) | **adopted** — dedicated shared grocery list (D2 ruling, §4); free, native iOS **and** Android, built for exactly this use case |
| Apple Calendar / Google Calendar | **Official** Anthropic Google Workspace connectors (Calendar full read/write); Google-managed MCP servers now GA; Fantastical has an official Mac MCP if wanted | **adopt** (connectors) |
| Gmail / Apple Mail | Anthropic connector: Gmail read + draft-only (no send, deliberate safety cap); community `taylorwilsdon/google_workspace_mcp` (2.8k★) adds real send; Apple Mail MCPs are AppleScript-fragile | **adopt** read/draft; escalate to community server only if send-from-agent is ever wanted |
| Outlook / OneNote / M365 (mac mini) | Anthropic M365 connector is read-only + business tenant; community `Softeria/ms-365-mcp-server` (820★, active) covers Graph read-write | **later** — only if M365 remains in real use |
| Trello (mac mini) | Not researched this pass | **owner input** — in real use, or uninstall? |

### 3.4 Home, media, communication

| App | MCP status | Verdict |
|---|---|---|
| Home Assistant | **Official first-party** `mcp_server` integration (HA 2025.2+, Assist-API scope) **and** the most active community server in this entire audit (`homeassistant-ai/ha-mcp`, 3.9k★, 85+ tools incl. todo lists, automations) | **adopt now** — also the aggregation hub for Bring!, Bambu, Kodi, presence (Direction C's richest signal source) |
| Spotify | No official; maintained community servers exist (`marcelmarais/spotify-mcp-server`); Web API trivial to wrap | **adopt (community)** / later |
| Kodi | No credible MCP, but first-class stable JSON-RPC API | **build (trivial)** if media control from agents is wanted — or route via HA's Kodi integration |
| VLC / SVT Play / Apple TV+Music+Podcasts | Nothing usable or nothing at all; Apple Podcasts library is a local sqlite | **ignore** (delegate media playback to Kodi/HA where needed) |
| Discord | **Anthropic-official plugin** (claude-plugins-official) + community servers | **adopt on demand** |
| Zoom | **Official** Claude connector (GA 2026-04): meeting summaries, transcripts, scheduling | **adopt on demand** |
| Microsoft Teams | Anthropic M365 connector (read-only, business tenant) | **ignore** personally |

### 3.5 Making, creative, finance, infra

| App | MCP status | Verdict |
|---|---|---|
| Autodesk Fusion | **Official, two servers**: in-product Fusion MCP (local port, reads/modifies live design) + cloud Fusion Data MCP; Claude Desktop connector in directory | **adopt** for CAD sessions |
| Affinity Designer/Photo/Publisher | **Official** "Affinity AI connection for Claude" (April 2026, beta, script-generation based) | **adopt (beta)** |
| Adobe CC | Illustrator beta has built-in MCP; Express MCP GA; no Photoshop official | **ignore** unless Illustrator use grows |
| draw.io | **Official** `jgraph/drawio-mcp` (4.7k★): MCP app + Claude Code plugin, native .drawio | **adopt** — immediately useful for Builder System diagrams |
| BambuStudio / OrcaSlicer / Bambu printer | No official (vendor actively hostile to third-party access, 2025-2026 lockdown); community MCPs work via LAN Developer Mode; **best path: `greghesp/ha-bambulab` (2.2k★) → HA MCP** | **adopt via HA** for status; avoid building on Bambu's surfaces directly (breakage risk) |
| LightBurn | No API (years-old open feature request); undocumented UDP listener only | **keep as burner** — pattern: agent produces SVG, LightBurn burns it; no integration built |
| Avanza | No public API; community MCP is market-data-only; portfolio access = fragile reverse-engineered TOTP lib, ToS-grey | **ignore for now** — and keep order placement out of agent reach permanently |
| Tailscale | Community servers fine (`HexSleeves/tailscale-mcp`, active); REST API trivial | **later** — ops nicety, not a need |
| Grammarly | No API (developer SDK shut down 2024); company rebranded to Superhuman; only browser-automation hacks | **drop** — a Claude proofreading pass replaces it at zero integration cost |
| Apple Photos | Community read-only via `osxphotos` | **later** — media-artifact intake is a KAP question first |
| Apple Health | No Mac API; accepted pattern = Health Auto Export (iOS) pushing JSON to a LAN endpoint + community MCPs over the export | **later** — natural CRE context signal once Direction C lands |
| ChatGPT / Claude / Codex desktop apps | These are the MCP **clients** | Direction B's audience — they all get vault access the day the Mimer MCP server exists |

Ecosystem signal worth recording: Safari Technology Preview 247 (July 2026) ships an MCP server,
and Apple archived-then-superseded community bridges keep churning — do not invest in building
Apple-app bridges that the vendor or an active community project will ship first.

## 4. Owner decisions (switch forks)

**D1 — Read-later consolidation — RESOLVED 2026-07-10.** Problem: three overlapping read-later
tools; Pocket is dead, Instapaper is agent-hostile (gatekept API key, no official MCP), Raindrop
is healthy but bookmark-shaped rather than reading/highlight-shaped. Re-framed against the actual
goal (material flows into Mimer via ingestion, not "best consumer reading app"): MCP-protocol
presence on the vendor side is irrelevant to a custom ingestion worker, which only needs a stable
free API to poll. That reframing changes the answer from the SaaS pick in the first pass.
- **Ruling:** self-host **Karakeep** (`karakeep-app/karakeep`, ex-Hoarder) on the mac mini via
  Docker for reading + highlights + AI tagging + full-text search — $0, local-first, own REST API
  for the ingestion worker plus a self-hosted MCP server as a bonus for interactive Claude access.
  **Raindrop.io is kept, not replaced** — it stays the bookmark-archive layer with its official MCP
  adopted (Direction A), a separate concern from Karakeep's reading/highlight/ingestion role.
  Instapaper and Pocket are both retired.
- *Superseded alternative:* Readwise Reader (official hosted MCP, $9.99+/mo) — same ingestion value
  achievable at $0 with Karakeep once the requirement was correctly scoped to "free API for our own
  ingest worker," not "best hosted reading UX."
- *Superseded alternative:* Wallabag (self-hosted, MIT, mature REST API, Pocket-compatible import) —
  a credible fallback if Karakeep's AI-tagging direction proves unwanted; not chosen, kept as a
  named alternative in case Karakeep self-hosting is later abandoned.
- Consequence: no new subscription; a new self-hosted Docker service to operate (backup/update
  posture as for any mac mini service); the read-later/highlight surface and the bookmark surface
  now live in two systems by design, not one, each doing the job it is actually shaped for.

**D2 — Task home — RESOLVED 2026-07-10.** Problem: tasks are split across Microsoft To Do (being
absorbed into Planner, no first-party agent surface) + Apple Reminders + Listonic (no API at all).
The owner added binding constraints beyond a simple tool pick: must work well on the Apple device
set, must work at a Microsoft-heavy job where the work computer may block new installs/connectors,
and must support sharing a list with his spouse — who has **Android, not iPhone**. That last fact
eliminated Apple Reminders as the shared-list surface: Reminders has no native Android app, and
the `icloud.com` web fallback cannot create/delete lists, move items, or send notifications — a
visibly degraded experience for a co-owner of the list, not a real option.
- **Ruling — split by sphere, not by app:**
  - **Work stays on Microsoft's tools, untouched.** Zero new install/IT risk, team visibility
    preserved, no agent (personal or otherwise) touches the work account today. This is not a
    permanent exclusion — it is staged behind the not-yet-built Mimer work-satellite (§ below),
    which would eventually bridge Microsoft Graph/To Do/Planner through its own, isolated LLM. See
    `docs/plans/PROTOCOL_SATELLITE_SYNC.md` and `docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md`
    for the existing (Spec/planned, not implemented) satellite architecture this defers to;
    `InstanceSettings.role: Literal["master", "satellite"]` already exists in the settings schema
    (`app/settings/models.py:366`) and local satellite role-gating already shipped (#1869/#1935/
    #2185/#2220) — only cross-instance sync (the piece that would carry this) remains unbuilt.
  - **Todoist** for general personal/household tasks — official hosted MCP (`Doist/todoist-mcp`),
    native apps on **both** iOS and Android so neither spouse gets a degraded experience, free tier
    allows 5 collaborators per shared project (spouse needs no paid account), ~$60/yr for the
    owner's Pro tier, web client needs no install if ever wanted on the work machine.
  - **Bring!** for the shared grocery list specifically, not folded into Todoist — free, native on
    both platforms, purpose-built for exactly this (real-time shared list, store-aisle sorting),
    agent-accessible via Home Assistant (`miaucl/bring-api` backing a Platinum-quality first-party
    HA integration, exposed to agents via HA's official `mcp_server` or the more capable
    `homeassistant-ai/ha-mcp`). Chosen over a plain Todoist "Groceries" project because the owner
    confirmed the grocery-specific UX is worth a second app.
  - Microsoft To Do and Listonic are both retired for the personal/household sphere.
- *Open flag, unverified:* whether Bring!'s store-level offer integration covers Swedish chains is
  still unconfirmed (DACH-market signal only) — the ruling stands regardless since shared-list
  UX/cross-platform parity, not store offers, was the deciding factor.

## 5. Build list (ranked) — and explicit non-builds

Build items are advisory here; they enter the backlog through feature-breakdown with their own
specs. Ranked by leverage:

- **B1 — Mimer MCP server (Direction B).** First ratify MCP as an additional client adapter by
  superseding ADR-0056's explicit deferral, then build a thin MCP transport over the existing
  `ask`, governed `capture`, `retrieve`/search, read-note, and health endpoints. Capture returns
  its governed receipt in the same response; a separate receipt read-back endpoint is neither
  shipped nor part of this item. The server preserves the authority envelope the `mimer-*` skills
  and `docs/contracts/MIMER_CLIENT_CONTRACT.md` already encode without claiming MCP is currently a
  contracted transport. Every MCP client the owner touches becomes a governed vault client.
  Nothing else in this audit multiplies value like this item.
- **B2 — Karakeep self-host (D1 ruling, decided not speculative).** Docker deployment on the mac
  mini (`karakeep-app/karakeep`, AGPL-3.0, $0); a scheduled ingest job (`app/ingest/`-adjacent)
  pulls saved links/notes/highlights via its REST API and writes candidates into the vault through
  Mimer's governed capture path — same shape as B1's ingestion pattern, no MCP transport required
  for this leg since it is Mimer's own worker doing the pulling, not an interactive MCP client.
  Karakeep's bundled MCP server is a free bonus for ad hoc Claude access to the reading archive
  directly (Direction A), independent of the ingestion job.
- **B3 — Swedish-first voice capture pipeline.** Watched-folder / endpoint on the mac mini running
  KB-Whisper (National Library of Sweden fine-tune; ~47% WER reduction vs whisper-large-v3 on
  Swedish) or Parakeet-MLX, emitting markdown capture candidates into KAP intake. Sources: Voice
  Memos/Shortcuts drops, Drafts audio, later Omi. For a dyslexic operator this is the
  friction-killer; no consumer product ships this Swedish-first + local + vault-governed. (SaaS
  shortcut exists — Voicenotes has an official MCP — but it moves raw voice off-device, against
  the local-first capture posture.)
- **B4 — Direction C consumption slices.** CRE/KAP consuming external MCP signals via the existing
  flagged remote-MCP seam: HA presence/state → context dimensions; Todoist/Bring! tasks → commitment
  context (both D2-ruled, both Direction A adopt already — this slice is the runtime-consumption
  follow-on, not the connection itself). Sequenced behind B1/B2.
- **B5 (optional, trivial) — Kodi MCP** over JSON-RPC, only if media control from chat is actually
  wanted; HA's Kodi integration may make it moot.

Explicit **non-builds**: Listonic (switch instead), Grammarly (drop), SVT Play (no sanctioned
surface; delegate to Kodi addon), LightBurn (SVG handoff pattern instead), Bambu-direct
(HA route instead; vendor hostile), Avanza portfolio (fragile + ToS-grey + finance stays out of
agent hands), generic Obsidian vault MCP (**never** — §2 invariant).

## 6. Verification notes

Spot-verified live on 2026-07-07 by the coordinating agent (GitHub API / vendor pages):
`agiletortoise/drafts-mcp-server` (39★, pushed 2026-05), `Doist/todoist-mcp` (524★, 2026-07-03),
`54yyyu/zotero-mcp` (4.2k★, 2026-07-05), `mattt/iMCP` (1.5k★, 2026-05), `homeassistant-ai/ha-mcp`
(3.9k★, 2026-07-07), `Softeria/ms-365-mcp-server` (820★, 2026-06), `adeze/raindrop-mcp` (173★,
2026-03), readwise.io/mcp (200), home-assistant.io/integrations/mcp_server (200),
developer.raindrop.io MCP page (200). Research-agent-sourced claims flagged inline where the
agents themselves could not fully verify (Affinity connector transport, LightBurn UDP command set,
Zoom tool enumeration). Re-verify any claim before an implementation issue cites it.

Spot-verified live on 2026-07-10 (D1 decision support): `karakeep-app/karakeep` (27.2k★,
archived=false, license AGPL-3.0, pushed 2026-07-06); Raindrop.io REST API confirmed free-tier
accessible via non-expiring test token (120 req/min), MCP itself remains Pro-gated per
`developer.raindrop.io`; `wallabag/wallabag` confirmed MIT-licensed, free self-host, Pocket-format
import support (named alternative, not selected).

Spot-verified live on 2026-07-10 (D2 decision support): `miaucl/bring-api` (63★, archived=false,
pushed 2026-07-06); `home-assistant.io/integrations/bring/` reachable (200); Todoist free-tier
collaborator limit (5 per personal project) confirmed via `todoist.com/help` — spouse needs no
paid account for the shared project.

## 7. Roadmap handoff

`docs/ROADMAP.md :: External-connectivity (MCP) sequencing` now carries the bounded forward line:
Direction A adoption is operator configuration (no backlog) and now includes both D2-ruled
connections (Todoist, Bring! via Home Assistant); Direction B (B1 Mimer MCP server, B2 Karakeep
self-host per the D1 ruling) is the build line pending feature-breakdown; Direction C stays
deferred behind B1/B2. Both owner decisions (D1, D2) are now resolved; the only forward-looking
open thread from this audit is the Mimer work-satellite (own LLM, staged, unimplemented) named
under D2's ruling. This audit is the evidence base; it decides nothing by itself beyond the D1/D2
rulings the owner already made.
