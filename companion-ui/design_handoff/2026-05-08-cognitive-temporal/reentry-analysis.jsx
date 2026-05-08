/* ============================================================
   Re-entry mist — analysis & comparison artboards
   ============================================================ */

/* ── Premise / cover ──────────────────────────────────── */
function RM_Premise() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'22px 26px', display:'flex', flexDirection:'column', gap:14 }}>
      <ABHead tone="var(--accent)" sub="re-entry mist · phenomenology study">
        Returning, after three days
      </ABHead>
      <div style={{ ...TT.disp, fontStyle:'italic', fontSize:15,
        color:'var(--fg-2)', lineHeight:1.55, maxWidth:'94%' }}>
        The user opens a document they last touched seventy-six hours ago.
        The system must reconstitute continuity — gently — without claiming
        their attention.
      </div>
      <Hairline />
      <div>
        <Caption color="var(--accent)" size={8.5}>refining</Caption>
        <div style={{ ...TT.ui, fontSize:12, color:'var(--fg-1)',
          lineHeight:1.55, marginTop:6 }}>
          The phenomenology of three alternative re-entry mists. Each makes
          a different bet about what a returning thinker actually needs.
        </div>
      </div>
      <Hairline />
      <div style={{ display:'grid', gridTemplateColumns:'auto 1fr', gap:'8px 16px',
        ...TT.ui, fontSize:11, color:'var(--fg-2)', lineHeight:1.45 }}>
        <Caption color="var(--accent)" size={8.5}>A · whisper</Caption>
        <span>continuity lives in the margin · doc readable from t=0</span>
        <Caption color="var(--cyan)" size={8.5}>B · breath</Caption>
        <span>continuity is one half-finished sentence · everything else latent</span>
        <Caption color="var(--vault)" size={8.5}>C · recall</Caption>
        <span>continuity is atmospheric · the room remembers, not the UI</span>
      </div>
      <Hairline />
      <div style={{ ...TT.mono, fontSize:9.5, color:'var(--fg-3)',
        lineHeight:1.55, letterSpacing:'0.02em' }}>
        constraints held: no dashboards · no badges · no notifications · no
        productivity chrome · no chat surface · calmness above density
      </div>
    </div>
  );
}

/* ── Attentional cadence — three columns ──────────────── */
function RM_Cadence() {
  const phases = [
    { t:'t=0', label:'opens doc' },
    { t:'+200ms', label:'first breath' },
    { t:'+1.5s', label:'orient' },
    { t:'+3s', label:'read' },
    { t:'first key', label:'commit' },
    { t:'+30s', label:'session settles' },
  ];
  const A = [
    'doc fully visible, dimmed 5%',
    'gold breath behind last line · caret echo',
    'four whispers fade in column-right, staggered',
    'whispers stable · doc primary',
    'breath dissolves · whispers dim to 30%',
    'whispers fade to ambient marginalia dots',
  ];
  const B = [
    'doc dim 45% · headline visible',
    'half-sentence ghosts in at cursor',
    'silence · only caret breathes',
    'three numerals fade in below margin',
    'sentence becomes editable · numerals hold',
    'numerals contract to 3 dots in lower margin',
  ];
  const C = [
    'doc full opacity · warm tint over page',
    'four corner glyphs glow once, then settle',
    'gravity well rises in lower margin',
    'tint stabilises · glyphs dim to ambient',
    'tint fades to baseline · glyphs hold',
    'only gravity well + caret breath remain',
  ];

  const Col = ({ title, tone, items }) => (
    <div style={{ display:'flex', flexDirection:'column', gap:0 }}>
      <div style={{ ...TT.ui, fontSize:11, fontWeight:500, color:tone,
        marginBottom:8, paddingBottom:6,
        borderBottom:`1px solid ${tone}`, opacity:0.95 }}>{title}</div>
      {items.map((s,i) => (
        <div key={i} style={{ padding:'8px 0',
          borderTop: i === 0 ? 'none' : '1px solid var(--border)',
          ...TT.ui, fontSize:10.5, color:'var(--fg-1)', lineHeight:1.4 }}>
          {s}
        </div>
      ))}
    </div>
  );

  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 22px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--accent)" sub="what surfaces when · what fades first">
        Attentional cadence
      </ABHead>
      <div style={{ display:'grid', gridTemplateColumns:'90px 1fr 1fr 1fr',
        gap:14 }}>
        <div>
          <div style={{ height:25 }} />
          {phases.map((p,i) => (
            <div key={i} style={{ padding:'8px 0',
              borderTop: i === 0 ? 'none' : '1px solid var(--border)' }}>
              <Caption color="var(--cyan)" size={9}>{p.t}</Caption>
              <div style={{ ...TT.ui, fontSize:10, color:'var(--fg-2)',
                marginTop:2 }}>{p.label}</div>
            </div>
          ))}
        </div>
        <Col title="A · whisper" tone="var(--accent)" items={A} />
        <Col title="B · breath"  tone="var(--cyan)"   items={B} />
        <Col title="C · recall"  tone="var(--vault)"  items={C} />
      </div>
    </div>
  );
}

/* ── Density comparison — payload weight ──────────────── */
function RM_Density() {
  const rows = [
    { aspect:'words on screen', A:'~38', B:'~22', C:'~6' },
    { aspect:'distinct surfaces', A:'1 column', B:'1 sentence', C:'4 glyphs + tint' },
    { aspect:'numerals shown', A:'3', B:'3 (delayed)', C:'0' },
    { aspect:'labels shown',  A:'4', B:'3 (delayed)', C:'4 glyphs' },
    { aspect:'doc dimming',   A:'5%',  B:'45%', C:'0%' },
    { aspect:'modal feel',    A:'low',  B:'medium', C:'none' },
    { aspect:'time to read',  A:'3-4s', B:'1-2s', C:'0s' },
    { aspect:'overload risk', A:'medium · 4 streams in periphery',
      B:'low · single focus', C:'very low · entirely felt' },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 22px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--cyan)" sub="minimum viable continuity payload">
        Density comparison
      </ABHead>
      <div style={{ display:'grid',
        gridTemplateColumns:'150px 1fr 1fr 1fr', gap:8,
        ...TT.ui, fontSize:11 }}>
        <div />
        <div style={{ color:'var(--accent)', ...TT.mono, fontSize:9,
          letterSpacing:'0.1em', textTransform:'uppercase' }}>A · whisper</div>
        <div style={{ color:'var(--cyan)', ...TT.mono, fontSize:9,
          letterSpacing:'0.1em', textTransform:'uppercase' }}>B · breath</div>
        <div style={{ color:'var(--vault)', ...TT.mono, fontSize:9,
          letterSpacing:'0.1em', textTransform:'uppercase' }}>C · recall</div>
        {rows.map((r,i) => (
          <React.Fragment key={i}>
            <div style={{ borderTop:'1px solid var(--border)', padding:'7px 0',
              color:'var(--fg-3)', ...TT.mono, fontSize:9.5,
              letterSpacing:'0.05em' }}>{r.aspect}</div>
            <div style={{ borderTop:'1px solid var(--border)', padding:'7px 0',
              color:'var(--fg-1)' }}>{r.A}</div>
            <div style={{ borderTop:'1px solid var(--border)', padding:'7px 0',
              color:'var(--fg-1)' }}>{r.B}</div>
            <div style={{ borderTop:'1px solid var(--border)', padding:'7px 0',
              color:'var(--fg-1)' }}>{r.C}</div>
          </React.Fragment>
        ))}
      </div>
      <div style={{ marginTop:6, ...TT.mono, fontSize:9, color:'var(--fg-3)',
        letterSpacing:'0.06em', lineHeight:1.55 }}>
        all three resolve the same four questions · they differ in how much
        of the answer is told vs. felt · C tells almost nothing and trusts
        memory to do the rest
      </div>
    </div>
  );
}

/* ── Dissolve behavior comparison ─────────────────────── */
function RM_Dissolve() {
  const rows = [
    { phase:'first keystroke',
      A:'gold breath fades in 240ms · whispers desaturate to 30%',
      B:'sentence becomes black-ink editable · numerals hold',
      C:'warm tint slides to baseline over 600ms · glyphs unchanged' },
    { phase:'first scroll',
      A:'whispers detach from doc, become margin sticky',
      B:'numerals follow viewport bottom-left',
      C:'glyphs stay anchored to viewport corners' },
    { phase:'first selection',
      A:'whispers dim further to 15%',
      B:'numerals shrink to lone digit-dots',
      C:'no change · selection dominates instead' },
    { phase:'after 30s of work',
      A:'whispers → marginalia dots (3-6px) at original positions',
      B:'numerals → 3 small dots in lower-left margin',
      C:'tint baseline · gravity well dims to 20% but persists' },
    { phase:'esc / dismiss',
      A:'whispers gone · marginalia dots remain ambient',
      B:'numerals gone · sentence-anchor underline remains',
      C:'corner glyphs disappear · gravity well + tint persist' },
  ];

  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 22px', display:'flex', flexDirection:'column', gap:10 }}>
      <ABHead tone="var(--amber)" sub="how each variant lets go">
        Dissolve semantics
      </ABHead>
      <div style={{ display:'grid',
        gridTemplateColumns:'120px 1fr 1fr 1fr', gap:10,
        ...TT.ui, fontSize:10.5 }}>
        <div />
        <div style={{ color:'var(--accent)', ...TT.mono, fontSize:9,
          letterSpacing:'0.1em', textTransform:'uppercase' }}>A · whisper</div>
        <div style={{ color:'var(--cyan)', ...TT.mono, fontSize:9,
          letterSpacing:'0.1em', textTransform:'uppercase' }}>B · breath</div>
        <div style={{ color:'var(--vault)', ...TT.mono, fontSize:9,
          letterSpacing:'0.1em', textTransform:'uppercase' }}>C · recall</div>
        {rows.map((r,i) => (
          <React.Fragment key={i}>
            <div style={{ borderTop:'1px solid var(--border)', padding:'8px 0',
              color:'var(--amber)', ...TT.mono, fontSize:9,
              letterSpacing:'0.06em' }}>{r.phase}</div>
            <div style={{ borderTop:'1px solid var(--border)', padding:'8px 0',
              color:'var(--fg-1)', lineHeight:1.45 }}>{r.A}</div>
            <div style={{ borderTop:'1px solid var(--border)', padding:'8px 0',
              color:'var(--fg-1)', lineHeight:1.45 }}>{r.B}</div>
            <div style={{ borderTop:'1px solid var(--border)', padding:'8px 0',
              color:'var(--fg-1)', lineHeight:1.45 }}>{r.C}</div>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

/* ── Ambient persistence — what remains ──────────────── */
function RM_Persistence() {
  const items = [
    { v:'A',  tone:'var(--accent)',
      keeps:[
        'marginalia dots at every prior whisper position',
        'caret echo (a tiny gold tick) where you stopped',
        'one open-loop glyph for each unresolved synthesis',
      ],
      removes:[
        'all whisper text',
        'gold breath',
        'numeric counts',
      ] },
    { v:'B',  tone:'var(--cyan)',
      keeps:[
        'underline at sentence-anchor (resume jump)',
        'three faint dots in lower-left margin',
        'caret breathing at original line',
      ],
      removes:[
        'the half-sentence itself',
        'numerals',
        'doc dimming',
      ] },
    { v:'C',  tone:'var(--vault)',
      keeps:[
        'warm room tint, dimmed 60%',
        'gravity well at 20% (unresolved still pulls)',
        'caret breath at last line',
      ],
      removes:[
        'corner glyphs',
        'all explicit answers',
        'tooltips on hover',
      ] },
  ];
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'20px 22px', display:'flex', flexDirection:'column', gap:14 }}>
      <ABHead tone="var(--vault)" sub="what stays after dissolve · ambient layer">
        Ambient persistence
      </ABHead>
      <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-2)',
        lineHeight:1.5, marginBottom:2 }}>
        The mist is gone, but the document is not the same as a fresh document.
        Each variant leaves a different kind of trace — something the user can
        return to without summoning a card.
      </div>
      {items.map((r) => (
        <div key={r.v} style={{ display:'grid',
          gridTemplateColumns:'70px 1fr 1fr', gap:12,
          paddingTop:12, borderTop:'1px solid var(--border)' }}>
          <div>
            <div style={{ ...TT.disp, fontSize:22, color:r.tone,
              lineHeight:1 }}>{r.v}</div>
            <Caption color={r.tone} size={8.5} style={{ marginTop:4,
              display:'block' }}>variant</Caption>
          </div>
          <div>
            <Caption color="var(--fg-3)" size={8.5}>keeps</Caption>
            <ul style={{ margin:'4px 0 0 14px', padding:0,
              ...TT.ui, fontSize:11, color:'var(--fg-1)', lineHeight:1.55 }}>
              {r.keeps.map((k,i) => <li key={i}>{k}</li>)}
            </ul>
          </div>
          <div>
            <Caption color="var(--fg-3)" size={8.5}>lets go</Caption>
            <ul style={{ margin:'4px 0 0 14px', padding:0,
              ...TT.ui, fontSize:11, color:'var(--fg-2)', lineHeight:1.55 }}>
              {r.removes.map((k,i) => <li key={i}>{k}</li>)}
            </ul>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Recommendation ───────────────────────────────────── */
function RM_Recommendation() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      padding:'22px 26px', display:'flex', flexDirection:'column', gap:14 }}>
      <ABHead tone="var(--vault)" sub="quietest · highest continuity">
        Recommendation — Variant C, tempered by B
      </ABHead>

      <div style={{ ...TT.disp, fontStyle:'italic', fontSize:15,
        color:'var(--fg-1)', lineHeight:1.55, maxWidth:'96%' }}>
        The room should remember before the UI does.
      </div>

      <Hairline />

      <div>
        <Caption color="var(--vault)" size={8.5}>why C wins on quietness</Caption>
        <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
          lineHeight:1.55, marginTop:6 }}>
          C is the only variant where the document is fully readable with
          zero text added. The four questions are still answered — but
          atmospherically: warm tint = "you have been here before"; gravity
          well = "something is still pulling"; caret breath = "you stopped
          here"; corner glyphs = "ask if you want to know more."
          Cognition does not have to read anything to feel oriented.
        </div>
      </div>

      <div>
        <Caption color="var(--cyan)" size={8.5}>where C is too thin · borrow from B</Caption>
        <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
          lineHeight:1.55, marginTop:6 }}>
          On returns where momentum was mid-sentence, atmosphere is not
          enough — the user needs the literal half-thought back. Adopt
          B's single ghost-sentence at the cursor, but only when the
          stop-state was textual. If the user paused on a thought (no
          unfinished sentence), C alone is sufficient.
        </div>
      </div>

      <div>
        <Caption color="var(--accent)" size={8.5}>where A belongs</Caption>
        <div style={{ ...TT.ui, fontSize:11.5, color:'var(--fg-1)',
          lineHeight:1.55, marginTop:6 }}>
          A is the right shape for absences past 14 days, when atmosphere
          alone cannot reconstitute context. Promote A automatically once
          the latency ladder crosses "long mist."
        </div>
      </div>

      <Hairline />

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
        <div>
          <Caption color="var(--fg-3)" size={8.5}>composite default</Caption>
          <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
            lineHeight:1.55, marginTop:6 }}>
            <b>2h – 3d</b> · C alone<br/>
            <b>3d – 14d</b> · C + B's ghost-sentence (if mid-text)<br/>
            <b>&gt; 14d</b> · A's column appears in addition
          </div>
        </div>
        <div>
          <Caption color="var(--fg-3)" size={8.5}>invariant</Caption>
          <div style={{ ...TT.ui, fontSize:11, color:'var(--fg-1)',
            lineHeight:1.55, marginTop:6 }}>
            no card ever centers on the document.
            re-entry is felt at the periphery.
            cognition returns to the document, not to the system.
          </div>
        </div>
      </div>
    </div>
  );
}

window.RM_Premise = RM_Premise;
window.RM_Cadence = RM_Cadence;
window.RM_Density = RM_Density;
window.RM_Dissolve = RM_Dissolve;
window.RM_Persistence = RM_Persistence;
window.RM_Recommendation = RM_Recommendation;
