"""On-prem ConversationChannelPort: fail-fast portability placeholder (sovereign-exit proof)."""

from __future__ import annotations

from speech_lexicon_kit import Transcript

from ...config import Settings


class OnPremConversationChannel:
    """Satisfies ConversationChannelPort but refuses: the client wires its own voice channel."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, call_ref: str, *, tenant: str) -> Transcript:
        raise NotImplementedError(
            "on-prem voice channel is a portability placeholder: bind the client's own "
            "telephony / STT stack (see docs/onprem-migration.md)"
        )
