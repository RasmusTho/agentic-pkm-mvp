/* Mode 5: Resurfacing
   ─ reintroduce previously relevant knowledge · ambient · non-disruptive.
   Wireframe: thin marginalia on the side of the document. Items appear
   like a faint constellation. No pop-ups, no notifications. The user
   notices when ready. Vault-green at low intensity. */

function ModeResurfacing_Wire() {
  return (
    <div style={{ width:880, height:560, background:'var(--bg-base)',
      display:'flex', flexDirection:'column', overflow:'hidden',
      position:'relative' }}>
      <StageTopBar surface="Converse" />

      <div style={{ flex:1, display:'flex', overflow:'hidden' }}>
        {/* document — full attention */}
        <div style={{ flex:1, padding:'28px 56px 28px 36px', overflow:'hidden',
          position:'relative' }}>
          <DocFrontmatter />
          <DocTitle />
          <DocH level={2}>## Decision record</DocH>
          <DocPara n={3} />
          <DocH level={3}>### Network boundary</DocH>
          <DocPara n={2} />
          <DocH level={3}>### Runtime contract</DocH>
          <DocPara n={3} dim />

          {/* faint right-edge marks anchored to passages */}
          {[
            { top:140, label:'Q1-arch · network',  c:'var(--vault)', size:5, align:0 },
            { top:200, label:'memory-essay · §2',  c:'var(--vault)', size:7, align:1 },
            { top:266, label:'session 2026-04-12', c:'var(--agent)', size:5, align:0 },
            { top:340, label:'evergreen · contracts', c:'var(--vault)', size:9, align:2 },
            { top:410, label:'Thornwall analogy',  c:'var(--cyan)',  size:5, align:0 },
          ].map((m,i) => (
            <div key={i} style={{ position:'absolute',
              right: 18 + m.align*4, top: m.top,
              display:'flex', alignItems:'center', gap:6 }}>
              <IconDot size={m.size} color={m.c}
                glow={m.size > 6}
                style={{ opacity: 0.4 + (m.size/15) }} />
            </div>
          ))}
        </div>

        {/* gentle resurface tray — collapsed by default, peeking */}
        <div style={{ width:200, background:'var(--bg-surface)',
          borderLeft:'1px dashed var(--border-strong)',
          display:'flex', flexDirection:'column', flexShrink:0,
          opacity:0.92 }}>
          <div style={{ padding:'9px 12px',
            borderBottom:'1px solid var(--border)',
            display:'flex', alignItems:'center', gap:6 }}>
            <IconDot size={5} color="var(--vault)" />
            <span style={{ ...T.mono, fontSize:9, color:'var(--vault)',
              textTransform:'uppercase', letterSpacing:'0.08em' }}>
              resurface
            </span>
            <span style={{ marginLeft:'auto', ...T.mono, fontSize:8,
              color:'var(--fg-3)' }}>5 latent</span>
          </div>
          <div style={{ flex:1, padding:'8px 10px',
            display:'flex', flexDirection:'column', gap:7 }}>
            {[
              { c:'var(--vault)', s:0.95, t:'Q1 arch · network',
                why:'cited in current doc · same boundary' },
              { c:'var(--vault)', s:0.78, t:'memory-essay · §2',
                why:'shared concept: contract' },
              { c:'var(--vault)', s:0.55, t:'evergreen · contracts',
                why:'high alignment · 3 weeks dormant' },
              { c:'var(--agent)', s:0.40, t:'session 2026-04-12',
                why:'you stopped here mid-thought' },
              { c:'var(--cyan)',  s:0.22, t:'Thornwall analogy',
                why:'distant · possibly useful' },
            ].map((r,i) => (
              <div key={i} style={{ padding:'5px 7px',
                background:'transparent',
                borderLeft:`2px solid ${r.c}`,
                opacity: 0.4 + r.s*0.6 }}>
                <div style={{ display:'flex', alignItems:'baseline', gap:4 }}>
                  <span style={{ ...T.ui, fontSize:11,
                    color:'var(--fg-1)', fontWeight: r.s > 0.7 ? 500 : 400 }}>
                    {r.t}
                  </span>
                </div>
                <span style={{ ...T.mono, fontSize:9, color:'var(--fg-3)',
                  fontStyle:'italic', display:'block', marginTop:2,
                  lineHeight:1.3 }}>
                  {r.why}
                </span>
              </div>
            ))}
          </div>
          <div style={{ padding:'8px 10px',
            borderTop:'1px solid var(--border)' }}>
            <span style={{ ...T.mono, fontSize:9, color:'var(--fg-3)' }}>
              salience falls with distance · no notifications
            </span>
          </div>
        </div>
      </div>

      {/* annotations */}
      <Callout style={{ position:'absolute', top:50, left:14, maxWidth:170 }}>
        marks at right-edge of doc anchor each resurface to its passage
      </Callout>
      <Anno style={{ position:'absolute', left:280, top:160 }}>
        dot size = salience<br/>opacity = recency ↗
      </Anno>
      <Anno style={{ position:'absolute', left:200, bottom:80 }}>
        ↑ never interrupts — the user&apos;s eye finds it when ready
      </Anno>
    </div>
  );
}

function ModeResurfacing_Spec() {
  return (
    <SpecCard color="var(--vault)" rows={[
      ['Overlay class',  'Marginalia + soft tray · always present, never demanding'],
      ['Density',        'Very low · 3–7 items max, sized by salience not equal weight'],
      ['Persistence',    'Salience model lives in runtime; the items themselves are vault notes'],
      ['Provenance',     'Each resurface shows reason ("cited", "dormant", "high alignment")'],
      ['Sources',        'Item IS the source · clicking opens SourcePeek anchored to its passage'],
      ['AI visibility',  'Background · agent computes salience; no agent voice or chat presence'],
      ['Spatial',        'Right-edge dots map 1:1 to passages; tray is the legend'],
      ['Interruption',   'Zero · no notifications, no badges, no popups; survives reload silently'],
      ['Transitions',    'Click item → SourcePeek (Converse) · Pin item → Synthesis comparison strip · Dismiss → fades for 7 days'],
    ]} />
  );
}

window.ModeResurfacing_Wire = ModeResurfacing_Wire;
window.ModeResurfacing_Spec = ModeResurfacing_Spec;
