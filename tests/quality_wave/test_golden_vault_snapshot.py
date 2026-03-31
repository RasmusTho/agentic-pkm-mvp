"""Quality Wave B — golden vault snapshot tests.

Seeds the vault with test notes, runs the watcher→panel→promotion flow,
and compares each note's post-run state against golden baselines and a
manifest of expected frontmatter changes.

Validates:
  1. Golden files and manifest are consistent with seed material
  2. Promoted notes match their golden snapshot (frontmatter + body)
  3. Non-promoted notes remain byte-for-byte identical to their seed
  4. Frontmatter invariants hold (uuid, title never mutated)
  5. Idempotency: rerun produces the same golden state
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.uat import seed_vault_test_notes, run_vault_test_flow, SEED_SOURCE
from app.promotion.consumer import reset_promotion_dedup_store
from app.store import object_store as object_store_module
from scripts.yaml_roundtrip import load_frontmatter

pytestmark = pytest.mark.not_pg

GOLDEN_DIR = Path(__file__).parent / "golden_snapshots"
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"

# Volatile frontmatter keys that may be added by the runtime and should be
# ignored when comparing against the golden baseline.
VOLATILE_KEYS = frozenset({"modified_at", "last_processed", "indexed_at"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _parse_note(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) for a markdown note."""
    text = path.read_text(encoding="utf-8")
    fm, body = load_frontmatter(text)
    return (fm if isinstance(fm, dict) else {}), body


def _strip_volatile(fm: dict) -> dict:
    """Remove keys that may vary between runs (timestamps, etc.)."""
    return {k: v for k, v in fm.items() if k not in VOLATILE_KEYS}


def _diff_frontmatter(actual: dict, expected: dict) -> list[str]:
    """Return human-readable list of frontmatter differences."""
    diffs: list[str] = []
    all_keys = set(actual) | set(expected)
    for key in sorted(all_keys):
        a = actual.get(key)
        e = expected.get(key)
        if a != e:
            diffs.append(f"  {key}: actual={a!r} expected={e!r}")
    return diffs


def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Configure environment for deterministic vault flow. Returns outbox path."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","confidence":0.95}')
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "config")
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "capture")
    monkeypatch.setenv("VAULT_DESK_DIR_REL", "workbench")

    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    return outbox_path


def _run_seeded_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict]:
    """Seed vault, run flow, return (seeded_folder, uat_summary.checks)."""
    object_store_module._MEMORY_STORE.clear()
    reset_promotion_dedup_store()
    _setup_env(monkeypatch, tmp_path)

    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)

    seed = seed_vault_test_notes(vault_root=vault, target_subdir="Test")
    summary = run_vault_test_flow(
        vault_root=vault, target_subdir="Test", assert_expectations=False,
    )
    return seed.destination, summary.checks or {}


def _seed_names() -> list[str]:
    excluded = {"golden.md", "Note_1.md", "Note_2.md"}
    return sorted(p.name for p in SEED_SOURCE.glob("*.md") if p.name not in excluded)


def _golden_names() -> list[str]:
    return sorted(p.stem.replace(".golden", "") + ".md" for p in GOLDEN_DIR.glob("*.golden.md"))


# ---------------------------------------------------------------------------
# 1. Infrastructure consistency
# ---------------------------------------------------------------------------

class TestGoldenInfrastructure:
    """Verify seed material, golden files, and manifest are consistent."""

    def test_seed_notes_exist(self) -> None:
        names = _seed_names()
        assert len(names) == 6, f"Expected 6 seed notes, found {len(names)}: {names}"

    def test_golden_files_exist(self) -> None:
        names = _golden_names()
        assert len(names) == 6, f"Expected 6 golden files, found {len(names)}: {names}"
        for name in names:
            golden = GOLDEN_DIR / name.replace(".md", ".golden.md")
            fm, body = _parse_note(golden)
            assert fm.get("uuid"), f"Golden {name} missing uuid"

    def test_manifest_covers_all_seeds(self) -> None:
        manifest = _load_manifest()
        seed_names = set(_seed_names())
        manifest_names = set(manifest.keys())
        assert manifest_names == seed_names, (
            f"Manifest/seed mismatch: "
            f"in manifest only: {manifest_names - seed_names}, "
            f"in seeds only: {seed_names - manifest_names}"
        )

    def test_golden_files_match_seed_names(self) -> None:
        golden_names = set(_golden_names())
        seed_names = set(_seed_names())
        assert golden_names == seed_names, (
            f"Golden/seed mismatch: "
            f"golden only: {golden_names - seed_names}, "
            f"seeds only: {seed_names - golden_names}"
        )


# ---------------------------------------------------------------------------
# 2. Golden vault snapshot comparison
# ---------------------------------------------------------------------------

class TestGoldenVaultSnapshot:
    """Run flow and compare each note against its golden baseline."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def test_evergreen_matches_golden(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seeded_folder, checks = _run_seeded_flow(tmp_path, monkeypatch)
        assert checks.get("evergreen_note_promoted"), "evergreen should be promoted"

        actual_fm, actual_body = _parse_note(seeded_folder / "evergreen-strategy.md")
        golden_fm, golden_body = _parse_note(GOLDEN_DIR / "evergreen-strategy.golden.md")

        actual_clean = _strip_volatile(actual_fm)
        golden_clean = _strip_volatile(golden_fm)
        diffs = _diff_frontmatter(actual_clean, golden_clean)
        assert not diffs, "evergreen-strategy.md frontmatter mismatch:\n" + "\n".join(diffs)
        assert actual_body == golden_body, "evergreen-strategy.md body changed"

    def test_manual_policy_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seeded_folder, checks = _run_seeded_flow(tmp_path, monkeypatch)
        assert checks.get("manual_policy_skipped") or checks.get("manual_note_unchanged")

        actual_fm, actual_body = _parse_note(seeded_folder / "manual-policy.md")
        seed_fm, seed_body = _parse_note(SEED_SOURCE / "manual-policy.md")

        assert _strip_volatile(actual_fm) == _strip_volatile(seed_fm), "manual-policy frontmatter should not change"
        assert actual_body == seed_body, "manual-policy body should not change"

    @pytest.mark.parametrize("note_name", _seed_names())
    def test_golden_match_all_notes(self, note_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seeded_folder, _ = _run_seeded_flow(tmp_path, monkeypatch)
        manifest = _load_manifest()
        manifest[note_name]

        actual_fm, actual_body = _parse_note(seeded_folder / note_name)
        golden_fm, golden_body = _parse_note(GOLDEN_DIR / note_name.replace(".md", ".golden.md"))

        actual_clean = _strip_volatile(actual_fm)
        golden_clean = _strip_volatile(golden_fm)
        diffs = _diff_frontmatter(actual_clean, golden_clean)
        assert not diffs, f"{note_name} frontmatter mismatch:\n" + "\n".join(diffs)
        assert actual_body == golden_body, f"{note_name} body mismatch"


# ---------------------------------------------------------------------------
# 3. Manifest contract validation
# ---------------------------------------------------------------------------

class TestManifestContract:
    """Validate manifest expectations against actual post-run state."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    @pytest.mark.parametrize("note_name", _seed_names())
    def test_expected_frontmatter_changes_applied(
        self, note_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded_folder, _ = _run_seeded_flow(tmp_path, monkeypatch)
        manifest = _load_manifest()
        spec = manifest[note_name]

        actual_fm, _ = _parse_note(seeded_folder / note_name)

        # Verify expected changes are present
        for key, expected_value in spec["expected_frontmatter_changes"].items():
            assert actual_fm.get(key) == expected_value, (
                f"{note_name}: expected {key}={expected_value!r}, got {actual_fm.get(key)!r}"
            )

    @pytest.mark.parametrize("note_name", _seed_names())
    def test_invariant_keys_unchanged(
        self, note_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded_folder, _ = _run_seeded_flow(tmp_path, monkeypatch)
        manifest = _load_manifest()
        spec = manifest[note_name]

        actual_fm, _ = _parse_note(seeded_folder / note_name)
        seed_fm, _ = _parse_note(SEED_SOURCE / note_name)

        for key in spec["must_not_change"]:
            assert actual_fm.get(key) == seed_fm.get(key), (
                f"{note_name}: invariant key {key} changed from {seed_fm.get(key)!r} to {actual_fm.get(key)!r}"
            )

    @pytest.mark.parametrize("note_name", _seed_names())
    def test_body_matches_seed(
        self, note_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded_folder, _ = _run_seeded_flow(tmp_path, monkeypatch)
        manifest = _load_manifest()
        spec = manifest[note_name]

        if not spec.get("body_must_match_seed", False):
            pytest.skip("body_must_match_seed is false")

        _, actual_body = _parse_note(seeded_folder / note_name)
        _, seed_body = _parse_note(SEED_SOURCE / note_name)
        assert actual_body == seed_body, f"{note_name}: body text diverged from seed"


# ---------------------------------------------------------------------------
# 4. Idempotency: rerun state matches golden
# ---------------------------------------------------------------------------

class TestGoldenIdempotency:
    """After the flow runs (including internal rerun), state still matches golden."""

    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

    def test_rerun_state_matches_golden(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The UAT flow already does run + rerun internally. Verify the final state matches golden."""
        seeded_folder, checks = _run_seeded_flow(tmp_path, monkeypatch)

        assert checks.get("rerun_no_changes"), "rerun should detect no changes"
        assert checks.get("rerun_no_panel_side_effects"), "rerun should have no panel side effects"

        for note_name in _seed_names():
            actual_fm, actual_body = _parse_note(seeded_folder / note_name)
            golden_fm, golden_body = _parse_note(GOLDEN_DIR / note_name.replace(".md", ".golden.md"))

            actual_clean = _strip_volatile(actual_fm)
            golden_clean = _strip_volatile(golden_fm)
            diffs = _diff_frontmatter(actual_clean, golden_clean)
            assert not diffs, (
                f"{note_name} post-rerun frontmatter diverged from golden:\n" + "\n".join(diffs)
            )
            assert actual_body == golden_body, f"{note_name} post-rerun body diverged from golden"

    def test_uat_checks_all_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """All built-in UAT checks should pass."""
        _, checks = _run_seeded_flow(tmp_path, monkeypatch)
        failed = [name for name, passed in checks.items() if not passed]
        assert not failed, f"UAT checks failed: {failed}"
