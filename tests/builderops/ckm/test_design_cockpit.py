from __future__ import annotations

from pathlib import Path

from app.builderops.design_agent_adapters import DesignAgentAdapterRegistry
from app.builderops.design_run_governance import DesignRunGovernance
from app.builderops.model_access_resolver import BuilderModelAccessResolver
from app.builderops.store import SqliteBuilderOpsStore


def test_ckm_calls_only_builder_system_design_adapter_port(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    policy_path = repo_root / "config/builderops/design_run_policy.json"
    policy_path.parent.mkdir(parents=True)
    source_policy = (
        Path(__file__).parents[3]
        / "config/builderops/design_run_policy.json"
    )
    policy_path.write_bytes(source_policy.read_bytes())
    store = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    store.initialize()

    service = DesignRunGovernance.from_declared_sources(
        store=store,
        channel="dev",
        repo_root=repo_root,
    )

    assert isinstance(service.registry, DesignAgentAdapterRegistry)
    assert isinstance(service.registry.resolver, BuilderModelAccessResolver)
    assert service.registry.model_turn_adapters == {}
    descriptors = service.list_adapters(run_id="run.production.zero-edge")
    assert {item.design_agent_id for item in descriptors} == {
        "claude-design-via-claude-code",
        "codex",
        "fable",
    }
    assert all(not item.available for item in descriptors)
