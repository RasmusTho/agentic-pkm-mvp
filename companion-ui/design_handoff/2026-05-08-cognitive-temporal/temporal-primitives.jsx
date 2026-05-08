/* ============================================================
   Temporal cognition — shared primitives
   ============================================================
   Visual vocabulary specific to time, decay, dormancy, and
   continuity. Builds on the cyberpunk/Tron design system.
   ============================================================ */

const TT = {
  hand: { fontFamily: "'Kalam', cursive" },
  mono: { fontFamily: 'var(--font-mono)' },
  ui:   { fontFamily: 'var(--font-ui)' },
  disp: { fontFamily: 'var(--font-display)' },
};

/* ── Hairline divider with optional inline label ───────── */
function Hairline({ label, color = 'var(--border)', labelColor = 'var(--fg-3)', style = {} }) {
  if (!label) return <div style={{ height:1, background:color, ...style }} />;
  return (
    <div style={{ display:'flex', alignItems:'center', gap:8, ...style }}>
      <div style={{ height:1, flex:1, background:color }} />
      <span style={{ ...TT.mono, fontSize:8.5, color:labelColor,
        letterSpacing:'0.12em', textTransform:'uppercase' }}>{label}</span>
      <div style={{ height:1, flex:1, background:color }} />
    </div>
  );
}

/* ── Annotation in handwriting (Kalam) ─────────────────── */
function HandNote({ children, color = 'var(--accent)', size = 12, style = {} }) {
  return (
    <div style={{ ...TT.hand, fontSize:size, color, lineHeight:1.35,
      letterSpacing:'0.005em', ...style }}>{children}</div>
  );
}

/* ── Mono caption (uppercase, tracked) ─────────────────── */
function Caption({ children, color = 'var(--fg-3)', size = 9, style = {} }) {
  return (
    <span style={{ ...TT.mono, fontSize:size, color,
      letterSpacing:'0.1em', textTransform:'uppercase', ...style }}>{children}</span>
  );
}

/* ── Faint marginalia dot — salience by size, recency by opacity ── */
function MargDot({ size = 6, opacity = 1, color = 'var(--vault)', glow = true }) {
  return (
    <div style={{ width:size, height:size, borderRadius:'50%',
      background:color, opacity,
      boxShadow: glow ? `0 0 ${size*1.4}px ${color}` : 'none',
      flexShrink:0 }} />
  );
}

/* ── Skeleton text line — placeholder for body copy ───── */
function Line({ w = '100%', h = 6, color = 'var(--border-strong)',
  opacity = 1, style = {} }) {
  return <div style={{ width:w, height:h, background:color,
    borderRadius:1, opacity, ...style }} />;
}
function Lines({ rows = 3, last = '60%', h = 6, gap = 6,
  color = 'var(--border-strong)', opacity = 1 }) {
  return (
    <div style={{ display:'flex', flexDirection:'column', gap }}>
      {Array.from({length:rows}).map((_,i) =>
        <Line key={i} h={h} w={i === rows-1 ? last : '100%'}
          color={color} opacity={opacity} />)}
    </div>
  );
}

/* ── Document panel — used as a stage for overlay demos ─ */
function DocStage({ children, width = '100%', height = '100%',
  pad = '20px 28px', style = {} }) {
  return (
    <div style={{ width, height, background:'var(--bg-base)',
      backgroundImage:
        'linear-gradient(rgba(0,212,232,0.018) 1px, transparent 1px),' +
        'linear-gradient(90deg, rgba(0,212,232,0.018) 1px, transparent 1px)',
      backgroundSize:'32px 32px',
      padding:pad, position:'relative', overflow:'hidden', ...style }}>
      {children}
    </div>
  );
}

/* ── Time-decay arc — small SVG that draws a fading curve ── */
function DecayArc({ w = 120, h = 32, color = 'var(--vault)',
  highlight = 0.7, style = {} }) {
  // highlight = 0..1 position of "now"
  const points = [];
  for (let i = 0; i <= 40; i++) {
    const x = (i/40) * (w - 6) + 3;
    const y = h - 4 - (h - 8) * Math.exp(-i/12);
    points.push([x,y]);
  }
  const path = points.map((p,i) => `${i===0?'M':'L'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const nowX = highlight * (w - 6) + 3;
  const nowI = Math.round(highlight * 40);
  const nowY = points[nowI] ? points[nowI][1] : h - 4;
  return (
    <svg width={w} height={h} style={style}>
      <path d={path} fill="none" stroke={color} strokeWidth="1.2"
        opacity="0.45" strokeLinecap="round" />
      <circle cx={nowX} cy={nowY} r="2.5" fill={color} />
      <circle cx={nowX} cy={nowY} r="5" fill="none" stroke={color}
        strokeWidth="0.8" opacity="0.4" />
    </svg>
  );
}

/* ── Tension halo — radial pressure indicator ─────────── */
function TensionHalo({ size = 40, level = 0.6, color = 'var(--amber)' }) {
  // level 0..1 pressure intensity
  const r = size/2 - 2;
  return (
    <svg width={size} height={size}>
      <defs>
        <radialGradient id={`th-${level}`}>
          <stop offset="0%" stopColor={color} stopOpacity={0.45 * level} />
          <stop offset="60%" stopColor={color} stopOpacity={0.15 * level} />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx={size/2} cy={size/2} r={r} fill={`url(#th-${level})`} />
      <circle cx={size/2} cy={size/2} r="1.5" fill={color} opacity={0.7 + 0.3*level} />
    </svg>
  );
}

/* ── Trajectory thread — broken / dashed line indicating  ─
       a thought that paused and may resume                ── */
function TrajectoryThread({ w = 200, h = 14, color = 'var(--accent)',
  broken = true, intensity = 0.6 }) {
  return (
    <svg width={w} height={h}>
      <line x1="2" y1={h/2} x2={w*0.4} y2={h/2}
        stroke={color} strokeWidth="1.5" opacity={intensity}
        strokeLinecap="round" />
      {broken && Array.from({length:5}).map((_,i) =>
        <circle key={i} cx={w*0.4 + 8 + i*8} cy={h/2} r="0.9"
          fill={color} opacity={intensity * (1 - i*0.15)} />
      )}
      <line x1={broken ? w*0.4 + 56 : w*0.4} y1={h/2} x2={w-2} y2={h/2}
        stroke={color} strokeWidth="1.5" opacity={intensity * 0.5}
        strokeLinecap="round" strokeDasharray={broken ? '0' : '0'} />
      <circle cx={w-2} cy={h/2} r="1.6" fill={color} opacity={intensity * 0.6} />
    </svg>
  );
}

/* ── Time spine — horizontal axis with tick markers ────── */
function TimeSpine({ w = 540, h = 28, marks = [], style = {} }) {
  // marks: [{ at: 0..1, label, color, ring }]
  return (
    <svg width={w} height={h} style={style}>
      <line x1="2" y1={h-7} x2={w-2} y2={h-7} stroke="var(--border-strong)"
        strokeWidth="0.8" />
      {marks.map((m, i) => {
        const x = m.at * (w - 4) + 2;
        return (
          <g key={i}>
            <line x1={x} y1={h-12} x2={x} y2={h-2} stroke={m.color || 'var(--fg-3)'}
              strokeWidth="0.8" opacity="0.5" />
            <circle cx={x} cy={h-7} r={m.ring ? 3 : 2}
              fill={m.color || 'var(--fg-2)'}
              stroke={m.ring ? m.color : 'none'} strokeWidth={m.ring ? 0.5 : 0}
              opacity={m.opacity ?? 1} />
          </g>
        );
      })}
    </svg>
  );
}

/* ── Mist gradient overlay — orientation drift ────────── */
function MistOverlay({ children, side = 'top', color = 'var(--accent)',
  intensity = 0.05, style = {} }) {
  const grad = side === 'top'
    ? `linear-gradient(180deg, rgba(212,168,67,${intensity}) 0%, transparent 60%)`
    : `linear-gradient(0deg, rgba(212,168,67,${intensity}) 0%, transparent 60%)`;
  return (
    <div style={{ position:'absolute', inset:0, background:grad,
      pointerEvents:'none', ...style }}>{children}</div>
  );
}

/* ── Open-loop chip — compact "unresolved" token ───────── */
function OpenLoop({ children, age = '3d', tone = 'var(--accent)', soft = false }) {
  return (
    <div style={{ display:'inline-flex', alignItems:'center', gap:6,
      padding:'3px 8px 3px 7px',
      background: soft ? 'transparent' : 'rgba(212,168,67,0.04)',
      border:`1px solid ${soft ? 'var(--border)' : 'rgba(212,168,67,0.25)'}`,
      borderLeft:`2px solid ${tone}`, borderRadius:2 }}>
      <div style={{ width:4, height:4, borderRadius:'50%', background:tone,
        boxShadow:`0 0 4px ${tone}` }} />
      <span style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
        whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis',
        maxWidth:240 }}>{children}</span>
      <span style={{ ...TT.mono, fontSize:8.5, color:'var(--fg-3)',
        letterSpacing:'0.05em', marginLeft:4 }}>{age}</span>
    </div>
  );
}

/* ── Pulse — subtle ambient indicator ──────────────────── */
function Pulse({ size = 8, color = 'var(--vault)', delay = 0 }) {
  return (
    <div style={{ position:'relative', width:size, height:size }}>
      <div style={{ position:'absolute', inset:0, borderRadius:'50%',
        background:color, animation:`tcpulse 2.4s ease ${delay}s infinite`,
        opacity:0.7 }} />
      <div style={{ position:'absolute', inset:size*0.25, borderRadius:'50%',
        background:color, boxShadow:`0 0 ${size}px ${color}` }} />
    </div>
  );
}

/* ── Section heading inside an artboard ────────────────── */
function ABHead({ children, tone = 'var(--accent)', sub }) {
  return (
    <div style={{ display:'flex', flexDirection:'column', gap:4, marginBottom:12 }}>
      <div style={{ ...TT.disp, fontSize:18, color:'var(--fg-1)',
        letterSpacing:'-0.01em', lineHeight:1.15 }}>{children}</div>
      {sub && <div style={{ ...TT.mono, fontSize:9, color:tone,
        letterSpacing:'0.1em', textTransform:'uppercase' }}>{sub}</div>}
      <div style={{ height:1, background:tone, opacity:0.4, width:48 }} />
    </div>
  );
}

/* ── Pill — generic small label ────────────────────────── */
function Pill({ children, tone = 'var(--fg-3)', filled = false, style = {} }) {
  return (
    <span style={{ display:'inline-flex', alignItems:'center', gap:4,
      padding:'2px 7px',
      background: filled ? `color-mix(in srgb, ${tone} 12%, transparent)` : 'transparent',
      border:`1px solid ${tone}`, borderRadius:2,
      ...TT.mono, fontSize:9, color:tone,
      letterSpacing:'0.06em', textTransform:'uppercase', ...style }}>{children}</span>
  );
}

/* ── inject keyframes once ─────────────────────────────── */
(function ensureKeyframes(){
  if (document.getElementById('tc-keyframes')) return;
  const s = document.createElement('style');
  s.id = 'tc-keyframes';
  s.textContent = `
    @keyframes tcpulse {
      0%, 100% { transform: scale(1); opacity: 0.8; }
      50% { transform: scale(2.1); opacity: 0; }
    }
    @keyframes tcdrift {
      0%, 100% { transform: translateY(0px); }
      50% { transform: translateY(-2px); }
    }
    @keyframes tcbreathe {
      0%, 100% { opacity: 0.45; }
      50% { opacity: 0.75; }
    }
  `;
  document.head.appendChild(s);
})();

Object.assign(window, {
  TT, Hairline, HandNote, Caption, MargDot, Line, Lines,
  DocStage, DecayArc, TensionHalo, TrajectoryThread, TimeSpine,
  MistOverlay, OpenLoop, Pulse, ABHead, Pill,
});
