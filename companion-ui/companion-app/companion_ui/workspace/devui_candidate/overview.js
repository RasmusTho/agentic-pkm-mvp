"use strict";

const AXES = ["availability", "freshness", "completeness", "cardinality", "linkage"];
const FIELD_LABELS = {
  actor_class: "Actor",
  availability: "Availability",
  authority: "Authority",
  authority_ref: "Authority source",
  cardinality: "Cardinality",
  captured_at: "Captured",
  claim: "Claim",
  claim_id: "Claim reference",
  completeness: "Completeness",
  composed_at: "Composed",
  coverage: "Coverage",
  display_label: "Title",
  evidence_id: "Evidence reference",
  evidence_state: "Evidence state",
  freshness: "Freshness",
  kind: "Kind",
  legality: "Legality",
  limitation: "Limitation",
  linkage: "Linkage",
  locator: "Source location",
  navigation_refs: "Navigation",
  owner_state: "Owner state",
  provider: "Provider",
  read_watermark: "Read watermark",
  reason: "Reason",
  receipt_ref: "Receipt reference",
  risk_id: "Risk reference",
  role: "Provider role",
  snapshot: "Snapshot",
  source_id: "Source reference",
  source_ref: "Source reference",
  source_type: "Source type",
  state: "State",
  status: "Status",
  subject_ref: "Subject reference",
  summary: "Summary",
  title: "Title",
  version: "Source version",
  workflow_ref: "Workflow reference",
};
const TECHNICAL_FIELDS = new Set([
  "authority_ref",
  "captured_at",
  "claim_id",
  "composed_at",
  "correlation",
  "evidence_id",
  "evidence_state",
  "locator",
  "navigation_refs",
  "read_watermark",
  "receipt_ref",
  "risk_id",
  "source_id",
  "source_ref",
  "source_type",
  "subject_ref",
  "version",
  "workflow_ref",
  ...AXES,
]);

function text(parent, tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null ? "" : String(value);
  parent.appendChild(node);
  return node;
}

function labelFor(key) {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  return key
    .split("_")
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
}

function scalarValue(value) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function sourceWarning(value) {
  const warningPhrases = {
    availability: {
      unavailable: "the source is unavailable",
      refused: "the source refused the read",
      unsupported: "the source does not support this read",
    },
    freshness: {
      stale: "the source is stale",
      unknown: "source timing is unknown",
    },
    completeness: {
      partial: "required content is incomplete",
      unread: "required content was not read",
      missing: "required content is missing",
    },
    cardinality: {
      not_measured: "source item count was not measured",
    },
    linkage: {
      unlinked: "source relation is unlinked",
      not_assessed: "source relation was not assessed",
    },
  };
  const signals = Object.entries(warningPhrases)
    .filter(([key, phrases]) =>
      Object.prototype.hasOwnProperty.call(value || {}, key) &&
      value[key] !== null &&
      Object.prototype.hasOwnProperty.call(phrases, value[key])
    )
    .map(([key, phrases]) => phrases[value[key]]);
  if (!signals.length) return null;
  return `Source evidence requires attention: ${signals
    .join("; ")}.`;
}

function ownerRows(parent, value) {
  const list = document.createElement("div");
  list.className = "owner-summary";
  Object.keys(value || {}).forEach((key) => {
    if (
      TECHNICAL_FIELDS.has(key) ||
      key === "limitations" ||
      value[key] == null ||
      !Object.prototype.hasOwnProperty.call(FIELD_LABELS, key) ||
      (value[key] !== null && typeof value[key] === "object")
    ) return;
    const row = document.createElement("p");
    row.className = "owner-fact";
    text(row, "b", labelFor(key));
    text(row, "span", scalarValue(value[key]));
    list.appendChild(row);
  });
  const warning = sourceWarning(value);
  if (warning) text(list, "p", warning, "owner-warning");
  if (!list.childElementCount && Object.keys(value || {}).length) {
    const row = document.createElement("p");
    row.className = "owner-fact";
    text(row, "b", "Source details");
    text(row, "span", "Available for inspection");
    list.appendChild(row);
  }
  if (list.childElementCount) parent.appendChild(list);
  return list;
}

function technicalDetails(parent, summary, value, omitAxes = false) {
  const details = document.createElement("details");
  details.className = "technical-disclosure";
  const label = text(details, "summary", summary);
  label.dataset.testid = "devui-technical-disclosure";
  rows(details, value, omitAxes);
  parent.appendChild(details);
  return details;
}

function providerStates(parent, value) {
  const states = Array.isArray(value && value.provider_states) ? value.provider_states : [];
  states.forEach((state) => {
    const section = document.createElement("section");
    section.className = "provider-state";
    section.dataset.providerRole = String(state.role || "");
    text(section, "h3", state.role || "Provider");
    rows(section, state);
    parent.appendChild(section);
  });
}

function trustSummary(parent, value) {
  const states = Array.isArray(value && value.provider_states) ? value.provider_states : [];
  const summary = document.createElement("div");
  summary.className = "owner-summary";
  const count = document.createElement("p");
  count.className = "owner-fact";
  text(count, "b", "Provider sources");
  text(count, "span", String(states.length));
  summary.appendChild(count);
  const refused = states
    .filter((state) => state && state.status === "refused")
    .map((state) => state.role || state.provider || "unknown provider");
  if (refused.length) {
    text(
      summary,
      "p",
      `Source refused the read: ${refused.join(", ")}.`,
      "owner-warning",
    );
  }
  parent.appendChild(summary);
}

function renderTrustFrame(parent, value) {
  trustSummary(parent, value);
  const details = document.createElement("details");
  details.className = "technical-disclosure";
  const label = text(details, "summary", "Inspect trust frame");
  label.dataset.testid = "devui-technical-disclosure";
  providerStates(details, value);
  parent.appendChild(details);
}

function matrix(parent, value) {
  providerStates(parent, value);
  const axes = AXES.filter((axis) => Object.prototype.hasOwnProperty.call(value || {}, axis));
  if (!axes.length) return;
  const grid = document.createElement("div");
  grid.className = "matrix";
  axes.forEach((axis) => {
    const cell = document.createElement("div");
    cell.className = "axis";
    cell.dataset.axis = axis;
    cell.dataset.value = String(value[axis]);
    text(cell, "b", labelFor(axis));
    text(cell, "span", value[axis]);
    grid.appendChild(cell);
  });
  parent.appendChild(grid);
}

function rows(parent, value, omitAxes = false) {
  const list = document.createElement("ul");
  list.className = "rungs";
  Object.keys(value || {}).forEach((key) => {
    if (key === "navigation_refs" || (omitAxes && AXES.includes(key))) return;
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
  ownerRows(body, {
    display_label: item.display_label,
    reason: item.reason,
  });
  technicalDetails(body, "Inspect subject source details", item.subject_ref || {});
  (item.evidence || []).forEach((evidence) => {
    const evidenceBox = document.createElement("div");
    evidenceBox.className = "evidence-entry";
    ownerRows(evidenceBox, evidence);
    const details = document.createElement("details");
    details.className = "technical-disclosure";
    const summary = text(details, "summary", "Inspect evidence details");
    summary.dataset.testid = "devui-technical-disclosure";
    matrix(details, evidence);
    rows(details, evidence, true);
    evidenceBox.appendChild(details);
    body.appendChild(evidenceBox);
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
  shell.dataset.serverState = "loaded";
  const trust = document.querySelector('[data-testid="overview-trust-matrix"]');
  renderTrustFrame(trust, payload.trust_frame || {});
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
