/* ============================================================
   Section 2 — Re-entry ergonomics
   The mist, the resumption shapes, the four questions
   ============================================================ */

/* ── 2A · Re-entry mist overlay ─────────────────────────── */
function S2_MistWire() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>

      {/* doc header */}
      <div style={{ padding:'10px 18px', borderBottom:'1px solid var(--border)',
        display:'flex', alignItems:'center', gap:10 }}>
        <Caption color="var(--fg-3)">Projects/Q2-arch.md</Caption>
        <Caption color="var(--vault)">·  resuming after 3 days</Caption>
      </div>

      {/* doc — slightly dimmed under mist */}
      <div style={{ flex:1, padding:'18px 32px', position:'relative',
        backgroundImage:
          'linear-gradient(rgba(0,212,232,0.012) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(0,212,232,0.012) 1px, transparent 1px)',
        backgroundSize:'32px 32px' }}>

        <div style={{ opacity:0.45 }}>
          <div style={{ ...TT.disp, fontSize:20, color:'var(--fg-1)',
            marginBottom:12, letterSpacing:'-0.01em' }}>Network boundary</div>
          <Lines rows={3} last="58%" h={6.5} gap={9} />
          <div style={{ height:18 }} />
          <Lines rows={4} last="40%" h={6.5} gap={9} />
        </div>

        {/* the mist itself — top gradient + center re-entry card */}
        <div style={{ position:'absolute', inset:0, pointerEvents:'none',
          background:'radial-gradient(ellipse at 50% 35%, rgba(212,168,67,0.06) 0%, transparent 55%)' }} />

        {/* re-entry card — floats over mist */}
        <div style={{ position:'absolute', top:60, left:'50%',
          transform:'translateX(-50%)', width:540,
          background:'rgba(7,11,18,0.92)',
          backdropFilter:'blur(8px)',
          border:'1px solid rgba(212,168,67,0.35)',
          boxShadow:'0 0 24px rgba(212,168,67,0.15), 0 8px 32px rgba(0,0,0,0.5)',
          padding:'18px 22px', borderRadius:3 }}>
          <div style={{ display:'flex', alignItems:'baseline', gap:10,
            marginBottom:4 }}>
            <span style={{ ...TT.disp, fontSize:22, color:'var(--fg-1)',
              letterSpacing:'-0.01em' }}>Where you were</span>
            <Caption color="var(--accent)">3d 4h ago</Caption>
          </div>
          <div style={{ height:1, background:'var(--accent)', opacity:0.4,
            width:42, marginBottom:14 }} />

          {/* the four questions answered as a stack */}
          {[
            { q:'doing', a:'Reconciling three sources on partition tolerance.',
              tone:'var(--accent)' },
            { q:'stopped', a:'Mid-sentence: "...does this hold when latency exceeds 200ms?"',
              tone:'var(--cyan)' },
            { q:'unresolved', a:'1 open synthesis · 2 staged edits · 1 conflicting claim.',
              tone:'var(--amber)' },
            { q:'changed', a:'Hugin found 1 related note; vault sync 2h ago.',
              tone:'var(--vault)' },
          ].map((row, i) => (
            <div key={row.q} style={{ display:'grid',
              gridTemplateColumns:'90px 1fr', gap:12, padding:'7px 0',
              borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}>
              <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                <div style={{ width:2, height:14, background:row.tone }} />
                <Caption color={row.tone} size={9}>{row.q}</Caption>
              </div>
              <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
                lineHeight:1.45 }}>{row.a}</div>
            </div>
          ))}

          <div style={{ display:'flex', gap:6, marginTop:14 }}>
            <div style={{ padding:'4px 12px', border:'1px solid var(--accent)',
              borderRadius:2, ...TT.ui, fontSize:11, color:'var(--accent)' }}>
              Resume here
            </div>
            <div style={{ padding:'4px 12px', border:'1px solid var(--border-strong)',
              borderRadius:2, ...TT.ui, fontSize:11, color:'var(--fg-2)' }}>
              Show what changed
            </div>
            <div style={{ marginLeft:'auto', padding:'4px 8px',
              ...TT.mono, fontSize:9, color:'var(--fg-3)' }}>esc · dismiss</div>
          </div>
        </div>

        {/* dismissal hint */}
        <div style={{ position:'absolute', bottom:18, left:'50%',
          transform:'translateX(-50%)', ...TT.mono, fontSize:9,
          color:'var(--fg-3)', letterSpacing:'0.1em', textTransform:'uppercase',
          opacity:0.6 }}>
          first keystroke clears the mist
        </div>
      </div>

      {/* annotations */}
      <div style={{ position:'absolute', top:50, left:14, pointerEvents:'none' }}>
        <HandNote color="var(--accent)" size={11}>document dims, never hides<br/>spatial position preserved</HandNote>
      </div>
      <div style={{ position:'absolute', top:50, right:14, pointerEvents:'none',
        textAlign:'right' }}>
        <HandNote color="var(--accent)" size={11}>card surfaces once<br/>then dissolves on action</HandNote>
      </div>
    </div>
  );
}

/* ── 2B · The four questions, formalized ────────────────── */
function S2_FourQuestions() {
  const qs = [
    { q:'What was I doing?',
      a:'Reconstructed from edit pulses + last query + active selection. One sentence summary, never analytical.',
      tone:'var(--accent)',
      shape:'one line · summary · always present' },
    { q:'Where did momentum stop?',
      a:'Cursor position + last 30s of edits expressed as a quoted fragment. Resume button jumps to exact caret.',
      tone:'var(--cyan)',
      shape:'verbatim quote · jumpable' },
    { q:'What remains unresolved?',
      a:'Open loops + staged proposals + tension halos. Counted, not enumerated. Click expands to inline list.',
      tone:'var(--amber)',
      shape:'counts only · expandable' },
    { q:'What changed since last engagement?',
      a:'Vault diffs touching this trajectory, agent-found context, decayed items. Diff summary, never timeline.',
      tone:'var(--vault)',
      shape:'delta only · never since-zero' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:8 }}>
      <ABHead tone="var(--accent)" sub="re-entry ergonomics">
        Four questions, four shapes
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55, marginBottom:6 }}>
        The mist card answers exactly four questions. No more. The shape of
        each answer is fixed — not negotiable per session.
      </div>
      {qs.map((row, i) => (
        <div key={row.q} style={{ padding:'10px 0',
          borderTop: i === 0 ? '1px solid var(--border)' : '1px solid var(--border)' }}>
          <div style={{ display:'flex', alignItems:'baseline', gap:10,
            marginBottom:4 }}>
            <div style={{ width:2, alignSelf:'stretch', background:row.tone }} />
            <span style={{ ...TT.disp, fontSize:14, color:'var(--fg-1)',
              fontStyle:'italic' }}>"{row.q}"</span>
          </div>
          <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
            lineHeight:1.5, marginLeft:12, marginBottom:4 }}>{row.a}</div>
          <div style={{ marginLeft:12 }}>
            <Caption color={row.tone}>shape · {row.shape}</Caption>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── 2C · Re-entry latency ladder ──────────────────────── */
function S2_LatencyLadder() {
  const stages = [
    { gap:'< 90s', name:'no mist',
      desc:'Active state. Cursor still pulsing. Returning is identity.',
      visual:'cursor breath' },
    { gap:'90s – 15m', name:'thread fade',
      desc:'Conversation pane fades a fraction. No card. The trajectory is implicit.',
      visual:'ambient dim' },
    { gap:'15m – 2h', name:'soft mist',
      desc:'Re-entry card appears compact: just "where you stopped" sentence + cursor jump. No metadata.',
      visual:'1-line card' },
    { gap:'2h – 3d', name:'full mist',
      desc:'All four questions answered. This is the canonical re-entry shape.',
      visual:'4-question card' },
    { gap:'3d – 14d', name:'long mist',
      desc:'Adds: what changed in vault, what Hugin learned, decayed adjacent canvas branches.',
      visual:'card + delta strip' },
    { gap:'> 14d', name:'cold start',
      desc:'No mist. The document is ambient context only. User searches.',
      visual:'no overlay' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:6 }}>
      <ABHead tone="var(--cyan)" sub="how re-entry scales with absence">
        Latency ladder
      </ABHead>
      {stages.map((s, i) => (
        <div key={s.gap} style={{ display:'grid',
          gridTemplateColumns:'90px 1fr 110px', gap:10, alignItems:'flex-start',
          padding:'8px 0',
          borderTop: i === 0 ? '1px solid var(--border)' : '1px solid var(--border)' }}>
          <Caption color="var(--cyan)">{s.gap}</Caption>
          <div>
            <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
              fontWeight:500, marginBottom:2 }}>{s.name}</div>
            <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
              lineHeight:1.45 }}>{s.desc}</div>
          </div>
          <Caption color="var(--fg-3)" size={8.5}>{s.visual}</Caption>
        </div>
      ))}
    </div>
  );
}

window.S2_MistWire = S2_MistWire;
window.S2_FourQuestions = S2_FourQuestions;
window.S2_LatencyLadder = S2_LatencyLadder;
