"""Read-only admission for an approved current-TEST candidate and protected stable PR.

The existing promotion plan carries the inputs and the execution receipt.  This
module never moves a ref, deploys an image, or records an operator's approval.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable

from scripts import postmerge_channel_bug as channels
from scripts.postmerge_dev_test import Candidate, IMAGE_REPOSITORY, REPOSITORY, _github, load_candidate

MARKER = "<!-- stable-promotion -->"
OUTCOMES = "<!-- promotion-outcomes -->"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SECTIONS = (
    "Promotion target", "Code delta", "Migration delta", "Config / settings delta",
    "Risk notes", "Rollback path", "Operator acknowledgments",
)
_INPUT_FIELDS = {"candidate", "stable_baseline", "deployment_model", "functional_evidence"}
Api = Callable[..., Any]


class PromotionRefused(ValueError):
    """A bounded reason code, never raw caller data or subprocess output."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def approval_digest(evidence: dict[str, Any], *, plan_text: str) -> str:
    """Bind approval to inputs; PR/merge readback is an independently checked output."""
    if not _INPUT_FIELDS <= evidence.keys():
        raise PromotionRefused("promotion_plan_incomplete")
    reviewed = plan_text.split(OUTCOMES, 1)[0]
    narrative = re.sub(re.escape(MARKER) + r"\n```json\n([^`]+)\n```", MARKER, reviewed)
    # Ticking acknowledgments records approval; changing the reviewed narrative
    # (including migration/config/risk sections) invalidates that approval.
    narrative = re.sub(r"^- \[[xX]\]", "- [ ]", narrative, flags=re.MULTILINE)
    # Blank separator lines before appended observations do not change the plan.
    narrative = narrative.rstrip("\n")
    encoded = json.dumps({"inputs": {key: evidence[key] for key in sorted(_INPUT_FIELDS)},
                          "plan": narrative},
                         sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _read_plan_text(path: Path) -> str:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError()
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(262145)
        if len(raw) > 262144:
            raise ValueError()
        return raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        raise PromotionRefused("promotion_plan_invalid") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _load_plan(path: Path, *, approved: bool = True) -> dict[str, Any]:
    try:
        text = _read_plan_text(path)
        if text.count(OUTCOMES) > 1:
            raise ValueError()
        reviewed = text.split(OUTCOMES, 1)[0]
        matches = re.findall(re.escape(MARKER) + r"\n```json\n([^`]+)\n```", reviewed)
        if (len(matches) != 1 or text.count(MARKER) != 1
                or any("## " + section + "\n" not in reviewed for section in _SECTIONS)):
            raise ValueError()
        evidence = json.loads(matches[0], object_pairs_hook=_unique)
        if (not isinstance(evidence, dict)
                or set(evidence) != _INPUT_FIELDS | {"approval", "execution"}):
            raise ValueError()
        if approved:
            acknowledgment = reviewed.split("## Operator acknowledgments\n", 1)[1].split("\n## ", 1)[0]
            checks = re.findall(r"^- \[([ xX])\] .+", acknowledgment, re.MULTILINE)
            approval = evidence["approval"]
            if (not checks or " " in checks or not isinstance(approval, dict)
                    or set(approval) != {"operator", "plan_digest"}
                    or not isinstance(approval.get("operator"), str)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._@-]{0,127}",
                                    str(approval.get("operator", ""))) is None
                    or approval.get("plan_digest") != approval_digest(evidence, plan_text=text)):
                raise PromotionRefused("exact_plan_approval_required")
        return evidence
    except PromotionRefused:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise PromotionRefused("promotion_plan_invalid") from None


def _candidate(value: Any) -> Candidate:
    if (not isinstance(value, dict)
            or set(value) != {"sha", "digest", "run_id", "run_attempt", "artifact_id"}
            or not isinstance(value.get("sha"), str) or _SHA.fullmatch(value["sha"]) is None
            or not isinstance(value.get("digest"), str) or _DIGEST.fullmatch(value["digest"]) is None
            or any(type(value.get(key)) is not int or value[key] < 1
                   for key in ("run_id", "run_attempt", "artifact_id"))):
        raise PromotionRefused("promotion_candidate_invalid")
    return Candidate(**value)


def _ref(api: Api, name: str) -> str:
    # The #6226 producer's exact-ref reader refuses ambiguous/incomplete listings.
    reader = getattr(channels, "_channel_ref", None)
    if reader is None:
        raise PromotionRefused("channel_ref_producer_unavailable")
    value = reader(api, name)
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise PromotionRefused("current_channel_ref_missing")
    return value


def _protection(api: Api) -> None:
    value = api("GET", f"repos/{REPOSITORY}/branches/stable/protection")
    if not isinstance(value, dict):
        raise PromotionRefused("stable_protection_required")
    checks = value.get("required_status_checks") or {}
    if (value.get("enforce_admins", {}).get("enabled") is not True
            or value.get("required_pull_request_reviews") is None
            or checks.get("strict") is not True
            or not {"smoke", "smoke-docker", "pr-contract"} <= set(checks.get("contexts", []))
            or value.get("allow_force_pushes", {}).get("enabled") is not False
            or value.get("allow_deletions", {}).get("enabled") is not False):
        raise PromotionRefused("stable_protection_required")


def _pinned_model(source_repo: Path) -> None:
    from app.release_channels.promotion_receipt import _read_json

    receipt = _read_json(source_repo / "ops/deployments/prod-latest.json", code="cutover_receipt_required")
    fitness = receipt.get("fleet_model_fitness")
    if (receipt.get("channel") != "prod" or not isinstance(fitness, dict)
            or fitness.get("guard") != "fleet_model_fitness.v1"
            or fitness.get("channel") != "prod" or fitness.get("model") != "pinned-image"
            or fitness.get("ok") is not True):
        raise PromotionRefused("pinned_image_cutover_receipt_required")


def _binding(evidence: dict[str, Any], *, phase: str, api: Api,
             archive: Callable[[str], bytes]) -> dict[str, Any]:
    candidate = _candidate(evidence["candidate"])
    baseline = evidence["stable_baseline"]
    if not isinstance(baseline, str) or _SHA.fullmatch(baseline) is None:
        raise PromotionRefused("stable_baseline_invalid")
    if evidence["deployment_model"] != "pinned-image":
        # GitHub's generated merge SHA is not the TEST-qualified checkout SHA.
        # Refuse before moving stable, rather than discovering this after merge.
        raise PromotionRefused("checkout_merge_identity_unqualified")
    if _ref(api, "test") != candidate.sha:
        raise PromotionRefused("candidate_is_not_current_test")

    def read(path: str) -> bytes:
        return archive(path) if path.endswith("/zip") else json.dumps(api("GET", path)).encode()

    if load_candidate(candidate.run_id, run_attempt=candidate.run_attempt, read=read) != candidate:
        raise PromotionRefused("tested_image_identity_mismatch")
    run = api("GET", f"repos/{REPOSITORY}/actions/runs/{candidate.run_id}/attempts/{candidate.run_attempt}")
    green = getattr(channels, "_green_receipt", None)
    if green is None:
        raise PromotionRefused("channel_ref_producer_unavailable")
    for channel in ("dev", "test"):
        if not green(api, archive, candidate, run.get("created_at", ""), channel=channel):
            raise PromotionRefused("current_candidate_green_evidence_required")
    _protection(api)
    comparison = api("GET", f"repos/{REPOSITORY}/compare/{baseline}...{candidate.sha}")
    if not isinstance(comparison, dict) or comparison.get("status") not in {"ahead", "identical"}:
        raise PromotionRefused("stable_ancestry_reconciliation_required")
    stable = _ref(api, "stable")
    if phase == "promotion":
        if stable != baseline:
            raise PromotionRefused("stable_baseline_changed")
    elif phase == "deploy":
        execution = evidence["execution"]
        if (not isinstance(execution, dict) or set(execution) != {"pull_request", "stable_sha"}
                or type(execution.get("pull_request")) is not int or execution["pull_request"] < 1
                or execution.get("stable_sha") != stable):
            raise PromotionRefused("protected_promotion_receipt_required")
        pr = api("GET", f"repos/{REPOSITORY}/pulls/{execution['pull_request']}")
        if (not isinstance(pr, dict) or pr.get("merged") is not True
                or pr.get("base", {}).get("ref") != "stable"
                or pr.get("base", {}).get("repo", {}).get("full_name") != REPOSITORY
                or pr.get("head", {}).get("repo", {}).get("full_name") != REPOSITORY
                or pr.get("head", {}).get("sha") != candidate.sha
                or pr.get("merge_commit_sha") != stable):
            raise PromotionRefused("protected_promotion_receipt_mismatch")
        merged = api("GET", f"repos/{REPOSITORY}/git/commits/{stable}")
        tested = api("GET", f"repos/{REPOSITORY}/git/commits/{candidate.sha}")
        if (not isinstance(merged, dict) or not isinstance(tested, dict)
                or [item.get("sha") for item in merged.get("parents", [])] != [baseline, candidate.sha]
                or merged.get("tree", {}).get("sha") != tested.get("tree", {}).get("sha")
                or _SHA.fullmatch(str(tested.get("tree", {}).get("sha", ""))) is None):
            raise PromotionRefused("protected_merge_identity_mismatch")
        if evidence["deployment_model"] != "pinned-image":
            raise PromotionRefused("checkout_merge_identity_unqualified")
    else:
        raise PromotionRefused("promotion_phase_invalid")
    if _ref(api, "test") != candidate.sha or _ref(api, "stable") != stable:
        raise PromotionRefused("promotion_ref_changed")
    return {"candidate": asdict(candidate), "stable_baseline": baseline, "stable_sha": stable}


def _functional_inputs(plan: Path, evidence: dict[str, Any], binding: dict[str, Any]) -> tuple[
    Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any],
]:
    from app.release_channels.channel_manifest import create_promotion_candidate
    from app.release_channels.promotion_receipt import _read_json

    functional = evidence["functional_evidence"]
    fields = {"receipt", "registry", "context", "check_report", "rendered", "manifest", "receipt_id"}
    if (not isinstance(functional, dict) or set(functional) != fields
            or any(not isinstance(value, str) or not value for value in functional.values())):
        raise PromotionRefused("functional_test_receipt_required")
    inputs = {key: _read_json((plan.parent / functional[key]).resolve(), code="functional_input_unavailable")
              for key in fields - {"receipt_id"}}
    tested = create_promotion_candidate(inputs["rendered"], inputs["manifest"])
    candidate = binding["candidate"]
    if (tested.get("channel") != "promotion-test"
            or tested["artifact_graph"]["source_identity"] != "git:" + candidate["sha"]
            or tested["artifact_graph"]["image_index"] != IMAGE_REPOSITORY + "@" + candidate["digest"]
            or inputs["check_report"].get("candidate_identity") != tested["candidate_identity"]
            or inputs["receipt"].get("receipt_id") != functional["receipt_id"]
            or inputs["context"].get("artifact_digest") != candidate["digest"]
            or inputs["context"].get("migration_baseline_identity") != "git:" + binding["stable_baseline"]):
        raise PromotionRefused("functional_test_identity_mismatch")
    return inputs["receipt"], inputs["registry"], inputs["context"], inputs["check_report"]


def resolve_migration_baseline(plan: Path, *, expected_digest: str, expected_receipt_id: object,
                               expected_stable: str, source_repo: Path) -> str:
    """Re-authenticate the approved S -> M transition for the existing v2 validator.

    This does not accept a caller-selected baseline: S must be M's first parent,
    M the current protected stable PR merge, and C/D the current green TEST image.
    """
    evidence = _load_plan(plan)
    _pinned_model(source_repo)
    binding = _binding(evidence, phase="deploy", api=channels._api, archive=_github)
    receipt, _, _, _ = _functional_inputs(plan, evidence, binding)
    if (binding["candidate"]["digest"] != expected_digest
            or binding["stable_sha"] != expected_stable
            or receipt["receipt_id"] != expected_receipt_id):
        raise PromotionRefused("functional_image_identity_mismatch")
    # Reuse STARTUP-04's sanitized, rehash-verified immutable object reader.
    # Neither caller refs/config nor a substituted GitHub client can invent S/C/M.
    from app.release_channels.promotion_receipt import _verified_commit

    merge_tree, parents = _verified_commit(source_repo, expected_stable)
    source_tree, _ = _verified_commit(source_repo, binding["candidate"]["sha"])
    if parents != (binding["stable_baseline"], binding["candidate"]["sha"]) or merge_tree != source_tree:
        raise PromotionRefused("protected_merge_identity_mismatch")
    if (_ref(channels._api, "test") != binding["candidate"]["sha"]
            or _ref(channels._api, "stable") != expected_stable or _load_plan(plan) != evidence):
        raise PromotionRefused("promotion_ref_or_plan_changed")
    return str(binding["stable_baseline"])


def _authorize_promotion(plan: Path, *, phase: str, source_repo: Path,
                         candidate_sha: str | None, image_digest: str | None,
                         api: Api | None, archive: Callable[[str], bytes] | None,
                         now: datetime | None) -> dict[str, Any]:
    from app.release_channels.promotion_receipt import prepare_prod_activation

    api = api or channels._api
    archive = archive or _github
    evidence = _load_plan(plan)
    _pinned_model(source_repo)
    candidate = _candidate(evidence["candidate"])
    if ((candidate_sha is not None and candidate_sha != candidate.sha)
            or (image_digest is not None and image_digest != candidate.digest)):
        raise PromotionRefused("deploy_target_identity_mismatch")
    binding = _binding(evidence, phase=phase, api=api, archive=archive)
    receipt, registry, context, report = _functional_inputs(plan, evidence, binding)
    accepted = prepare_prod_activation(
        receipt, registry, context, check_report=report,
        source_repo=source_repo, now=now or datetime.now(timezone.utc),
        promotion_plan=plan if phase == "deploy" else None,
    )
    # Functional verification can take time. Refuse a changed frontier before the caller acts.
    if _ref(api, "test") != candidate.sha or _ref(api, "stable") != binding["stable_sha"]:
        raise PromotionRefused("promotion_ref_changed")
    if _load_plan(plan) != evidence:
        raise PromotionRefused("promotion_plan_changed")
    return {**binding, "image_digest": candidate.digest, "functional_receipt_id": accepted["receipt_id"],
            "approved_plan_digest": evidence["approval"]["plan_digest"],
            "operator": evidence["approval"]["operator"]}


def authorize_promotion(plan: Path, *, phase: str, source_repo: Path,
                        candidate_sha: str | None = None, image_digest: str | None = None,
                        api: Api | None = None, archive: Callable[[str], bytes] | None = None,
                        now: datetime | None = None) -> dict[str, Any]:
    """Validate admission, refusing unavailable evidence without provider diagnostics."""
    try:
        return _authorize_promotion(plan, phase=phase, source_repo=source_repo,
                                    candidate_sha=candidate_sha, image_digest=image_digest,
                                    api=api, archive=archive, now=now)
    except PromotionRefused:
        raise
    except Exception:
        raise PromotionRefused("promotion_evidence_unavailable_or_invalid") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--phase", choices=("promotion", "deploy"), default="promotion")
    parser.add_argument("--candidate")
    parser.add_argument("--image-digest")
    parser.add_argument("--approval-digest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.approval_digest:
            result: Any = approval_digest(_load_plan(args.plan, approved=False), plan_text=_read_plan_text(args.plan))
        else:
            result = authorize_promotion(args.plan, phase=args.phase,
                                         source_repo=Path(__file__).resolve().parents[2],
                                         candidate_sha=args.candidate, image_digest=args.image_digest)
    except Exception as exc:
        # No subprocess output, plan content, private paths, or credential material in diagnostics.
        reason = str(exc) if isinstance(exc, PromotionRefused) else "evidence_unavailable_or_invalid"
        print("ABORT: stable promotion admission refused: " + reason, file=sys.stderr)
        return 78
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
