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

function bandMarkup(band) {
  const count = band.countable
    ? `<span class="band-count">${band.count}</span>`
    : `<span class="band-count" style="border-color:var(--destructive);color:var(--destructive)">cannot be counted</span>`;
  let bodyHtml = "";
  if (!band.countable) {
    bodyHtml = "";
  } else if (band.key === "done") {
    const cards = band.items.map(cardMarkup).join("");
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
    bodyHtml = `<div class="lane"><div class="lane-cards">${band.items
      .map(cardMarkup)
      .join("")}</div></div>`;
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
