"""The interdiction pipeline: deterministic verdict, grounded warning, redact-before-audit.

The consequential decision (score, band, allow/warn/hold/block) is pure and replayable, a model
can never move a hold or a block, the customer warning is grounded or discarded for a
deterministic fallback, and no raw identifier reaches the WORM record.
"""

from __future__ import annotations

import pytest

from app_fraud_interdiction.adapters.local._fixture_data import FIXTURE_TENANT
from app_fraud_interdiction.adapters.local.audit import LocalAuditAdapter
from app_fraud_interdiction.config import Settings, build_container
from app_fraud_interdiction.domain.interdiction_engine import assess as engine_assess
from app_fraud_interdiction.domain.interdiction_service import InterdictionService
from app_fraud_interdiction.domain.kernel import Verdict
from app_fraud_interdiction.domain.models import InterdictionAssessment, PaymentEvent
from app_fraud_interdiction.domain.warning import MAX_WARNING_CHARS, WarningRequest
from app_fraud_interdiction.rulepacks_loader import load_packs, load_scam_lexicon
from app_fraud_interdiction.service_factory import build_service

from tests.fixtures import sample_cases


def _service() -> tuple[InterdictionService, LocalAuditAdapter]:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    audit = container.audit
    assert isinstance(audit, LocalAuditAdapter)
    return build_service(container), audit


def _assess(event: PaymentEvent) -> InterdictionAssessment:
    service, _ = _service()
    return service.assess(event, actor="analyst@bank.example", tenant=FIXTURE_TENANT)


# --------------------------------------------------------------------------- #
# The deterministic engine owns the verdict.
# --------------------------------------------------------------------------- #
def test_the_four_verdict_bands_are_deterministic() -> None:
    from app_fraud_interdiction.adapters.local import _fixture_data as fx

    by_id = {event.event_id: event for event in fx.SCRIPTED_EVENTS}
    assert _assess(by_id["sg-allow-01"]).verdict is Verdict.ALLOW
    assert _assess(by_id["sg-warn-01"]).verdict is Verdict.WARN
    assert _assess(by_id["sg-hold-01"]).verdict is Verdict.HOLD
    assert _assess(by_id["sg-block-01"]).verdict is Verdict.BLOCK


def test_the_verdict_is_byte_identical_on_replay() -> None:
    first = _assess(sample_cases.ESCALATING_EVENT)
    second = _assess(sample_cases.ESCALATING_EVENT)
    assert first.signal_key == second.signal_key
    assert first.score == second.score
    assert first.verdict == second.verdict


def test_the_score_is_the_baseline_plus_one_uplift_line_per_fired_rule() -> None:
    result = _assess(sample_cases.ESCALATING_EVENT)
    pack = load_packs()["SG"]
    assert result.score == min(100, sum(reason.uplift for reason in result.reason_codes))
    assert result.reason_codes, "a block must cite the rules that drove it"
    assert all(
        reason.citation.source_id.startswith(pack.instrument) for reason in result.reason_codes
    )


def test_hold_and_block_require_review_allow_and_warn_do_not() -> None:
    from app_fraud_interdiction.adapters.local import _fixture_data as fx

    by_id = {event.event_id: event for event in fx.SCRIPTED_EVENTS}
    assert _assess(by_id["sg-allow-01"]).requires_human_review is False
    assert _assess(by_id["sg-warn-01"]).requires_human_review is False
    assert _assess(by_id["sg-hold-01"]).requires_human_review is True
    assert _assess(by_id["sg-block-01"]).requires_human_review is True


def test_per_market_packs_produce_different_thresholds() -> None:
    """The engine has no market branch: the SG and AU packs decide, and they differ."""
    packs = load_packs()
    assert packs["SG"].block_at != packs["AU"].block_at
    assert {rule.code for rule in packs["SG"].rules} != {rule.code for rule in packs["AU"].rules}


# --------------------------------------------------------------------------- #
# The scam-call lexicon feeds the engine as a feature.
# --------------------------------------------------------------------------- #
def test_a_linked_scam_call_raises_the_score() -> None:
    """The same payment scores higher WITH the coached call than without it."""
    with_call = sample_cases.ESCALATING_EVENT
    without_call = PaymentEvent(
        event_id="sg-block-nocall",
        as_of=with_call.as_of,
        market=with_call.market,
        payer_ref=with_call.payer_ref,
        payee_ref=with_call.payee_ref,
        amount_minor=with_call.amount_minor,
        currency=with_call.currency,
    )
    assert _assess(with_call).score > _assess(without_call).score


def test_the_scam_lexicon_matches_at_least_two_distinct_cues() -> None:
    from app_fraud_interdiction.adapters.local._fixture_data import transcript_for
    from app_fraud_interdiction.domain.scam_lexicon import scan

    hits = scan(transcript_for("call-scam-sg", tenant=FIXTURE_TENANT), load_scam_lexicon())
    assert len({hit.phrase_id for hit in hits}) >= 2


# --------------------------------------------------------------------------- #
# The model may narrate, never decide, and the warning is grounded or discarded.
# --------------------------------------------------------------------------- #
def test_the_offline_generator_warning_is_used_and_grounded() -> None:
    result = _assess(sample_cases.ESCALATING_EVENT)
    assert result.warning_source == "model"
    assert result.warning and len(result.warning) <= MAX_WARNING_CHARS


def test_a_failing_generator_falls_back_to_the_deterministic_template() -> None:
    """An interdiction never waits on generation: a raising generator yields the fallback."""

    class _BrokenGenerator:
        def draft(self, request: WarningRequest) -> str:
            raise RuntimeError("model endpoint unreachable")

    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = InterdictionService(
        features=container.features,
        warning_generator=_BrokenGenerator(),
        audit=container.audit,
        tracer=container.tracer,
        conversation_channel=container.conversation_channel,
        packs=load_packs(),
        lexicon=load_scam_lexicon(),
    )
    result = service.assess(sample_cases.ESCALATING_EVENT, actor="a", tenant=FIXTURE_TENANT)
    assert result.warning_source == "fallback"
    assert result.warning, "the fallback warning must always exist"
    assert result.verdict is Verdict.BLOCK, "a broken generator must not change the verdict"


def test_a_generator_that_invents_a_figure_is_discarded() -> None:
    """A warning carrying a number the engine never produced is not grounded, so it is dropped."""

    class _LyingGenerator:
        def draft(self, request: WarningRequest) -> str:
            return "This payment was blocked; transfer 999999 now to stay safe."

    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = InterdictionService(
        features=container.features,
        warning_generator=_LyingGenerator(),
        audit=container.audit,
        tracer=container.tracer,
        conversation_channel=container.conversation_channel,
        packs=load_packs(),
        lexicon=load_scam_lexicon(),
    )
    result = service.assess(sample_cases.ESCALATING_EVENT, actor="a", tenant=FIXTURE_TENANT)
    assert result.warning_source == "fallback"
    assert "999999" not in result.warning


def test_every_number_is_identical_whatever_the_generator_does() -> None:
    """The flagship determinism invariant, asserted directly: the model narrates, never numbers.

    Three generators drive the SAME event: the real offline stand-in, one stubbed out entirely
    (it yields nothing, so the deterministic fallback ships), and an alternate but still-grounded
    narration. The customer warning and its source change; every consequential field, the verdict,
    score, band, review flag, signal_key, reason codes and citations, is byte-identical across all
    three, because each comes from the pure engine and none from the generation seam.
    """

    class _StubbedOut:
        def draft(self, request: WarningRequest) -> str:
            return ""  # generation stubbed out: the orchestrator must fall back

    class _AlternateValid:
        def draft(self, request: WarningRequest) -> str:
            return f"This payment was blocked. Reference: {request.instrument}."

    def _run(generator: object) -> InterdictionAssessment:
        container = build_container(Settings(profile="local", audit_path=":memory:"))
        service = InterdictionService(
            features=container.features,
            warning_generator=generator,  # type: ignore[arg-type]
            audit=container.audit,
            tracer=container.tracer,
            conversation_channel=container.conversation_channel,
            packs=load_packs(),
            lexicon=load_scam_lexicon(),
        )
        return service.assess(sample_cases.ESCALATING_EVENT, actor="a", tenant=FIXTURE_TENANT)

    def _numbers(a: InterdictionAssessment) -> tuple[object, ...]:
        return (
            a.verdict,
            a.score,
            a.band,
            a.requires_human_review,
            a.signal_key,
            a.reason_codes,
            a.citations,
        )

    baseline = _assess(sample_cases.ESCALATING_EVENT)  # the real offline generator
    stubbed = _run(_StubbedOut())
    alternate = _run(_AlternateValid())

    assert _numbers(baseline) == _numbers(stubbed) == _numbers(alternate)
    # And prove the generation seam genuinely varied, so the equality above is not vacuous.
    assert baseline.warning_source == "model"
    assert stubbed.warning_source == "fallback"
    assert alternate.warning_source == "model"
    assert len({baseline.warning, stubbed.warning, alternate.warning}) == 3


# --------------------------------------------------------------------------- #
# Redact before the audit write.
# --------------------------------------------------------------------------- #
def test_pii_in_the_memo_is_redacted_before_the_audit_write() -> None:
    service, audit = _service()
    service.assess(sample_cases.PII_EVENT, actor="analyst@bank.example", tenant=FIXTURE_TENANT)
    records = audit.log.read_all()
    assert records, "an audit event should have been recorded"
    summary = records[-1]["redacted_summary"]
    assert sample_cases.PLANTED_NRIC not in summary
    assert "REDACTED" in summary
    assert records[-1]["actor"] == "analyst@bank.example"
    assert audit.log.verify_chain().ok


def test_an_unknown_market_is_refused_not_guessed() -> None:
    service, _ = _service()
    event = PaymentEvent(
        event_id="xx-1",
        as_of=sample_cases.ESCALATING_EVENT.as_of,
        market="ZZ",
        payer_ref="payer-calm",
        payee_ref="np-generic",
        amount_minor=1000,
        currency="SGD",
    )
    with pytest.raises(ValueError, match="no rule pack"):
        service.assess(event, actor="a", tenant=FIXTURE_TENANT)


def test_the_engine_is_pure_of_the_orchestrator() -> None:
    """The engine result depends only on event, features and pack, with no port and no clock."""
    container = build_container(Settings(profile="local"))
    features = container.features.features_for(sample_cases.ROUTINE_EVENT)
    pack = load_packs()["SG"]
    a = engine_assess(sample_cases.ROUTINE_EVENT, features, pack)
    b = engine_assess(sample_cases.ROUTINE_EVENT, features, pack)
    assert a == b
