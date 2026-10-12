"""Fitness checks for the selected vault's Sources landing zone (#3414)."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

import app.knowledge_acquisition.candidate_writeback as candidate_writeback
from app.heimdal import (
    candidate_projection,
    cursor_store,
    meeting_finalization,
    meeting_ledger,
    observation_log,
)
from app.heimdal.publish import publish_observation
from app.knowledge_acquisition.candidate_writeback import (
    CandidateWritebackError,
    write_candidate_note,
)
from app.knowledge_acquisition.source_bundle import (
    SourceBundleError,
    materialize_youtube_source_bundle,
)
from app.knowledge_acquisition.source_frames import (
    CapturedFrame,
    SourceFramesError,
    _bundle_folder as source_frames_bundle_folder,
    capture_source_frames,
)
from app.mcp.vault_tools import VaultToolError, append_note
from app.settings.locations import canonical_settings_root
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition.test_candidate_writeback import _assembled_candidate
from tests.knowledge_acquisition.test_source_frames import _moments as _source_moments
from tests.knowledge_acquisition.test_youtube_source_bundle import _source_material

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGURED_SOURCES = "ConfiguredSources"

# This is the full current writer census. Each public writer is exercised below through its
# production entry point; changing the census requires updating both the implementation map and
# the selected-vault assertions.
REGISTERED_SOURCE_WRITERS = {
    ("app/knowledge_acquisition/candidate_writeback.py", "write_candidate_note"),
    ("app/knowledge_acquisition/source_bundle.py", "materialize_youtube_source_bundle"),
    ("app/knowledge_acquisition/source_frames.py", "capture_source_frames"),
    ("app/heimdal/candidate_projection.py", "write_candidate_note"),
    ("app/heimdal/candidate_projection.py", "write_reading_candidate_note"),
    ("app/heimdal/candidate_projection.py", "project_pending_candidates"),
    ("app/heimdal/meeting_finalization.py", "finalize_session"),
}

# Bare packaged names remain only in the resolver, read-only sampling, or pure path/classification
# helpers. These exact occurrences are reviewed exceptions; a new literal must be routed through
# the selected-vault resolver before it can be added here.
SOURCE_LITERAL_ALLOWLIST = {
    ("app/cli/alpha_human_flows.py", "_select_sample_files", "Sources"),
    ("app/heimdal/candidate_projection.py", "<module>", "Sources/Heimdal"),
    ("app/heimdal/candidate_projection.py", "<module>", "Sources/Reading/Karakeep"),
    ("app/heimdal/meeting_finalization.py", "<module>", "Sources/Meetings"),
    ("app/knowledge/adapters.py", "FsVaultAdapter.__init__", "Sources"),
    ("app/knowledge/multiwriter.py", "classify_note", "Sources"),
    ("app/knowledge/multiwriter.py", "classify_note_in_vault", "Sources"),
    ("app/knowledge_acquisition/candidate_writeback.py", "<module>", "Sources"),
    ("app/knowledge_acquisition/source_bundle.py", "<module>", "Sources/YouTube/_attachments"),
    ("app/vault/paths.py", "<module>", "Sources"),
}

# Every shipped Sources-root consumer is inventoried, including readers, resolver owners,
# classification helpers, bootstrap, app-agent, and capture exclusions. A new consumer fails this
# check until its role is understood and registered.
SOURCE_RESOLVER_CALLERS = {
    ("app/agents/panel_agent/policy.py", "watcher_panel_writeback_allowed"),
    ("app/api/routes/capture.py", "capture_to_inbox"),
    ("app/heimdal/candidate_projection.py", "write_candidate_note"),
    ("app/heimdal/candidate_projection.py", "write_reading_candidate_note"),
    ("app/heimdal/candidate_projection.py", "project_pending_candidates"),
    ("app/heimdal/meeting_finalization.py", "meetings_dir_rel"),
    ("app/journaling/day_context.py", "_read_captures"),
    ("app/knowledge/service.py", "_build_adapter"),
    ("app/knowledge/service.py", "resolve_knowledge_port"),
    ("app/knowledge_acquisition/acquire.py", "_candidate_will_render"),
    ("app/knowledge_acquisition/candidate_writeback.py", "write_candidate_note"),
    ("app/knowledge_acquisition/source_bundle.py", "materialize_youtube_source_bundle"),
    ("app/knowledge_acquisition/source_frames.py", "_bundle_folder"),
    ("app/mcp/vault_tools.py", "append_note"),
    ("app/ops/karakeep_runtime.py", "child_preflight"),
    ("app/services/artifact_identity.py", "_is_create_once"),
    ("app/settings/mimer_scaffolder.py", "MimerScaffolder.scaffold"),
    ("app/vault/paths.py", "get_vault_sources_dir_rel"),
}

SOURCE_WRITE_EXCLUSIONS = {
    ("app/api/routes/capture.py", "capture_to_inbox"),
    ("app/mcp/vault_tools.py", "append_note"),
}

SOURCE_WRITE_SINKS = {
    "append_note_relative",
    "create_candidate_note_once",
    "write_note_from_absolute",
    "write_note_relative",
}
SOURCE_PATH_BUILDERS = {
    "_bundle_folder",
    "candidate_note_path",
    "get_vault_sources_dir_rel",
    "meetings_dir_rel",
    "reading_candidate_note_path",
    "resolve_vault_sources_dir_rel",
    "validate_youtube_attachment_root",
}


def _module_function_for(node_stack: list[ast.AST]) -> str:
    names = [
        node.name
        for node in node_stack
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not names:
        return "<module>"
    if len(names) > 1 and isinstance(
        next(node for node in reversed(node_stack) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))),
        (ast.FunctionDef, ast.AsyncFunctionDef),
    ):
        return ".".join(names[-2:])
    return names[-1]


def _source_code_inventory(repo_root: Path = REPO_ROOT) -> tuple[
    set[tuple[str, str, str]], set[tuple[str, str]], set[tuple[str, str]]
]:
    literals: set[tuple[str, str, str]] = set()
    resolver_callers: set[tuple[str, str]] = set()
    source_write_callers: set[tuple[str, str]] = set()
    trees = {
        path.relative_to(repo_root).as_posix(): ast.parse(
            path.read_text(encoding="utf-8"), filename=path.relative_to(repo_root).as_posix()
        )
        for path in sorted((repo_root / "app").rglob("*.py"))
    }
    aliases_by_file: dict[str, dict[str, str]] = {}
    for relative, tree in trees.items():
        aliases = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app."):
                aliases.update({alias.asname or alias.name: alias.name for alias in node.names})
        aliases_by_file[relative] = aliases

    def call_name(
        relative: str, callee: ast.expr, aliases: dict[str, str] | None = None
    ) -> str | None:
        if isinstance(callee, ast.Name):
            return (aliases or aliases_by_file[relative]).get(callee.id, callee.id)
        if isinstance(callee, ast.Attribute):
            return callee.attr
        return None

    def function_import_aliases(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
        aliases: dict[str, str] = {}

        class LocalImports(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                return

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                return

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                if (node.module or "").startswith("app."):
                    aliases.update(
                        {alias.asname or alias.name: alias.name for alias in node.names}
                    )

        visitor = LocalImports()
        for statement in function.body:
            visitor.visit(statement)
        return aliases

    calls_by_function: dict[tuple[str, str], list[tuple[str, ast.Call]]] = {}
    function_nodes: dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef] = {}
    aliases_by_function: dict[tuple[str, str], dict[str, str]] = {}
    for relative, tree in trees.items():
        stack: list[ast.AST] = []

        class Inventory(ast.NodeVisitor):
            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                stack.append(node)
                self.generic_visit(node)
                stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node)
                key = (relative, _module_function_for(stack))
                function_nodes[key] = node
                aliases = dict(aliases_by_file[relative])
                for index, ancestor in enumerate(stack[:-1]):
                    if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        ancestor_key = (relative, _module_function_for(stack[: index + 1]))
                        aliases.update(aliases_by_function.get(ancestor_key, {}))
                aliases.update(function_import_aliases(node))
                aliases_by_function[key] = aliases
                calls: list[tuple[str, ast.Call]] = []

                class DirectCalls(ast.NodeVisitor):
                    def visit_FunctionDef(self, nested: ast.FunctionDef) -> None:
                        return

                    visit_AsyncFunctionDef = visit_FunctionDef

                    def visit_Call(self, call: ast.Call) -> None:
                        name = call_name(relative, call.func, aliases)
                        if name:
                            calls.append((name, call))
                        self.generic_visit(call)

                for statement in node.body:
                    DirectCalls().visit(statement)
                calls_by_function[key] = calls
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Constant(self, node: ast.Constant) -> None:
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value == "Sources" or node.value.startswith("Sources/"):
                        literals.add((relative, _module_function_for(stack), node.value))

            def visit_Call(self, node: ast.Call) -> None:
                active_function = next(
                    (
                        (relative, _module_function_for(stack[: index + 1]))
                        for index in range(len(stack) - 1, -1, -1)
                        if isinstance(stack[index], (ast.FunctionDef, ast.AsyncFunctionDef))
                    ),
                    None,
                )
                aliases = aliases_by_function.get(active_function, aliases_by_file[relative])
                if call_name(relative, node.func, aliases) in {
                    "get_vault_sources_dir_rel",
                    "resolve_vault_sources_dir_rel",
                }:
                    resolver_callers.add((relative, _module_function_for(stack)))
                self.generic_visit(node)

        Inventory().visit(tree)

    builders_by_function = {
        key
        for key, calls in calls_by_function.items()
        if any(name in SOURCE_PATH_BUILDERS for name, _call in calls)
    }
    sinks_by_function = {
        key
        for key, calls in calls_by_function.items()
        if any(name in SOURCE_WRITE_SINKS for name, _call in calls)
    }
    source_write_callers.update(builders_by_function & sinks_by_function)

    # Follow one explicit helper boundary: aliases are normalized above, and a path value must
    # reach a helper containing a sink. This is intentionally not general Python dataflow.
    path_helper_names = {
        key[1].split(".")[-1] for key in builders_by_function - sinks_by_function
    }
    sink_helper_names = {key[1].split(".")[-1] for key in sinks_by_function}

    def is_source_path(relative: str, expression: ast.AST, names: set[str]) -> bool:
        for child in ast.walk(expression):
            if isinstance(child, ast.Name) and child.id in names:
                return True
            if isinstance(child, ast.Call) and call_name(
                relative, child.func, aliases_by_function.get(key, aliases_by_file[relative])
            ) in (
                SOURCE_PATH_BUILDERS | path_helper_names
            ):
                return True
        return False

    for key, calls in calls_by_function.items():
        function_node = function_nodes[key]
        assignments: list[tuple[list[ast.expr], ast.expr]] = []

        class Assignments(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node is function_node:
                    self.generic_visit(node)

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Assign(self, node: ast.Assign) -> None:
                assignments.append((list(node.targets), node.value))
                self.generic_visit(node.value)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                if node.value is not None:
                    assignments.append(([node.target], node.value))
                    self.generic_visit(node.value)

            def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
                assignments.append(([node.target], node.value))
                self.generic_visit(node.value)

        Assignments().visit(function_node)
        source_names: set[str] = set()
        changed = True
        while changed:
            changed = False
            for targets, value in assignments:
                if is_source_path(key[0], value, source_names):
                    for target in targets:
                        for child in ast.walk(target):
                            if isinstance(child, ast.Name) and child.id not in source_names:
                                source_names.add(child.id)
                                changed = True

        if any(
            name in sink_helper_names
            and any(
                is_source_path(key[0], argument, source_names)
                for argument in (*call.args, *(keyword.value for keyword in call.keywords))
            )
            for name, call in calls
        ):
            source_write_callers.add(key)

    return literals, resolver_callers, source_write_callers


def _configured_vault(root: Path, *, sources_dir: str = CONFIGURED_SOURCES) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    settings = canonical_settings_root(root) / "system-settings.md"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        "---\npaths:\n  sources_dir_rel: " + json.dumps(sources_dir) + "\n---\n",
        encoding="utf-8",
    )
    return VaultContext("selected", "vault-test", "Vault Test", str(root))


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _fixture_media():
    class FixtureMedia:
        def download_temporary_media(
            self, *, item_ref: str, dest_dir: Path, max_bytes: int, max_duration_seconds: int
        ) -> Path:
            target = dest_dir / "fixture.mp4"
            target.write_bytes(b"fixture media")
            return target

        def extract_frame(self, *, media_path: Path, timestamp_seconds: int, work_dir: Path) -> CapturedFrame:
            assert media_path.is_file()
            return CapturedFrame(
                image_bytes=b"\xff\xd8\xfffixture\xff\xd9",
                grayscale_32=bytes([127]) * (32 * 32),
            )

    return FixtureMedia()


def _publish_candidate_observation(*, karakeep: bool, observation_id: str) -> None:
    payload = {
        "observation_id": observation_id,
        "episode_id": observation_id,
        "content": f"Sensor candidate {observation_id}",
        "raw_ref": f"raw:{observation_id}",
        "provenance": {
            "sensor": "karakeep_rest" if karakeep else "fixture_sensor",
            "content_identity": "sha256:" + ("b" if karakeep else "a") * 64,
            "raw_ref": f"raw:{observation_id}",
            "capture_chain": ["fixture"],
        },
    }
    if karakeep:
        payload["content_structure"] = {
            "karakeep": {
                "item_kind": "link",
                "source_item_identity": observation_id,
                "source_url": "https://example.com/sources-zone",
                "tombstone": False,
            }
        }
    publish_observation(
        topic="heimdal.observation.published",
        observation_id=observation_id,
        payload=payload,
        source="test.sources-zone",
        stage_versions={"test": "1"},
    )


def _meeting_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vault: VaultContext) -> str:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", "9f" * 32)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "meeting-outbox.jsonl"))
    monkeypatch.setenv("HEIMDAL_MEETING_LEDGER_PATH", str(tmp_path / "meeting-ledger.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_PROJECTION_PATH", str(tmp_path / "meeting-projection.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_BLOCKS_PATH", str(tmp_path / "meeting-blocks.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_FINALIZATION_PATH", str(tmp_path / "meeting-finalization.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_VAULT_ROOT", str(vault.active_vault_path))
    session_id = f"zone-fitness-{uuid4()}"
    meeting_ledger.open_meeting_session(session_id=session_id, device_id="fixture-device")
    meeting_ledger.close_meeting_session(session_id=session_id, final_seq_count=0)
    return session_id


def test_zone_resolved_via_settings_not_literal() -> None:
    literals, resolver_callers, source_write_callers = _source_code_inventory()
    assert literals == SOURCE_LITERAL_ALLOWLIST
    assert resolver_callers == SOURCE_RESOLVER_CALLERS
    assert source_write_callers == REGISTERED_SOURCE_WRITERS | SOURCE_WRITE_EXCLUSIONS


def test_writer_inventory_follows_aliased_resolvers_and_write_helpers(tmp_path: Path) -> None:
    files = {
        "app/__init__.py": "",
        "app/writers/__init__.py": "",
        "app/writers/paths.py": (
            "def get_vault_sources_dir_rel():\n"
            "    return 'configured-sources'\n"
        ),
        "app/writers/sinks.py": "def write_note_relative(path):\n    return path\n",
        "app/writers/helpers.py": (
            "import app.writers.paths as path_api\n"
            "from app.writers.sinks import write_note_relative as persist_note\n"
            "def build_source_path():\n"
            "    return path_api.get_vault_sources_dir_rel()\n"
            "def write_source_path(path):\n"
            "    return persist_note(path)\n"
        ),
        "app/writers/producer.py": (
            "from app.writers.helpers import build_source_path as make_path\n"
            "from app.writers.helpers import write_source_path as save_path\n"
            "def newly_added_writer():\n"
            "    path = make_path()\n"
            "    return save_path(path)\n"
            "def unrelated_path_and_write_calls():\n"
            "    path = make_path()\n"
            "    return save_path('unrelated')\n"
            "def local_import_writer():\n"
            "    from app.writers.paths import get_vault_sources_dir_rel as resolve\n"
            "    from app.writers.sinks import write_note_relative as persist\n"
            "    return persist(f'{resolve()}/rogue.md')\n"
            "def nested_local_import_writer_3414():\n"
            "    from app.writers.paths import get_vault_sources_dir_rel as resolve_3414\n"
            "    from app.writers.sinks import write_note_relative as persist_3414\n"
            "    def make_path_3414():\n"
            "        return f'{resolve_3414()}/nested.md'\n"
            "    def persist_path_3414(path):\n"
            "        return persist_3414(path)\n"
            "    return persist_path_3414(make_path_3414())\n"
        ),
    }
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    _literals, resolver_callers, source_write_callers = _source_code_inventory(tmp_path)

    assert ("app/writers/helpers.py", "build_source_path") in resolver_callers
    assert (
        "app/writers/producer.py",
        "nested_local_import_writer_3414.make_path_3414",
    ) in resolver_callers
    assert ("app/writers/producer.py", "newly_added_writer") in source_write_callers
    assert ("app/writers/producer.py", "local_import_writer") in source_write_callers
    assert ("app/writers/producer.py", "nested_local_import_writer_3414") in source_write_callers
    assert ("app/writers/producer.py", "unrelated_path_and_write_calls") not in source_write_callers


def test_only_registered_writers_target_sources_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import objects as object_store_module
    from app.stores import reset_store_backends

    monkeypatch.delenv("VAULT_SOURCES_DIR_REL", raising=False)
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "Inbox/inbox.md")
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    vault = _configured_vault(tmp_path / "selected-vault")
    vault_root = Path(vault.active_vault_path or "")
    guard = _guard()
    observed: dict[str, str] = {}

    # YouTube candidate note and source bundle.
    youtube_candidate = _assembled_candidate()
    candidate_note = write_candidate_note(
        youtube_candidate, vault_context=vault, write_guard=guard
    )
    assert candidate_note.status == "written" and candidate_note.artifact_path
    observed["youtube_candidate"] = candidate_note.artifact_path

    proposal_candidate = replace(
        youtube_candidate, extraction_artifact_ids=("sources-zone-extraction",)
    )
    proposal = write_candidate_note(
        proposal_candidate,
        vault_context=vault,
        write_guard=guard,
        proposal_on_existing=True,
    )
    assert proposal.status == "proposal_written" and proposal.artifact_path
    observed["youtube_candidate_proposal"] = proposal.artifact_path

    _raw, transcript, bundle_candidate = _source_material(tmp_path / "youtube-material")
    bundle = materialize_youtube_source_bundle(
        bundle_candidate, transcript, vault_context=vault, write_guard=guard
    )
    assert bundle.status == "written"
    observed["youtube_bundle_transcript"] = bundle.transcript_path
    observed["youtube_bundle_manifest"] = bundle.manifest_path

    # The attached-frame writer is a separate production path under the same resolved root.
    moments, frame_transcript = _source_moments()
    frames = capture_source_frames(
        key_moments=moments,
        transcript=frame_transcript,
        item_ref="abcDEF12345",
        vault_context=vault,
        write_guard=guard,
        media_capture=_fixture_media(),
        temp_root=tmp_path / "media-temp",
    )
    assert frames.status == "frames_retained" and frames.manifest_path
    observed["youtube_frames_manifest"] = frames.manifest_path
    observed["youtube_frame"] = str(frames.frames[0]["path"])

    # Both Heimdal candidate classes use the real per-consumer projection entry point.
    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=False, observation_id="sources-zone-candidate")
    heimdal = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(heimdal) == 1 and heimdal[0].status == "written" and heimdal[0].artifact_path
    observed["heimdal_candidate"] = heimdal[0].artifact_path

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=True, observation_id="sources-zone-reading")
    reading = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(reading) == 1 and reading[0].status == "written" and reading[0].artifact_path
    observed["karakeep_reading_candidate"] = reading[0].artifact_path

    # Meeting close finalization writes the three registered material notes.
    session_id = _meeting_runtime(tmp_path, monkeypatch, vault)
    finalization = meeting_finalization.finalize_session(session_id)
    refs = finalization["receipt"]["artifact_refs"]
    observed.update({f"meeting_{name}": path for name, path in refs.items()})

    assert set(observed) == {
        "youtube_candidate",
        "youtube_candidate_proposal",
        "youtube_bundle_transcript",
        "youtube_bundle_manifest",
        "youtube_frames_manifest",
        "youtube_frame",
        "heimdal_candidate",
        "karakeep_reading_candidate",
        "meeting_transcript",
        "meeting_analysis",
        "meeting_user_notes",
    }
    assert all(path.startswith(f"{CONFIGURED_SOURCES}/") for path in observed.values())
    assert all((vault_root / path).is_file() for path in observed.values())

    # Each Sources producer rejects a target that overlaps the effective capture inbox before
    # publishing. These calls use the actual production writer entry points a second time.
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", candidate_note.artifact_path)
    with pytest.raises(CandidateWritebackError, match="overlaps effective capture note"):
        write_candidate_note(
            proposal_candidate,
            vault_context=vault,
            write_guard=guard,
            proposal_on_existing=True,
        )

    proposal_path = candidate_writeback._versioned_proposal_path(
        proposal_candidate, candidate_note.artifact_path
    )
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", proposal_path)
    with pytest.raises(CandidateWritebackError, match="overlaps effective capture note"):
        write_candidate_note(
            proposal_candidate,
            vault_context=vault,
            write_guard=guard,
            proposal_on_existing=True,
        )

    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", bundle.transcript_path)
    with pytest.raises(SourceBundleError, match="capture note"):
        materialize_youtube_source_bundle(
            bundle_candidate, transcript, vault_context=vault, write_guard=guard
        )

    alternate_frame_root = f"{CONFIGURED_SOURCES}/AlternateFrames"
    alternate_manifest = (
        source_frames_bundle_folder(
            vault_root,
            "abcDEF12345",
            frame_transcript,
            alternate_frame_root,
        )
        / "frames.json"
    ).as_posix()
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", alternate_manifest)
    with pytest.raises(SourceFramesError, match="overlaps effective capture note"):
        capture_source_frames(
            key_moments=moments,
            transcript=frame_transcript,
            item_ref="abcDEF12345",
            vault_context=vault,
            write_guard=guard,
            youtube_attachment_root=alternate_frame_root,
            media_capture=_fixture_media(),
            temp_root=tmp_path / "media-temp-retry",
        )

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=False, observation_id="sources-zone-candidate")
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", str(heimdal[0].artifact_path))
    blocked_candidate = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(blocked_candidate) == 1 and blocked_candidate[0].status == "blocked"

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    _publish_candidate_observation(karakeep=True, observation_id="sources-zone-reading")
    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", str(reading[0].artifact_path))
    blocked_reading = candidate_projection.project_pending_candidates(
        vault_context=vault, write_guard=guard, advance=False
    )
    assert len(blocked_reading) == 1 and blocked_reading[0].status == "blocked"

    monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", refs["transcript"])
    with pytest.raises(meeting_finalization.MeetingFinalizationError, match="overlap the capture note"):
        meeting_finalization.finalize_session(session_id)

    observation_log.reset_memory_observation_log()
    cursor_store.reset_memory_cursor_store()
    object_store_module._MEMORY_STORE.clear()
    reset_store_backends()


def test_capture_and_sources_zone_mutually_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from app.agents.panel_agent.policy import watcher_panel_writeback_allowed
    from app.api.app import app
    from tests.api._vault_test_helpers import bind_initialized_vault

    vault_root = tmp_path / "capture-vault"
    vault_root.mkdir()
    bind_initialized_vault(monkeypatch, vault_root, store_dir=tmp_path)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Inbox")
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "capture-outbox.jsonl"))
    monkeypatch.delenv("VAULT_CAPTURE_NOTE_REL", raising=False)

    response = TestClient(app).post(
        "/api/companion/capture", json={"text": "must not enter Sources"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "capture_sources_overlap"
    assert not (vault_root / "Inbox" / "inbox.md").exists()

    mcp_vault = tmp_path / "mcp-vault"
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", CONFIGURED_SOURCES)
    with pytest.raises(VaultToolError, match="inside the selected vault Sources zone"):
        append_note(
            title="Agent note",
            body="must stay outside Sources",
            vault_root=mcp_vault,
            relative_dir=f"{CONFIGURED_SOURCES}/AgentNotes",
        )
    assert not mcp_vault.exists()

    source_note = vault_root / CONFIGURED_SOURCES / "panel.md"
    source_note.parent.mkdir(parents=True, exist_ok=True)
    source_note.write_text("existing Sources note\n", encoding="utf-8")
    permitted_note = vault_root / "Inbox" / "panel.md"
    permitted_note.parent.mkdir(parents=True, exist_ok=True)
    permitted_note.write_text("existing permitted note\n", encoding="utf-8")

    assert watcher_panel_writeback_allowed(
        f"{CONFIGURED_SOURCES}/panel.md",
        vault_root=vault_root,
        sources_root_rel=CONFIGURED_SOURCES,
    ) is False
    assert watcher_panel_writeback_allowed(
        "Inbox/panel.md",
        vault_root=vault_root,
        sources_root_rel=CONFIGURED_SOURCES,
    ) is True
