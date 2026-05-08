/* ============================================================
   Section 5 — Temporal provenance
   How understanding evolved · what changed · when
   ============================================================ */

/* ── 5A · The genealogy strip ──────────────────────────── */
function S5_GenealogyWire() {
  // a single paragraph's evolution over time
  const stages = [
    { at:'09 Mar', tone:'var(--fg-3)', state:'seed',
      text:'Memory does not persist; it reassembles.',
      meta:'first capture · Hugin · suggested phrasing' },
    { at:'12 Mar', tone:'var(--cyan)', state:'expanded',
      text:'Memory does not store; it reconstructs from cue and context.',
      meta:'user revision · added "from cue and context"' },
    { at:'24 Mar', tone:'var(--amber)', state:'contested',
      text:'Memory does not store; it reconstructs — though the literature disagrees on timing.',
      meta:'conflict introduced · Frankland 2005' },
    { at:'02 Apr', tone:'var(--vault)', state:'synthesized',
      text:'Memory does not store; it reconstructs. The interesting question is what reliably reassembles.',
      meta:'user reframing · resolved by elision' },
    { at:'now',    tone:'var(--accent)', state:'active',
      text:'Memory does not store; it reconstructs. The interesting question is not what persists, but what reliably reassembles?',
      meta:'open loop · question form · 2h idle' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      <div style={{ padding:'10px 18px', borderBottom:'1px solid var(--border)',
        display:'flex', alignItems:'center', gap:10 }}>
        <Caption color="var(--fg-3)">Writing/memory-essay.md  ·  ¶ 4</Caption>
        <Caption color="var(--accent)">·  genealogy</Caption>
        <div style={{ marginLeft:'auto' }}>
          <Pill tone="var(--accent)">5 revisions over 28 days</Pill>
        </div>
      </div>

      <div style={{ flex:1, padding:'22px 28px', overflow:'auto' }}>
        {/* time spine across the top */}
        <div style={{ marginBottom:18 }}>
          <Caption color="var(--fg-3)">temporal spine</Caption>
          <div style={{ marginTop:6 }}>
            <TimeSpine w={780} h={28} marks={[
              { at:0.04, color:'var(--fg-3)' },
              { at:0.22, color:'var(--cyan)' },
              { at:0.5,  color:'var(--amber)', ring:true },
              { at:0.74, color:'var(--vault)' },
              { at:0.96, color:'var(--accent)', ring:true },
            ]} />
          </div>
          <div style={{ display:'flex', justifyContent:'space-between',
            marginTop:0, paddingRight:8 }}>
            {stages.map((s,i) =>
              <Caption key={i} color={s.tone}>{s.at}</Caption>)}
          </div>
        </div>

        {/* stacked revisions */}
        <div style={{ display:'flex', flexDirection:'column', gap:0 }}>
          {stages.map((s, i) => (
            <div key={i} style={{ display:'grid',
              gridTemplateColumns:'72px 1fr 200px', gap:14,
              alignItems:'flex-start', padding:'12px 0',
              borderTop:'1px solid var(--border)' }}>
              <div>
                <div style={{ ...TT.mono, fontSize:9, color:s.tone,
                  letterSpacing:'0.08em', textTransform:'uppercase' }}>
                  {s.state}
                </div>
                <div style={{ ...TT.mono, fontSize:9, color:'var(--fg-3)',
                  marginTop:2 }}>{s.at}</div>
              </div>
              <div style={{ paddingLeft:12, borderLeft:`2px solid ${s.tone}`,
                opacity: i === stages.length-1 ? 1 : 0.7 }}>
                <div style={{ ...TT.disp, fontSize:14, color:'var(--fg-1)',
                  fontStyle:'italic', lineHeight:1.5 }}>"{s.text}"</div>
              </div>
              <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
                lineHeight:1.45 }}>{s.meta}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ position:'absolute', top:60, right:14,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--accent)" size={11}>genealogy = paragraph<br/>not document</HandNote>
      </div>
      <div style={{ position:'absolute', bottom:24, right:14,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--amber)" size={11}>note when conflict<br/>entered the trace</HandNote>
      </div>
    </div>
  );
}

/* ── 5B · Uncertainty trace ────────────────────────────── */
function S5_UncertaintyTrace() {
  // tracks confidence over time for a claim
  const w = 480, h = 110;
  const points = [
    [0.02, 0.30], [0.10, 0.45], [0.18, 0.55], [0.28, 0.40],
    [0.36, 0.25], [0.46, 0.55], [0.58, 0.70], [0.68, 0.62],
    [0.78, 0.78], [0.88, 0.72], [0.96, 0.85],
  ];
  const path = points.map(([x,y],i) =>
    `${i===0?'M':'L'}${(x*(w-20)+10).toFixed(1)} ${(h - 12 - y*(h-30)).toFixed(1)}`
  ).join(' ');
  const events = [
    { x:0.18, label:'Squire',     tone:'var(--cyan)' },
    { x:0.36, label:'Frankland',  tone:'var(--amber)' },
    { x:0.58, label:'reframing',  tone:'var(--vault)' },
    { x:0.88, label:'now',        tone:'var(--accent)' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:8 }}>
      <ABHead tone="var(--cyan)" sub="confidence over time, claim-scoped">
        Uncertainty trace
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55, marginBottom:6 }}>
        Per-claim: how sure the user has been, when sources entered, when
        rephrasings shifted the ground.
      </div>

      <div style={{ background:'var(--bg-raised)',
        border:'1px solid var(--border)', padding:'12px 8px 6px',
        borderRadius:2, marginTop:4 }}>
        <svg width={w} height={h}>
          {/* horizontal guides */}
          {[0.25, 0.5, 0.75].map(y => (
            <line key={y} x1="10" y1={h - 12 - y*(h-30)} x2={w-10}
              y2={h - 12 - y*(h-30)} stroke="var(--border)"
              strokeWidth="0.5" strokeDasharray="2 4" />
          ))}
          {/* baseline */}
          <line x1="10" y1={h-12} x2={w-10} y2={h-12}
            stroke="var(--border-strong)" strokeWidth="0.8" />
          {/* curve */}
          <path d={path} fill="none" stroke="var(--cyan)"
            strokeWidth="1.4" opacity="0.85" strokeLinecap="round" />
          {/* events */}
          {events.map((e,i) => {
            const x = e.x * (w-20) + 10;
            const idx = Math.round(e.x * (points.length-1));
            const y = h - 12 - points[idx][1] * (h - 30);
            return (
              <g key={i}>
                <line x1={x} y1="6" x2={x} y2={h-12} stroke={e.tone}
                  strokeWidth="0.5" strokeDasharray="2 3" opacity="0.5" />
                <circle cx={x} cy={y} r="3" fill={e.tone} />
                <circle cx={x} cy={y} r="6" fill="none" stroke={e.tone}
                  strokeWidth="0.6" opacity="0.4" />
              </g>
            );
          })}
          {/* labels */}
          <text x="14" y="14" fill="var(--fg-3)" fontSize="9"
            style={{ fontFamily:'var(--font-mono)',
              letterSpacing:'0.08em', textTransform:'uppercase' }}>certain</text>
          <text x="14" y={h-2} fill="var(--fg-3)" fontSize="9"
            style={{ fontFamily:'var(--font-mono)',
              letterSpacing:'0.08em', textTransform:'uppercase' }}>uncertain</text>
        </svg>
        <div style={{ display:'flex', justifyContent:'space-between',
          padding:'0 6px', marginTop:2 }}>
          {events.map(e =>
            <Caption key={e.label} color={e.tone}>{e.label}</Caption>)}
        </div>
      </div>

      <div style={{ marginTop:8, padding:'8px 10px',
        background:'var(--cyan-muted)', border:'1px solid var(--cyan-dim)',
        borderLeft:'2px solid var(--cyan)' }}>
        <Caption color="var(--cyan)">reading rule</Caption>
        <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
          lineHeight:1.5, marginTop:4 }}>
          Dips reveal where doubt entered. Lifts reveal where evidence
          consolidated. The trace is a memory of <em>how you came to think this</em>,
          not a chart of facts.
        </div>
      </div>
    </div>
  );
}

/* ── 5C · Diff lens — what changed since X ─────────────── */
function S5_DiffLens() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      <div style={{ padding:'10px 18px', borderBottom:'1px solid var(--border)',
        display:'flex', alignItems:'center', gap:10 }}>
        <Caption color="var(--fg-3)">Writing/memory-essay.md</Caption>
        <Caption color="var(--accent)">·  diff lens · since 3d ago</Caption>
        <div style={{ marginLeft:'auto', display:'flex', gap:6 }}>
          <Pill tone="var(--accent)">3d</Pill>
          <Pill tone="var(--fg-3)">7d</Pill>
          <Pill tone="var(--fg-3)">30d</Pill>
          <Pill tone="var(--fg-3)">all</Pill>
        </div>
      </div>

      <div style={{ flex:1, padding:'22px 36px', position:'relative' }}>

        <div style={{ ...TT.disp, fontSize:18, color:'var(--fg-1)',
          marginBottom:14 }}>The retention envelope</div>

        {/* paragraph w/ inline diff highlights */}
        <div style={{ ...TT.ui, fontSize:13.5, color:'var(--fg-1)',
          lineHeight:1.7, marginBottom:14 }}>
          Memory does not <span style={{
            background:'rgba(255,61,61,0.08)',
            textDecoration:'line-through',
            textDecorationColor:'var(--destructive)',
            color:'var(--fg-3)', padding:'0 2px' }}>persist</span>{' '}
          <span style={{ background:'rgba(57,232,125,0.1)',
            borderBottom:'1px solid var(--vault)',
            padding:'0 2px' }}>store</span>; it reconstructs.{' '}
          <span style={{ background:'rgba(57,232,125,0.08)',
            borderBottom:'1px solid var(--vault)',
            padding:'0 2px' }}>The interesting question is not what persists,
            but what reliably reassembles?</span>
        </div>

        <div style={{ ...TT.ui, fontSize:13, color:'var(--fg-1)',
          lineHeight:1.7, marginBottom:14, opacity:0.45 }}>
          Standard model holds consolidation completes within hours.
          Hippocampal binding decays as cortical traces solidify.
        </div>

        {/* changed elsewhere — pulled in for context */}
        <div style={{ background:'rgba(74,158,255,0.04)',
          border:'1px solid rgba(74,158,255,0.2)',
          borderLeft:'2px solid var(--agent)',
          padding:'10px 12px', marginBottom:14 }}>
          <div style={{ display:'flex', alignItems:'center', gap:6,
            marginBottom:6 }}>
            <Caption color="var(--agent)">elsewhere in vault · 1d ago</Caption>
          </div>
          <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
            lineHeight:1.5 }}>
            <span style={{ color:'var(--fg-2)' }}>Atomic notes/Reconstruction.md</span>
            {' — '}you wrote: "Reconstruction implies cue-dependence; the cue
            is the interesting object." This may relate to your open loop above.
          </div>
        </div>

        {/* delta summary */}
        <div style={{ display:'flex', gap:8, alignItems:'center',
          padding:'8px 12px', background:'var(--bg-raised)',
          border:'1px solid var(--border)', marginTop:6 }}>
          <Caption color="var(--accent)">delta · 3d</Caption>
          <span style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)' }}>
            +1 sentence
          </span>
          <span style={{ width:1, height:14, background:'var(--border-strong)' }} />
          <span style={{ ...TT.ui, fontSize:11, color:'var(--vault)' }}>
            "store" → "reconstruct"
          </span>
          <span style={{ width:1, height:14, background:'var(--border-strong)' }} />
          <span style={{ ...TT.ui, fontSize:11, color:'var(--agent)' }}>
            1 vault echo
          </span>
          <div style={{ marginLeft:'auto', ...TT.mono, fontSize:9,
            color:'var(--fg-3)' }}>esc · close lens</div>
        </div>
      </div>

      <div style={{ position:'absolute', top:80, right:14,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--accent)" size={11}>diffs inline,<br/>not in a sidebar</HandNote>
      </div>
      <div style={{ position:'absolute', bottom:90, right:14,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--agent)" size={11}>vault changes elsewhere<br/>that touch this trajectory</HandNote>
      </div>
    </div>
  );
}

window.S5_GenealogyWire = S5_GenealogyWire;
window.S5_UncertaintyTrace = S5_UncertaintyTrace;
window.S5_DiffLens = S5_DiffLens;
