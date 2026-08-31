"""API request/response schemas (Pydantic) mapped to/from the pure-domain models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ..domain.kernel import utcnow
from ..domain.models import InterdictionAssessment, PaymentEvent


class InterdictRequest(BaseModel):
    """One in-flight payment to assess. Parties are opaque references, tokenised upstream."""

    event_id: str
    market: str
    payer_ref: str
    payee_ref: str
    amount_minor: int
    currency: str
    channel: str = "faster_payment"
    memo: str = ""
    call_ref: str = ""
    as_of: datetime | None = None

    def to_event(self) -> PaymentEvent:
        return PaymentEvent(
            event_id=self.event_id,
            as_of=self.as_of or utcnow(),
            market=self.market,
            payer_ref=self.payer_ref,
            payee_ref=self.payee_ref,
            amount_minor=self.amount_minor,
            currency=self.currency,
            channel=self.channel,
            memo=self.memo,
            call_ref=self.call_ref,
        )


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class ReasonCodeModel(BaseModel):
    code: str
    title: str
    uplift: int
    feature_key: str


class InterdictResponse(BaseModel):
    event_id: str
    market: str
    verdict: str
    score: int
    band: str
    warning: str
    #: "model" when a validated model draft was used, "fallback" when it was discarded for the
    #: deterministic pack template. A caller can tell whether a model touched this warning.
    warning_source: str
    requires_human_review: bool
    signal_key: str
    #: Where the escalation WENT (rule R8): the Hrz7 review id, or the local queue reference.
    #: Empty only when the verdict was not consequential (allow / warn).
    review_ref: str = ""
    reason_codes: list[ReasonCodeModel] = []
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(
        cls, result: InterdictionAssessment, *, review_ref: str = ""
    ) -> InterdictResponse:
        return cls(
            event_id=result.event_id,
            market=result.market,
            verdict=result.verdict.value,
            score=result.score,
            band=result.band.value,
            warning=result.warning,
            warning_source=result.warning_source,
            requires_human_review=result.requires_human_review,
            signal_key=result.signal_key,
            review_ref=review_ref,
            reason_codes=[
                ReasonCodeModel(
                    code=reason.code,
                    title=reason.title,
                    uplift=reason.uplift,
                    feature_key=reason.feature_key,
                )
                for reason in result.reason_codes
            ],
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Both are read off the service because the browser cannot know either.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
