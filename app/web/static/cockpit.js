/* BuilderOps cockpit renderer. Read-only: fetches the read-time join and
 * draws it. No state is stored anywhere — a reload recomputes everything. */
"use strict";

const RUNG_LABELS = {
  intention: "intention",
  capability: "capability",
  epic: "epic",
  slice: "slice",
  pr: "PR",
  ci_sha: "CI / sha",
  receipt: "receipt",
  tried: "tried by you",
};

// Locked rung order (mirrors app/builderops/cockpit_registry.py::RUNG_ORDER).
// The graph lens fans these out as columns.
const RUNG_ORDER = [
  "intention",
  "capability",
  "epic",
  "slice",
  "pr",
  "ci_sha",
  "receipt",
  "tried",
];

// The only stretch of the spine that is CI-forced/database-keyed in every
// case the registry can emit (app/builderops/cockpit_chain.py: slice/pr/
// ci_sha/receipt are always "proven" or "absent", never "derived" — capability
// and epic can be "proven" too, but only via a docs/prose edge, never a
// CI-forced one). The graph lens draws this stretch as the only solid
// backbone; everything else stays dashed/dotted regardless of its own class.
const MIDDLE_RUNGS = new Set(["slice", "pr", "ci_sha", "receipt"]);

// The four fixed questions the one-question lens pages through, in the
// charter's own locked order (docs/BUILDEROPS_COCKPIT/README.md).
const FOCUS_BAND_KEYS = ["working", "done", "flawed", "forgotten"];
const FOCUS_ROW_CAP = 5;

const CARD_CLASS = {
  working: "card-active",
  done: "card-done",
  flawed: "card-flaw",
  forgotten: "card-still",
  needs_you: "card-human",
};

const CLASS_CODE = { proven: "p", derived: "d", unlinked: "a", absent: "n" };

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function spineMarkup(rungs, large) {
  const parts = [];
  rungs.forEach((rung, index) => {
    const code = CLASS_CODE[rung.class] || "n";
    if (index > 0) parts.push(`<i class="${code}"></i>`);
    parts.push(`<b class="${code}" title="${esc(rung.name)}: ${esc(rung.class)}"></b>`);
  });
  return `<span class="spine${large ? " spine-lg" : ""}">${parts.join("")}</span>`;
}

function rungListMarkup(rungs) {
  const rows = rungs
    .map((rung) => {
      const code = CLASS_CODE[rung.class] || "n";
      return (
        `<li class="r-${code}"><span class="dot ${code}"></span>` +
        `<span class="r-name">${esc(RUNG_LABELS[rung.name] || rung.name)}</span>` +
        `<span class="r-val">${esc(rung.value || "")}</span>` +
        `<span class="r-cls">${esc(rung.class)}</span></li>`
      );
    })
    .join("");
  return `<ul class="rungs">${rows}</ul>`;
}

function chipRow(item) {
  const chips = [];
  if (item.repo) chips.push(`<span class="chip">${esc(item.repo)}</span>`);
  if (item.issue_number) chips.push(`<span class="chip">#${esc(item.issue_number)}</span>`);
  if (item.priority) chips.push(`<span class="chip">${esc(item.priority)}</span>`);
  if (item.status) chips.push(`<span class="chip">${esc(item.status)}</span>`);
  if (item.claimed_by) chips.push(`<span class="chip chip-lease">${esc(item.claimed_by)}</span>`);
  (item.labels || []).forEach((label) => {
    if (label === "agent:needs-human") {
      chips.push(`<span class="chip chip-agent">${esc(label)}</span>`);
    }
  });
  return chips.join("");
}

function cardMarkup(item) {
  const links = (item.links || [])
    .map(
      (url) =>
        `<a class="btn btn-out" href="${esc(url)}" target="_blank" rel="noopener">` +
        `<span class="k">out</span>open the authority</a>`
    )
    .join("");
  const receiptRung = (item.rungs || []).find((rung) => rung.name === "receipt");
  const receipt =
    receiptRung && receiptRung.class === "proven"
      ? `<div class="receipt">verification receipt · ${esc(receiptRung.value || "")}</div>`
      : `<div class="receipt none"><b>No verification receipt.</b> Updated ${esc(item.updated_at || "unknown")}.</div>`;
  return (
    `<details class="card ${CARD_CLASS[item.band] || ""}">` +
    `<summary><div class="meta">${spineMarkup(item.rungs || [])}${chipRow(item)}</div>` +
    `<h3>${esc(item.title)}</h3>` +
    `<p class="why">${esc(item.why_now || "")}</p></summary>` +
    `<div class="body">` +
    `<h4>Evidence spine</h4>${rungListMarkup(item.rungs || [])}` +
    (links ? `<div class="out">${links}</div>` : "") +
    `</div>${receipt}</details>`
  );
}

// Many-at-once (decision Q2 / AC4): past LANE_CARD_CAP cards in one lane, the
// rest fall to row form. Row form still carries the same evidence spine — it
// is denser, never hidden, and never a "+N more" silence. The surface gets
// longer, not shorter.
const LANE_CARD_CAP = 5;

function threadRowMarkup(item) {
  const idText = item.issue_number ? `#${esc(item.issue_number)}` : esc(item.id);
  const flaw = (item.flaws || [])[0];
  const tag = flaw
    ? `<span class="chip chip-flaw">${esc(flaw.predicate)}</span>`
    : `<span class="chip">${esc(item.status || "")}</span>`;
  return (
    `<div class="thread-row">` +
    `<span class="id">${idText}</span>` +
    spineMarkup(item.rungs || []) +
    `<span class="nm">${esc(item.title)}</span>${tag}` +
    `</div>`
  );
}

function laneCardsMarkup(items) {
  if (items.length <= LANE_CARD_CAP) {
    return items.map(cardMarkup).join("");
  }
  const cards = items.slice(0, LANE_CARD_CAP).map(cardMarkup).join("");
  const rows = items
    .slice(LANE_CARD_CAP)
    .map(threadRowMarkup)
    .join("");
  return `${cards}<div class="thread-rows">${rows}</div>`;
}

function bandMarkup(band) {
  const count = band.countable
    ? `<span class="band-count">${band.count}</span>`
    : `<span class="band-count" style="border-color:var(--destructive);color:var(--destructive)">cannot be counted</span>`;
  let bodyHtml = "";
  if (!band.countable) {
    bodyHtml = "";
  } else if (band.key === "done") {
    const cards = laneCardsMarkup(band.items);
    bodyHtml =
      `<div class="tier tier-invite"><div class="tier-head"><h3>Ready for you to use</h3>` +
      `<p>Delivered threads. The open link goes to the authority, never to a copy.</p></div>` +
      `<div class="lane-cards">${cards || ""}</div>` +
      (cards ? "" : `<p class="mono" style="color:var(--fg-3)">nothing delivered and unread</p>`) +
      `</div>` +
      `<div class="tier tier-archive"><div class="tier-head"><h3>Tried by you</h3>` +
      `<p>Empty by contract: no owner-acceptance receipt exists yet (INV-DG-7).` +
      ` Its emptiness is itself an honest claim.</p></div></div>`;
  } else if (band.items.length === 0) {
    bodyHtml = `<p class="mono" style="color:var(--fg-3)">0 — counted, not assumed</p>`;
  } else {
    bodyHtml = `<div class="lane"><div class="lane-cards">${laneCardsMarkup(
      band.items
    )}</div></div>`;
  }
  const number = band.key === "needs_you" ? "·" : String(bandIndex(band.key));
  return (
    `<section class="band"><div class="band-head">` +
    `<span class="band-no">${number}</span>` +
    `<h2 class="band-q">${esc(band.question)}</h2>${count}</div>${bodyHtml}</section>`
  );
}

function bandIndex(key) {
  return { working: 1, done: 2, flawed: 3, forgotten: 4 }[key] || "·";
}

// ---------------------------------------------------------------------------
// Graph lens: the same threads, re-projected as a fan-out across the eight
// rung columns. Every thread appears once in every column it has a rung for
// (never fewer, never more) — no new data, only a different reading order.
// ---------------------------------------------------------------------------

function allThreads(payload) {
  // One identity, many appearances (README): a thread can sit in its
  // position band *and* the flaws band. Dedupe by id so the graph lens never
  // draws the same thread twice.
  const seen = new Map();
  (payload.bands || []).forEach((band) => {
    (band.items || []).forEach((item) => {
      if (!seen.has(item.id)) seen.set(item.id, item);
    });
  });
  return Array.from(seen.values());
}

function graphNodeClass(rung, isMiddle) {
  if (!rung || rung.class === "absent") return "node-abs";
  if (isMiddle) {
    // The middle rungs (slice/pr/ci_sha/receipt) are only ever "proven",
    // "amber" (stale-downgraded), or "absent" in the registry — never
    // "derived" — so "proven" is the only case that earns the solid,
    // machine-keyed node style here.
    return rung.class === "proven" ? "node-p" : "node-ghost";
  }
  // Left of slice / the tried rung: never solid, even when the registry
  // classifies the edge "proven" (a docs-plane frontmatter edge is still a
  // prose/docs proof, not a CI-forced one — the graph lens's solid backbone
  // is reserved for the stretch CI itself enforces).
  return rung.class === "amber" ? "node-ghost" : "node-d";
}

function graphColumnMarkup(rungName, threads) {
  const isMiddle = MIDDLE_RUNGS.has(rungName);
  const nodes = threads
    .map((item) => {
      const rung = (item.rungs || []).find((r) => r.name === rungName);
      const cls = graphNodeClass(rung, isMiddle);
      const detail = rung && rung.value ? rung.value : rung ? rung.class : "no object";
      return (
        `<div class="node ${cls}" data-thread="${esc(item.id)}" data-rung-class="${esc(
          (rung && rung.class) || "absent"
        )}">${esc(item.title)}` +
        `<span class="n-id">${esc(item.issue_number ? "#" + item.issue_number : item.id)} · ${esc(
          detail
        )}</span></div>`
      );
    })
    .join("");
  return (
    `<div class="graf-col" data-rung="${esc(rungName)}"><h3>${esc(
      RUNG_LABELS[rungName] || rungName
    )}</h3>` +
    (nodes || `<p class="mono" style="color:var(--fg-3)">no threads</p>`) +
    `</div>`
  );
}

function renderGraph(payload) {
  const threads = allThreads(payload);
  document.getElementById("graph-cols").innerHTML = RUNG_ORDER.map((name) =>
    graphColumnMarkup(name, threads)
  ).join("");
}

// ---------------------------------------------------------------------------
// One-question-at-a-time lens: the same four bands, one screen each, in the
// charter's fixed order. Answer first as a claim, then at most five rows,
// then an explicit counted deferral into the bands lens — never a silent cut.
// ---------------------------------------------------------------------------

function focusClaim(bandKey, band) {
  if (!band.countable) {
    return "This cannot be counted: the source it depends on is unavailable.";
  }
  const n = band.count;
  const plural = n === 1 ? "" : "s";
  if (bandKey === "working") {
    return n === 0 ? "Nothing is in motion right now." : `${n} thread${plural} in motion right now.`;
  }
  if (bandKey === "done") {
    return n === 0
      ? "Nothing delivered and unread by you."
      : `${n} thing${plural} delivered and unread by you.`;
  }
  if (bandKey === "flawed") {
    return n === 0
      ? "No flaw fired on what could be read."
      : `${n} flaw${plural} fired on what could be read.`;
  }
  return n === 0
    ? "Nothing has stalled without closure."
    : `${n} thread${plural} stalled without closure.`;
}

function focusRowMarkup(item) {
  const idText = item.issue_number ? `#${esc(item.issue_number)}` : esc(item.id);
  return (
    `<li><span class="id">${idText}</span><span>${esc(item.title)}</span>` +
    `<span class="mono">${esc(item.why_now || "")}</span></li>`
  );
}

function focusScreenMarkup(index, band) {
  const screenNo = index + 1;
  const items = band.countable ? band.items : [];
  const shown = items.slice(0, FOCUS_ROW_CAP);
  const extra = items.length - shown.length;
  const rows = shown.map(focusRowMarkup).join("");
  const deferral =
    extra > 0
      ? `<label class="btn btn-out" for="lens-bands"><span class="k">+${extra}</span>and ${extra} more in the register</label>`
      : "";
  const nextIndex = index + 1;
  const nav =
    nextIndex < FOCUS_BAND_KEYS.length
      ? `<label class="btn btn-out" for="fq${nextIndex + 1}"><span class="k">next</span>question ${
          nextIndex + 1
        } of 4</label>`
      : `<label class="btn btn-out" for="lens-bands"><span class="k">done</span>Open the register</label>`;
  const back =
    index > 0 ? `<label class="btn" for="fq${index}">Back</label>` : "";
  return (
    `<div class="focus" id="f${screenNo}">` +
    `<p class="eyebrow">Question ${screenNo} of 4</p>` +
    `<p class="q">${esc(band.question)}</p>` +
    `<p class="a${band.countable ? "" : " warn"}">${esc(focusClaim(band.key, band))}</p>` +
    (rows
      ? `<ul class="focus-list">${rows}</ul>`
      : `<p class="mono" style="color:var(--fg-3)">nothing to show</p>`) +
    deferral +
    `<div class="focus-nav">${nav}${back}</div>` +
    `</div>`
  );
}

function renderFocus(payload) {
  const bandByKey = new Map((payload.bands || []).map((band) => [band.key, band]));
  const html = FOCUS_BAND_KEYS.map((key, index) => {
    const band = bandByKey.get(key) || {
      key,
      question: "",
      countable: false,
      count: null,
      items: [],
    };
    return focusScreenMarkup(index, band);
  }).join("");
  document.getElementById("focus-screens").innerHTML = html;
}

function sourceMarkup(source) {
  const cls = source.state === "unavailable" ? " dead" : source.state === "stale" ? " stale" : "";
  const read = source.last_successful_read
    ? `read ${source.last_successful_read}`
    : "no successful read";
  return (
    `<div class="src${cls}"><b>${esc(source.name)}</b>` +
    `<span>${esc(source.state)} · ${esc(read)}</span>` +
    `<span>${esc(source.detail || "")}</span></div>`
  );
}

function render(payload) {
  const claimSection = document.getElementById("claim");
  const anyDead = (payload.sources || []).some((s) => s.state === "unavailable");
  claimSection.classList.toggle("bad", payload.claim.kind === "refused");
  claimSection.classList.toggle("warn", payload.claim.kind !== "refused" && anyDead);
  document.getElementById("claim-text").textContent = payload.claim.text;
  document.getElementById("generated-at").textContent = `as of ${payload.generated_at}`;
  document.getElementById("sources").innerHTML = (payload.sources || [])
    .map(sourceMarkup)
    .join("");
  document.getElementById("unread-planes").textContent = payload.unread_planes.length
    ? `planes not read in v1 (their absence is stated, not hidden): ${payload.unread_planes.join(" · ")}`
    : "";
  document.getElementById("bands").innerHTML = (payload.bands || [])
    .map(bandMarkup)
    .join("");
  const wrap = document.getElementById("unclassified-wrap");
  const rows = payload.unclassified || [];
  wrap.hidden = rows.length === 0;
  document.getElementById("unclassified").innerHTML = rows
    .map(
      (row) =>
        `<div class="still-row"><span class="id">${esc(row.id)}</span>` +
        `<span class="nm">${esc(row.title)}</span>` +
        `<span class="ag">status: ${esc(row.status)}</span>` +
        `<span class="mv">${esc(row.reason)}</span><span></span></div>`
    )
    .join("");

  // Same payload, two more re-projections. Neither performs a fetch: the
  // lens switcher (pure CSS :has()) only chooses which of the three already-
  // rendered panes is visible.
  renderGraph(payload);
  renderFocus(payload);
}

function renderFetchFailure(error) {
  const claimSection = document.getElementById("claim");
  claimSection.classList.add("bad");
  document.getElementById("claim-text").textContent =
    "I cannot say what is in motion: the registry endpoint could not be read.";
  document.getElementById("sources").innerHTML = sourceMarkup({
    name: "cockpit-api",
    state: "unavailable",
    last_successful_read: null,
    detail: String(error),
  });
}

fetch("/api/cockpit/registry", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch(renderFetchFailure);
