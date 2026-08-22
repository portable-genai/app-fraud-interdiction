"""On-prem FeaturePort: fail-fast portability placeholder (the sovereign-exit proof)."""

from __future__ import annotations

from ...config import Settings
from ...domain.models import FeatureVector, PaymentEvent


class OnPremFeatureStore:
    """Satisfies FeaturePort but refuses: the client wires its own feature store."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def features_for(self, event: PaymentEvent) -> FeatureVector:
        raise NotImplementedError(
            "on-prem feature enrichment is a portability placeholder: bind the client's own "
            "feature store (see docs/onprem-migration.md)"
        )
