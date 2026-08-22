"""Prove the SHIPPED pii_safety metric is not structurally falsely green (the C4 lesson).

The proof drives ``eval/run_eval.py``'s own scorer, not a lookalike written for the test. A
falsification proof scored against a local helper proves the helper works and says nothing about
the metric the gate runs, which is exactly how a metric that reads one field of a multi-field
record stayed green while the identifier sat in the record beside it.

The green and red inputs are REAL persisted audit rows from the real pipeline: the same
interdiction, once with the redaction boundary in place and once with the raw identifier put back
into the row the way an unmasked citation puts it there.
"""

from __future__ import annotations

import copy
from typing import Any

import run_eval as ev
from agent_eval_kit import assert_can_go_red

from app_fraud_interdiction.adapters.local._fixture_data import FIXTURE_TENANT
from app_fraud_interdiction.config import Settings, build_container
from app_fraud_interdiction.service_factory import build_service

from tests.fixtures import sample_cases


def _persisted_rows() -> list[dict[str, Any]]:
    """Run the REAL pipeline over an event carrying a planted id; return the WORM rows."""
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    build_service(container).assess(
        sample_cases.PII_EVENT, actor=sample_cases.ACTOR, tenant=FIXTURE_TENANT
    )
    return [dict(row) for row in container.audit.log.read_all()]


def _unredacted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The mutant: the boundary is off, so a citation snippet keeps the raw identifier.

    This is the defect in its exact shape rather than an approximation. The summary stays masked
    (the one field the old scorer read) and the identifier lives in the citation stored in the
    same WORM record.
    """
    mutated = copy.deepcopy(rows)
    for row in mutated:
        citations = row.get("citations") or []
        if citations:
            citations[0]["snippet"] = f"payer NRIC {sample_cases.PLANTED_NRIC} on the instruction"
    return mutated


def _score(rows: list[dict[str, Any]]) -> float:
    return ev.pii_safety(ev.audit_surfaces(rows), [sample_cases.PLANTED_NRIC])


def test_pii_safety_can_go_red() -> None:
    rows = _persisted_rows()
    assert rows, "the pipeline must have written an audit record to score"
    assert_can_go_red(
        _score,
        green=rows,  # the boundary held: nothing content-bearing carries the identifier
        red=_unredacted(rows),  # the boundary off: the citation keeps what the summary lost
        threshold=ev.THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )


def test_the_metric_ignores_the_actor_attribution_field() -> None:
    """The verified principal is an address BY DESIGN, so it may not be scored as a leak.

    A blanket scan over a whole audit row can never go green, and a metric that can never go
    green is a metric somebody switches off. This pins the shipped scorer to the content fields.
    """
    rows = _persisted_rows()
    assert any("@" in str(row["actor"]) for row in rows), "the fixture actor must be an address"
    assert _score(rows) == 1.0
