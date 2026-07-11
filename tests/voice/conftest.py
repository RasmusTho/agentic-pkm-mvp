from __future__ import annotations

import io
from types import SimpleNamespace

from fastapi import UploadFile
import pytest
from starlette.requests import Request


WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def voice_request() -> Request:
    return Request({"type": "http", "method": "POST", "headers": []})


def voice_upload(payload: bytes = WAV) -> UploadFile:
    return UploadFile(filename="question.wav", file=io.BytesIO(payload), headers={"content-type": "audio/wav"})


def ask_state(answer: str = "Grounded answer") -> SimpleNamespace:
    return SimpleNamespace(answer=answer, hits=[])
