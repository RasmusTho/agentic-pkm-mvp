/* Cognitive Modes — shared primitives + the canonical "stage"
   (document with margin rail) that every mode wireframe builds on top of.
   Loaded as type="text/babel" before the per-mode files. */

const T = {
  hand: { fontFamily: "'Kalam', cursive" },
  mono: { fontFamily: 'var(--font-mono)' },
  ui:   { fontFamily: 'var(--font-ui)' },
  disp: { fontFamily: 'var(--font-display)' },
};

/* ── micro primitives ─────────────────────────────────────── */
function Bar({ w='100%', h=7, c='var(--border-strong)', style={} }) {
  return <div style={{ width:w, height:h, background:c, borderRadius:2, ...style }} />;
}
function Lines({ n=3, w='100%', last='65%', h=7, gap=7, c }) {
  const col = c || 'var(--border-strong)';
  return (
    <div style={{ display:'flex', flexDirection:'column', gap }}>
      {Array.from({length:n}).map((_,i)=>
        <Bar key={i} w={i===n-1?last:w} h={h} c={col} />)}
    </div>
  );
}
function IconBox({ size=12, color='var(--fg-3)', style={} }) {
  return <div style={{ width:size, height:size, borderRadius:2,
    border:`1.5px solid ${color}`, flexShrink:0, ...style }} />;
}
function IconDot({ size=6, color='var(--fg-3)', glow=false }) {
  return <div style={{ width:size, height:size, borderRadius:'50%',
    background:color, boxShadow: glow ? `0 0 6px ${color}` : 'none', flexShrink:0 }} />;
}
function Pill({ children, color='var(--fg-3)', bg='transparent', border, style={} }) {
  return (
    <span style={{ display:'inline-flex', alignItems:'center', gap:4,
      padding:'2px 7px', borderRadius:2, background:bg,
      border:`1px solid ${border||color}`, ...T.mono, fontSize:9,
      color, letterSpacing:'0.06em', textTransform:'uppercase', ...style }}>
      {children}
    </span>
  );
}
function Btn({ children, color='var(--fg-3)', filled=false, style={} }) {
  return (
    <span style={{ padding:'3px 9px', borderRadius:2,
      border:`1px solid ${color}`,
      background: filled ? color : 'transparent',
      color: filled ? 'var(--fg-inverse)' : color,
      ...T.ui, fontSize:11, ...style }}>{children}</span>
  );
}

/* ── annotation marks (Kalam hand) ────────────────────────── */
function Anno({ children, style={}, dim=false, size=11 }) {
  return <div style={{ ...T.hand, fontSize:size, lineHeight:1.3,
    color: dim ? 'var(--fg-3)' : 'var(--accent)', ...style }}>{children}</div>;
}
function Callout({ children, w=180, style={} }) {
  return (
    <div style={{ background:'rgba(212,168,67,0.06)',
      border:'1px dashed rgba(212,168,67,0.35)', borderRadius:4,
      padding:'5px 9px', ...T.hand, fontSize:11, color:'var(--accent)',
      lineHeight:1.4, maxWidth:w, ...style }}>{children}</div>
  );
}
/* Curved arrow drawn as an SVG so we can point at things from anywhere. */
function Arrow({ d, color='var(--accent)', style={}, head=true, dashed=false }) {
  return (
    <svg style={{ position:'absolute', overflow:'visible', pointerEvents:'none', ...style }}
      width="100%" height="100%">
      <path d={d} stroke={color} strokeWidth="1.2" fill="none"
        strokeLinecap="round"
        strokeDasharray={dashed ? '3 3' : 'none'}
        markerEnd={head ? `url(#ah-${color.replace(/[^a-z0-9]/gi,'')})` : 'none'} />
      {head && (
        <defs>
          <marker id={`ah-${color.replace(/[^a-z0-9]/gi,'')}`} viewBox="0 0 8 8" refX="7" refY="4"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L7,4 L0,8" fill="none" stroke={color} strokeWidth="1.2" />
          </marker>
        </defs>
      )}
    </svg>
  );
}

/* ── document body — used by every mode ───────────────────── */
function DocFrontmatter({ title='Q2 architecture review', tags='architecture, decisions', status='active' }) {
  return (
    <div style={{ ...T.mono, fontSize:9, color:'var(--fg-3)', lineHeight:1.8,
      borderBottom:'1px solid var(--border)', paddingBottom:8, marginBottom:18 }}>
      title: {title} · tags: {tags} · status: {status}
    </div>
  );
}
function DocTitle({ children='Q2 architecture review' }) {
  return <div style={{ ...T.disp, fontSize:24, color:'var(--fg-1)',
    fontWeight:400, letterSpacing:'-0.02em', lineHeight:1.2,
    marginBottom:18 }}>{children}</div>;
}
function DocH({ level=2, children, style={} }) {
  const sizes = { 1:18, 2:13, 3:11 };
  const sz = sizes[level] || 13;
  return <div style={{ ...T.ui, fontSize:sz, color:'var(--fg-2)',
    textTransform:'uppercase', letterSpacing:'0.08em', fontWeight:500,
    marginTop: level===2 ? 14 : 8, marginBottom:8, ...style }}>{children}</div>;
}
function DocPara({ n=3, last='62%', dim=false }) {
  return (
    <div style={{ marginBottom:14 }}>
      <Lines n={n} last={last} h={7}
        c={dim ? 'rgba(61,85,112,0.4)' : 'var(--border-strong)'} />
    </div>
  );
}

/* ── stage chrome — top bar + base layout ─────────────────── */
function StageTopBar({ surface='Converse', vault=true, sessionTitle='Q2 architecture review' }) {
  return (
    <div style={{ height:34, borderBottom:'1px solid var(--border)',
      background:'var(--bg-surface)', display:'flex', alignItems:'center',
      padding:'0 12px', gap:12, flexShrink:0 }}>
      <svg width="13" height="16" viewBox="0 0 40 50" fill="none" style={{flexShrink:0}}>
        <line x1="20" y1="9" x2="20" y2="38" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
        <path d="M20 24 Q11 19 6 15" stroke="var(--border-strong)" strokeWidth="1.2" fill="none"/>
        <path d="M20 24 Q29 19 34 15" stroke="var(--border-strong)" strokeWidth="1.2" fill="none"/>
        <circle cx="20" cy="6" r="2.5" fill="var(--accent)"/>
      </svg>
      {['Converse','Orient','Capture','Synthesize','Resurface'].map(s => (
        <span key={s} style={{ ...T.ui, fontSize:11,
          color: s===surface ? 'var(--fg-1)' : 'var(--fg-3)',
          fontWeight: s===surface ? 500 : 400,
          borderBottom: s===surface ? '1px solid var(--accent)' : 'none',
          paddingBottom:1 }}>{s}</span>
      ))}
      <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:6,
        padding:'2px 8px', background:'var(--bg-raised)',
        border:'1px solid var(--border)', borderRadius:2 }}>
        <span style={{ ...T.ui, fontSize:10, color:'var(--fg-2)' }}>{sessionTitle}</span>
        <span style={{ ...T.mono, fontSize:8, color:'var(--fg-3)' }}>▾</span>
      </div>
      <div style={{ display:'flex', alignItems:'center', gap:4 }}>
        <IconDot size={5} color={vault ? 'var(--vault)' : 'var(--destructive)'} glow />
        <span style={{ ...T.mono, fontSize:9,
          color: vault ? 'var(--vault)' : 'var(--destructive)' }}>
          {vault ? 'vault online' : 'vault offline'}
        </span>
      </div>
    </div>
  );
}

/* ── spec card — semantic overlay description ─────────────── */
function SpecCard({ rows, color='var(--cyan)' }) {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'18px 20px', overflow:'hidden', display:'flex',
      flexDirection:'column', gap:0 }}>
      {rows.map(([k,v], i) => (
        <div key={k} style={{ display:'grid', gridTemplateColumns:'132px 1fr',
          gap:14, padding:'9px 0',
          borderTop: i===0 ? 'none' : '1px solid var(--border)' }}>
          <div style={{ ...T.mono, fontSize:9, color,
            letterSpacing:'0.08em', textTransform:'uppercase', paddingTop:1 }}>
            {k}
          </div>
          <div style={{ ...T.ui, fontSize:11.5, color:'var(--fg-1)',
            lineHeight:1.5 }}>{v}</div>
        </div>
      ))}
    </div>
  );
}

/* ── shared overlay primitives ────────────────────────────── */

/* MarginRail — collapsed by default, expanded for converse-heavy modes */
function MarginRail({ collapsed=false, color='var(--agent)', label='Hugin', count=null, children }) {
  if (collapsed) {
    return (
      <div style={{ width:28, height:'100%', background:'var(--bg-surface)',
        borderLeft:'1px solid var(--border)', display:'flex',
        flexDirection:'column', alignItems:'center', paddingTop:10, gap:8, flexShrink:0 }}>
        <IconDot size={6} color={color} glow />
        {count!=null && <span style={{ ...T.mono, fontSize:9, color }}>{count}</span>}
        <span style={{ writingMode:'vertical-rl', ...T.mono, fontSize:9,
          color:'var(--fg-3)', letterSpacing:'0.1em', marginTop:'auto', marginBottom:14 }}>
          rail collapsed →
        </span>
      </div>
    );
  }
  return (
    <div style={{ width:280, height:'100%', background:'var(--bg-surface)',
      borderLeft:'1px solid var(--border)', display:'flex',
      flexDirection:'column', flexShrink:0 }}>
      <div style={{ padding:'9px 12px', borderBottom:'1px solid var(--border)',
        display:'flex', alignItems:'center', gap:8 }}>
        <IconDot size={6} color={color} glow />
        <span style={{ ...T.mono, fontSize:9, color, textTransform:'uppercase',
          letterSpacing:'0.08em' }}>{label}</span>
        <span style={{ marginLeft:'auto', ...T.mono, fontSize:8,
          color:'var(--fg-3)' }}>›</span>
      </div>
      {children}
    </div>
  );
}

/* SourcePeek — anchored provenance card */
function SourcePeek({ anchor, source, snippet, confidence='0.84', style={} }) {
  return (
    <div style={{ position:'absolute', background:'var(--bg-overlay)',
      border:'1px solid var(--cyan-dim)', borderLeft:'2px solid var(--cyan)',
      borderRadius:3, padding:'8px 10px', width:230,
      boxShadow:'var(--shadow-md)', ...style }}>
      <div style={{ display:'flex', alignItems:'center', gap:5, marginBottom:5 }}>
        <IconBox size={9} color="var(--cyan)" />
        <span style={{ ...T.mono, fontSize:9, color:'var(--cyan)' }}>{source}</span>
        <span style={{ marginLeft:'auto', ...T.mono, fontSize:8,
          color:'var(--fg-3)' }}>conf {confidence}</span>
      </div>
      <Lines n={2} h={5} last="55%" c="rgba(0,212,232,0.18)" />
      <div style={{ ...T.mono, fontSize:8, color:'var(--fg-3)',
        marginTop:6, fontStyle:'italic' }}>{snippet}</div>
    </div>
  );
}

/* Used by MarginRail children */
function RailMessage({ from='agent', anchor, color='var(--agent)', children, staged=false }) {
  const tint = staged
    ? { bg:'rgba(240,144,48,0.05)', border:'var(--amber-dim)', accent:'var(--amber)' }
    : from === 'agent'
      ? { bg:'var(--agent-muted)', border:'var(--agent-dim)', accent:color }
      : { bg:'var(--bg-raised)', border:'var(--border-strong)', accent:'transparent' };
  return (
    <div style={{ background:tint.bg, border:`1px solid ${tint.border}`,
      borderLeft: tint.accent==='transparent' ? `1px solid ${tint.border}` : `2px solid ${tint.accent}`,
      borderRadius:'1px 4px 4px 4px', padding:'7px 9px',
      alignSelf: from==='human' ? 'flex-end' : 'stretch',
      maxWidth: from==='human' ? '88%' : '100%' }}>
      {anchor && (
        <div style={{ display:'flex', alignItems:'center', gap:4, marginBottom:5 }}>
          <IconDot size={5} color={tint.accent} />
          <span style={{ ...T.mono, fontSize:8, color:tint.accent,
            letterSpacing:'0.06em' }}>re: {anchor}</span>
        </div>
      )}
      {children || <Lines n={2} h={5} last="60%"
        c={from==='agent' ? 'rgba(74,158,255,0.2)' : 'rgba(220,232,240,0.25)'} />}
    </div>
  );
}

/* Make available to per-mode files. */
Object.assign(window, {
  T, Bar, Lines, IconBox, IconDot, Pill, Btn,
  Anno, Callout, Arrow,
  DocFrontmatter, DocTitle, DocH, DocPara,
  StageTopBar, SpecCard, MarginRail, SourcePeek, RailMessage,
});
