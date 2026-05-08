/* ============================================================
   Section 1 — Interrupted trajectories
   How thought is preserved when the user steps away
   ============================================================ */

/* ── 1A · Trajectory preservation model ─────────────────── */
function S1_Model() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--accent)" sub="four states · one anchor">
        Trajectory states
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-2)', lineHeight:1.55,
        marginBottom:6 }}>
        Every thought-in-progress occupies one of four states. The system
        preserves all four invisibly, surfaces them only when the user looks for them.
      </div>

      {[
        { name:'Active', tone:'var(--cyan)',
          desc:'Cursor present in last 90 seconds. Living, hot.',
          mark:'cursor pulse · live caret · breath' },
        { name:'Warm', tone:'var(--accent)',
          desc:'Untouched 90s–2hr. Still in working memory. Still unfinished.',
          mark:'gold spine · open-loop chip · momentum trail' },
        { name:'Dormant', tone:'var(--vault)',
          desc:'2hr–14d quiet. Submerged but recoverable. Decay envelope.',
          mark:'faint marginalia · decay arc · tension halo if pressured' },
        { name:'Cold', tone:'var(--fg-3)',
          desc:'>14d. Vault-canonical only. Re-entry through search.',
          mark:'no surface trace · provenance only' },
      ].map((s, i) => (
        <div key={s.name} style={{ display:'grid',
          gridTemplateColumns:'82px 1fr 180px', gap:14, alignItems:'flex-start',
          padding:'9px 0',
          borderTop: i === 0 ? '1px solid var(--border)' : '1px solid var(--border)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:6 }}>
            <div style={{ width:3, height:24, background:s.tone }} />
            <div>
              <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
                fontWeight:500 }}>{s.name}</div>
              <div style={{ ...TT.mono, fontSize:8.5, color:s.tone,
                letterSpacing:'0.08em', textTransform:'uppercase' }}>state {i+1}</div>
            </div>
          </div>
          <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
            lineHeight:1.5 }}>{s.desc}</div>
          <div style={{ ...TT.mono, fontSize:9, color:'var(--fg-3)',
            letterSpacing:'0.04em', lineHeight:1.5 }}>{s.mark}</div>
        </div>
      ))}

      <div style={{ marginTop:8, padding:'8px 10px',
        background:'rgba(212,168,67,0.04)', border:'1px solid rgba(212,168,67,0.2)',
        borderLeft:'2px solid var(--accent)' }}>
        <Caption color="var(--accent)">invariant</Caption>
        <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
          lineHeight:1.5, marginTop:4 }}>
          State changes are <em>derived</em>, never declared. The user never
          marks something dormant; the system never asks. Time does the work.
        </div>
      </div>
    </div>
  );
}

/* ── 1B · What gets preserved when user steps away ──────── */
function S1_Preserved() {
  const items = [
    { k:'Cursor + selection', v:'Last caret line:col + selection range, per file.' },
    { k:'Scroll trail', v:'Last 40 viewport positions (sparse). Reveals what user lingered on.' },
    { k:'Open loops', v:'Sentences ending in question mark, "TODO", "?", or unresolved bracket. Auto-detected.' },
    { k:'Last query', v:'Most recent question to Hugin. Lives in the trajectory, not just chat history.' },
    { k:'Adjacent canvas', v:'Branches, even unsaved. Cached locally with last-touched timestamp.' },
    { k:'Staged proposals', v:'Pending review-mode blocks remain in place. Amber persists.' },
    { k:'Reading thread', v:'Sequence of notes opened in this session. Order matters for reconstruction.' },
    { k:'Tension graph', v:'Which passages had unresolved synthesis or conflicting sources.' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--cyan)" sub="continuity payload">
        What is preserved
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)', lineHeight:1.55 }}>
        Every interruption captures a small structured snapshot. Stored locally,
        keyed to the active document. Vault remains canonical; this is volatile
        cognitive scaffolding.
      </div>
      <div style={{ flex:1, display:'flex', flexDirection:'column', gap:0,
        marginTop:6 }}>
        {items.map((it, i) => (
          <div key={it.k} style={{ display:'grid',
            gridTemplateColumns:'140px 1fr', gap:12, padding:'7px 0',
            borderTop: i === 0 ? '1px solid var(--border)' : '1px solid var(--border)' }}>
            <Caption color="var(--cyan)">{it.k}</Caption>
            <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
              lineHeight:1.45 }}>{it.v}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop:6, ...TT.mono, fontSize:9, color:'var(--fg-3)',
        letterSpacing:'0.06em' }}>
        snapshot.json · ~6kb · written every 4s when dirty · purged at 30 days
      </div>
    </div>
  );
}

/* ── 1C · Wireframe: document at moment of interruption ── */
function S1_InterruptWire() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      {/* doc header */}
      <div style={{ padding:'10px 18px', borderBottom:'1px solid var(--border)',
        display:'flex', alignItems:'center', gap:10 }}>
        <Caption color="var(--fg-3)">Projects/Q2-arch.md</Caption>
        <Caption color="var(--accent)" size={9}>·  warm  ·  18m idle</Caption>
        <div style={{ marginLeft:'auto' }}>
          <Pill tone="var(--accent)">trajectory live</Pill>
        </div>
      </div>

      {/* doc body w/ persistent state */}
      <div style={{ flex:1, padding:'18px 32px', position:'relative',
        backgroundImage:
          'linear-gradient(rgba(0,212,232,0.018) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(0,212,232,0.018) 1px, transparent 1px)',
        backgroundSize:'32px 32px' }}>

        {/* ## heading */}
        <div style={{ ...TT.disp, fontSize:20, color:'var(--fg-1)',
          marginBottom:12, letterSpacing:'-0.01em' }}>Network boundary</div>
        <Lines rows={3} last="58%" h={6.5} gap={9} />

        <div style={{ height:18 }} />

        {/* paragraph w/ inline cursor + open question */}
        <div style={{ position:'relative' }}>
          <Lines rows={2} last="100%" h={6.5} gap={9} />
          <div style={{ display:'flex', alignItems:'center', gap:1, marginTop:9,
            ...TT.ui, fontSize:13, color:'var(--fg-1)', lineHeight:1.55 }}>
            <span style={{ color:'var(--fg-2)' }}>...does this hold when latency exceeds 200ms</span>
            <span style={{ ...TT.disp, color:'var(--accent)', fontSize:18,
              marginLeft:1 }}>?</span>
            <span style={{ display:'inline-block', width:1.5, height:14,
              background:'var(--cyan)', marginLeft:2,
              animation:'tcbreathe 1.4s ease infinite' }} />
          </div>
          <Caption color="var(--accent)" style={{ position:'absolute', right:-10,
            top:32 }}>open loop · captured</Caption>
        </div>

        <div style={{ height:18 }} />

        {/* trajectory bar — visible only when dormant overlay is hovered */}
        <div style={{ display:'flex', alignItems:'center', gap:10,
          padding:'8px 12px', background:'rgba(212,168,67,0.03)',
          border:'1px dashed rgba(212,168,67,0.25)', borderRadius:2 }}>
          <Caption color="var(--accent)">momentum trail</Caption>
          <TimeSpine w={360} h={22} marks={[
            { at:0.05, color:'var(--fg-3)', opacity:0.6 },
            { at:0.18, color:'var(--vault)', opacity:0.6 },
            { at:0.32, color:'var(--accent)', opacity:0.7 },
            { at:0.48, color:'var(--accent)', opacity:0.85 },
            { at:0.62, color:'var(--cyan)', opacity:0.9, ring:true },
            { at:0.78, color:'var(--accent)', opacity:1, ring:true },
            { at:0.92, color:'var(--cyan)', opacity:1, ring:true },
          ]} />
          <Caption color="var(--fg-3)">9:14 → now</Caption>
        </div>

        <div style={{ height:14 }} />

        {/* unresolved synthesis stub */}
        <div style={{ background:'rgba(57,232,125,0.03)',
          borderLeft:'2px solid var(--vault)',
          padding:'10px 12px', borderRadius:'0 2px 2px 0', position:'relative' }}>
          <Caption color="var(--vault)">synthesis · unfinished</Caption>
          <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
            marginTop:5, lineHeight:1.5 }}>
            Two sources align on consistency model; <span style={{ color:'var(--amber)' }}>
            third disagrees on partition tolerance</span> — draft paragraph
            pending reconciliation.
          </div>
          <div style={{ display:'flex', gap:6, marginTop:7 }}>
            <Pill tone="var(--vault)" filled>3 sources</Pill>
            <Pill tone="var(--amber)">1 conflict</Pill>
            <Pill tone="var(--fg-3)">draft 60%</Pill>
          </div>
        </div>
      </div>

      {/* annotations */}
      <div style={{ position:'absolute', top:62, right:14, pointerEvents:'none',
        textAlign:'right' }}>
        <HandNote color="var(--accent)" size={11}>cursor + last query<br/>persist verbatim</HandNote>
      </div>
      <div style={{ position:'absolute', bottom:88, right:14, pointerEvents:'none',
        textAlign:'right' }}>
        <HandNote color="var(--vault)" size={11}>unresolved synthesis<br/>holds shape, not flattens</HandNote>
      </div>
      <div style={{ position:'absolute', bottom:170, left:14, pointerEvents:'none' }}>
        <HandNote color="var(--accent)" size={11}>momentum trail —<br/>scroll dwell + edit pulses</HandNote>
      </div>
    </div>
  );
}

window.S1_Model = S1_Model;
window.S1_Preserved = S1_Preserved;
window.S1_InterruptWire = S1_InterruptWire;
