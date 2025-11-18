from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from app.settings.agents import (
    get_agent_config,
    get_agents_for_flow,
    load_agent_configs,
)


def _write_agent(root: Path, name: str, content: str) -> None:
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip() + "\n", encoding="utf-8")


def test_load_agent_configs_parses_markdown(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    _write_agent(
        root,
        "planner",
        """\
        ---
        agent_id: planner
        agent_type: planner
        enabled: true
        flows:
          - ingest
          - promotion
        allowed_targets:
          - planner.queue
        allowed_events:
          - ingest.object.created
        model:
          provider: openai
          name: gpt-4o
          temperature: 0.1
          max_tokens: 2048
        tools:
          - summarize
          - promote
        prompt_template_ref: planner.prompts.default
        ---
        planner agent body is ignored
        """,
    )
    _write_agent(
        root,
        "normalizer",
        """\
        ---
        agent_type: worker
        enabled: false
        flows:
          - ingest
        allowed_targets:
          - normalize.queue
        allowed_events:
          - ingest.object.created
        tools:
          - normalize
        ---
        """,
    )

    configs = load_agent_configs(root=root)

    assert set(configs.keys()) == {"planner", "normalizer"}

    planner = configs["planner"]
    assert planner.agent_id == "planner"
    assert planner.agent_type == "planner"
    assert planner.enabled is True
    assert planner.flows == ["ingest", "promotion"]
    assert planner.allowed_targets == ["planner.queue"]
    assert planner.allowed_events == ["ingest.object.created"]
    assert planner.tools == ["summarize", "promote"]
    assert planner.prompt_template_ref == "planner.prompts.default"
    assert planner.model is not None
    assert planner.model.provider == "openai"
    assert planner.model.name == "gpt-4o"
    assert planner.model.temperature == 0.1
    assert planner.model.max_tokens == 2048

    normalizer = configs["normalizer"]
    assert normalizer.agent_id == "normalizer"
    assert normalizer.agent_type == "worker"
    assert normalizer.enabled is False
    assert normalizer.flows == ["ingest"]
    assert normalizer.model is None


def test_get_agent_config_and_missing(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    _write_agent(
        root,
        "planner",
        """\
        ---
        agent_id: planner
        agent_type: planner
        flows:
          - ingest
        ---
        """,
    )

    configs = load_agent_configs(root=root)

    assert get_agent_config("planner", configs) is configs["planner"]
    assert get_agent_config("missing", configs) is None


def test_get_agents_for_flow_filters_disabled(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    _write_agent(
        root,
        "planner",
        """\
        ---
        agent_type: planner
        flows:
          - ingest
          - promotion
        ---
        """,
    )
    _write_agent(
        root,
        "qa",
        """\
        ---
        agent_type: qa
        enabled: false
        flows:
          - ingest
        ---
        """,
    )
    _write_agent(
        root,
        "promotion",
        """\
        ---
        agent_id: promotion
        agent_type: promotion
        flows:
          - promotion
        ---
        """,
    )

    configs = load_agent_configs(root=root)

    ingest_agents = get_agents_for_flow("ingest", configs)
    assert [agent.agent_id for agent in ingest_agents] == ["planner"]

    promotion_agents = get_agents_for_flow("promotion", configs)
    assert [agent.agent_id for agent in promotion_agents] == ["planner", "promotion"]
