"""ConversationChannelPort: the inbound voice channel for a linked scam call.

A payment can be linked to a live or recorded call (a victim on the phone to a scammer while they
authorise the transfer). The managed adapter sits in front of a CCAI inbound channel and returns
a diarized :class:`~speech_lexicon_kit.Transcript`; the offline adapter returns a scripted fixture
transcript so the gate stays SDK-free. The scam LEXICON that runs over the transcript is vertical
policy and lives in this repo (see ``domain/scam_lexicon.py``), not behind this port.

The transcript type and the STT / diarization ports are re-exported from the shared speech kernel
(``ports/speech.py``), so this port names only the channel itself.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from speech_lexicon_kit import Transcript


@runtime_checkable
class ConversationChannelPort(Protocol):
    def fetch(self, call_ref: str, *, tenant: str) -> Transcript:
        """Return ``tenant``'s diarized transcript for ``call_ref``, or raise if it cannot be got.

        ``tenant`` is the VERIFIED principal's and is required, not defaulted. This port took a
        client-supplied ``call_ref`` and no principal, so any authenticated caller could point
        their own payment at any stored call: the recording is somebody else's customer talking
        to a scammer, and the scam-cue count it yields comes back on the response as a score and
        a reason code, which makes it a content oracle over another bank's recording.

        A call owned by another tenant is refused the same way an unresolvable one is, so the
        answer says nothing about which references exist.
        """
        ...
