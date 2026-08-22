"""The deterministic interdiction engine: pure, event-time driven, replayable.

The consequential decision on an in-flight payment (the score, the reason codes and the
allow / warn / hold / block verdict) is computed here by pure standard-library code from the
payment event, its features and a market rule pack. There is no clock (the engine reasons over
``event.as_of``, supplied by the caller) and no I/O. Two runs of the same event produce a
byte-identical result, and ``signal_key`` is the fingerprint that lets a caller prove it.

``HOLD`` and ``BLOCK`` are engine verdicts and nothing else can produce them: a model may narrate
a verdict, never move one. That is the whole reason the score and the thresholds live in code and
data a policy owner reviews, not in a prompt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .kernel import CONSEQUENTIAL_VERDICTS, Citation, RiskBand, Verdict
from .models import FeatureVector, PaymentEvent, ReasonCode
from .rulepack import RulePack

#: Scores are clamped into this closed range so no accumulation of uplifts can escape the band
#: and verdict cutoffs, whatever a future pack adds.
_MIN_SCORE = 0
_MAX_SCORE = 100


@dataclass(frozen=True, slots=True)
class EngineVerdict:
    """The deterministic half of an assessment: everything computable from the event alone."""

    verdict: Verdict
    score: int
    band: RiskBand
    reason_codes: tuple[ReasonCode, ...]
    signal_key: str
    citations: tuple[Citation, ...]

    @property
    def requires_human_review(self) -> bool:
        """A hold or a block is consequential and always goes to a human (rule R8)."""
        return self.verdict in CONSEQUENTIAL_VERDICTS


def _verdict_for(score: int, pack: RulePack) -> Verdict:
    """Map a clamped score to a verdict using ONLY the pack's cutoffs (no engine literal)."""
    if score >= pack.block_at:
        return Verdict.BLOCK
    if score >= pack.hold_at:
        return Verdict.HOLD
    if score >= pack.warn_at:
        return Verdict.WARN
    return Verdict.ALLOW


def _signal_key(event: PaymentEvent, score: int, verdict: Verdict, codes: tuple[str, ...]) -> str:
    """A stable content hash of what drove the decision, so replays diff exactly.

    Built from a canonically encoded tuple, sorted where order is not meaningful, so it never
    depends on set-iteration or dict-insertion order across processes. Cribs the fingerprint
    discipline of ``cdd-sow-research``'s ``perpetual_kyc`` module.
    """
    payload = json.dumps(
        {
            "event_id": event.event_id,
            "market": event.market,
            "amount_minor": event.amount_minor,
            "score": score,
            "verdict": verdict.value,
            "fired": sorted(codes),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def assess(event: PaymentEvent, features: FeatureVector, pack: RulePack) -> EngineVerdict:
    """Score one payment against its market pack and return the deterministic verdict.

    Every fired rule adds its uplift and contributes one :class:`ReasonCode` citing the pack's
    regulator instrument, so the arithmetic is fully auditable: baseline plus the sum of the
    uplifts, clamped, one reason line per rule. The market pack, not this function, owns the
    numbers, so this code is identical for every jurisdiction.
    """
    reason_codes: list[ReasonCode] = []
    running = pack.baseline_score
    for rule in pack.rules:
        feature = features.get(rule.feature_key)
        if feature is None or not rule.fires(feature.value):
            continue
        running += rule.uplift
        reason_codes.append(
            ReasonCode(
                code=rule.code,
                title=rule.title,
                uplift=rule.uplift,
                feature_key=rule.feature_key,
                citation=Citation(
                    source_id=f"{pack.instrument}:{rule.locator}",
                    title=rule.title,
                    snippet=f"{rule.feature_key} {rule.op} {rule.threshold:g} -> +{rule.uplift}",
                ),
            )
        )

    score = max(_MIN_SCORE, min(_MAX_SCORE, running))
    verdict = _verdict_for(score, pack)
    band = pack.band_for(score)
    fired = tuple(reason.code for reason in reason_codes)
    citations = tuple(reason.citation for reason in reason_codes) or (
        Citation(
            source_id=f"{pack.instrument}:baseline",
            title="No rule fired",
            snippet=f"baseline score {pack.baseline_score}",
        ),
    )
    return EngineVerdict(
        verdict=verdict,
        score=score,
        band=band,
        reason_codes=tuple(reason_codes),
        signal_key=_signal_key(event, score, verdict, fired),
        citations=citations,
    )
