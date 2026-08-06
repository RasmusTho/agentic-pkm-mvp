"""Descriptor-relative filesystem primitives shared by knowledge write seams."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import stat
import sys

from app.knowledge.errors import KnowledgeCapabilityError


def atomic_exchange_at(
    first_dir_fd: int,
    first_name: str,
    second_dir_fd: int,
    second_name: str,
) -> None:
    """Atomically swap two same-filesystem paths or fail closed.

    Python does not expose the exchange variants of rename. Linux and macOS do,
    and both are used by the supported runtime/CI environments. An unsupported
    platform must reject optimistic rewritten-note writes rather than degrade to
    a non-atomic check-then-write sequence.
    """

    libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    first_raw = os.fsencode(first_name)
    second_raw = os.fsencode(second_name)
    if sys.platform == "darwin":
        rename_exchange = getattr(libc, "renameatx_np", None)
        if rename_exchange is None:
            raise KnowledgeCapabilityError("atomic path exchange is unavailable")
        rename_exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exchange.restype = ctypes.c_int
        result = rename_exchange(
            first_dir_fd,
            first_raw,
            second_dir_fd,
            second_raw,
            0x00000002,
        )  # RENAME_SWAP
    elif sys.platform.startswith("linux"):
        rename_exchange = getattr(libc, "renameat2", None)
        if rename_exchange is None:
            raise KnowledgeCapabilityError("atomic path exchange is unavailable")
        rename_exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exchange.restype = ctypes.c_int
        result = rename_exchange(
            first_dir_fd,
            first_raw,
            second_dir_fd,
            second_raw,
            0x00000002,
        )
    else:
        raise KnowledgeCapabilityError("atomic path exchange is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), first_name)


def atomic_rename_noreplace_at(
    source_dir_fd: int,
    source_name: str,
    destination_dir_fd: int,
    destination_name: str,
) -> None:
    """Atomically rename without replacing an existing destination."""

    libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    source_raw = os.fsencode(source_name)
    destination_raw = os.fsencode(destination_name)
    if sys.platform == "darwin":
        rename_noreplace = getattr(libc, "renameatx_np", None)
        if rename_noreplace is None:
            raise KnowledgeCapabilityError("atomic no-replace rename is unavailable")
        rename_noreplace.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(
            source_dir_fd,
            source_raw,
            destination_dir_fd,
            destination_raw,
            0x00000004,
        )  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename_noreplace = getattr(libc, "renameat2", None)
        if rename_noreplace is None:
            raise KnowledgeCapabilityError("atomic no-replace rename is unavailable")
        rename_noreplace.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(
            source_dir_fd,
            source_raw,
            destination_dir_fd,
            destination_raw,
            0x00000001,
        )  # RENAME_NOREPLACE
    else:
        raise KnowledgeCapabilityError("atomic no-replace rename is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), source_name)


def same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Return whether two stat records identify the same object kind and inode."""

    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )
