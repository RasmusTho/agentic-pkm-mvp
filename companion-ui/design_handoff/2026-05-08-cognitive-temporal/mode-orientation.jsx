/* Mode 1: Orientation
   ─ user returns after interruption; reconstruct active context.
   Wireframe: document underneath, soft "re-entry" overlay floats above
   showing unresolved threads, last edits, open loops. Not a dashboard —
   a brief mist that clears when dismissed. */

function ModeOrientation_Wire() {
  return (
    <div style={{ width:880, height:560, background:'var(--bg-base)',
      display:'flex', flexDirection:'column', overflow:'hidden',
      position:'relative' }}>
      <StageTopBar surface="Orient" />

      {/* document is live underneath — slightly desaturated/dimmed */}
      <div style={{ flex:1, display:'flex', overflow:'hidden', position:'relative' }}>
        <div style={{ flex:1, padding:'28px 56px', overflow:'hidden',
          opacity:0.42, filter:'blur(0.4px)' }}>
          <DocFrontmatter />
          <DocTitle />
          <DocH level={2}>## Decision record</DocH>
          <DocPara n={3} />
          <DocH level={3}>### Network boundary</DocH>
          <DocPara n={2} />
          <DocPara n={3} dim />
        </div>

        {/* Re-entry overlay — floats centered, doesn't replace doc */}
        <div style={{ position:'absolute', top:24, left:'50%',
          transform:'translateX(-50%)', width:540,
          background:'rgba(14,24,40,0.94)',
          border:'1px solid rgba(212,168,67,0.35)',
          borderTop:'2px solid var(--accent)',
          borderRadius:4, padding:'14px 18px',
          boxShadow:'var(--shadow-float)', backdropFilter:'blur(4px)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:10 }}>
            <Pill color="var(--accent)" border="rgba(212,168,67,0.4)"
              bg="rgba(212,168,67,0.06)">re-entry</Pill>
            <span style={{ ...T.ui, fontSize:11, color:'var(--fg-2)' }}>
              You were last here <span style={{color:'var(--fg-1)'}}>3 days ago</span>
            </span>
            <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
              color:'var(--fg-3)' }}>Esc · dismiss</span>
          </div>

          {/* unresolved threads */}
          <div style={{ ...T.mono, fontSize:9, color:'var(--fg-3)',
            textTransform:'uppercase', letterSpacing:'0.1em', marginBottom:6 }}>
            Open loops · 3
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:5, marginBottom:12 }}>
            {[
              { c:'var(--amber)', t:'staged edit · ## Decision record',
                m:'awaiting your review · 2d' },
              { c:'var(--agent)', t:'unanswered prompt · "should we keep boundary X?"',
                m:'thread paused mid-turn' },
              { c:'var(--cyan)',  t:'unresolved link · [[Q1-arch]] cited but not opened',
                m:'1 source unread' },
            ].map(x => (
              <div key={x.t} style={{ display:'flex', alignItems:'center', gap:8,
                padding:'5px 8px', background:'var(--bg-raised)',
                border:'1px solid var(--border)', borderLeft:`2px solid ${x.c}`,
                borderRadius:2 }}>
                <IconDot size={5} color={x.c} />
                <span style={{ ...T.ui, fontSize:11, color:'var(--fg-1)' }}>{x.t}</span>
                <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
                  color:'var(--fg-3)' }}>{x.m}</span>
              </div>
            ))}
          </div>

          {/* last cognitive trace */}
          <div style={{ ...T.mono, fontSize:9, color:'var(--fg-3)',
            textTransform:'uppercase', letterSpacing:'0.1em', marginBottom:6 }}>
            Last trace
          </div>
          <div style={{ ...T.ui, fontSize:11, color:'var(--fg-2)',
            lineHeight:1.5, marginBottom:10, fontStyle:'italic' }}>
            “…we were comparing the runtime contract against the network
            boundary; you stopped mid-edit at line 47.”
          </div>

          <div style={{ display:'flex', gap:6 }}>
            <Btn color="var(--accent)" filled>Resume here</Btn>
            <Btn color="var(--fg-3)">Show all threads</Btn>
            <Btn color="var(--fg-3)" style={{ marginLeft:'auto' }}>Dismiss</Btn>
          </div>
        </div>

        {/* tiny gutter beacons that persist after dismissal */}
        <div style={{ position:'absolute', left:8, top:140,
          display:'flex', flexDirection:'column', gap:14 }}>
          <IconDot size={6} color="var(--amber)" glow />
          <IconDot size={6} color="var(--agent)" glow />
          <IconDot size={6} color="var(--cyan)" glow />
        </div>

        {/* annotations */}
        <Anno style={{ position:'absolute', left:14, top:108 }}>
          beacons remain<br/>after dismiss ↓
        </Anno>
        <Callout style={{ position:'absolute', right:14, top:42, maxWidth:140 }}>
          document stays loaded underneath — orientation is a mist, not a wall
        </Callout>
        <Anno style={{ position:'absolute', left:'50%', top:380,
          transform:'translateX(-50%)', textAlign:'center' }}>
          ↑ overlay self-dismisses on first click in document
        </Anno>
      </div>
    </div>
  );
}

function ModeOrientation_Spec() {
  return (
    <SpecCard color="var(--accent)" rows={[
      ['Overlay class',  'Floating re-entry card · centered, dismissible'],
      ['Density',        'High info, low chrome · 3–7 items max'],
      ['Persistence',    'Ephemeral · auto-dismiss on first interaction with document'],
      ['Provenance',     'Each loop links to its anchor (note·section·turn)'],
      ['Sources',        'Cited but unread links surface as a class of loop'],
      ['AI visibility',  'Low · Hugin authored the trace summary, attributed inline'],
      ['Spatial',        'Document remains in its last position; overlay floats above, blurs nothing'],
      ['Interruption',   'Survives reload via vault-side `orientation/last-trace.md`'],
      ['Transitions',    'Resume → Converse · Show all threads → Review · Dismiss → free reading'],
    ]} />
  );
}

window.ModeOrientation_Wire = ModeOrientation_Wire;
window.ModeOrientation_Spec = ModeOrientation_Spec;
