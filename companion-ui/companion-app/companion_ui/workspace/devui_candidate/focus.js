"use strict";

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
  correlation: "Correlation",
  coverage: "Coverage",
  evidence_id: "Evidence reference",
  evidence_state: "Evidence state",
  freshness: "Freshness",
  kind: "Kind",
  legality: "Legality",
  limitation: "Limitation",
  linkage: "Linkage",
  locator: "Source location",
  observation_ref: "Observation reference",
  owner_state: "Owner state",
  provider: "Provider",
  read_watermark: "Read watermark",
  reason: "Reason",
  receipt_ref: "Receipt reference",
  risk_id: "Risk reference",
  source_id: "Source reference",
  source_ref: "Source reference",
  source_type: "Source type",
  state: "State",
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
  "observation_ref",
  "read_watermark",
  "receipt_ref",
  "risk_id",
  "observed_at",
  "source_id",
  "source_ref",
  "source_type",
  "version",
  "workflow_ref",
]);
const EVIDENCE_AXIS_FIELDS = new Set([
  "availability",
  "freshness",
  "coverage",
  "completeness",
  "cardinality",
  "linkage",
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
  if (value == null) return "Unavailable";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function isEvidenceAxisVector(value) {
  return typeof value?.claim === "string" &&
    Object.keys(value || {}).filter((key) => EVIDENCE_AXIS_FIELDS.has(key)).length >= 3;
}

function ownerRows(parent, value, {hideEvidenceAxes = false} = {}) {
  const list = document.createElement("div");
  list.className = "owner-summary";
  const hideAxes = hideEvidenceAxes && isEvidenceAxisVector(value);
  Object.keys(value || {}).forEach((key) => {
    if (
      TECHNICAL_FIELDS.has(key) ||
      (hideAxes && EVIDENCE_AXIS_FIELDS.has(key)) ||
      !Object.prototype.hasOwnProperty.call(FIELD_LABELS, key) ||
      (value[key] !== null && typeof value[key] === "object")
    ) return;
    const row = document.createElement("p");
    row.className = "owner-fact";
    text(row, "b", labelFor(key));
    text(row, "span", scalarValue(value[key]));
    list.appendChild(row);
  });
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

function rows(parent, value) {
  const list = document.createElement("ul");
  list.className = "rungs";
  Object.keys(value || {}).forEach((key) => {
    const row = document.createElement("li");
    text(row, "b", key);
    text(row, "code", typeof value[key] === "string" ? value[key] : JSON.stringify(value[key]));
    list.appendChild(row);
  });
  parent.appendChild(list);
}

function render(testid, value) {
  const target = document.querySelector(`[data-testid="${testid}"] > div`);
  const hideEvidenceAxes = testid === "focus-governing-sources" || testid === "focus-evidence";
  if (Array.isArray(value)) {
    if (!value.length) text(target, "p", "No server-declared entries.", "empty");
    value.forEach((entry) => renderEntry(target, entry, hideEvidenceAxes));
    return;
  }
  renderEntry(target, value || {}, hideEvidenceAxes);
}

function renderEntry(parent, value, hideEvidenceAxes = false) {
  const entry = document.createElement("div");
  entry.className = "focus-entry";
  ownerRows(entry, value, {hideEvidenceAxes});
  const details = document.createElement("details");
  details.className = "technical-disclosure";
  const summary = text(details, "summary", "Inspect source and technical details");
  summary.dataset.testid = "devui-technical-disclosure";
  rows(details, value);
  entry.appendChild(details);
  parent.appendChild(entry);
}

const query = new URLSearchParams(window.location.search);
const entries = Array.from(query.entries());
const subject = entries.length === 1 && entries[0][0] === "subject" && entries[0][1] ? entries[0][1] : null;
const subjectNode = document.querySelector('[data-testid="focus-subject"]');
if (subject) {
  subjectNode.dataset.subject = subject;
  subjectNode.textContent = subject;
}

const focusRead = subject
  ? fetch(`/api/devui/focus?subject=${encodeURIComponent(subject)}`, {method: "GET", cache: "no-store"})
  : Promise.reject(new Error("One governed subject is required."));

focusRead.then(async (response) => {
  if (!response.ok) throw new Error(`Focus read failed for ${subject} (${response.status}).`);
  const payload = await response.json();
  if (!payload.subject || payload.subject.stable_id !== subject) throw new Error(`Focus response did not match ${subject}.`);
  const shell = document.querySelector('[data-testid="devui-focus"]');
  shell.dataset.serverState = String(payload.state || "unclassified");
  subjectNode.textContent = payload.subject.title || subject;
  render("focus-owner-intent", payload.owner_intent);
  render("focus-governing-sources", payload.governing_sources);
  render("focus-evidence", payload.evidence);
  render("focus-receipts", payload.receipts);
  render("focus-risks", payload.risks);
  render("focus-next-step", payload.next_legal_step);
  render("focus-execution", payload.execution_observations);
  render("focus-conversation", payload.conversation_port);
  render("focus-limitations", payload.limitations);
  const state = document.querySelector('[data-testid="focus-load-state"]');
  state.dataset.state = "loaded";
  state.textContent = `Server state: ${shell.dataset.serverState}`;
}).catch((error) => {
  const shell = document.querySelector('[data-testid="devui-focus"]');
  shell.classList.add("bad");
  shell.dataset.serverState = "read_error";
  const state = document.querySelector('[data-testid="focus-load-state"]');
  state.dataset.state = "error";
  state.setAttribute("role", "alert");
  state.textContent = error.message;
});
