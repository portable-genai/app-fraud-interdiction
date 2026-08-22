"""Local FeaturePort: a deterministic, SDK-free feature store for the offline profile.

Derives the engine's features from the payment event and the shared synthetic risk profiles
(``_fixture_data``). Every value carries a citation, and the same event always yields the same
vector, so the whole pipeline replays byte-identically. An unknown payer or payee falls back to a
calm default rather than raising: a feature store that refused an unseen party would make the
service unusable on any real (unfixtured) event.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.kernel import Citation
from ...domain.models import FeatureValue, FeatureVector, PaymentEvent
from . import _fixture_data


def _feature(key: str, value: float, snippet: str) -> FeatureValue:
    return FeatureValue(
        key=key,
        value=value,
        citation=Citation(
            source_id=f"feature-store:{key}", title="Streaming feature", snippet=snippet
        ),
    )


class LocalFeatureStore:
    """Compute cited features deterministically from the event and the synthetic profiles."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def features_for(self, event: PaymentEvent) -> FeatureVector:
        new_payee, payee_age_days = _fixture_data.payee_profile(event.payee_ref)
        velocity_24h, device_change = _fixture_data.payer_profile(event.payer_ref)
        amount_major = event.amount_minor / 100.0
        values = (
            _feature("amount_major", amount_major, f"{amount_major:g} {event.currency}"),
            _feature("device_change", device_change, "newly seen authorising device"),
            _feature("new_payee", new_payee, "first payment to this payee"),
            _feature("payee_age_days", payee_age_days, "payee account age in days"),
            _feature("velocity_24h", velocity_24h, "outbound payments in the last 24h"),
        )
        return FeatureVector(values=tuple(sorted(values, key=lambda feature: feature.key)))
