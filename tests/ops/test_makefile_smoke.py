from __future__ import annotations

from pathlib import Path


def _makefile_target_block(makefile: str, target: str, next_target: str) -> str:
    return makefile.split(f"{target}:", maxsplit=1)[1].split(
        f"\n{next_target}:", maxsplit=1
    )[0]


def test_make_test_loads_pytest_asyncio_when_available() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    test_block = _makefile_target_block(makefile, "test", "eval")

    assert '$(PYTHON) -c "import pytest_asyncio.plugin"' in test_block
    assert "-p pytest_asyncio.plugin" in test_block
    assert "--import-mode=importlib" in test_block


def test_make_smoke_loads_xdist_only_when_available() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    smoke_block = _makefile_target_block(makefile, "smoke", "test-vault-init")

    assert '$(PYTHON) -c "import xdist.plugin"' in smoke_block
    assert "PYTEST_PLUGIN_ARGS" in smoke_block
    assert "$(PYTHON) -m pytest $$PYTEST_PLUGIN_ARGS" in smoke_block
    assert "$(PYTHON) -m pytest -p xdist.plugin" not in smoke_block


def test_make_smoke_loads_pytest_asyncio_when_available() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    smoke_block = _makefile_target_block(makefile, "smoke", "test-vault-init")

    assert '$(PYTHON) -c "import pytest_asyncio.plugin"' in smoke_block
    assert "-p pytest_asyncio.plugin" in smoke_block
    assert "PYTEST_E2E_PLUGIN_ARGS=\"$$PYTEST_E2E_PLUGIN_ARGS -p pytest_asyncio.plugin\"" in smoke_block


def test_make_smoke_preserves_importlib_mode_without_pytest_ini() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    smoke_block = _makefile_target_block(makefile, "smoke", "test-vault-init")

    assert "-c /dev/null" in smoke_block
    assert "--import-mode=importlib" in smoke_block
