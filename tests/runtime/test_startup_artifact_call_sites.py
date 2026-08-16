"""Strict P1 skeletons: replacement requires a real production call-site proof."""

from pathlib import Path

import pytest


SKELETON = Path(__file__).read_text()


def test_future_runtime_call_sites_are_explicitly_deferred() -> None:
    """P1 proves deferral posture; later slices must replace these skeletons."""
    assert SKELETON.count("\n@pytest.mark.xfail(strict=True") == 6
    assert SKELETON.count("\n    raise NotImplementedError") == 6
    assert "production call-site proof" in SKELETON


@pytest.mark.xfail(strict=True, reason="STARTUP-02 production render call site is not implemented")
def test_promotion_render_is_digest_only() -> None:
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="STARTUP-02 local-source admission call site is not implemented")
def test_local_source_cannot_create_promotion_candidate() -> None:
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="STARTUP-03 ordinary-boot production call site is not implemented")
def test_ordinary_boot_has_no_mutation_calls() -> None:
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="STARTUP-03 dependency-policy call site is not implemented")
def test_ordinary_boot_dependency_policy() -> None:
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="STARTUP-04 receipt-validator production call site is not implemented")
def test_prod_receipt_validator_is_invoked_before_activation() -> None:
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="STARTUP-04 promotion-test receipt writer call site is not implemented")
def test_promotion_test_writes_one_durable_terminal_receipt() -> None:
    raise NotImplementedError
