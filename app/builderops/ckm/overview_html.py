"""Self-contained, non-authoritative HTML overview for the CKM."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Mapping, Sequence

from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmCapability,
    CkmEvidenceEdge,
    CkmFinding,
    utc_now,
)
from app.builderops.ckm.store import CkmStore


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _watermarks(values: Mapping[str, str]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{_e(key)}={_e(value)}" for key, value in sorted(values.items()))


def _forest(capabilities: Sequence[CkmCapability]) -> list[tuple[int, CkmCapability]]:
    known = {item.id for item in capabilities}
    children: dict[str | None, list[CkmCapability]] = {}
    for item in capabilities:
        parent = item.parent_id if item.parent_id in known else None
        children.setdefault(parent, []).append(item)
    for values in children.values():
        values.sort(key=lambda item: (item.name.casefold(), item.id))
    result: list[tuple[int, CkmCapability]] = []
    visited: set[str] = set()

    def visit(item: CkmCapability, depth: int) -> None:
        if item.id in visited:
            return
        visited.add(item.id)
        result.append((depth, item))
        for child in children.get(item.id, []):
            visit(child, depth + 1)

    for root in children.get(None, []):
        visit(root, 0)
    for item in sorted(capabilities, key=lambda value: (value.name.casefold(), value.id)):
        visit(item, 0)
    return result


def _band(aggregate: float | None) -> str:
    if aggregate is None:
        return "unknown"
    if aggregate < 0.4:
        return "critical"
    if aggregate < 0.7:
        return "watch"
    return "healthy"


def _edge_counts(edges: Sequence[CkmEvidenceEdge]) -> tuple[int, int]:
    return (
        sum(edge.lifecycle == "confirmed" for edge in edges),
        sum(edge.lifecycle == "candidate" for edge in edges),
    )


def _citation_source(citation: Mapping[str, object]) -> str:
    source_ref = citation.get("source_ref")
    artifact = citation.get("artifact")
    if source_ref is None and isinstance(artifact, Mapping):
        source_ref = artifact.get("source_ref")
    lifecycle = citation.get("lifecycle")
    edge = citation.get("edge")
    if lifecycle is None and isinstance(edge, Mapping):
        lifecycle = edge.get("lifecycle")
    suffix = f" · {lifecycle}" if lifecycle in {"candidate", "confirmed"} else ""
    return f"{source_ref or 'evidence snapshot'}{suffix}"


def _dimension_markup(
    dimension: str,
    score: float,
    citations: Sequence[Mapping[str, object]],
    candidate_share: float,
) -> str:
    percent = max(0.0, min(100.0, score * 100.0))
    citation_items = "".join(
        f"<li>{_e(_citation_source(citation))}</li>" for citation in citations
    ) or "<li>No selected citations.</li>"
    return f"""
      <section class="dimension" data-dimension="{_e(dimension)}">
        <div class="dimension-label"><span>{_e(dimension.replace('_', ' '))}</span><strong>{score:.2f}</strong></div>
        <div class="dimension-track" role="progressbar" aria-label="{_e(dimension)}" aria-valuemin="0" aria-valuemax="1" aria-valuenow="{score:.3f}">
          <span class="dimension-bar" style="width:{percent:.1f}%"></span>
        </div>
        <small>{len(citations)} citation(s) · candidate share {candidate_share:.1%}</small>
        <details class="citations"><summary>Citations</summary><ul>{citation_items}</ul></details>
      </section>"""


def _mini_dimensions_markup(scores: Mapping[str, float] | None) -> str:
    """Render the seven maturity dimensions in the always-visible card summary."""

    bars = []
    for dimension in MATURITY_DIMENSIONS:
        score = float(scores[dimension]) if scores is not None else None
        percent = max(0.0, min(100.0, score * 100.0)) if score is not None else 0.0
        label = (
            f"{dimension.replace('_', ' ')}: {score:.2f}"
            if score is not None
            else f"{dimension.replace('_', ' ')}: not assessed"
        )
        bars.append(
            f'<span class="mini-dimension{" mini-unknown" if score is None else ""}" '
            f'title="{_e(label)}" aria-label="{_e(label)}" '
            f'style="--score:{percent:.1f}%"></span>'
        )
    return (
        '<span class="mini-dimensions" aria-label="Seven-dimension maturity">'
        + "".join(bars)
        + "</span>"
    )


def _evidence_markup(edges: Sequence[CkmEvidenceEdge]) -> str:
    if not edges:
        return '<p class="empty">No linked evidence.</p>'
    items = []
    for edge in sorted(edges, key=lambda item: (item.lifecycle, item.source_ref, item.id)):
        items.append(
            f"""<li class="evidence evidence-{_e(edge.lifecycle)}">
              <span class="badge">{_e(edge.lifecycle)}</span>
              <code>{_e(edge.evidence_kind)}</code> · {_e(edge.source_ref)}
              <div class="basis">Basis: {_e(edge.basis)}</div>
            </li>"""
        )
    return f"<ul class=\"evidence-list\">{''.join(items)}</ul>"


def _finding_markup(findings: Sequence[CkmFinding]) -> str:
    if not findings:
        return '<p class="empty">No current findings.</p>'
    return "<ul class=\"finding-list\">" + "".join(
        f"<li><span class=\"badge\">{_e(item.kind)}</span> "
        f"<strong>{_e(item.dimension.replace('_', ' '))}</strong>: {_e(item.statement)} "
        f"<small>({len(item.citations)} citation(s))</small></li>"
        for item in findings
    ) + "</ul>"


def _capability_markup(
    store: CkmStore,
    capability: CkmCapability,
    *,
    depth: int,
) -> str:
    edges = store.list_evidence_edges_for_capability(capability.id)
    findings = store.list_findings_for_capability(capability.id)
    confirmed, candidate = _edge_counts(edges)
    assessment = store.latest_assessment_for_capability(capability.id)
    projection = store.assessment_for_projection(capability.id) if assessment else None
    aggregate = float(assessment.aggregate) if assessment else None
    band = _band(aggregate)
    flags: list[str] = []
    if projection and projection.stale_relative_to_evidence:
        flags.append('<span class="flag flag-stale">STALE relative to evidence</span>')
    if assessment and assessment.low_confidence:
        flags.append('<span class="flag flag-low">LOW CONFIDENCE</span>')
    if assessment:
        max_candidate_share = max(assessment.candidate_shares.values())
        flags.append(
            f'<span class="flag flag-candidate">candidate share {max_candidate_share:.1%}</span>'
        )
    else:
        flags.append('<span class="flag flag-candidate">candidate share unavailable</span>')
    dimensions = ""
    if assessment:
        dimensions = "".join(
            _dimension_markup(
                dimension,
                float(assessment.scores[dimension]),
                assessment.citations[dimension],
                float(assessment.candidate_shares[dimension]),
            )
            for dimension in MATURITY_DIMENSIONS
        )
    else:
        dimensions = '<p class="empty">Assessment missing.</p>'
    aggregate_text = f"{aggregate:.2f}" if aggregate is not None else "not assessed"
    return f"""
    <article class="capability band-{band}" data-capability-id="{_e(capability.id)}" data-aggregate-band="{band}" style="--depth:{depth}">
      <details>
        <summary>
          <span class="tree-name">{_e(capability.name)}</span>
          {_mini_dimensions_markup(assessment.scores if assessment else None)}
          <span class="aggregate">{_e(aggregate_text)}</span>
          <span class="lifecycle">{_e(capability.lifecycle)}</span>
        </summary>
        <div class="capability-body">
          <p>{_e(capability.definition)}</p>
          <p>Boundary: <strong>{_e(capability.boundary_ref or '—')}</strong> · Evidence: <strong>{confirmed} confirmed / {candidate} candidate</strong></p>
          <div class="flags">{''.join(flags)}</div>
          <div class="dimensions">{dimensions}</div>
          <details class="drilldown"><summary>Evidence and basis</summary>{_evidence_markup(edges)}</details>
          <details class="drilldown"><summary>Findings</summary>{_finding_markup(findings)}</details>
        </div>
      </details>
    </article>"""


def render_overview_html(
    store: CkmStore,
    *,
    generated_at: str | None = None,
) -> str:
    """Render one self-contained CKM projection without mutating the store."""

    timestamp = generated_at or utc_now()
    capabilities = store.list_capabilities()
    capability_by_id = {item.id: item for item in capabilities}
    all_findings = store.list_findings()
    cards = "".join(
        _capability_markup(store, capability, depth=depth)
        for depth, capability in _forest(capabilities)
    ) or '<p class="empty">No capabilities in the CKM store.</p>'
    gap_items = "".join(
        f"<li><span class=\"badge\">{_e(item.kind)}</span> "
        f"<strong>{_e(capability_by_id[item.capability_id].name if item.capability_id in capability_by_id else item.capability_id)}</strong> · "
        f"{_e(item.dimension.replace('_', ' '))}: {_e(item.statement)}</li>"
        for item in all_findings
    ) or "<li>No current findings.</li>"
    watermark_text = _watermarks(store.current_watermark_set())
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CKM Development Overview</title>
  <style>
    :root {{ color-scheme: light dark; --bg:#0b1020; --panel:#141b2d; --text:#eef2ff; --muted:#a9b4ca; --line:#33405d; --critical:#ef4444; --watch:#f59e0b; --healthy:#22c55e; --unknown:#64748b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 ui-sans-serif,system-ui,sans-serif; }}
    main, footer {{ width:min(1180px,calc(100% - 32px)); margin:0 auto; }}
    header {{ padding:38px 0 20px; }} h1,h2 {{ margin:.2em 0; }} .subtitle,.empty,small {{ color:var(--muted); }}
    .legend,.flags {{ display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; }}
    .legend span,.flag,.badge,.lifecycle,.aggregate {{ border:1px solid var(--line); border-radius:999px; padding:2px 8px; font-size:12px; }}
    .capability {{ margin:8px 0 8px calc(var(--depth) * 22px); border:1px solid var(--line); border-left:5px solid var(--unknown); border-radius:10px; background:var(--panel); }}
    .band-critical {{ border-left-color:var(--critical); }} .band-watch {{ border-left-color:var(--watch); }} .band-healthy {{ border-left-color:var(--healthy); }}
    summary {{ cursor:pointer; }} .capability > details > summary {{ display:flex; gap:10px; align-items:center; padding:12px 14px; }}
    .tree-name {{ flex:1; font-weight:700; }} .capability-body {{ border-top:1px solid var(--line); padding:14px; }}
    .mini-dimensions {{ display:grid; grid-template-columns:repeat(7,18px); gap:3px; }}
    .mini-dimension {{ width:18px; height:8px; border-radius:8px; background:linear-gradient(to right,#60a5fa var(--score),#25304a var(--score)); }}
    .mini-unknown {{ background:var(--unknown); opacity:.55; }}
    .dimensions {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:10px; margin:14px 0; }}
    .dimension {{ border:1px solid var(--line); border-radius:8px; padding:10px; }} .dimension-label {{ display:flex; justify-content:space-between; gap:8px; }}
    .dimension-track {{ height:8px; margin:7px 0; border-radius:8px; background:#25304a; overflow:hidden; }} .dimension-bar {{ display:block; height:100%; background:#60a5fa; }}
    .flag-stale,.flag-low {{ border-color:var(--watch); color:#fbbf24; }} .flag-candidate {{ border-color:#60a5fa; }}
    .drilldown,.citations {{ margin-top:10px; }} .evidence-list,.finding-list {{ padding-left:20px; }} .evidence-list li,.finding-list li {{ margin:7px 0; }} .basis {{ color:var(--muted); margin-left:8px; }}
    .gaps-panel {{ margin:24px 0; padding:16px; border:1px solid var(--line); border-radius:10px; background:var(--panel); }}
    footer {{ margin-top:28px; padding:18px 0 36px; border-top:1px solid var(--line); color:var(--muted); overflow-wrap:anywhere; }}
    @media (max-width:650px) {{ .capability {{ margin-left:calc(var(--depth) * 8px); }} .capability > details > summary {{ align-items:flex-start; flex-wrap:wrap; }} .mini-dimensions {{ order:4; width:100%; }} }}
  </style>
</head>
<body>
  <main>
    <header><h1>Development Overview</h1><p class="subtitle">Capability Knowledge Model maturity heatmap and cited drill-down.</p></header>
    <section aria-labelledby="map-heading">
      <h2 id="map-heading">Capability map</h2>
      <div class="legend"><span>healthy ≥ 0.70</span><span>watch 0.40–0.69</span><span>critical &lt; 0.40</span><span>unknown</span></div>
      <div class="capability-tree">{cards}</div>
    </section>
    <section class="gaps-panel" aria-labelledby="gaps-heading"><h2 id="gaps-heading">Current gaps</h2><ul>{gap_items}</ul></section>
  </main>
  <footer class="projection-footer">
    <strong>Generated projection (BuilderOps CKM). Not source of truth.</strong><br>
    Generated: {_e(timestamp)}<br>
    Watermarks: {watermark_text}<br>
    Candidate and confirmed evidence remain distinct. Regenerate from the CKM store; do not edit this file as authority.
  </footer>
</body>
</html>
"""


def write_overview_html(
    store: CkmStore,
    output_path: Path,
    *,
    generated_at: str | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_overview_html(store, generated_at=generated_at),
        encoding="utf-8",
    )
    return output_path
