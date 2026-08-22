"""API surface: verified-principal identity, fail-closed S2S, security headers.

The client comes from the shared ``api_client`` fixture, which pins a loopback peer: the
app-object exposure guard refuses the unauthenticated local posture to any other peer, and
TestClient's default peer is the literal host "testclient".
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

_TOKEN_ENV = "SCAMINTERDICT_S2S_TOKEN"

_BLOCK_BODY = {
    "event_id": "sg-block-api",
    "market": "SG",
    "payer_ref": "payer-coached",
    "payee_ref": "sg-mule-2d",
    "amount_minor": 600000,
    "currency": "SGD",
    "call_ref": "call-scam-sg",
}
_ALLOW_BODY = {
    "event_id": "sg-allow-api",
    "market": "SG",
    "payer_ref": "payer-calm",
    "payee_ref": "sg-established",
    "amount_minor": 20000,
    "currency": "SGD",
}


def test_interdict_uses_the_verified_principal_as_actor(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/interdict",
        json=_BLOCK_BODY,
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "block"
    assert body["band"] == "critical"
    assert body["requires_human_review"] is True
    # Rule R8: the escalation was routed, not merely flagged (see test_review_routing.py).
    assert body["review_ref"]


def test_the_deterministic_score_arithmetic_is_returned(api_client: TestClient) -> None:
    body = api_client.post(
        "/v1/interdict", json=_BLOCK_BODY, headers={"X-Dev-Persona": "auditor"}
    ).json()
    uplift_sum = sum(reason["uplift"] for reason in body["reason_codes"])
    assert body["score"] == min(100, uplift_sum)
    assert body["reason_codes"], "a block must return the rules that drove it"


def test_a_linked_call_of_another_tenant_is_not_readable(api_client: TestClient) -> None:
    """Object-level authorization: naming a call reference is not entitlement to the recording.

    `ConversationChannelPort.fetch` took a client-supplied `call_ref` and no principal, so any
    authenticated caller could point their own payment at any stored call. The transcript is a
    diarized recording of somebody else's customer talking to a scammer, and the scam-cue count
    it yields comes straight back on the response as a score and an `SG-SCAM-CALL-CUES` reason
    code: a content oracle over another bank's recording, one query at a time.

    The verified principal `other-tenant` belongs to `other-bank`, and the fixture calls belong
    to `demo-bank`. The assessment still runs and still bands the payment, because refusing the
    enrichment is not refusing the request; what must not happen is the foreign call being read.
    """
    body = {**_BLOCK_BODY, "event_id": "sg-block-foreign-call"}
    own = api_client.post("/v1/interdict", json=body, headers={"X-Dev-Persona": "analyst"})
    other = api_client.post("/v1/interdict", json=body, headers={"X-Dev-Persona": "other-tenant"})
    assert own.status_code == 200 and other.status_code == 200
    own_reasons = {r["code"] for r in own.json()["reason_codes"]}
    other_reasons = {r["code"] for r in other.json()["reason_codes"]}
    assert "SG-SCAM-CALL-CUES" in own_reasons, "the owning tenant must still get the enrichment"
    assert "SG-SCAM-CALL-CUES" not in other_reasons, (
        f"a foreign tenant read the linked call: {sorted(other_reasons)}"
    )


def test_unknown_persona_is_401(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/interdict",
        json=_ALLOW_BODY,
        headers={"X-Dev-Persona": "ghost"},
    )
    assert resp.status_code == 401


def test_healthz_reports_profile_and_region(api_client: TestClient) -> None:
    body = api_client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["profile"] == "local"
    assert body["region"] == "asia-southeast1"


def test_security_headers_present(api_client: TestClient) -> None:
    headers = api_client.get("/healthz").headers
    assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.fixture()
def token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-service-token")
    yield "s3cret-service-token"


def test_s2s_endpoint_open_when_secret_unset(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    assert api_client.post("/v1/audit/ping").status_code == 200


def test_s2s_endpoint_rejects_missing_token_when_enforced(
    api_client: TestClient, token_env: str
) -> None:
    assert api_client.post("/v1/audit/ping").status_code == 401


def test_s2s_endpoint_accepts_correct_token(api_client: TestClient, token_env: str) -> None:
    resp = api_client.post("/v1/audit/ping", headers={"Authorization": f"Bearer {token_env}"})
    assert resp.status_code == 200
