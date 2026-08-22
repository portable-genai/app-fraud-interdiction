"""Vertical artifact models: this service's own request and result types.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for
no reason but the length of its name.

Money is carried in integer MINOR units (cents), never a float: a payment verdict must be
byte-identical on replay, and floating-point money is the classic way to make it not be. Feature
values are floats because they are thresholds and ratios, not amounts.

A fork building a different vertical rewrites this module and keeps ``kernel.py`` untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .kernel import Citation, RiskBand, Verdict


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    """One in-flight payment or checkout event, as it arrives on the stream.

    ``as_of`` is the payment's EVENT time, supplied by the stream, and it is the only time the
    deterministic engine ever sees: the verdict for a given event is a function of the event, not
    of when the pipeline happened to run it. All parties are opaque references (tokenised
    upstream); no raw identifier belongs on this model.
    """

    event_id: str
    as_of: datetime
    market: str
    payer_ref: str
    payee_ref: str
    amount_minor: int
    currency: str
    channel: str = "faster_payment"
    memo: str = ""
    call_ref: str = ""

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("PaymentEvent.event_id must be non-empty")
        if not self.market.strip():
            raise ValueError("PaymentEvent.market must be non-empty")
        if self.amount_minor < 0:
            raise ValueError("PaymentEvent.amount_minor must be non-negative")
        if self.as_of.tzinfo is None:
            raise ValueError("PaymentEvent.as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """One named signal about a payment, with the source it was derived from.

    Every feature carries a :class:`~.kernel.Citation` because a fired rule cites the feature it
    fired on, and a claim with no provenance is not shippable. The value is a float so a rule can
    threshold or ratio it; a boolean signal is carried as ``0.0`` / ``1.0``.
    """

    key: str
    value: float
    citation: Citation

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("FeatureValue.key must be non-empty")


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """The features known about one payment, keyed by name, in a stable order.

    Stable order matters: the engine's ``signal_key`` fingerprint is built from the features that
    fired, and a set-iteration-order dependence would make two replays of the same event disagree
    across processes. The values arrive already sorted by key.
    """

    values: tuple[FeatureValue, ...] = ()

    def __post_init__(self) -> None:
        keys = [feature.key for feature in self.values]
        if len(keys) != len(set(keys)):
            raise ValueError("FeatureVector has duplicate feature keys")
        if list(keys) != sorted(keys):
            raise ValueError("FeatureVector values must be sorted by key")

    def get(self, key: str) -> FeatureValue | None:
        for feature in self.values:
            if feature.key == key:
                return feature
        return None

    def value_or(self, key: str, default: float = 0.0) -> float:
        feature = self.get(key)
        return feature.value if feature is not None else default


@dataclass(frozen=True, slots=True)
class ScamLexiconHit:
    """A deterministic scam-phrase match found in a voice call transcript.

    Produced by the shared speech kernel's phrase matcher over an in-repo lexicon pack. A hit is
    a FEATURE that feeds the engine, never a verdict on its own: a customer saying a phrase a
    scammer coached them to say is a signal, and the stop is the engine's to order.
    """

    phrase_id: str
    turn_index: int
    citation: Citation


@dataclass(frozen=True, slots=True)
class ReasonCode:
    """One rule that fired, why, and how much it moved the score.

    The engine emits one ReasonCode per fired rule, each citing the regulator instrument the rule
    encodes. The ``uplift`` is the points it added to the baseline score; the human-readable
    :class:`~.kernel.Citation` is what a reviewer and the drafted warning quote.
    """

    code: str
    title: str
    uplift: int
    feature_key: str
    citation: Citation


@dataclass(frozen=True, slots=True)
class InterdictionAssessment:
    """The engine verdict on one payment, plus the drafted warning and the review routing.

    ``verdict``, ``score``, ``band`` and ``reason_codes`` come from pure deterministic code and
    are replayable from ``event`` alone. ``warning`` is narration: a model may draft it, but it is
    schema-validated and grounded against this assessment, and it is discarded for a deterministic
    fallback on any failure, so an interdiction never waits on generation. ``signal_key`` is the
    content fingerprint that makes two runs of the same event diff exactly.
    """

    event_id: str
    market: str
    as_of: datetime
    verdict: Verdict
    score: int
    band: RiskBand
    reason_codes: tuple[ReasonCode, ...]
    warning: str
    warning_source: str
    requires_human_review: bool
    signal_key: str
    citations: tuple[Citation, ...] = ()

    @property
    def summary(self) -> str:
        """A one-line summary the audit record and the review console quote."""
        return (
            f"{self.event_id} [{self.market}]: {self.verdict.value} "
            f"(score {self.score}, {self.band.value})"
        )
