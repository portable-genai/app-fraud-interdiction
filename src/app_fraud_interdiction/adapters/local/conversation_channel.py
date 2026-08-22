"""Local ConversationChannelPort: scripted scam-call transcripts (no CCAI, no STT).

Returns the fixture transcript for a linked call, so the scam-lexicon scan runs end to end
offline. This is where the managed profile would call the CCAI inbound channel and the speech
kernel's STT / diarization ports; here the transcript is already diarized fixture data, which is
what keeps the gate SDK-free while still exercising the lexicon feature path.
"""

from __future__ import annotations

from speech_lexicon_kit import Transcript

from ...config import Settings
from . import _fixture_data


class LocalConversationChannel:
    """Serve scripted diarized transcripts for the SDK-free ``local`` profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, call_ref: str, *, tenant: str) -> Transcript:
        try:
            return _fixture_data.transcript_for(call_ref, tenant=tenant)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
