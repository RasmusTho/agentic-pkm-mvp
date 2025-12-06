from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class ReasoningMode(str, Enum):
    CLAIMS = "claims"
    REVIEW = "review"
    RANKING = "ranking"
    PLANNING = "planning"
    ASK_ANSWER = "ask_answer"


class ReasoningStep(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
    metadata: dict[str, Any] = {}


class ReasoningRun(BaseModel):
    id: str = str(uuid.uuid4())
    mode: ReasoningMode
    trace_id: str | None = None
    object_uuids: list[str] = []
    steps: list[ReasoningStep] = []
    result: Any | None = None
    status: Literal["ok", "failed"] = "ok"
    error: str | None = None
