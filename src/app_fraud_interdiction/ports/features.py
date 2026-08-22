"""FeaturePort: the streaming-feature edge that enriches one payment before it is scored.

Given a payment event, an adapter returns the derived features the engine thresholds (payee age,
new-payee flag, velocity, device change, and so on), each carrying the source it was derived
from. The port returns raw cited signals and decides nothing: the verdict is the engine's, so a
feature store swap can never move a decision on its own.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import FeatureVector, PaymentEvent


@runtime_checkable
class FeaturePort(Protocol):
    def features_for(self, event: PaymentEvent) -> FeatureVector:
        """Return the cited feature vector for ``event``. Never computes a score or a verdict."""
        ...
