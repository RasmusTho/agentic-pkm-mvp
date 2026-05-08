/* ============================================================
   Section 4 — Cognitive tension
   Visualizing unresolvedness, conflict, dormant pressure
   ============================================================ */

/* ── 4A · Tension topology ──────────────────────────────── */
function S4_Topology() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:8 }}>
      <ABHead tone="var(--amber)" sub="four shapes of unresolvedness">
        Tension topology
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55, marginBottom:4 }}>
        Tension is not a number. It has a shape. The shape determines the
        visual.
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14,
        marginTop:6 }}>
        {/* loop */}
        <div style={{ padding:'12px 14px',
          background:'rgba(212,168,67,0.04)',
          border:'1px solid rgba(212,168,67,0.25)',
          borderLeft:'2px solid var(--accent)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <TensionHalo size={32} level={0.55} color="var(--accent)" />
            <div>
              <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
                fontWeight:500 }}>Open loop</div>
              <Caption color="var(--accent)">single thread · unfinished</Caption>
            </div>
          </div>
          <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
            lineHeight:1.5, marginTop:8 }}>
            One question waits for an answer. Linear shape: trajectory dotted
            line, gold dot at the open end.
          </div>
        </div>
        {/* conflict */}
        <div style={{ padding:'12px 14px',
          background:'rgba(240,144,48,0.04)',
          border:'1px solid rgba(240,144,48,0.25)',
          borderLeft:'2px solid var(--amber)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <svg width="32" height="32" viewBox="0 0 32 32">
              <line x1="6" y1="10" x2="26" y2="22" stroke="var(--amber)"
                strokeWidth="1.5" />
              <line x1="6" y1="22" x2="26" y2="10" stroke="var(--amber)"
                strokeWidth="1.5" />
              <circle cx="6" cy="10" r="2" fill="var(--amber)" />
              <circle cx="26" cy="22" r="2" fill="var(--amber)" />
              <circle cx="6" cy="22" r="2" fill="var(--amber)" />
              <circle cx="26" cy="10" r="2" fill="var(--amber)" />
            </svg>
            <div>
              <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
                fontWeight:500 }}>Conflict</div>
              <Caption color="var(--amber)">two interpretations · refused merge</Caption>
            </div>
          </div>
          <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
            lineHeight:1.5, marginTop:8 }}>
            Sources or claims disagree. X shape. Amber break in the draft, both
            sides preserved with provenance.
          </div>
        </div>
        {/* incomplete synthesis */}
        <div style={{ padding:'12px 14px',
          background:'rgba(57,232,125,0.04)',
          border:'1px solid rgba(57,232,125,0.25)',
          borderLeft:'2px solid var(--vault)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <svg width="32" height="32" viewBox="0 0 32 32">
              <circle cx="8" cy="10" r="2" fill="var(--vault)" />
              <circle cx="20" cy="8" r="2" fill="var(--vault)" />
              <circle cx="14" cy="22" r="2" fill="var(--vault)" />
              <line x1="8" y1="10" x2="14" y2="22" stroke="var(--vault)"
                strokeWidth="1" opacity="0.6" />
              <line x1="20" y1="8" x2="14" y2="22" stroke="var(--vault)"
                strokeWidth="1" opacity="0.6" />
              <line x1="8" y1="10" x2="20" y2="8" stroke="var(--vault)"
                strokeWidth="1" opacity="0.3" strokeDasharray="2 2" />
            </svg>
            <div>
              <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
                fontWeight:500 }}>Incomplete synthesis</div>
              <Caption color="var(--vault)">three nodes · one unbridged</Caption>
            </div>
          </div>
          <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
            lineHeight:1.5, marginTop:8 }}>
            Sources gathered, draft started, one connection still missing.
            Triangle with a dashed edge. Provenance flecks show progress.
          </div>
        </div>
        {/* dormant pressure */}
        <div style={{ padding:'12px 14px',
          background:'rgba(74,158,255,0.04)',
          border:'1px solid rgba(74,158,255,0.25)',
          borderLeft:'2px solid var(--agent)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <svg width="32" height="32" viewBox="0 0 32 32">
              <circle cx="16" cy="16" r="3" fill="var(--agent)" />
              <circle cx="16" cy="16" r="7" fill="none" stroke="var(--agent)"
                strokeWidth="0.8" opacity="0.4" />
              <circle cx="16" cy="16" r="11" fill="none" stroke="var(--agent)"
                strokeWidth="0.5" opacity="0.25" strokeDasharray="2 3" />
              <circle cx="16" cy="16" r="14" fill="none" stroke="var(--agent)"
                strokeWidth="0.4" opacity="0.15" strokeDasharray="1 4" />
            </svg>
            <div>
              <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
                fontWeight:500 }}>Dormant pressure</div>
              <Caption color="var(--agent)">conceptual mass · unattended</Caption>
            </div>
          </div>
          <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
            lineHeight:1.5, marginTop:8 }}>
            Cluster of related notes building up around an unaddressed theme.
            Nested rings, faint. Never alerts; surfaces only via marginalia.
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── 4B · Tension as inline visual on the document ─────── */
function S4_InlineWire() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      <div style={{ padding:'10px 18px', borderBottom:'1px solid var(--border)',
        display:'flex', alignItems:'center', gap:10 }}>
        <Caption color="var(--fg-3)">Writing/memory-essay.md</Caption>
        <Caption color="var(--amber)">·  3 unresolved · 1 conflict</Caption>
      </div>

      <div style={{ flex:1, padding:'22px 36px', position:'relative',
        backgroundImage:
          'linear-gradient(rgba(0,212,232,0.012) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(0,212,232,0.012) 1px, transparent 1px)',
        backgroundSize:'32px 32px' }}>

        <div style={{ ...TT.disp, fontSize:18, color:'var(--fg-1)',
          marginBottom:14 }}>The retention envelope</div>

        {/* paragraph w/ open loop halo around terminal "?" */}
        <div style={{ ...TT.ui, fontSize:13.5, color:'var(--fg-1)',
          lineHeight:1.65, marginBottom:14, position:'relative' }}>
          Memory does not store; it reconstructs. The interesting question is
          not what persists, but what reliably reassembles
          <span style={{ position:'relative', display:'inline-block',
            width:14, height:14, marginLeft:1, verticalAlign:'-3px' }}>
            <span style={{ position:'absolute', inset:-9 }}>
              <TensionHalo size={32} level={0.7} color="var(--accent)" />
            </span>
            <span style={{ position:'absolute', inset:0,
              ...TT.disp, color:'var(--accent)', fontStyle:'italic',
              fontSize:14 }}>?</span>
          </span>
        </div>

        {/* conflict block — amber break, both sides */}
        <div style={{ ...TT.ui, fontSize:13, color:'var(--fg-1)',
          lineHeight:1.65, marginBottom:14 }}>
          Standard model holds consolidation completes within hours.
        </div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 28px 1fr',
          gap:0, marginBottom:14, alignItems:'stretch' }}>
          <div style={{ padding:'10px 12px',
            background:'rgba(240,144,48,0.04)',
            borderLeft:'2px solid var(--amber)',
            borderRight:'1px dashed rgba(240,144,48,0.4)' }}>
            <Caption color="var(--amber)">Squire 1994</Caption>
            <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
              lineHeight:1.5, marginTop:4 }}>
              Hippocampal binding decays as cortical traces solidify.
              Hours, not years.
            </div>
          </div>
          <div style={{ display:'flex', alignItems:'center',
            justifyContent:'center', position:'relative' }}>
            <svg width="20" height="60" style={{ position:'absolute' }}>
              <line x1="10" y1="6" x2="10" y2="54" stroke="var(--amber)"
                strokeWidth="0.6" strokeDasharray="2 3" opacity="0.6" />
              <circle cx="10" cy="30" r="6" fill="var(--bg-base)"
                stroke="var(--amber)" strokeWidth="1" />
              <text x="10" y="33" textAnchor="middle"
                fill="var(--amber)" fontSize="9"
                style={{ fontFamily:'var(--font-mono)' }}>×</text>
            </svg>
          </div>
          <div style={{ padding:'10px 12px',
            background:'rgba(240,144,48,0.04)',
            borderRight:'2px solid var(--amber)' }}>
            <Caption color="var(--amber)">Frankland 2005</Caption>
            <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
              lineHeight:1.5, marginTop:4 }}>
              Remote memories remain hippocampus-dependent decades on.
              The timing is wrong.
            </div>
          </div>
        </div>
        <div style={{ ...TT.mono, fontSize:9, color:'var(--amber)',
          letterSpacing:'0.08em', textTransform:'uppercase',
          marginBottom:14, opacity:0.8 }}>
          ↑ refused merge · 14d unresolved · click to reconcile
        </div>

        {/* incomplete synthesis stub */}
        <div style={{ ...TT.ui, fontSize:13, color:'var(--fg-1)',
          lineHeight:1.65, position:'relative' }}>
          A workable synthesis would need to account for both —
          <span style={{ background:'rgba(57,232,125,0.06)',
            borderBottom:'1px dashed var(--vault)',
            padding:'0 3px', borderRadius:1 }}>
            possibly via dual-trace consolidation
          </span>
          — but the literature on this is still
          <span style={{ ...TT.disp, color:'var(--vault)',
            fontStyle:'italic' }}> incomplete</span>.
          <span style={{ display:'inline-block', marginLeft:6,
            verticalAlign:'middle' }}>
            <Pulse size={6} color="var(--vault)" />
          </span>
        </div>
      </div>

      {/* annotations */}
      <div style={{ position:'absolute', top:80, right:14,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--accent)" size={11}>halo around the question<br/>marks an open loop</HandNote>
      </div>
      <div style={{ position:'absolute', top:240, right:14,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--amber)" size={11}>amber break refuses to flatten<br/>the disagreement</HandNote>
      </div>
      <div style={{ position:'absolute', bottom:24, right:14,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--vault)" size={11}>pulse = synthesis<br/>still active in background</HandNote>
      </div>
    </div>
  );
}

/* ── 4C · Pressure dial — global tension at a glance ──── */
function S4_PressureDial() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--amber)" sub="never demanded · always queryable">
        Cognitive pressure
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55 }}>
        A small ambient indicator the user can <em>choose</em> to look at,
        in the corner of the document. Never appears unsolicited.
      </div>

      {/* the dial */}
      <div style={{ display:'flex', justifyContent:'center', marginTop:10 }}>
        <div style={{ position:'relative', width:200, height:200 }}>
          <svg width="200" height="200" viewBox="0 0 200 200">
            {/* faint outer ring */}
            <circle cx="100" cy="100" r="86" fill="none"
              stroke="var(--border)" strokeWidth="0.6" />
            {/* tension arcs — one per topology */}
            {[
              { color:'var(--accent)', from:0,    span:60, intensity:0.7,  label:'open loops · 3' },
              { color:'var(--amber)',  from:90,   span:38, intensity:0.85, label:'conflicts · 1' },
              { color:'var(--vault)',  from:160,  span:75, intensity:0.55, label:'incomplete · 4' },
              { color:'var(--agent)',  from:255,  span:90, intensity:0.4,  label:'dormant · 7' },
            ].map((a, i) => {
              const r = 78;
              const a1 = (a.from - 90) * Math.PI / 180;
              const a2 = (a.from + a.span - 90) * Math.PI / 180;
              const x1 = 100 + r * Math.cos(a1);
              const y1 = 100 + r * Math.sin(a1);
              const x2 = 100 + r * Math.cos(a2);
              const y2 = 100 + r * Math.sin(a2);
              const large = a.span > 180 ? 1 : 0;
              return (
                <path key={i}
                  d={`M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`}
                  fill="none" stroke={a.color}
                  strokeWidth={3 + a.intensity*3} opacity={a.intensity}
                  strokeLinecap="round" />
              );
            })}
            {/* center pulse */}
            <circle cx="100" cy="100" r="5" fill="var(--accent)" opacity="0.6" />
            <circle cx="100" cy="100" r="2.5" fill="var(--accent)" />
          </svg>
        </div>
      </div>

      {/* legend */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8,
        marginTop:6 }}>
        {[
          { c:'var(--accent)', l:'Open loops',     n:'3' },
          { c:'var(--amber)',  l:'Conflicts',      n:'1' },
          { c:'var(--vault)',  l:'Incomplete syn.', n:'4' },
          { c:'var(--agent)',  l:'Dormant mass',   n:'7' },
        ].map(r => (
          <div key={r.l} style={{ display:'flex', alignItems:'center', gap:8,
            padding:'5px 8px', background:'var(--bg-raised)',
            borderLeft:`2px solid ${r.c}` }}>
            <div style={{ width:5, height:5, borderRadius:'50%', background:r.c }} />
            <span style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)' }}>{r.l}</span>
            <span style={{ marginLeft:'auto', ...TT.mono, fontSize:11,
              color:r.c }}>{r.n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

window.S4_Topology = S4_Topology;
window.S4_InlineWire = S4_InlineWire;
window.S4_PressureDial = S4_PressureDial;
