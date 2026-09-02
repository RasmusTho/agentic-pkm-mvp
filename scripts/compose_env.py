"""Bounded Compose dotenv value parsing shared by runtime and inventory paths."""

from __future__ import annotations

import re


def _decode_double_quoted(value: str) -> str:
    decoded: list[str] = []
    escaped = False
    for character in value:
        if escaped:
            if character in {'"', "\\"}:
                decoded.append(character)
            else:
                decoded.extend(("\\", character))
            escaped = False
        elif character == "\\":
            escaped = True
        else:
            decoded.append(character)
    if escaped:
        decoded.append("\\")
    return "".join(decoded)


def compose_env_value(raw_value: str) -> str:
    """Parse the bounded dotenv value forms accepted by the Compose launcher."""

    value = raw_value.strip()
    if value[:1] in {"'", '"'}:
        quote = value[0]
        escaped = False
        for index in range(1, len(value)):
            character = value[index]
            if quote == '"' and escaped:
                escaped = False
                continue
            if quote == '"' and character == "\\":
                escaped = True
                continue
            if character != quote:
                continue
            suffix = value[index + 1 :].lstrip()
            if not suffix or suffix.startswith("#"):
                quoted = value[1:index]
                return _decode_double_quoted(quoted) if quote == '"' else quoted
            break
        return value
    comment = re.search(r"[ \t]+#", value)
    if comment:
        value = value[: comment.start()].rstrip()
    return value
