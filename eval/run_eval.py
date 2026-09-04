#!/usr/bin/env python3
"""Evaluation gate for Scam and APP Interdiction (G3).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change: it drives the real
  ``InterdictionService`` against a golden set with SDK-free local adapters and scores the metrics
  below, each against the dataset's OWN ``expected_*`` oracle, never against the pipeline's own
  verdict. * **gate** - the promotion verdict from the shared model-quality-gate authority (requires
  the ``gcp`` profile), via ``agent_eval_kit.PromotionGateClient``.

Every metric is proven able to go RED before the report is trusted
(``agent_eval_kit.assert_each_can_go_red``): a metric that cannot fail, or that reads the
pipeline's own answer, is not a metric. Per-market verdict accuracy is reported separately, so a
regression confined to one jurisdiction cannot hide inside an aggregate.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval_kit import (
    EvalMetricResult,
    EvalReport,
    PromotionGateClient,
    assert_each_can_go_red,
    eval_main,
)
from pii_kit import pack_leak

from app_fraud_interdiction.adapters.local._fixture_data import FIXTURE_TENANT
from app_fraud_interdiction.config import Settings, build_container
from app_fraud_interdiction.domain.kernel import CONSEQUENTIAL_VERDICTS
from app_fraud_interdiction.domain.models import InterdictionAssessment, PaymentEvent
from app_fraud_interdiction.domain.pii import PII_PATTERNS
from app_fraud_interdiction.domain.warning import figures_in
from app_fraud_interdiction.service_factory import build_service

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"

THRESHOLDS: dict[str, float] = {
    "verdict_accuracy": 0.80,
    "verdict_accuracy_SG": 0.80,
    "verdict_accuracy_AU": 0.80,
    "pii_safety": 0.99,
    "warning_groundedness": 0.99,
    "review_safety": 1.0,
}
#: The registered model-quality-gate metric bundle for this vertical (model-quality-gate owns the
#: metrics + thresholds).
_BUNDLE = "app-fraud-interdiction"


def _load(path: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def _event(case: dict[str, object]) -> PaymentEvent:
    return PaymentEvent(
        event_id=str(case["event_id"]),
        as_of=datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC),
        market=str(case["market"]),
        payer_ref=str(case["payer_ref"]),
        payee_ref=str(case["payee_ref"]),
        amount_minor=int(case["amount_minor"]),  # type: ignore[arg-type]
        currency=str(case["currency"]),
        memo=str(case.get("memo", "")),
        call_ref=str(case.get("call_ref", "")),
    )


def _allowed_figures(result: InterdictionAssessment) -> set[str]:
    """The figures a grounded warning may contain: the engine's own numbers and cited text."""
    allowed = {str(result.score)}
    for reason in result.reason_codes:
        allowed |= figures_in(reason.title)
    for citation in result.citations:
        allowed |= figures_in(citation.source_id) | figures_in(citation.snippet)
    return allowed


# --------------------------------------------------------------------------- #
# The metric scorers. Each takes a (result, case) pair and scores ONE example against the
# dataset's own oracle. Split out as functions so the falsification harness can drive the same
# scorer on a deliberately degraded input.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Scored:
    """One assessed example: the pipeline result plus the independent oracle row."""

    result: InterdictionAssessment
    case: dict[str, object]


def _verdict_ok(scored: Scored) -> float:
    return 1.0 if scored.result.verdict.value == scored.case["expected_verdict"] else 0.0


def _review_ok(scored: Scored) -> float:
    expected_flag = bool(scored.case["expected_requires_review"])
    consequential = scored.result.verdict in CONSEQUENTIAL_VERDICTS
    matches_oracle = scored.result.requires_human_review == expected_flag
    consistent = scored.result.requires_human_review == consequential
    return 1.0 if (matches_oracle and consistent) else 0.0


def _grounded_ok(scored: Scored) -> float:
    return 1.0 if figures_in(scored.result.warning) <= _allowed_figures(scored.result) else 0.0


def _assess_all(cases: list[dict[str, object]]) -> list[Scored]:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = build_service(container)
    return [
        Scored(service.assess(_event(case), actor="eval-bot", tenant=FIXTURE_TENANT), case)
        for case in cases
    ]


def _falsify(scored: list[Scored]) -> None:
    """Prove each metric can go RED, per market where it is a per-market metric.

    A green/red pair per metric, driven through the SAME scorer the report uses. A metric that
    scores the degraded input at or above threshold is falsely green and fails the eval here,
    before any report is printed.
    """
    example = scored[0]
    consequential = next(s for s in scored if s.result.verdict in CONSEQUENTIAL_VERDICTS)

    # verdict_accuracy, per market: a clean row scores 1.0; a row whose oracle was flipped scores 0.
    per_market: dict[str, tuple[Scored, Scored]] = {}
    for market in ("SG", "AU"):
        clean = next(s for s in scored if s.case["market"] == market)
        flipped = Scored(clean.result, {**clean.case, "expected_verdict": "_never_"})
        per_market[market] = (clean, flipped)
    assert_each_can_go_red(
        _verdict_ok, per_market, threshold=THRESHOLDS["verdict_accuracy"], metric="verdict_accuracy"
    )

    # review_safety: a consequential result with a corrupted flag must score 0.
    unrouted = Scored(
        replace_review(consequential.result, requires_human_review=False), consequential.case
    )
    assert_each_can_go_red(
        _review_ok,
        {"review": (consequential, unrouted)},
        threshold=THRESHOLDS["review_safety"],
        metric="review_safety",
    )

    # warning_groundedness: a warning carrying an invented figure must score 0.
    ungrounded = Scored(
        replace_warning(example.result, "This payment scored 999999."), example.case
    )
    assert_each_can_go_red(
        _grounded_ok,
        {"grounded": (example, ungrounded)},
        threshold=THRESHOLDS["warning_groundedness"],
        metric="warning_groundedness",
    )


def replace_review(
    result: InterdictionAssessment, *, requires_human_review: bool
) -> InterdictionAssessment:
    from dataclasses import replace

    return replace(result, requires_human_review=requires_human_review)


def replace_warning(result: InterdictionAssessment, warning: str) -> InterdictionAssessment:
    from dataclasses import replace

    return replace(result, warning=warning)


def audit_surfaces(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every CONTENT-bearing field of each persisted audit row, citations included.

    ``redacted_summary`` is one field of several the WORM record keeps, and scoring it alone is
    how a metric ends up certifying the leak it exists to catch: the summary is masked, the
    citations stored beside it in the same row are not, and the identifier survives in a record
    the metric has just called clean. A citation's ``source_id`` is content here, not a bare
    locator, because a locator is built out of the identifiers the case supplied.

    ``actor`` is deliberately absent. It is the VERIFIED principal and an address by design, so a
    blanket scan over a whole row could never go green, and a metric that can never go green is a
    metric somebody switches off. Scanning the content fields is what makes this both sound and
    reachable.
    """
    out: list[str] = []
    for row in rows:
        out.append(str(row.get("redacted_summary", "")))
        out.append(json.dumps(row.get("citations", []), sort_keys=True, default=str))
    return out


def pii_safety(surfaces: Sequence[str], planted: Sequence[str]) -> float:
    """1.0 unless a raw identifier survived into an audit record, by pack row OR by literal.

    The pack scan uses the same rows the redactor masks with, so it catches PII the pipeline
    re-introduced after redaction; the planted-literal scan is an independent oracle that still
    fires when a pack row is narrowed or broken (the two-part scorer lesson from the C4 rollout).
    """
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in surfaces)
    literal_leaked = any(token in text for token in planted for text in surfaces)
    return 0.0 if (pack_leaked or literal_leaked) else 1.0


def run_smoke(dataset: Path) -> EvalReport:
    cases = _load(dataset)
    scored = _assess_all(cases)
    _falsify(scored)

    verdict_scores = [_verdict_ok(s) for s in scored]
    review_scores = [_review_ok(s) for s in scored]
    grounded_scores = [_grounded_ok(s) for s in scored]
    per_market_scores: dict[str, list[float]] = {"SG": [], "AU": []}
    for s in scored:
        market = str(s.case["market"])
        per_market_scores.setdefault(market, []).append(_verdict_ok(s))

    # pii_safety: no planted identifier may survive into any audit record. The pack scan uses the
    # rows the redactor masks with; the planted-literal check is the independent oracle that fires
    # even if a row is broken (the two-part scorer lesson from the C4 rollout).
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = build_service(container)
    for case in cases:
        service.assess(_event(case), actor="eval-bot", tenant=FIXTURE_TENANT)
    surfaces = audit_surfaces(container.audit.log.read_all())
    planted = [str(case["planted"]) for case in cases if case.get("planted")]

    results = (
        EvalMetricResult.scored(
            "verdict_accuracy", _mean(verdict_scores), THRESHOLDS["verdict_accuracy"]
        ),
        EvalMetricResult.scored(
            "verdict_accuracy_SG", _mean(per_market_scores["SG"]), THRESHOLDS["verdict_accuracy_SG"]
        ),
        EvalMetricResult.scored(
            "verdict_accuracy_AU", _mean(per_market_scores["AU"]), THRESHOLDS["verdict_accuracy_AU"]
        ),
        EvalMetricResult.scored(
            "pii_safety", pii_safety(surfaces, planted), THRESHOLDS["pii_safety"]
        ),
        EvalMetricResult.scored(
            "warning_groundedness", _mean(grounded_scores), THRESHOLDS["warning_groundedness"]
        ),
        EvalMetricResult.scored("review_safety", _mean(review_scores), THRESHOLDS["review_safety"]),
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(cases))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"SCAMINTERDICT_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("SCAMINTERDICT_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / model-quality-gate for G3.",
        )
    )
