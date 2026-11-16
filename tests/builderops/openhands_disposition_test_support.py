"""Synthetic owning-session inputs for tests of other PR-cycle behavior."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def items(report):
    rows = [("findings", i, item) for i, item in enumerate(report["findings"])]
    rows += [("scope", i, item) for i, item in enumerate(report["scope_assessment"]["limitations"])]
    for number, child in report.get("closing_assessments", {}).items():
        rows += [(f"closing:{number}", i, item) for i, item in enumerate(child["limitations"])]
    return rows


def synthetic_disposition(report, reconciliation=None):
    """Test evidence only: the calling test represents an authorized, independently assessing owner."""
    current = items(report)
    rows = [{"report": "current", "where": where, "index": index, "sha256": digest(value),
             "decision": "nonblocking", "rationale": "Synthetic owner assessed this item against the test contract."}
            for where, index, value in current]
    original_digest = attempt_digest = None
    if reconciliation is not None:
        archive = reconciliation["archived"]
        original_digest, attempt_digest = digest(archive["review"]), digest(archive)
        for where, index, value in items(archive["review"]):
            match = None
            for candidate_where, candidate_index, candidate in current:
                if candidate_where != where:
                    continue
                if where == "findings":
                    same = all(candidate.get(key) == value.get(key) for key in
                               ("severity", "summary", "file", "line", "failure_scenario"))
                else:
                    same = candidate.get("detail") == value if isinstance(value, str) else candidate == value
                if same:
                    match = (candidate_where, candidate_index, candidate)
                    break
            row = {"report": "original", "where": where, "index": index, "sha256": digest(value),
                   "rationale": "Synthetic owner assessed the original item against the test contract."}
            if match is None:
                row["decision"] = "nonblocking"
            else:
                row.update(decision="retained", successor={"where": match[0], "index": match[1],
                                                          "sha256": digest(match[2])})
            rows.append(row)
    return {"identity": report["identity"], "head_sha": report["head_sha"], "report_sha256": digest(report),
            "original_report_sha256": original_digest, "original_attempt_sha256": attempt_digest,
            "assessment": "Synthetic owner reviewed the report and its test-contract obligations.", "items": rows}


def synthetic_reservation(layout, number, identity, operation):
    from app.builderops import epic_run_state, openhands_pr_completion

    def update(state):
        state["dispatch_decisions"].append({"kind": "openhands_pr_completion", "number": number,
                                            "identity": identity, "operation_id": operation,
                                            "request": "independent-review", "attempt": 1, "outcome": "completed",
                                            "repository": openhands_pr_completion.REPOSITORY, "route": "native"})
        return state

    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir,
                                         expected_epic_issue_number=layout.epic, updater=update)
