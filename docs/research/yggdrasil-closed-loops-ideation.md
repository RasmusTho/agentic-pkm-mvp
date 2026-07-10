State: Advisory research capture. Owner-ratified ideation session 2026-07-07. Grounds the seven closed-loop capability specifications; not itself a specification.

# Yggdrasil Closed Loops — owner ideation capture (2026-07-07)

Loops 1–5 come from the gap ideation pass; loops 6–7 were added by the owner in the same session. Each has its own specification directory and parent feature issue.

## Framing

The delivered system is strong on vertical capabilities — capture (Heimdal), episodes (ERE spec), decision receipts, commitments, proactive relevance (CRE), synthesis engines (Expansion Connect + Create), TTS read-back — but the highest-leverage missing features are the **closed loops across those verticals**. A backlog and docs sweep (open/closed Issues; `docs/ROADMAP.md`; `docs/research/yggdrasil-fable5-audit.md`; `docs/MIMER_CAPABILITY_HARDENING/`; `docs/EPISODE_RESOLUTION_ENGINE/`) confirmed none of the loops below were captured as buildable work anywhere (loop 6's screen modality exists only as a `future` declaration in the ERE stream registry), while their enabling substrate is already live or already specified.

This aligns with two acknowledged-but-thin arc stages: **Reflect** (compounding learning, decision quality — `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2) and the **interface layer** for a dyslexic, Swedish-speaking owner (audio-first, push-not-pull, visual picks over typing).

## The seven loops

Each entry: owner need → what already-built substrate enables it → the uncaptured gap. Each has its own specification directory (linked) and parent feature issue.

### 1. Daily briefing — `docs/DAILY_BRIEFING/`

Need: one low-cognitive-load touchpoint per day instead of checking panels; audio-first.
Enabled by: commitments surfacing (live), CRE proactive loop (live), decision receipts (live), TTS with mixed sv/en (live), calendar stream arriving via ERE-09.
Gap: no briefing/digest artifact exists anywhere. Strategically, the briefing is the **distribution channel** the other Reflect loops deliver through. The Episode Resolution Engine deliberately excluded egress surfaces (notifications/TTS); this capability owns the other side of that seam.

### 2. Decision calibration — `docs/DECISION_CALIBRATION/`

Need: decisions are the owner's craft; the receipt log is write-only today. The compounding value of a decision journal is revisiting.
Enabled by: decision-receipt log (vault-canonical + PG projection, live on prod), companion UI card patterns, episodes as a future revisit anchor.
Gap: nothing revisits a decision, stamps an outcome, or aggregates a calibration profile.

### 3. Standing questions — `docs/STANDING_QUESTIONS/`

Need: an architect carries open questions for months; ASK answers only from what exists now; the Knowledge Acquisition Platform deliberately ends at "candidate".
Enabled by: KAP acquisitions, Heimdal captures, retrieval, the Create engine's provenance-cited answer notes.
Gap: no durable open-question entity, no evidence accumulation against it over time, no re-answering when evidence changes or contradicts the standing answer.

### 4. Episode debrief — `docs/EPISODE_DEBRIEF/`

Need: episodes (meetings, builds, trips) generate exhaust that nobody distills; the retro never happens.
Enabled by: ERE closure events (specified in `docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md` — currently drive decay only), the Create engine, commitments and decision receipts as debrief inputs.
Gap: closure → synthesis is unwired. A debrief note (decisions made, commitments taken, open loops, key captures) is the most natural first consumer of the Episode primitive beyond decay. Blocked on ERE core delivery.

### 5. Mimer voice loop — `docs/MIMER_VOICE_LOOP/`

Need: the owner is dyslexic and Swedish; every current query surface is read/type. Voice is where the disadvantage inverts.
Enabled by: Heimdal speech-to-text on the capture path (live), ASK synthesis with citations (live), mixed sv/en TTS (live). All three exist; nothing connects microphone → ASK → spoken answer.
Gap: no voice query path exists; Bifrost B3 is capture-only. The server-side voice-ask contract is client-agnostic so Bifrost mobile/Watch surfaces consume it later.

### 6. Heimdal screen stream — `docs/HEIMDAL_SCREEN_STREAM/`

Need (owner-stated 2026-07-07): "a Heimdal agent that keeps track of what I'm doing all the time I'm on my computer — screenshots plus other contexts — turned into many valuable tracks: the event motor, auto-journaling complemented by recordings, analysis of what I spend my time on."
Enabled by: Heimdal v1 observation substrate (live), the ERE stream registry contract (specified — `screen` modality is declared `future` there with nothing behind it), vision-capable derivation models, the governed capture path.
Gap: no desktop observation client, no screen→observation derivation, no time-spend analysis anywhere. This is the single richest episode-segmentation signal ("the event motor" feed) and the raw material for auto-journaling.
Owner ruling recorded: the capture-posture fork (discrete vs always-on) is decided for the **desktop screen modality**: always-on-while-at-computer is approved on the owner's single-operator machines, with pause and app/scope exclusion controls and a derive-and-discard raw posture as spec defaults. The wearable/audio side of the fork remains open.

### 7. Conversational journaling — `docs/CONVERSATIONAL_JOURNALING/`

Need (owner-stated 2026-07-07): "a bit of journaling and reflection on the day, in a conversational format with an agent as my ghost writer."
Enabled by: chat sessions (live, and already an ERE-registered stream), the Create engine, day-context sources (commitments, decision receipts, captures — later enriched by episodes and the screen stream), TTS/voice loop as the natural conversation medium for a dyslexic owner.
Gap: no reflective conversation surface, no ghost-written journal artifact. The screen stream and episode debriefs provide the automatic "what happened" skeleton; this loop adds the human reflection layer on top, agent-led (the agent asks, the owner talks, the agent drafts).

## Priority recommendation (owner-ratified)

Daily briefing first — highest value-to-effort on live substrate, and it becomes the delivery surface for loops 2–4 and 7 as they land. Conversational journaling is the evening bookend and is buildable early (chat + Create engine exist; voice and episode enrichment arrive as seams). The screen stream is the largest investment and the largest payoff — it feeds the event motor, journaling, and time-spend analysis at once — but its ERE registration leg waits on the ERE stream registry. Voice loop's mobile context arrives with Bifrost B3. Episode debrief is sequenced behind ERE delivery.

## Relationship to captured direction

These loops extend, and do not fork: Expansion Connect + Create (`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`) provides the synthesis engines the loops consume; proactivity tiers and quiet-mode govern their delivery pressure; the Settings Spine (`docs/SETTINGS_SPINE/`) owns their tunables; ERE owns segmentation and closure. Every artifact the loops produce is derived/candidate-class, provenance-cited, WriteGuard-gated, and never overwrites human-owned notes.
