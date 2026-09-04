"""Rule R8: a consequential interdiction is ROUTED to human-review-console, not left in a per-repo
boolean.

This is the standing gate for the failure the rule exists to prevent. A repo can set
``requires_human_review = True``, pass every other test, and still auto-execute in practice
because nothing ever reads the flag. So the assertions here are about the ROUTING, not the flag:
a hold or block produces an outbound review, an allow or warn produces none, the payload leaves
redacted, and the on-prem placeholder refuses rather than swallowing the escalation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app_fraud_interdiction.adapters.gcp.review_router import (
    CloudReviewRouter,
)
from app_fraud_interdiction.adapters.local._fixture_data import FIXTURE_TENANT
from app_fraud_interdiction.adapters.local.review_router import (
    LocalReviewRouter,
)
from app_fraud_interdiction.adapters.onprem.review_router import (
    OnPremReviewRouter,
)
from app_fraud_interdiction.api.app import (
    app,
)
from app_fraud_interdiction.config import (
    Settings,
    build_container,
)
from app_fraud_interdiction.domain.kernel import (
    Citation,
    RiskBand,
    Verdict,
)
from app_fraud_interdiction.domain.models import (
    InterdictionAssessment,
    PaymentEvent,
    ReasonCode,
)
from app_fraud_interdiction.service_factory import build_service

from tests.fixtures import sample_cases

_BLOCK_BODY = {
    "event_id": "sg-block-req",
    "market": "SG",
    "payer_ref": "payer-coached",
    "payee_ref": "sg-mule-2d",
    "amount_minor": 600000,
    "currency": "SGD",
    "call_ref": "call-scam-sg",
}
_ALLOW_BODY = {
    "event_id": "sg-allow-req",
    "market": "SG",
    "payer_ref": "payer-calm",
    "payee_ref": "sg-established",
    "amount_minor": 20000,
    "currency": "SGD",
}


def _settings(profile: str = "local") -> Settings:
    return Settings(profile=profile, audit_path=":memory:", tenant="demo-bank")


def _assess(event: PaymentEvent) -> InterdictionAssessment:
    return build_service(build_container(_settings())).assess(
        event, actor="analyst@bank.example", tenant=FIXTURE_TENANT
    )


def test_a_consequential_result_produces_an_outbound_review() -> None:
    router = LocalReviewRouter(_settings())
    result = _assess(sample_cases.ESCALATING_EVENT)
    ref = router.route(result, maker="analyst@bank.example")
    assert ref, "routing must return a reference, so the caller can record where it went"
    pending = router.outbox.pending()
    assert len(pending) == 1
    review = pending[0].review
    assert review.maker == "analyst@bank.example"
    assert review.tenant == "demo-bank"
    assert review.severity == RiskBand.CRITICAL.value
    assert review.source_key, "a durable outbox needs an idempotency key"


def test_a_block_demands_dual_control() -> None:
    router = LocalReviewRouter(_settings())
    router.route(_assess(sample_cases.ESCALATING_EVENT), maker="analyst@bank.example")
    assert router.outbox.pending()[0].review.required_approvals == 2


def test_the_payload_is_redacted_before_it_leaves_the_process() -> None:
    """human-review-console is a shared sink; a raw identifier in any routed field must never reach
    the wire.

    The event id is the field a caller controls, so a planted identifier there is the honest
    probe: the shared converter redacts every field it puts on the wire, whichever family built
    it, so the identifier is masked before the review is enqueued.

    The citation is planted in EVERY field, including the locator and the title. The converter
    masked only the snippet, so a citation whose locator was composed out of caller text put a
    raw identifier on the shared console with everything around it masked. Today's citations are
    rule-pack locators with nothing to mask, which is why the gap survived: the boundary has to
    hold by construction rather than because of what the current producers happen to emit.
    """
    router = LocalReviewRouter(_settings())
    citation = Citation(
        source_id=f"MAS-PSN08-FICTIONAL:cl-3.1:{sample_cases.PLANTED_NRIC}",
        title=f"rule cited for {sample_cases.PLANTED_NRIC}",
        snippet=f"new_payee for {sample_cases.PLANTED_NRIC}",
    )
    planted = InterdictionAssessment(
        event_id=f"case {sample_cases.PLANTED_NRIC}",
        market="SG",
        as_of=sample_cases.ESCALATING_EVENT.as_of,
        verdict=Verdict.BLOCK,
        score=100,
        band=RiskBand.CRITICAL,
        reason_codes=(
            ReasonCode(
                code="SG-NEW-PAYEE",
                title="First payment to a newly added payee",
                uplift=25,
                feature_key="new_payee",
                citation=citation,
            ),
        ),
        warning="blocked",
        warning_source="fallback",
        requires_human_review=True,
        signal_key="abc123",
        citations=(citation,),
    )
    router.route(planted, maker="analyst@bank.example")
    wire = repr(router.outbox.pending()[0].review.to_payload())
    assert sample_cases.PLANTED_NRIC not in wire
    assert "REDACTED" in wire


def test_the_managed_router_refuses_when_no_console_is_configured() -> None:
    """An escalation with nowhere to go must fail loudly, not return as if it were reviewed."""
    router = CloudReviewRouter(Settings(profile="gcp", audit_path=":memory:", review_url=""))
    with pytest.raises(RuntimeError, match="R8"):
        router.route(_assess(sample_cases.ESCALATING_EVENT), maker="analyst@bank.example")


def test_the_onprem_placeholder_refuses_rather_than_dropping_the_escalation() -> None:
    router = OnPremReviewRouter(_settings("onprem"))
    with pytest.raises(NotImplementedError, match="R8"):
        router.route(_assess(sample_cases.ESCALATING_EVENT), maker="analyst@bank.example")


def test_the_api_routes_the_escalation_in_the_same_request() -> None:
    """The serving path, not just the adapter: an escalation must not depend on a later job."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    escalated = client.post(
        "/v1/interdict", json=_BLOCK_BODY, headers={"X-Dev-Persona": "auditor"}
    ).json()
    assert escalated["verdict"] == "block"
    assert escalated["requires_human_review"] is True
    assert escalated["review_ref"], "an escalation with no routing reference went nowhere"

    routine = client.post(
        "/v1/interdict", json=_ALLOW_BODY, headers={"X-Dev-Persona": "auditor"}
    ).json()
    assert routine["requires_human_review"] is False
    assert routine["review_ref"] == "", "a non-escalation must not manufacture a review"
