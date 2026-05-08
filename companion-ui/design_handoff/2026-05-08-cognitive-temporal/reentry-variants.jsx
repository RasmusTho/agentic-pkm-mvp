/* ============================================================
   Re-entry mist — three phenomenological variants
   ============================================================
   A: Margin Whisper      lateral · spatial · marginalia
   B: Resumption Breath   single sentence · gravity · progressive
   C: Atmospheric Recall  no card · room-like · ambient fixtures
   ============================================================ */

/* shared bits ─────────────────────────────────────────── */
function DocBody({ dim = 0.45, title = 'Network boundary' }) {
  return (
    <div style={{ opacity: dim }}>
      <div style={{ ...TT.disp, fontSize:18, color:'var(--fg-1)',
        marginBottom:10, letterSpacing:'-0.01em' }}>{title}</div>
      <Lines rows={3} last="58%" h={5.5} gap={8} />
      <div style={{ height:14 }} />
      <Lines rows={4} last="42%" h={5.5} gap={8} />
      <div style={{ height:14 }} />
      <Lines rows={2} last="74%" h={5.5} gap={8} />
    </div>
  );
}

function DocChrome({ where = 'Projects/Q2-arch.md', resume = '3d 4h ago' }) {
  return (
    <div style={{ padding:'9px 18px', borderBottom:'1px solid var(--border)',
      display:'flex', alignItems:'center', gap:10 }}>
      <Caption color="var(--fg-3)">{where}</Caption>
      <Caption color="var(--vault)">·  re-entry · {resume}</Caption>
      <div style={{ flex:1 }} />
      <Caption color="var(--fg-3)" size={8.5}>esc dissolves</Caption>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   VARIANT A — MARGIN WHISPER
   ─────────────────────────────────────────────────────────
   Phenomenology: the four answers do not aggregate into a
   card. They surface as faint, position-anchored whispers
   in the right margin — each pinned to where in the doc the
   thought lived. The document is fully readable from first
   pixel; the mist is just a horizontal gold breath at the
   last cursor line.
   ─────────────────────────────────────────────────────────*/
function VariantA_Wire() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      <DocChrome />
      <div style={{ flex:1, display:'grid',
        gridTemplateColumns:'1fr 220px', position:'relative',
        backgroundImage:
          'linear-gradient(rgba(0,212,232,0.012) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(0,212,232,0.012) 1px, transparent 1px)',
        backgroundSize:'32px 32px' }}>

        {/* doc body, fully readable from first pixel */}
        <div style={{ padding:'18px 22px 18px 28px', position:'relative' }}>
          <div>
            <div style={{ ...TT.disp, fontSize:18, color:'var(--fg-1)',
              marginBottom:10, letterSpacing:'-0.01em' }}>Network boundary</div>
            <Lines rows={3} last="58%" h={5.5} gap={8} />
            <div style={{ height:14 }} />
            {/* the line where momentum stopped — lit, not hidden */}
            <div style={{ position:'relative' }}>
              <Lines rows={2} last="74%" h={5.5} gap={8} />
              {/* gold breath behind the last line — the only "mist" */}
              <div style={{ position:'absolute', left:-12, right:-220, top:-4,
                height:32,
                background:'linear-gradient(90deg, rgba(212,168,67,0.10) 0%, rgba(212,168,67,0.04) 60%, transparent 100%)',
                pointerEvents:'none' }} />
              {/* caret echo */}
              <div style={{ position:'absolute', left:'58%', top:14, width:1,
                height:14, background:'var(--accent)',
                boxShadow:'0 0 6px var(--accent)', animation:'tcbreathe 3.2s ease infinite' }} />
            </div>
            <div style={{ height:14 }} />
            <Lines rows={4} last="42%" h={5.5} gap={8} />
          </div>
        </div>

        {/* margin column — four whispers, position-pinned */}
        <div style={{ borderLeft:'1px dashed var(--border)',
          padding:'18px 16px', position:'relative' }}>
          <div style={{ position:'absolute', top:18, left:-1, height:46,
            width:2, background:'var(--accent)', opacity:0.5 }} />

          {/* doing */}
          <div style={{ marginBottom:22 }}>
            <Caption color="var(--accent)" size={8.5}>doing</Caption>
            <div style={{ ...TT.disp, fontStyle:'italic', fontSize:12,
              color:'var(--fg-1)', lineHeight:1.4, marginTop:3, opacity:0.85 }}>
              reconciling three sources on partition tolerance
            </div>
          </div>

          {/* stopped — pinned to the lit line */}
          <div style={{ marginBottom:22, marginTop:38 }}>
            <Caption color="var(--cyan)" size={8.5}>stopped at</Caption>
            <div style={{ ...TT.disp, fontStyle:'italic', fontSize:11,
              color:'var(--fg-2)', lineHeight:1.4, marginTop:3 }}>
              "…does this hold when latency exceeds 200ms?"
            </div>
          </div>

          {/* unresolved — counts only */}
          <div style={{ marginBottom:22 }}>
            <Caption color="var(--amber)" size={8.5}>unresolved</Caption>
            <div style={{ display:'flex', gap:8, marginTop:5,
              alignItems:'baseline' }}>
              <span style={{ ...TT.disp, fontSize:18, color:'var(--amber)',
                lineHeight:1 }}>1</span>
              <span style={{ ...TT.ui, fontSize:10, color:'var(--fg-2)' }}>open synthesis</span>
            </div>
            <div style={{ display:'flex', gap:8, marginTop:3,
              alignItems:'baseline' }}>
              <span style={{ ...TT.disp, fontSize:14, color:'var(--fg-2)',
                lineHeight:1 }}>2</span>
              <span style={{ ...TT.ui, fontSize:10, color:'var(--fg-2)' }}>staged edits</span>
            </div>
          </div>

          {/* changed */}
          <div>
            <Caption color="var(--vault)" size={8.5}>since</Caption>
            <div style={{ ...TT.ui, fontSize:10.5, color:'var(--fg-2)',
              lineHeight:1.45, marginTop:3 }}>
              vault sync 2h ago.<br/>
              Hugin found 1 adjacent note.
            </div>
          </div>
        </div>

        {/* ─ annotations ─ */}
        <div style={{ position:'absolute', top:14, left:14, pointerEvents:'none' }}>
          <HandNote color="var(--accent)" size={11}>doc readable from t=0<br/>no card to dismiss</HandNote>
        </div>
        <div style={{ position:'absolute', bottom:36, left:36, pointerEvents:'none' }}>
          <HandNote color="var(--cyan)" size={10.5}>gold breath = where you stopped<br/>only "mist" in the doc</HandNote>
        </div>
        <div style={{ position:'absolute', top:74, right:240, pointerEvents:'none',
          textAlign:'right' }}>
          <HandNote color="var(--accent)" size={10.5}>whispers stay during<br/>the whole session,<br/>fade after 30s</HandNote>
        </div>
      </div>
      <div style={{ position:'absolute', bottom:8, left:'50%',
        transform:'translateX(-50%)', ...TT.mono, fontSize:9,
        color:'var(--fg-3)', letterSpacing:'0.1em', textTransform:'uppercase',
        opacity:0.55 }}>
        A · margin whisper — lateral, spatial, never modal
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   VARIANT B — RESUMPTION BREATH
   ─────────────────────────────────────────────────────────
   Phenomenology: a single sentence appears in place — the
   exact half-finished thought, ghosted, with a quiet caret.
   Nothing else for ~3 seconds. If the user pauses, three
   numerals quietly emerge in the lower margin: open / staged
   / changed. No labels, no card edge, no separators.
   ─────────────────────────────────────────────────────────*/
function VariantB_Wire() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      <DocChrome />
      <div style={{ flex:1, padding:'24px 38px', position:'relative',
        backgroundImage:
          'linear-gradient(rgba(0,212,232,0.012) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(0,212,232,0.012) 1px, transparent 1px)',
        backgroundSize:'32px 32px' }}>

        {/* doc body — readable, dimmed only along the path of attention */}
        <div style={{ opacity:0.55 }}>
          <div style={{ ...TT.disp, fontSize:18, color:'var(--fg-1)',
            marginBottom:10, letterSpacing:'-0.01em' }}>Network boundary</div>
          <Lines rows={3} last="58%" h={5.5} gap={8} />
          <div style={{ height:14 }} />
          <Lines rows={2} last="74%" h={5.5} gap={8} />
        </div>

        {/* the single sentence — ghosted in situ */}
        <div style={{ marginTop:18, position:'relative' }}>
          <div style={{ ...TT.disp, fontStyle:'italic', fontSize:18,
            color:'var(--fg-1)', lineHeight:1.5, opacity:0.78,
            letterSpacing:'-0.005em', maxWidth:'78%' }}>
            …does this hold when latency exceeds 200ms,
            <span style={{ color:'var(--fg-2)' }}>&nbsp;or are we partitioning past the consistency budget</span>
            <span style={{ display:'inline-block', verticalAlign:'-2px',
              width:1.5, height:18, background:'var(--accent)',
              marginLeft:3, boxShadow:'0 0 6px var(--accent)',
              animation:'tcbreathe 2.4s ease infinite' }} />
          </div>
          {/* a single faint underline marking the resume point */}
          <div style={{ height:1, width:42, background:'var(--accent)',
            opacity:0.45, marginTop:10 }} />
        </div>

        {/* document continues, dimmer */}
        <div style={{ opacity:0.32, marginTop:22 }}>
          <Lines rows={4} last="42%" h={5.5} gap={8} />
        </div>

        {/* the latent triplet — emerges only after ~3s pause */}
        <div style={{ position:'absolute', bottom:30, left:38, right:38,
          display:'flex', alignItems:'baseline', gap:32, opacity:0.78 }}>
          <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
            <span style={{ ...TT.disp, fontSize:24, color:'var(--amber)',
              lineHeight:1 }}>1</span>
            <span style={{ ...TT.ui, fontSize:10, color:'var(--fg-3)',
              letterSpacing:'0.04em' }}>open</span>
          </div>
          <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
            <span style={{ ...TT.disp, fontSize:24, color:'var(--cyan)',
              lineHeight:1 }}>2</span>
            <span style={{ ...TT.ui, fontSize:10, color:'var(--fg-3)',
              letterSpacing:'0.04em' }}>staged</span>
          </div>
          <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
            <span style={{ ...TT.disp, fontSize:24, color:'var(--vault)',
              lineHeight:1 }}>1</span>
            <span style={{ ...TT.ui, fontSize:10, color:'var(--fg-3)',
              letterSpacing:'0.04em' }}>since</span>
          </div>
          <div style={{ marginLeft:'auto', ...TT.mono, fontSize:8.5,
            color:'var(--fg-3)', letterSpacing:'0.1em',
            textTransform:'uppercase', opacity:0.7 }}>
            tap any number to expand
          </div>
        </div>

        {/* annotations */}
        <div style={{ position:'absolute', top:90, right:18,
          textAlign:'right', pointerEvents:'none' }}>
          <HandNote color="var(--accent)" size={11}>one sentence<br/>no chrome, no card</HandNote>
        </div>
        <div style={{ position:'absolute', bottom:74, left:18,
          pointerEvents:'none' }}>
          <HandNote color="var(--cyan)" size={10.5}>numerals fade in only<br/>after 3s of stillness<br/>otherwise: never seen</HandNote>
        </div>
        <div style={{ position:'absolute', top:170, right:170,
          pointerEvents:'none', textAlign:'right' }}>
          <HandNote color="var(--amber)" size={10}>greyed continuation<br/>= what AI heard you<br/>not-yet-say</HandNote>
        </div>
      </div>
      <div style={{ position:'absolute', bottom:8, left:'50%',
        transform:'translateX(-50%)', ...TT.mono, fontSize:9,
        color:'var(--fg-3)', letterSpacing:'0.1em', textTransform:'uppercase',
        opacity:0.55 }}>
        B · resumption breath — one sentence, then silence
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
   VARIANT C — ATMOSPHERIC RECALL
   ─────────────────────────────────────────────────────────
   Phenomenology: no card, no margin column. The page
   itself remembers — a faint warm tint, a single gravity
   well at the bottom margin (unresolved synthesis pulling),
   and the cursor breathing at its last position. The four
   answers are accessible only by hovering the corner glyphs;
   otherwise nothing speaks.
   ─────────────────────────────────────────────────────────*/
function VariantC_Wire() {
  return (
    <div style={{ width:'100%', height:'100%', background:'var(--bg-base)',
      display:'flex', flexDirection:'column', position:'relative', overflow:'hidden' }}>
      <DocChrome />
      <div style={{ flex:1, position:'relative',
        backgroundImage:
          'radial-gradient(ellipse at 50% 50%, rgba(212,168,67,0.04) 0%, transparent 70%),' +
          'linear-gradient(rgba(0,212,232,0.012) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(0,212,232,0.012) 1px, transparent 1px)',
        backgroundSize:'auto, 32px 32px, 32px 32px' }}>

        {/* doc body, full opacity except where attention rests */}
        <div style={{ padding:'22px 60px' }}>
          <div style={{ ...TT.disp, fontSize:18, color:'var(--fg-1)',
            marginBottom:10, letterSpacing:'-0.01em', opacity:0.95 }}>
            Network boundary
          </div>
          <div style={{ opacity:0.85 }}>
            <Lines rows={3} last="58%" h={5.5} gap={8} />
          </div>
          <div style={{ height:14 }} />
          <div style={{ position:'relative' }}>
            <div style={{ opacity:0.95 }}>
              <Lines rows={2} last="74%" h={5.5} gap={8} />
            </div>
            <div style={{ position:'absolute', left:'74%', top:8, width:1.5,
              height:14, background:'var(--accent)',
              boxShadow:'0 0 8px var(--accent)',
              animation:'tcbreathe 2.8s ease infinite' }} />
          </div>
          <div style={{ height:14 }} />
          <div style={{ opacity:0.85 }}>
            <Lines rows={4} last="42%" h={5.5} gap={8} />
          </div>
        </div>

        {/* gravity well — unresolved synthesis felt as weight */}
        <div style={{ position:'absolute', left:0, right:0, bottom:0, height:120,
          background:
            'radial-gradient(ellipse 280px 90px at 30% 100%, rgba(240,144,48,0.14) 0%, transparent 70%),' +
            'radial-gradient(ellipse 200px 60px at 70% 100%, rgba(57,232,125,0.06) 0%, transparent 70%)',
          pointerEvents:'none' }} />

        {/* corner fixtures — four glyphs, one per question, no labels */}
        {/* top-left: doing */}
        <div style={{ position:'absolute', top:18, left:18,
          display:'flex', flexDirection:'column', alignItems:'flex-start', gap:6 }}>
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <div style={{ width:6, height:6, background:'var(--accent)',
              boxShadow:'0 0 8px var(--accent)' }} />
            <Caption color="var(--accent)" size={8.5}>thread</Caption>
          </div>
        </div>

        {/* top-right: changed */}
        <div style={{ position:'absolute', top:18, right:18,
          display:'flex', flexDirection:'column', alignItems:'flex-end', gap:6 }}>
          <div style={{ display:'flex', alignItems:'center', gap:8 }}>
            <Caption color="var(--vault)" size={8.5}>since</Caption>
            <div style={{ width:6, height:6, borderRadius:'50%',
              background:'var(--vault)', boxShadow:'0 0 8px var(--vault)' }} />
          </div>
        </div>

        {/* bottom-left: unresolved (visible weight, not number) */}
        <div style={{ position:'absolute', bottom:18, left:18,
          display:'flex', alignItems:'center', gap:8 }}>
          <TensionHalo size={26} level={0.55} color="var(--amber)" />
          <Caption color="var(--amber)" size={8.5}>weight</Caption>
        </div>

        {/* bottom-right: stopped — a small caret echo */}
        <div style={{ position:'absolute', bottom:18, right:18,
          display:'flex', alignItems:'center', gap:8 }}>
          <Caption color="var(--cyan)" size={8.5}>caret</Caption>
          <div style={{ width:1, height:11, background:'var(--cyan)',
            boxShadow:'0 0 6px var(--cyan)',
            animation:'tcbreathe 3.6s ease infinite' }} />
        </div>

        {/* annotations */}
        <div style={{ position:'absolute', top:54, left:60, pointerEvents:'none' }}>
          <HandNote color="var(--accent)" size={11}>warm tint = "this room<br/>has been used before"</HandNote>
        </div>
        <div style={{ position:'absolute', bottom:78, left:'46%',
          pointerEvents:'none' }}>
          <HandNote color="var(--amber)" size={11}>gravity well<br/>= unresolved pulling<br/>(felt, not labeled)</HandNote>
        </div>
        <div style={{ position:'absolute', top:38, right:88,
          pointerEvents:'none', textAlign:'right' }}>
          <HandNote color="var(--vault)" size={10.5}>hover any corner<br/>to read its answer<br/>otherwise: silent</HandNote>
        </div>
      </div>
      <div style={{ position:'absolute', bottom:8, left:'50%',
        transform:'translateX(-50%)', ...TT.mono, fontSize:9,
        color:'var(--fg-3)', letterSpacing:'0.1em', textTransform:'uppercase',
        opacity:0.55 }}>
        C · atmospheric recall — a room that remembers
      </div>
    </div>
  );
}

window.VariantA_Wire = VariantA_Wire;
window.VariantB_Wire = VariantB_Wire;
window.VariantC_Wire = VariantC_Wire;
