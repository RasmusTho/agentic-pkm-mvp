"""One-shot exec barrier for the Linux verification containment root."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence


RELEASE_TOKEN = b"verification-linux-scope-release-v1\n"


def _read_release(fd: int) -> bool:
    payload = b""
    try:
        os.set_inheritable(fd, False)
        while len(payload) <= len(RELEASE_TOKEN):
            chunk = os.read(fd, len(RELEASE_TOKEN) + 1 - len(payload))
            if not chunk:
                break
            payload += chunk
    except OSError:
        return False
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return payload == RELEASE_TOKEN


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--release-fd", type=int, required=True)
    parsed, command = parser.parse_known_args(argv)
    if not command or command[0] != "--" or len(command) == 1:
        return 1
    if parsed.release_fd < 0 or not _read_release(parsed.release_fd):
        return 1
    try:
        os.execvpe(command[1], command[1:], os.environ)
    except OSError:
        return 1
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised through exec.
    raise SystemExit(main())
