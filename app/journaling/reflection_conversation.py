"""Agent-led evening reflection on the existing durable chat-session surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar
from uuid import uuid4

from app.chat.session_log import SessionLog, SessionLogWriter
from app.journaling.day_context import DayContextBundle, DayContextItem
from app.services.llm import call_llm
from app.vault.manager import VaultContext
from app.vault.settings_service import SettingsService


LLMFunction = Callable[[str, dict[str, object]], str]
T = TypeVar("T")
STOP_ACTIONS = frozenset({"/stop", "/done", "stop"})


@dataclass(frozen=True)
class ReflectionSettings:
    evening_nudge_enabled: bool
    evening_nudge_start_hour: int
    evening_nudge_end_hour: int
    idle_timeout_seconds: int
    max_owner_turns: int


@dataclass(frozen=True)
class EveningReflectionOffer:
    label: str = "Reflect on today?"
    action: str = "journaling.reflection.begin"
    tap_required: bool = True

    def as_payload(self) -> dict[str, object]:
        """Return the server-declared shape consumed by the Companion renderer."""
        return {
            "label": self.label,
            "action": self.action,
            "tap_required": self.tap_required,
        }


@dataclass
class ReflectionConversation:
    session: SessionLog
    day_context: DayContextBundle
    settings: ReflectionSettings
    opening_turn: str
    last_activity_at: datetime
    owner_turn_count: int = 0
    closed: bool = False
    messages: list[tuple[str, str]] = field(default_factory=list)


def load_reflection_settings(
    vault_context: VaultContext, *, settings_service: SettingsService | None = None
) -> ReflectionSettings:
    """Resolve all reflection tunables from the canonical Settings registry."""
    effective = (settings_service or SettingsService()).effective_settings(vault_context)

    def value(key: str) -> Any:
        return effective[key].value

    def integer_value(key: str) -> int:
        resolved = value(key)
        if not isinstance(resolved, int) or isinstance(resolved, bool):
            raise ValueError(f"{key} must be an integer")
        return resolved

    settings = ReflectionSettings(
        evening_nudge_enabled=bool(value("journalingEveningNudgeEnabled")),
        evening_nudge_start_hour=integer_value("journalingEveningNudgeStartHour"),
        evening_nudge_end_hour=integer_value("journalingEveningNudgeEndHour"),
        idle_timeout_seconds=integer_value("journalingReflectionIdleTimeoutSeconds"),
        max_owner_turns=integer_value("journalingReflectionMaxOwnerTurns"),
    )
    _validate_settings(settings)
    return settings


def build_evening_reflection_offer(
    *, now: datetime, settings: ReflectionSettings
) -> EveningReflectionOffer | None:
    """Return an inert Companion offer inside the configured local-hour window.

    This function has no conversation service or callback parameter on purpose:
    evaluating the nudge cannot start a session.  Only
    :func:`begin_reflection_from_offer`, called by an explicit tap, can cross
    that boundary.
    """
    _validate_settings(settings)
    if not settings.evening_nudge_enabled:
        return None
    hour = now.hour
    start = settings.evening_nudge_start_hour
    end = settings.evening_nudge_end_hour
    in_window = start <= hour < end if start < end else hour >= start or hour < end
    return EveningReflectionOffer() if in_window else None


def begin_reflection_from_offer(
    offer: EveningReflectionOffer, *, start: Callable[[], T]
) -> T:
    """Begin only after the Companion surface dispatches an explicit tap."""
    if not offer.tap_required or offer.action != "journaling.reflection.begin":
        raise ValueError("invalid evening reflection offer")
    return start()


class ReflectionConversationService:
    """Run a bounded reflection while synchronously persisting every message."""

    def __init__(
        self,
        *,
        vault_root: Path,
        llm_fn: LLMFunction | None = None,
        now_fn: Callable[[], datetime] | None = None,
        settings: ReflectionSettings | None = None,
    ) -> None:
        self._vault_root = vault_root.expanduser().resolve()
        self._writer = SessionLogWriter(vault_root=self._vault_root)
        self._llm = llm_fn or _call_reflection_llm
        self._now = now_fn or datetime.now
        context = VaultContext(
            status="selected",
            active_vault_path=str(self._vault_root),
            settings_path=str(self._vault_root / "settings"),
        )
        self._settings = settings or load_reflection_settings(context)

    def start(
        self, *, note_path: Path, day_context: DayContextBundle
    ) -> ReflectionConversation:
        """Open the existing chat artifact and persist the informed agent turn."""
        resolved_note = note_path.expanduser().resolve()
        resolved_note.relative_to(self._vault_root)
        if not resolved_note.is_file():
            raise ValueError("reflection requires an existing vault note as its chat anchor")
        now = self._now()
        label = f"evening-reflection-{day_context.for_date.isoformat()}-{uuid4().hex[:8]}"
        session = self._writer.open_session(resolved_note, label)
        opening = self._opening_turn(day_context)
        self._writer.append_message(session, "agent", opening)
        return ReflectionConversation(
            session=session,
            day_context=day_context,
            settings=self._settings,
            opening_turn=opening,
            last_activity_at=now,
            messages=[("agent", opening)],
        )

    def submit_owner_turn(
        self, conversation: ReflectionConversation, text: str
    ) -> str | None:
        """Persist one owner turn, then ask an LLM-generated bounded follow-up."""
        self._require_open(conversation)
        normalized = text.strip()
        if not normalized:
            raise ValueError("owner turn must not be empty")
        if normalized.lower() in STOP_ACTIONS:
            self.stop(conversation, reason="owner_stop")
            return None

        # Persist before cognition: an LLM/provider failure must never erase the
        # owner's already-shared reflection.
        self._writer.append_message(conversation.session, "owner", normalized)
        conversation.messages.append(("owner", normalized))
        conversation.owner_turn_count += 1
        conversation.last_activity_at = self._now()
        if conversation.owner_turn_count >= conversation.settings.max_owner_turns:
            self.stop(conversation, reason="max_owner_turns")
            return None

        followup = self._followup_turn(conversation)
        self._writer.append_message(conversation.session, "agent", followup)
        conversation.messages.append(("agent", followup))
        conversation.last_activity_at = self._now()
        return followup

    def stop(self, conversation: ReflectionConversation, *, reason: str) -> None:
        """Close immediately, including before the owner's first turn."""
        if conversation.closed:
            return
        self._writer.close_session(
            conversation.session,
            f"reflection closed ({reason}); owner_turns={conversation.owner_turn_count}",
        )
        conversation.closed = True

    def stop_if_idle(
        self, conversation: ReflectionConversation, *, now: datetime | None = None
    ) -> bool:
        """Close after the bounded idle threshold, with no minimum-turn gate."""
        if conversation.closed:
            return False
        checked_at = now or self._now()
        idle_seconds = (checked_at - conversation.last_activity_at).total_seconds()
        if idle_seconds < conversation.settings.idle_timeout_seconds:
            return False
        self.stop(conversation, reason="idle_timeout")
        return True

    def _opening_turn(self, day_context: DayContextBundle) -> str:
        anchor = _first_concrete_item(day_context)
        gaps = [name.replace("_", " ") for name in day_context.degraded_sources]
        response = self._llm(
            "journaling.reflection.opening",
            {
                "system": _SYSTEM_PROMPT,
                "day_context": day_context.model_dump(mode="json"),
                "concrete_anchor": anchor,
                "degraded_sources": gaps,
                "instruction": "Ask one short open reflective question grounded in the anchor.",
            },
        ).strip()
        if not response:
            raise ValueError("reflection opening LLM returned an empty turn")
        parts: list[str] = []
        if gaps:
            parts.append(f"I don't have today's {', '.join(gaps)}, so this view is incomplete.")
        if anchor:
            parts.append(f"I saw {anchor}.")
        else:
            parts.append("I don't have a concrete day item to ground this in yet.")
        parts.append(response)
        return " ".join(parts)

    def _followup_turn(self, conversation: ReflectionConversation) -> str:
        response = self._llm(
            "journaling.reflection.followup",
            {
                "system": _SYSTEM_PROMPT,
                "day_context": conversation.day_context.model_dump(mode="json"),
                "transcript": [
                    {"role": role, "content": content}
                    for role, content in conversation.messages
                ],
                "remaining_owner_turns": (
                    conversation.settings.max_owner_turns - conversation.owner_turn_count
                ),
                "instruction": "Ask one short open follow-up in the owner's current language.",
            },
        ).strip()
        if not response:
            raise ValueError("reflection follow-up LLM returned an empty turn")
        return response

    @staticmethod
    def _require_open(conversation: ReflectionConversation) -> None:
        if conversation.closed:
            raise ValueError("reflection conversation is already closed")


_SYSTEM_PROMPT = (
    "You are a concise ghost-writer interviewer, not a counselor. "
    "Ask reflective questions without advice or emotional diagnosis. "
    "Follow the owner's Swedish or English language in the transcript."
)


def _call_reflection_llm(kind: str, pack: dict[str, object]) -> str:
    return call_llm(
        "journaling-reflection",
        pack,
        agent="journaling-reflection",
        kind=kind,
        max_tokens=160,
    )


def _first_concrete_item(bundle: DayContextBundle) -> str | None:
    for section in bundle.sections.values():
        if section.items:
            return _describe_item(section.items[0])
    return None


def _describe_item(item: DayContextItem) -> str:
    content = item.content
    for key in ("summary", "key", "content_identity", "target_ref", "commitment_id", "object_id"):
        value = content.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return item.provenance_ref


def _validate_settings(settings: ReflectionSettings) -> None:
    if not 0 <= settings.evening_nudge_start_hour <= 23:
        raise ValueError("evening nudge start hour must be in 0..23")
    if not 0 <= settings.evening_nudge_end_hour <= 23:
        raise ValueError("evening nudge end hour must be in 0..23")
    if settings.evening_nudge_start_hour == settings.evening_nudge_end_hour:
        raise ValueError("evening nudge window must not span a full day")
    if settings.idle_timeout_seconds <= 0:
        raise ValueError("reflection idle timeout must be positive")
    if settings.max_owner_turns <= 0:
        raise ValueError("reflection max owner turns must be positive")


__all__ = [
    "EveningReflectionOffer",
    "ReflectionConversation",
    "ReflectionConversationService",
    "ReflectionSettings",
    "begin_reflection_from_offer",
    "build_evening_reflection_offer",
    "load_reflection_settings",
]
