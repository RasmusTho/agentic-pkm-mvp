/* Mode 4: Review / Governance
   ─ human review of AI-generated proposals · provenance · staged accept/reject.
   Wireframe: document is the surface; staged proposals appear as inline
   amber blocks with diff + receipts. A small governance dock anchors at
   the bottom showing the queue. Non-intrusive: nothing applies until
   the human clicks. Amber tones throughout. */

function ModeReview_Wire() {
  return (
    <div style={{ width:880, height:560, background:'var(--bg-base)',
      display:'flex', flexDirection:'column', overflow:'hidden',
      position:'relative' }}>
      <StageTopBar surface="Converse" />

      <div style={{ flex:1, display:'flex', overflow:'hidden' }}>
        {/* document with staged blocks inline */}
        <div style={{ flex:1, padding:'24px 36px 60px', overflow:'hidden',
          position:'relative' }}>
          <DocFrontmatter />
          <DocTitle />
          <DocH level={2}>## Decision record</DocH>
          <DocPara n={2} />

          {/* staged proposal — inline amber block with receipt */}
          <div style={{ background:'rgba(240,144,48,0.05)',
            border:'1px solid rgba(240,144,48,0.25)',
            borderLeft:'3px solid var(--amber)',
            borderRadius:'0 3px 3px 0', padding:'10px 12px', marginBottom:14,
            position:'relative' }}>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
              <Pill color="var(--amber)" bg="rgba(240,144,48,0.06)"
                border="var(--amber-dim)">SUGGEST</Pill>
              <span style={{ ...T.mono, fontSize:9, color:'var(--fg-2)' }}>
                Hugin · 2 changes · receipt #r-2026-05-07-014
              </span>
              <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
                color:'var(--fg-3)' }}>conf 0.82</span>
            </div>
            {/* diff lines */}
            {[
              { s:'+', c:'rgba(57,232,125,0.4)', w:'80%' },
              { s:'+', c:'rgba(57,232,125,0.4)', w:'62%' },
              { s:'-', c:'rgba(255,61,61,0.4)',  w:'58%' },
              { s:' ', c:'var(--border-strong)', w:'70%' },
            ].map((r,i) => (
              <div key={i} style={{ display:'flex', gap:8, alignItems:'center',
                marginBottom:4 }}>
                <span style={{ ...T.mono, fontSize:10,
                  color: r.s==='+' ? 'rgba(57,232,125,0.7)'
                    : r.s==='-' ? 'rgba(255,61,61,0.7)' : 'var(--fg-3)',
                  width:10 }}>{r.s}</span>
                <div style={{ flex:1, height:6, background:r.c,
                  borderRadius:1, maxWidth:r.w }} />
              </div>
            ))}
            {/* evidence trail */}
            <div style={{ marginTop:10, display:'flex', gap:6,
              flexWrap:'wrap', alignItems:'center' }}>
              <span style={{ ...T.mono, fontSize:9, color:'var(--fg-3)',
                textTransform:'uppercase', letterSpacing:'0.08em' }}>
                evidence
              </span>
              {['Q1-arch.md:44', 'memory-essay.md:9', 'session 2026-05-04']
                .map(e => (
                  <span key={e} style={{ ...T.mono, fontSize:9,
                    color:'var(--cyan)', background:'var(--cyan-muted)',
                    border:'1px solid var(--cyan-dim)', borderRadius:2,
                    padding:'1px 6px' }}>{e}</span>
              ))}
            </div>
            {/* governance row */}
            <div style={{ display:'flex', gap:6, marginTop:10 }}>
              <Btn color="var(--vault)" filled>Apply</Btn>
              <Btn color="var(--amber)">Apply w/ edits</Btn>
              <Btn color="var(--fg-3)">Defer</Btn>
              <Btn color="var(--destructive)">Reject</Btn>
              <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
                color:'var(--fg-3)', alignSelf:'center' }}>
                ⌘↵ apply · ⌘⌫ reject
              </span>
            </div>
          </div>

          <DocH level={2}>## Network boundary</DocH>
          <DocPara n={2} dim />
        </div>
      </div>

      {/* governance dock — bottom strip */}
      <div style={{ position:'absolute', bottom:0, left:0, right:0,
        height:42, background:'var(--bg-surface)',
        borderTop:'1px solid var(--amber-dim)', display:'flex',
        alignItems:'center', gap:10, padding:'0 14px' }}>
        <Pill color="var(--amber)" bg="rgba(240,144,48,0.08)"
          border="var(--amber-dim)">queue · 4</Pill>
        {/* mini queue items */}
        {[
          { c:'var(--amber)', t:'## Decision record',  active:true },
          { c:'var(--amber)', t:'frontmatter · status' },
          { c:'var(--agent)', t:'new wikilink → [[Q1-arch]]' },
          { c:'var(--vault)', t:'evergreen draft ready' },
        ].map((q,i) => (
          <div key={i} style={{ display:'flex', alignItems:'center', gap:5,
            padding:'4px 9px', borderRadius:2,
            background: q.active ? 'rgba(240,144,48,0.08)' : 'transparent',
            border: `1px solid ${q.active ? 'var(--amber-dim)' : 'transparent'}` }}>
            <IconDot size={5} color={q.c} />
            <span style={{ ...T.ui, fontSize:11,
              color: q.active ? 'var(--amber)' : 'var(--fg-2)',
              fontWeight: q.active ? 500 : 400 }}>{q.t}</span>
          </div>
        ))}
        <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
          color:'var(--fg-3)' }}>← / → walks queue · esc closes</span>
      </div>

      {/* annotations */}
      <Callout style={{ position:'absolute', top:50, right:14, maxWidth:160 }}>
        proposal lives where it would land — not in a sidebar. inspect-in-place.
      </Callout>
      <Anno style={{ position:'absolute', right:18, top:240, textAlign:'right' }}>
        ↖ receipt id<br/>links to vault<br/>audit trail
      </Anno>
      <Anno style={{ position:'absolute', left:14, bottom:60 }}>
        ↓ governance dock — non-modal, walks queue without losing place
      </Anno>
    </div>
  );
}

function ModeReview_Spec() {
  return (
    <SpecCard color="var(--amber)" rows={[
      ['Overlay class',  'Inline staged blocks · governance dock at bottom'],
      ['Density',        'Calm · one proposal expanded at a time, others compact in queue'],
      ['Persistence',    'Vault-side · receipts written to `/receipts/`; status survives reload'],
      ['Provenance',     'Mandatory · every proposal carries receipt id, evidence chips, confidence'],
      ['Sources',        'Linked from evidence chips · click opens SourcePeek without leaving page'],
      ['AI visibility',  'Bounded · agent proposes only; verbs are SUGGEST. APPLY is human-only.'],
      ['Spatial',        'Document at full width; dock is 42px chrome that never obscures content'],
      ['Interruption',   'Defer puts proposal in queue with timestamp; nothing is lost or auto-applied'],
      ['Transitions',    'Apply → back to Converse · Reject → recorded in receipt · Defer → Orientation surfaces it later'],
    ]} />
  );
}

window.ModeReview_Wire = ModeReview_Wire;
window.ModeReview_Spec = ModeReview_Spec;
