"""Resolve only actual external libraries required by the Python executable."""

import pytest

from scripts import openhands_native_libraries as native


def test_python_binary_includes_its_linked_library_directory(tmp_path, monkeypatch):
    prefix = tmp_path / "python"
    binary = prefix / "bin/python"
    binary.parent.mkdir(parents=True)
    binary.touch()
    library = tmp_path / "gettext/lib/libintl.8.dylib"
    library.parent.mkdir(parents=True)
    library.touch()
    monkeypatch.setattr(native.sys, "platform", "darwin")
    monkeypatch.setattr(native.subprocess, "check_output", lambda *a, **kw:
                        f"{binary}:\n\t{library} (compatibility version 1.0.0, current version 1.0.0)\n")
    assert native.python_binary_roots(binary, prefix) == [str(library.parent)]


def test_python_binary_refuses_unresolved_library(tmp_path, monkeypatch):
    binary = tmp_path / "python"
    binary.touch()
    monkeypatch.setattr(native.sys, "platform", "darwin")
    monkeypatch.setattr(native.subprocess, "check_output", lambda *a, **kw:
                        f"{binary}:\n\t@rpath/libfoo.dylib (compatibility version 1.0.0, current version 1.0.0)\n")
    with pytest.raises(RuntimeError, match="safely inspect"):
        native.python_binary_roots(binary, tmp_path)
