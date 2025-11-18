from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from app.settings.flow_profiles import get_flow, get_flows_for_event, load_flow_profiles


def _write_flow(root: Path, name: str, content: str) -> None:
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip() + "\n", encoding="utf-8")


def test_load_flow_profiles_parses_markdown_files(tmp_path: Path) -> None:
    root = tmp_path / "flows"
    _write_flow(
        root,
        "ingest",
        """\
        ---
        flow_id: ingest
        name: Ingest pipeline
        enabled: true
        event_triggers:
          - ingest.object.created
          - ask.query.received
        intent: |
          Turn new raw text into structured, searchable knowledge.
        suggested_patterns:
          - name: standard_ingest
            description: Normalize through indexing
            steps:
              - target: agent:normalizer
              - target: mcp:vault.append_note
                description: Capture normalized summary
                args:
                  content: "{{ summary }}"
          - name: light_ingest
            steps:
              - target: agent:normalizer
        planner_mode:
          strictness: advisory
          max_steps: 6
        prompt_profiles:
          - id: ingest-default
            description: Primary ingest planner prompt
            prompt_template_ref: prompts/planner/ingest-default.md
          - id: ingest-fast
            prompt_template_ref: prompts/planner/ingest-fast.md
        ---
        # ingest profile body ignored
        """,
    )
    _write_flow(
        root,
        "qa",
        """\
        ---
        enabled: false
        event_triggers:
          - ask.query.received
        intent: Answer a question with existing knowledge.
        ---
        body content is ignored
        """,
    )

    profiles = load_flow_profiles(root=root)

    assert set(profiles.keys()) == {"ingest", "qa"}

    ingest = profiles["ingest"]
    assert ingest.flow_id == "ingest"
    assert ingest.name == "Ingest pipeline"
    assert ingest.enabled is True
    assert ingest.event_triggers == ["ingest.object.created", "ask.query.received"]
    assert ingest.intent and ingest.intent.strip() == "Turn new raw text into structured, searchable knowledge."
    assert len(ingest.suggested_patterns) == 2
    primary_pattern = ingest.suggested_patterns[0]
    assert primary_pattern.name == "standard_ingest"
    assert primary_pattern.description == "Normalize through indexing"
    assert len(primary_pattern.steps) == 2
    assert primary_pattern.steps[0].target == "agent:normalizer"
    assert primary_pattern.steps[1].target == "mcp:vault.append_note"
    assert primary_pattern.steps[1].args["content"] == "{{ summary }}"
    light_pattern = ingest.suggested_patterns[1]
    assert [step.target for step in light_pattern.steps] == ["agent:normalizer"]
    assert ingest.planner_mode.strictness == "advisory"
    assert ingest.planner_mode.max_steps == 6
    assert len(ingest.prompt_profiles) == 2
    assert ingest.prompt_profiles[0].id == "ingest-default"
    assert ingest.prompt_profiles[0].prompt_template_ref == "prompts/planner/ingest-default.md"
    assert ingest.prompt_profiles[1].description is None

    qa = get_flow("qa", profiles)
    assert qa is not None
    assert qa.flow_id == "qa"
    assert qa.enabled is False
    assert qa.event_triggers == ["ask.query.received"]
    assert qa.intent == "Answer a question with existing knowledge."
    assert qa.suggested_patterns == []
    assert qa.prompt_profiles == []


def test_get_flows_for_event_filters_disabled(tmp_path: Path) -> None:
    root = tmp_path / "flows"
    _write_flow(
        root,
        "ingest",
        """\
        ---
        event_triggers:
          - ingest.object.created
        ---
        """,
    )
    _write_flow(
        root,
        "qa",
        """\
        ---
        enabled: false
        event_triggers:
          - ingest.object.created
        ---
        """,
    )
    _write_flow(
        root,
        "promotion",
        """\
        ---
        event_triggers:
          - promote.intent.created
        ---
        """,
    )

    profiles = load_flow_profiles(root=root)

    ingest_flows = get_flows_for_event("ingest.object.created", profiles)
    assert [flow.flow_id for flow in ingest_flows] == ["ingest"]

    promotion_flows = get_flows_for_event("promote.intent.created", profiles)
    assert [flow.flow_id for flow in promotion_flows] == ["promotion"]

    assert get_flows_for_event("ask.query.received", profiles) == []


def test_profiles_default_optional_fields_when_missing(tmp_path: Path) -> None:
    root = tmp_path / "flows"
    _write_flow(
        root,
        "minimal",
        """\
        ---
        event_triggers:
          - ingest.object.created
        ---
        """,
    )

    profiles = load_flow_profiles(root=root)
    profile = profiles["minimal"]

    assert profile.enabled is True
    assert profile.intent is None
    assert profile.suggested_patterns == []
    assert profile.planner_mode.strictness == "balanced"
    assert profile.planner_mode.max_steps == 8
    assert profile.prompt_profiles == []


def test_missing_directory_returns_empty_dict(tmp_path: Path) -> None:
    missing_root = tmp_path / "no_such_dir"
    assert load_flow_profiles(root=missing_root) == {}
