"use strict";
// Deliberately not a generic check/status publisher: one immutable legacy head only.
const crypto = require("crypto");
const fs = require("fs");
const TARGET = Object.freeze({repository: "RasmusTho/agentic-pkm-mvp", prNumber: 4052, head: "a159571da2ce9068131810aedc1ea05107d7bfaf", title: "Fix CKM metric schema bundle refusal"});
const TRUSTED = new Set(["OWNER", "MEMBER", "COLLABORATOR"]);
const AUTHORITY_MARKER = "verified issue-set merge authority:";
const PHASE_MARKER = "verified issue-set merge phase:";
const PHASE_FIELDS = ["authority_sha256", "body_sha256", "closed_issues", "contract", "head_sha", "merge_commit_sha", "phase", "pr_number", "reopened_unauthorized_issues", "repository", "run_id"].sort();
const canonicalJson = value => Array.isArray(value) ? `[${value.map(canonicalJson).join(",")}]` : value !== null && typeof value === "object" ? `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}` : JSON.stringify(value);
const sha256 = value => crypto.createHash("sha256").update(value, "utf8").digest("hex");
const hasExactFields = (value, fields) => value !== null && typeof value === "object" && !Array.isArray(value) && JSON.stringify(Object.keys(value).sort()) === JSON.stringify(fields);

function currentMainValidator() {
  const workflow = fs.readFileSync(".github/workflows/issue-pr-governance.yml", "utf8");
  const between = (start, end) => workflow.split(start, 2)[1].split(end, 2)[0];
  const source = between("// authority-classifier:start", "// authority-classifier:end") + between("// neutralized-authority-validator:start", "// neutralized-authority-validator:end");
  // Reuse the current-main production parser, never a weaker recovery parser.
  return new Function("crypto", `${source}\nreturn { classifyIssueAuthority, resolveNeutralizedMergeAuthority };`)(crypto);
}
function trustedRecords(comments, marker) {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`${escaped}\\s*\\x60\\x60\\x60json\\s*([\\s\\S]*?)\\s*\\x60\\x60\\x60`, "gm");
  return comments.flatMap(comment => {
    if (!TRUSTED.has(comment.author_association) || typeof comment.body !== "string") return [];
    const matches = [...comment.body.matchAll(pattern)];
    if (matches.length !== 1) return [];
    try { return [{comment, receipt: JSON.parse(matches[0][1])}]; } catch (_) { return []; }
  });
}
function targetRecords(records) { return records.filter(({receipt}) => receipt && typeof receipt === "object" && receipt.repository === TARGET.repository && receipt.pr_number === TARGET.prNumber && receipt.head_sha === TARGET.head); }
function requireUniquePreparedPhase(comments, authority) {
  const records = targetRecords(trustedRecords(comments, PHASE_MARKER));
  const authoritySha = sha256(canonicalJson(authority));
  const valid = records.filter(({receipt}) => hasExactFields(receipt, PHASE_FIELDS) && receipt.contract === "verified_issue_set_merge_phase.v1" && receipt.run_id === authority.run_id && receipt.phase === "prepared" && receipt.authority_sha256 === authoritySha && receipt.body_sha256 === authority.neutralized_body_sha256 && receipt.merge_commit_sha === null && Array.isArray(receipt.closed_issues) && receipt.closed_issues.length === 0 && Array.isArray(receipt.reopened_unauthorized_issues) && receipt.reopened_unauthorized_issues.length === 0);
  if (!valid.length || valid.length !== records.length || new Set(valid.map(({receipt}) => canonicalJson(receipt))).size !== 1) throw new Error("prepared phase is missing, stale, forged, conflicting, or non-continuous");
  return valid[0];
}
async function main() {
  const token = process.env.GITHUB_TOKEN, repository = process.env.GITHUB_REPOSITORY, requestedPr = Number(process.env.RECOVERY_PR_NUMBER || 0);
  if (!token || repository !== TARGET.repository || requestedPr !== TARGET.prNumber) throw new Error("recovery target is not the one authorized immutable legacy PR");
  const request = async (method, path, body) => { const response = await fetch(`https://api.github.com${path}`, {method, headers: {Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2022-11-28"}, body: body === undefined ? undefined : JSON.stringify(body)}); if (!response.ok) throw new Error(`${method} ${path} failed: ${response.status}`); return response.status === 204 ? null : response.json(); };
  const repo = await request("GET", "/repos/RasmusTho/agentic-pkm-mvp");
  const branch = await request("GET", `/repos/RasmusTho/agentic-pkm-mvp/branches/${repo.default_branch}`);
  if (process.env.GITHUB_REF !== `refs/heads/${repo.default_branch}` || process.env.GITHUB_SHA !== branch.commit.sha) throw new Error("recovery must execute from the current default-branch head");
  const pullRequest = await request("GET", "/repos/RasmusTho/agentic-pkm-mvp/pulls/4052");
  if (pullRequest.state !== "open" || pullRequest.number !== TARGET.prNumber || pullRequest.head?.sha !== TARGET.head || pullRequest.head?.repo?.full_name !== TARGET.repository || pullRequest.title !== TARGET.title) throw new Error("PR identity is current, mutable, foreign, or otherwise not the authorized legacy target");
  const closing = await request("POST", "/graphql", {query: "query { repository(owner:\"RasmusTho\", name:\"agentic-pkm-mvp\") { pullRequest(number:4052) { closingIssuesReferences(first:20) { nodes { number } } } } }"});
  if (closing.data?.repository?.pullRequest?.closingIssuesReferences?.nodes?.length !== 0) throw new Error("live closing references are not empty");
  const comments = [];
  for (let page = 1; page <= 10; page += 1) {
    const batch = await request("GET", `/repos/RasmusTho/agentic-pkm-mvp/issues/4052/comments?per_page=100&page=${page}`);
    if (!Array.isArray(batch)) throw new Error("comment enumeration is malformed");
    comments.push(...batch);
    if (batch.length < 100) break;
    if (page === 10) throw new Error("comment enumeration exceeded bounded recovery limit");
  }
  const {classifyIssueAuthority, resolveNeutralizedMergeAuthority} = currentMainValidator();
  const issueAuthority = classifyIssueAuthority(pullRequest.body || "");
  const authority = resolveNeutralizedMergeAuthority({ comments, issueAuthority, pullRequest, repository });
  const authorityRecords = targetRecords(trustedRecords(comments, AUTHORITY_MARKER));
  if (authority === null || !authorityRecords.length || authorityRecords.some(({receipt}) => canonicalJson(receipt) !== canonicalJson(authority))) throw new Error("authority receipt is missing, forged, stale, or conflicting");
  const phase = requireUniquePreparedPhase(comments, authority);
  await request("POST", "/repos/RasmusTho/agentic-pkm-mvp/check-runs", {name: "pr-contract", head_sha: TARGET.head, status: "completed", conclusion: "success", external_id: `base-side-pr-contract-recovery:${authority.run_id}:${TARGET.head}`, details_url: `${process.env.GITHUB_SERVER_URL}/${TARGET.repository}/actions/runs/${process.env.GITHUB_RUN_ID}`, output: {title: "Current-main pr-contract recovery authenticated", summary: `authority_run=${authority.run_id}; prepared_phase=${phase.receipt.run_id}. Additional exact-head result only; no check is replaced, suppressed, or waived.`}});
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
