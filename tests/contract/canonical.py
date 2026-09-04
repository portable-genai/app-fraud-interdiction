"""ONE canonical request per port, shared by the structural and behavioural contract suites.

Parity means the same request through every implementation, so the request needs a single home.
Retyping it per suite is how two "parity" tests end up asserting different things.

Each :class:`PortCase` answers three questions about one port:

* ``invoke``   : what a single canonical call to this port looks like;
* ``answered`` : what it means for the OFFLINE family to have actually answered (a port that
  returns ``None`` and records nothing has not answered, it has merely not raised);
* ``managed_refusal`` : what the MANAGED family must do when called with no cloud reachable.
  Never a silent success: either it refuses because it is unconfigured, or its lazy SDK import
  fails. Both are honest; returning as if the work happened is not.

Adding a port means adding a case here. ``test_port_parity.py`` fails the build if this table
and the port map ever disagree, so the touch list in ``CONTRIBUTING.md`` is enforced rather than
merely written down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_eval_kit import EvalReport
from hex_service_kit.identity import IdentityError, Principal, RequestContext
from hex_service_kit.observability import TokenUsage

from app_fraud_interdiction.adapters.local._fixture_data import FIXTURE_TENANT
from app_fraud_interdiction.domain.kernel import (
    AuditEvent,
    Citation,
    RiskBand,
    Verdict,
)
from app_fraud_interdiction.domain.models import (
    InterdictionAssessment,
    ReasonCode,
)
from app_fraud_interdiction.ports.payment_stream import StreamRequest

from tests.fixtures import sample_cases

_CITATION = Citation(
    source_id="MAS-PSN08-FICTIONAL:cl-3.1",
    title="First payment to a newly added payee",
    snippet="new_payee >= 1 -> +25",
)

#: The audit record every audit-port implementation is handed. Already redacted, as the port
#: requires: a raw identifier must never reach a WORM record.
CANONICAL_EVENT = AuditEvent(
    action="interdict",
    actor=sample_cases.ACTOR,
    verdict=Verdict.BLOCK,
    band=RiskBand.CRITICAL,
    redacted_summary="sg-block-eval [SG]: block (score 100, critical)",
    citations=(_CITATION,),
)

#: The consequential assessment every review-router implementation is handed (rule R8's payload).
CANONICAL_RESULT = InterdictionAssessment(
    event_id=sample_cases.ESCALATING_EVENT.event_id,
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
            citation=_CITATION,
        ),
    ),
    warning="This payment was blocked to protect you from a likely scam.",
    warning_source="fallback",
    requires_human_review=True,
    signal_key="deadbeefcafe0001",
    citations=(_CITATION,),
)

#: The inbound transport context every identity implementation is handed.
CANONICAL_CONTEXT = RequestContext(headers={"x-dev-persona": "auditor"})


@dataclass(frozen=True, slots=True)
class PortCase:
    """One port's canonical call plus the two verdicts the parity suites need."""

    invoke: Callable[[Any], Any]
    answered: Callable[[Any, Any], bool]
    managed_refusal: tuple[type[BaseException], ...]
    detail: str


def _audit_invoke(adapter: Any) -> Any:
    return adapter.record(CANONICAL_EVENT)


def _audit_answered(adapter: Any, _result: Any) -> bool:
    stored = adapter.log.read_all()
    return bool(stored) and stored[-1]["actor"] == sample_cases.ACTOR and adapter.verify().ok


def _identity_invoke(adapter: Any) -> Any:
    return adapter.resolve(CANONICAL_CONTEXT)


def _identity_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, Principal) and bool(result.actor)


def _review_invoke(adapter: Any) -> Any:
    return adapter.route(CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)


def _review_answered(adapter: Any, result: Any) -> bool:
    return bool(result) and len(adapter.outbox.pending()) == 1


def _stream_invoke(adapter: Any) -> Any:
    return adapter.poll(StreamRequest())


def _stream_answered(_adapter: Any, result: Any) -> bool:
    return bool(result) and all(hasattr(event, "event_id") for event in result)


def _features_invoke(adapter: Any) -> Any:
    return adapter.features_for(sample_cases.SAMPLE_EVENT)


def _features_answered(_adapter: Any, result: Any) -> bool:
    return bool(result.values) and all(feature.citation.source_id for feature in result.values)


def _channel_invoke(adapter: Any) -> Any:
    return adapter.fetch(sample_cases.CALL_REF, tenant=FIXTURE_TENANT)


def _channel_answered(_adapter: Any, result: Any) -> bool:
    return bool(result.turns)


def _warning_invoke(adapter: Any) -> Any:
    return adapter.draft(sample_cases.WARNING_REQUEST)


def _warning_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, str) and bool(result.strip())


def _tracer_invoke(adapter: Any) -> Any:
    with adapter.span("canonical.unit", action="canonical"):
        adapter.record_token_usage(TokenUsage(input_tokens=7, output_tokens=2), "canonical-model")
    return True


def _tracer_answered(adapter: Any, result: Any) -> bool:
    return bool(result)


def _evaluation_invoke(adapter: Any) -> Any:
    return adapter.evaluate("eval/datasets/canonical.jsonl")


def _evaluation_answered(adapter: Any, result: Any) -> bool:
    return isinstance(result, EvalReport) and result.dataset.endswith("canonical.jsonl")


CANONICAL_CALLS: dict[str, PortCase] = {
    "audit": PortCase(
        invoke=_audit_invoke,
        answered=_audit_answered,
        # The lazy `google.cloud` import is the first thing the managed sink does.
        managed_refusal=(ImportError,),
        detail="write one already-redacted WORM record",
    ),
    "identity": PortCase(
        invoke=_identity_invoke,
        answered=_identity_answered,
        # No IAP assertion header offline, so the managed adapter refuses before importing.
        managed_refusal=(IdentityError,),
        detail="resolve a verified principal from transport context",
    ),
    "review_router": PortCase(
        invoke=_review_invoke,
        answered=_review_answered,
        # Rule R8: with no console configured the managed router must refuse, not swallow.
        managed_refusal=(RuntimeError,),
        detail="route one consequential result to human review",
    ),
    "payment_stream": PortCase(
        invoke=_stream_invoke,
        answered=_stream_answered,
        managed_refusal=(ImportError,),
        detail="pull one batch of in-flight payment events",
    ),
    "features": PortCase(
        invoke=_features_invoke,
        answered=_features_answered,
        managed_refusal=(ImportError,),
        detail="return a cited feature vector for a payment",
    ),
    "conversation_channel": PortCase(
        invoke=_channel_invoke,
        answered=_channel_answered,
        managed_refusal=(ImportError,),
        detail="resolve a linked call to a diarized transcript",
    ),
    "warning_generator": PortCase(
        invoke=_warning_invoke,
        answered=_warning_answered,
        managed_refusal=(ImportError,),
        detail="draft a customer warning from the verdict",
    ),
    "tracer": PortCase(
        invoke=_tracer_invoke,
        answered=_tracer_answered,
        # NOTHING. Tracing is not essential to correctness, so the managed adapter must not refuse
        # offline either: with no SDK it degrades to a no-op and the traced body still runs. An
        # adapter that raised here would take a request down over a diagnostic.
        managed_refusal=(),
        detail="open one span and report the cost of a model call",
    ),
    "evaluation": PortCase(
        invoke=_evaluation_invoke,
        answered=_evaluation_answered,
        # The managed gate reaches model-quality-gate over HTTP, which is unreachable offline.
        managed_refusal=(Exception,),
        detail="score one golden dataset through the promotion authority",
    ),
}
