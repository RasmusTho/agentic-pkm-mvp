/* ============================================================
   Section 3 — Temporal resurfacing
   Decay, salience, marginalia evolution
   ============================================================ */

/* ── 3A · The marginalia field ─────────────────────────── */
function S3_MarginaliaWire() {
  // simulated marks down the right edge of a document
  const marks = [
    { y:60,  size:7,  op:0.95, c:'var(--vault)',  label:'related note · 4d',          state:'fresh' },
    { y:108, size:5,  op:0.7,  c:'var(--vault)',  label:'echo · seen 12d ago',        state:'warm' },
    { y:162, size:9,  op:1,    c:'var(--amber)',  label:'tension — sources disagree', state:'pressured' },
    { y:228, size:4,  op:0.45, c:'var(--vault)',  label:'dormant evergreen · 41d',    state:'cold' },
    { y:284, size:6,  op:0.85, c:'var(--cyan)',   label:'returning question · 3d',    state:'recurrent' },
    { y:340, size:3,  op:0.3,  c:'var(--vault)',  label:'faint · 70d',                state:'fading' },
    { y:402, size:8,  op:0.95, c:'var(--accent)', label:'open loop · yours · 6d',     state:'self-trace' },
    { y:472, size:4,  op:0.5,  c:'var(--vault)',  label:'adjacent vault edit · 9d',   state:'warm' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      <div style={{ padding:'10px 18px', borderBottom:'1px solid var(--border)',
        display:'flex', alignItems:'center', gap:10 }}>
        <Caption color="var(--fg-3)">Writing/memory-essay.md</Caption>
        <Caption color="var(--vault)">·  marginalia field active</Caption>
        <div style={{ marginLeft:'auto' }}>
          <Pill tone="var(--vault)">8 latent marks</Pill>
        </div>
      </div>

      <div style={{ flex:1, display:'flex', position:'relative' }}>
        {/* doc body */}
        <div style={{ flex:1, padding:'24px 40px 24px 60px',
          backgroundImage:
            'linear-gradient(rgba(0,212,232,0.012) 1px, transparent 1px),' +
            'linear-gradient(90deg, rgba(0,212,232,0.012) 1px, transparent 1px)',
          backgroundSize:'32px 32px', opacity:0.85 }}>
          <div style={{ ...TT.disp, fontSize:22, color:'var(--fg-1)',
            marginBottom:14, letterSpacing:'-0.01em' }}>
            On the architecture of memory
          </div>
          <Lines rows={3} last="62%" h={6.5} gap={9} />
          <div style={{ height:14 }} />
          <Lines rows={2} last="84%" h={6.5} gap={9} />
          <div style={{ height:14 }} />
          <div style={{ ...TT.disp, fontSize:15, color:'var(--fg-2)',
            marginBottom:9 }}>The retention envelope</div>
          <Lines rows={4} last="48%" h={6.5} gap={9} />
          <div style={{ height:14 }} />
          <Lines rows={3} last="70%" h={6.5} gap={9} />
          <div style={{ height:14 }} />
          <div style={{ ...TT.disp, fontSize:15, color:'var(--fg-2)',
            marginBottom:9 }}>Decay, not deletion</div>
          <Lines rows={3} last="58%" h={6.5} gap={9} />
        </div>

        {/* the right-edge marginalia rail */}
        <div style={{ width:46, position:'relative',
          borderLeft:'1px solid var(--border)' }}>
          {marks.map((m, i) => (
            <div key={i} style={{ position:'absolute',
              top:m.y, left:'50%', transform:'translateX(-50%)',
              display:'flex', alignItems:'center' }}>
              <MargDot size={m.size} opacity={m.op} color={m.c}
                glow={m.state !== 'fading'} />
            </div>
          ))}
          {/* hover preview anchored to one dot */}
          <div style={{ position:'absolute', top:152, right:50,
            width:200, padding:'8px 10px',
            background:'rgba(7,11,18,0.94)',
            backdropFilter:'blur(6px)',
            border:'1px solid var(--amber-dim)',
            borderLeft:'2px solid var(--amber)',
            boxShadow:'0 4px 16px rgba(0,0,0,0.5)' }}>
            <Caption color="var(--amber)">tension · 2 sources disagree</Caption>
            <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
              lineHeight:1.45, marginTop:6 }}>
              "Memory consolidation timing" — Squire (1994) vs.
              Frankland (2005). Unreconciled in your draft.
            </div>
            <div style={{ display:'flex', gap:6, marginTop:8 }}>
              <Pill tone="var(--amber)" filled>open</Pill>
              <Pill tone="var(--fg-3)">14d unresolved</Pill>
            </div>
          </div>
        </div>
      </div>

      {/* annotations */}
      <div style={{ position:'absolute', top:60, right:60,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--vault)" size={11}>size = salience<br/>opacity = recency</HandNote>
      </div>
      <div style={{ position:'absolute', bottom:80, right:60,
        pointerEvents:'none', textAlign:'right' }}>
        <HandNote color="var(--vault)" size={11}>no tooltip until hover<br/>no badges, no count, no chime</HandNote>
      </div>
      <div style={{ position:'absolute', top:148, left:14,
        pointerEvents:'none' }}>
        <HandNote color="var(--amber)" size={11}>tension marks pulse<br/>once per session</HandNote>
      </div>
    </div>
  );
}

/* ── 3B · Decay envelope ──────────────────────────────── */
function S3_DecayEnvelope() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--vault)" sub="how marks fade · how tension persists">
        Decay envelope
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55 }}>
        Marginalia opacity follows a curve, not a clock. Recency, salience,
        and tension each pull on the curve differently.
      </div>

      {/* the three decay curves stacked */}
      <div style={{ marginTop:8 }}>
        {[
          { name:'Recency only', tone:'var(--vault)', highlight:0.78,
            note:'pure exponential. 50% at 7d, 10% at 30d.' },
          { name:'Salience-weighted', tone:'var(--accent)', highlight:0.55,
            note:'half-life doubles per uniqueness tier. evergreens persist.' },
          { name:'Tension-bound', tone:'var(--amber)', highlight:0.32,
            note:'no decay until resolved. unresolved synthesis stays bright.' },
        ].map((row, i) => (
          <div key={row.name} style={{ display:'grid',
            gridTemplateColumns:'140px 1fr 1fr', gap:14, padding:'10px 0',
            alignItems:'center', borderTop:'1px solid var(--border)' }}>
            <div>
              <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
                fontWeight:500 }}>{row.name}</div>
              <div style={{ ...TT.mono, fontSize:9, color:row.tone,
                letterSpacing:'0.06em', marginTop:2 }}>curve {i+1}</div>
            </div>
            <DecayArc w={140} h={36} color={row.tone}
              highlight={row.highlight} />
            <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
              lineHeight:1.45 }}>{row.note}</div>
          </div>
        ))}
      </div>

      <div style={{ marginTop:6, padding:'8px 10px',
        background:'rgba(57,232,125,0.04)', border:'1px solid rgba(57,232,125,0.2)',
        borderLeft:'2px solid var(--vault)' }}>
        <Caption color="var(--vault)">composition rule</Caption>
        <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
          lineHeight:1.5, marginTop:4 }}>
          A mark's final opacity is <code style={{ ...TT.mono,
            background:'transparent', border:'none', padding:0,
            color:'var(--fg-2)' }}>min(recency, salience) · tension_bonus</code>.
          Tension never lets a mark go fully dark while a loop is open.
        </div>
      </div>
    </div>
  );
}

/* ── 3C · Resurfacing triggers ─────────────────────────── */
function S3_Triggers() {
  const rows = [
    { trig:'Contextual proximity',
      when:'User reads a passage; vault has neighbors within k=3 hops.',
      surf:'Faint vault dot at line. Dim until eye lingers >2s.' },
    { trig:'Temporal echo',
      when:'Today\'s date matches a prior session anniversary, or recurring date frame.',
      surf:'Cyan recurrent mark. Surfaces once per matching day.' },
    { trig:'Unresolved tension',
      when:'Open loop or conflicting source persists across sessions.',
      surf:'Amber tension halo. Pulses once per session entry.' },
    { trig:'Synthesis drift',
      when:'Vault edit elsewhere contradicts a claim in current draft.',
      surf:'Amber margin mark + provenance fleck on affected paragraph.' },
    { trig:'Self-trace',
      when:'Returning to a passage the user last edited mid-thought.',
      surf:'Gold momentum trail under the paragraph for 1 session.' },
    { trig:'Decayed adjacent',
      when:'Old exploration branch touches current cursor topic.',
      surf:'Faint cyan dot in marginalia. Click reanimates branch.' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 24px', display:'flex', flexDirection:'column', gap:6 }}>
      <ABHead tone="var(--vault)" sub="non-disruptive surfacing only">
        Resurfacing triggers
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.55, marginBottom:4 }}>
        Six conditions can make a latent item surface. None of them produce
        a notification. All resolve to a visual weight on something already
        on screen.
      </div>
      {rows.map((r, i) => (
        <div key={r.trig} style={{ display:'grid',
          gridTemplateColumns:'130px 1fr 1fr', gap:12, padding:'8px 0',
          borderTop:'1px solid var(--border)' }}>
          <Caption color="var(--vault)">{r.trig}</Caption>
          <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
            lineHeight:1.45 }}>{r.when}</div>
          <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-1)',
            lineHeight:1.45 }}>{r.surf}</div>
        </div>
      ))}
    </div>
  );
}

window.S3_MarginaliaWire = S3_MarginaliaWire;
window.S3_DecayEnvelope = S3_DecayEnvelope;
window.S3_Triggers = S3_Triggers;
