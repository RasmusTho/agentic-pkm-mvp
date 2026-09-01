from __future__ import annotations

import json
from pathlib import Path

from app.governance.design_packet_resolver import (
    ChangeFacts,
    DesignPacket,
    DesignPacketRefusal,
    resolve_design_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
HEAD = "a" * 40


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


def _write_kernel(root: Path, entries: list[dict[str, str]]) -> None:
    principle_blocks = []
    for entry in entries:
        principle_blocks.append(
            "\n".join(
                (
                    f"### {entry['title']}",
                    "",
                    "**Routing metadata:** "
                    f"ID `{entry['principle_id']}`; "
                    f"applicability `{entry['applicability']}`; "
                    f"owner `{entry['owner']}`; "
                    f"required reading `{entry['required_reading']}`; "
                    f"enforcement `{entry['enforcement']}`.",
                    "",
                    "- Synthetic test principle.",
                )
            )
        )
    path = root / "docs" / "DESIGN_PRINCIPLES.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Design Principles\n\n## System Design Principles\n\n"
        + "\n\n".join(principle_blocks)
        + "\n\n## Documentation Design Principles\n",
        encoding="utf-8",
    )


def test_equal_change_facts_produce_canonical_packet() -> None:
    first = resolve_design_packet(
        _facts(
            changed_paths=("docs/ARCHITECTURE.md", "app/retrieval/query.py"),
            external_effects=("vault-write", "audit-event"),
            risk_triggers=("public-contract-or-interface-change",),
        ),
        repository_root=REPO_ROOT,
        repository_head=HEAD,
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
        repository_head=HEAD,
    )

    assert isinstance(first, DesignPacket)
    assert isinstance(second, DesignPacket)
    assert first.canonical_json() == second.canonical_json()
    assert json.loads(first.canonical_json()) == first.to_dict()
    assert first.repository_head == HEAD
    assert first.kernel_version == "design-principle-kernel.v1"
    assert [item.principle_id for item in first.principles] == ["DP-01", "DP-04", "DP-06"]
    assert [item.owner for item in first.principles] == [
        "docs/DESIGN_PRINCIPLES.md :: 1. Boundary-First Design",
        "docs/DESIGN_PRINCIPLES.md :: 4. Explicit Mutation Authority",
        "docs/DESIGN_PRINCIPLES.md :: 6. Contracts Over Implementations",
    ]


def test_ambiguous_or_stale_authority_refuses_without_partial_packet(tmp_path: Path) -> None:
    stale = resolve_design_packet(
        _facts(expected_principle_ids=("DP-01", "DP-STALE")),
        repository_root=REPO_ROOT,
        repository_head=HEAD,
    )
    contradictory = resolve_design_packet(
        _facts(write_class="read-only", external_effects=("remote-write",)),
        repository_root=REPO_ROOT,
        repository_head=HEAD,
    )

    ambiguous_root = tmp_path / "ambiguous"
    _write_kernel(
        ambiguous_root,
        [
            {
                "title": "1. First",
                "principle_id": "DP-01",
                "applicability": "architecture-boundary-change",
                "owner": "docs/DESIGN_PRINCIPLES.md :: 1. First",
                "required_reading": "docs/DESIGN_PRINCIPLES.md :: 1. First",
                "enforcement": "manual-review",
            },
            {
                "title": "2. Second",
                "principle_id": "DP-02",
                "applicability": "architecture-boundary-change",
                "owner": "docs/DESIGN_PRINCIPLES.md :: 2. Second",
                "required_reading": "docs/DESIGN_PRINCIPLES.md :: 2. Second",
                "enforcement": "manual-review",
            },
        ],
    )
    ambiguous = resolve_design_packet(
        _facts(
            write_class="read-only",
            persistence_class="none",
            external_effects=(),
            risk_triggers=(),
        ),
        repository_root=ambiguous_root,
        repository_head=HEAD,
    )

    missing_root = tmp_path / "missing"
    _write_kernel(
        missing_root,
        [
            {
                "title": "1. First",
                "principle_id": "DP-01",
                "applicability": "architecture-boundary-change",
                "owner": "docs/DESIGN_PRINCIPLES.md :: 1. First",
                "required_reading": "docs/MISSING.md :: Missing owner",
                "enforcement": "manual-review",
            }
        ],
    )
    missing = resolve_design_packet(
        _facts(
            write_class="read-only",
            persistence_class="none",
            external_effects=(),
            risk_triggers=(),
        ),
        repository_root=missing_root,
        repository_head=HEAD,
    )

    outcomes = {
        "stale": (stale, "stale_kernel_ids"),
        "contradictory": (contradictory, "contradictory_classification"),
        "ambiguous": (ambiguous, "ambiguous_authority"),
        "missing": (missing, "missing_owner_section"),
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
        repository_head=HEAD,
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
