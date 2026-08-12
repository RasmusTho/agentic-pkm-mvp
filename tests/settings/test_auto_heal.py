from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.settings import compiler
from app.settings import runtime as settings_runtime

pytestmark = pytest.mark.not_pg


def _write_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(body).strip() + "\n", encoding="utf-8")


def test_auto_heal_rewrites_invalid_values(tmp_path, monkeypatch):
    vault = tmp_path / "vault" / "settings"
    runtime_dir = tmp_path / "runtime" / "settings"

    _write_md(
        vault / "global.md",
        """
        ---
        uuid: g
        ---
        ## Runtime
        ```yaml settings
        timeout_ms: "fast"
        log_level: "LOUD"
        ```
        """,
    )
    _write_md(
        vault / "providers.md",
        """
        ---
        uuid: p
        ---
        ## Provider defaults
        ```yaml settings
        llm: {}
        ```
        """,
    )
    _write_md(
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        configured_keys:
          - reasoning_model
        default_chat:
          primary:
            model_id: openai.chat.gpt_5_4_mini
        ```
        """,
    )
    _write_md(
        vault / "retrieval.md",
        """
        ---
        uuid: retrieval
        ---
        ## Rerank
        ```yaml settings
        configured_keys:
          - rerank
        rerank_top_k: invalid
        ```
        """,
    )
    _write_md(
        vault / "agents" / "classifier.md",
        """
        ---
        uuid: c
        ---
        ## Toggles
        - [x] enable

        ## Runtime
        ```yaml settings
        timeout_ms: fast
        min_confidence: 0.4
        ```
        """,
    )

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    bundle = compiler.compile_all(auto_heal=True)

    assert bundle.global_.timeout_ms == 8000
    assert bundle.agents["classifier"].timeout_ms == 8000
    assert bundle.retrieval_tuning.rerank_top_k == 100
    assert bundle.retrieval_tuning.configured_keys == ["rerank_top_k"]
    assert bundle.llm_routing.configured_keys == ["default_chat"]

    agent_md = (vault / "agents" / "classifier.md").read_text(encoding="utf-8")
    assert "timeout_ms: 8000" in agent_md
    assert "<!-- BEGIN:settings:reference -->" in agent_md
    retrieval_md = (vault / "retrieval.md").read_text(encoding="utf-8")
    assert "rerank_top_k: 100" in retrieval_md
    assert "configured_keys" not in retrieval_md
    projection = (runtime_dir / "retrieval_tuning.yaml").read_text(encoding="utf-8")
    assert "configured_keys:" in projection
    llm_routing_md = (vault / "llm_routing.md").read_text(encoding="utf-8")
    assert "configured_keys" not in llm_routing_md
    llm_projection = (runtime_dir / "llm_routing.yaml").read_text(encoding="utf-8")
    assert "configured_keys:" in llm_projection

    # A valid-but-polluted source is also repaired at the compiler ingress
    # boundary, not accepted as user authority on a later compile.
    retrieval_path = vault / "retrieval.md"
    retrieval_path.write_text(
        retrieval_path.read_text(encoding="utf-8").replace(
            "rerank_top_k: 100", "configured_keys:\n  - rerank\nrerank_top_k: 100"
        ),
        encoding="utf-8",
    )
    recompiled = compiler.compile_all(auto_heal=True)
    assert recompiled.retrieval_tuning.configured_keys == ["rerank_top_k"]
    assert "configured_keys:" not in retrieval_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("later_payload", "closing_fence"),
    (
        ("configured_keys:\n  - rerank\nrerank: always\n", "```\n"),
        ("configured_keys:\n  - rerank\nrerank_top_k: [\n", "```\n"),
        (
            "configured_keys:\n  - rerank\n| rerank_top_k | 999 |\n",
            "",
        ),
    ),
    ids=("valid-later-fence", "invalid-later-fence", "malformed-later-fence"),
)
def test_retrieval_source_rejects_later_settings_fence_and_keeps_last_valid_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    later_payload: str,
    closing_fence: str,
) -> None:
    vault = tmp_path / "vault" / "settings"
    runtime_dir = tmp_path / "runtime" / "settings"
    _write_md(
        vault / "providers.md",
        """
        ---
        uuid: p
        ---
        ## Provider defaults
        ```yaml settings
        llm: {}
        ```
        """,
    )
    _write_md(
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        default_chat:
          primary:
            model_id: openai.chat.gpt_5_4_mini
        ```
        """,
    )
    retrieval_path = vault / "retrieval.md"
    _write_md(
        retrieval_path,
        """
        ---
        uuid: retrieval
        ---
        ## Rerank
        ```yaml settings
        rerank_top_k: 7
        ```
        """,
    )
    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(settings_runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(settings_runtime, "_CURRENT", None)

    compiler.compile_all(auto_heal=True)
    canonical_source = retrieval_path.read_text(encoding="utf-8")
    last_valid_projection = (runtime_dir / "retrieval_tuning.yaml").read_bytes()
    assert settings_runtime.reload_settings_bundle(notify=False).retrieval_tuning.rerank_top_k == 7

    ambiguous_source = (
        canonical_source.rstrip()
        + "\n\n## Later authority\n```yaml settings\n"
        + later_payload
        + closing_fence
    )
    retrieval_path.write_text(ambiguous_source, encoding="utf-8")

    with pytest.raises(compiler.SettingsSourceError, match="`yaml settings` fence"):
        compiler.compile_all(auto_heal=True)

    assert retrieval_path.read_text(encoding="utf-8") == ambiguous_source
    assert (runtime_dir / "retrieval_tuning.yaml").read_bytes() == last_valid_projection
    last_valid = settings_runtime.reload_settings_bundle(notify=False)
    assert last_valid.retrieval_tuning.rerank_top_k == 7
    assert last_valid.retrieval_tuning.configured_keys == ["rerank_top_k"]

    retrieval_path.write_text(
        canonical_source.replace("rerank_top_k: 7", "rerank_top_k: 11"),
        encoding="utf-8",
    )
    compiler.compile_all(auto_heal=True)
    recovered = settings_runtime.reload_settings_bundle(notify=False)
    assert recovered.retrieval_tuning.rerank_top_k == 11
    assert recovered.retrieval_tuning.configured_keys == ["rerank_top_k"]


def test_auto_heal_writes_settings_via_knowledge_port(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault" / "settings"
    runtime_dir = tmp_path / "runtime" / "settings"

    _write_md(
        vault / "global.md",
        """
        ---
        uuid: g
        ---
        ## Runtime
        ```yaml settings
        timeout_ms: "fast"
        ```
        """,
    )
    _write_md(
        vault / "providers.md",
        """
        ---
        uuid: p
        ---
        ## Provider defaults
        ```yaml settings
        llm: {}
        ```
        """,
    )
    _write_md(
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        default_chat:
          primary:
            model_id: openai.chat.gpt_5_4_mini
        ```
        """,
    )

    writes: list[str] = []

    def _fake_write_note(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or vault.parent).resolve()
        resolved_path = Path(path).resolve()
        rel = resolved_path.relative_to(resolved_root).as_posix()
        writes.append(rel)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr("app.settings.writeback.write_note_from_absolute", _fake_write_note)

    compiler.compile_all(auto_heal=True)

    assert "settings/global.md" in writes


def test_compile_all_writes_llm_routing_runtime_file(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault" / "@Settings"
    runtime_dir = tmp_path / "runtime" / "settings"

    _write_md(
        vault / "global.md",
        """
        ---
        uuid: g
        ---
        ## Runtime
        ```yaml settings
        log_level: INFO
        ```
        """,
    )
    _write_md(
        vault / "providers.md",
        """
        ---
        uuid: p
        ---
        ## Provider defaults
        ```yaml settings
        llm: {}
        ```
        """,
    )
    _write_md(
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        tasks:
          plan:
            primary:
              model_id: openai.chat.gpt_5_4
        ```
        """,
    )

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    bundle = compiler.compile_all(auto_heal=False)

    assert bundle.llm_routing.tasks["plan"].primary.model_id == "openai.chat.gpt_5_4"
    assert bundle.llm_routing.tasks["plan"].primary.provider == "openai"
    compiled = (runtime_dir / "llm_routing.yaml").read_text(encoding="utf-8")
    assert "gpt-5.4" in compiled


def test_compile_all_rejects_incompatible_model_kind_for_embed_task(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault" / "@Settings"
    runtime_dir = tmp_path / "runtime" / "settings"

    _write_md(
        vault / "global.md",
        """
        ---
        uuid: g
        ---
        ## Runtime
        ```yaml settings
        log_level: INFO
        ```
        """,
    )
    _write_md(
        vault / "providers.md",
        """
        ---
        uuid: p
        ---
        ## Provider defaults
        ```yaml settings
        llm: {}
        ```
        """,
    )
    _write_md(
        vault / "llm_routing.md",
        """
        ---
        uuid: r
        ---
        ## Routing
        ```yaml settings
        tasks:
          embed:
            primary:
              model_id: openai.chat.gpt_5_4_mini
        ```
        """,
    )

    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    with pytest.raises(ValueError, match="expected kind=embedding"):
        compiler.compile_all(auto_heal=False)
