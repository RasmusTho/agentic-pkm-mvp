State: Design-of-record (owner working artifact, 2026-07-05; committed to the hub 2026-07-06 as the surface B1 is verified against). Advisory until CES/ADR enactment; the topology-C decision it recommends is ratified in ADR-0049 §4 and ADR-0050. Body preserved as authored; only this header and the restored title line frame it.
Doc role: Reference (design-of-record for the Bifrost native apps)
Authority: Describes the intended native-app topology and platform footprint (one shell, two bounded clients). It is the design B1 (#3023) is verified against. It does NOT decide vault-write consistency — that is ADR-0053 (interim) and #3114 (full model before B2). Owner docs and ADRs win on any conflict.
Owner: Architecture / product (Rasmus)

# Yggdrasil native apps — topology & platform decision

Answers two owner questions raised after the wearable-sensor study: **(1) do we start iOS/iPadOS app
design now?** and **(2) do Mimer (the companion/reader) and Heimdal (the sensor) share one app or not?**
This extends the Heimdal UI/UX thread into a **native-app design track**. Design-only; nothing built.

The governing rules from the rest of this thread still hold and constrain every option below:
- **Markdown holds the record; the app is a lens.** Any app reads/writes the **same vault `.md`**, never a
  private store. Delete the app → lose nothing.
- **Client over contracts, never a merger.** Heimdal and Mimer are **sibling constituents** (SoS,
  replaceable subsystems). An app is a *client* over each constituent's contract, not a place where their
  logic blends.

---

## 1. The decision: one shell, two bounded clients (splittable)

**Recommendation:** a **single app shell ("Yggdrasil")** that hosts **two clearly-bounded internal
clients** — a Heimdal (capture) client and a Mimer (knowledge) client — each binding *only* to its own
constituent's contract, both over the same vault. Architected so the capture client can be **split into its
own app later without a rewrite** (a repackaging, not a re-architecture).

This is deliberately **neither** extreme:

| Option | What it is | Why not (as the day-one choice) |
|---|---|---|
| **A · Two separate apps** from day one | Heimdal.app + Mimer.app, separate icons | Splits the capture→review loop; two icons = cognitive load for one human; not technically required (Otter/Granola are single apps doing background capture **and** rich review). |
| **B · One merged app** | Capture + knowledge blended in one codebase/UX | Violates *sibling-constituents / client-over-contracts*; loses replaceability; concentrates App-Store always-on-mic risk across the whole product. |
| **C · One shell, two bounded clients ✅** | One icon; two internal clients each over its own contract; splittable later | Keeps one-icon simplicity **and** the constituent boundary. Best fit for a single human without giving up the SoS stance. |

**Consequence of C:** the boundary is real *inside* the app (two clients, two contracts), so if we later
need two apps, it's a packaging change. We get the ergonomics of one app now and keep the exit.

### Split triggers (when C becomes A)
Split the capture client into its own app **only** if:
1. **App Store review** on always-on microphone / background audio threatens the whole app's approval, or
2. **Capture's background/battery behavior destabilizes the reader** (a daemon misbehaving shouldn't take
   down your daily knowledge app), or
3. A **third-party capture device** (e.g. the Omi pendant's own companion) makes a standalone Heimdal app
   the natural home.

Until a trigger fires, one shell is simpler for one human.

---

## 2. Platform footprint — the two clients differ

The clients do **not** share a platform footprint, which is exactly why iPadOS needs its own design.

| Client | iPhone | iPadOS | Apple Watch | Obsidian (desktop/mobile) | Character |
|---|---|---|---|---|---|
| **Heimdal** — capture (J0), consent (JC), device health (JD) | **primary** | — *(you don't sense with an iPad)* | **yes** — one-tap record + haptic capture status | the `.md` record is always there | background **daemon**: thin, mostly invisible, permission-heavy (mic, location) |
| **Mimer** — chat (J2/J4), interest map (J3), attention (J6), entity confirm (JE), watch-list + filters + settings (J1/J5/J7) | **on-the-go review** | **primary canvas** | — | full editing on the vault | foreground **reader/thinker**: rich, interactive |

**iPadOS is not a big iPhone.** It is the home of the "thinking" surfaces and earns a dedicated design pass:
- **Multi-column** layout: source/list · item · inspector — the review feed and its context at once.
- **Side-by-side entity confirmation (JE)** — the score-banded candidate compare is cramped on a phone and
  excellent on a tablet; this is the single biggest iPad win.
- **Pencil + keyboard**: annotate an ingested item, correct an attribution, drag a snippet into a note.
- **Drag-drop into the vault**: promote/curate an episode straight into a note.

**Apple Watch** is a Heimdal surface only: start a memo, feel a haptic when capture pauses/resumes
(the study's known interruption cases), glance at "still capturing?". No Mimer reading on the wrist.

---

## 3. What the shell actually shares vs isolates

**Shared shell (thin host):** app icon, auth/identity, **vault selection** (the existing no-manual-paths
visual pick), the **`.md` renderer** (both clients render the same notes), the design system, and global
settings. One place to sign in and pick a vault.

**Isolated per client:** each client's contract binding, permissions, and lifecycle. The Heimdal client
owns mic/location/background-audio + the on-device ASR pipeline + sensor adapters (`HeimdalSensor`); the
Mimer client owns query/review/promote. They **communicate only through the vault + the published-event
seam**, never by reaching into each other — same boundary as the backend constituents.

> Net: from the *user's* view it's one app with a capture side and a knowledge side. From the
> *architecture's* view it's two clients that happen to share a shell — which is what keeps markdown-first
> and client-over-contracts honest, and keeps the split option open.

---

## 4. Relationship to Obsidian (markdown-first still holds)

The native apps do **not** replace Obsidian; they are additional lenses over the same vault. Obsidian stays
the full-power editor of the record; the Mimer app is the ergonomic reader/steerer; the Heimdal app is the
capture/consent/device utility. Anyone could run the whole system from Obsidian + the notes alone — the apps
just make the hot paths (capture, review, steer, confirm) nicer. **No journey becomes app-only.**

---

## 5. Recommended sequencing (design track, advisory)

1. **Confirm topology C** (owner) — one shell, two bounded clients, splittable. *Everything below assumes it.*
2. **Shell + Mimer-iPhone** wireframes — the daily driver; reuses the 12 journeys already mocked.
3. **Mimer-iPad** wireframes — the multi-column canvas + side-by-side JE (the real net-new design).
4. **Heimdal-iPhone + Watch** wireframes — capture (J0), consent (JC), device health (JD); thin by design.
5. Fold results into the Claude Design pass (the CD prompt now includes this track).

**Held until step 1 is confirmed:** detailed per-screen iPhone/iPad layouts — building screens on an
unconfirmed one-vs-two split is wasted work.

---

## 6. SBS reconciliation

| Claim | Reconciliation | Routing |
|---|---|---|
| One shell / two bounded clients, splittable (§1) | `extend` — a client topology within the SoS/constituent model | owner confirm → CES/ADR at enactment |
| Platform split; iPad-first Mimer canvas (§2) | `extend` — new design surface | none (design-only) |
| Apps as lenses over the same vault; Obsidian retained (§4) | `conform` — markdown-first + client-over-contracts | none |
| A future standalone Heimdal app (split trigger) | `reshape` — of the one-shell topology | owner decision at the trigger |
