"""Managed ConversationChannelPort: fetch a diarized transcript from the CCAI inbound channel.

The managed channel would call the speech kernel's STT and diarization ports over Contact Center
AI. The SDK import is lazy, so this binds offline and refuses on the import when nothing is
reachable rather than fabricating a transcript.
"""

from __future__ import annotations

from speech_lexicon_kit import Transcript

from ...config import Settings


class CcaiConversationChannel:
    """Resolve a linked call to a diarized transcript via CCAI (managed profile)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, call_ref: str, *, tenant: str) -> Transcript:
        from google.cloud import contact_center_insights_v1  # noqa: F401  (lazy import)

        raise NotImplementedError(  # pragma: no cover - needs a live CCAI channel
            "CcaiConversationChannel needs a configured CCAI channel; see docs/runbook.md"
        )
