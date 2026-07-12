"""Voice-ask runtime seams.

Voice handling stays separate from Heimdal capture: an utterance is an
ephemeral question, never a governed raw record.
"""

from app.voice.transcription import transcribe_voice_wav

__all__ = ["transcribe_voice_wav"]
