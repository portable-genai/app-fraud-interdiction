"""Canonical synthetic cases, shared by the unit and contract suites.

Every party is an opaque, obviously fictional reference and every address is an ``.example``
domain or an RFC 5737 / RFC 3849 literal. The parties match the offline feature-store profiles in
``adapters/local/_fixture_data`` so a fixture event scores the verdict its name claims: parity and
the end-to-end proofs need the SAME request through every implementation, so the request has one
home here rather than being retyped per test.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app_fraud_interdiction.domain.kernel import Verdict
from app_fraud_interdiction.domain.models import PaymentEvent
from app_fraud_interdiction.domain.warning import WarningRequest

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: A tenant partition, so the outbound-review assertions are not all on the empty string.
TENANT = "demo-bank"

_AS_OF = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)

#: A linked scam call whose customer turns carry coached cues (see the local channel fixtures).
CALL_REF = "call-scam-sg"

#: A benign payment: the deterministic verdict is ALLOW, so no review is routed. A router that
#: manufactured a review here would be lying.
ROUTINE_EVENT = PaymentEvent(
    event_id="sg-allow-eval",
    as_of=_AS_OF,
    market="SG",
    payer_ref="payer-calm",
    payee_ref="sg-established",
    amount_minor=20000,
    currency="SGD",
    memo="Monthly rent to landlord",
)

#: A payment that MUST reach a consequential verdict (BLOCK): new + young mule payee, high amount,
#: new device and coached scam-call cues. Rule R8 routing applies.
ESCALATING_EVENT = PaymentEvent(
    event_id="sg-block-eval",
    as_of=_AS_OF,
    market="SG",
    payer_ref="payer-coached",
    payee_ref="sg-mule-2d",
    amount_minor=600000,
    currency="SGD",
    memo="Urgent transfer to protect my savings",
    call_ref=CALL_REF,
)

#: A neutral event for the feature-store canonical call: any well-formed payment works.
SAMPLE_EVENT = ROUTINE_EVENT

#: A planted identifier, so a redaction assertion has an independent literal to look for rather
#: than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: A consequential event whose MEMO carries personal data, for the redact-before-audit proofs.
PII_EVENT = PaymentEvent(
    event_id="sg-block-pii",
    as_of=_AS_OF,
    market="SG",
    payer_ref="payer-coached",
    payee_ref="sg-mule-2d",
    amount_minor=600000,
    currency="SGD",
    memo=f"Urgent transfer, my NRIC {PLANTED_NRIC} and mail ops@gamma.example on file",
    call_ref=CALL_REF,
)

#: The canonical warning-generator request: a BLOCK verdict with one cited reason.
WARNING_REQUEST = WarningRequest(
    verdict=Verdict.BLOCK,
    market="SG",
    instrument="MAS-PSN08-FICTIONAL",
    reason_titles=("First payment to a newly added payee",),
    allowed_figures=("08",),
    locale="en",
)
