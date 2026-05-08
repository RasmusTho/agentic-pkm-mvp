/* Mode 3: Synthesis
   ─ convergence · compare concepts · candidate evergreen knowledge.
   Wireframe: side-by-side comparison strip across top, candidate
   evergreen draft below. Document still visible but inset (it is the
   substrate being synthesized FROM). Vault-green tones — synthesis
   is heading toward durable knowledge. */

function ModeSynthesis_Wire() {
  return (
    <div style={{ width:880, height:560, background:'var(--bg-base)',
      display:'flex', flexDirection:'column', overflow:'hidden',
      position:'relative' }}>
      <StageTopBar surface="Synthesize" />

      <div style={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden' }}>
        {/* comparison strip — three source notes side by side */}
        <div style={{ display:'flex', gap:10, padding:'12px 14px 10px',
          borderBottom:'1px solid var(--border)',
          background:'var(--bg-surface)' }}>
          {[
            { t:'Q2 architecture', c:'var(--accent)', tag:'active' },
            { t:'Q1 architecture', c:'var(--vault)', tag:'evergreen' },
            { t:'memory-essay',    c:'var(--vault)', tag:'evergreen' },
          ].map(s => (
            <div key={s.t} style={{ flex:1, background:'var(--bg-raised)',
              border:'1px solid var(--border)', borderTop:`2px solid ${s.c}`,
              borderRadius:'0 0 3px 3px', padding:'8px 10px' }}>
              <div style={{ display:'flex', alignItems:'center', gap:5, marginBottom:5 }}>
                <IconBox size={9} color={s.c} />
                <span style={{ ...T.mono, fontSize:9, color:'var(--fg-2)' }}>{s.t}</span>
                <Pill color={s.c} bg="transparent" border={s.c}
                  style={{ marginLeft:'auto', fontSize:8 }}>{s.tag}</Pill>
              </div>
              <Lines n={3} h={5} last="60%" c="rgba(220,232,240,0.18)" />
              {/* tiny "matches" markers */}
              <div style={{ display:'flex', gap:4, marginTop:6 }}>
                {[0,1,2].map(i => <div key={i} style={{ height:3,
                  flex:1, background:i===1?'var(--vault)':'rgba(57,232,125,0.3)',
                  borderRadius:1 }} />)}
              </div>
              <span style={{ ...T.mono, fontSize:8, color:'var(--vault)',
                marginTop:4, display:'inline-block' }}>3 alignments</span>
            </div>
          ))}
        </div>

        {/* candidate evergreen — main work surface */}
        <div style={{ flex:1, display:'flex', overflow:'hidden' }}>
          <div style={{ flex:1, padding:'18px 26px', overflow:'hidden',
            position:'relative' }}>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:10 }}>
              <Pill color="var(--vault)" bg="var(--vault-muted)"
                border="var(--vault-dim)">candidate evergreen</Pill>
              <span style={{ ...T.mono, fontSize:9, color:'var(--fg-3)' }}>
                /Evergreens/runtime-contract.md · draft
              </span>
              <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
                color:'var(--fg-3)' }}>3 sources synthesized</span>
            </div>

            <div style={{ ...T.disp, fontSize:18, color:'var(--fg-1)',
              marginBottom:12, letterSpacing:'-0.01em' }}>
              The runtime contract as boundary, not surface
            </div>

            {/* paragraphs with provenance flecks */}
            {[
              { n:3, sources:[1,2] },
              { n:2, sources:[0,2] },
              { n:3, sources:[0,1] },
            ].map((p, i) => (
              <div key={i} style={{ display:'flex', gap:8, marginBottom:12 }}>
                <div style={{ flex:1 }}>
                  <Lines n={p.n} h={7} last="58%" c="var(--border-strong)" />
                </div>
                <div style={{ display:'flex', flexDirection:'column', gap:3,
                  paddingTop:2, flexShrink:0 }}>
                  {p.sources.map(s => (
                    <div key={s} style={{ display:'flex', alignItems:'center', gap:3 }}>
                      <IconDot size={4} color="var(--vault)" />
                      <span style={{ ...T.mono, fontSize:8,
                        color:'var(--vault)' }}>s{s+1}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {/* divergence note — where sources disagree */}
            <div style={{ background:'rgba(240,144,48,0.05)',
              border:'1px solid var(--amber-dim)',
              borderLeft:'2px solid var(--amber)', borderRadius:'1px 3px 3px 1px',
              padding:'7px 10px', marginTop:6 }}>
              <span style={{ ...T.mono, fontSize:9, color:'var(--amber)',
                textTransform:'uppercase', letterSpacing:'0.08em' }}>
                divergence · s1 vs s3
              </span>
              <div style={{ ...T.ui, fontSize:11, color:'var(--fg-2)',
                marginTop:3 }}>
                Q2 frames the contract as <i>negotiated</i>; the memory essay treats it as <i>imposed</i>. Reconcile?
              </div>
            </div>
          </div>

          {/* side rail — provenance + accept/refine */}
          <div style={{ width:200, background:'var(--bg-surface)',
            borderLeft:'1px solid var(--border)', display:'flex',
            flexDirection:'column', flexShrink:0 }}>
            <div style={{ padding:'9px 12px',
              borderBottom:'1px solid var(--border)' }}>
              <span style={{ ...T.mono, fontSize:9, color:'var(--vault)',
                textTransform:'uppercase', letterSpacing:'0.08em' }}>
                Provenance
              </span>
            </div>
            <div style={{ flex:1, padding:'8px 10px',
              display:'flex', flexDirection:'column', gap:6 }}>
              {[
                { s:'s1', n:'Q2 architecture', l:[12,18] },
                { s:'s2', n:'Q1 architecture', l:[44] },
                { s:'s3', n:'memory-essay',    l:[8,9,71] },
              ].map(p => (
                <div key={p.s} style={{ background:'var(--bg-raised)',
                  border:'1px solid var(--border)', borderRadius:2,
                  padding:'5px 7px' }}>
                  <div style={{ display:'flex', alignItems:'center', gap:4 }}>
                    <IconDot size={4} color="var(--vault)" />
                    <span style={{ ...T.mono, fontSize:9,
                      color:'var(--fg-2)' }}>{p.s} · {p.n}</span>
                  </div>
                  <span style={{ ...T.mono, fontSize:8, color:'var(--fg-3)' }}>
                    lines {p.l.join(', ')}
                  </span>
                </div>
              ))}
            </div>
            <div style={{ padding:'8px 10px', borderTop:'1px solid var(--border)',
              display:'flex', flexDirection:'column', gap:5 }}>
              <Btn color="var(--vault)" filled>Stage as evergreen</Btn>
              <Btn color="var(--fg-3)">Refine with Hugin</Btn>
              <Btn color="var(--fg-3)">Discard draft</Btn>
            </div>
          </div>
        </div>
      </div>

      <Callout style={{ position:'absolute', top:50, left:14, maxWidth:170 }}>
        sources align across the top — the comparison itself is the work surface
      </Callout>
      <Anno style={{ position:'absolute', right:218, top:200 }}>
        green flecks =<br/>which sources<br/>back each para →
      </Anno>
      <Anno style={{ position:'absolute', left:160, bottom:90 }}>
        amber breaks ↑ where sources disagree — refusal to flatten
      </Anno>
    </div>
  );
}

function ModeSynthesis_Spec() {
  return (
    <SpecCard color="var(--vault)" rows={[
      ['Overlay class',  'Comparison strip + draft surface · replaces document temporarily'],
      ['Density',        'High structure · precise alignment markers, per-paragraph provenance'],
      ['Persistence',    'Draft persists as `*.draft.md` in vault (not yet evergreen)'],
      ['Provenance',     'Always visible · per-paragraph source flecks; full provenance rail to the right'],
      ['Sources',        'Primary surface · sources are first-class peers'],
      ['AI visibility',  'High · agent generates draft, but every claim is attributed and questionable'],
      ['Spatial',        'Three-zone: comparison top, draft center, provenance right'],
      ['Interruption',   'Draft auto-saves; resume picks up in-place. Sources re-fetched on open.'],
      ['Transitions',    'Stage as evergreen → Review · Refine → Converse · Discard → back to source doc'],
    ]} />
  );
}

window.ModeSynthesis_Wire = ModeSynthesis_Wire;
window.ModeSynthesis_Spec = ModeSynthesis_Spec;
