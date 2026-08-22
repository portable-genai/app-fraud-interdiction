"""Managed FeaturePort: derive features from BigQuery / Vertex feature store (lazy SDK import)."""

from __future__ import annotations

from ...config import Settings
from ...domain.models import FeatureVector, PaymentEvent


class VertexFeatureStore:
    """Fetch streaming features for a payment from the managed feature store (managed profile)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def features_for(self, event: PaymentEvent) -> FeatureVector:
        from google.cloud import bigquery  # noqa: F401  (lazy: proves managed reachability)

        raise NotImplementedError(  # pragma: no cover - needs a live feature store
            "VertexFeatureStore needs a configured feature store; see docs/runbook.md"
        )
