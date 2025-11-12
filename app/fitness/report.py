from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from app.eval.golden import evaluate_vs_baseline
from .metrics import qas003_hybrid_latency, qas010_outbox_to_index_latency
from .relations import relation_metrics
from .chunks import diarization_metrics
from .reasoning import reasoning_metrics

SUMMARY_LABELS = [
    "LATENCY",
    "EVAL",
    "EVAL DELTA",
    "RELATION COVERAGE",
    "RELATIONS",
    "DIARIZATION",
    "REASONING",
    "GATES",
]

__all__ = ["SUMMARY_LABELS", "parse_summary_lines", "load_thresholds", "evaluate_gates"]


def _truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _summary_line(label: str, **metrics: Any) -> str:
    parts = [label]
    for key, value in metrics.items():
        parts.append(f"{key}={value}")
    return "CI SUMMARY " + " ".join(parts)


def load_thresholds(path: str | None = None) -> Dict[str, Any]:
    target = Path(path or os.getenv("THRESHOLDS_PATH", "ops/quality/baselines.yaml"))
    if not target.exists():
        raise FileNotFoundError(f"Thresholds file not found: {target}")
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return data


def _coerce_metric(value: str) -> Any:
    raw = value.strip()
    suffixes = ("s", "%")
    for suffix in suffixes:
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    try:
        return float(raw)
    except ValueError:
        lowered = raw.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        return raw


def parse_summary_lines(lines: Iterable[str], required: List[str] | None = None) -> Dict[str, Dict[str, Any]]:
    parsed: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        if not line.startswith("CI SUMMARY "):
            continue
        remainder = line[len("CI SUMMARY ") :].strip()
        if not remainder:
            continue
        parts = remainder.split()
        label_tokens: List[str] = []
        metric_start = len(parts)
        for idx, token in enumerate(parts):
            if "=" not in token:
                label_tokens.append(token)
                continue
            key, _ = token.split("=", 1)
            if (
                label_tokens == ["RELATION"]
                and key == "COVERAGE"
                and idx == 1
            ):
                label_tokens.append(key)
            metric_start = idx
            break
        if not label_tokens and parts:
            label_tokens.append(parts[0])
        label = " ".join(label_tokens)
        metrics: Dict[str, Any] = {}
        for token in parts[metric_start:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            metrics[key] = _coerce_metric(value)
        parsed.setdefault(label, {}).update(metrics)
    if required:
        missing = [label for label in required if label not in parsed]
        if missing:
            raise ValueError(f"Missing CI summary lines: {', '.join(missing)}")
    return parsed


def evaluate_gates(
    summary: Dict[str, Dict[str, Any]],
    thresholds: Dict[str, Any],
    *,
    provider: str,
    diarization_off: Dict[str, Any],
    strict: bool,
    reasoning_enabled: bool,
) -> tuple[bool, List[str]]:
    reasons: List[str] = []

    # Latency gates
    latency_cfg = thresholds.get("latency", {})
    latency_summary = summary.get("LATENCY", {})
    lat_fail = False
    for metric in ("QAS003", "QAS010"):
        current = latency_summary.get(metric)
        cfg = latency_cfg.get(metric, {})
        baseline = cfg.get("value")
        tolerance = cfg.get("tolerance", latency_cfg.get("tolerance", 0.10))
        if current is None or baseline is None:
            continue
        if current > baseline * (1 + tolerance):
            lat_fail = True
    if lat_fail:
        reasons.append("LAT")

    eval_cfg = thresholds.get("eval", {})
    delta_summary = summary.get("EVAL DELTA", {})
    delta_p = delta_summary.get("DP10")
    delta_ndcg = delta_summary.get("DnDCG10")
    provider_spec = (provider or "").strip().lower()
    if provider_spec in {"ce_local", "local"}:
        min_p = eval_cfg.get("delta_precision_min", 0.0)
        min_ndcg = eval_cfg.get("delta_ndcg_min", 0.0)
        if strict:
            ok = ((delta_p is not None and delta_p >= min_p) or (delta_ndcg is not None and delta_ndcg >= min_ndcg))
        else:
            ok = ((delta_p is not None and delta_p >= 0) or (delta_ndcg is not None and delta_ndcg >= 0))
        if not ok:
            reasons.append("EVAL_DELTA")
    else:
        tolerance = eval_cfg.get("delta_abs_tolerance", 0.005)
        abs_ok = True
        if delta_p is not None and abs(delta_p) > tolerance:
            abs_ok = False
        if delta_ndcg is not None and abs(delta_ndcg) > tolerance:
            abs_ok = False
        if not abs_ok:
            reasons.append("EVAL_DELTA")

    # Relation coverage/validity
    relations_cfg = thresholds.get("relations", {})
    coverage_summary = summary.get("RELATION COVERAGE", {})
    coverage_percent = coverage_summary.get("COVERAGE")
    if coverage_percent is None or (coverage_percent / 100.0) < relations_cfg.get("coverage_min", 0.95):
        reasons.append("REL_COV")
    relations_summary = summary.get("RELATIONS", {})
    validity_percent = relations_summary.get("validity")
    if validity_percent is None or (validity_percent / 100.0) < relations_cfg.get("validity_min", 0.95):
        reasons.append("REL_VAL")

    # Diarization ratio
    diarization_summary = summary.get("DIARIZATION", {})
    chunk_on = diarization_summary.get("chunk_p95")
    chunk_off = diarization_off.get("chunk_p95")
    ratio_limit = thresholds.get("diarization", {}).get("p95_ratio_max", 0.95)
    if not chunk_off or not chunk_on:
        reasons.append("DIA_P95")
    else:
        ratio = chunk_on / chunk_off
        if ratio > ratio_limit:
            reasons.append("DIA_P95")

    reasoning_summary = summary.get("REASONING", {})
    if reasoning_enabled:
        reason_cfg = thresholds.get("reasoning", {})
        claims_avg = reasoning_summary.get("claims_avg")
        inf_avg = reasoning_summary.get("inferences_avg")
        conflicts = reasoning_summary.get("conflicts")
        if claims_avg is None or claims_avg < reason_cfg.get("claims_avg_min", 0.0):
            reasons.append("REASONING")
        elif inf_avg is None or inf_avg < reason_cfg.get("inferences_avg_min", 0.0):
            reasons.append("REASONING")
        elif conflicts is not None and conflicts > reason_cfg.get("conflicts_max", float("inf")):
            reasons.append("REASONING")

    return (not reasons), reasons


def main() -> None:
    qas003 = qas003_hybrid_latency()
    qas010 = qas010_outbox_to_index_latency()
    provider = os.getenv("CI_EVAL_RERANK_PROVIDER", "ce_local")
    eval_k = int(os.getenv("CI_EVAL_K", "10"))
    golden = evaluate_vs_baseline(provider, k=eval_k)
    relation_stats = relation_metrics()
    diarization_off = diarization_metrics(flag_enabled=False)
    diarization_on = diarization_metrics(flag_enabled=True)
    reasoning_enabled = _truthy(os.getenv("REASONING_ENABLE"))
    reasoning_stats = reasoning_metrics(flag_enabled=reasoning_enabled)
    coverage = relation_stats["coverage"]
    validity = relation_stats["validity"]
    payload = {
        "QAS-003": qas003,
        "QAS-010": qas010,
        "golden": golden,
        "relation_coverage_percent": coverage,
        "diarization": {"off": diarization_off, "on": diarization_on},
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    summary_lines: List[str] = []

    def _emit(label: str, **metrics: Any) -> None:
        line = _summary_line(label, **metrics)
        summary_lines.append(line)
        print(line)

    _emit(
        "LATENCY",
        QAS003=f"{qas003['p95']:.6f}s",
        QAS010=f"{qas010['p95']:.6f}s",
    )
    _emit(
        "EVAL",
        P10=f"{golden['candidate']['precision@k']:.3f}",
        NDCG10=f"{golden['candidate']['ndcg@k']:.3f}",
        BASE_P10=f"{golden['baseline']['precision@k']:.3f}",
        BASE_NDCG10=f"{golden['baseline']['ndcg@k']:.3f}",
    )
    delta_p = golden["candidate"]["precision@k"] - golden["baseline"]["precision@k"]
    delta_ndcg = golden["candidate"]["ndcg@k"] - golden["baseline"]["ndcg@k"]
    _emit(
        "EVAL DELTA",
        DP10=f"{delta_p:+.3f}",
        DnDCG10=f"{delta_ndcg:+.3f}",
        RELATION_TARGET="60%",
    )
    relation_line = f"CI SUMMARY RELATION COVERAGE={coverage:.2f}%"
    summary_lines.append(relation_line)
    print(relation_line)
    _emit(
        "RELATIONS",
        coverage=f"{coverage:.2f}%",
        validity=f"{validity:.2f}%",
        target="95%",
    )
    _emit(
        "DIARIZATION",
        chunk_p95=f"{diarization_on['chunk_p95']:.2f}",
        speaker_avg=f"{diarization_on['speaker_avg']:.2f}",
        flag="on",
    )
    _emit(
        "REASONING",
        claims_avg=f"{reasoning_stats['claims_avg']:.2f}",
        inferences_avg=f"{reasoning_stats['inferences_avg']:.2f}",
        conflicts=f"{reasoning_stats['conflicts']:.2f}",
        flag="on" if reasoning_enabled else "off",
    )

    fail = False
    thresholds = load_thresholds()
    strict = _truthy(os.getenv("GATE_STRICT"))
    try:
        summary = parse_summary_lines(summary_lines, required=SUMMARY_LABELS[:-1])
    except ValueError as exc:
        print(f"CI SUMMARY error: {exc}", file=sys.stderr)
        fail = True
        summary = {}

    ok, reasons = evaluate_gates(
        summary,
        thresholds,
        provider=provider,
        diarization_off=diarization_off,
        strict=strict,
        reasoning_enabled=reasoning_enabled,
    )
    gates_line = _summary_line(
        "GATES",
        ok=str(ok).lower(),
        reasons=",".join(reasons),
    )
    summary_lines.append(gates_line)
    print(gates_line)
    if not ok:
        fail = True

    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
