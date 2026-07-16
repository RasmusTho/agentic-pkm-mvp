"""Contract tests for ops/observability/alerts.yml availability rules.

The Prometheus scrape config lists the worker /metrics target unconditionally
(``host.docker.internal:9101`` in ops/observability/prometheus.yml) while the
endpoint itself is opt-in (``WORKER_METRICS_PORT``, default off). Prometheus
records ``up{job="worker"} == 0`` from the very first scrape of an
unreachable target — there is no "never enabled" state — so an availability
rule written as a bare ``up == 0`` fires a permanent false critical alert in
the documented default setup (``docker compose -f
ops/observability/docker-compose.yaml up`` with ``WORKER_METRICS_PORT``
unset). These tests pin the contract that prevents that regression.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY_DIR = REPO_ROOT / "ops" / "observability"


def _load_alert_rules() -> dict[str, dict]:
    doc = yaml.safe_load((OBSERVABILITY_DIR / "alerts.yml").read_text(encoding="utf-8"))
    return {rule["alert"]: rule for group in doc["groups"] for rule in group["rules"]}


def _normalized(expr: str) -> str:
    """PromQL with all whitespace stripped, for layout-insensitive matching."""
    return "".join(expr.split())


def test_worker_scrape_target_is_unconditional() -> None:
    """Premise guard: prometheus.yml scrapes job="worker" unconditionally.

    The exclusion contract in the tests below only matters while the worker
    target is always configured; if the scrape job is ever removed or made
    conditional, revisit those tests together with this one.
    """
    prom = yaml.safe_load((OBSERVABILITY_DIR / "prometheus.yml").read_text(encoding="utf-8"))
    jobs = {cfg["job_name"] for cfg in prom["scrape_configs"]}
    assert "worker" in jobs


def test_service_down_excludes_the_opt_in_worker_target() -> None:
    """ServiceDown must not match the default-off worker target.

    A bare ``up == 0`` matches ``up{job="worker"} == 0``, which holds forever
    when the opt-in worker /metrics endpoint is disabled (the default), so the
    critical rule would fire perpetually out of the box.
    """
    expr = _normalized(_load_alert_rules()["ServiceDown"]["expr"])
    assert 'up{job!="worker"}==0' in expr


def test_worker_down_rule_only_fires_after_the_endpoint_has_been_up() -> None:
    """The worker gets its own availability rule gated on prior success.

    ``max_over_time(up{job="worker"}[...]) == 1`` is unsatisfiable in the
    never-enabled default state (up is 0 on every sample), so the rule can
    only fire once the endpoint has actually been seen up and then vanished.
    """
    expr = _normalized(_load_alert_rules()["WorkerMetricsDown"]["expr"])
    assert 'up{job="worker"}==0' in expr
    assert 'max_over_time(up{job="worker"}[' in expr
    assert "])==1" in expr
