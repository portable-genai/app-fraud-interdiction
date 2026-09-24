"""Review routing has a switch, default on, and every caller says what happened to a hand-off.

The fleet's runtime-control contract (2026-09-24). Review routing is the one cheap runtime
control this service has: ``SCAMINTERDICT_REVIEW_ROUTING`` is read in three states; off binds a
disabled router and says so at startup; on under the managed profile refuses to boot without a
console; and the API, the agent tool and both CLI commands report ``review_routing`` rather than
failing an already-computed assessment when the console is unreachable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app_fraud_interdiction.adapters.controls import (
    DisabledReviewRouter,
    RecordingReviewRouter,
    ReviewRouting,
)
from app_fraud_interdiction.agent import tools
from app_fraud_interdiction.api import app as api_module
from app_fraud_interdiction.api.app import app
from app_fraud_interdiction.cli import main as cli
from app_fraud_interdiction.config import (
    REVIEW_ROUTING_ENV,
    Container,
    ControlSwitches,
    ProfileChoice,
    Settings,
    build_container,
    warn_switched_off,
)
from app_fraud_interdiction.envread import ConfiguredEmptyError

_LOOPBACK = ("127.0.0.1", 50000)
_PATH = "/v1/interdict"
_ESCALATING: dict[str, Any] = {
    "event_id": "sg-block-rcs",
    "market": "SG",
    "payer_ref": "payer-coached",
    "payee_ref": "sg-mule-2d",
    "amount_minor": 600000,
    "currency": "SGD",
    "call_ref": "call-scam-sg",
}
_ROUTINE: dict[str, Any] = {
    "event_id": "sg-allow-rcs",
    "market": "SG",
    "payer_ref": "payer-calm",
    "payee_ref": "sg-established",
    "amount_minor": 20000,
    "currency": "SGD",
}
_HEADERS = {"X-Dev-Persona": "auditor"}
_LOCAL_ROUTER = "app_fraud_interdiction.adapters.local.review_router.LocalReviewRouter.route"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(REVIEW_ROUTING_ENV, raising=False)
    monkeypatch.delenv("HUMAN_REVIEW_URL", raising=False)
    # The API caches its container for the process; each test here states its own posture.
    api_module._container.cache_clear()
    yield
    api_module._container.cache_clear()


def _managed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app_fraud_interdiction.config.resolve_profile",
        lambda environ=None: ProfileChoice("gcp", True),
    )


def _result(*, requires_human_review: bool) -> Any:
    """A stand-in result: the recorder reads only ``requires_human_review``."""
    return cast(Any, SimpleNamespace(requires_human_review=requires_human_review))


# --------------------------------------------------------------------------- #
# Three states
# --------------------------------------------------------------------------- #
def test_routing_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(review_routing=True)


def test_routing_switched_off_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.switched_off() == (REVIEW_ROUTING_ENV,)


def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "")
    with pytest.raises(ConfiguredEmptyError, match=REVIEW_ROUTING_ENV):
        Settings.load()


def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "sometimes")
    with pytest.raises(ValueError, match=REVIEW_ROUTING_ENV):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled router, and says so once
# --------------------------------------------------------------------------- #
def test_off_binds_the_disabled_router() -> None:
    settings = Settings(profile="local", controls=ControlSwitches(review_routing=False))
    assert isinstance(Container(settings).review_router, DisabledReviewRouter)


def test_on_binds_the_profile_router() -> None:
    settings = Settings(profile="local")
    assert not isinstance(Container(settings).review_router, DisabledReviewRouter)


def test_the_off_posture_is_logged_once_however_many_containers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    warn_switched_off.cache_clear()
    settings = Settings(profile="local", controls=ControlSwitches(review_routing=False))
    with caplog.at_level(logging.WARNING, logger="app_fraud_interdiction.config"):
        for _ in range(3):
            build_container(settings)
    assert caplog.text.count(REVIEW_ROUTING_ENV) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under the managed profile
# --------------------------------------------------------------------------- #
def test_routing_on_under_gcp_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _managed(monkeypatch)
    with pytest.raises(ConfiguredEmptyError, match="HUMAN_REVIEW_URL"):
        Settings.load()


def test_routing_stated_off_under_gcp_needs_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    _managed(monkeypatch)
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "false")
    assert Settings.load().controls.review_routing is False


def test_routing_on_under_gcp_with_a_console_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    _managed(monkeypatch)
    monkeypatch.setenv("HUMAN_REVIEW_URL", "https://review.example.test")
    assert Settings.load().review_url == "https://review.example.test"


# --------------------------------------------------------------------------- #
# The four routing outcomes
# --------------------------------------------------------------------------- #
class _Accepting:
    def route(self, result: object, *, maker: str, tenant: str = "") -> str:
        return "review-1"


class _Refusing:
    def route(self, result: object, *, maker: str, tenant: str = "") -> str:
        raise ConnectionError("console unreachable")


def test_routing_outcomes_take_each_of_their_four_values() -> None:
    escalated = _result(requires_human_review=True)
    quiet = _result(requires_human_review=False)

    not_required = RecordingReviewRouter(_Accepting())
    assert not_required.route(quiet, maker="m") == ""
    assert not_required.outcome is ReviewRouting.NOT_REQUIRED

    routed = RecordingReviewRouter(_Accepting())
    assert routed.route(escalated, maker="m") == "review-1"
    assert routed.outcome is ReviewRouting.ROUTED

    off = RecordingReviewRouter(DisabledReviewRouter(Settings()))
    assert off.route(escalated, maker="m") == ""
    assert off.outcome is ReviewRouting.OFF

    failed = RecordingReviewRouter(_Refusing())
    assert failed.route(escalated, maker="m") == ""
    assert failed.outcome is ReviewRouting.FAILED


def test_a_failed_hand_off_is_reported_and_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = RecordingReviewRouter(_Refusing())
    with caplog.at_level(logging.WARNING, logger="app_fraud_interdiction.adapters.controls"):
        assert failed.route(_result(requires_human_review=True), maker="m") == ""
    assert failed.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


# --------------------------------------------------------------------------- #
# Every caller reports it
# --------------------------------------------------------------------------- #
def _call(body: dict[str, Any]) -> dict[str, Any]:
    response = TestClient(app, client=_LOOPBACK).post(_PATH, json=body, headers=_HEADERS)
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_the_api_reports_a_routed_hand_off() -> None:
    body = _call(_ESCALATING)
    assert body["review_routing"] == "routed"
    assert body["review_ref"]


def test_the_api_reports_nothing_to_route() -> None:
    body = _call(_ROUTINE)
    assert body["review_routing"] == "not_required"
    assert body["review_ref"] == ""


def test_the_api_reports_routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    body = _call(_ESCALATING)
    assert body["review_routing"] == "off"
    assert body["review_ref"] == ""


def test_the_api_reports_a_failed_hand_off_instead_of_failing_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_LOCAL_ROUTER, _Refusing.route)
    body = _call(_ESCALATING)
    assert body["review_routing"] == "failed"
    assert body["review_ref"] == ""


def test_the_agent_tool_reports_the_hand_off() -> None:
    payload = tools.assess_payment(
        event_id="sg-block-agent-rcs",
        market="SG",
        payer_ref="payer-coached",
        payee_ref="sg-mule-2d",
        amount_minor=600000,
        call_ref="call-scam-sg",
        tenant="demo-bank",
    )
    assert payload["review_routing"] == "routed"


def test_the_agent_tool_reports_a_failed_hand_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_LOCAL_ROUTER, _Refusing.route)
    payload = tools.assess_payment(
        event_id="sg-block-agent-rcs",
        market="SG",
        payer_ref="payer-coached",
        payee_ref="sg-mule-2d",
        amount_minor=600000,
        call_ref="call-scam-sg",
        tenant="demo-bank",
    )
    assert payload["review_routing"] == "failed"
    assert payload["review_ref"] == ""


def test_the_cli_reports_the_hand_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert (
        cli.main(
            [
                "interdict",
                "sg-block-cli-rcs",
                "SG",
                "payer-coached",
                "sg-mule-2d",
                "600000",
                "--call-ref",
                "call-scam-sg",
            ]
        )
        == 0
    )
    assert "human review hand-off : off" in capsys.readouterr().out
