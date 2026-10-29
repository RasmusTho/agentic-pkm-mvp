"""Predeclared repeated evidence for the frozen subscription classifier; opt-in only."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import random
from typing import Any, Callable

import yaml

from app.eval.classification import evaluate_classification, load_classification_cases
from app.eval.subscription_classification import (
    CORPORA, DECISION_INSTRUCTIONS, DECISION_PROTOCOL, EFFORT, HOLDOUT_PATH, MODELS,
    _decision_schema, preflight_targets, run_comparison,
)
from app.model_access.codex_cli import CodexCliExecutor

SEEDS = (101, 202, 303, 404, 505)
THRESHOLDS_PATH = Path("config/eval_thresholds.yaml")


def validation_plan() -> dict[str, Any]:
    """Bind the full finite experiment before any inference."""
    frozen = yaml.safe_load(HOLDOUT_PATH.read_text())["frozen_protocol"]
    if (frozen["instruction_sha256"] != hashlib.sha256(DECISION_INSTRUCTIONS.encode()).hexdigest()
            or frozen["protocol"] != DECISION_PROTOCOL or frozen["models"] != list(MODELS)
            or frozen["effort"] != EFFORT
            or frozen["schema_sha256"] != hashlib.sha256(json.dumps(_decision_schema(), sort_keys=True).encode()).hexdigest()
            or any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h
                   for p, h in frozen["protected_files"].items())):
        raise ValueError("frozen study protocol changed")
    thresholds = yaml.safe_load(THRESHOLDS_PATH.read_text())["classification"]
    expected = {"macro_precision", "macro_recall", "pass_rate", "answer_rate", "unknown_safe_fail_rate"}
    if set(thresholds) != expected or any(type(v) not in (int, float) or not 0 <= v <= 1
                                          for v in thresholds.values()):
        raise ValueError("invalid thresholds")
    datasets = {}
    for name, path in CORPORA.items():
        cases = load_classification_cases(path)
        datasets[name] = {"path": str(path), "cases": len(cases),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return {"schema_version": "subscription-classification-validation.v1",
            "decision_protocol": DECISION_PROTOCOL, "models": list(MODELS), "effort": EFFORT,
            "instruction_sha256": hashlib.sha256(DECISION_INSTRUCTIONS.encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(json.dumps(_decision_schema(), sort_keys=True).encode()).hexdigest(),
            "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                Path("app/eval/subscription_classification.py"), Path("app/eval/subscription_validation.py"),
                Path("app/eval/classification.py"))},
            "thresholds": thresholds,
            "thresholds_sha256": hashlib.sha256(THRESHOLDS_PATH.read_bytes()).hexdigest(),
            "datasets": datasets,
            "trials": [{"repeat": i + 1, "corpus": corpus, "seed": seed}
                       for i, seed in enumerate(SEEDS)
                       for corpus in (("golden", "holdout") if i % 2 == 0 else ("holdout", "golden"))]}


def _metric_values(metrics: dict[str, Any]) -> dict[str, float]:
    return {"macro_precision": metrics["macro_precision"], "macro_recall": metrics["macro_recall"],
            "pass_rate": metrics["pass_rate"], "answer_rate": metrics["safe_fail"]["answer_rate"],
            "unknown_safe_fail_rate": metrics["unknown"]["safe_fail_rate"]}


def summarize_validation(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute scores from outcomes; incomplete or mixed evidence cannot pass."""
    plan = validation_plan()
    if len(trials) > len(plan["trials"]):
        raise ValueError("extra trials")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    checks = []
    runtime_identity = None
    seen_inputs: dict[str, set[str]] = defaultdict(set)
    complete = len(trials) == len(plan["trials"])
    for index, trial in enumerate(trials):
        spec = plan["trials"][index]
        if set(trial) != {"repeat", "corpus", "seed", "receipt"} or any(trial[k] != v for k, v in spec.items()):
            raise ValueError("invalid trial identity or order")
        receipt = trial["receipt"]
        corpus = spec["corpus"]
        if (receipt["schema_version"] != "gpt56-classification-eval.v1"
                or receipt["decision_protocol"] != plan["decision_protocol"]
                or receipt["instruction_sha256"] != plan["instruction_sha256"]
                or receipt["requested_models"] != plan["models"]
                or receipt["dataset"] != plan["datasets"][corpus]
                or receipt["shuffle_seed"] != spec["seed"]):
            raise ValueError("mixed trial protocol or dataset")
        if not re.fullmatch(r"[0-9a-f]{64}", receipt["schema_sha256"]):
            raise ValueError("invalid schema hash")
        if receipt["schema_sha256"] != plan["schema_sha256"]:
            raise ValueError("mixed schemas")
        input_hash = receipt["input_sha256"]
        ordered = list(load_classification_cases(CORPORA[corpus]))
        random.Random(spec["seed"]).shuffle(ordered)
        expected_inputs = [{"case_id": f"case-{i:03d}", "intent": c.utterance,
                            "context": {"surface": c.surface, "note_state": c.note_state}}
                           for i, c in enumerate(ordered)]
        expected_hash = hashlib.sha256(json.dumps(expected_inputs, ensure_ascii=False).encode()).hexdigest()
        if input_hash != expected_hash or input_hash in seen_inputs[corpus]:
            raise ValueError("duplicate or invalid input order")
        seen_inputs[corpus].add(input_hash)
        runs = receipt["runs"]
        if [r["model"] for r in runs] != list(MODELS[:len(runs)]) or not runs or len(runs) > len(MODELS):
            raise ValueError("invalid model coverage")
        if any(type(r["complete"]) is not bool for r in runs):
            raise ValueError("invalid completion state")
        trial_complete = len(runs) == len(MODELS) and all(r["complete"] is True for r in runs)
        if type(receipt["complete"]) is not bool or receipt["complete"] != trial_complete:
            raise ValueError("contradictory completion")
        if not trial_complete:
            complete = False
            if index != len(trials) - 1:
                raise ValueError("continued after incomplete trial")
        cases = load_classification_cases(CORPORA[corpus])
        for run in runs:
            if (run["transport"] != "codex_cli" or run["authentication"] != "chatgpt_subscription"
                    or run["reasoning_effort"] != EFFORT):
                raise ValueError("mixed execution route")
            if run["complete"] is not True:
                checks.append({**spec, "model": run["model"], "complete": False, "passed": False})
                continue
            identity = (run["cli_version"], run["safe_profile_ref"])
            if any(not isinstance(v, str) or not v for v in identity):
                raise ValueError("missing runtime identity")
            runtime_identity = runtime_identity or identity
            if runtime_identity != identity:
                raise ValueError("mixed runtime identity")
            outcomes = run["case_outcomes"]
            if set(outcomes) != {c.id for c in cases} or run["completed_cases"] != len(cases):
                raise ValueError("invalid case coverage")
            if any(v not in {"co_authoring", "exploratory", "governance_bearing", "unknown"}
                   for v in outcomes.values()):
                raise ValueError("invalid outcome")
            metrics = evaluate_classification(cases, outcomes)
            if any(run["metrics"].get(k) != v for k, v in metrics.items()):
                raise ValueError("score differs from unchanged scorer")
            safety = not metrics["mutation_side_confusions"]
            if run["hard_gate_passed"] is not safety:
                raise ValueError("contradictory safety")
            values = _metric_values(metrics)
            failures = [c.id for c in cases if outcomes[c.id] not in (c.expected_intent, *c.acceptable)]
            check = {**spec, "model": run["model"], "complete": True,
                     "passed": safety and all(values[k] >= v for k, v in plan["thresholds"].items()),
                     "metrics": values, "passed_cases": len(cases) - len(failures),
                     "exact_primary_cases": sum(outcomes[c.id] == c.expected_intent for c in cases),
                     "accepted_alternative_cases": len(cases) - len(failures) - sum(
                         outcomes[c.id] == c.expected_intent for c in cases),
                     "by_language": {lang: {"cases": sum(c.language == lang for c in cases),
                         "failed_cases": [c.id for c in cases if c.language == lang and c.id in failures]}
                         for lang in ("sv", "en")},
                     "failed_cases": failures, "mutation_side_errors": metrics["mutation_side_confusions"],
                     "outcomes": outcomes}
            checks.append(check)
            grouped[(corpus, run["model"])].append(check)
        expected_safety = trial_complete and all(r["hard_gate_passed"] for r in runs)
        if receipt["hard_gate_passed"] is not expected_safety:
            raise ValueError("contradictory trial safety")
    groups = []
    for corpus in CORPORA:
        cases = load_classification_cases(CORPORA[corpus])
        for model in MODELS:
            rows = grouped[(corpus, model)]
            all_repeats = len(rows) == len(SEEDS)
            unstable = {c.id: [r["outcomes"][c.id] for r in rows] for c in cases
                        if len({r["outcomes"][c.id] for r in rows}) > 1}
            groups.append({"corpus": corpus, "model": model, "observed_complete_repeats": len(rows),
                           "minimum_metrics": {k: min(r["metrics"][k] for r in rows)
                                               for k in plan["thresholds"]} if rows else None,
                           "passed_observations": sum(r["passed_cases"] for r in rows),
                           "observations": len(cases) * len(rows), "unique_cases": len(cases),
                           "unstable_cases": unstable, "stability_complete": all_repeats,
                           "stable_correct_cases": sum(all(c.id not in r["failed_cases"] for r in rows)
                                                       for c in cases) if all_repeats else None,
                           "all_repeats_passed": all_repeats and all(r["passed"] for r in rows)})
    return {**plan, "recorded_at": datetime.now(timezone.utc).isoformat(), "complete": complete,
            "pre_registered_gate_passed": complete and all(c["passed"] for c in checks),
            "perfect_repeatability": complete and all(g["stable_correct_cases"] == g["unique_cases"]
                                                        and not g["unstable_cases"] for g in groups),
            "observed_trials": len(trials), "checks": [{k: v for k, v in c.items() if k != "outcomes"}
                                                        for c in checks], "groups": groups,
            "limitations": ["synthetic blind-authored cases, not a population sample or human validation",
                            "repeated observations of the same cases are correlated",
                            "no guarantee for unseen inputs; no proof that overfitting is absent",
                            "legacy comparator, not Product TypeSafe qualification",
                            "batch timing only; served identity, usage and dollar cost unavailable"]}


def run_validation(executor: CodexCliExecutor, *,
                   on_trial: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    plan = validation_plan()
    preflight_targets(executor, MODELS)
    trials = []
    for spec in plan["trials"]:
        if validation_plan() != plan:
            raise ValueError("experiment changed during validation")
        receipt = run_comparison(executor, cases_path=CORPORA[spec["corpus"]], shuffle_seed=spec["seed"])
        trial = {**spec, "receipt": receipt}
        trials.append(trial)
        if on_trial is not None:
            on_trial(trial)
        summarize_validation(trials)  # Validate the saved prefix before any next trial.
        if receipt["complete"] is not True:
            break  # Terminal transport/protocol failure. A quality failure is retained, not retried.
    if validation_plan() != plan:
        raise ValueError("experiment changed during validation")
    return {"summary": summarize_validation(trials), "trials": trials}


def main() -> int:
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error("explicit --run is required")
    try:
        profile = Path(os.environ["CODEX_CLI_SAFE_PROFILE_PATH"])
        if not profile.is_absolute():
            raise ValueError("absolute profile required")
        validation_plan()
        args.output_directory.mkdir(parents=True, exist_ok=False)
        executor = CodexCliExecutor(safe_profile_path=profile, preflight_timeout_seconds=30,
                                    execution_timeout_seconds=300)
        saved = 0

        def save(trial: dict[str, Any]) -> None:
            nonlocal saved
            saved += 1
            (args.output_directory / f"trial-{saved:02d}.json").write_text(json.dumps(trial, sort_keys=True))
            print(f"saved trial {saved}/10", flush=True)

        result = run_validation(executor, on_trial=save)
        (args.output_directory / "validation.json").write_text(json.dumps(result, sort_keys=True))
    except Exception:
        print(json.dumps({"schema_version": "subscription-classification-validation.v1", "complete": False,
                          "failure": "validation_failed_or_unavailable"}))
        return 2
    print(json.dumps(result["summary"], sort_keys=True))
    return 0 if result["summary"]["pre_registered_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
