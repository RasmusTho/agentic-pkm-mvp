/* Cross-mode artboards: transition map, overlay hierarchy, example flows,
   interruption/recovery, provenance interaction, resurfacing patterns. */

/* ── Transition map ───────────────────────────────────────── */
function ModeTransitionMap() {
  // node positions
  const nodes = [
    { id:'orient',  label:'Orientation',  x:140, y:100, c:'var(--accent)' },
    { id:'explore', label:'Exploration',  x:380, y:80,  c:'var(--cyan)'   },
    { id:'synth',   label:'Synthesis',    x:620, y:120, c:'var(--vault)'  },
    { id:'review',  label:'Review',       x:540, y:300, c:'var(--amber)'  },
    { id:'resurf',  label:'Resurfacing',  x:220, y:320, c:'var(--vault)'  },
  ];
  const edges = [
    { from:'orient',  to:'explore', label:'resume + branch'   },
    { from:'orient',  to:'review',  label:'show all threads'  },
    { from:'orient',  to:'resurf',  label:'return without intent' },
    { from:'explore', to:'synth',   label:'promote'           },
    { from:'explore', to:'review',  label:'anchor branch'     },
    { from:'synth',   to:'review',  label:'stage as evergreen'},
    { from:'review',  to:'orient',  label:'defer'             },
    { from:'resurf',  to:'synth',   label:'pin to comparison' },
    { from:'resurf',  to:'explore', label:'follow + diverge'  },
  ];
  const get = id => nodes.find(n => n.id === id);

  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      position:'relative', overflow:'hidden' }}>
      {/* grid */}
      <div style={{ position:'absolute', inset:0,
        backgroundImage:'linear-gradient(rgba(0,212,232,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(0,212,232,0.03) 1px, transparent 1px)',
        backgroundSize:'24px 24px' }} />

      <div style={{ position:'relative', padding:'16px 20px' }}>
        <div style={{ ...T.disp, fontSize:18, color:'var(--fg-1)',
          letterSpacing:'-0.01em', marginBottom:2 }}>
          Mode transitions
        </div>
        <div style={{ ...T.mono, fontSize:9, color:'var(--fg-3)',
          letterSpacing:'0.08em', textTransform:'uppercase' }}>
          all transitions preserve document anchor
        </div>
      </div>

      <svg style={{ position:'absolute', inset:0, pointerEvents:'none' }}
        width="100%" height="100%" viewBox="0 0 800 440"
        preserveAspectRatio="none">
        <defs>
          <marker id="ah-mode" viewBox="0 0 8 8" refX="7" refY="4"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L7,4 L0,8" fill="none" stroke="var(--fg-3)" strokeWidth="1.2"/>
          </marker>
        </defs>
        {edges.map((e,i) => {
          const a = get(e.from), b = get(e.to);
          const mx = (a.x + b.x)/2;
          const my = (a.y + b.y)/2 - 18;
          const d = `M ${a.x},${a.y} Q ${mx},${my} ${b.x},${b.y}`;
          return (
            <g key={i}>
              <path d={d} stroke="var(--border-strong)" strokeWidth="1.2"
                fill="none" markerEnd="url(#ah-mode)" />
              <text x={mx} y={my+2} fill="var(--fg-3)" fontSize="10"
                fontFamily="JetBrains Mono" textAnchor="middle"
                style={{ paintOrder:'stroke', stroke:'var(--bg-base)', strokeWidth:4,
                  strokeLinejoin:'round' }}>
                {e.label}
              </text>
            </g>
          );
        })}
      </svg>

      {nodes.map(n => (
        <div key={n.id} style={{ position:'absolute',
          left: `${(n.x/800)*100}%`, top: `${(n.y/440)*100}%`,
          transform:'translate(-50%, -50%)',
          padding:'8px 14px', background:'var(--bg-raised)',
          border:`1px solid ${n.c}`, borderLeft:`3px solid ${n.c}`,
          borderRadius:3, ...T.ui, fontSize:12, color:n.c,
          letterSpacing:'0.02em', whiteSpace:'nowrap',
          boxShadow:`0 0 0 4px var(--bg-base)` }}>
          {n.label}
        </div>
      ))}

      {/* legend */}
      <div style={{ position:'absolute', right:16, bottom:14,
        ...T.mono, fontSize:9, color:'var(--fg-3)', textAlign:'right',
        lineHeight:1.7 }}>
        gold = governance · cyan = transient · green = vault · amber = staged
      </div>
    </div>
  );
}

/* ── Overlay hierarchy diagram ────────────────────────────── */
function OverlayHierarchy() {
  const layers = [
    { z:6, label:'Toast/system',     hint:'errors, vault offline, never blocks' },
    { z:5, label:'Re-entry overlay', hint:'orientation only · centered, dismissible' },
    { z:4, label:'Source peek',      hint:'anchored card · click outside dismisses' },
    { z:3, label:'Bottom sheet / governance dock', hint:'review queue · portrait rail' },
    { z:2, label:'Margin rail · tray',    hint:'conversation · resurface tray' },
    { z:1, label:'Adjacent canvas',  hint:'exploration · synthesis comparison' },
    { z:0, label:'Document',         hint:'always present · cognitive anchor' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'16px 20px', display:'flex', flexDirection:'column' }}>
      <div style={{ ...T.disp, fontSize:18, color:'var(--fg-1)',
        letterSpacing:'-0.01em', marginBottom:2 }}>
        Overlay hierarchy
      </div>
      <div style={{ ...T.mono, fontSize:9, color:'var(--fg-3)',
        letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:14 }}>
        higher = more transient · all dismissible without losing anchor
      </div>
      <div style={{ flex:1, display:'flex', flexDirection:'column',
        justifyContent:'space-between', position:'relative' }}>
        {layers.map((l,i) => {
          const inset = l.z * 14;
          const tone = l.z === 0
            ? { bg:'var(--bg-raised)', bd:'var(--border-strong)',
                fg:'var(--fg-1)', accent:'var(--accent)' }
            : l.z === 1
              ? { bg:'rgba(0,212,232,0.04)', bd:'var(--cyan-dim)',
                  fg:'var(--cyan)', accent:'var(--cyan)' }
              : l.z === 2
                ? { bg:'var(--agent-muted)', bd:'var(--agent-dim)',
                    fg:'var(--agent)', accent:'var(--agent)' }
                : l.z === 3
                  ? { bg:'rgba(240,144,48,0.04)', bd:'var(--amber-dim)',
                      fg:'var(--amber)', accent:'var(--amber)' }
                  : l.z === 4
                    ? { bg:'var(--cyan-muted)', bd:'var(--cyan-dim)',
                        fg:'var(--cyan)', accent:'var(--cyan)' }
                    : l.z === 5
                      ? { bg:'rgba(212,168,67,0.06)', bd:'rgba(212,168,67,0.4)',
                          fg:'var(--accent)', accent:'var(--accent)' }
                      : { bg:'var(--bg-raised)', bd:'var(--border-strong)',
                          fg:'var(--fg-2)', accent:'var(--fg-2)' };
          return (
            <div key={l.z} style={{ marginLeft:inset, marginRight:inset,
              padding:'8px 12px', background:tone.bg,
              border:`1px solid ${tone.bd}`,
              borderLeft:`2px solid ${tone.accent}`,
              borderRadius:3, display:'flex', alignItems:'center', gap:10 }}>
              <span style={{ ...T.mono, fontSize:9, color:tone.fg,
                width:18 }}>z{l.z}</span>
              <span style={{ ...T.ui, fontSize:11.5, color:'var(--fg-1)',
                fontWeight: l.z===0 ? 500 : 400 }}>{l.label}</span>
              <span style={{ marginLeft:'auto', ...T.mono, fontSize:9,
                color:'var(--fg-3)' }}>{l.hint}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Example flow trace ───────────────────────────────────── */
function FlowTrace({ title, subtitle, steps, color='var(--accent)' }) {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'16px 20px', display:'flex', flexDirection:'column' }}>
      <div style={{ ...T.disp, fontSize:16, color:'var(--fg-1)',
        letterSpacing:'-0.01em', marginBottom:2 }}>{title}</div>
      <div style={{ ...T.mono, fontSize:9, color:'var(--fg-3)',
        letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:14 }}>
        {subtitle}
      </div>
      <div style={{ flex:1, display:'flex', flexDirection:'column',
        gap:0, position:'relative' }}>
        {steps.map((s, i) => (
          <div key={i} style={{ display:'flex', gap:12, padding:'7px 0',
            borderTop: i===0 ? 'none' : '1px solid var(--border)' }}>
            <div style={{ display:'flex', flexDirection:'column',
              alignItems:'center', width:60, flexShrink:0 }}>
              <div style={{ width:18, height:18, borderRadius:2,
                border:`1px solid ${s.mode_color || color}`,
                background:'var(--bg-raised)',
                display:'flex', alignItems:'center', justifyContent:'center',
                ...T.mono, fontSize:9, color: s.mode_color || color }}>
                {String(i+1).padStart(2,'0')}
              </div>
              <span style={{ ...T.mono, fontSize:8, color:'var(--fg-3)',
                marginTop:3, textAlign:'center', letterSpacing:'0.04em' }}>
                {s.mode}
              </span>
            </div>
            <div style={{ flex:1 }}>
              <div style={{ ...T.ui, fontSize:11.5, color:'var(--fg-1)',
                lineHeight:1.45 }}>{s.action}</div>
              {s.detail && <div style={{ ...T.mono, fontSize:9,
                color:'var(--fg-3)', marginTop:3, lineHeight:1.4 }}>
                {s.detail}
              </div>}
            </div>
            {s.surface && (
              <Pill color={s.mode_color || color} bg="transparent"
                border={s.mode_color || color}
                style={{ alignSelf:'flex-start', marginTop:1 }}>
                {s.surface}
              </Pill>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function FlowOrientationToReview() {
  return <FlowTrace
    title="Recovery: interrupt → resume → review"
    subtitle="user closed laptop mid-thought · returns 3 days later"
    steps={[
      { mode:'orient',  mode_color:'var(--accent)',
        action:'Re-entry overlay surfaces 3 open loops + last trace.',
        detail:'overlay floats; document already loaded underneath',
        surface:'overlay' },
      { mode:'orient',  mode_color:'var(--accent)',
        action:'User clicks "Resume here".',
        detail:'overlay dismisses; gutter beacons remain at line 47, frontmatter, [[Q1-arch]]',
        surface:'document' },
      { mode:'converse',mode_color:'var(--agent)',
        action:'Margin rail expands with last 3 turns of conversation.',
        detail:'thread is continuous, not a fresh session',
        surface:'rail' },
      { mode:'review',  mode_color:'var(--amber)',
        action:'User clicks the amber gutter beacon at line 47.',
        detail:'staged proposal expands inline with full diff + receipt #r-014',
        surface:'inline block' },
      { mode:'review',  mode_color:'var(--amber)',
        action:'User applies the proposal (⌘↵).',
        detail:'receipt updated · new beacon for next item in queue',
        surface:'governance dock' },
    ]} />;
}

function FlowExploreToEvergreen() {
  return <FlowTrace
    title="Cognition: probe → converge → durable"
    subtitle="exploratory thought becomes vault-canonical"
    color="var(--cyan)"
    steps={[
      { mode:'converse',mode_color:'var(--agent)',
        action:'User highlights the phrase "runtime contract" in document.',
        surface:'document' },
      { mode:'explore', mode_color:'var(--cyan)',
        action:'User opens an exploration canvas anchored to that phrase.',
        detail:'three speculative branches generated · nothing persists yet',
        surface:'adjacent canvas' },
      { mode:'explore', mode_color:'var(--cyan)',
        action:'User merges branches B and C; deletes A.',
        detail:'canvas state cached locally for 24h',
        surface:'adjacent canvas' },
      { mode:'synth',   mode_color:'var(--vault)',
        action:'"Promote to companion note" → Synthesis surface opens.',
        detail:'comparison strip auto-pulls Q1-arch + memory-essay as related',
        surface:'compare strip' },
      { mode:'synth',   mode_color:'var(--vault)',
        action:'User authors candidate evergreen with provenance flecks live.',
        detail:'each para tagged with backing source ids',
        surface:'draft surface' },
      { mode:'review',  mode_color:'var(--amber)',
        action:'"Stage as evergreen" — proposal lands in governance queue.',
        detail:'final apply still requires explicit human action',
        surface:'review queue' },
    ]} />;
}

function FlowResurfacingPattern() {
  return <FlowTrace
    title="Ambient: latent knowledge re-attentioning"
    subtitle="non-disruptive resurfacing during normal reading"
    color="var(--vault)"
    steps={[
      { mode:'converse',mode_color:'var(--agent)',
        action:'User opens Q2-arch.md to read.',
        detail:'no agent action requested',
        surface:'document' },
      { mode:'resurf',  mode_color:'var(--vault)',
        action:'Right-edge of doc shows 5 faint dots, sized by salience.',
        detail:'computed silently · no notification, no badge, no chrome flash',
        surface:'marginalia' },
      { mode:'resurf',  mode_color:'var(--vault)',
        action:'User notices a larger dot near "## Network boundary".',
        detail:'their eye finds it · we never demanded attention',
        surface:'marginalia' },
      { mode:'converse',mode_color:'var(--agent)',
        action:'Click → SourcePeek opens with [[Q1-arch · network]] excerpt.',
        detail:'inline, not a navigation · doc unchanged',
        surface:'source peek' },
      { mode:'synth',   mode_color:'var(--vault)',
        action:'"Pin to comparison" — adds to Synthesis strip for next session.',
        detail:'durable but lazy · nothing forced',
        surface:'compare strip' },
    ]} />;
}

function FlowProvenancePattern() {
  return <FlowTrace
    title="Provenance: claim → evidence → audit"
    subtitle="every agent claim is inspectable without leaving page"
    color="var(--cyan)"
    steps={[
      { mode:'review',  mode_color:'var(--amber)',
        action:'Inline proposal shows 3 evidence chips: [Q1-arch:44] [memory-essay:9] [session 2026-05-04].',
        surface:'staged block' },
      { mode:'review',  mode_color:'var(--cyan)',
        action:'Hover an evidence chip → SourcePeek slides in next to it.',
        detail:'shows snippet + confidence + line number · doc untouched',
        surface:'source peek' },
      { mode:'review',  mode_color:'var(--cyan)',
        action:'Click "open in vault" → Obsidian receives uri scheme.',
        detail:'companion UI does not navigate · vault is canonical',
        surface:'external' },
      { mode:'review',  mode_color:'var(--amber)',
        action:'Receipt id #r-014 links to /receipts/2026-05-07/r-014.md',
        detail:'full prompt, model, sources, confidence, accept/reject status',
        surface:'vault file' },
    ]} />;
}

window.ModeTransitionMap = ModeTransitionMap;
window.OverlayHierarchy = OverlayHierarchy;
window.FlowOrientationToReview = FlowOrientationToReview;
window.FlowExploreToEvergreen = FlowExploreToEvergreen;
window.FlowResurfacingPattern = FlowResurfacingPattern;
window.FlowProvenancePattern = FlowProvenancePattern;
