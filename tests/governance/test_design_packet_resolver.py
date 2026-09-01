from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

from app.governance.design_packet_resolver import (
    ChangeFacts,
    DesignPacket,
    DesignPacketRefusal,
    resolve_design_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


REPO_HEAD = _git_head(REPO_ROOT)
_REFERENCE_PAIR = re.compile(
    r"owner `(?P<owner>[^`]+)`; required reading `(?P<required_reading>[^`]+)`;"
)


def _facts(**overrides: object) -> ChangeFacts:
    values: dict[str, object] = {
        "changed_paths": ("docs/ARCHITECTURE.md", "app/retrieval/query.py"),
        "system_classification": "boundary",
        "write_class": "durable",
        "persistence_class": "durable",
        "external_effects": ("vault-write",),
        "risk_triggers": ("public-contract-or-interface-change",),
        "expected_principle_ids": (),
    }
    values.update(overrides)
    return ChangeFacts(**values)  # type: ignore[arg-type]


def _write_kernel_repository(
    root: Path,
    *,
    transform: Callable[[str], str] | None = None,
    document_overrides: dict[str, str] | None = None,
    binary_overrides: dict[str, bytes] | None = None,
    omitted_documents: set[str] | None = None,
) -> Path:
    kernel = (REPO_ROOT / "docs" / "DESIGN_PRINCIPLES.md").read_text(encoding="utf-8")
    if transform is not None:
        kernel = transform(kernel)
    path = root / "docs" / "DESIGN_PRINCIPLES.md"
    path.parent.mkdir(parents=True)
    path.write_text(kernel, encoding="utf-8")

    headings_by_path: dict[str, set[str]] = {}
    for match in _REFERENCE_PAIR.finditer(kernel):
        for reference in (match.group("owner"), match.group("required_reading")):
            path_text, separator, heading = reference.partition(" :: ")
            if separator and path_text != "docs/DESIGN_PRINCIPLES.md":
                headings_by_path.setdefault(path_text, set()).add(heading)
    for path_text, headings in headings_by_path.items():
        if path_text in (omitted_documents or set()):
            continue
        target = root / path_text
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# Fixture document\n\n"
            + "\n\n".join(f"## {heading}\n\nFixture section." for heading in sorted(headings))
            + "\n",
            encoding="utf-8",
        )
    for path_text, content in (document_overrides or {}).items():
        target = root / path_text
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for path_text, content in (binary_overrides or {}).items():
        target = root / path_text
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return path


def _commit_kernel(
    root: Path,
    *,
    transform: Callable[[str], str] | None = None,
    document_overrides: dict[str, str] | None = None,
    binary_overrides: dict[str, bytes] | None = None,
    omitted_documents: set[str] | None = None,
) -> tuple[str, Path]:
    path = _write_kernel_repository(
        root,
        transform=transform,
        document_overrides=document_overrides,
        binary_overrides=binary_overrides,
        omitted_documents=omitted_documents,
    )
    for command in (
        ("git", "init", "-q"),
        ("git", "config", "user.name", "Design Packet Test"),
        ("git", "config", "user.email", "design-packet@example.invalid"),
        ("git", "add", "."),
        ("git", "commit", "-qm", "test kernel"),
    ):
        subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)
    return _git_head(root), path


def test_equal_change_facts_produce_canonical_packet(tmp_path: Path) -> None:
    first = resolve_design_packet(
        _facts(
            changed_paths=("docs/ARCHITECTURE.md", "app/retrieval/query.py"),
            external_effects=("vault-write", "audit-event"),
            risk_triggers=("public-contract-or-interface-change",),
        ),
        repository_root=REPO_ROOT,
        repository_head=REPO_HEAD,
    )
    second = resolve_design_packet(
        _facts(
            changed_paths=(
                "app/retrieval/query.py",
                "docs/./ARCHITECTURE.md",
                "app/retrieval/query.py",
            ),
            external_effects=("audit-event", "vault-write", "audit-event"),
            risk_triggers=(
                "public-contract-or-interface-change",
                "public-contract-or-interface-change",
            ),
        ),
        repository_root=REPO_ROOT,
        repository_head=REPO_HEAD,
    )

    assert isinstance(first, DesignPacket)
    assert isinstance(second, DesignPacket)
    assert first.canonical_json() == second.canonical_json()
    assert json.loads(first.canonical_json()) == first.to_dict()
    assert first.repository_head == REPO_HEAD
    assert first.kernel_version == "design-principle-kernel.v1"
    assert [item.principle_id for item in first.principles] == ["DP-01", "DP-04", "DP-06"]
    assert [item.owner for item in first.principles] == [
        "docs/DESIGN_PRINCIPLES.md :: 1. Boundary-First Design",
        "docs/DESIGN_PRINCIPLES.md :: 4. Explicit Mutation Authority",
        "docs/DESIGN_PRINCIPLES.md :: 6. Contracts Over Implementations",
    ]

    exact_head_root = tmp_path / "exact-head"
    exact_head, kernel_path = _commit_kernel(exact_head_root)
    committed = resolve_design_packet(
        _facts(
            write_class="read-only",
            persistence_class="none",
            external_effects=(),
            risk_triggers=(),
        ),
        repository_root=exact_head_root,
        repository_head=exact_head,
    )
    kernel_path.write_text(
        kernel_path.read_text(encoding="utf-8").replace("ID `DP-01`", "ID `DP-DIRTY`"),
        encoding="utf-8",
    )
    dirty_worktree = resolve_design_packet(
        _facts(
            write_class="read-only",
            persistence_class="none",
            external_effects=(),
            risk_triggers=(),
        ),
        repository_root=exact_head_root,
        repository_head=exact_head,
    )
    assert isinstance(committed, DesignPacket)
    assert isinstance(dirty_worktree, DesignPacket)
    assert dirty_worktree.canonical_json() == committed.canonical_json()


def test_ambiguous_or_stale_authority_refuses_without_partial_packet(tmp_path: Path) -> None:
    stale = resolve_design_packet(
        _facts(expected_principle_ids=("DP-01", "DP-STALE")),
        repository_root=REPO_ROOT,
        repository_head=REPO_HEAD,
    )
    contradictory = resolve_design_packet(
        _facts(write_class="read-only", external_effects=("remote-write",)),
        repository_root=REPO_ROOT,
        repository_head=REPO_HEAD,
    )
    invalid_head = resolve_design_packet(
        _facts(),
        repository_root=REPO_ROOT,
        repository_head="f" * 40,
    )

    ambiguous_root = tmp_path / "ambiguous"
    ambiguous_head, _ = _commit_kernel(
        ambiguous_root,
        transform=lambda text: text.replace(
            "ID `DP-02`; applicability `capability-or-orchestration-change`",
            "ID `DP-02`; applicability `architecture-boundary-change`",
            1,
        ),
    )
    ambiguous = resolve_design_packet(
        _facts(
            write_class="read-only",
            persistence_class="none",
            external_effects=(),
            risk_triggers=(),
        ),
        repository_root=ambiguous_root,
        repository_head=ambiguous_head,
    )

    missing_root = tmp_path / "missing"
    missing_head, _ = _commit_kernel(
        missing_root,
        transform=lambda text: text.replace(
            "required reading `docs/CAPABILITY_CONTRACT_MODEL.md :: Capability definition`",
            "required reading `docs/CAPABILITY_CONTRACT_MODEL.md`",
            1,
        ),
    )
    missing = resolve_design_packet(
        _facts(
            write_class="read-only",
            persistence_class="none",
            external_effects=(),
            risk_triggers=(),
        ),
        repository_root=missing_root,
        repository_head=missing_head,
    )

    duplicate_heading_root = tmp_path / "duplicate-heading"
    duplicate_heading_head, _ = _commit_kernel(
        duplicate_heading_root,
        document_overrides={
            "docs/CAPABILITY_CONTRACT_MODEL.md": (
                "# Fixture\n\n## Capability definition\n\nFirst.\n\n"
                "## Capability definition\n\nSecond.\n"
            )
        },
    )
    duplicate_heading = resolve_design_packet(
        _facts(),
        repository_root=duplicate_heading_root,
        repository_head=duplicate_heading_head,
    )

    near_match_root = tmp_path / "near-match-heading"
    near_match_head, _ = _commit_kernel(
        near_match_root,
        document_overrides={
            "docs/CAPABILITY_CONTRACT_MODEL.md": "# Fixture\n\n## Capability definition \n"
        },
    )
    near_match = resolve_design_packet(
        _facts(),
        repository_root=near_match_root,
        repository_head=near_match_head,
    )

    swapped_ids_root = tmp_path / "swapped-ids"

    def _swap_ids(text: str) -> str:
        return text.replace("ID `DP-01`", "ID `DP-SWAP`", 1).replace(
            "ID `DP-02`", "ID `DP-01`", 1
        ).replace("ID `DP-SWAP`", "ID `DP-02`", 1)

    swapped_ids_head, _ = _commit_kernel(swapped_ids_root, transform=_swap_ids)
    swapped_ids = resolve_design_packet(
        _facts(),
        repository_root=swapped_ids_root,
        repository_head=swapped_ids_head,
    )

    duplicate_boundary_root = tmp_path / "duplicate-boundary"
    duplicate_boundary_head, _ = _commit_kernel(
        duplicate_boundary_root,
        transform=lambda text: text.replace(
            "\n## Documentation Design Principles",
            "\n## System Design Principles\n\n## Documentation Design Principles",
            1,
        ),
    )
    duplicate_boundary = resolve_design_packet(
        _facts(),
        repository_root=duplicate_boundary_root,
        repository_head=duplicate_boundary_head,
    )

    orphan_metadata_root = tmp_path / "orphan-metadata"
    orphan_metadata_head, _ = _commit_kernel(
        orphan_metadata_root,
        transform=lambda text: text.replace(
            "## System Design Principles\n",
            "## System Design Principles\n\n"
            "**Routing metadata:** ID `DP-01`; applicability `architecture-boundary-change`; "
            "owner `docs/DESIGN_PRINCIPLES.md :: 1. Boundary-First Design`; required reading "
            "`docs/ARCHITECTURE.md :: Boundary Enforcement`; enforcement `manual-review`.\n",
            1,
        ),
    )
    orphan_metadata = resolve_design_packet(
        _facts(),
        repository_root=orphan_metadata_root,
        repository_head=orphan_metadata_head,
    )

    malformed_metadata_root = tmp_path / "malformed-metadata"
    malformed_metadata_head, _ = _commit_kernel(
        malformed_metadata_root,
        transform=lambda text: text.replace("required reading `", "required-reading `", 1),
    )
    malformed_metadata = resolve_design_packet(
        _facts(),
        repository_root=malformed_metadata_root,
        repository_head=malformed_metadata_head,
    )

    wrong_owner_root = tmp_path / "wrong-owner"
    wrong_owner_head, _ = _commit_kernel(
        wrong_owner_root,
        transform=lambda text: text.replace(
            "owner `docs/DESIGN_PRINCIPLES.md :: 2. Capability-Based Composition`",
            "owner `docs/DESIGN_PRINCIPLES.md :: 1. Boundary-First Design`",
            1,
        ),
    )
    wrong_owner = resolve_design_packet(
        _facts(),
        repository_root=wrong_owner_root,
        repository_head=wrong_owner_head,
    )

    selected_file_only_root = tmp_path / "selected-file-only"
    selected_file_only_head, _ = _commit_kernel(
        selected_file_only_root,
        transform=lambda text: text.replace(
            "required reading `docs/ARCHITECTURE.md :: Boundary Enforcement`",
            "required reading `docs/ARCHITECTURE.md`",
            1,
        ),
    )
    selected_file_only = resolve_design_packet(
        _facts(),
        repository_root=selected_file_only_root,
        repository_head=selected_file_only_head,
    )

    missing_blob_root = tmp_path / "missing-blob"
    missing_blob_head, _ = _commit_kernel(
        missing_blob_root,
        omitted_documents={"docs/CAPABILITY_CONTRACT_MODEL.md"},
    )
    missing_blob = resolve_design_packet(
        _facts(),
        repository_root=missing_blob_root,
        repository_head=missing_blob_head,
    )

    invalid_utf8_root = tmp_path / "invalid-utf8"
    invalid_utf8_head, _ = _commit_kernel(
        invalid_utf8_root,
        binary_overrides={"docs/CAPABILITY_CONTRACT_MODEL.md": b"\xff\xfe"},
    )
    invalid_utf8 = resolve_design_packet(
        _facts(),
        repository_root=invalid_utf8_root,
        repository_head=invalid_utf8_head,
    )

    outcomes = {
        "stale": (stale, "stale_kernel_ids"),
        "contradictory": (contradictory, "contradictory_classification"),
        "invalid_head": (invalid_head, "invalid_repository_head"),
        "ambiguous": (ambiguous, "ambiguous_authority"),
        "missing": (missing, "missing_owner_section"),
        "duplicate_heading": (duplicate_heading, "ambiguous_authority"),
        "near_match": (near_match, "missing_owner_section"),
        "swapped_ids": (swapped_ids, "stale_kernel_ids"),
        "duplicate_boundary": (duplicate_boundary, "stale_kernel_ids"),
        "orphan_metadata": (orphan_metadata, "stale_kernel_ids"),
        "malformed_metadata": (malformed_metadata, "stale_kernel_ids"),
        "wrong_owner": (wrong_owner, "stale_kernel_ids"),
        "selected_file_only": (selected_file_only, "missing_owner_section"),
        "missing_blob": (missing_blob, "missing_owner_section"),
        "invalid_utf8": (invalid_utf8, "missing_owner_section"),
    }
    for name, (outcome, code) in outcomes.items():
        assert isinstance(outcome, DesignPacketRefusal), name
        assert outcome.code == code, name
        assert set(outcome.to_dict()) == {"contract", "code", "detail", "repository_head"}
        assert "principles" not in outcome.to_dict()


def test_packet_is_read_only_projection(monkeypatch) -> None:
    def _unexpected_write(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("the design-packet resolver must not write")

    monkeypatch.setattr(Path, "write_text", _unexpected_write)
    packet = resolve_design_packet(
        _facts(),
        repository_root=REPO_ROOT,
        repository_head=REPO_HEAD,
    )

    assert isinstance(packet, DesignPacket)
    assert packet.contract == "design_packet.v1"
    assert packet.authority == "projection_only_no_mutation_acceptance_or_ranking_authority"
    assert set(packet.to_dict()) == {
        "authority",
        "contract",
        "kernel_sha256",
        "kernel_version",
        "normalized_change_facts",
        "principles",
        "repository_head",
    }
    assert not hasattr(packet, "accept")
    assert not hasattr(packet, "mutate")
