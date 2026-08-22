"""One coherent synthetic world the offline adapters share (obviously fictional data only).

The local payment-stream, feature-store and conversation-channel adapters all read from here, so
the scripted payments, the payee/payer risk profiles and the linked call transcripts stay
consistent: the event that names ``payer-coached`` and ``call-scam-au`` is the same one the
feature store gives a device-change signal and the channel gives a scam-cue transcript. That is
what makes the offline pipeline a real end-to-end demo rather than three unrelated fixtures.

Every identifier is invented. No real customer, payee, account or phone number appears.
"""

from __future__ import annotations

from datetime import UTC, datetime

from speech_lexicon_kit import ChannelRole, SpeakerTurn, Transcript

from ...domain.models import PaymentEvent

# --------------------------------------------------------------------------- #
# Risk profiles, keyed by opaque reference. Unknown refs fall back to a calm default.
# --------------------------------------------------------------------------- #
#: payee_ref -> (new_payee flag, payee account age in days)
_PAYEES: dict[str, tuple[float, float]] = {
    "sg-mule-2d": (1.0, 2.0),
    "sg-mule-5d": (1.0, 5.0),
    "sg-established": (0.0, 800.0),
    "au-mule-2d": (1.0, 2.0),
    "au-established": (0.0, 900.0),
    "np-generic": (1.0, 120.0),
}
_DEFAULT_PAYEE = (0.0, 365.0)

#: payer_ref -> (outbound payments in the last 24h, newly-seen-device flag)
_PAYERS: dict[str, tuple[float, float]] = {
    "payer-calm": (1.0, 0.0),
    "payer-busy": (6.0, 0.0),
    "payer-newdevice": (1.0, 1.0),
    "payer-coached": (2.0, 1.0),
}
_DEFAULT_PAYER = (1.0, 0.0)


def payee_profile(payee_ref: str) -> tuple[float, float]:
    return _PAYEES.get(payee_ref, _DEFAULT_PAYEE)


def payer_profile(payer_ref: str) -> tuple[float, float]:
    return _PAYERS.get(payer_ref, _DEFAULT_PAYER)


# --------------------------------------------------------------------------- #
# The scripted in-flight payment stream. Event times are fixed so replays are identical.
# --------------------------------------------------------------------------- #
def _at(minute: int) -> datetime:
    return datetime(2026, 8, 1, 9, minute, 0, tzinfo=UTC)


SCRIPTED_EVENTS: tuple[PaymentEvent, ...] = (
    PaymentEvent(
        event_id="sg-allow-01",
        as_of=_at(0),
        market="SG",
        payer_ref="payer-calm",
        payee_ref="sg-established",
        amount_minor=20000,
        currency="SGD",
        memo="Monthly rent to landlord",
    ),
    PaymentEvent(
        event_id="sg-warn-01",
        as_of=_at(1),
        market="SG",
        payer_ref="payer-calm",
        payee_ref="np-generic",
        amount_minor=100000,
        currency="SGD",
        memo="Deposit for online marketplace purchase",
    ),
    PaymentEvent(
        event_id="sg-hold-01",
        as_of=_at(2),
        market="SG",
        payer_ref="payer-calm",
        payee_ref="sg-mule-5d",
        amount_minor=300000,
        currency="SGD",
        memo="Investment top-up as advised",
    ),
    PaymentEvent(
        event_id="sg-block-01",
        as_of=_at(3),
        market="SG",
        payer_ref="payer-coached",
        payee_ref="sg-mule-2d",
        amount_minor=600000,
        currency="SGD",
        channel="faster_payment",
        memo="Urgent transfer to protect my savings",
        call_ref="call-scam-sg",
    ),
    PaymentEvent(
        event_id="au-allow-01",
        as_of=_at(4),
        market="AU",
        payer_ref="payer-calm",
        payee_ref="au-established",
        amount_minor=50000,
        currency="AUD",
        memo="Utility bill payment",
    ),
    PaymentEvent(
        event_id="au-warn-01",
        as_of=_at(5),
        market="AU",
        payer_ref="payer-newdevice",
        payee_ref="np-generic",
        amount_minor=100000,
        currency="AUD",
        memo="First payment to new supplier",
    ),
    PaymentEvent(
        event_id="au-hold-01",
        as_of=_at(6),
        market="AU",
        payer_ref="payer-busy",
        payee_ref="au-mule-2d",
        amount_minor=500000,
        currency="AUD",
        memo="Loan repayment to broker",
    ),
    PaymentEvent(
        event_id="au-block-01",
        as_of=_at(7),
        market="AU",
        payer_ref="payer-coached",
        payee_ref="au-mule-2d",
        amount_minor=1500000,
        currency="AUD",
        memo="Moving funds on instruction from bank security",
        call_ref="call-scam-au",
    ),
)


def events_for(market: str, max_events: int) -> tuple[PaymentEvent, ...]:
    selected = [event for event in SCRIPTED_EVENTS if not market or event.market == market]
    return tuple(selected[:max_events])


# --------------------------------------------------------------------------- #
# Linked scam-call transcripts. The CUSTOMER turns carry the coached cues the lexicon matches.
# --------------------------------------------------------------------------- #
def _scam_transcript(transcript_id: str) -> Transcript:
    return Transcript(
        transcript_id=transcript_id,
        locale="en",
        started_at=datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 8, 1, 9, 5, 0, tzinfo=UTC),
        turns=(
            SpeakerTurn(
                index=0,
                speaker_id="agent-bot",
                role=ChannelRole.AGENT,
                text="Thanks for calling. Are you making a payment right now?",
            ),
            SpeakerTurn(
                index=1,
                speaker_id="caller",
                role=ChannelRole.CUSTOMER,
                text="Yes, i am just paying a friend, nothing unusual.",
            ),
            SpeakerTurn(
                index=2,
                speaker_id="agent-bot",
                role=ChannelRole.AGENT,
                text="Can you tell me a bit more about the payment?",
            ),
            SpeakerTurn(
                index=3,
                speaker_id="caller",
                role=ChannelRole.CUSTOMER,
                text="I must do it right now, they told me the account is at risk.",
            ),
            SpeakerTurn(
                index=4,
                speaker_id="caller",
                role=ChannelRole.CUSTOMER,
                text="I am moving my money to a safe account, that is all.",
            ),
        ),
    )


_TRANSCRIPTS: dict[str, Transcript] = {
    "call-scam-sg": _scam_transcript("call-scam-sg"),
    "call-scam-au": _scam_transcript("call-scam-au"),
}

#: A benign call: one customer turn with no coached cue, so its scam-hit count is zero.
_TRANSCRIPTS["call-benign"] = Transcript(
    transcript_id="call-benign",
    locale="en",
    started_at=datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC),
    ended_at=datetime(2026, 8, 1, 9, 2, 0, tzinfo=UTC),
    turns=(
        SpeakerTurn(
            index=0,
            speaker_id="agent-bot",
            role=ChannelRole.AGENT,
            text="How can i help you today?",
        ),
        SpeakerTurn(
            index=1,
            speaker_id="caller",
            role=ChannelRole.CUSTOMER,
            text="Just checking my balance before i pay my rent, thank you.",
        ),
    ),
)


#: The tenant every fixture call belongs to. A recorded call is one bank's customer talking, so
#: the store has an owner, and the offline profile exercises the same object-level authorization
#: the managed channel must: the seeded ``other-tenant`` persona reads none of these.
FIXTURE_TENANT = "demo-bank"

#: call_ref -> owning tenant. Kept beside the transcripts rather than on ``Transcript``, which is
#: the shared speech kernel's type and is not this repo's to extend.
_CALL_TENANTS: dict[str, str] = {ref: FIXTURE_TENANT for ref in _TRANSCRIPTS}


def transcript_for(call_ref: str, *, tenant: str) -> Transcript:
    """Return ``tenant``'s transcript for ``call_ref``.

    A call owned by another tenant raises the same ``KeyError`` as an unknown reference, so the
    caller cannot use the answer to learn which references are real. An untagged call matches
    nobody: the fail-closed reading of "we do not know whose call this is" is "not yours".
    """
    if not tenant or _CALL_TENANTS.get(call_ref) != tenant:
        raise KeyError(f"no fixture transcript for call_ref {call_ref!r} in tenant {tenant!r}")
    try:
        return _TRANSCRIPTS[call_ref]
    except KeyError as exc:
        raise KeyError(
            f"no fixture transcript for call_ref {call_ref!r}; known calls: {sorted(_TRANSCRIPTS)}"
        ) from exc
