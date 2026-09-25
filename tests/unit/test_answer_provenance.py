"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

Here the one model seam is the warning generator. Under ``local`` it is a deterministic stub that
notes its own name, so an interdiction names the stub, and a warning generator that FAILED (the
deterministic fallback shipped instead) names nothing. No adapter here attaches an online search
tool, so the Search half is proved by standing a generator that notes one in for the stub.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

from app_fraud_interdiction import config
from app_fraud_interdiction.adapters.local import warning_generator as local_generator
from app_fraud_interdiction.domain.warning import WarningRequest

from tests import REPO_ROOT

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"

_BODY = {
    "event_id": "sg-block-pills",
    "market": "SG",
    "payer_ref": "payer-coached",
    "payee_ref": "sg-mule-2d",
    "amount_minor": 600000,
    "currency": "SGD",
    "call_ref": "call-scam-sg",
}


def _interdict(api_client: TestClient) -> tuple[dict[str, str], dict[str, object]]:
    response = api_client.post("/v1/interdict", json=_BODY, headers={"X-Dev-Persona": "analyst"})
    assert response.status_code == 200, response.text
    return dict(response.headers), response.json()


def test_an_interdiction_names_the_model_the_bound_generator_is(api_client: TestClient) -> None:
    """Under ``local`` the stub drafted the warning, so the pill names the stub, not a model."""
    headers, body = _interdict(api_client)
    assert body["warning_source"] != "fallback", "the stub's draft should have been used"
    assert headers[ANSWERED_BY] == local_generator.STUB_MODEL
    assert SEARCH_USED not in headers
    # The configured pill and the answered pill name the same thing: what the binding calls.
    assert config.Settings.load().generator_model == headers[ANSWERED_BY]


def test_a_failed_draft_names_no_model(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deterministic fallback shipped, so no model answered and no header claims one did."""

    def refuse(self: object, request: WarningRequest) -> str:
        raise RuntimeError("model unreachable")

    monkeypatch.setattr(local_generator.LocalWarningGenerator, "draft", refuse)
    headers, body = _interdict(api_client)
    assert body["warning_source"] == "fallback"
    assert ANSWERED_BY not in headers
    assert SEARCH_USED not in headers


def test_a_generator_that_searched_says_so_and_it_does_not_leak(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = local_generator.LocalWarningGenerator.draft

    def searching(self: local_generator.LocalWarningGenerator, request: WarningRequest) -> str:
        provenance.note_search()  # what an adapter that attached a search tool notes
        return original(self, request)

    monkeypatch.setattr(local_generator.LocalWarningGenerator, "draft", searching)
    headers, _ = _interdict(api_client)
    assert headers[ANSWERED_BY] == local_generator.STUB_MODEL
    assert headers[SEARCH_USED] == "true"
    # The next request is a fresh record: a search never leaks into a later response.
    monkeypatch.setattr(local_generator.LocalWarningGenerator, "draft", original)
    headers, _ = _interdict(api_client)
    assert SEARCH_USED not in headers


def test_the_warning_draft_pins_no_temperature() -> None:
    """Drafting a customer warning is narration, so it samples freely: nothing pins it to 0.0.

    The draft is judged afterwards (``validate_warning``) rather than compared, so determinism
    buys nothing here, and some models reject the parameter outright, so "free" means absent.
    """
    assert "temperature" not in WarningRequest.__dataclass_fields__


def test_generator_model_is_the_setting_the_adapter_reads_and_no_flag_swaps_it() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered.

    A resolver once named ``models.hard_reasoning`` when ``models.use_hard_reasoning`` was set,
    while a managed adapter called ``request.model or models.reasoning`` and never read the flag.
    The pill then named a model that never answered. The flag is gone; a stray one in a settings
    object must change nothing.
    """
    models = SimpleNamespace(
        reasoning="the-model-the-adapter-calls",
        hard_reasoning="a-model-nobody-calls",
        use_hard_reasoning=True,
    )
    named = config._model_from_settings(SimpleNamespace(models=models), "models.reasoning")
    assert named == "the-model-the-adapter-calls"


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    settings_file = (REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "use_hard_reasoning" not in settings_file
    for source in sorted((REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
