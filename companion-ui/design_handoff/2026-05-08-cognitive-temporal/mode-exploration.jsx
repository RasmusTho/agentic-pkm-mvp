/* Mode 2: Exploration
   ─ divergent thinking; speculative associations; ephemeral cognition.
   Wireframe: temporary canvas blooms beside document. Branches without
   committing. Cyan-toned (signal of probe/transient). Has a soft event
   horizon — close it and ideas dissolve unless explicitly saved. */

function ModeExploration_Wire() {
  return (
    <div style={{ width:880, height:560, background:'var(--bg-base)',
      display:'flex', flexDirection:'column', overflow:'hidden',
      position:'relative' }}>
      <StageTopBar surface="Converse" />

      <div style={{ flex:1, display:'flex', overflow:'hidden' }}>
        {/* document — narrower; explore canvas takes the right half */}
        <div style={{ flex:'0 0 42%', padding:'26px 32px',
          borderRight:'1px solid var(--border)', overflow:'hidden' }}>
          <DocFrontmatter />
          <DocTitle />
          <DocH level={2}>## Decision record</DocH>
          {/* highlighted phrase — anchor of the exploration */}
          <div style={{ position:'relative', marginBottom:14 }}>
            <Lines n={3} h={7} last="62%" c="var(--border-strong)" />
            <div style={{ position:'absolute', top:6, left:0, width:'58%', height:9,
              background:'rgba(0,212,232,0.12)',
              border:'1px solid rgba(0,212,232,0.35)', borderRadius:2 }} />
          </div>
          <DocH level={3}>### Network boundary</DocH>
          <DocPara n={2} dim />
        </div>

        {/* Explore canvas — temporary, dotted edge to signal ephemerality */}
        <div style={{ flex:1, position:'relative',
          background:'rgba(0,212,232,0.025)',
          backgroundImage:'radial-gradient(rgba(0,212,232,0.18) 1px, transparent 1px)',
          backgroundSize:'12px 12px', overflow:'hidden' }}>

          {/* canvas header */}
          <div style={{ position:'absolute', top:0, left:0, right:0,
            display:'flex', alignItems:'center', gap:8, padding:'8px 12px',
            background:'rgba(7,11,18,0.7)',
            borderBottom:'1px dashed var(--cyan-dim)' }}>
            <IconBox size={10} color="var(--cyan)" />
            <span style={{ ...T.mono, fontSize:9, color:'var(--cyan)',
              textTransform:'uppercase', letterSpacing:'0.1em' }}>
              Exploration · ephemeral
            </span>
            <span style={{ ...T.mono, fontSize:9, color:'var(--fg-3)' }}>
              anchored to “runtime contract”
            </span>
            <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
              color:'var(--fg-3)' }}>5 min · auto-fade</span>
          </div>

          {/* the seed prompt — small, lower-left */}
          <div style={{ position:'absolute', left:14, top:46, width:170,
            background:'var(--bg-raised)', border:'1px solid var(--border-strong)',
            borderRadius:'4px 4px 1px 4px', padding:'7px 9px' }}>
            <Lines n={2} h={6} last="50%" c="rgba(220,232,240,0.3)" />
          </div>

          {/* three speculative branches — different angles */}
          {[
            { x:200, y:62, w:175, h:84, c:'var(--cyan)', label:'angle a · constraints',
              n:3 },
            { x:200, y:170, w:200, h:74, c:'var(--cyan)', label:'angle b · analogy',
              n:2, dashed:true },
            { x:36,  y:188, w:160, h:78, c:'var(--cyan)', label:'angle c · counter',
              n:2 },
          ].map(b => (
            <div key={b.label} style={{ position:'absolute', left:b.x, top:b.y,
              width:b.w, padding:'7px 9px',
              background:'rgba(0,30,40,0.5)',
              border:`1px ${b.dashed?'dashed':'solid'} rgba(0,212,232,0.35)`,
              borderLeft:`2px solid ${b.c}`, borderRadius:3 }}>
              <div style={{ display:'flex', alignItems:'center', gap:5, marginBottom:5 }}>
                <IconBox size={8} color={b.c} />
                <span style={{ ...T.mono, fontSize:8, color:b.c,
                  letterSpacing:'0.06em' }}>{b.label}</span>
              </div>
              <Lines n={b.n} h={5} last="55%" c="rgba(0,212,232,0.22)" />
            </div>
          ))}

          {/* faint connector lines from anchor to branches */}
          <Arrow d="M 12,40 C 80,40 100,80 195,90"
            color="rgba(0,212,232,0.4)" head={false} dashed
            style={{ left:0, top:0, right:0, bottom:0 }} />
          <Arrow d="M 12,40 C 80,40 100,180 195,200"
            color="rgba(0,212,232,0.3)" head={false} dashed
            style={{ left:0, top:0, right:0, bottom:0 }} />
          <Arrow d="M 12,40 C 30,80 60,150 100,200"
            color="rgba(0,212,232,0.25)" head={false} dashed
            style={{ left:0, top:0, right:0, bottom:0 }} />

          {/* footer — keep / dissolve */}
          <div style={{ position:'absolute', bottom:0, left:0, right:0,
            display:'flex', alignItems:'center', gap:6, padding:'7px 12px',
            background:'rgba(7,11,18,0.85)',
            borderTop:'1px dashed var(--cyan-dim)' }}>
            <span style={{ ...T.mono, fontSize:9, color:'var(--fg-3)' }}>
              3 branches · nothing persisted
            </span>
            <Btn color="var(--cyan)" style={{ marginLeft:'auto' }}>
              Promote to companion note
            </Btn>
            <Btn color="var(--fg-3)">Dissolve</Btn>
          </div>
        </div>
      </div>

      {/* annotations */}
      <Anno style={{ position:'absolute', top:50, left:340 }}>
        ← anchor highlight in doc<br/>→ canvas blooms from it
      </Anno>
      <Callout style={{ position:'absolute', right:14, top:48, maxWidth:160 }}>
        cyan = transient. nothing here is in the vault until the user promotes it.
      </Callout>
      <Anno style={{ position:'absolute', left:380, bottom:80, fontSize:11 }}>
        ↑ branches are reorderable, deletable, mergeable
      </Anno>
    </div>
  );
}

function ModeExploration_Spec() {
  return (
    <SpecCard color="var(--cyan)" rows={[
      ['Overlay class',  'Adjacent canvas · siblings to document, not modal'],
      ['Density',        'Low governance · cards float, edges dashed'],
      ['Persistence',    'Ephemeral by default · auto-fade after inactivity unless promoted'],
      ['Provenance',     'Each branch tracks origin anchor; no commit until promotion'],
      ['Sources',        'Soft surfacing · suggested links appear as ghost chips, not citations'],
      ['AI visibility',  'Mid · agent contributes branches but is one voice among the user\'s'],
      ['Spatial',        'Splits the stage horizontally; document remains anchored'],
      ['Interruption',   'Canvas state cached locally · re-opens with same branches for ~24h'],
      ['Transitions',    'Promote → Synthesis · Anchor branch → in-doc edit (Review) · Dissolve → return to Converse'],
    ]} />
  );
}

window.ModeExploration_Wire = ModeExploration_Wire;
window.ModeExploration_Spec = ModeExploration_Spec;
