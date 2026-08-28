"use strict";

const AXES = ["availability", "freshness", "completeness", "cardinality", "linkage"];

function text(parent, tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null ? "" : String(value);
  parent.appendChild(node);
  return node;
}

function matrix(parent, value) {
  const grid = document.createElement("div");
  grid.className = "matrix";
  AXES.forEach((axis) => {
    if (!Object.prototype.hasOwnProperty.call(value || {}, axis)) return;
    const cell = document.createElement("div");
    cell.className = "axis";
    cell.dataset.axis = axis;
    cell.dataset.value = String(value[axis]);
    text(cell, "b", axis);
    text(cell, "span", value[axis]);
    grid.appendChild(cell);
  });
  parent.appendChild(grid);
}

function rows(parent, value) {
  const list = document.createElement("ul");
  list.className = "rungs";
  Object.keys(value || {}).forEach((key) => {
    if (key === "navigation_refs") return;
    const row = document.createElement("li");
    text(row, "b", key);
    text(row, "code", typeof value[key] === "string" ? value[key] : JSON.stringify(value[key]));
    list.appendChild(row);
  });
  parent.appendChild(list);
}

function verifiedFocusHref(item) {
  const refs = Array.isArray(item.navigation_refs) ? item.navigation_refs : [];
  if (refs.length !== 1 || refs[0].kind !== "focus" || refs[0].status !== "available") return null;
  const ref = refs[0].navigation_ref;
  if (!ref || ref.source_id !== item.subject_ref.source_id || typeof ref.locator !== "string") return null;
  const target = new URL(ref.locator, window.location.origin);
  if (target.origin !== window.location.origin || target.pathname !== "/devui/focus" || target.hash) return null;
  const pairs = Array.from(target.searchParams.entries());
  if (pairs.length !== 1 || pairs[0][0] !== "subject" || pairs[0][1] !== item.subject_ref.source_id) return null;
  return ref.locator;
}

function renderItem(parent, item) {
  const card = document.createElement("article");
  card.className = "card";
  text(card, "h3", item.display_label, "card-title").dataset.testid = "overview-card-title";
  text(card, "p", item.reason, "why");
  const body = document.createElement("div");
  body.className = "body";
  rows(body, item.subject_ref);
  (item.evidence || []).forEach((evidence) => {
    matrix(body, evidence);
    rows(body, evidence);
  });
  (item.limitations || []).forEach((limitation) => text(body, "p", limitation, "empty"));
  card.appendChild(body);
  const href = verifiedFocusHref(item);
  if (href) {
    const link = text(card, "a", "Open Focus", "btn btn-out");
    link.href = href;
    link.dataset.testid = "overview-focus-link";
    const key = document.createElement("span");
    key.className = "k";
    key.textContent = "in";
    link.prepend(key);
  }
  parent.appendChild(card);
}

function renderZone(testid, items) {
  const parent = document.querySelector(`[data-testid="${testid}"]`);
  if (!items.length) text(parent, "p", "No server-declared items.", "empty");
  items.forEach((item) => renderItem(parent, item));
}

function renderLimitations(items) {
  const list = document.querySelector('[data-testid="overview-limitations"] ul');
  if (!items.length) text(list, "li", "No server-declared limitations.", "empty");
  items.forEach((item) => text(list, "li", typeof item === "string" ? item : JSON.stringify(item)));
}

fetch("/api/devui/overview", {method: "GET", cache: "no-store"}).then(async (response) => {
  if (!response.ok) throw new Error(`Overview read failed (${response.status}).`);
  const payload = await response.json();
  const shell = document.querySelector('[data-testid="overview-shell"]');
  shell.dataset.serverState = String(payload.state || "unclassified");
  const trust = document.querySelector('[data-testid="overview-trust-matrix"]');
  matrix(trust, payload.trust_frame || {});
  rows(trust, payload.trust_frame || {});
  renderZone("overview-now", payload.now || []);
  renderZone("overview-needs-you", payload.needs_you || []);
  renderZone("overview-ready-to-try", payload.ready_to_try || []);
  renderLimitations(payload.limitations || []);
  const state = document.querySelector('[data-testid="overview-load-state"]');
  state.dataset.state = "loaded";
  state.textContent = `Server state: ${shell.dataset.serverState}`;
}).catch((error) => {
  const shell = document.querySelector('[data-testid="overview-shell"]');
  shell.classList.add("bad");
  shell.dataset.serverState = "read_error";
  const state = document.querySelector('[data-testid="overview-load-state"]');
  state.dataset.state = "error";
  state.setAttribute("role", "alert");
  state.textContent = error.message;
});
