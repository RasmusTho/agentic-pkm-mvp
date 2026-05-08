/* ============================================================
   Section 6 — Attention rules + semantic hierarchy update
   The grammar that holds it all together
   ============================================================ */

/* ── 6A · Attention-preserving interaction rules ───────── */
function S6_AttentionRules() {
  const rules = [
    ['no notification', 'No badge, chime, popup, or modal ever surfaces resurfaced material. Salience is visual weight, not interruption.'],
    ['surface on dwell', 'Latent items reveal detail only when the eye lingers — hover ≥1.2s or cursor proximity. No click required to know what something is.'],
    ['dim, never hide',  'Mist, decay, and overlays reduce contrast. Nothing in the trajectory layer ever hides document content.'],
    ['anchor preservation', 'Mode and overlay changes never alter scroll, cursor, or selection. Re-entry lands you at the same caret.'],
    ['reversibility',    'Every overlay closes with esc. No state survives that the user did not author or apply.'],
    ['idempotent surfacing', 'Tension halos and resurfacing marks pulse at most once per session entry. They do not re-attract attention they already gave.'],
    ['ambient over analytical', 'Default presentation is shape, color, weight. Numbers and timelines surface only when explicitly queried.'],
    ['no since-zero', 'Diffs and deltas always frame "since last engagement" or "since X". Never since the document\'s creation.'],
    ['proposal duality', 'Anything shown in the chat appears identically in the document with the same actions. Nothing exists chat-only.'],
    ['agent voice = one of many', 'Hugin\'s contributions are visually distinct (agent blue) but never structurally privileged over user trace.'],
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column' }}>
      <ABHead tone="var(--accent)" sub="invariants · all temporal patterns">
        Attention rules
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55, marginBottom:8 }}>
        Ten invariants that preserve low attentional load across every
        temporal pattern in this document.
      </div>
      <div style={{ flex:1, overflow:'auto' }}>
        {rules.map(([k,v], i) => (
          <div key={k} style={{ padding:'8px 0',
            borderTop:'1px solid var(--border)' }}>
            <Caption color="var(--accent)">{k}</Caption>
            <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
              lineHeight:1.5, marginTop:3 }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── 6B · Semantic overlay hierarchy update ────────────── */
function S6_OverlayHierarchy() {
  const layers = [
    { z:0, name:'Document surface',
      what:'Markdown body. The cognitive anchor. Never altered by overlays.',
      tone:'var(--fg-1)' },
    { z:1, name:'Trajectory layer',
      what:'Cursor pulse, momentum trail, edit pulses. Active state only.',
      tone:'var(--cyan)' },
    { z:2, name:'Marginalia field',
      what:'Right-edge dots: salience-sized, recency-faded. Resurfacing ambient.',
      tone:'var(--vault)' },
    { z:3, name:'Tension layer',
      what:'Halos, amber breaks, dormant pressure rings. Inline only.',
      tone:'var(--amber)' },
    { z:4, name:'Provenance flecks',
      what:'Source links per paragraph. Hover-only detail.',
      tone:'var(--vault)' },
    { z:5, name:'Re-entry mist',
      what:'Session-start gradient + four-question card. Self-dismisses.',
      tone:'var(--accent)' },
    { z:6, name:'Diff lens / genealogy',
      what:'On demand. Inline highlights or stacked revisions. esc closes.',
      tone:'var(--accent)' },
    { z:7, name:'Conversation rail',
      what:'Hugin thread. Anchored to passages. Collapsible to 28px.',
      tone:'var(--agent)' },
    { z:8, name:'Governance dock',
      what:'Bottom strip during review. Walks staged proposals.',
      tone:'var(--amber)' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:8 }}>
      <ABHead tone="var(--cyan)" sub="z-order · what may overlap what">
        Semantic overlay hierarchy
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55, marginBottom:4 }}>
        The full stack with temporal layers added. Layers above can dim
        layers below, never replace them.
      </div>
      <div style={{ flex:1, overflow:'auto' }}>
        {layers.map((l, i) => (
          <div key={l.name} style={{ display:'grid',
            gridTemplateColumns:'40px 170px 1fr', gap:10,
            alignItems:'flex-start', padding:'8px 0',
            borderTop:'1px solid var(--border)' }}>
            <Caption color={l.tone} size={9.5}>z{l.z}</Caption>
            <div>
              <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
                fontWeight:500 }}>{l.name}</div>
              <div style={{ width:24, height:2, background:l.tone,
                marginTop:3, opacity:0.5 }} />
            </div>
            <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
              lineHeight:1.45 }}>{l.what}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── 6C · Composition flow — interrupt → resume → resolve ─ */
function S6_CompositionFlow() {
  const steps = [
    { t:'T0',     label:'active editing',
      tone:'var(--cyan)',
      detail:'cursor present · trajectory live · open loop forming' },
    { t:'T0+5m',  label:'user steps away',
      tone:'var(--fg-3)',
      detail:'snapshot written · cursor + selection + open loops captured' },
    { t:'+15m',   label:'thread fade',
      tone:'var(--fg-3)',
      detail:'conversation pane dims slightly · no card yet' },
    { t:'+3d',    label:'return',
      tone:'var(--accent)',
      detail:'mist appears · 4 questions answered · esc clears' },
    { t:'+3d',    label:'resume here',
      tone:'var(--cyan)',
      detail:'cursor jumps to last caret · momentum trail visible' },
    { t:'+3d 5m', label:'tension resolves',
      tone:'var(--vault)',
      detail:'open loop closes · halo dissolves · genealogy stamps it' },
    { t:'+3d 7m', label:'paragraph stable',
      tone:'var(--vault)',
      detail:'staged → applied · receipt logged · marginalia recomputes' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--accent)" sub="one trace · seven moments">
        End-to-end flow
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55, marginBottom:4 }}>
        The full life of one open loop, from interruption to resolution. Each
        step uses only the temporal patterns defined above.
      </div>
      <div style={{ flex:1, position:'relative', paddingLeft:24 }}>
        {/* spine */}
        <div style={{ position:'absolute', left:7, top:6, bottom:6,
          width:1, background:'var(--border-strong)' }} />
        {steps.map((s, i) => (
          <div key={i} style={{ position:'relative', padding:'8px 0',
            display:'grid', gridTemplateColumns:'70px 1fr', gap:12 }}>
            <div style={{ position:'absolute', left:-21, top:11,
              width:11, height:11, borderRadius:'50%',
              background:s.tone, border:`2px solid var(--bg-base)`,
              boxShadow:`0 0 6px ${s.tone}` }} />
            <Caption color={s.tone}>{s.t}</Caption>
            <div>
              <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
                fontWeight:500 }}>{s.label}</div>
              <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
                lineHeight:1.45, marginTop:2 }}>{s.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── 6D · Premise card ─────────────────────────────────── */
function S0_Premise() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'22px 24px', display:'flex', flexDirection:'column', gap:10 }}>
      <div style={{ ...TT.disp, fontSize:24, color:'var(--fg-1)',
        letterSpacing:'-0.02em', lineHeight:1.15 }}>
        Continuity of thought, across time.
      </div>
      <Caption color="var(--accent)">temporal cognition · interruption recovery</Caption>
      <div style={{ height:1, background:'var(--border)', margin:'6px 0' }} />
      <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
        lineHeight:1.6 }}>
        The companion remembers <em>how you were thinking</em>, not just what
        you wrote. When you return, the document is the anchor — but the
        trajectory, the open loops, the unresolved tension, and the genealogy
        of every paragraph are quietly within reach.
      </div>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55 }}>
        Five concerns, one grammar:
      </div>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:5,
        marginTop:2 }}>
        {[
          { c:'var(--accent)', n:'Interrupted trajectories' },
          { c:'var(--cyan)',   n:'Re-entry ergonomics' },
          { c:'var(--vault)',  n:'Temporal resurfacing' },
          { c:'var(--amber)',  n:'Cognitive tension' },
          { c:'var(--accent)', n:'Temporal provenance' },
          { c:'var(--cyan)',   n:'Attention rules' },
        ].map(m => (
          <div key={m.n} style={{ display:'flex', alignItems:'center',
            gap:6, padding:'4px 8px', background:'var(--bg-raised)',
            borderLeft:`2px solid ${m.c}`, borderRadius:1 }}>
            <div style={{ width:5, height:5, borderRadius:'50%',
              background:m.c, boxShadow:`0 0 4px ${m.c}` }} />
            <span style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)' }}>{m.n}</span>
          </div>
        ))}
      </div>
      <div style={{ flex:1 }} />
      <div style={{ ...TT.mono, fontSize:9, color:'var(--fg-3)',
        letterSpacing:'0.08em', textTransform:'uppercase' }}>
        the goal is not task management.<br/>
        the goal is preserving continuity of thought.
      </div>
    </div>
  );
}

window.S6_AttentionRules = S6_AttentionRules;
window.S6_OverlayHierarchy = S6_OverlayHierarchy;
window.S6_CompositionFlow = S6_CompositionFlow;
window.S0_Premise = S0_Premise;
