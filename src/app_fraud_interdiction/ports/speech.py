"""The speech ports and transcript types, re-exported from the shared speech kernel.

``speech-lexicon-kit`` owns the STT / TTS / diarization protocols and the transcript value types
(pinned by tag in ``pyproject.toml``). This module re-exports them so a consumer of this repo has
one import site for the speech boundary, exactly as ``ports/__init__.py`` re-exports the commons'
``IdentityPort``. The scam lexicon that runs over a transcript is NOT here: it is vertical policy
in ``rulepacks/`` and ``domain/scam_lexicon.py``, per the kernel's kit boundary (kernel carries
the matcher, the consumer carries the phrases).

The conversation-channel port (``ports/conversation_channel.py``) is what this repo actually binds
in the container; these re-exports are the kernel primitives its adapters build transcripts from.
"""

from __future__ import annotations

from speech_lexicon_kit import (
    ChannelRole,
    DiarizationPort,
    SpeakerTurn,
    SpeechToTextPort,
    TextToSpeechPort,
    Transcript,
)

__all__ = [
    "ChannelRole",
    "DiarizationPort",
    "SpeakerTurn",
    "SpeechToTextPort",
    "TextToSpeechPort",
    "Transcript",
]
