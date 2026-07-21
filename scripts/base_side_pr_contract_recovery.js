"use strict";

// Deliberately not a generic check/status publisher: one immutable legacy head only.
const crypto = require("crypto");
const fs = require("fs");

const TARGET = Object.freeze({
  repository: "RasmusTho/agentic-pkm-mvp",
  defaultBranch: "main",
  prNumber: 4052,
  head: "a159571da2ce9068131810aedc1ea05107d7bfaf",
  title: "Fix CKM metric schema bundle refusal",
});
const TRUSTED = new Set(["OWNER", "MEMBER", "COLLABORATOR"]);
const AUTHORITY_MARKER = "verified issue-set merge authority:";
const PHASE_MARKER = "verified issue-set merge phase:";
const PHASE_FIELDS = [
  "authority_sha256", "body_sha256", "closed_issues", "contract", "head_sha",
  "merge_commit_sha", "phase", "pr_number", "reopened_unauthorized_issues",
  "repository", "run_id",
].sort();
const canonicalJson = value => {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key =>
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    ).join(",")}}`;
  }
  return JSON.stringify(value);
};
const sha256 = value => crypto.createHash("sha256").update(value, "utf8").digest("hex");
const hasExactFields = (value, fields) => value !== null && typeof value === "object" &&
  !Array.isArray(value) && canonicalJson(Object.keys(value).sort()) === canonicalJson(fields);
const canonicalTimestamp = value => {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/.test(value)) return null;
  const instant = Date.parse(value);
  return Number.isFinite(instant) && new Date(instant).toISOString() === `${value.slice(0, -1)}.000Z` ? instant : null;
};

function currentMainValidator() {
  const workflow = fs.readFileSync(".github/workflows/issue-pr-governance.yml", "utf8");
  const between = (start, end) => workflow.split(start, 2)[1].split(end, 2)[0];
  const source = between("// authority-classifier:start", "// authority-classifier:end") +
    between("// neutralized-authority-validator:start", "// neutralized-authority-validator:end");
  return new Function("crypto", `${source}\nreturn { classifyIssueAuthority, resolveNeutralizedMergeAuthority };`)(crypto);
}

function trustedRecords(comments, marker) {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`${escaped}\\s*\\x60\\x60\\x60json\\s*([\\s\\S]*?)\\s*\\x60\\x60\\x60`, "gm");
  return comments.flatMap(comment => {
    if (!TRUSTED.has(comment.author_association) || typeof comment.body !== "string") return [];
    const matches = [...comment.body.matchAll(pattern)];
    if (matches.length !== 1) return [];
    try {
      const created = canonicalTimestamp(comment.created_at);
      const updated = canonicalTimestamp(comment.updated_at);
      return [{
        comment: {
          id: comment.id, actor: comment.user?.login,
          association: comment.author_association,
          created_at: comment.created_at, updated_at: comment.updated_at,
        },
        metadata_valid: Number.isInteger(comment.id) &&
          typeof comment.user?.login === "string" && created !== null &&
          updated !== null && created <= updated,
        receipt: JSON.parse(matches[0][1]),
      }];
    } catch (_) { return []; }
  });
}

function targetRecords(records) {
  return records.filter(({receipt}) => receipt && typeof receipt === "object" &&
    receipt.repository === TARGET.repository && receipt.pr_number === TARGET.prNumber &&
    receipt.head_sha === TARGET.head);
}

function requireUniquePreparedPhase(comments, authority) {
  const records = targetRecords(trustedRecords(comments, PHASE_MARKER));
  const authoritySha = sha256(canonicalJson(authority));
  const valid = records.filter(({receipt, metadata_valid: metadataValid}) => metadataValid &&
    hasExactFields(receipt, PHASE_FIELDS) &&
    receipt.contract === "verified_issue_set_merge_phase.v1" &&
    receipt.run_id === authority.run_id && receipt.phase === "prepared" &&
    receipt.authority_sha256 === authoritySha &&
    receipt.body_sha256 === authority.neutralized_body_sha256 &&
    receipt.merge_commit_sha === null && Array.isArray(receipt.closed_issues) &&
    receipt.closed_issues.length === 0 && Array.isArray(receipt.reopened_unauthorized_issues) &&
    receipt.reopened_unauthorized_issues.length === 0);
  if (records.length !== 1 || valid.length !== 1) {
    throw new Error("prepared phase is missing, stale, forged, conflicting, or non-continuous");
  }
  return valid[0];
}

function requireExactBaseIdentity(repo, branch, pullRequest, env) {
  if (repo.default_branch !== TARGET.defaultBranch) throw new Error("repository default branch drifted from main");
  if (env.GITHUB_REF !== "refs/heads/main" || env.GITHUB_SHA !== branch.commit.sha) {
    throw new Error("recovery must execute from the current default-branch head");
  }
  if (pullRequest.state !== "open" || pullRequest.draft !== false ||
      pullRequest.number !== TARGET.prNumber || pullRequest.head?.sha !== TARGET.head ||
      pullRequest.head?.repo?.full_name !== TARGET.repository ||
      pullRequest.base?.repo?.full_name !== TARGET.repository ||
      pullRequest.base?.ref !== TARGET.defaultBranch || pullRequest.title !== TARGET.title) {
    throw new Error("PR identity/base is mutable, retargeted, foreign, or not the authorized legacy target");
  }
}

async function captureValidatedSnapshot(request, env) {
  const repo = await request("GET", "/repos/RasmusTho/agentic-pkm-mvp");
  const branch = await request("GET", "/repos/RasmusTho/agentic-pkm-mvp/branches/main");
  const pullRequest = await request("GET", "/repos/RasmusTho/agentic-pkm-mvp/pulls/4052");
  requireExactBaseIdentity(repo, branch, pullRequest, env);
  const closing = await request("POST", "/graphql", {
    query: "query { repository(owner:\"RasmusTho\", name:\"agentic-pkm-mvp\") { pullRequest(number:4052) { closingIssuesReferences(first:20) { nodes { number } } } } }",
  });
  const closingNodes = closing.data?.repository?.pullRequest?.closingIssuesReferences?.nodes;
  if (!Array.isArray(closingNodes) || closingNodes.length !== 0) throw new Error("live closing references are not empty");
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
  const authority = resolveNeutralizedMergeAuthority({comments, issueAuthority, pullRequest, repository: TARGET.repository});
  const authorityRecords = targetRecords(trustedRecords(comments, AUTHORITY_MARKER));
  if (authority === null || authorityRecords.length !== 1 || !authorityRecords[0].metadata_valid ||
      canonicalJson(authorityRecords[0].receipt) !== canonicalJson(authority)) {
    throw new Error("authority receipt is missing, forged, stale, or conflicting");
  }
  const phase = requireUniquePreparedPhase(comments, authority);
  return {
    default_branch: repo.default_branch,
    default_branch_sha: branch.commit.sha,
    pull_request: {
      number: pullRequest.number, state: pullRequest.state, draft: pullRequest.draft,
      title: pullRequest.title, body: pullRequest.body,
      head: {sha: pullRequest.head.sha, ref: pullRequest.head.ref, repository: pullRequest.head.repo.full_name},
      base: {sha: pullRequest.base.sha, ref: pullRequest.base.ref, repository: pullRequest.base.repo.full_name},
    },
    closing_issues: closingNodes.map(node => node.number),
    authority: authorityRecords[0],
    phase,
  };
}

async function publishStableSnapshot({request, env, capture = captureValidatedSnapshot}) {
  const validated = await capture(request, env);
  // This second complete read is the publication fence. Any main, PR, closer,
  // authority-comment, phase-comment, identity, timestamp, or budget drift posts nothing.
  const reread = await capture(request, env);
  if (canonicalJson(validated) !== canonicalJson(reread)) throw new Error("recovery snapshot drifted before publication");
  const authority = reread.authority.receipt;
  const phase = reread.phase.receipt;
  await request("POST", "/repos/RasmusTho/agentic-pkm-mvp/check-runs", {
    name: "pr-contract", head_sha: reread.pull_request.head.sha,
    status: "completed", conclusion: "success",
    external_id: `base-side-pr-contract-recovery:${authority.run_id}:${reread.pull_request.head.sha}`,
    details_url: `${env.GITHUB_SERVER_URL}/${TARGET.repository}/actions/runs/${env.GITHUB_RUN_ID}`,
    output: {title: "Current-main pr-contract recovery authenticated", summary: `authority_run=${authority.run_id}; prepared_phase=${phase.run_id}. Additional exact-head result only; no check is replaced, suppressed, or waived.`},
  });
}

async function main() {
  const env = process.env;
  if (!env.GITHUB_TOKEN || env.GITHUB_REPOSITORY !== TARGET.repository ||
      Number(env.RECOVERY_PR_NUMBER || 0) !== TARGET.prNumber) {
    throw new Error("recovery target is not the one authorized immutable legacy PR");
  }
  const request = async (method, path, body) => {
    const response = await fetch(`https://api.github.com${path}`, {
      method,
      headers: {Accept: "application/vnd.github+json", Authorization: `Bearer ${env.GITHUB_TOKEN}`, "X-GitHub-Api-Version": "2022-11-28"},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${method} ${path} failed: ${response.status}`);
    return response.status === 204 ? null : response.json();
  };
  await publishStableSnapshot({request, env});
}

module.exports = {publishStableSnapshot, requireExactBaseIdentity};
if (require.main === module) main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
