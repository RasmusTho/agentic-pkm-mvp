"use strict";

function text(parent, tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null ? "" : String(value);
  parent.appendChild(node);
  return node;
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
  if (Array.isArray(value)) {
    if (!value.length) text(target, "p", "No server-declared entries.", "empty");
    value.forEach((entry) => rows(target, entry));
    return;
  }
  rows(target, value || {});
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
