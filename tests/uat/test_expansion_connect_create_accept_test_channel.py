"""No-mock, opt-in UAT for the isolated Expansion Connect/Create/Accept path.

The runtime scenarios use real test-channel retrieval, synthesis, WriteGuard,
vault files, and the governed acceptance function. They never substitute a
provider, index, guard, or production function. The final synthetic test-actor
action is a separately authorized phase; see the companion runbook.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.agents.panel.parser import parse_panel
from app.expansion.accept import DraftNotAcceptedError, accept_draft
from app.expansion.connect import ConnectPassConfig, run_connect_pass
from app.expansion.create import CreateRequest, OutputKind, SourceInput, run_create_pass
from app.index.artifact_metadata import compute_indexed_content_hash
from app.retrieval.capability import RetrievalRequest, retrieve
from app.stores import get_vector_index
from app.vault.paths import get_vault_system_dir_rel
from scripts.yaml_roundtrip import load_frontmatter

RUN_ENV = "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_UAT"
TEST_ACTOR_ENV = "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_TEST_ACTOR"
EXPANSION_ACTOR_AUTHORIZATION_REF = (
    "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4826#issuecomment-6107736254"
)
EXPECTED_IDENTITY = {
    "provider": "ollama",
    "model": "bge-m3:latest",
    "dim": 1024,
    "normalize": True,
}
CHANNEL_ENV_KEYS = (
    "PKM_ENVIRONMENT",
    "PKM_CHANNEL",
    "VAULT_ROOT_TEST",
    "DATABASE_URL",
    "DB_DSN",
    "STORE_BACKEND",
    "INDEX_OUTBOX_PATH",
    "LLM_FORCE_PROVIDER",
    "LLM_FORCE_MODEL",
    "LLM_PROVIDER_ENFORCE",
    "LLM_PROVIDER",
    "LLM_CHAT_MODEL",
    "LLM_EMBED_MODEL",
    "REASONING_PROVIDER",
)
# Root pytest safety setup removes VAULT_ROOT and may normalize DB/provider
# settings. Capture only the explicit TEST selectors at import so this opt-in
# module can restore them inside its fixture without using the operator vault.
_CAPTURED_TEST_ENV = {name: os.getenv(name) for name in CHANNEL_ENV_KEYS}


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.fail(f"{name} is required for this isolated TEST UAT")
    return value


def _restore_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _CAPTURED_TEST_ENV.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _subprocess_env(vault_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["VAULT_ROOT"] = str(vault_root)
    environment["VAULT_ROOT_TEST"] = str(vault_root)
    return environment


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=False, capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2]
    )
    if result.returncode != 0:
        pytest.fail("cannot establish exact candidate identity from the current checkout")
    return result.stdout.strip()


def _candidate_identity() -> dict[str, str]:
    head = _git_value("rev-parse", "HEAD")
    base = _git_value("merge-base", "HEAD", "origin/main")
    if _git_value("status", "--porcelain"):
        pytest.fail("live UAT requires a clean checkout at the candidate SHA")
    return {"base_sha": base, "head_sha": head}


def _run_channel_command(args: list[str], *, vault_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=_subprocess_env(vault_root),
        cwd=Path(__file__).resolve().parents[2],
    )


def _assert_test_channel_preflight(vault_root: Path) -> None:
    result = _run_channel_command(
        ["ops", "channel-preflight", "--channel", "test", "--context", "host"],
        vault_root=vault_root,
    )
    # Do not echo preflight diagnostics: failure output can include the actual
    # value of a misbound environment variable.
    assert result.returncode == 0, "test-channel preflight failed; inspect the named bindings locally"


def _read_doctor(vault_root: Path) -> dict[str, Any]:
    result = _run_channel_command(["index", "doctor", "--strict", "--json"], vault_root=vault_root)
    assert result.returncode == 0, "strict index doctor failed; inspect its output locally"
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError("strict index doctor did not return JSON") from exc
    assert report.get("status") == "ok"
    assert report.get("issues") == []
    assert report.get("expected_identity") == EXPECTED_IDENTITY
    assert report.get("stored_identity") == EXPECTED_IDENTITY
    return report


def _assert_no_mock_reasoning_route() -> dict[str, str]:
    from app.settings.reasoning_route import resolve_effective_reasoning_route
    from app.reasoning.provider import OllamaDeliberationAgent, get_deliberation_agent

    backend = (os.getenv("REASONING_PROVIDER") or "").strip().lower()
    assert backend in {"", "llm", "ollama"}, "no-mock TEST UAT requires a supported live reasoning backend"
    assert (os.getenv("LLM_PROVIDER") or "").strip().lower() != "mock", (
        "no-mock TEST UAT refuses the reasoning provider's mock-agent fallback"
    )
    assert not (os.getenv("CI") == "1" and not backend), "no-mock TEST UAT refuses CI's implicit mock backend"
    agent = get_deliberation_agent()
    assert isinstance(agent, OllamaDeliberationAgent), "effective reasoning selection resolved to a mock or unknown agent"
    route = resolve_effective_reasoning_route()
    assert route.provider.strip().lower() != "mock", "no-mock TEST UAT refuses a mock effective reasoning route"
    return {"provider": route.provider, "model": route.model}


def _successful_cognition(frontmatter: dict[str, Any]) -> dict[str, Any]:
    proposed_by = frontmatter.get("proposed_by")
    cognition = proposed_by.get("cognition") if isinstance(proposed_by, dict) else None
    assert isinstance(cognition, dict), "Create draft lacks its cognition execution receipt"
    assert cognition.get("outcome") == "success", "Create cognition did not complete successfully"
    assert cognition.get("degraded") is False and cognition.get("degraded_reason") is None, (
        "Create cognition degraded to deterministic collation; do not report technical UAT PASS"
    )
    return cognition


def _outside_ai_panels(text: str) -> str:
    remaining: list[str] = []
    in_panel = False
    for line in text.splitlines(keepends=True):
        marker = line.strip()
        if marker == "%% AI:Start %%":
            assert not in_panel, "nested AI panel marker in a source note"
            in_panel = True
            continue
        if marker == "%% AI:End %%":
            assert in_panel, "unmatched AI panel end marker in a source note"
            in_panel = False
            continue
        if not in_panel:
            remaining.append(line)
    assert not in_panel, "unterminated AI panel in a source note"
    return "".join(remaining)


def _relative_source_path(raw: str, vault_root: Path) -> Path:
    candidate = (vault_root / raw).resolve()
    assert candidate.is_relative_to(vault_root), "a selected source escapes the TEST vault"
    assert candidate.is_file(), "a selected TEST source is missing"
    relative = candidate.relative_to(vault_root).as_posix()
    assert not relative.startswith("_system/drafts/"), "a staged draft cannot be a Connect/Create source"
    return candidate


def _source_input(path: Path, vault_root: Path) -> tuple[SourceInput, str]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(text)
    object_id = str(frontmatter.get("uuid") or f"path:{path.relative_to(vault_root).as_posix()}").strip()
    quote = next(
        (line.strip() for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")),
        None,
    )
    assert quote, "a selected TEST source must contain a quotable body span"
    return (
        SourceInput(
            object_id=object_id,
            note_path=path.relative_to(vault_root).as_posix(),
            text=text,
            quoted_spans=(quote,),
            language=str(frontmatter.get("language") or "und"),
            review_state=str(frontmatter.get("review_state") or "reviewed"),
        ),
        str(frontmatter.get("domain") or "").strip(),
    )


def _shared_source_scope(scopes: tuple[str, str]) -> str:
    """Require the selected pair to share one explicit or unscoped domain."""
    assert scopes[0] == scopes[1], "the selected source pair must share one scope"
    return scopes[0] or "unscoped"


def _source_ref_matches(raw: str, path: Path, vault_root: Path) -> bool:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = vault_root / candidate
    try:
        return candidate.resolve() == path.resolve()
    except OSError:
        return False


def _index_source_hashes_match(rows: list[dict[str, Any]], sources: tuple[SourceInput, ...], vault_root: Path) -> bool:
    for source in sources:
        source_path = (vault_root / source.note_path).resolve()
        matching = [
            row
            for row in rows
            if _source_ref_matches(str(row.get("source_ref") or ""), source_path, vault_root)
        ]
        if len(matching) != 1:
            return False
        payload = matching[0].get("payload") or {}
        provenance = payload.get("provenance") or {}
        current_text = source_path.read_text(encoding="utf-8")
        if provenance.get("content_hash") != compute_indexed_content_hash(current_text):
            return False
    return True


def _wait_for_index_convergence(
    sources: tuple[SourceInput, ...], vault_root: Path, *, timeout_seconds: float = 60.0
) -> tuple[list[dict[str, Any]], str]:
    """Wait for stable durable rows whose indexed hashes match current sources."""
    index = get_vector_index()
    deadline = time.monotonic() + timeout_seconds
    last_generation: str | None = None
    last_signature: tuple[tuple[str, str, str], ...] | None = None
    stable_observations = 0
    while time.monotonic() < deadline:
        generation_before = index.generation()
        rows = list(index.all_rows())  # exhaustive durable index read, never top-k
        generation_after = index.generation()
        signature = tuple(
            sorted(
                (
                    str(row.get("object_id") or ""),
                    str(row.get("source_ref") or ""),
                    str(((row.get("payload") or {}).get("provenance") or {}).get("content_hash") or ""),
                )
                for row in rows
            )
        )
        stable_read = generation_before == generation_after and signature == last_signature
        if stable_read and _index_source_hashes_match(rows, sources, vault_root):
            stable_observations += 1
        else:
            stable_observations = 0
        if stable_observations >= 2:
            return rows, generation_after
        last_generation = generation_after
        last_signature = signature
        time.sleep(1.0)
    pytest.fail(
        "the durable TEST index did not converge to the selected source hashes "
        f"within {timeout_seconds:g}s (last generation observed: {last_generation or 'none'})"
    )


def _draft_rows(rows: list[dict[str, Any]], draft_path: Path, draft_id: str, vault_root: Path) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload") or {}
        if str(row.get("object_id") or "") == draft_id or str(payload.get("artifact_id") or "") == draft_id:
            matched.append(row)
            continue
        if _source_ref_matches(str(row.get("source_ref") or ""), draft_path, vault_root):
            matched.append(row)
    return matched


@dataclass(frozen=True)
class UatContext:
    vault_root: Path
    outbox_path: Path
    source_paths: tuple[Path, Path]
    sources: tuple[SourceInput, SourceInput]
    source_scope: str
    connect_query: str
    run_id: str
    receipt_path: Path
    candidate: dict[str, str]
    reasoning_route: dict[str, str]

    def receipt(self) -> dict[str, Any]:
        if not self.receipt_path.exists():
            return {}
        try:
            payload = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError("UAT receipt is unreadable; do not repeat an uncertain phase") from exc
        assert isinstance(payload, dict), "UAT receipt is not an object"
        return payload

    def record(self, **values: Any) -> None:
        payload = self.receipt()
        payload.setdefault("contract", "expansion-connect-create-accept-test-channel.v1")
        payload.setdefault("run_id", self.run_id)
        payload.setdefault("candidate", self.candidate)
        payload.setdefault(
            "channel",
            {
                "name": "test",
                "preflight": "pass",
                "stored_embedding_identity": EXPECTED_IDENTITY,
                "vault_binding": "VAULT_ROOT_TEST",
                "database": "app_test",
                "reasoning_route": self.reasoning_route,
                "receipt_redacted": True,
            },
        )
        payload.update(values)
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        self.receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def uat_context(monkeypatch: pytest.MonkeyPatch) -> UatContext:
    if not _enabled(RUN_ENV):
        pytest.skip(f"opt-in no-mock TEST UAT; set {RUN_ENV}=1 after prerequisites are qualified")

    _restore_test_env(monkeypatch)
    assert os.getenv("PKM_ENVIRONMENT") == "test", "PKM_ENVIRONMENT must be explicitly test"
    assert os.getenv("PKM_CHANNEL") == "test", "PKM_CHANNEL must be explicitly test"
    assert os.getenv("STORE_BACKEND", "").strip().lower() == "postgres", "TEST UAT requires the Postgres backend"
    for name in ("LLM_PROVIDER", "LLM_FORCE_PROVIDER"):
        if (os.getenv(name) or "").strip().lower() == "mock":
            pytest.fail("no-mock TEST UAT refuses a mock model provider")

    test_root = Path(_required_env("VAULT_ROOT_TEST")).expanduser().resolve()
    assert test_root.is_dir(), "the pre-existing TEST vault must be reachable"
    database_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN") or ""
    try:
        from sqlalchemy.engine import make_url

        database_name = make_url(database_url).database
    except Exception as exc:
        raise AssertionError("the explicit TEST database binding cannot be classified") from exc
    assert database_name == "app_test", "the TEST UAT requires the isolated app_test database"

    # pytest's root safety harness clears the ambiguous VAULT_ROOT. Rebind it
    # only from the independently required test-only selector before preflight.
    monkeypatch.setenv("VAULT_ROOT", str(test_root))
    _assert_test_channel_preflight(test_root)
    reasoning_route = _assert_no_mock_reasoning_route()
    candidate = _candidate_identity()
    raw_sources = [part.strip() for part in _required_env("UAT_EXPANSION_SOURCE_PATHS").split(",") if part.strip()]
    assert len(raw_sources) == 2, "UAT_EXPANSION_SOURCE_PATHS must name exactly two seeded source notes"
    source_paths = tuple(_relative_source_path(raw, test_root) for raw in raw_sources)
    assert source_paths[0] != source_paths[1], "the selected source pair must be distinct"
    source_data = tuple(_source_input(path, test_root) for path in source_paths)
    sources = tuple(item[0] for item in source_data)
    scopes = tuple(item[1] for item in source_data)
    source_scope = _shared_source_scope((scopes[0], scopes[1]))

    outbox_path = Path(_required_env("INDEX_OUTBOX_PATH")).expanduser().resolve()
    run_id = _required_env("UAT_EXPANSION_RUN_ID")
    assert len(run_id) >= 8 and all(char.isalnum() or char in "-_" for char in run_id), "UAT run id must be filesystem-safe and unique"
    system_root = Path(get_vault_system_dir_rel(test_root))
    receipt_path = test_root / system_root / "receipts" / f"expansion-connect-create-accept-{run_id}.json"
    receipt_exists = receipt_path.exists()
    prior_receipt: dict[str, Any] = {}
    if receipt_exists:
        try:
            prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError("UAT run id already has an unreadable receipt; choose a fresh run id") from exc
    if _enabled(TEST_ACTOR_ENV):
        assert prior_receipt.get("technical_phase") == "pass", "synthetic action requires the prior technical PASS receipt"
        assert prior_receipt.get("candidate") == candidate, "candidate changed after technical PASS; start a fresh UAT"
        assert prior_receipt.get("run_id") == run_id, "receipt run id does not match the requested action"

    return UatContext(
        vault_root=test_root,
        outbox_path=outbox_path,
        source_paths=(source_paths[0], source_paths[1]),
        sources=(sources[0], sources[1]),
        source_scope=source_scope,
        connect_query=_required_env("UAT_EXPANSION_CONNECT_QUERY"),
        run_id=run_id,
        receipt_path=receipt_path,
        candidate=candidate,
        reasoning_route=reasoning_route,
    )


def test_test_channel_identity_and_doctor_are_strict(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert not receipt, "technical UAT run id must be fresh"
    report = _read_doctor(uat_context.vault_root)
    uat_context.record(
        technical_phase="doctor_pass",
        doctor={
            "status": report["status"],
            "expected_identity": report["expected_identity"],
            "stored_identity": report["stored_identity"],
            "issue_count": len(report["issues"]),
        },
    )


def test_connect_is_candidate_only_and_unchecked(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert receipt.get("technical_phase") == "doctor_pass", "run the strict identity/doctor phase first"
    assert receipt.get("candidate") == uat_context.candidate, "candidate changed during the UAT"
    before_text = {path: path.read_bytes().decode("utf-8") for path in uat_context.source_paths}
    before_frontmatter = {path: load_frontmatter(text)[0] for path, text in before_text.items()}
    before_markdown = {
        path.relative_to(uat_context.vault_root): path.read_bytes()
        for path in uat_context.vault_root.rglob("*.md")
    }
    top_hits = retrieve(RetrievalRequest(query=uat_context.connect_query, k=2)).hits
    selected_paths = set(uat_context.source_paths)
    assert len(top_hits) == 2, "the bounded Connect preflight must return exactly two top-ranked sources"
    assert all(any(_source_ref_matches(hit.source_ref, path, uat_context.vault_root) for path in selected_paths) for hit in top_hits), (
        "the query's top two results include a source outside the selected pair; Connect was not run"
    )
    assert all(any(_source_ref_matches(hit.source_ref, path, uat_context.vault_root) for hit in top_hits) for path in selected_paths), (
        "the query's top two results must contain both selected sources; Connect was not run"
    )
    drafts_dir = uat_context.vault_root / Path(get_vault_system_dir_rel(uat_context.vault_root)) / "drafts"
    drafts_before = set(drafts_dir.glob("*.md")) if drafts_dir.exists() else set()

    report = run_connect_pass(
        vault_root=uat_context.vault_root,
        queries=[uat_context.connect_query],
        config=ConnectPassConfig(retrieval_k=2),
        outbox_path=uat_context.outbox_path,
    )
    logical_pairs: dict[str, set[str]] = {}
    for finding in report.findings:
        logical_pairs.setdefault(finding.finding_id, set()).add(finding.note_uuid)
    selected_pair = {source.object_id for source in uat_context.sources}
    selected_finding_ids = {
        finding_id for finding_id, note_ids in logical_pairs.items() if selected_pair <= note_ids
    }
    assert selected_finding_ids, "Connect produced no one-finding same-scope result containing both selected identities"

    changed_paths = {
        path for path, original in before_text.items() if path.read_bytes().decode("utf-8") != original
    }
    after_markdown = {
        path.relative_to(uat_context.vault_root): path.read_bytes()
        for path in uat_context.vault_root.rglob("*.md")
    }
    assert after_markdown.keys() == before_markdown.keys(), "Connect created or removed a Markdown artifact"
    changed_markdown = {
        relative_path
        for relative_path, original in before_markdown.items()
        if after_markdown[relative_path] != original
    }
    selected_relative_paths = {
        path.relative_to(uat_context.vault_root) for path in uat_context.source_paths
    }
    assert changed_markdown <= selected_relative_paths, "Connect changed Markdown outside the selected source pair"
    for path in uat_context.source_paths:
        after = path.read_bytes().decode("utf-8")
        assert load_frontmatter(after)[0] == before_frontmatter[path], "Connect changed source frontmatter"
        assert _outside_ai_panels(before_text[path]) == _outside_ai_panels(after), "Connect changed source text outside its governed AI proposal block"
        panel_actions = parse_panel(after).actions
        expected = [
            f"[curation:{finding.finding_class.value}] {finding.proposed} (finding {finding.finding_id[:12]})"
            for finding in report.findings
            if finding.note_uuid == next(source.object_id for source in uat_context.sources if source.note_path == path.relative_to(uat_context.vault_root).as_posix())
            and finding.finding_id in selected_finding_ids
        ]
        assert expected, "the selected logical finding lacks its source-side proposal"
        for proposal in expected:
            matching_actions = [action for action in panel_actions if action.text == proposal]
            assert len(matching_actions) == 1, "selected source must contain one Connect proposal"
            assert not matching_actions[0].checked, "a Connect proposal must remain unchecked"
            assert matching_actions[0].option_id and matching_actions[0].proposal_pending, (
                "a Connect proposal must retain its persistent option and human-gate markers"
            )
    drafts_after = set(drafts_dir.glob("*.md")) if drafts_dir.exists() else set()
    assert drafts_after == drafts_before, "Connect created or removed a staged draft"
    assert changed_paths <= set(uat_context.source_paths), "Connect changed a path outside the selected source pair"
    uat_context.record(
        connect="candidate_only_unchecked",
        selected_source_ids=sorted(selected_pair),
        selected_source_scope=uat_context.source_scope,
        selected_finding_ids=sorted(selected_finding_ids),
        source_changes_within_governed_block=True,
        canonical_or_draft_artifacts_created=0,
    )


def test_create_stages_resolvable_sources_and_excludes_draft_from_retrieval(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert receipt.get("connect") == "candidate_only_unchecked", "run the Connect phase first"
    assert receipt.get("candidate") == uat_context.candidate, "candidate changed during the UAT"
    canonical_before = {
        path.relative_to(uat_context.vault_root).as_posix()
        for path in uat_context.vault_root.rglob("*.md")
        if "drafts" not in path.relative_to(uat_context.vault_root).parts
    }
    request = CreateRequest(
        kind=OutputKind.OVERVIEW,
        title=f"UAT Connect Create Accept {uat_context.run_id}",
        sources=uat_context.sources,
        question=uat_context.connect_query,
        trace_id=uat_context.run_id,
    )
    report = run_create_pass(request, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    assert report.activatable and report.draft_path and report.receipt_id, "Create did not produce one staged proposal"
    draft_path = (uat_context.vault_root / report.draft_path).resolve()
    assert draft_path.is_relative_to(uat_context.vault_root), "Create draft escaped the TEST vault"
    frontmatter, draft_text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    assert frontmatter.get("kind") == "draft"
    assert frontmatter.get("derived_by") == "synthesis"
    assert frontmatter.get("authority_state") == "proposal"
    assert frontmatter.get("sources") == [source.object_id for source in uat_context.sources]
    cognition = _successful_cognition(frontmatter)
    acceptance_line = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    assert draft_text.count(acceptance_line) == 1, "Create did not write exactly one dedicated unchecked acceptance control"

    rows, generation = _wait_for_index_convergence(uat_context.sources, uat_context.vault_root)
    excluded = _draft_rows(rows, draft_path, draft_id, uat_context.vault_root)
    assert not excluded, "the staged draft is present in the exhaustive durable retrieval index"
    retrieval = retrieve(RetrievalRequest(query=uat_context.connect_query, k=100))
    assert all(
        not _source_ref_matches(hit.source_ref, draft_path, uat_context.vault_root)
        for hit in retrieval.hits
    ), "retrieval returned the staged draft"
    canonical_after = {
        path.relative_to(uat_context.vault_root).as_posix()
        for path in uat_context.vault_root.rglob("*.md")
        if "drafts" not in path.relative_to(uat_context.vault_root).parts
    }
    assert canonical_after == canonical_before, "Create wrote outside the staging directory"
    uat_context.record(
        draft_path=Path(report.draft_path).as_posix(),
        draft_id=draft_id,
        create_receipt_id=report.receipt_id,
        cognition={
            "outcome": cognition["outcome"],
            "degraded": cognition["degraded"],
            "degraded_reason": cognition.get("degraded_reason"),
            "claim_count": cognition.get("claims"),
            "inference_count": cognition.get("inferences"),
        },
        index_convergence={"status": "stable_source_hashes", "generation": generation, "rows_scanned": len(rows)},
        draft_excluded_from_full_index=True,
        draft_excluded_from_retrieval=True,
        technical_phase="create_staged",
    )


def test_accept_rejects_unchecked_checkbox(uat_context: UatContext) -> None:
    receipt = uat_context.receipt()
    assert receipt.get("technical_phase") == "create_staged", "run Connect and Create before acceptance checks"
    draft_path = (uat_context.vault_root / str(receipt["draft_path"])).resolve()
    assert draft_path.is_relative_to(uat_context.vault_root)
    before_files = {path.relative_to(uat_context.vault_root) for path in uat_context.vault_root.rglob("*.md")}
    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    after_files = {path.relative_to(uat_context.vault_root) for path in uat_context.vault_root.rglob("*.md")}
    assert after_files == before_files, "unchecked acceptance wrote or removed a canonical artifact"
    assert draft_path.exists(), "unchecked draft must remain staged"
    uat_context.record(unchecked_acceptance="refused_without_write", technical_phase="pass", test_actor_action="pending")


def test_checked_checkbox_uses_only_governed_materialization_path(uat_context: UatContext) -> None:
    if not _enabled(TEST_ACTOR_ENV):
        pytest.skip(
            f"authorized synthetic actor phase; set {TEST_ACTOR_ENV}=1 only after current TEST "
            "qualification and the #4826 owner authorization are verified"
        )
    receipt = uat_context.receipt()
    assert receipt.get("technical_phase") == "pass", "synthetic action requires the prior complete technical PASS"
    assert receipt.get("candidate") == uat_context.candidate, "candidate changed after technical PASS"
    _assert_test_channel_preflight(uat_context.vault_root)
    _read_doctor(uat_context.vault_root)

    draft_path = (uat_context.vault_root / str(receipt["draft_path"])).resolve()
    assert draft_path.is_relative_to(uat_context.vault_root)
    draft_id = str(receipt["draft_id"])
    text = draft_path.read_text(encoding="utf-8")
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_lower = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_upper = f"- [X] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1 and checked_lower not in text and checked_upper not in text, "the exact dedicated control is not in its one-time unchecked state"
    assert "test_actor_attempt" not in receipt, "an earlier action attempt is uncertain; reconcile it read-only and do not replay"

    uat_context.record(
        test_actor_attempt={
            "status": "started",
            "actor": "synthetic_test_actor",
            "authorization_ref": EXPANSION_ACTOR_AUTHORIZATION_REF,
            "checkbox_count": 1,
        }
    )
    draft_path.write_text(text.replace(unchecked, checked_lower, 1), encoding="utf-8")
    checked_text = draft_path.read_text(encoding="utf-8")
    assert checked_text.count(checked_lower) == 1 and unchecked not in checked_text
    uat_context.record(
        test_actor_attempt={
            "status": "checkbox_checked",
            "actor": "synthetic_test_actor",
            "authorization_ref": EXPANSION_ACTOR_AUTHORIZATION_REF,
            "checkbox_count": 1,
        }
    )

    result = accept_draft(draft_path, vault_root=uat_context.vault_root, outbox_path=uat_context.outbox_path)
    assert result.status == "accepted" and result.final_note_path and result.receipt_id
    final_path = (uat_context.vault_root / result.final_note_path).resolve()
    assert final_path.is_relative_to(uat_context.vault_root)
    final_frontmatter, final_body = load_frontmatter(final_path.read_text(encoding="utf-8"))
    assert final_frontmatter.get("sources") == [source.object_id for source in uat_context.sources]
    assert final_frontmatter.get("derived_by") == "synthesis"
    assert final_frontmatter.get("accepted_by") == "human"
    assert final_frontmatter.get("acceptance_receipt_id") == result.receipt_id
    assert not any("Accept this draft into the vault" in line for line in final_body.splitlines())
    uat_context.record(
        accepted={
            "status": "accepted",
            "actor": "synthetic_test_actor",
            "authorization_ref": EXPANSION_ACTOR_AUTHORIZATION_REF,
            "draft_path": Path(receipt["draft_path"]).as_posix(),
            "final_note_path": Path(result.final_note_path).as_posix(),
            "source_ids": [source.object_id for source in uat_context.sources],
            "acceptance_receipt_id": result.receipt_id,
            "derived_by": final_frontmatter["derived_by"],
            "accepted_by": final_frontmatter["accepted_by"],
        },
        disposition="synthetic_test_actor_acceptance_pass",
    )


@pytest.mark.parametrize(
    ("binding", "value", "message"),
    [
        ("PKM_ENVIRONMENT", None, "PKM_ENVIRONMENT must be explicitly test"),
        ("PKM_ENVIRONMENT", "development", "PKM_ENVIRONMENT must be explicitly test"),
        ("PKM_CHANNEL", None, "PKM_CHANNEL must be explicitly test"),
        ("PKM_CHANNEL", "prod", "PKM_CHANNEL must be explicitly test"),
        ("STORE_BACKEND", "memory", "TEST UAT requires the Postgres backend"),
    ],
)
def test_uat_context_rejects_non_test_bindings_before_channel_preflight(
    monkeypatch: pytest.MonkeyPatch, binding: str, value: str | None, message: str
) -> None:
    captured = {name: None for name in CHANNEL_ENV_KEYS}
    captured.update(
        {
            "PKM_ENVIRONMENT": "test",
            "PKM_CHANNEL": "test",
            "STORE_BACKEND": "postgres",
            "DATABASE_URL": "postgresql://localhost/app_test",
        }
    )
    captured[binding] = value
    monkeypatch.setattr(sys.modules[__name__], "_CAPTURED_TEST_ENV", captured)
    monkeypatch.setenv(RUN_ENV, "1")

    def unexpected_preflight(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("channel preflight must not run for invalid TEST bindings")

    monkeypatch.setattr(sys.modules[__name__], "_assert_test_channel_preflight", unexpected_preflight)
    with pytest.raises(AssertionError, match=message):
        uat_context.__wrapped__(monkeypatch)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "degraded"},
        {"issues": [{"code": "identity_mismatch"}]},
        {"expected_identity": {"provider": "openai", "model": "wrong", "dim": 3, "normalize": False}},
        {"stored_identity": {"provider": "openai", "model": "wrong", "dim": 3, "normalize": False}},
        {"stored_identity": None},
    ],
)
def test_read_doctor_rejects_missing_or_mismatched_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    report: dict[str, Any] = {
        "status": "ok",
        "issues": [],
        "expected_identity": dict(EXPECTED_IDENTITY),
        "stored_identity": dict(EXPECTED_IDENTITY),
    }
    report.update(changes)
    result = subprocess.CompletedProcess(
        args=["app.cli", "index", "doctor"],
        returncode=0,
        stdout=json.dumps(report),
        stderr="",
    )
    monkeypatch.setattr(
        sys.modules[__name__],
        "_run_channel_command",
        lambda *_args, **_kwargs: result,
    )

    with pytest.raises(AssertionError):
        _read_doctor(tmp_path)


def test_runbook_documents_required_test_channel_guards() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runbook_path = repo_root / "docs/runbooks/UAT_EXPANSION_CONNECT_CREATE_ACCEPT.md"
    assert runbook_path.is_file()
    runbook = runbook_path.read_text(encoding="utf-8")
    for required in (
        "#issuecomment-6107736254",
        "#3320 tracks a separate TEST recovery/security decision and does not authorize this Expansion actor",
        "channel-preflight",
        "index doctor --strict --json",
        "index convergence",
        "RUN_EXPANSION_CONNECT_CREATE_ACCEPT_TEST_ACTOR=1",
        "synthetic test actor",
        "expansion-connect-create-accept-test-channel.v1",
        "It never provisions, deploys, starts, restarts, re-indexes, repairs, or reconfigures a channel.",
        "effective reasoning route",
        "reflection-journal.md",
        "summary-request.md",
        "unscoped",
        "retrieval_k=2",
        "outcome: success",
    ):
        assert required in runbook
    assert "-k 'not checked_checkbox'" not in runbook
    assert "python -m pytest -q tests/uat/test_expansion_connect_create_accept_test_channel.py\n```" in runbook
    docs_index = (repo_root / "docs/DOCS_INDEX.md").read_text(encoding="utf-8")
    assert "docs/runbooks/UAT_EXPANSION_CONNECT_CREATE_ACCEPT.md" in docs_index


@pytest.mark.parametrize("backend", ["openai", "unexpected", "mock", "golden"])
def test_no_mock_route_rejects_non_runtime_reasoning_backends(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    monkeypatch.setenv("REASONING_PROVIDER", backend)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(AssertionError, match="supported live reasoning backend"):
        _assert_no_mock_reasoning_route()


def test_no_mock_route_rejects_reasoning_provider_mock_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    with pytest.raises(AssertionError, match="mock-agent fallback"):
        _assert_no_mock_reasoning_route()


@pytest.mark.parametrize(
    "cognition",
    [
        {"outcome": "provider_failure", "degraded": True, "degraded_reason": "provider_failure"},
        {"outcome": "missing_input", "degraded": True, "degraded_reason": "missing_input"},
        {"outcome": "empty_output", "degraded": True, "degraded_reason": "empty_provider_output"},
    ],
)
def test_successful_cognition_gate_rejects_degraded_create(cognition: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match="did not complete successfully"):
        _successful_cognition({"proposed_by": {"cognition": cognition}})


def test_successful_cognition_gate_rejects_inconsistent_degraded_flag() -> None:
    cognition = {"outcome": "success", "degraded": True, "degraded_reason": "provider_failure"}
    with pytest.raises(AssertionError, match="degraded to deterministic collation"):
        _successful_cognition({"proposed_by": {"cognition": cognition}})


def test_successful_cognition_gate_accepts_only_success_receipt() -> None:
    cognition = {"outcome": "success", "degraded": False, "degraded_reason": None, "claims": 2}
    assert _successful_cognition({"proposed_by": {"cognition": cognition}}) is cognition


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [(("work", "work"), "work"), (("", ""), "unscoped")],
)
def test_selected_sources_must_share_one_scope(scopes: tuple[str, str], expected: str) -> None:
    assert _shared_source_scope(scopes) == expected


@pytest.mark.parametrize("scopes", [("work", "personal"), ("work", "")])
def test_selected_sources_reject_mixed_scopes(scopes: tuple[str, str]) -> None:
    with pytest.raises(AssertionError, match="share one scope"):
        _shared_source_scope(scopes)
