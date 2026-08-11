"""Production-path regressions for the temporal owner-doc guard."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def _guard_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "guard-repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "docs/development").mkdir(parents=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "guard@example.test"], repo)
    _run(["git", "config", "user.name", "Docs Guard Test"], repo)
    for name in ("docs_guard.py", "docs_guard_logic.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "base"], repo)
    return repo


def _guard_result(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "GITHUB_BASE_REF": "HEAD~1"}
    return subprocess.run(
        [sys.executable, "scripts/docs_guard.py", *args],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_mixed_runtime_and_governance_change_still_requires_temporal_owner_doc(
    tmp_path: Path,
) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "app").mkdir()
    (repo / "app/runtime.py").write_text("changed = True\n", encoding="utf-8")
    (repo / "scripts/git_hygiene.py").write_text("# governance\n", encoding="utf-8")
    (repo / "docs/development/WORKFLOW.md").write_text("governance writeback\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "mixed"], repo)

    result = _guard_result(repo)

    assert result.returncode == 1
    assert "temporal code/config changed" in result.stdout


def test_primary_swedish_documentation_fails_with_evidence(tmp_path: Path) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "docs/SWEDISH.md").write_text(
        """# Beslut

Det här dokumentet är skrivet på svenska och ska därför stoppas av kontrollen.
Vi behöver beskriva vad som händer, hur arbetet ska göras och varför beslutet
är viktigt. Dokumentet måste vara tydligt för den som ska läsa det senare.
""",
        encoding="utf-8",
    )
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "swedish-doc"], repo)

    result = _guard_result(repo)

    assert result.returncode == 1
    assert "Docs language guard" in result.stdout
    assert "docs/SWEDISH.md" in result.stdout
    assert '"detected_primary_language": "swedish"' in result.stdout


def test_primary_german_documentation_fails_too(tmp_path: Path) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "docs/GERMAN.md").write_text(
        """# Entscheidung

Das ist ein Dokument und die Regeln sind nicht auf Englisch. Der Text muss
mit dem System geprüft werden, weil die Dokumentation für alle verständlich
sein soll. Wenn das Dokument nicht passt, wird der Test fehlschlagen.
""",
        encoding="utf-8",
    )
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "german-doc"], repo)

    result = _guard_result(repo, "--language-only")

    assert result.returncode == 1
    assert '"detected_primary_language": "german"' in result.stdout


def test_non_latin_primary_prose_in_root_documentation_fails(tmp_path: Path) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "CONTRIBUTING.md").write_text(
        """# Правила

Этот документ описывает правила проекта и порядок работы. Каждый участник
должен соблюдать решения владельца, проверять изменения и сохранять историю.
Документация должна быть понятной, точной и доступной для проверки.
""",
        encoding="utf-8",
    )
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "non-latin-root-doc"], repo)

    result = _guard_result(repo, "--language-only")

    assert result.returncode == 1
    assert "CONTRIBUTING.md" in result.stdout
    assert '"detected_primary_language": "non_latin"' in result.stdout


def test_bounded_swedish_examples_in_english_docs_are_allowed(tmp_path: Path) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "docs/EXAMPLE.md").write_text(
        """# Localized example

This document explains an English contract for a localized user interface.
The primary prose remains English, including the purpose, constraints,
expected behavior, verification method, and owner-facing consequences.

```text
Spara den här anteckningen och öppna den senare.
```

The fenced string is test data and does not change the document language.
""",
        encoding="utf-8",
    )
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "localized-example"], repo)

    result = _guard_result(repo, "--language-only")

    assert result.returncode == 0
    assert "Docs language guard: OK" in result.stdout


def test_language_guard_rejects_adversarial_primary_non_english_docs(
    tmp_path: Path,
) -> None:
    repo = _guard_repo(tmp_path)
    documents = {
        "SHORT_SWEDISH.md": "# Beslut\n\nDet här beskriver hur arbetet ska göras.\n",
        "POLISH.md": """# Zasady

Ten dokument opisuje zasady projektu oraz sposób pracy zespołu. Każda zmiana
powinna zostać sprawdzona przed połączeniem, ponieważ jakość i bezpieczeństwo
systemu są ważne dla wszystkich użytkowników. Dokumentacja musi być jasna,
dokładna i dostępna.
""",
        "PORTUGUESE.md": """# Regras

Este documento descreve as regras e como a equipe deve trabalhar. As mudanças
são verificadas antes da entrega.
""",
        "TURKISH.md": """# Kurallar

Bu belge projenin kurallarını ve ekibin çalışma biçimini açıklar. Her değişiklik
birleştirilmeden önce doğrulanmalıdır çünkü sistemin kalitesi ve güvenliği tüm
kullanıcılar için önemlidir. Belgeler açık ve doğru olmalıdır.
""",
        "VIETNAMESE.md": """# Quy tắc

Tài liệu này mô tả các quy tắc của dự án và cách nhóm làm việc. Mọi thay đổi
phải được kiểm tra trước khi hợp nhất vì chất lượng và sự an toàn của hệ thống
rất quan trọng đối với tất cả người dùng.
""",
        "SHORT_CHINESE.md": "# 规则\n\n本文说明项目规则和工作方式。\n",
        "ALIAS_TABLE.md": """# Innehåll

| English | en |
| --- | --- |
| Det här dokumentet beskriver vad som ska göras | Vi behöver förstå hur arbetet ska genomföras |
| Den här texten måste vara tydlig | Därför ska varje beslut vara enkelt att följa |
""",
    }
    for name, content in documents.items():
        (repo / "docs" / name).write_text(content, encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "adversarial-non-english-docs"], repo)

    result = _guard_result(repo, "--language-only")

    assert result.returncode == 1
    for name in documents:
        assert f'"path": "docs/{name}"' in result.stdout


def test_language_guard_allows_adversarial_english_and_localization_docs(
    tmp_path: Path,
) -> None:
    repo = _guard_repo(tmp_path)
    documents = {
        "LOCALIZATION.md": """# Labels

This table defines bounded localization strings for the interface.

| Key | English | Swedish |
| --- | --- | --- |
| save | Save the note | Spara den här anteckningen |
| open | Open the note | Öppna den här anteckningen |
| clear | This must be clear | Det här måste vara tydligt |
| next | What happens next | Vad händer efter detta |
| where | Where is it | Var är den |

The table is localization data, while the governing contract remains English.
""",
        "TECHNICAL.md": """# API matrix

| Method | Path | Status | Notes |
| --- | --- | --- | --- |
| GET | /v1/items | 200 | idempotent |
| POST | /v1/items | 202 | queued |
| DELETE | /v1/items/{id} | 204 | terminal |

Complexity: O(n). Schema: Item{id, version, checksum}. Exit code: 0.
""",
        "MATH_TABLE.md": """# Symbol table

| α | β | γ | δ |
| --- | --- | --- | --- |
| ε | ζ | η | θ |
| ι | κ | λ | μ |
""",
        "REPEATED_AMBIGUOUS.md": """# Concise English

Her view, her note, her decision.
""",
        "EXAMPLES.md": """# Examples

This document defines the contract and its verification evidence.

```text
Det här dokumentet är på svenska och ska inte påverka kontrollen.
```

Use `Spara den här anteckningen` for the Swedish locale. The primary prose
remains English and the example is explicitly bounded.
""",
    }
    for name, content in documents.items():
        (repo / "docs" / name).write_text(content, encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "adversarial-allowed-docs"], repo)

    result = _guard_result(repo, "--language-only")

    assert result.returncode == 0, result.stdout
    assert "Docs language guard: OK" in result.stdout


def test_product_vault_markdown_is_not_repository_documentation(tmp_path: Path) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "vault").mkdir()
    (repo / "vault/anteckning.md").write_text(
        "Det här är en svensk anteckning i produktens flerspråkiga valv. " * 8,
        encoding="utf-8",
    )
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "vault-fixture"], repo)

    result = _guard_result(repo, "--language-only")

    assert result.returncode == 0
    assert "Docs language guard: OK" in result.stdout


@pytest.mark.parametrize(
    ("script_path", "doc_path"),
    [
        pytest.param(
            "scripts/git_hygiene.py",
            "docs/development/GIT_HYGIENE.md",
            id="git-hygiene-paired-doc",
        ),
        pytest.param(
            "scripts/select_pr_tests.py",
            "docs/development/TEST_STRATEGY_HOT_PATH.md",
            id="select_pr_tests-paired-doc",
        ),
    ],
)
def test_governance_enforcement_with_development_writeback_passes(
    tmp_path: Path, script_path: str, doc_path: str
) -> None:
    repo = _guard_repo(tmp_path)
    (repo / script_path).write_text("# governance\n", encoding="utf-8")
    (repo / doc_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / doc_path).write_text("governance writeback\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "governance"], repo)

    result = _guard_result(repo)

    assert result.returncode == 0
    assert "Docs guard: OK" in result.stdout


def _origin_backed_repo(tmp_path: Path) -> Path:
    """A work tree whose base branch exists only as `origin/main`.

    Mirrors the pull_request shape on GitHub Actions: GITHUB_BASE_REF is the
    bare branch name, and actions/checkout leaves no local branch by that name.
    """

    upstream = _guard_repo(tmp_path)
    _run(["git", "branch", "-M", "main"], upstream)

    work = tmp_path / "work"
    _run(["git", "clone", str(upstream), str(work)], tmp_path)
    _run(["git", "config", "user.email", "guard@example.test"], work)
    _run(["git", "config", "user.name", "Docs Guard Test"], work)
    _run(["git", "checkout", "-b", "feature"], work)
    # Leave only the remote-tracking ref for the base branch.
    _run(["git", "branch", "-D", "main"], work)
    return work


def _guard_result_with_base(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "GITHUB_BASE_REF": base}
    return subprocess.run(
        [sys.executable, "scripts/docs_guard.py"],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_bare_branch_base_ref_resolves_to_the_remote_tracking_ref(tmp_path: Path) -> None:
    # On pull_request events GITHUB_BASE_REF is "main", not "origin/main". With
    # no local `main`, the three-dot diff had no merge base to resolve, so the
    # guard could not run on the PR path at all.
    repo = _origin_backed_repo(tmp_path)
    (repo / "app").mkdir()
    (repo / "app/runtime.py").write_text("changed = True\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "app-only"], repo)

    result = _guard_result_with_base(repo, "main")

    # The guard saw the real diff (an app/** change with no docs writeback)
    # rather than dying on an unresolvable ref or diffing HEAD against itself.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "app/** changed but no docs" in result.stdout


def test_empty_base_ref_falls_back_to_origin_main_instead_of_an_empty_diff(
    tmp_path: Path,
) -> None:
    # GitHub Actions defines GITHUB_BASE_REF as "" on non-pull_request events.
    # Reading it with a `.get` default produced "", and `git diff ...HEAD`
    # treats an empty left side as HEAD -- so the guard diffed HEAD against
    # itself and reported OK on any changeset.
    repo = _origin_backed_repo(tmp_path)
    (repo / "app").mkdir()
    (repo / "app/runtime.py").write_text("changed = True\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "app-only"], repo)

    result = _guard_result_with_base(repo, "")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "app/** changed but no docs" in result.stdout


def test_select_pr_tests_requires_its_specific_paired_doc(tmp_path: Path) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "scripts/select_pr_tests.py").write_text("# governance\n", encoding="utf-8")
    (repo / "docs/development/UNRELATED.md").write_text("unrelated\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "governance"], repo)

    result = _guard_result(repo)

    assert result.returncode == 1
    assert "temporal code/config changed" in result.stdout


def _assert_governance_script_rejects_unrelated_doc(tmp_path: Path, script: str) -> None:
    repo = _guard_repo(tmp_path)
    script_path = repo / "scripts" / script
    if script in {"docs_guard.py", "docs_guard_logic.py"}:
        script_path.write_text(
            script_path.read_text(encoding="utf-8") + "\n# governance\n",
            encoding="utf-8",
        )
    else:
        script_path.write_text("# governance\n", encoding="utf-8")
    (repo / "docs/development/UNRELATED.md").write_text("unrelated\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "governance"], repo)

    result = _guard_result(repo)

    assert result.returncode == 1
    assert "temporal code/config changed" in result.stdout


def test_docs_guard_requires_its_specific_paired_doc(tmp_path: Path) -> None:
    _assert_governance_script_rejects_unrelated_doc(tmp_path, "docs_guard.py")


def test_docs_guard_logic_requires_its_specific_paired_doc(tmp_path: Path) -> None:
    _assert_governance_script_rejects_unrelated_doc(tmp_path, "docs_guard_logic.py")


def test_git_hygiene_requires_its_specific_paired_doc(tmp_path: Path) -> None:
    _assert_governance_script_rejects_unrelated_doc(tmp_path, "git_hygiene.py")
