"""The interdiction path opens ONE span, and that span carries no content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit store.
So the value of tracing the interdiction path depends entirely on the span carrying structural
attributes only: which action, whose, which market's rule pack, how long. A payer or payee
reference, the customer's memo or the drafted warning reaching a span has left the boundary that
the redact-before-audit call exists to hold, and it has left it silently.

The content case drives the payment whose memo carries a planted NRIC, so the check runs against
input that would actually leak if any attribute were content-shaped.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app_fraud_interdiction.adapters.local._fixture_data import FIXTURE_TENANT
from app_fraud_interdiction.config import Settings, build_container
from app_fraud_interdiction.domain.interdiction_service import InterdictionService
from app_fraud_interdiction.domain.models import InterdictionAssessment, PaymentEvent
from app_fraud_interdiction.rulepacks_loader import load_packs, load_scam_lexicon

from tests.fixtures import sample_cases

#: Every attribute key the interdiction span is allowed to carry. A blocked payment that started
#: explaining itself on the span (the band, the payee, a memo fragment) would widen this set,
#: which is the point of asserting on the set rather than on the individual keys.
_ASSESS_KEYS = {"action", "actor", "market"}


class _RecordingTracer:
    """Captures every span name and attribute so the test can inspect what was emitted."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _assess(event: PaymentEvent) -> tuple[_RecordingTracer, InterdictionAssessment]:
    """The REAL local adapters for every port except the tracer under inspection."""
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    tracer = _RecordingTracer()
    service = InterdictionService(
        features=container.features,
        warning_generator=container.warning_generator,
        audit=container.audit,
        tracer=tracer,  # type: ignore[arg-type]
        conversation_channel=container.conversation_channel,
        packs=load_packs(),
        lexicon=load_scam_lexicon(),
    )
    result = service.assess(event, actor=sample_cases.ACTOR, tenant=FIXTURE_TENANT)
    return tracer, result


def _emitted(tracer: _RecordingTracer) -> str:
    """Every span name, attribute KEY and attribute VALUE, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


def test_assessing_one_payment_opens_exactly_one_named_span() -> None:
    tracer, _ = _assess(sample_cases.ROUTINE_EVENT)
    assert [name for name, _ in tracer.spans] == ["interdiction.assess"]


def test_the_span_carries_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose interdiction is slow, and in which market", and nothing more."""
    tracer, _ = _assess(sample_cases.ROUTINE_EVENT)
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "assess"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["market"] == sample_cases.ROUTINE_EVENT.market


@pytest.mark.parametrize(
    "event",
    [sample_cases.ROUTINE_EVENT, sample_cases.ESCALATING_EVENT, sample_cases.PII_EVENT],
    ids=["allow", "block", "pii"],
)
def test_the_attribute_set_is_a_fixed_allowlist_whatever_the_verdict(event: PaymentEvent) -> None:
    """A blocked payment must not start attaching its reason codes to the span to explain itself."""
    tracer, _ = _assess(event)
    for _, attributes in tracer.spans:
        assert set(attributes) == _ASSESS_KEYS


def test_no_span_attribute_carries_payment_content_or_the_planted_identifier() -> None:
    """The payment used here has an NRIC planted in its memo, so a leak would show."""
    tracer, result = _assess(sample_cases.PII_EVENT)
    emitted = _emitted(tracer)

    forbidden: list[str] = [
        sample_cases.PLANTED_NRIC,
        sample_cases.PII_EVENT.memo,
        sample_cases.PII_EVENT.payer_ref,
        sample_cases.PII_EVENT.payee_ref,
        sample_cases.PII_EVENT.event_id,
        sample_cases.PII_EVENT.call_ref,
        "ops@gamma.example",
        # The customer-facing warning and the assessment summary are the other content-shaped
        # values in reach of this call.
        result.warning,
        result.summary,
    ]
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal not in emitted, f"a span attribute carried {literal!r}"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"

    # Belt and braces: no distinctive token of the free-text memo appears either, so a truncated
    # or reformatted fragment cannot slip through the whole-string checks above.
    tokens = {
        token.strip(",.;:")
        for token in sample_cases.PII_EVENT.memo.split()
        if len(token.strip(",.;:")) > 5
    }
    emitted_tokens = set(emitted.lower().split())
    assert tokens, "the fixture must carry distinctive text for this check to mean anything"
    assert not {token.lower() for token in tokens} & emitted_tokens


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    tracer, _ = _assess(sample_cases.ESCALATING_EVENT)
    values: list[Any] = [value for _, attributes in tracer.spans for value in attributes.values()]
    assert values
    assert all(isinstance(value, str) for value in values)
